/*
 * The headphone check (type: headphone_check), run on a runtime phase page.
 *
 * The server makes each trial's three sounds as one WAV and keeps the answer
 * to itself (adapters/headphone_check.py), so this page never knows which
 * interval is the target:
 *
 * - antiphase (Woods et al., 2017): three 1 s, 200 Hz tones. One is 6 dB
 *   quieter (the answer); one is in antiphase (left = -right), which over
 *   loudspeakers partly cancels and sounds quietest.
 * - huggins (Milne et al., 2021): three 1 s noise bursts. In one (the answer)
 *   the right channel has a narrow band around 600 Hz inverted, heard over
 *   headphones as a faint tone in the noise.
 *
 * Each trial records which sound the participant chose; the server scores
 * it. Only the calibration noise is made here, with Web Audio.
 */
(function () {
    'use strict';
    var rt = window.potatoRuntime;
    if (!rt) { return; }
    var cfg = rt.config;
    var opts = cfg.runtime || {};
    var target = document.getElementById('runtime-target');
    var ctx = null;
    var trials = [];
    var plan = [];
    var index = 0;
    var playing = false;

    function el(tag, attrs, kids) {
        var n = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (k === 'text') { n.textContent = attrs[k]; }
            else if (k === 'className') { n.className = attrs[k]; }
            else if (k.indexOf('on') === 0) { n.addEventListener(k.slice(2), attrs[k]); }
            else { n.setAttribute(k, attrs[k]); }
        });
        (kids || []).forEach(function (c) { n.appendChild(c); });
        return n;
    }

    function ramp(i, n, rate) {
        var r = Math.floor(0.1 * rate);
        if (i < r) { return 0.5 - 0.5 * Math.cos(Math.PI * i / r); }
        if (i > n - r) { return 0.5 - 0.5 * Math.cos(Math.PI * (n - i) / r); }
        return 1;
    }

    function calibrationNoise() {
        var rate = ctx.sampleRate, n = rate, buf = ctx.createBuffer(2, n, rate);
        var L = buf.getChannelData(0), R = buf.getChannelData(1);
        for (var i = 0; i < n; i++) { L[i] = R[i] = (Math.random() * 2 - 1) * 0.25 * ramp(i, n, rate); }
        return buf;
    }

    function makePlan() {
        var tests = opts.test === 'both' ? ['huggins', 'antiphase'] : [opts.test || 'huggins'];
        tests.forEach(function (test) {
            for (var t = 0; t < (opts.trials || 6); t++) {
                plan.push({test: test, trial: t + 1, index: plan.length});
            }
        });
    }

    function loadSounds(p) {
        return fetch(opts.stimulus + p.index + '.wav', {credentials: 'same-origin', cache: 'no-store'})
            .then(function (r) {
                if (!r.ok) { throw new Error('the server did not send the sounds (' + r.status + ')'); }
                return r.arrayBuffer();
            })
            .then(function (bytes) {
                return new Promise(function (resolve, reject) {
                    ctx.decodeAudioData(bytes, resolve, reject);
                });
            });
    }

    function playSequence(buffer, buttons) {
        playing = true;
        var spacing = opts.spacing_s || 1.5, length = opts.interval_s || 1;
        var t0 = ctx.currentTime + 0.2;
        var s = ctx.createBufferSource();
        s.buffer = buffer;
        s.connect(ctx.destination);
        s.start(t0);
        buttons.forEach(function (b, i) {
            var start = t0 + i * spacing;
            setTimeout(function () { b.classList.add('hc-active'); }, (start - ctx.currentTime) * 1000);
            setTimeout(function () { b.classList.remove('hc-active'); },
                       (start + length - ctx.currentTime) * 1000);
        });
        return new Promise(function (resolve) {
            setTimeout(function () { playing = false; resolve(); },
                       (t0 + buffer.duration - ctx.currentTime) * 1000 + 100);
        });
    }

    function show(nodes) {
        target.innerHTML = '';
        var box = el('div', {className: 'hc-box'}, nodes);
        target.appendChild(box);
        var focus = box.querySelector('button:not([disabled])');
        if (focus) { focus.focus(); }
    }

    function intro() {
        show([
            el('h1', {text: 'Headphone check'}),
            el('p', {text: 'Put on headphones (not speakers) and sit somewhere quiet. ' +
                           'Play the sound below and set your volume so it is comfortable.'}),
            el('button', {type: 'button', className: 'hc-btn', text: 'Play calibration sound',
                onclick: function () {
                    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
                    if (ctx.state === 'suspended') { ctx.resume(); }
                    var s = ctx.createBufferSource();
                    s.buffer = calibrationNoise(); s.connect(ctx.destination); s.start();
                }}),
            el('button', {type: 'button', className: 'hc-btn hc-primary', text: 'Start the check',
                onclick: function () {
                    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
                    if (ctx.state === 'suspended') { ctx.resume(); }
                    trial();
                }})
        ]);
    }

    function trial() {
        if (index >= plan.length) {
            rt.finish(trials, []);
            return;
        }
        var p = plan[index];
        var question = p.test === 'antiphase' ? 'Which sound was the quietest?'
            : 'Which sound had a faint tone hidden in the noise?';
        var buttons = [1, 2, 3].map(function (i) {
            return el('button', {type: 'button', className: 'hc-btn hc-choice', disabled: 'disabled',
                text: String(i), 'aria-label': 'Sound ' + i,
                onclick: function () {
                    if (playing) { return; }
                    var row = {index: p.index, test: p.test, trial: p.trial, response: i};
                    Object.assign(row, rt.properties);
                    trials.push(row);
                    rt.trial(row);
                    index += 1;
                    trial();
                }});
        });
        var play = el('button', {type: 'button', className: 'hc-btn hc-primary', text: 'Play the three sounds',
            onclick: function () {
                play.disabled = true;
                loadSounds(p).then(function (buf) { return playSequence(buf, buttons); }).then(function () {
                    buttons.forEach(function (b) { b.removeAttribute('disabled'); });
                    buttons[0].focus();
                }, function (err) {
                    rt.fail(String(err && err.message || err));
                });
            }});
        show([
            el('p', {className: 'hc-progress', text: 'Sound set ' + (index + 1) + ' of ' + plan.length}),
            el('h2', {text: question}),
            el('p', {text: 'You will hear three sounds once. Then choose one.'}),
            play,
            el('div', {className: 'hc-choices', role: 'group', 'aria-label': question}, buttons)
        ]);
    }

    rt.onCollect(function () { return [trials, []]; });
    rt.onStart(function () {
        if (!(window.AudioContext || window.webkitAudioContext) || !window.fetch) {
            rt.fail('this browser cannot play the check (no Web Audio support).');
            return;
        }
        makePlan();
        intro();
    });
})();

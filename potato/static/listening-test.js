/*
 * Listening tests: MUSHRA, BS.1116, ACR, DCR, CCR, ABX and P.835
 * (annotation_type: listening_test).
 *
 * The page knows slot names ("s1", "A", "X", "ref") and opaque audio URLs
 * only; which slot is which condition stays on the server (see
 * potato/listening/plan.py). Every stimulus is decoded into one Web Audio
 * context, so switching from one sample to another continues at the same
 * position, which is what lets a listener compare short passages in a MUSHRA
 * or BS.1116 trial.
 *
 * Answers go in the scheme's hidden input as JSON and are restored from it.
 * Completeness ("play every sample", "rate one sample 100") is declared on
 * the form's data-incomplete-reason, which validateRequiredFields reads.
 */
(function () {
    'use strict';
    if (window.PotatoListeningTest) { return; }

    var STATES = new WeakMap();
    var ctxSingleton = null;

    function audioContext() {
        if (!ctxSingleton) {
            var Ctx = window.AudioContext || window.webkitAudioContext;
            ctxSingleton = Ctx ? new Ctx() : null;
        }
        return ctxSingleton;
    }

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (k === 'text') { node.textContent = attrs[k]; }
            else if (k === 'className') { node.className = attrs[k]; }
            else if (k.indexOf('on') === 0) { node.addEventListener(k.slice(2), attrs[k]); }
            else { node.setAttribute(k, attrs[k]); }
        });
        (children || []).forEach(function (c) { if (c) { node.appendChild(c); } });
        return node;
    }

    function slotLabel(slot) {
        if (slot === 'ref') { return 'Reference'; }
        if (/^s\d+$/.test(slot)) { return 'Sample ' + slot.slice(1); }
        return slot;
    }

    // ------------------------------------------------------------------
    // Player
    // ------------------------------------------------------------------

    function Player(ctx, buffers, onTick, onChange) {
        this.ctx = ctx;
        this.buffers = buffers;       // slot -> AudioBuffer
        this.current = null;
        this.source = null;
        this.gain = null;
        this.startedAt = 0;
        this.offset = 0;
        this.loopOn = false;
        this.loopStart = 0;
        this.loopEnd = 0;
        this.onTick = onTick;
        // Called when what has been heard changes (a sample ended, a pause),
        // so the answer and its completeness are saved.
        this.onChange = onChange || function () {};
        this.listened = {};           // slot -> seconds heard
        this.completed = {};          // slot -> true once played to the end
        this._raf = null;
        this._lastTick = null;
    }

    Player.prototype.duration = function (slot) {
        var b = this.buffers[slot || this.current];
        return b ? b.duration : 0;
    };

    Player.prototype.position = function () {
        if (!this.source) { return this.offset; }
        var t = this.ctx.currentTime - this.startedAt;
        var dur = this.duration();
        if (this.loopOn && this.loopEnd > this.loopStart) {
            var len = this.loopEnd - this.loopStart;
            if (t > this.loopEnd) { t = this.loopStart + ((t - this.loopStart) % len); }
            return t;
        }
        return Math.min(t, dur);
    };

    Player.prototype.play = function (slot) {
        var self = this;
        if (this.ctx.state === 'suspended') { this.ctx.resume(); }
        var pos = this.source ? this.position() : this.offset;
        var buffer = this.buffers[slot];
        if (!buffer) { return; }
        if (pos >= buffer.duration - 0.01) { pos = this.loopOn ? this.loopStart : 0; }
        this._stopSource(true);
        var gain = this.ctx.createGain();
        gain.gain.setValueAtTime(0, this.ctx.currentTime);
        gain.gain.linearRampToValueAtTime(1, this.ctx.currentTime + 0.005);
        gain.connect(this.ctx.destination);
        var src = this.ctx.createBufferSource();
        src.buffer = buffer;
        if (this.loopOn && this.loopEnd > this.loopStart) {
            src.loop = true;
            src.loopStart = this.loopStart;
            src.loopEnd = Math.min(this.loopEnd, buffer.duration);
            if (pos < this.loopStart || pos > this.loopEnd) { pos = this.loopStart; }
        }
        src.connect(gain);
        src.onended = function () {
            if (self.source !== src) { return; }
            // Ended by itself: the whole stimulus was heard.
            self._account();
            self.completed[slot] = true;
            self.source = null;
            self.offset = 0;
            self._stopTicking();
            self.onTick();
            self.onChange();
        };
        src.start(0, pos);
        this.source = src;
        this.gain = gain;
        this.current = slot;
        this.startedAt = this.ctx.currentTime - pos;
        this._lastTick = this.ctx.currentTime;
        this._startTicking();
        this.onTick();
    };

    /* Add the time since the last tick to what the current slot was heard
       for. Called per frame and on every pause, switch and end, so a tab in
       the background (no animation frames) still counts what played. */
    Player.prototype._account = function () {
        var now = this.ctx.currentTime;
        if (this.current && this.source && this._lastTick !== null) {
            this.listened[this.current] = (this.listened[this.current] || 0) + (now - this._lastTick);
            if (!this.loopOn && this.position() >= this.duration() - 0.05) {
                this.completed[this.current] = true;
            }
        }
        this._lastTick = now;
    };

    Player.prototype._stopSource = function (fade) {
        if (!this.source) { return; }
        this._account();
        var src = this.source, gain = this.gain, now = this.ctx.currentTime;
        this.source = null;
        this.onChange();
        try {
            if (fade) {
                gain.gain.setValueAtTime(gain.gain.value, now);
                gain.gain.linearRampToValueAtTime(0, now + 0.005);
                src.stop(now + 0.006);
            } else {
                src.stop();
            }
        } catch (e) { /* already stopped */ }
    };

    Player.prototype.pause = function () {
        if (!this.source) { return; }
        this.offset = this.position();
        this._stopSource(true);
        this._stopTicking();
        this.onTick();
    };

    Player.prototype.stop = function () {
        this._stopSource(true);
        this.offset = this.loopOn ? this.loopStart : 0;
        this._stopTicking();
        this.onTick();
    };

    Player.prototype.seek = function (seconds) {
        var playing = !!this.source, slot = this.current;
        this._stopSource(false);
        this.offset = Math.max(0, seconds);
        if (playing && slot) { this.play(slot); } else { this.onTick(); }
    };

    Player.prototype._startTicking = function () {
        var self = this;
        if (this._raf) { return; }
        var step = function () {
            if (!self.source) { self._raf = null; return; }
            var wasComplete = !!self.completed[self.current];
            self._account();
            self.onTick();
            if (!wasComplete && self.completed[self.current]) { self.onChange(); }
            self._raf = requestAnimationFrame(step);
        };
        this._raf = requestAnimationFrame(step);
    };

    Player.prototype._stopTicking = function () {
        if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
    };

    Player.prototype.heard = function (slot) {
        var d = this.duration(slot);
        return !!this.completed[slot] || (this.listened[slot] || 0) >= Math.min(2, d * 0.5);
    };

    // ------------------------------------------------------------------
    // One widget
    // ------------------------------------------------------------------

    function instanceId() {
        var input = document.getElementById('instance_id');
        return input ? input.value : '';
    }

    function readStored(form) {
        var h = form.querySelector('.listening-test-input');
        if (h && h.value) {
            try { return JSON.parse(h.value) || {}; } catch (e) { return {}; }
        }
        return {};
    }

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { return; }
        if (prior && prior.player) { prior.player.stop(); }
        var root = form.querySelector('.lt-root');
        var cfg = JSON.parse(form.getAttribute('data-listening-config') || '{}');
        var state = {instance: instanceId(), cfg: cfg, form: form, root: root,
                     answer: readStored(form), player: null, view: null};
        STATES.set(form, state);
        var ctx = audioContext();
        if (!ctx) {
            root.innerHTML = '';
            root.appendChild(el('p', {className: 'lt-error', role: 'alert',
                text: 'This browser cannot play the listening test (no Web Audio support).'}));
            return;
        }
        var url = '/api/listening/plan?schema=' + encodeURIComponent(cfg.schema) +
                  '&instance_id=' + encodeURIComponent(state.instance);
        fetch(url, {credentials: 'same-origin'}).then(function (r) {
            if (!r.ok) { throw new Error('plan ' + r.status); }
            return r.json();
        }).then(function (view) {
            state.view = view;
            var entries = view.slots.map(function (s) { return [s.slot, s.url]; });
            if (view.reference) { entries.unshift(['ref', view.reference]); }
            return Promise.all(entries.map(function (pair) {
                return fetch(pair[1], {credentials: 'same-origin'}).then(function (r) {
                    if (!r.ok) { throw new Error(pair[0] + ' ' + r.status); }
                    return r.arrayBuffer();
                }).then(function (buf) {
                    return new Promise(function (resolve, reject) {
                        ctx.decodeAudioData(buf, resolve, reject);
                    });
                }).then(function (decoded) { return [pair[0], decoded]; });
            }));
        }).then(function (decoded) {
            if (STATES.get(form) !== state) { return; }
            var buffers = {};
            decoded.forEach(function (pair) { buffers[pair[0]] = pair[1]; });
            state.player = new Player(ctx, buffers, function () { refresh(state); },
                                      function () { save(state); refresh(state); });
            (state.answer.played || []).forEach(function (slot) {
                state.player.completed[slot] = true;
            });
            render(state);
        }).catch(function (err) {
            console.error('[listening-test]', err);
            root.innerHTML = '';
            root.appendChild(el('p', {className: 'lt-error', role: 'alert',
                text: 'The audio for this item could not be loaded. Reload the page; if it ' +
                      'happens again, tell the researcher.'}));
        });
    }

    function played(state) {
        var p = state.player, out = [];
        Object.keys(p.buffers).forEach(function (slot) { if (p.heard(slot)) { out.push(slot); } });
        return out;
    }

    function save(state) {
        var h = state.form.querySelector('.listening-test-input');
        var data = Object.assign({}, state.answer, {played: played(state)});
        state.answer = data;
        var hasAnswer = Object.keys(data).some(function (k) { return k !== 'played'; });
        h.value = hasAnswer ? JSON.stringify(data) : '';
        h.setAttribute('data-modified', 'true');
        h.dispatchEvent(new Event('change', {bubbles: true}));
        declare(state);
    }

    function declare(state) {
        var v = state.view, a = state.answer, p = state.player, reasons = [];
        if (!v || !p) { return; }
        var slots = v.slots.map(function (s) { return s.slot; });
        var mustHear = v.require_full_playback ? slots.filter(function (s) { return !p.completed[s]; })
            : (v.require_all_played ? slots.filter(function (s) { return !p.heard(s); }) : []);
        if (mustHear.length) {
            reasons.push((v.require_full_playback ? 'play to the end: ' : 'listen to: ') +
                         mustHear.map(slotLabel).join(', '));
        }
        var m = v.method;
        if (m === 'mushra' || m === 'bs1116') {
            var r = a.ratings || {};
            var unrated = slots.filter(function (s) { return r[s] === undefined; });
            if (unrated.length) { reasons.push('rate ' + unrated.map(slotLabel).join(', ')); }
            if (m === 'mushra' && v.require_one_at_100 && !unrated.length &&
                    !slots.some(function (s) { return Number(r[s]) === 100; })) {
                reasons.push('rate at least one sample 100 (the hidden reference)');
            }
        } else if (m === 'p835') {
            ['sig', 'bak', 'ovrl'].forEach(function (k) {
                if (a[k] === undefined) { reasons.push('answer ' + k.toUpperCase()); }
            });
        } else if (m === 'abx') {
            if (!a.choice) { reasons.push('choose A or B'); }
        } else if (a.rating === undefined) {
            reasons.push('choose a rating');
        }
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
    }

    // ------------------------------------------------------------------
    // Rendering
    // ------------------------------------------------------------------

    function playButton(state, slot, label) {
        return el('button', {type: 'button', className: 'lt-play', 'data-slot': slot,
            'aria-pressed': 'false', text: label || slotLabel(slot),
            onclick: function () {
                var p = state.player;
                if (p.source && p.current === slot) { p.pause(); }
                else { p.play(slot); }
                save(state);
            }});
    }

    function transport(state) {
        var p = state.player, v = state.view;
        var bar = el('input', {type: 'range', className: 'lt-position', min: '0', step: '0.01',
            'aria-label': 'Playback position (seconds)',
            oninput: function () { p.seek(parseFloat(this.value)); }});
        var time = el('span', {className: 'lt-time', 'aria-live': 'off'});
        var stop = el('button', {type: 'button', className: 'lt-stop', text: 'Stop',
            onclick: function () { p.stop(); }});
        var row = el('div', {className: 'lt-transport'}, [stop, bar, time]);
        state.posBar = bar;
        state.timeLabel = time;
        if (v.loop) {
            var maxDur = Math.max.apply(null, Object.keys(p.buffers).map(function (k) { return p.buffers[k].duration; }));
            p.loopStart = 0;
            p.loopEnd = maxDur;
            var on = el('input', {type: 'checkbox', className: 'lt-loop-on', id: state.cfg.schema + '-loop',
                onchange: function () { p.loopOn = this.checked; if (p.source) { p.play(p.current); } }});
            var from = el('input', {type: 'number', className: 'lt-loop-from', min: '0', step: '0.1',
                value: '0', 'aria-label': 'Loop start (seconds)',
                onchange: function () { p.loopStart = Math.max(0, parseFloat(this.value) || 0); }});
            var to = el('input', {type: 'number', className: 'lt-loop-to', min: '0', step: '0.1',
                value: maxDur.toFixed(1), 'aria-label': 'Loop end (seconds)',
                onchange: function () { p.loopEnd = Math.min(maxDur, parseFloat(this.value) || maxDur); }});
            row.appendChild(el('span', {className: 'lt-loop'}, [
                on, el('label', {'for': state.cfg.schema + '-loop', text: 'Loop'}),
                el('span', {text: ' from '}), from, el('span', {text: ' to '}), to, el('span', {text: ' s'})]));
        }
        return row;
    }

    function categoryGroup(state, key, labels, label, values) {
        var group = el('div', {className: 'lt-categories', role: 'radiogroup', 'aria-label': label});
        labels.forEach(function (text, i) {
            var b = el('button', {type: 'button', role: 'radio', className: 'lt-category',
                'data-key': key, 'data-index': String(i), text: text,
                onclick: function () {
                    if (this.disabled) { return; }
                    state.answer[key] = values ? values[i] : i;
                    save(state);
                    refresh(state);
                }});
            group.appendChild(b);
        });
        return group;
    }

    function ratingSlider(state, slot, min, max, step, labels) {
        var r = (state.answer.ratings || {});
        var value = r[slot] !== undefined ? r[slot] : (min + max) / 2;
        var out = el('output', {className: 'lt-value', text: r[slot] !== undefined ? String(r[slot]) : '–'});
        var input = el('input', {type: 'range', className: 'lt-slider', min: String(min), max: String(max),
            step: String(step), value: String(value), 'data-slot': slot,
            'aria-label': 'Rating for ' + slotLabel(slot) + ' (' + min + ' to ' + max + ')',
            oninput: function () {
                state.answer.ratings = state.answer.ratings || {};
                var v = step < 1 ? Math.round(parseFloat(this.value) * 10) / 10 : parseInt(this.value, 10);
                state.answer.ratings[slot] = v;
                out.textContent = String(v);
                this.classList.add('lt-rated');
                save(state);
            }});
        if (r[slot] !== undefined) { input.classList.add('lt-rated'); }
        var scale = el('div', {className: 'lt-scale', 'aria-hidden': 'true'});
        labels.slice().reverse().forEach(function (t) { scale.appendChild(el('span', {text: t})); });
        return el('div', {className: 'lt-row'}, [playButton(state, slot),
            el('div', {className: 'lt-slider-wrap'}, [scale, input]), out]);
    }

    function render(state) {
        var v = state.view, root = state.root;
        root.innerHTML = '';
        var m = v.method;
        if (v.reference && (m === 'mushra' || m === 'bs1116' || m === 'dcr')) {
            root.appendChild(el('div', {className: 'lt-reference'}, [playButton(state, 'ref', 'Reference')]));
        }
        if (m === 'mushra') {
            v.slots.forEach(function (s) { root.appendChild(ratingSlider(state, s.slot, 0, 100, 1, v.scale)); });
        } else if (m === 'bs1116') {
            v.slots.forEach(function (s) { root.appendChild(ratingSlider(state, s.slot, 1, 5, 0.1, v.scale)); });
        } else if (m === 'abx') {
            root.appendChild(el('div', {className: 'lt-buttons'}, v.slots.map(function (s) {
                return playButton(state, s.slot);
            })));
            root.appendChild(categoryGroup(state, 'choice', ['X is A', 'X is B'], 'Which sample is X?', ['A', 'B']));
        } else {
            root.appendChild(el('div', {className: 'lt-buttons'}, v.slots.map(function (s) {
                return playButton(state, s.slot, v.slots.length === 1 ? 'Play' : slotLabel(s.slot));
            })));
            if (m === 'p835') {
                var names = {sig: 'Speech signal', bak: 'Background', ovrl: 'Overall'};
                ['sig', 'bak', 'ovrl'].forEach(function (k) {
                    root.appendChild(el('p', {className: 'lt-question', text: names[k]}));
                    root.appendChild(categoryGroup(state, k, v.scales[k], names[k]));
                });
            } else {
                if (m === 'ccr') {
                    root.appendChild(el('p', {className: 'lt-question',
                        text: 'Compared with Sample 1, the quality of Sample 2 is:'}));
                }
                root.appendChild(categoryGroup(state, 'rating', v.scale, 'Rating'));
            }
        }
        root.appendChild(transport(state));
        if (v.require_full_playback && m !== 'mushra' && m !== 'bs1116') {
            root.insertBefore(el('p', {className: 'lt-gate', 'aria-live': 'polite',
                text: v.slots.length === 1 ? 'Play the sample to the end, then answer.'
                    : 'Play every sample to the end, then answer.'}), root.lastChild);
        }
        var keys = v.slots.length === 1 ? 'Keys: 1 plays the sample' : 'Keys: 1–' + v.slots.length + ' play a sample';
        if (v.reference) { keys += ', R the reference'; }
        root.appendChild(el('p', {className: 'lt-keys', text: keys + ', Space pauses.'}));
        refresh(state);
        declare(state);
    }

    function refresh(state) {
        var p = state.player, v = state.view, a = state.answer;
        if (!p || !v) { return; }
        state.root.querySelectorAll('.lt-play').forEach(function (b) {
            var slot = b.getAttribute('data-slot');
            var on = !!p.source && p.current === slot;
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
            b.classList.toggle('lt-heard', v.require_full_playback ? !!p.completed[slot] : p.heard(slot));
        });
        var gate = v.require_full_playback && v.slots.some(function (s) { return !p.completed[s.slot]; });
        var hint = state.root.querySelector('.lt-gate');
        if (hint) { hint.hidden = !gate; }
        state.root.querySelectorAll('.lt-category').forEach(function (b) {
            var key = b.getAttribute('data-key'), i = parseInt(b.getAttribute('data-index'), 10);
            var chosen = key === 'choice' ? a.choice === ['A', 'B'][i] : a[key] === i;
            b.setAttribute('aria-checked', chosen ? 'true' : 'false');
            b.disabled = gate && !chosen;
        });
        if (state.posBar) {
            var dur = p.duration() || p.duration(v.slots[0] && v.slots[0].slot) || 0;
            state.posBar.max = String(dur);
            state.posBar.value = String(p.position());
            state.timeLabel.textContent = p.position().toFixed(1) + ' / ' + dur.toFixed(1) + ' s' +
                (p.current ? ' · ' + slotLabel(p.current) : '');
        }
    }

    function onKey(e) {
        var form = e.target.closest && e.target.closest('.listening-test');
        if (!form) { return; }
        var state = STATES.get(form);
        if (!state || !state.player || e.target.tagName === 'INPUT') { return; }
        var slots = state.view.slots.map(function (s) { return s.slot; });
        var handled = false;
        if (/^[1-9]$/.test(e.key) && slots[parseInt(e.key, 10) - 1]) {
            state.player.play(slots[parseInt(e.key, 10) - 1]); handled = true;
        } else if ((e.key === 'r' || e.key === 'R') && state.player.buffers.ref) {
            state.player.play('ref'); handled = true;
        } else if (e.key === ' ') {
            if (state.player.source) { state.player.pause(); }
            else if (state.player.current) { state.player.play(state.player.current); }
            handled = true;
        }
        if (handled) {
            // Potato's own label shortcuts must not also fire.
            e.preventDefault();
            e.stopPropagation();
            save(state);
        }
    }

    function init() {
        document.querySelectorAll('form.listening-test').forEach(setup);
    }

    document.addEventListener('keydown', onKey, true);
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { init(); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoListeningTest = {init: init};
})();

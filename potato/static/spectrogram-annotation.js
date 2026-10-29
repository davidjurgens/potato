/*
 * Spectrogram box annotation (annotation_type: spectrogram_annotation).
 *
 * The page decodes the item's audio with Web Audio, computes a short-time
 * Fourier transform with one column per canvas pixel, and paints it. Boxes are
 * positioned in percentages of the spectrogram, so zooming only widens the
 * canvas and never has to move them.
 *
 * Mouse / touch: drag on empty spectrogram to draw a box with the active
 * label; drag a box to move it; drag a corner handle to resize; click empty
 * spectrogram to move the play position.
 * Keyboard (focus in the widget): 1-9 choose the label (and relabel the
 * selected box); arrows move the selected box, Shift+arrows resize it; N adds a
 * box at the play position; Delete removes; Escape deselects; Space plays or
 * pauses; P plays the selected box.
 *
 * The answer is the scheme's hidden .annotation-data-input as a JSON list of
 * {start_s, end_s, low_hz, high_hz, label}, restored from that input.
 */
(function () {
    'use strict';
    if (window.PotatoSpectrogram) { return; }

    var STATES = new WeakMap();
    var ctxSingleton = null;
    var MIN_DRAG_PX = 4;

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

    function instanceId() {
        var input = document.getElementById('instance_id');
        return input ? input.value : '';
    }

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    function fmtTime(s) { return (Math.round(s * 100) / 100).toFixed(2); }

    function fmtFreq(hz) {
        if (hz === null || hz === undefined) { return '–'; }
        return hz >= 1000 ? (Math.round(hz / 100) / 10).toFixed(1) + ' kHz' : Math.round(hz) + ' Hz';
    }

    // ------------------------------------------------------------------
    // Spectrogram
    // ------------------------------------------------------------------

    function fftTables(n) {
        var levels = Math.round(Math.log2(n));
        var rev = new Uint32Array(n);
        for (var i = 0; i < n; i++) {
            var x = i, r = 0;
            for (var b = 0; b < levels; b++) { r = (r << 1) | (x & 1); x >>= 1; }
            rev[i] = r;
        }
        var cos = new Float32Array(n / 2), sin = new Float32Array(n / 2);
        for (var k = 0; k < n / 2; k++) {
            cos[k] = Math.cos(2 * Math.PI * k / n);
            sin[k] = Math.sin(2 * Math.PI * k / n);
        }
        var win = new Float32Array(n);
        for (var w = 0; w < n; w++) { win[w] = 0.5 - 0.5 * Math.cos(2 * Math.PI * w / (n - 1)); }
        return {n: n, rev: rev, cos: cos, sin: sin, win: win};
    }

    function fft(t, re, im) {
        var n = t.n, i, j;
        for (i = 0; i < n; i++) {
            j = t.rev[i];
            if (j > i) {
                var tr = re[i]; re[i] = re[j]; re[j] = tr;
                var ti = im[i]; im[i] = im[j]; im[j] = ti;
            }
        }
        for (var size = 2; size <= n; size <<= 1) {
            var half = size >> 1, step = n / size;
            for (i = 0; i < n; i += size) {
                for (j = 0; j < half; j++) {
                    var k = j * step;
                    var a = i + j, b = a + half;
                    var xr = re[b] * t.cos[k] + im[b] * t.sin[k];
                    var xi = -re[b] * t.sin[k] + im[b] * t.cos[k];
                    re[b] = re[a] - xr; im[b] = im[a] - xi;
                    re[a] += xr; im[a] += xi;
                }
            }
        }
    }

    var MAPS = {
        viridis: [[68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142], [38, 130, 142],
                  [31, 158, 137], [53, 183, 121], [109, 205, 89], [180, 222, 44], [253, 231, 37]],
        magma: [[0, 0, 4], [28, 16, 68], [79, 18, 123], [129, 37, 129], [181, 54, 122],
                [229, 80, 100], [251, 135, 97], [254, 194, 135], [252, 253, 191]],
        grayscale: [[255, 255, 255], [0, 0, 0]]
    };

    function lut(name) {
        var stops = MAPS[name] || MAPS.viridis, out = new Uint8ClampedArray(256 * 3);
        for (var i = 0; i < 256; i++) {
            var pos = i / 255 * (stops.length - 1), lo = Math.floor(pos), hi = Math.min(lo + 1, stops.length - 1);
            var f = pos - lo;
            for (var c = 0; c < 3; c++) { out[i * 3 + c] = stops[lo][c] + (stops[hi][c] - stops[lo][c]) * f; }
        }
        return out;
    }

    function mono(buffer) {
        var n = buffer.length, out = new Float32Array(n), ch = buffer.numberOfChannels;
        for (var c = 0; c < ch; c++) {
            var data = buffer.getChannelData(c);
            for (var i = 0; i < n; i++) { out[i] += data[i] / ch; }
        }
        return out;
    }

    /* Paint the spectrogram of `buffer` between fmin and fmax onto `canvas`. */
    function paint(canvas, buffer, opts) {
        var t = fftTables(opts.fftSize), n = t.n;
        var samples = mono(buffer);
        var binHz = buffer.sampleRate / n;
        var b0 = Math.max(0, Math.floor(opts.fmin / binHz));
        var b1 = Math.min(n / 2, Math.ceil(opts.fmax / binHz));
        var rows = Math.max(1, b1 - b0);
        var cols = Math.max(200, Math.min(4096, Math.ceil(buffer.duration * 200)));
        var mags = new Float32Array(cols * rows), re = new Float32Array(n), im = new Float32Array(n);
        var max = -Infinity;
        for (var c = 0; c < cols; c++) {
            var centre = Math.floor((c + 0.5) / cols * samples.length), start = centre - n / 2;
            for (var i = 0; i < n; i++) {
                var s = start + i;
                re[i] = (s >= 0 && s < samples.length) ? samples[s] * t.win[i] : 0;
                im[i] = 0;
            }
            fft(t, re, im);
            for (var r = 0; r < rows; r++) {
                var b = b0 + r;
                var db = 10 * Math.log10(re[b] * re[b] + im[b] * im[b] + 1e-12);
                mags[c * rows + r] = db;
                if (db > max) { max = db; }
            }
        }
        canvas.width = cols;
        canvas.height = rows;
        var g = canvas.getContext('2d'), img = g.createImageData(cols, rows), px = img.data;
        // Map the noise floor (the median level) to the bottom of the colour
        // scale, so calls stand out instead of sitting in a bright haze.
        var sample = [], stride = Math.max(1, Math.floor(mags.length / 20000));
        for (var q = 0; q < mags.length; q += stride) { sample.push(mags[q]); }
        sample.sort(function (a, b) { return a - b; });
        var median = sample.length ? sample[Math.floor(sample.length / 2)] : max - 80;
        var colors = lut(opts.colormap), floor = Math.max(median, max - 90), range = Math.max(20, max - floor);
        for (var y = 0; y < rows; y++) {
            var row = rows - 1 - y;            // high frequencies at the top
            for (var x = 0; x < cols; x++) {
                var v = clamp((mags[x * rows + row] - floor) / range, 0, 1);
                var idx = Math.round(v * 255) * 3, o = (y * cols + x) * 4;
                px[o] = colors[idx]; px[o + 1] = colors[idx + 1]; px[o + 2] = colors[idx + 2]; px[o + 3] = 255;
            }
        }
        g.putImageData(img, 0, 0);
        // The band actually painted, so boxes line up with whole bins.
        return {fmin: b0 * binHz, fmax: b1 * binHz};
    }

    // ------------------------------------------------------------------
    // State helpers
    // ------------------------------------------------------------------

    var nextId = 1;

    function readStored(input) {
        if (!input || !input.value || input.getAttribute('data-server-set') !== 'true') { return []; }
        try {
            var parsed = JSON.parse(input.value);
            if (parsed && !Array.isArray(parsed) && Array.isArray(parsed.boxes)) { parsed = parsed.boxes; }
            return Array.isArray(parsed) ? parsed.filter(function (b) {
                return b && isFinite(parseFloat(b.start_s)) && isFinite(parseFloat(b.end_s));
            }).map(function (b) {
                var box = Object.assign({}, b);
                box.start_s = parseFloat(b.start_s); box.end_s = parseFloat(b.end_s);
                box.low_hz = (b.low_hz === null || b.low_hz === undefined || b.low_hz === '') ? null : parseFloat(b.low_hz);
                box.high_hz = (b.high_hz === null || b.high_hz === undefined || b.high_hz === '') ? null : parseFloat(b.high_hz);
                box.label = String(b.label || '');
                box._id = nextId++;
                return box;
            }) : [];
        } catch (e) { return []; }
    }

    function labelInfo(state, name) {
        for (var i = 0; i < state.cfg.labels.length; i++) {
            if (state.cfg.labels[i].name === name) { return state.cfg.labels[i]; }
        }
        return {name: name, color: '#64748b', key: ''};
    }

    function serialise(state) {
        return state.boxes.map(function (b) {
            var out = {};
            Object.keys(b).forEach(function (k) { if (k !== '_id') { out[k] = b[k]; } });
            ['start_s', 'end_s'].forEach(function (k) { out[k] = Math.round(out[k] * 1e4) / 1e4; });
            ['low_hz', 'high_hz'].forEach(function (k) {
                if (out[k] !== null && out[k] !== undefined) { out[k] = Math.round(out[k] * 10) / 10; }
            });
            return out;
        });
    }

    function save(state) {
        var value = JSON.stringify(serialise(state));
        if (state.input.value !== value) {
            state.input.value = value;
            state.input.setAttribute('data-modified', 'true');
            state.input.dispatchEvent(new Event('change', {bubbles: true}));
        }
        declare(state);
    }

    function declare(state) {
        var reasons = [], min = state.cfg.minBoxes || 0;
        if (state.boxes.length < min) {
            reasons.push('draw at least ' + min + ' box' + (min === 1 ? '' : 'es') +
                         ' (' + state.boxes.length + ' so far)');
        }
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
    }

    function markEdited(box) {
        if (box.source && box.source !== 'human') { box.edited = true; }
    }

    function selected(state) {
        for (var i = 0; i < state.boxes.length; i++) {
            if (state.boxes[i]._id === state.selected) { return state.boxes[i]; }
        }
        return null;
    }

    function status(state, text) { if (state.statusEl) { state.statusEl.textContent = text; } }

    // ------------------------------------------------------------------
    // Geometry: seconds / hertz <-> fractions of the spectrogram
    // ------------------------------------------------------------------

    function fx(state, s) { return clamp(s / state.duration, 0, 1); }
    function fy(state, hz) { return clamp(1 - (hz - state.fmin) / (state.fmax - state.fmin), 0, 1); }

    function pointAt(state, ev) {
        var rect = state.wrap.getBoundingClientRect();
        var x = clamp((ev.clientX - rect.left) / rect.width, 0, 1);
        var y = clamp((ev.clientY - rect.top) / rect.height, 0, 1);
        return {s: x * state.duration, hz: state.fmin + (1 - y) * (state.fmax - state.fmin),
                px: ev.clientX - rect.left, py: ev.clientY - rect.top, w: rect.width, h: rect.height};
    }

    function bandOf(state, box) {
        return {low: box.low_hz === null ? state.fmin : box.low_hz,
                high: box.high_hz === null ? state.fmax : box.high_hz};
    }

    // ------------------------------------------------------------------
    // Rendering
    // ------------------------------------------------------------------

    function describe(box) {
        var band = (box.low_hz === null || box.high_hz === null) ? 'all frequencies'
            : fmtFreq(box.low_hz) + ' to ' + fmtFreq(box.high_hz);
        return box.label + ', ' + fmtTime(box.start_s) + ' to ' + fmtTime(box.end_s) + ' s, ' + band;
    }

    function drawBoxes(state) {
        var layer = state.layer;
        var keepFocus = document.activeElement && layer.contains(document.activeElement)
            ? document.activeElement.getAttribute('data-box-id') : null;
        layer.innerHTML = '';
        state.boxes.forEach(function (box, i) {
            var info = labelInfo(state, box.label), band = bandOf(state, box);
            var left = fx(state, box.start_s), right = fx(state, box.end_s);
            var top = fy(state, band.high), bottom = fy(state, band.low);
            var node = el('div', {
                className: 'sg-box' + (box._id === state.selected ? ' sg-selected' : '') +
                    (box.low_hz === null ? ' sg-band' : '') + (box.source === 'ai' && !box.edited ? ' sg-machine' : ''),
                tabindex: '0', role: 'button', 'data-box-id': String(box._id),
                'aria-pressed': box._id === state.selected ? 'true' : 'false',
                'aria-label': 'Box ' + (i + 1) + ': ' + describe(box)
            }, [
                el('div', {className: 'sg-tag', text: box.label +
                    (box.confidence !== undefined && box.confidence !== null && !box.edited
                        ? ' ' + Math.round(box.confidence * 100) + '%' : '')}),
                el('span', {className: 'sg-handle sg-handle-nw', 'data-handle': 'nw', 'aria-hidden': 'true'}),
                el('span', {className: 'sg-handle sg-handle-se', 'data-handle': 'se', 'aria-hidden': 'true'})
            ]);
            node.style.left = (left * 100) + '%';
            node.style.width = Math.max(0, (right - left) * 100) + '%';
            node.style.top = (top * 100) + '%';
            node.style.height = Math.max(0, (bottom - top) * 100) + '%';
            node.style.setProperty('--sg-color', info.color);
            // The label sits above the box unless the box touches the top edge.
            if (top < 0.1) { node.classList.add('sg-tag-inside'); }
            if (left > 0.8) { node.classList.add('sg-tag-right'); }
            node.addEventListener('focus', function () {
                if (state.selected !== box._id) { select(state, box._id, false); }
            });
            layer.appendChild(node);
        });
        if (keepFocus) {
            var again = layer.querySelector('[data-box-id="' + keepFocus + '"]');
            if (again) { again.focus({preventScroll: true}); }
        }
        drawList(state);
        drawLabels(state);
    }

    function drawList(state) {
        var body = state.listBody;
        body.innerHTML = '';
        state.countEl.textContent = state.boxes.length === 1 ? '1 box' : state.boxes.length + ' boxes';
        state.boxes.forEach(function (box, i) {
            var labelSelect = el('select', {className: 'sg-row-label', 'aria-label': 'Label for box ' + (i + 1)});
            state.cfg.labels.forEach(function (l) {
                var opt = el('option', {value: l.name, text: l.name});
                if (l.name === box.label) { opt.selected = true; }
                labelSelect.appendChild(opt);
            });
            if (!state.cfg.labels.some(function (l) { return l.name === box.label; })) {
                var odd = el('option', {value: box.label, text: box.label + ' (not in list)'});
                odd.selected = true;
                labelSelect.insertBefore(odd, labelSelect.firstChild);
            }
            labelSelect.addEventListener('change', function () {
                box.label = labelSelect.value; markEdited(box); drawBoxes(state); save(state);
            });
            var row = el('tr', {className: box._id === state.selected ? 'sg-row-selected' : '',
                                'data-box-id': String(box._id)}, [
                el('td', {}, [el('span', {className: 'sg-swatch', 'aria-hidden': 'true'})]),
                el('td', {}, [labelSelect]),
                el('td', {className: 'sg-num', text: fmtTime(box.start_s) + '–' + fmtTime(box.end_s) + ' s'}),
                el('td', {className: 'sg-num', text: (box.low_hz === null ? 'all' :
                    fmtFreq(box.low_hz) + '–' + fmtFreq(box.high_hz))}),
                el('td', {className: 'sg-row-actions'}, [
                    el('button', {type: 'button', className: 'sg-btn sg-row-play', text: 'Play',
                                  'aria-label': 'Play box ' + (i + 1),
                                  onclick: function () { select(state, box._id, false); playBox(state, box); }}),
                    el('button', {type: 'button', className: 'sg-btn sg-row-delete', text: 'Delete',
                                  'aria-label': 'Delete box ' + (i + 1),
                                  onclick: function () { remove(state, box._id); }})
                ])
            ]);
            row.querySelector('.sg-swatch').style.background = labelInfo(state, box.label).color;
            body.appendChild(row);
        });
        state.listWrap.hidden = state.boxes.length === 0;
    }

    function drawLabels(state) {
        var sel = selected(state);
        state.labelBar.querySelectorAll('.sg-label').forEach(function (b) {
            var name = b.getAttribute('data-label');
            b.setAttribute('aria-pressed', name === state.activeLabel ? 'true' : 'false');
            b.classList.toggle('sg-label-of-selected', !!sel && sel.label === name);
        });
    }

    function drawAxes(state) {
        var f = state.faxis, t = state.taxis;
        f.innerHTML = ''; t.innerHTML = '';
        var span = state.fmax - state.fmin, step = niceStep(span / 5);
        for (var hz = Math.ceil(state.fmin / step) * step; hz <= state.fmax + 1e-6; hz += step) {
            var tick = el('span', {className: 'sg-ftick', text: hz >= 1000 ? (hz / 1000) + 'k' : String(Math.round(hz))});
            tick.style.top = (fy(state, hz) * 100) + '%';
            if (fy(state, hz) < 0.04) { tick.style.transform = 'none'; }
            else if (fy(state, hz) > 0.96) { tick.style.transform = 'translateY(-100%)'; }
            f.appendChild(tick);
        }
        var width = state.wrap.getBoundingClientRect().width || 600;
        var tstep = niceStep(state.duration / Math.max(2, Math.floor(width / 80)));
        for (var s = 0; s <= state.duration + 1e-6; s += tstep) {
            var tt = el('span', {className: 'sg-ttick', text: (Math.round(s * 100) / 100) + ' s'});
            tt.style.left = (fx(state, s) * 100) + '%';
            if (s > 0 && fx(state, s) > 0.97) { tt.classList.add('sg-ttick-last'); }
            t.appendChild(tt);
        }
    }

    function niceStep(raw) {
        var p = Math.pow(10, Math.floor(Math.log10(raw || 1))), m = raw / p;
        return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
    }

    function drawPlayhead(state) {
        var pos = position(state);
        state.playhead.style.left = (fx(state, pos) * 100) + '%';
        state.timeEl.textContent = fmtTime(pos) + ' / ' + fmtTime(state.duration) + ' s';
        state.playBtn.textContent = state.source ? 'Pause' : 'Play';
        state.playBtn.setAttribute('aria-pressed', state.source ? 'true' : 'false');
    }

    // ------------------------------------------------------------------
    // Playback
    // ------------------------------------------------------------------

    function position(state) {
        if (!state.source) { return state.offset; }
        return Math.min(state.ctx.currentTime - state.startedAt, state.stopAt || state.duration);
    }

    function play(state, from, until) {
        stop(state, true);
        if (state.ctx.state === 'suspended') { state.ctx.resume(); }
        var start = from === undefined ? state.offset : from;
        if (start >= state.duration - 0.01) { start = 0; }
        var src = state.ctx.createBufferSource();
        src.buffer = state.buffer;
        src.connect(state.ctx.destination);
        src.onended = function () {
            if (state.source !== src) { return; }
            state.source = null;
            state.offset = until !== undefined ? start : 0;
            drawPlayhead(state);
        };
        if (until !== undefined) { src.start(0, start, Math.max(0.01, until - start)); }
        else { src.start(0, start); }
        state.source = src;
        state.startedAt = state.ctx.currentTime - start;
        state.stopAt = until;
        tick(state);
    }

    function stop(state, keepPosition) {
        if (state.source) {
            var pos = position(state);
            var src = state.source;
            state.source = null;
            try { src.stop(); } catch (e) { /* already stopped */ }
            state.offset = keepPosition ? pos : state.offset;
        }
        drawPlayhead(state);
    }

    function tick(state) {
        drawPlayhead(state);
        if (state.source) { requestAnimationFrame(function () { tick(state); }); }
    }

    function playBox(state, box) { play(state, box.start_s, box.end_s); }

    // ------------------------------------------------------------------
    // Editing
    // ------------------------------------------------------------------

    function select(state, id, focus) {
        state.selected = id;
        var box = selected(state);
        if (box && labelInfo(state, box.label)) { state.activeLabel = box.label; }
        drawBoxes(state);
        if (focus && id !== null) {
            var node = state.layer.querySelector('[data-box-id="' + id + '"]');
            if (node) { node.focus({preventScroll: true}); }
        }
        if (box) { status(state, 'Selected ' + describe(box) + '.'); }
    }

    function remove(state, id) {
        state.boxes = state.boxes.filter(function (b) { return b._id !== id; });
        if (state.selected === id) { state.selected = null; }
        drawBoxes(state);
        save(state);
        status(state, 'Box deleted.');
        state.root.focus({preventScroll: true});
    }

    function canAdd(state) {
        if (state.cfg.maxBoxes && state.boxes.length >= state.cfg.maxBoxes) {
            status(state, 'This clip allows at most ' + state.cfg.maxBoxes + ' boxes.');
            return false;
        }
        return true;
    }

    function add(state, box) {
        box._id = nextId++;
        box.source = 'human';
        state.boxes.push(box);
        state.selected = box._id;
        drawBoxes(state);
        save(state);
        status(state, 'Added ' + describe(box) + '.');
    }

    function setLabel(state, name) {
        state.activeLabel = name;
        var box = selected(state);
        if (box && box.label !== name) {
            box.label = name; markEdited(box); drawBoxes(state); save(state);
            status(state, 'Relabelled: ' + describe(box) + '.');
        } else {
            drawLabels(state);
            status(state, 'New boxes: ' + name + '.');
        }
    }

    function normalise(state, box) {
        var minDur = Math.max(0.005, state.duration / 2000);
        box.start_s = clamp(box.start_s, 0, state.duration);
        box.end_s = clamp(Math.max(box.end_s, box.start_s + minDur), 0, state.duration);
        if (box.low_hz !== null && box.high_hz !== null) {
            var minBand = (state.fmax - state.fmin) / 500;
            box.low_hz = clamp(box.low_hz, state.fmin, state.fmax);
            box.high_hz = clamp(Math.max(box.high_hz, box.low_hz + minBand), state.fmin, state.fmax);
        }
    }

    function onPointerDown(state, ev) {
        if (ev.button !== undefined && ev.button !== 0) { return; }
        var boxNode = ev.target.closest('.sg-box');
        var p = pointAt(state, ev);
        state.root.focus({preventScroll: true});
        if (boxNode) {
            var id = parseInt(boxNode.getAttribute('data-box-id'), 10);
            var box = null;
            state.boxes.forEach(function (b) { if (b._id === id) { box = b; } });
            if (!box) { return; }
            var handle = ev.target.getAttribute('data-handle');
            if (!handle && state.selected !== id && box.source === 'ai') {
                // A detector's box that is not selected is drawn over, not
                // moved. BirdNET boxes are full-band 3 s windows and can cover
                // the whole spectrogram, so a press always landed on one and a
                // drag meant to draw a missed call moved a detection instead.
                // A click without a drag still selects it; once selected it
                // moves and resizes as usual.
                state.drag = {mode: 'draw', from: p, moved: false, ghost: null, pressedBox: id};
                state.wrap.setPointerCapture(ev.pointerId);
                ev.preventDefault();
                return;
            }
            select(state, id, false);
            state.drag = {mode: handle ? 'resize-' + handle : 'move', box: box, from: p,
                          orig: {start_s: box.start_s, end_s: box.end_s, low_hz: box.low_hz, high_hz: box.high_hz},
                          moved: false};
        } else {
            state.drag = {mode: 'draw', from: p, moved: false, ghost: null};
        }
        state.wrap.setPointerCapture(ev.pointerId);
        ev.preventDefault();
    }

    function onPointerMove(state, ev) {
        var d = state.drag;
        if (!d) { return; }
        var p = pointAt(state, ev);
        if (Math.abs(p.px - d.from.px) >= MIN_DRAG_PX || Math.abs(p.py - d.from.py) >= MIN_DRAG_PX) { d.moved = true; }
        if (!d.moved) { return; }
        if (d.mode === 'draw') {
            if (!d.ghost) {
                d.ghost = el('div', {className: 'sg-ghost', 'aria-hidden': 'true'});
                d.ghost.style.setProperty('--sg-color', labelInfo(state, state.activeLabel).color);
                state.wrap.appendChild(d.ghost);
            }
            var l = Math.min(p.px, d.from.px), t = Math.min(p.py, d.from.py);
            d.ghost.style.left = (l / p.w * 100) + '%';
            d.ghost.style.top = (t / p.h * 100) + '%';
            d.ghost.style.width = (Math.abs(p.px - d.from.px) / p.w * 100) + '%';
            d.ghost.style.height = (Math.abs(p.py - d.from.py) / p.h * 100) + '%';
            return;
        }
        var box = d.box, o = d.orig, ds = p.s - d.from.s, dhz = p.hz - d.from.hz;
        if (d.mode === 'move') {
            var dur = o.end_s - o.start_s;
            box.start_s = clamp(o.start_s + ds, 0, state.duration - dur);
            box.end_s = box.start_s + dur;
            if (o.low_hz !== null && o.high_hz !== null) {
                var bw = o.high_hz - o.low_hz;
                box.low_hz = clamp(o.low_hz + dhz, state.fmin, state.fmax - bw);
                box.high_hz = box.low_hz + bw;
            }
        } else if (d.mode === 'resize-se') {
            box.end_s = Math.max(o.start_s, o.end_s + ds);
            if (o.low_hz !== null) { box.low_hz = Math.min(o.high_hz, o.low_hz + dhz); }
        } else if (d.mode === 'resize-nw') {
            box.start_s = Math.min(o.end_s, o.start_s + ds);
            if (o.high_hz !== null) { box.high_hz = Math.max(o.low_hz, o.high_hz + dhz); }
        }
        normalise(state, box);
        var node = state.layer.querySelector('[data-box-id="' + box._id + '"]');
        if (node) {
            var band = bandOf(state, box);
            node.style.left = (fx(state, box.start_s) * 100) + '%';
            node.style.width = ((fx(state, box.end_s) - fx(state, box.start_s)) * 100) + '%';
            node.style.top = (fy(state, band.high) * 100) + '%';
            node.style.height = ((fy(state, band.low) - fy(state, band.high)) * 100) + '%';
        }
    }

    function onPointerUp(state, ev) {
        var d = state.drag;
        state.drag = null;
        if (!d) { return; }
        try { state.wrap.releasePointerCapture(ev.pointerId); } catch (e) { /* not captured */ }
        var p = pointAt(state, ev);
        if (d.mode === 'draw') {
            if (d.ghost) { d.ghost.remove(); }
            var wide = Math.abs(p.px - d.from.px) >= MIN_DRAG_PX, tall = Math.abs(p.py - d.from.py) >= MIN_DRAG_PX;
            if (d.moved && wide && tall) {
                if (!canAdd(state)) { return; }
                var box = {start_s: Math.min(p.s, d.from.s), end_s: Math.max(p.s, d.from.s),
                           low_hz: Math.min(p.hz, d.from.hz), high_hz: Math.max(p.hz, d.from.hz),
                           label: state.activeLabel};
                normalise(state, box);
                add(state, box);
            } else if (!d.moved && d.pressedBox !== undefined) {
                select(state, d.pressedBox, false);
            } else if (!d.moved) {
                // A click on empty spectrogram: deselect and move the play position.
                state.selected = null;
                var playing = !!state.source;
                stop(state, false);
                state.offset = p.s;
                drawBoxes(state);
                drawPlayhead(state);
                if (playing) { play(state, p.s); }
            }
            return;
        }
        if (d.moved) {
            markEdited(d.box);
            drawBoxes(state);
            save(state);
            status(state, (d.mode === 'move' ? 'Moved: ' : 'Resized: ') + describe(d.box) + '.');
        }
    }

    function onKey(e) {
        var form = e.target.closest && e.target.closest('.spectrogram-annotation');
        if (!form) { return; }
        var state = STATES.get(form);
        if (!state || !state.buffer) { return; }
        var tag = e.target.tagName;
        if (tag === 'SELECT' || tag === 'INPUT' || tag === 'TEXTAREA') { return; }
        if (tag === 'BUTTON' && (e.key === ' ' || e.key === 'Enter')) { return; }
        var box = selected(state), handled = true, changed = false;
        var tStep = state.duration / (100 * state.zoom), fStep = (state.fmax - state.fmin) / 50;
        var labelHit = null;
        state.cfg.labels.forEach(function (l) {
            if (l.key && e.key === l.key && !e.ctrlKey && !e.metaKey && !e.altKey) { labelHit = l.name; }
        });
        if (labelHit) {
            setLabel(state, labelHit);
        } else if (e.key === ' ') {
            if (state.source) { stop(state, true); } else { play(state); }
        } else if ((e.key === 'p' || e.key === 'P') && box) {
            playBox(state, box);
        } else if ((e.key === 'n' || e.key === 'N') && !e.ctrlKey && !e.metaKey) {
            if (canAdd(state)) {
                var len = Math.min(0.5, state.duration / 10), span = state.fmax - state.fmin;
                var nb = {start_s: Math.min(state.offset, state.duration - len), end_s: 0,
                          low_hz: state.fmin + span / 3, high_hz: state.fmin + 2 * span / 3, label: state.activeLabel};
                nb.end_s = nb.start_s + len;
                normalise(state, nb);
                add(state, nb);
                select(state, nb._id, true);
            }
        } else if ((e.key === 'Delete' || e.key === 'Backspace') && box) {
            remove(state, box._id);
        } else if (e.key === 'Escape' && box) {
            state.selected = null; drawBoxes(state); status(state, 'Nothing selected.');
            state.root.focus({preventScroll: true});
        } else if (box && /^Arrow/.test(e.key)) {
            var hasBand = box.low_hz !== null && box.high_hz !== null;
            var resize = e.shiftKey;
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                var dt = e.key === 'ArrowLeft' ? -tStep : tStep;
                if (resize) { box.end_s += dt; }
                else {
                    dt = clamp(dt, -box.start_s, state.duration - box.end_s);
                    box.start_s += dt; box.end_s += dt;
                }
            } else if (hasBand) {
                var df = e.key === 'ArrowUp' ? fStep : -fStep;
                if (resize) { box.high_hz += df; }
                else {
                    df = clamp(df, state.fmin - box.low_hz, state.fmax - box.high_hz);
                    box.low_hz += df; box.high_hz += df;
                }
            }
            normalise(state, box);
            markEdited(box);
            changed = true;
        } else {
            handled = false;
        }
        if (handled) {
            // Potato's own label shortcuts must not also fire.
            e.preventDefault();
            e.stopPropagation();
        }
        if (changed) {
            drawBoxes(state);
            save(state);
            status(state, describe(box) + '.');
        }
    }

    function setZoom(state, zoom) {
        var vp = state.viewport, centre = (vp.scrollLeft + vp.clientWidth / 2) / (vp.scrollWidth || 1);
        state.zoom = clamp(zoom, 1, 16);
        state.wrapOuter.style.width = (state.zoom * 100) + '%';
        vp.scrollLeft = centre * vp.scrollWidth - vp.clientWidth / 2;
        state.zoomEl.textContent = state.zoom + '×';
        drawAxes(state);
    }

    // ------------------------------------------------------------------
    // Setup
    // ------------------------------------------------------------------

    /* The sample rate a WAV file was recorded at, read from its fmt chunk.
       decodeAudioData resamples to the context's rate, which would put an
       empty band above the recording's own Nyquist frequency. */
    function wavRate(data) {
        try {
            var v = new DataView(data);
            if (v.byteLength < 28 || v.getUint32(0, false) !== 0x52494646 || v.getUint32(8, false) !== 0x57415645) {
                return null;
            }
            var pos = 12;
            while (pos + 8 <= v.byteLength) {
                var id = v.getUint32(pos, false), size = v.getUint32(pos + 4, true);
                if (id === 0x666d7420) { return v.getUint32(pos + 12, true) || null; }
                pos += 8 + size + (size % 2);
            }
        } catch (e) { /* not a WAV */ }
        return null;
    }

    function decode(ctx, data, rate) {
        var Offline = window.OfflineAudioContext || window.webkitOfflineAudioContext;
        var target = ctx;
        if (rate && Offline && rate !== ctx.sampleRate) {
            try { target = new Offline(1, 1, rate); } catch (e) { target = ctx; }
        }
        return new Promise(function (resolve, reject) {
            var p = target.decodeAudioData(data, resolve, reject);
            if (p && p.then) { p.then(resolve, reject); }
        });
    }

    function audioUrl(cfg) {
        var url = window.potatoInstanceField ? window.potatoInstanceField(cfg.sourceField) : null;
        if (!url) {
            var text = document.getElementById('instance-text');
            var raw = text ? (text.textContent || '').trim() : '';
            if (/^(https?:\/\/|\/)\S+\.(wav|mp3|flac|ogg|m4a|aac|opus|webm)(\?\S*)?$/i.test(raw)) { url = raw; }
        }
        return url;
    }

    function build(state) {
        var cfg = state.cfg, root = state.root;
        root.innerHTML = '';
        root.setAttribute('tabindex', '0');
        root.setAttribute('aria-label', 'Spectrogram box annotation. Drag on the spectrogram to draw a box. ' +
            'Keys: 1 to ' + Math.min(9, cfg.labels.length) + ' choose a label, arrows move the selected box, ' +
            'Shift and arrows resize it, N adds a box, Delete removes it, Space plays.');
        state.playBtn = el('button', {type: 'button', className: 'sg-btn sg-play', text: 'Play', 'aria-pressed': 'false',
            onclick: function () { if (state.source) { stop(state, true); } else { play(state); } }});
        state.timeEl = el('span', {className: 'sg-time', 'aria-live': 'off'});
        state.zoomEl = el('span', {className: 'sg-zoom-level', text: '1×'});
        var zoomOut = el('button', {type: 'button', className: 'sg-btn sg-zoom-out', text: '−', 'aria-label': 'Zoom out',
            onclick: function () { setZoom(state, state.zoom / 2); }});
        var zoomIn = el('button', {type: 'button', className: 'sg-btn sg-zoom-in', text: '+', 'aria-label': 'Zoom in',
            onclick: function () { setZoom(state, state.zoom * 2); }});
        state.labelBar = el('div', {className: 'sg-labels', role: 'group', 'aria-label': 'Label for new boxes'});
        cfg.labels.forEach(function (l) {
            var b = el('button', {type: 'button', className: 'sg-label', 'data-label': l.name, 'aria-pressed': 'false',
                                  onclick: function () { setLabel(state, l.name); }},
                [el('span', {className: 'sg-swatch', 'aria-hidden': 'true'}),
                 el('span', {className: 'sg-label-name', text: l.name}),
                 l.key ? el('kbd', {text: l.key}) : null]);
            b.querySelector('.sg-swatch').style.background = l.color;
            state.labelBar.appendChild(b);
        });
        var toolbar = el('div', {className: 'sg-toolbar'}, [
            el('div', {className: 'sg-transport'}, [state.playBtn, state.timeEl]),
            el('div', {className: 'sg-zoom'}, [zoomOut, state.zoomEl, zoomIn])
        ]);
        state.canvas = el('canvas', {className: 'sg-canvas', 'aria-hidden': 'true'});
        state.layer = el('div', {className: 'sg-boxes'});
        state.playhead = el('div', {className: 'sg-playhead', 'aria-hidden': 'true'});
        state.wrap = el('div', {className: 'sg-wrap'}, [state.canvas, state.layer, state.playhead]);
        state.wrap.style.height = cfg.height + 'px';
        state.taxis = el('div', {className: 'sg-taxis', 'aria-hidden': 'true'});
        state.wrapOuter = el('div', {className: 'sg-wrap-outer'}, [state.wrap, state.taxis]);
        state.viewport = el('div', {className: 'sg-viewport'}, [state.wrapOuter]);
        state.faxis = el('div', {className: 'sg-faxis', 'aria-hidden': 'true'});
        state.faxis.style.height = cfg.height + 'px';
        var stage = el('div', {className: 'sg-stage'}, [state.faxis, state.viewport]);
        state.statusEl = el('p', {className: 'sg-status', role: 'status', 'aria-live': 'polite'});
        state.countEl = el('span', {className: 'sg-count'});
        state.listBody = el('tbody');
        state.listWrap = el('div', {className: 'sg-list-wrap'}, [
            el('table', {className: 'sg-list'}, [
                el('caption', {}, [state.countEl]),
                el('thead', {}, [el('tr', {}, ['', 'Label', 'Time', 'Frequency', ''].map(function (h) {
                    return el('th', {scope: 'col', text: h});
                }))]),
                state.listBody])
        ]);
        root.appendChild(toolbar);
        root.appendChild(state.labelBar);
        root.appendChild(stage);
        root.appendChild(state.statusEl);
        root.appendChild(state.listWrap);
        root.appendChild(el('p', {className: 'sg-keys', text:
            'Drag to draw · drag a box to move it, its corners to resize · keys: ' +
            (cfg.labels.length > 1 ? '1–' + Math.min(9, cfg.labels.length) + ' label, ' : '') +
            'arrows move, Shift+arrows resize, N new box, Delete, Space play, P play box'}));

        state.wrap.addEventListener('pointerdown', function (ev) { onPointerDown(state, ev); });
        state.wrap.addEventListener('pointermove', function (ev) { onPointerMove(state, ev); });
        state.wrap.addEventListener('pointerup', function (ev) { onPointerUp(state, ev); });
        state.wrap.addEventListener('pointercancel', function (ev) { onPointerUp(state, ev); });
        window.addEventListener('resize', function () { drawAxes(state); });
    }

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { return; }
        if (prior) { stop(prior, false); }
        var cfg = JSON.parse(form.getAttribute('data-spectrogram-config') || '{}');
        var root = form.querySelector('.sg-root');
        var input = form.querySelector('.spectrogram-input');
        var state = {instance: instanceId(), cfg: cfg, form: form, root: root, input: input,
                     boxes: readStored(input), selected: null, zoom: 1, offset: 0, source: null,
                     activeLabel: (cfg.labels[0] || {}).name || '', buffer: null};
        STATES.set(form, state);
        declare(state);
        var ctx = audioContext();
        var url = audioUrl(cfg);
        function fail(text) {
            root.innerHTML = '';
            root.appendChild(el('p', {className: 'sg-error', role: 'alert', text: text}));
        }
        if (!ctx) { fail('This browser cannot show the spectrogram (no Web Audio support).'); return; }
        if (!url) { fail('This item has no audio in its "' + cfg.sourceField + '" field.'); return; }
        state.ctx = ctx;
        fetch(url, {credentials: 'same-origin'}).then(function (r) {
            if (!r.ok) { throw new Error('HTTP ' + r.status); }
            return r.arrayBuffer();
        }).then(function (data) {
            var fields = window.potatoInstanceFields ? window.potatoInstanceFields() : {};
            var rate = wavRate(data) || parseInt(fields.sample_rate, 10) || null;
            return decode(ctx, data, rate);
        }).then(function (buffer) {
            if (STATES.get(form) !== state) { return; }
            state.buffer = buffer;
            state.duration = buffer.duration;
            var nyquist = buffer.sampleRate / 2;
            var fmax = cfg.maxFreq ? Math.min(cfg.maxFreq, nyquist) : nyquist;
            var fmin = clamp(cfg.minFreq || 0, 0, fmax - 1);
            build(state);
            var band = paint(state.canvas, buffer, {fftSize: cfg.fftSize, fmin: fmin, fmax: fmax,
                                                     colormap: cfg.colormap});
            state.fmin = band.fmin; state.fmax = band.fmax;
            form.classList.add('sg-ready');
            drawAxes(state);
            drawBoxes(state);
            drawPlayhead(state);
        }).catch(function (err) {
            fail('Could not load the audio (' + (err && err.message ? err.message : err) + ').');
        });
    }

    function init() {
        document.querySelectorAll('form.spectrogram-annotation').forEach(setup);
    }

    document.addEventListener('keydown', onKey, true);
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { init(); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoSpectrogram = {init: init, _fft: fft, _fftTables: fftTables};
})();

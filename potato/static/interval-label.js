/*
 * interval_label: label intervals and point events on a time_series display.
 *
 * The answer is one hidden input holding
 *   {"intervals": [{start, end, label, channel}], "events": [{time, label, channel}]}
 * (channel: a channel name, or null for all channels). The server fills the
 * input when the instance is shown again; init() reads it and redraws the
 * overlays, so navigating away and back restores what was labelled.
 *
 * Several interval_label schemes may share one plot (sleep stages in epoch
 * mode plus a free-mode scheme for arousals). Pointer gestures go to the
 * scheme whose label was picked last; a click first selects an existing entry
 * in any scheme. Each scheme draws on its own overlay layer.
 */
(function () {
    'use strict';
    if (window.PotatoIntervalLabel) { return; }

    var STATES = new WeakMap();
    var EPS = 1e-6;

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

    function emptyValue() { return {intervals: [], events: []}; }

    function parseValue(text) {
        if (!text) { return emptyValue(); }
        try {
            var v = JSON.parse(text);
            if (Array.isArray(v)) {
                v = {intervals: v.filter(function (x) { return x && x.time === undefined; }),
                     events: v.filter(function (x) { return x && x.time !== undefined; })};
            }
            return {intervals: Array.isArray(v.intervals) ? v.intervals : [],
                    events: Array.isArray(v.events) ? v.events : []};
        } catch (e) {
            return emptyValue();
        }
    }

    function round6(x) { return Math.round(x * 1e6) / 1e6; }

    function labelOf(state, name) {
        for (var i = 0; i < state.cfg.labels.length; i++) {
            if (state.cfg.labels[i].name === name) { return state.cfg.labels[i]; }
        }
        return null;
    }

    function colorOf(state, name) {
        var lab = labelOf(state, name);
        return lab ? lab.color : '#6C757D';
    }

    // ------------------------------------------------------------------
    // Per-plot coordination
    // ------------------------------------------------------------------

    function hub(plot) {
        if (plot._il) { return plot._il; }
        var h = {schemes: [], owner: null};
        plot._il = h;
        plot.on('brush', function (b) {
            var s = h.owner || h.schemes.filter(function (x) { return x.cfg.mode === 'free'; })[0] || h.schemes[0];
            if (s) { onBrush(s, b); }
        });
        plot.on('click', function (c) {
            // With an event label picked, a click marks a point (or selects
            // one of that scheme's own events), even over a labelled interval.
            var o = h.owner, lab = o && labelOf(o, o.active);
            if (lab && lab.kind === 'event') {
                h.schemes.forEach(function (x) { if (x !== o) { deselect(x); } });
                if (!hitSelect(o, c, true)) { deselect(o); onClick(o, c); }
                return;
            }
            var ordered = h.owner ? [h.owner].concat(h.schemes.filter(function (x) { return x !== h.owner; }))
                                  : h.schemes.slice();
            for (var i = 0; i < ordered.length; i++) {
                if (hitSelect(ordered[i], c)) {
                    h.schemes.forEach(function (x) { if (x !== ordered[i]) { deselect(x); } });
                    return;
                }
            }
            h.schemes.forEach(function (x) { deselect(x); });
            var owner = h.owner || ordered[0];
            if (owner) { onClick(owner, c); }
        });
        plot.on('view', function () { h.schemes.forEach(function (s) { renderEpoch(s); }); });
        return h;
    }

    function claim(state) {
        if (state.plot) { hub(state.plot).owner = state; }
    }

    // ------------------------------------------------------------------
    // Editing
    // ------------------------------------------------------------------

    function scopeChannel(state, channel) {
        var scope = state.cfg.channelScope;
        if (scope === 'either') {
            var r = state.form.querySelector('.il-scope input:checked');
            scope = r ? r.value : 'all';
        }
        return scope === 'channel' ? (channel || null) : null;
    }

    function onBrush(state, b) {
        if (state.cfg.mode === 'epoch') {
            say(state, 'In epoch mode a label key labels the whole epoch. Use a free-mode scheme to label ' +
                'stretches inside an epoch.');
            return;
        }
        var lab = labelOf(state, state.active);
        if (!lab) { say(state, 'Pick a label first, then drag across the plot.'); return; }
        if (lab.kind === 'event') { say(state, '"' + lab.name + '" marks a point: click on the plot instead.'); return; }
        if (!(b.end - b.start > EPS)) { return; }
        var iv = {start: round6(b.start), end: round6(b.end), label: lab.name,
                  channel: scopeChannel(state, b.pointerChannel)};
        if (!state.cfg.allowOverlap) { carve(state, iv.start, iv.end, iv.channel); }
        state.value.intervals.push(iv);
        sortValue(state);
        state.selected = null;
        changed(state, 'Labelled ' + describe(state, iv) + '.');
    }

    /* Remove the part of every interval on the same channel that overlaps
       [start, end), splitting one that spans it. */
    function carve(state, start, end, channel) {
        var out = [];
        state.value.intervals.forEach(function (iv) {
            if ((iv.channel || null) !== (channel || null) || iv.end <= start + EPS || iv.start >= end - EPS) {
                out.push(iv);
                return;
            }
            if (iv.start < start - EPS) { out.push(Object.assign({}, iv, {end: start, source: undefined})); }
            if (iv.end > end + EPS) { out.push(Object.assign({}, iv, {start: end, source: undefined})); }
        });
        state.value.intervals = out.map(clean);
    }

    function clean(x) {
        var y = {};
        Object.keys(x).forEach(function (k) { if (x[k] !== undefined) { y[k] = x[k]; } });
        return y;
    }

    function onClick(state, c) {
        var lab = labelOf(state, state.active);
        if (lab && lab.kind === 'event') {
            var ev = {time: round6(c.time), label: lab.name, channel: scopeChannel(state, c.channel)};
            state.value.events.push(ev);
            sortValue(state);
            state.selected = null;
            changed(state, 'Marked ' + describe(state, ev) + '.');
        } else {
            render(state);
        }
    }

    function hitSelect(state, c, eventsOnly) {
        var plot = state.plot, view = plot.getView();
        var width = plot.u ? plot.u.over.clientWidth : 800;
        var tol = 6 * (view.end - view.start) / Math.max(1, width);
        var onChannel = function (x) { return !x.channel || !c.channel || x.channel === c.channel; };
        var hit = null;
        state.value.events.forEach(function (ev) {
            if (Math.abs(ev.time - c.time) <= tol && onChannel(ev)) { hit = {kind: 'events', item: ev}; }
        });
        if (!hit && !eventsOnly) {
            state.value.intervals.forEach(function (iv) {
                if (c.time >= iv.start && c.time <= iv.end && onChannel(iv)) { hit = {kind: 'intervals', item: iv}; }
            });
        }
        if (!hit) { return false; }
        state.selected = hit;
        render(state);
        say(state, 'Selected ' + describe(state, hit.item) + '. Delete removes it; a label key relabels it.');
        return true;
    }

    function deselect(state) {
        if (state.selected) { state.selected = null; render(state); }
    }

    function removeSelected(state) {
        var sel = state.selected;
        if (!sel) { return false; }
        state.value[sel.kind] = state.value[sel.kind].filter(function (x) { return x !== sel.item; });
        state.selected = null;
        changed(state, 'Removed ' + describe(state, sel.item) + '.');
        return true;
    }

    function relabelSelected(state, lab) {
        var sel = state.selected;
        if (!sel) { return false; }
        var wantKind = sel.kind === 'events' ? 'event' : 'interval';
        if (lab.kind !== wantKind) { return false; }
        sel.item.label = lab.name;
        delete sel.item.source;
        // Deselect, so the next label key picks a label rather than
        // relabelling the same entry again (relabel a beat V, then press N
        // to add a missed beat: without this the V beat went back to N).
        state.selected = null;
        changed(state, 'Relabelled as ' + lab.name + '.');
        return true;
    }

    /* Cut all-channel intervals (a hypnogram from the file) into the epochs
       they cover by at least half; channel intervals are kept as they are. */
    function toEpochs(state, intervals) {
        var plot = state.plot, L = state.cfg.epochLength, out = [];
        intervals.forEach(function (iv) {
            if (iv.channel) { out.push(iv); return; }
            var k0 = Math.max(0, Math.floor((iv.start - plot.meta.tStart) / L));
            var k1 = Math.min(plot.epochCount() - 1, Math.ceil((iv.end - plot.meta.tStart) / L) - 1);
            for (var k = k0; k <= k1; k++) {
                var b = plot.epochBounds(k);
                var overlap = Math.min(iv.end, b.end) - Math.max(iv.start, b.start);
                if (overlap >= (b.end - b.start) / 2 - EPS) {
                    out.push({start: round6(b.start), end: round6(b.end), label: iv.label, channel: null,
                              source: iv.source});
                }
            }
        });
        var seen = {};
        return out.filter(function (iv) {
            var k = iv.start + '|' + iv.end + '|' + (iv.channel || '');
            if (seen[k]) { return false; }
            seen[k] = true;
            return true;
        });
    }

    function epochIndexOf(state) { return state.plot ? state.plot.epochIndex() : 0; }

    function epochInterval(state, k) {
        var b = state.plot.epochBounds(k);
        var found = null;
        state.value.intervals.forEach(function (iv) {
            if (!iv.channel && Math.abs(iv.start - b.start) < 1e-3 && Math.abs(iv.end - b.end) < 1e-3) { found = iv; }
        });
        return found;
    }

    function labelEpoch(state, lab) {
        var k = epochIndexOf(state), b = state.plot.epochBounds(k);
        var existing = epochInterval(state, k);
        if (existing) {
            existing.label = lab.name;
            delete existing.source;
        } else {
            if (!state.cfg.allowOverlap) { carve(state, b.start, b.end, null); }
            state.value.intervals.push({start: round6(b.start), end: round6(b.end), label: lab.name, channel: null});
            sortValue(state);
        }
        state.selected = null;
        changed(state, 'Epoch ' + (k + 1) + ': ' + lab.name + '.');
        if (state.cfg.autoAdvance && k < state.plot.epochCount() - 1) { state.plot.epoch(k + 1); }
    }

    function clearEpoch(state) {
        var k = epochIndexOf(state), iv = epochInterval(state, k);
        if (!iv) { return; }
        state.value.intervals = state.value.intervals.filter(function (x) { return x !== iv; });
        changed(state, 'Epoch ' + (k + 1) + ' cleared.');
    }

    function pickLabel(state, lab) {
        claim(state);
        if (state.cfg.mode === 'epoch' && lab.kind !== 'event' && state.plot) {
            if (state.selected && state.selected.kind === 'events') { deselect(state); }
            labelEpoch(state, lab);
            return;
        }
        state.active = lab.name;
        if (!relabelSelected(state, lab)) {
            say(state, lab.kind === 'event' ? 'Click on the plot to mark "' + lab.name + '".'
                                            : 'Drag across the plot to label "' + lab.name + '".');
            render(state);
        }
    }

    function sortValue(state) {
        state.value.intervals.sort(function (a, b) { return a.start - b.start || a.end - b.end; });
        state.value.events.sort(function (a, b) { return a.time - b.time; });
    }

    // ------------------------------------------------------------------
    // Saving and completeness
    // ------------------------------------------------------------------

    function changed(state, message) {
        state.pending = false;
        save(state);
        render(state);
        if (message) { say(state, message); }
    }

    function serialize(state) {
        var v = {intervals: state.value.intervals.map(function (iv) {
                    var o = {start: iv.start, end: iv.end, label: iv.label, channel: iv.channel || null};
                    if (iv.source) { o.source = iv.source; }
                    return o;
                 }),
                 events: state.value.events.map(function (ev) {
                    var o = {time: ev.time, label: ev.label, channel: ev.channel || null};
                    if (ev.source) { o.source = ev.source; }
                    return o;
                 })};
        return (v.intervals.length || v.events.length) ? JSON.stringify(v) : '';
    }

    function save(state) {
        var input = state.input;
        input.value = serialize(state);
        input.setAttribute('data-modified', 'true');
        input.dispatchEvent(new Event('change', {bubbles: true}));
        declare(state);
    }

    function declare(state) {
        var reasons = [], cfg = state.cfg;
        if (cfg.requireAllEpochs && state.plot && state.plot.epochLength) {
            var n = state.plot.epochCount(), missing = 0;
            for (var k = 0; k < n; k++) { if (!epochInterval(state, k)) { missing += 1; } }
            if (missing) { reasons.push('label every epoch (' + missing + ' of ' + n + ' unlabelled)'); }
        }
        var total = state.value.intervals.length + state.value.events.length;
        if (cfg.minAnnotations && (state.pending ? 0 : total) < cfg.minAnnotations) {
            reasons.push('label at least ' + cfg.minAnnotations + ' interval' + (cfg.minAnnotations === 1 ? '' : 's') +
                         ' or event' + (cfg.minAnnotations === 1 ? '' : 's'));
        }
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
    }

    // ------------------------------------------------------------------
    // Rendering
    // ------------------------------------------------------------------

    function say(state, text) {
        var m = state.form.querySelector('.il-message');
        if (m) { m.textContent = text || ''; }
    }

    function timeText(state, t) {
        return state.plot ? state.plot.timeLabel(t, 60) : t.toFixed(2);
    }

    function describe(state, x) {
        var where = x.channel ? ' on ' + x.channel : '';
        if (x.time !== undefined) { return x.label + ' at ' + timeText(state, x.time) + where; }
        return x.label + ' ' + timeText(state, x.start) + '–' + timeText(state, x.end) + where;
    }

    function render(state) {
        var cfg = state.cfg, plot = state.plot;
        // Label buttons: the active label (free) or this epoch's label (epoch).
        var current = null;
        if (cfg.mode === 'epoch' && plot) {
            var iv = epochInterval(state, epochIndexOf(state));
            current = iv ? iv.label : null;
        }
        state.form.querySelectorAll('.il-label').forEach(function (b) {
            var name = b.getAttribute('data-label');
            var on = cfg.mode === 'epoch' && b.getAttribute('data-kind') !== 'event' ? name === current
                                                                                     : name === state.active;
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        if (plot) {
            var sel = state.selected ? state.selected.item : null;
            plot.setOverlays({
                intervals: state.value.intervals.map(function (iv) {
                    return {start: iv.start, end: iv.end, channel: iv.channel, label: iv.label,
                            color: colorOf(state, iv.label), selected: iv === sel, dashed: !!state.pending};
                }),
                events: state.value.events.map(function (ev) {
                    return {time: ev.time, channel: ev.channel, label: ev.label,
                            color: colorOf(state, ev.label), selected: ev === sel};
                })
            }, cfg.schema);
            plot.setOverviewMarks(state.value.intervals.filter(function (iv) { return !iv.channel; })
                .map(function (iv) { return {start: iv.start, end: iv.end, color: colorOf(state, iv.label)}; })
                .concat(state.value.events.map(function (ev) {
                    var w = (plot.meta.tEnd - plot.meta.tStart) / 600;
                    return {start: ev.time - w / 2, end: ev.time + w / 2, color: colorOf(state, ev.label)};
                })), cfg.schema);
        }
        renderList(state);
        renderEpoch(state);
        var pre = state.form.querySelector('.il-pre');
        if (pre) {
            var n = state.value.intervals.length + state.value.events.length;
            pre.hidden = !state.pending || !n;
            pre.querySelector('.il-pre-text').textContent = n + ' annotation' + (n === 1 ? '' : 's') +
                ' from the file ' + (n === 1 ? 'is' : 'are') + ' shown (dashed). They are saved with your first change.';
        }
        state.form.setAttribute('data-il-count', String(state.value.intervals.length + state.value.events.length));
        declare(state);
    }

    function renderEpoch(state) {
        var box = state.form.querySelector('.il-epoch-text');
        if (!box || !state.plot || !state.plot.epochLength) { return; }
        var k = epochIndexOf(state), b = state.plot.epochBounds(k), iv = epochInterval(state, k);
        box.textContent = 'Epoch ' + (k + 1) + ' of ' + state.plot.epochCount() + ' · ' +
            timeText(state, b.start) + '–' + timeText(state, b.end) + ' · ' + (iv ? iv.label : 'unlabelled');
        state.form.querySelectorAll('.il-label').forEach(function (btn) {
            if (btn.getAttribute('data-kind') !== 'event') {
                btn.setAttribute('aria-pressed', iv && btn.getAttribute('data-label') === iv.label ? 'true' : 'false');
            }
        });
    }

    function renderList(state) {
        var body = state.form.querySelector('.il-list tbody');
        var empty = state.form.querySelector('.il-empty');
        if (!body) { return; }
        body.innerHTML = '';
        var rows = state.value.intervals.map(function (x) { return {kind: 'intervals', item: x, t: x.start}; })
            .concat(state.value.events.map(function (x) { return {kind: 'events', item: x, t: x.time}; }))
            .sort(function (a, b) { return a.t - b.t; });
        var selectedRow = null;
        rows.forEach(function (r) {
            var x = r.item;
            var when = r.kind === 'events' ? timeText(state, x.time)
                                           : timeText(state, x.start) + '–' + timeText(state, x.end);
            var isSel = state.selected && state.selected.item === x;
            var tr = el('tr', {className: 'il-row' + (isSel ? ' il-selected' : '') + (x.source ? ' il-from-file' : '')}, [
                el('td', {className: 'il-when', text: when}),
                el('td', {}, [el('span', {className: 'il-swatch', style: 'background:' + colorOf(state, x.label),
                                          'aria-hidden': 'true'}),
                              document.createTextNode(' ' + x.label + (r.kind === 'events' ? ' (event)' : '') +
                                                      (x.source ? ' · from file' : ''))]),
                el('td', {text: x.channel || 'all'}),
                el('td', {className: 'il-actions'}, [
                    el('button', {type: 'button', className: 'il-go', text: 'Show',
                                  'aria-label': 'Show ' + describe(state, x),
                                  onclick: function () { show(state, r); }}),
                    el('button', {type: 'button', className: 'il-del', text: 'Delete',
                                  'aria-label': 'Delete ' + describe(state, x),
                                  onclick: function () {
                                      state.selected = r;
                                      removeSelected(state);
                                  }})
                ])
            ]);
            if (isSel) { selectedRow = tr; }
            body.appendChild(tr);
        });
        if (empty) { empty.hidden = rows.length > 0; }
        if (selectedRow && selectedRow.scrollIntoView) {
            var wrap = state.form.querySelector('.il-list-wrap');
            if (wrap) {
                var top = selectedRow.offsetTop, h = selectedRow.offsetHeight;
                if (top < wrap.scrollTop || top + h > wrap.scrollTop + wrap.clientHeight) {
                    wrap.scrollTop = Math.max(0, top - wrap.clientHeight / 2);
                }
            }
        }
    }

    function show(state, r) {
        var plot = state.plot;
        if (!plot) { return; }
        state.selected = r;
        var x = r.item;
        if (plot.epochLength) {
            var t = r.kind === 'events' ? x.time : x.start;
            plot.epoch(Math.floor((t - plot.meta.tStart) / plot.epochLength + 1e-9));
        } else {
            var v = plot.getView(), span = v.end - v.start;
            if (r.kind === 'intervals' && x.end - x.start > span * 0.9) { span = (x.end - x.start) * 1.25; }
            var c = r.kind === 'events' ? x.time : (x.start + x.end) / 2;
            plot.setView(c - span / 2, c + span / 2);
        }
        render(state);
    }

    // ------------------------------------------------------------------
    // Keys
    // ------------------------------------------------------------------

    var navHandled = new WeakSet();

    function isTyping(target) {
        if (!target) { return false; }
        var tag = target.tagName;
        if (tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable) { return true; }
        if (tag === 'INPUT') {
            var type = (target.getAttribute('type') || 'text').toLowerCase();
            return ['radio', 'checkbox', 'button', 'submit', 'range'].indexOf(type) < 0;
        }
        return false;
    }

    function onKey(e) {
        if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) { return; }
        var forms = document.querySelectorAll('form.interval-label');
        var handled = false;
        forms.forEach(function (form) {
            var state = STATES.get(form);
            if (!state || !state.plot || handled) { return; }
            var cfg = state.cfg, key = e.key;
            if (key === cfg.nextKey || key === 'PageDown' || key === cfg.previousKey || key === 'PageUp') {
                if (!navHandled.has(e)) {
                    navHandled.add(e);
                    state.plot.step(key === cfg.nextKey || key === 'PageDown' ? 1 : -1);
                }
                handled = true;
                return;
            }
            if ((key === 'Delete' || key === 'Backspace') && state.selected) {
                removeSelected(state);
                handled = true;
                return;
            }
            if (key === 'Escape' && state.selected) {
                deselect(state);
                say(state, '');
                handled = true;
                return;
            }
            var lower = key.length === 1 ? key.toLowerCase() : key;
            for (var i = 0; i < cfg.labels.length; i++) {
                var lab = cfg.labels[i];
                if (lab.key && lab.key.toLowerCase() === lower) {
                    pickLabel(state, lab);
                    handled = true;
                    return;
                }
            }
        });
        if (handled) {
            // Potato's own label shortcuts (radio/checkbox data-key) must not also fire.
            e.preventDefault();
            e.stopPropagation();
        }
    }

    // ------------------------------------------------------------------
    // Setup
    // ------------------------------------------------------------------

    function bindPlot(state, plot) {
        if (STATES.get(state.form) !== state) { return; }
        state.plot = plot;
        var h = hub(plot);
        if (h.schemes.indexOf(state) < 0) { h.schemes.push(state); }
        plot.setBrushScope(state.cfg.channelScope === 'channel' ? 'channel' : 'all');
        if (state.cfg.channelScope === 'either') {
            state.form.querySelectorAll('.il-scope input').forEach(function (r) {
                r.addEventListener('change', function () {
                    claim(state);
                    plot.setBrushScope(state.form.querySelector('.il-scope input:checked').value);
                });
            });
        }
        if (state.cfg.mode === 'epoch') { plot.setEpochMode(state.cfg.epochLength); }
        if (!h.owner && state.cfg.mode === 'free') { h.owner = state; }
        render(state);
        var stored = state.value.intervals.length + state.value.events.length;
        if (!stored && state.cfg.preAnnotations) {
            var url = '/api/signals/preannotations?instance_id=' + encodeURIComponent(state.instance) +
                '&field=' + encodeURIComponent(state.cfg.signalField) + '&schema=' + encodeURIComponent(state.cfg.schema);
            fetch(url, {credentials: 'same-origin'}).then(function (r) { return r.ok ? r.json() : null; })
                .then(function (pre) {
                    if (!pre || STATES.get(state.form) !== state) { return; }
                    if (state.value.intervals.length + state.value.events.length) { return; }
                    if (!(pre.intervals || []).length && !(pre.events || []).length) { return; }
                    state.value = {intervals: pre.intervals || [], events: pre.events || []};
                    if (state.cfg.mode === 'epoch') { state.value.intervals = toEpochs(state, state.value.intervals); }
                    state.pending = true;
                    render(state);
                }).catch(function () { /* no pre-annotations */ });
        }
        state.form.setAttribute('data-il-ready', 'true');
    }

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { return; }
        var cfg;
        try { cfg = JSON.parse(form.getAttribute('data-il-config') || '{}'); }
        catch (e) { return; }
        var input = form.querySelector('.interval-label-input');
        var state = {form: form, cfg: cfg, input: input, instance: instanceId(),
                     value: parseValue(input.value), active: null, selected: null, pending: false, plot: null};
        var firstInterval = cfg.labels.filter(function (l) { return l.kind !== 'event'; })[0];
        state.active = cfg.mode === 'free' ? (firstInterval || cfg.labels[0] || {}).name || null : null;
        STATES.set(form, state);
        form.querySelectorAll('.il-label').forEach(function (b) {
            b.addEventListener('click', function () {
                var lab = labelOf(state, b.getAttribute('data-label'));
                if (lab && state.plot) { pickLabel(state, lab); }
            });
        });
        form.querySelectorAll('.il-step').forEach(function (b) {
            b.addEventListener('click', function () {
                if (state.plot) { state.plot.step(parseInt(b.getAttribute('data-step'), 10)); }
            });
        });
        var clear = form.querySelector('.il-clear-epoch');
        if (clear) { clear.addEventListener('click', function () { if (state.plot) { clearEpoch(state); } }); }
        var keep = form.querySelector('.il-keep');
        if (keep) { keep.addEventListener('click', function () { changed(state, 'Kept the file\'s annotations.'); }); }
        var discard = form.querySelector('.il-discard');
        if (discard) {
            discard.addEventListener('click', function () {
                state.value = emptyValue();
                state.selected = null;
                changed(state, 'Discarded the file\'s annotations.');
            });
        }
        render(state);
        if (!window.PotatoTimeSeries) {
            say(state, 'This scheme needs a time_series display on the page.');
            return;
        }
        window.PotatoTimeSeries.whenReady(cfg.signalField, function (plot) { bindPlot(state, plot); });
        setTimeout(function () {
            if (state.plot || STATES.get(form) !== state) { return; }
            var host = document.querySelector('.potato-viewer[data-viewer-field="' +
                (window.CSS && CSS.escape ? CSS.escape(cfg.signalField) : cfg.signalField) + '"]');
            if (!host) {
                say(state, 'signal_field "' + cfg.signalField + '" does not name a time_series field on this page.');
            } else if (host.getAttribute('data-viewer-state') === 'error' || host.classList.contains('pv-failed')) {
                say(state, 'The signal could not be shown, so there is nothing to label.');
            }
        }, 4000);
    }

    function init() {
        document.querySelectorAll('form.interval-label').forEach(setup);
    }

    document.addEventListener('keydown', onKey, true);
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { init(); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoIntervalLabel = {init: init, _states: STATES};
})();

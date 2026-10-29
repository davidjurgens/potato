/*
 * peak_picking scheme: peaks and integrals picked on a spectrum display.
 *
 * Binds to window.potatoViewers[viewer_field] (viewer-framework.js and the
 * spectrum adapter, spectrum.js), writes the selection as JSON into the
 * scheme's hidden input, and on load hands the stored JSON back with
 * setSelection(), which repaints the plot and these tables.
 *
 * Lists suggested peaks to accept or reject, the picked peaks with their
 * fields (assignment, multiplicity ...), and integrated regions with their
 * value relative to the first region. "Add a peak at" picks a peak from the
 * keyboard. min_peaks, require_review and required fields are reported on
 * the form's data-incomplete-reason.
 */
(function () {
    'use strict';
    if (window.PotatoPeakPicking) { return; }

    var STATES = new WeakMap();

    function instanceId() {
        var input = document.getElementById('instance_id');
        return input ? input.value : '';
    }

    function el(tag, attrs, text) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        if (text !== undefined) { node.textContent = text; }
        return node;
    }

    function readStored(input) {
        if (!input || !input.value) { return null; }
        try {
            var v = JSON.parse(input.value);
            return v && typeof v === 'object' ? v : null;
        } catch (e) { return null; }
    }

    function keyX(x) { return Number(x).toPrecision(9); }
    function itemKey(it) {
        return it.kind === 'region' ? 'r:' + keyX(it.from) + ':' + keyX(it.to) : 'p:' + keyX(it.x);
    }

    function hasContent(sel) {
        return !!sel && ((sel.items && sel.items.length) || (sel.rejected && sel.rejected.length));
    }

    function say(state, text) { state.message.textContent = text || ''; }

    function sp(state) { return state.viewer && state.viewer.spectrum; }

    function fmtX(state, x) { return sp(state) ? sp(state).format(x) : String(x); }

    function unit(state) {
        var s = sp(state);
        var u = s && s.cfg ? s.cfg.xUnits : '';
        return {PPM: 'ppm', HZ: 'Hz', '1/CM': 'cm⁻¹', 'M/Z': ''}[u] !== undefined
            ? {PPM: 'ppm', HZ: 'Hz', '1/CM': 'cm⁻¹', 'M/Z': ''}[u] : (u || '').toLowerCase();
    }

    function where(state, x) {
        var u = unit(state);
        var s = sp(state);
        var prefix = s && s.cfg && s.cfg.xUnits === 'M/Z' ? 'm/z ' : '';
        return prefix + fmtX(state, x) + (u ? ' ' + u : '');
    }

    function fmtY(y) {
        if (typeof y !== 'number' || !isFinite(y)) { return ''; }
        var a = Math.abs(y);
        return a !== 0 && (a >= 1e5 || a < 1e-3) ? y.toExponential(2) : String(Number(y.toPrecision(4)));
    }

    // ------------------------------------------------------------------

    function save(state, sel) {
        state.last = sel;
        state.input.value = hasContent(sel) ? JSON.stringify(sel) : '';
        state.input.setAttribute('data-modified', 'true');
        state.input.dispatchEvent(new Event('change', {bubbles: true}));
    }

    function missingFields(fields, items) {
        var missing = [];
        fields.forEach(function (f) {
            if (!f.required) { return; }
            if (items.some(function (it) { return !(it.fields && it.fields[f.name]); })) { missing.push(f.label); }
        });
        return missing;
    }

    function declare(state, sel) {
        var cfg = state.cfg, reasons = [];
        sel = sel || {items: []};
        var peaks = sel.items.filter(function (it) { return it.kind === 'peak'; });
        var regions = sel.items.filter(function (it) { return it.kind === 'region'; });
        if (cfg.minPeaks && peaks.length < cfg.minPeaks) {
            reasons.push('pick at least ' + cfg.minPeaks + ' peak' + (cfg.minPeaks === 1 ? '' : 's') +
                         (peaks.length ? ' (' + peaks.length + ' so far)' : ''));
        }
        if (cfg.requireReview && sp(state)) {
            var left = sp(state).pendingSuggestions(sel).length;
            if (left) { reasons.push('accept or reject every suggested peak (' + left + ' left)'); }
        }
        var mp = missingFields(cfg.peakFields || [], peaks);
        if (mp.length) { reasons.push('fill in ' + mp.join(', ') + ' for every peak'); }
        var mr = missingFields(cfg.regionFields || [], regions);
        if (mr.length) { reasons.push('fill in ' + mr.join(', ') + ' for every integral'); }
        if (state.viewer && state.viewer.state === 'error' && !peaks.length) {
            reasons.push('the spectrum could not load');
        }
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
    }

    /* A field edit: stored and drawn on the plot, without rebuilding the table
       (which would take the caret out of the box being typed in). */
    function setField(state, key, name, value) {
        var next = state.viewer.getSelection();
        var item = next.items.filter(function (it) { return itemKey(it) === key; })[0];
        if (!item) { return; }
        item.fields = item.fields || {};
        if (value) { item.fields[name] = value; } else { delete item.fields[name]; }
        if (!Object.keys(item.fields).length) { delete item.fields; }
        commit(state, next, false);
    }

    function fieldControl(state, f, item, what) {
        var current = item.fields && item.fields[f.name] || '';
        var label = f.label + ' for ' + what;
        var key = itemKey(item);
        var control;
        if (f.type === 'choice') {
            control = el('select', {'class': 'pp-field', 'aria-label': label, 'data-field': f.name});
            control.appendChild(el('option', {value: ''}, '—'));
            (f.options || []).forEach(function (o) {
                var opt = el('option', {value: o}, o);
                if (o === current) { opt.selected = true; }
                control.appendChild(opt);
            });
            control.addEventListener('change', function () { setField(state, key, f.name, control.value); });
        } else {
            control = el('input', {type: 'text', 'class': 'pp-field', 'aria-label': label,
                                   'data-field': f.name, autocomplete: 'off',
                                   placeholder: f.placeholder || ''});
            control.value = current;
            control.addEventListener('input', function () { setField(state, key, f.name, control.value.trim()); });
        }
        if (f.required) { control.setAttribute('aria-required', 'true'); }
        return control;
    }

    function head(table, columns) {
        var thead = table.querySelector('thead');
        thead.innerHTML = '';
        var tr = el('tr');
        columns.forEach(function (c) {
            var th = el('th', {scope: 'col'}, c.text);
            if (c.cls) { th.className = c.cls; }
            tr.appendChild(th);
        });
        thead.appendChild(tr);
    }

    function sortedForDisplay(state, items, getX) {
        var s = sp(state), rev = s && s.cfg && s.cfg.reversed;
        return items.slice().sort(function (a, b) { return rev ? getX(b) - getX(a) : getX(a) - getX(b); });
    }

    function removeButton(state, item, what, onDone) {
        var b = el('button', {type: 'button', 'class': 'pp-btn pp-remove', 'aria-label': 'Remove ' + what}, 'Remove');
        b.addEventListener('click', function () {
            var next = state.viewer.getSelection(), k = itemKey(item);
            next.items = next.items.filter(function (it) { return itemKey(it) !== k; });
            commit(state, next, true);
            say(state, 'Removed ' + what + '.');
            onDone();
        });
        return b;
    }

    function renderSuggestions(state, sel) {
        var s = sp(state), box = state.sugg;
        var all = s ? s.suggestions() : [];
        box.hidden = !all.length;
        if (!all.length) { return; }
        var pending = s.pendingSuggestions(sel);
        var rejected = all.filter(function (x) { return s.suggestionState(x, sel) === 'rejected'; });
        state.suggCount.textContent = pending.length
            ? pending.length + ' of ' + all.length + ' to review'
            : 'all ' + all.length + ' reviewed';
        state.acceptAll.disabled = !pending.length;
        state.rejectAll.disabled = !pending.length;
        state.suggList.innerHTML = '';
        sortedForDisplay(state, pending, function (x) { return x.x; }).forEach(function (sg) {
            var what = 'suggested peak at ' + where(state, sg.x);
            var li = el('li', {'class': 'pp-sugg'});
            li.appendChild(el('span', {'class': 'pp-sugg-mark', 'aria-hidden': 'true'}));
            li.appendChild(el('span', {'class': 'pp-pos'}, where(state, sg.x) + (sg.label ? ' · ' + sg.label : '')));
            var acc = el('button', {type: 'button', 'class': 'pp-btn pp-accept', 'aria-label': 'Accept ' + what}, 'Accept');
            var rej = el('button', {type: 'button', 'class': 'pp-btn pp-reject', 'aria-label': 'Reject ' + what}, 'Reject');
            var refocus = function () {
                var next = state.suggList.querySelector('.pp-accept');
                (next || state.form.querySelector('.pp-peak-table .pp-field, .pp-peak-table .pp-remove') || state.form).focus();
            };
            acc.addEventListener('click', function () { s.accept(sg); say(state, 'Accepted ' + what + '.'); refocus(); });
            rej.addEventListener('click', function () { s.reject(sg); say(state, 'Rejected ' + what + '.'); refocus(); });
            li.appendChild(acc);
            li.appendChild(rej);
            state.suggList.appendChild(li);
        });
        state.rejected.hidden = !rejected.length;
        state.rejected.innerHTML = '';
        if (rejected.length) {
            state.rejected.appendChild(el('span', {'class': 'pp-rejected-title'}, 'Rejected:'));
            sortedForDisplay(state, rejected, function (x) { return x.x; }).forEach(function (sg) {
                var b = el('button', {type: 'button', 'class': 'pp-btn pp-restore',
                                      'aria-label': 'Restore the suggested peak at ' + where(state, sg.x)},
                           '↺ ' + fmtX(state, sg.x));
                b.addEventListener('click', function () {
                    s.restore(sg.x);
                    say(state, 'Restored the suggestion at ' + where(state, sg.x) + '.');
                });
                state.rejected.appendChild(b);
            });
        }
    }

    function renderPeaks(state, sel) {
        var cfg = state.cfg, s = sp(state);
        var peaks = sel.items.filter(function (it) { return it.kind === 'peak'; });
        var table = state.peakTable, body = table.querySelector('tbody');
        state.empty.hidden = peaks.length > 0;
        table.hidden = !peaks.length;
        var count = peaks.length ? peaks.length + ' picked' : '';
        if (cfg.maxPeaks) { count += (count ? ', ' : '') + 'at most ' + cfg.maxPeaks; }
        if (cfg.minPeaks) { count += (count ? ', ' : '') + 'at least ' + cfg.minPeaks + ' needed'; }
        state.peakCount.textContent = count;
        var xLabel = s && s.cfg ? s.cfg.xLabel : 'Position';
        head(table, [{text: xLabel}, {text: 'Intensity', cls: 'pp-num'}, {text: 'Source'}]
            .concat((cfg.peakFields || []).map(function (f) { return {text: f.label + (f.required ? ' *' : '')}; }))
            .concat([{text: '', cls: 'pp-actions'}]));
        body.innerHTML = '';
        sortedForDisplay(state, peaks, function (it) { return it.x; }).forEach(function (it, i, list) {
            var what = 'the peak at ' + where(state, it.x);
            var tr = el('tr', {'data-key': itemKey(it)});
            tr.appendChild(el('td', {'class': 'pp-pos'}, fmtX(state, it.x)));
            tr.appendChild(el('td', {'class': 'pp-num'}, fmtY(it.y)));
            var src = el('td');
            src.appendChild(el('span', {'class': 'pp-source pp-source-' + it.source},
                               it.source === 'auto' ? 'suggested' : 'added'));
            tr.appendChild(src);
            (cfg.peakFields || []).forEach(function (f) {
                var td = el('td');
                td.appendChild(fieldControl(state, f, it, what));
                tr.appendChild(td);
            });
            var act = el('td', {'class': 'pp-actions'});
            act.appendChild(removeButton(state, it, what, function () {
                var buttons = body.querySelectorAll('.pp-remove');
                var target = buttons[Math.min(i, buttons.length - 1)];
                (target || state.addInput || state.form).focus();
            }));
            tr.appendChild(act);
            body.appendChild(tr);
        });
    }

    function renderRegions(state, sel) {
        var cfg = state.cfg, s = sp(state);
        var regions = sel.items.filter(function (it) { return it.kind === 'region'; });
        state.regions.hidden = !regions.length;
        var table = state.regionTable, body = table.querySelector('tbody');
        head(table, [{text: 'Range'}, {text: 'Integral', cls: 'pp-num'}, {text: 'Relative', cls: 'pp-num'}]
            .concat((cfg.regionFields || []).map(function (f) { return {text: f.label + (f.required ? ' *' : '')}; }))
            .concat([{text: '', cls: 'pp-actions'}]));
        body.innerHTML = '';
        regions.forEach(function (it) {
            var range = s && s.cfg && s.cfg.reversed
                ? fmtX(state, it.to) + '–' + fmtX(state, it.from)
                : fmtX(state, it.from) + '–' + fmtX(state, it.to);
            var what = 'the integral over ' + range;
            var tr = el('tr', {'data-key': itemKey(it)});
            tr.appendChild(el('td', {'class': 'pp-pos'}, range));
            tr.appendChild(el('td', {'class': 'pp-num'}, fmtY(it.integral)));
            var rel = s ? s.relative(it, sel) : null;
            tr.appendChild(el('td', {'class': 'pp-num'}, rel === null ? '' : rel.toFixed(2)));
            (cfg.regionFields || []).forEach(function (f) {
                var td = el('td');
                td.appendChild(fieldControl(state, f, it, what));
                tr.appendChild(td);
            });
            var act = el('td', {'class': 'pp-actions'});
            act.appendChild(removeButton(state, it, what, function () { state.form.focus(); }));
            tr.appendChild(act);
            body.appendChild(tr);
        });
    }

    function render(state, sel) {
        sel = sel || {items: []};
        renderSuggestions(state, sel);
        renderPeaks(state, sel);
        renderRegions(state, sel);
        if (state.addHint) {
            var s = sp(state);
            state.addHint.textContent = s && s.cfg && s.cfg.xLabel ? s.cfg.xLabel : '';
        }
    }

    /* A change made from this scheme's own controls. */
    function commit(state, next, rerender) {
        state.committing = true;
        state.quiet = !rerender;
        state.viewer.setSelection(next);      // repaints the plot; source 'api'
        state.committing = false;
        state.quiet = false;
        var sel = state.viewer.getSelection();
        save(state, sel);
        if (rerender) { render(state, sel); }
        declare(state, sel);
    }

    function peakCount(sel) { return sel.items.filter(function (it) { return it.kind === 'peak'; }).length; }

    function onChange(state, sel, info) {
        if (info && info.source === 'api') {
            if (!state.committing) { say(state, ''); }
            if (!state.quiet) { render(state, sel); }
            declare(state, sel);
            return;
        }
        var cfg = state.cfg, prev = state.last || {items: []};
        if (cfg.maxPeaks && peakCount(sel) > cfg.maxPeaks && peakCount(sel) > peakCount(prev)) {
            say(state, 'At most ' + cfg.maxPeaks + ' peak' + (cfg.maxPeaks === 1 ? '' : 's') +
                ' may be picked. Remove one first.');
            state.committing = true;
            state.viewer.setSelection(JSON.parse(JSON.stringify(prev)));
            state.committing = false;
            return;
        }
        var before = {}, after = {};
        prev.items.forEach(function (it) { before[itemKey(it)] = it; });
        sel.items.forEach(function (it) { after[itemKey(it)] = it; });
        var added = sel.items.filter(function (it) { return !before[itemKey(it)]; })[0];
        var gone = prev.items.filter(function (it) { return !after[itemKey(it)]; })[0];
        if (added && added.kind === 'peak') {
            say(state, (added.source === 'auto' ? 'Accepted the suggested peak at ' : 'Picked a peak at ') +
                where(state, added.x) + '.');
        } else if (added && added.kind === 'region') {
            say(state, 'Integrated ' + fmtX(state, added.from) + '–' + fmtX(state, added.to) + '.');
        } else if (gone) {
            say(state, 'Removed ' + (gone.kind === 'region' ? 'the integral over ' + fmtX(state, gone.from) +
                '–' + fmtX(state, gone.to) : 'the peak at ' + where(state, gone.x)) + '.');
        }
        save(state, sel);
        render(state, sel);
        declare(state, sel);
    }

    function wireAdd(state) {
        var row = state.form.querySelector('.pp-add');
        if (!row) { return; }
        state.addInput = row.querySelector('.pp-add-x');
        state.addHint = row.querySelector('.pp-add-hint');
        var add = function () {
            var raw = state.addInput.value.trim().replace(',', '.');
            var x = parseFloat(raw);
            var s = sp(state);
            if (!s) { say(state, 'The spectrum has not loaded yet.'); return; }
            var range = s.cfg.xRange || [];
            if (!isFinite(x) || x < Math.min(range[0], range[1]) || x > Math.max(range[0], range[1])) {
                say(state, 'Type a position between ' + s.format(Math.min(range[0], range[1])) + ' and ' +
                    s.format(Math.max(range[0], range[1])) + '.');
                state.addInput.focus();
                return;
            }
            var item = s.addPeakAt(x);
            if (!item) { say(state, 'There is no peak near ' + where(state, x) + '.'); return; }
            state.addInput.value = '';
            state.addInput.focus();
        };
        row.querySelector('.pp-add-btn').addEventListener('click', add);
        state.addInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); add(); }
            e.stopPropagation();           // the page binds keys for navigation
        });
    }

    function attach(state, viewer) {
        if (state.viewer === viewer) { return; }
        if (state.unsubscribe) { state.unsubscribe(); }
        state.viewer = viewer;
        var stored = readStored(state.input);
        if (stored) { viewer.setSelection(stored); }
        state.last = viewer.getSelection();
        state.unsubscribe = viewer.onSelectionChange(function (sel, info) { onChange(state, sel, info); });
        var refresh = function (e) {
            if (e.detail.field !== state.cfg.viewerField) { return; }
            if (viewer.spectrum) { viewer.spectrum.setAllowManual(state.cfg.allowManual); }
            if (viewer.state === 'error') { say(state, 'The spectrum did not load, so no peaks can be picked.'); }
            render(state, viewer.getSelection());
            declare(state, viewer.getSelection());
        };
        document.addEventListener('potato:spectrum-init', refresh);
        document.addEventListener('potato:viewer-ready', refresh);
        if (viewer.spectrum) { viewer.spectrum.setAllowManual(state.cfg.allowManual); }
        render(state, state.last);
        declare(state, state.last);
    }

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { return; }
        var cfg;
        try { cfg = JSON.parse(form.getAttribute('data-peak-config') || '{}'); }
        catch (e) { cfg = {}; }
        var state = {
            form: form, cfg: cfg, instance: instanceId(),
            input: form.querySelector('.peak-picking-input'),
            sugg: form.querySelector('.pp-suggestions'),
            suggCount: form.querySelector('.pp-sugg-count'),
            suggList: form.querySelector('.pp-sugg-list'),
            rejected: form.querySelector('.pp-rejected'),
            acceptAll: form.querySelector('.pp-accept-all'),
            rejectAll: form.querySelector('.pp-reject-all'),
            empty: form.querySelector('.pp-empty'),
            peakTable: form.querySelector('.pp-peak-table'),
            peakCount: form.querySelector('.pp-peak-count'),
            regions: form.querySelector('.pp-regions'),
            regionTable: form.querySelector('.pp-region-table'),
            message: form.querySelector('.pp-message'),
            viewer: null, last: null
        };
        STATES.set(form, state);
        form.setAttribute('tabindex', '-1');
        wireAdd(state);
        state.acceptAll.addEventListener('click', function () {
            var s = sp(state);
            if (!s) { return; }
            var pending = s.pendingSuggestions();
            if (state.cfg.maxPeaks && peakCount(s.selection()) + pending.length > state.cfg.maxPeaks) {
                say(state, 'Accepting all ' + pending.length + ' would pass the limit of ' +
                    state.cfg.maxPeaks + ' peaks.');
                return;
            }
            s.accept(pending);
            say(state, 'Accepted ' + pending.length + ' suggested peak' + (pending.length === 1 ? '' : 's') + '.');
            state.form.focus();
        });
        state.rejectAll.addEventListener('click', function () {
            var s = sp(state);
            if (!s) { return; }
            var pending = s.pendingSuggestions();
            s.reject(pending);
            say(state, 'Rejected ' + pending.length + ' suggested peak' + (pending.length === 1 ? '' : 's') + '.');
            state.form.focus();
        });
        declare(state, readStored(state.input) || {items: []});
        var existing = window.potatoViewers && window.potatoViewers[cfg.viewerField];
        if (existing) {
            attach(state, existing);
            return;
        }
        document.addEventListener('potato:viewer-registered', function (e) {
            if (e.detail.field === cfg.viewerField) { attach(state, e.detail.viewer); }
        });
        setTimeout(function () {
            if (!state.viewer) {
                say(state, 'There is no spectrum named "' + cfg.viewerField + '" on this page.');
            }
        }, 4000);
    }

    function init() {
        document.querySelectorAll('form.peak-picking').forEach(setup);
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { setTimeout(init, 0); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoPeakPicking = {init: init};
})();

/*
 * viewer_selection scheme: stores what was selected in a viewer display.
 *
 * Binds to window.potatoViewers[viewer_field] (viewer-framework.js), writes
 * the selection as JSON into the scheme's hidden input, and on load hands
 * the stored JSON back to the viewer with setSelection(), which repaints the
 * 3D view, the residue table and this list.
 *
 * With labels, the annotator picks the label for new selections first; each
 * listed item can be relabelled or removed. min_selections, max_selections
 * and unlabelled items are reported on the form's data-incomplete-reason,
 * which the page's required-field check reads.
 */
(function () {
    'use strict';
    if (window.PotatoViewerSelection) { return; }

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

    function hasContent(sel) {
        if (!sel) { return false; }
        if (sel.items && sel.items.length) { return true; }
        return Object.keys(sel).some(function (k) {
            return k !== 'viewer' && k !== 'items' && sel[k] !== null && sel[k] !== undefined && sel[k] !== '';
        });
    }

    function say(state, text) {
        state.message.textContent = text || '';
    }

    // ------------------------------------------------------------------

    function save(state, sel) {
        state.last = sel;
        state.input.value = hasContent(sel) ? JSON.stringify(sel) : '';
        state.input.setAttribute('data-modified', 'true');
        state.input.dispatchEvent(new Event('change', {bubbles: true}));
    }

    function declare(state, sel) {
        var cfg = state.cfg, reasons = [];
        var n = sel ? sel.items.length : 0;
        if (cfg.minSelections && n < cfg.minSelections) {
            reasons.push('select at least ' + cfg.minSelections + (n ? ' (' + n + ' so far)' : ''));
        }
        if (cfg.labels && cfg.labels.length && sel &&
                sel.items.some(function (it) { return !it.label; })) {
            reasons.push('give every selection a label');
        }
        if (state.viewer && state.viewer.state === 'error' && !n) {
            reasons.push('the viewer could not load');
        }
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
    }

    function render(state, sel) {
        var viewer = state.viewer, cfg = state.cfg;
        state.list.innerHTML = '';
        var items = sel ? sel.items : [];
        state.empty.hidden = items.length > 0;
        items.forEach(function (item, index) {
            var text = viewer ? viewer.describe(withoutLabel(item)) : JSON.stringify(item);
            var li = el('li', {'class': 'vs-item'});
            var colour = item.label && state.colours[item.label];
            var sw = el('span', {'class': 'vs-swatch', 'aria-hidden': 'true'});
            if (colour) { sw.style.background = colour; }
            li.appendChild(sw);
            li.appendChild(el('span', {'class': 'vs-desc'}, text));
            if (cfg.labels && cfg.labels.length) {
                var select = el('select', {'class': 'vs-item-label', 'aria-label': 'Label for ' + text});
                if (!item.label) { select.appendChild(el('option', {value: ''}, 'Choose a label')); }
                cfg.labels.forEach(function (l) {
                    var opt = el('option', {value: l.name}, l.name);
                    if (l.name === item.label) { opt.selected = true; }
                    select.appendChild(opt);
                });
                select.addEventListener('change', function () {
                    var next = viewer.getSelection();
                    if (!next.items[index]) { return; }
                    next.items[index].label = select.value || undefined;
                    if (!select.value) { delete next.items[index].label; }
                    commit(state, next);
                });
                li.appendChild(select);
            }
            var remove = el('button', {type: 'button', 'class': 'vs-remove', 'aria-label': 'Remove ' + text}, 'Remove');
            remove.addEventListener('click', function () {
                var next = viewer.getSelection();
                next.items.splice(index, 1);
                commit(state, next);
                var buttons = state.list.querySelectorAll('.vs-remove');
                var target = buttons[Math.min(index, buttons.length - 1)];
                (target || state.form.querySelector('.vs-label[aria-checked="true"]') || state.form).focus();
                say(state, 'Removed ' + text + '.');
            });
            li.appendChild(remove);
            state.list.appendChild(li);
        });
        var ctx = sel && viewer && viewer._adapter().describeContext ? viewer._adapter().describeContext(sel) : '';
        state.context.hidden = !ctx;
        state.context.textContent = ctx ? 'Current ' + ctx.replace(/^view /, 'view: ') : '';
        var count = items.length + ' selected';
        if (cfg.maxSelections) { count += ' of at most ' + cfg.maxSelections; }
        if (cfg.minSelections) { count += ' (at least ' + cfg.minSelections + ' needed)'; }
        state.count.textContent = items.length || cfg.minSelections || cfg.maxSelections ? count : '';
    }

    function withoutLabel(item) {
        var copy = {};
        Object.keys(item).forEach(function (k) { if (k !== 'label') { copy[k] = item[k]; } });
        return copy;
    }

    /* A change made from this scheme's own list. */
    function commit(state, next) {
        state.committing = true;
        state.viewer.setSelection(next);      // repaints the viewer; source 'api'
        state.committing = false;
        var sel = state.viewer.getSelection();
        save(state, sel);
        render(state, sel);
        declare(state, sel);
    }

    function onChange(state, sel, info) {
        if (info && info.source === 'api') {
            if (!state.committing) { say(state, ''); }   // the last message described a different state
            render(state, sel);
            declare(state, sel);
            return;
        }
        var cfg = state.cfg, prev = state.last || {items: []};
        if (cfg.maxSelections && sel.items.length > cfg.maxSelections &&
                sel.items.length > prev.items.length) {
            say(state, 'At most ' + cfg.maxSelections + ' selection' +
                (cfg.maxSelections === 1 ? '' : 's') + ' allowed. Remove one first.');
            var keep = JSON.parse(JSON.stringify(prev));
            if (sel.locus !== undefined) { keep.locus = sel.locus; }
            state.committing = true;
            state.viewer.setSelection(keep);
            state.committing = false;
            if (hasContent(keep) && keep.locus !== prev.locus) { save(state, state.viewer.getSelection()); }
            return;
        }
        var relabel = false;
        if (state.activeLabel) {
            sel.items.forEach(function (it) {
                if (!it.label) { it.label = state.activeLabel; relabel = true; }
            });
        }
        if (relabel) {
            state.committing = true;
            state.viewer.setSelection(sel);
            state.committing = false;
            sel = state.viewer.getSelection();
        }
        if (sel.items.length > prev.items.length) {
            say(state, 'Selected ' + state.viewer.describe(withoutLabel(sel.items[sel.items.length - 1])) + '.');
        } else if (sel.items.length < prev.items.length) {
            var kept = {};
            sel.items.forEach(function (it) { kept[state.viewer.keyOf(it)] = true; });
            var gone = prev.items.filter(function (it) { return !kept[state.viewer.keyOf(it)]; })[0];
            say(state, gone ? 'Removed ' + state.viewer.describe(withoutLabel(gone)) + '.' : '');
        }
        save(state, sel);
        render(state, sel);
        declare(state, sel);
    }

    function attach(state, viewer) {
        if (state.viewer === viewer) { return; }
        if (state.unsubscribe) { state.unsubscribe(); }
        state.viewer = viewer;
        var colours = {};
        (state.cfg.labels || []).forEach(function (l) { colours[l.name] = l.color; });
        state.colours = colours;
        viewer.setLabelColors(colours);
        var stored = readStored(state.input);
        if (stored) {
            viewer.setSelection(stored);
        }
        state.last = viewer.getSelection();
        state.unsubscribe = viewer.onSelectionChange(function (sel, info) { onChange(state, sel, info); });
        render(state, state.last);
        declare(state, state.last);
        var whenReady = function (e) {
            if (e.detail.field !== state.cfg.viewerField) { return; }
            if (viewer.state === 'error') { say(state, 'The viewer did not load, so nothing can be selected here.'); }
            declare(state, viewer.getSelection());
        };
        document.addEventListener('potato:viewer-ready', whenReady);
    }

    function wireLabels(state) {
        var group = state.form.querySelector('.vs-labels');
        if (!group) { return; }
        var buttons = Array.prototype.slice.call(group.querySelectorAll('.vs-label'));
        function choose(btn, focus) {
            buttons.forEach(function (b) {
                var on = b === btn;
                b.setAttribute('aria-checked', on ? 'true' : 'false');
                b.setAttribute('tabindex', on ? '0' : '-1');
            });
            state.activeLabel = btn.getAttribute('data-label');
            if (focus) { btn.focus(); }
        }
        buttons.forEach(function (b) {
            b.addEventListener('click', function () { choose(b, false); });
        });
        group.addEventListener('keydown', function (e) {
            var i = buttons.indexOf(document.activeElement);
            if (i < 0) { return; }
            var next = null;
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { next = buttons[(i + 1) % buttons.length]; }
            else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { next = buttons[(i - 1 + buttons.length) % buttons.length]; }
            if (!next) { return; }
            e.preventDefault();
            e.stopPropagation();       // the page uses the arrows for previous/next item
            choose(next, true);
        });
        var first = group.querySelector('.vs-label[aria-checked="true"]') || buttons[0];
        if (first) { state.activeLabel = first.getAttribute('data-label'); }
    }

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { return; }
        var cfg;
        try { cfg = JSON.parse(form.getAttribute('data-selection-config') || '{}'); }
        catch (e) { cfg = {}; }
        var state = {
            form: form, cfg: cfg, instance: instanceId(),
            input: form.querySelector('.viewer-selection-input'),
            list: form.querySelector('.vs-list'),
            empty: form.querySelector('.vs-empty'),
            count: form.querySelector('.vs-count'),
            context: form.querySelector('.vs-context'),
            message: form.querySelector('.vs-message'),
            activeLabel: null, viewer: null, colours: {}, last: null
        };
        STATES.set(form, state);
        wireLabels(state);
        declare(state, readStored(state.input) || {items: []});
        var existing = window.potatoViewers && window.potatoViewers[cfg.viewerField];
        if (existing) {
            attach(state, existing);
            return;
        }
        document.addEventListener('potato:viewer-registered', function (e) {
            if (e.detail.field === cfg.viewerField) { attach(state, e.detail.viewer); }
        });
        // A page with no such viewer (a phase page, or a misnamed field).
        setTimeout(function () {
            if (!state.viewer) {
                say(state, 'There is no viewer named "' + cfg.viewerField + '" on this page.');
            }
        }, 4000);
    }

    function init() {
        document.querySelectorAll('form.viewer-selection').forEach(setup);
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { setTimeout(init, 0); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoViewerSelection = {init: init};
})();

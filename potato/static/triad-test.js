/*
 * Triad tests (annotation_type: triad_test).
 *
 * Shows the triads of one scheme one at a time ("Triad 3 of 13") and asks
 * which item is most different. Choosing moves on to the next unanswered
 * triad; Previous and Next revisit any of them. The keys 1, 2 and 3 choose
 * a position while the widget has focus.
 *
 * The plan (which triads, in what order, which item where) comes from
 * triad-design.js, seeded by participant, item and scheme, so a reload shows
 * the same sequence. Once answered, the stored triads are used as they are,
 * so the record always says what this participant saw.
 *
 * The answer is the scheme's hidden input, as JSON:
 *   {"design": "steiner", "triads": [[a, b, c, odd_or_null], ...]}
 */
(function () {
    'use strict';
    if (window.PotatoTriadTest) { return; }

    var STATES = new WeakMap();
    var ADVANCE_MS = 280;

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
        if (input && input.value) { return input.value; }
        return (window.currentInstance && window.currentInstance.id) || '__phase_page__';
    }

    function userId() {
        return (window.config && window.config.username) || '';
    }

    function readStored(form) {
        var h = form.querySelector('.triad-test-input');
        if (h && h.value) {
            try {
                var v = JSON.parse(h.value);
                if (v && Array.isArray(v.triads) && v.triads.length) { return v; }
            } catch (e) { /* fall through */ }
        }
        return null;
    }

    function domainFromItem(cfg) {
        // Always ask: window.currentInstanceData is only refreshed on pages
        // with card_sort and similar schemes, and may still hold the last item.
        var url = (window.potatoUrl ? window.potatoUrl('/api/instance_data') : '/api/instance_data');
        return fetch(url, {credentials: 'same-origin'}).then(function (r) {
            if (!r.ok) { throw new Error('instance data ' + r.status); }
            return r.json();
        }).then(function (d) {
            var raw = d ? d[cfg.items_field || 'items'] : null;
            if (!Array.isArray(raw)) {
                throw new Error('the item has no list under "' + (cfg.items_field || 'items') + '"');
            }
            return window.PotatoTriadDesign.domainItems(raw);
        });
    }

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { return; }
        if (prior && prior.timer) { clearTimeout(prior.timer); }
        var cfg = JSON.parse(form.getAttribute('data-triad-config') || '{}');
        var state = {instance: instanceId(), cfg: cfg, form: form, root: form.querySelector('.tt-root'),
                     triads: null, design: null, current: 0, timer: null};
        STATES.set(form, state);
        var stored = readStored(form);
        if (stored) {
            state.triads = stored.triads.map(function (t) {
                return [String(t[0]), String(t[1]), String(t[2]), t[3] == null ? null : String(t[3])];
            });
            state.design = stored.design || null;
            state.current = firstOpen(state);
            render(state);
            return;
        }
        var domain = cfg.labels ? Promise.resolve(cfg.labels) : domainFromItem(cfg);
        domain.then(function (items) {
            if (STATES.get(form) !== state) { return; }
            var plan = window.PotatoTriadDesign.plan(items, cfg.schema, userId(), state.instance,
                                                     cfg.design, cfg.max_triads);
            state.design = plan.design;
            state.triads = plan.triads.map(function (t) { return t.concat([null]); });
            state.current = 0;
            render(state);
        }).catch(function (err) {
            console.error('[triad-test]', err);
            state.root.innerHTML = '';
            state.root.appendChild(el('p', {className: 'tt-error', role: 'alert',
                text: 'The triads for this item could not be built (' + err.message +
                      '). Tell the researcher.'}));
        });
    }

    function answered(state) {
        return state.triads.filter(function (t) { return t[3] !== null; }).length;
    }

    function firstOpen(state) {
        for (var i = 0; i < state.triads.length; i++) { if (state.triads[i][3] === null) { return i; } }
        return state.triads.length - 1;
    }

    function nextOpen(state, from) {
        var n = state.triads.length;
        for (var k = 1; k <= n; k++) {
            var i = (from + k) % n;
            if (state.triads[i][3] === null) { return i; }
        }
        return -1;
    }

    function save(state) {
        var h = state.form.querySelector('.triad-test-input');
        var any = answered(state) > 0;
        h.value = any ? JSON.stringify({design: state.design, triads: state.triads}) : '';
        h.setAttribute('data-modified', 'true');
        h.dispatchEvent(new Event('change', {bubbles: true}));
        declare(state);
    }

    function declare(state) {
        var left = state.triads.length - answered(state);
        if (left) {
            state.form.setAttribute('data-incomplete-reason',
                'answer ' + left + ' more triad' + (left === 1 ? '' : 's'));
        } else {
            state.form.removeAttribute('data-incomplete-reason');
        }
    }

    function choose(state, position) {
        var triad = state.triads[state.current];
        if (!triad) { return; }
        triad[3] = triad[position];
        save(state);
        refresh(state);
        if (state.timer) { clearTimeout(state.timer); }
        var next = nextOpen(state, state.current);
        if (next >= 0) {
            state.timer = setTimeout(function () {
                state.timer = null;
                go(state, next, true);
            }, ADVANCE_MS);
        }
    }

    function go(state, index, keepFocus) {
        if (index < 0 || index >= state.triads.length) { return; }
        if (state.timer) { clearTimeout(state.timer); state.timer = null; }
        state.current = index;
        refresh(state);
        if (keepFocus && state.root.contains(document.activeElement)) {
            var chosen = state.root.querySelector('.tt-option[aria-checked="true"]') ||
                         state.root.querySelector('.tt-option');
            if (chosen) { chosen.focus(); }
        }
    }

    function render(state) {
        var root = state.root;
        root.innerHTML = '';
        state.progress = el('p', {className: 'tt-progress', 'aria-live': 'polite'});
        state.bar = el('div', {className: 'tt-bar', 'aria-hidden': 'true'}, [el('span', {className: 'tt-bar-fill'})]);
        root.appendChild(el('div', {className: 'tt-head'}, [state.progress, state.bar]));
        root.appendChild(el('p', {className: 'tt-question', id: state.cfg.schema + '-tt-q',
            text: state.cfg.question}));
        state.options = el('div', {className: 'tt-options', role: 'radiogroup',
            'aria-labelledby': state.cfg.schema + '-tt-q'});
        [0, 1, 2].forEach(function (p) {
            state.options.appendChild(el('button', {type: 'button', role: 'radio', className: 'tt-option',
                'data-position': String(p), 'aria-checked': 'false',
                onclick: function () { choose(state, p); }},
                [el('span', {className: 'tt-key', 'aria-hidden': 'true', text: String(p + 1)}),
                 el('span', {className: 'tt-item'})]));
        });
        root.appendChild(state.options);
        state.prev = el('button', {type: 'button', className: 'tt-prev', text: '← Previous triad',
            onclick: function () { go(state, state.current - 1); }});
        state.next = el('button', {type: 'button', className: 'tt-next', text: 'Next triad →',
            onclick: function () { go(state, state.current + 1); }});
        root.appendChild(el('div', {className: 'tt-nav'}, [state.prev, state.next]));
        state.done = el('p', {className: 'tt-done', role: 'status'});
        root.appendChild(state.done);
        root.appendChild(el('p', {className: 'tt-keys', text: 'Keys: 1, 2 or 3 chooses an item.'}));
        refresh(state);
        declare(state);
    }

    function refresh(state) {
        var t = state.triads[state.current], n = state.triads.length, k = answered(state);
        state.progress.textContent = 'Triad ' + (state.current + 1) + ' of ' + n +
            ' · ' + k + ' answered';
        state.bar.firstChild.style.width = (n ? (100 * k / n) : 0) + '%';
        state.options.querySelectorAll('.tt-option').forEach(function (b) {
            var p = parseInt(b.getAttribute('data-position'), 10);
            b.querySelector('.tt-item').textContent = t[p];
            b.setAttribute('aria-checked', t[3] !== null && t[3] === t[p] ? 'true' : 'false');
            b.setAttribute('aria-label', (p + 1) + ': ' + t[p]);
        });
        state.prev.disabled = state.current === 0;
        state.next.disabled = state.current === n - 1;
        var complete = k === n;
        state.done.hidden = !complete;
        state.done.textContent = complete ? 'All ' + n + ' triads answered.' : '';
    }

    function stateFor(e) {
        var form = e.target && e.target.closest && e.target.closest('form.triad-test');
        if (!form) { return null; }
        var state = STATES.get(form);
        return state && state.triads ? state : null;
    }

    document.addEventListener('keydown', function (e) {
        if (e.ctrlKey || e.metaKey || e.altKey) { return; }
        var state = stateFor(e);
        if (!state || !/^[123]$/.test(e.key)) { return; }
        e.preventDefault();
        e.stopPropagation();
        choose(state, parseInt(e.key, 10) - 1);
    }, true);
    // Potato's label shortcuts fire on keyup; these keys are ours here.
    document.addEventListener('keyup', function (e) {
        if (stateFor(e) && /^[123]$/.test(e.key)) { e.stopPropagation(); }
    }, true);

    function init() {
        document.querySelectorAll('form.triad-test').forEach(setup);
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { init(); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoTriadTest = {init: init};
})();

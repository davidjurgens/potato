/*
 * Free lists (annotation_type: free_list).
 *
 * The participant types items one at a time; Enter adds the item to the end
 * of the list. Order is data, so items cannot be reordered. Items can be
 * deleted, and a deletion undone (back to the same place, with its time).
 *
 * The answer is the scheme's hidden input, as JSON:
 *   {"items": [...], "timings_ms": [...], "elapsed_ms": n, "time_up": bool,
 *    "started": bool}
 * timings_ms[i] is the time from the start of the list to the moment item i
 * was added. The clock starts on the first focus of the entry box, or with
 * the Start button when there is a time limit, and runs only while this
 * page is showing: on returning to an item it resumes from elapsed_ms.
 *
 * Completeness (min_items, a timed list not started) is declared on the
 * form's data-incomplete-reason, which validateRequiredFields reads.
 */
(function () {
    'use strict';
    if (window.PotatoFreeList) { return; }

    var STATES = new WeakMap();

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

    function readStored(form) {
        var h = form.querySelector('.free-list-input');
        if (h && h.value) {
            try {
                var v = JSON.parse(h.value);
                if (v && Array.isArray(v.items)) { return v; }
            } catch (e) { /* fall through */ }
        }
        return null;
    }

    function now() {
        return (window.performance && performance.now) ? performance.now() : Date.now();
    }

    function key(text) {
        return text.trim().replace(/\s+/g, ' ').toLowerCase();
    }

    function fmtClock(ms) {
        var s = Math.max(0, Math.ceil(ms / 1000));
        return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
    }

    // ------------------------------------------------------------------

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { return; }
        if (prior) { stopClock(prior); }
        var cfg = JSON.parse(form.getAttribute('data-free-list-config') || '{}');
        var stored = readStored(form);
        var state = {
            instance: instanceId(), cfg: cfg, form: form,
            root: form.querySelector('.fl-root'),
            items: stored ? stored.items.map(String) : [],
            timings: stored && Array.isArray(stored.timings_ms) ? stored.timings_ms.slice() : [],
            elapsedBefore: stored ? Number(stored.elapsed_ms || 0) : 0,
            timeUp: !!(stored && stored.time_up),
            started: !!(stored && (stored.started || stored.items.length || stored.elapsed_ms)),
            runningSince: null, ticker: null, undo: []
        };
        while (state.timings.length < state.items.length) { state.timings.push(null); }
        if (!state.elapsedBefore && state.timings.length) {
            state.elapsedBefore = Math.max.apply(null, state.timings.map(Number).filter(isFinite).concat([0]));
        }
        STATES.set(form, state);
        render(state);
        if (state.started && cfg.time_limit_s && !state.timeUp) { startClock(state); }
        declare(state);
    }

    function elapsed(state) {
        return state.elapsedBefore + (state.runningSince === null ? 0 : now() - state.runningSince);
    }

    function startClock(state) {
        if (state.runningSince !== null || state.timeUp) { return; }
        state.started = true;
        state.runningSince = now();
        if (state.cfg.time_limit_s) {
            state.ticker = setInterval(function () { tick(state); }, 250);
            tick(state);
        }
    }

    function stopClock(state) {
        if (state.runningSince !== null) {
            state.elapsedBefore = elapsed(state);
            state.runningSince = null;
        }
        if (state.ticker) { clearInterval(state.ticker); state.ticker = null; }
    }

    function remaining(state) {
        return state.cfg.time_limit_s * 1000 - elapsed(state);
    }

    function tick(state) {
        if (!document.body.contains(state.form) || STATES.get(state.form) !== state) {
            stopClock(state);
            return;
        }
        var left = remaining(state);
        if (state.clock) { state.clock.textContent = fmtClock(left); }
        if (state.clockWrap) { state.clockWrap.classList.toggle('fl-clock-low', left <= 10000); }
        if (left <= 0) {
            stopClock(state);
            state.elapsedBefore = state.cfg.time_limit_s * 1000;
            state.timeUp = true;
            save(state);
            render(state);
            return;
        }
        // Keep the saved time current, so leaving the page does not hand
        // the participant the seconds since their last item.
        var slot = Math.floor(elapsed(state) / 5000);
        if (slot !== state.savedSlot) {
            state.savedSlot = slot;
            save(state);
        }
    }

    function locked(state) {
        return state.timeUp || (!!state.cfg.time_limit_s && !state.started);
    }

    function full(state) {
        return !!state.cfg.max_items && state.items.length >= state.cfg.max_items;
    }

    function say(state, text) {
        if (state.status) { state.status.textContent = text || ''; }
    }

    function add(state) {
        var input = state.entry;
        var text = (input.value || '').trim().replace(/\s+/g, ' ');
        if (!text) { return; }
        if (locked(state)) { return; }
        if (full(state)) {
            say(state, 'The list is full (' + state.cfg.max_items + ' items).');
            return;
        }
        if (!state.cfg.allow_duplicates &&
                state.items.some(function (it) { return key(it) === key(text); })) {
            say(state, '“' + text + '” is already on your list.');
            input.select();
            return;
        }
        startClock(state);
        state.items.push(text);
        state.timings.push(Math.round(elapsed(state)));
        input.value = '';
        say(state, 'Added “' + text + '”.');
        save(state);
        renderList(state);
        input.focus();
    }

    function remove(state, index) {
        if (locked(state)) { return; }
        var text = state.items[index];
        state.undo.push({index: index, item: text, timing: state.timings[index]});
        state.items.splice(index, 1);
        state.timings.splice(index, 1);
        save(state);
        renderList(state);
        say(state, 'Removed “' + text + '”.');
        if (state.undoBtn) { state.undoBtn.focus(); }
    }

    function undo(state) {
        var last = state.undo.pop();
        if (!last || locked(state)) { return; }
        var at = Math.min(last.index, state.items.length);
        state.items.splice(at, 0, last.item);
        state.timings.splice(at, 0, last.timing);
        save(state);
        renderList(state);
        say(state, 'Restored “' + last.item + '”.');
        if (state.entry && !state.entry.disabled) { state.entry.focus(); }
    }

    function save(state) {
        var h = state.form.querySelector('.free-list-input');
        var data = {items: state.items.slice(), timings_ms: state.timings.slice(),
                    elapsed_ms: Math.round(elapsed(state)), time_up: state.timeUp,
                    started: state.started};
        var keep = state.items.length || state.timeUp || (state.cfg.time_limit_s && state.started);
        h.value = keep ? JSON.stringify(data) : '';
        h.setAttribute('data-modified', 'true');
        h.dispatchEvent(new Event('change', {bubbles: true}));
        declare(state);
    }

    function declare(state) {
        var cfg = state.cfg, reasons = [];
        if (cfg.time_limit_s && !state.started) {
            reasons.push('start the timer and list your answers');
        } else if (cfg.min_items && state.items.length < cfg.min_items && !state.timeUp) {
            reasons.push('list at least ' + cfg.min_items + ' item' + (cfg.min_items === 1 ? '' : 's'));
        } else if (!state.items.length && !state.timeUp) {
            reasons.push('list at least one item');
        }
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
        if (state.count) { state.count.textContent = countText(state); }
    }

    function countText(state) {
        var n = state.items.length, cfg = state.cfg;
        var text = n + (n === 1 ? ' item' : ' items');
        if (cfg.min_items && cfg.max_items) { text += ' (' + cfg.min_items + ' to ' + cfg.max_items + ')'; }
        else if (cfg.min_items) { text += ' (at least ' + cfg.min_items + ')'; }
        else if (cfg.max_items) { text += ' (at most ' + cfg.max_items + ')'; }
        return text;
    }

    // ------------------------------------------------------------------

    function render(state) {
        var cfg = state.cfg, root = state.root;
        root.innerHTML = '';
        var entryId = root.getAttribute('data-entry-id') || (cfg.schema + '-fl-entry');
        if (cfg.time_limit_s) {
            state.clock = el('span', {className: 'fl-clock-value', role: 'timer',
                'aria-live': 'off', text: fmtClock(state.timeUp ? 0 : remaining(state))});
            state.clockWrap = el('div', {className: 'fl-clock'}, [
                el('span', {className: 'fl-clock-label', text: 'Time left '}), state.clock]);
            var head = el('div', {className: 'fl-timed'}, [state.clockWrap]);
            if (!state.started && !state.timeUp) {
                head.appendChild(el('button', {type: 'button', className: 'fl-start',
                    text: 'Start (' + fmtClock(cfg.time_limit_s * 1000) + ')',
                    onclick: function () {
                        startClock(state);
                        save(state);
                        render(state);
                        if (state.entry) { state.entry.focus(); }
                    }}));
            }
            root.appendChild(head);
        }
        state.entry = el('input', {type: 'text', className: 'fl-entry', id: entryId,
            autocomplete: 'off', spellcheck: 'false', maxlength: String(cfg.max_length || 200),
            placeholder: cfg.placeholder || ''});
        state.entry.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.isComposing) {
                e.preventDefault();
                e.stopPropagation();
                add(state);
            }
        });
        state.entry.addEventListener('focus', function () {
            if (!cfg.time_limit_s) { startClock(state); }
        });
        state.addBtn = el('button', {type: 'button', className: 'fl-add', text: 'Add',
            onclick: function () { add(state); }});
        root.appendChild(el('label', {className: 'fl-entry-label', 'for': entryId, text: 'Add an item'}));
        root.appendChild(el('div', {className: 'fl-entry-row'}, [state.entry, state.addBtn]));
        state.status = el('p', {className: 'fl-status', 'aria-live': 'polite'});
        root.appendChild(state.status);
        state.list = el('ol', {className: 'fl-items', 'aria-label': 'Your list'});
        root.appendChild(state.list);
        state.undoBtn = el('button', {type: 'button', className: 'fl-undo', text: 'Undo delete',
            onclick: function () { undo(state); }});
        state.count = el('p', {className: 'fl-count'});
        root.appendChild(el('div', {className: 'fl-footer'}, [state.count, state.undoBtn]));
        if (state.timeUp) {
            root.appendChild(el('p', {className: 'fl-timeup', role: 'status',
                text: 'Time is up. Your list has been saved.'}));
        }
        renderList(state);
        declare(state);
    }

    function renderList(state) {
        var lock = locked(state);
        state.list.innerHTML = '';
        state.items.forEach(function (text, i) {
            var del = el('button', {type: 'button', className: 'fl-delete',
                'aria-label': 'Delete “' + text + '”', title: 'Delete', text: '×',
                onclick: function () { remove(state, i); }});
            del.disabled = lock;
            state.list.appendChild(el('li', {className: 'fl-item'}, [
                el('span', {className: 'fl-item-text', text: text}), del]));
        });
        state.list.hidden = !state.items.length;
        var stopAdding = lock || full(state);
        state.entry.disabled = stopAdding;
        state.addBtn.disabled = stopAdding;
        if (full(state) && !lock) { state.entry.placeholder = 'The list is full'; }
        else { state.entry.placeholder = state.cfg.placeholder || ''; }
        state.undoBtn.hidden = !state.undo.length || lock;
        declare(state);
    }

    function init() {
        document.querySelectorAll('form.free-list').forEach(setup);
    }

    // Leaving the page (or the tab) pauses the clock; elapsed_ms is saved.
    document.addEventListener('visibilitychange', function () {
        document.querySelectorAll('form.free-list').forEach(function (form) {
            var state = STATES.get(form);
            if (!state || !state.started || state.timeUp) { return; }
            if (document.hidden) {
                stopClock(state);
                if (state.items.length) { save(state); }
            } else if (state.cfg.time_limit_s) {
                startClock(state);
            }
        });
    });

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { init(); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoFreeList = {init: init};
})();

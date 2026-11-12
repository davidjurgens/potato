/**
 * Sub-agent run-tree interaction (D6).
 *
 * The agent_trace display renders a run-tree sidebar (nav.run-tree) when the
 * item carries a run_tree (see trace_converter/base.py). Clicking a node
 * filters the step list to that run's turns (including descendant runs) and
 * scrolls the first matching step into view; clicking the active node again
 * clears the filter.
 *
 * Pure display behavior — no annotation state, so nothing here touches the
 * persistence pipeline. Event delegation on document so it survives instance
 * navigation (full page reload) and dynamic re-renders alike.
 */
(function () {
    'use strict';

    function clearFilter(display) {
        display.querySelectorAll('.rt-node.rt-active').forEach(function (n) {
            n.classList.remove('rt-active');
            n.setAttribute('aria-pressed', 'false');
        });
        display.querySelectorAll('.agent-trace-step.rt-dim, .agent-trace-step.rt-focus')
            .forEach(function (s) { s.classList.remove('rt-dim', 'rt-focus'); });
    }

    function applyFilter(display, node) {
        var ids = [node.getAttribute('data-run-id')];
        var desc = node.getAttribute('data-run-desc');
        if (desc) ids = ids.concat(desc.split(','));
        var idSet = {};
        ids.forEach(function (id) { if (id) idSet[id] = true; });

        node.classList.add('rt-active');
        node.setAttribute('aria-pressed', 'true');

        var first = null;
        display.querySelectorAll('.agent-trace-step').forEach(function (step) {
            var rid = step.getAttribute('data-run-id');
            var match = rid && idSet[rid];
            step.classList.toggle('rt-dim', !match);
            step.classList.toggle('rt-focus', !!match);
            if (match && !first) first = step;
        });
        if (first && typeof first.scrollIntoView === 'function') {
            first.scrollIntoView({behavior: 'smooth', block: 'nearest'});
        }
    }

    document.addEventListener('click', function (e) {
        var node = e.target.closest ? e.target.closest('.rt-node') : null;
        if (!node) return;
        var display = node.closest('.agent-trace-display');
        if (!display) return;
        var wasActive = node.classList.contains('rt-active');
        clearFilter(display);
        if (!wasActive) applyFilter(display, node);
    });
})();

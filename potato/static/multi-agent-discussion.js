/**
 * Multi-Agent Discussion display: client-side agent filtering.
 *
 * Legend chips (.mad-legend-chip) toggle visibility of that agent's turns
 * (matched via data-agent-id). Pure display behavior — no annotation state
 * is touched, so this module has no interaction with the persistence
 * pipeline. Uses event delegation so it works after full-page navigation
 * without re-initialization.
 */
(function () {
    'use strict';

    document.addEventListener('click', function (e) {
        const chip = e.target.closest('.mad-legend-chip');
        if (!chip) return;
        e.preventDefault();

        const agentId = chip.dataset.agentId;
        const container = chip.closest('.multi-agent-discussion');
        if (!container || !agentId) return;

        const nowPressed = chip.getAttribute('aria-pressed') !== 'true';
        chip.setAttribute('aria-pressed', String(nowPressed));

        container.querySelectorAll('.mad-turn').forEach(function (turn) {
            if (turn.dataset.agentId === agentId) {
                turn.classList.toggle('mad-hidden', !nowPressed);
            }
        });
    });
})();

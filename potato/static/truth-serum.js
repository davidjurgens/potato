/**
 * Truth Serum — surprisingly-popular prediction widget.
 *
 * After the annotator commits a label on the configured schema, a small card
 * asks one micro-question: "What percentage of other annotators will choose
 * the same label as you?" The (label, prediction) pair powers
 * surprisingly-popular verdicts and calibration scoring server-side.
 *
 * Loaded conditionally by base_template_v2.html when truth_serum.enabled;
 * configuration arrives via window.truthSerumConfig = {schema, question}.
 * Positioned bottom-LEFT (Boundary Lab owns bottom-right, and both can be
 * enabled at once). No annotation.js changes: label selection is observed via
 * document-level capture listeners.
 */
(function () {
    'use strict';

    var cfg = window.truthSerumConfig;
    if (!cfg || !cfg.schema) return;

    var state = {
        panel: null,
        timer: null,
        seq: 0,
        savedLabel: null,    // label the stored prediction was made for
        savedPct: null
    };

    function esc(s) {
        var div = document.createElement('div');
        div.textContent = s == null ? '' : String(s);
        return div.innerHTML;
    }

    function instanceId() {
        var el = document.getElementById('instance_id');
        return el ? el.value : null;
    }

    function selectedLabel() {
        var checked = document.querySelector(
            'input.annotation-input[schema="' + cfg.schema + '"]:checked');
        return checked ? checked.getAttribute('label_name') : null;
    }

    function ensurePanel() {
        if (state.panel) return state.panel;
        var panel = document.createElement('div');
        panel.id = 'truth-serum-panel';
        panel.className = 'ts-panel ts-hidden';
        panel.setAttribute('role', 'complementary');
        panel.setAttribute('aria-label', 'Agreement prediction');
        panel.setAttribute('aria-live', 'polite');
        document.body.appendChild(panel);
        state.panel = panel;
        return panel;
    }

    function hidePanel() {
        if (state.panel) state.panel.classList.add('ts-hidden');
    }

    function showPanel() {
        ensurePanel().classList.remove('ts-hidden');
    }

    // ------------------------------------------------------------- render --
    function renderAsk(label, initialPct) {
        var pct = typeof initialPct === 'number' ? initialPct : 50;
        var panel = ensurePanel();
        panel.innerHTML =
            '<div class="ts-header">' +
            '  <span class="ts-title">&#127919; Call the crowd</span>' +
            '  <button type="button" class="ts-close" aria-label="Dismiss prediction">&times;</button>' +
            '</div>' +
            '<div class="ts-body">' +
            '  <div class="ts-question">You chose <strong>' + esc(label) + '</strong>. ' +
                 esc(cfg.question) + '</div>' +
            '  <div class="ts-slider-row">' +
            '    <input type="range" class="ts-slider" min="0" max="100" step="5" value="' + pct + '"' +
            '           aria-label="Predicted percentage of annotators agreeing with you">' +
            '    <output class="ts-value">' + pct + '%</output>' +
            '  </div>' +
            '  <div class="ts-actions">' +
            '    <button type="button" class="ts-save">Lock it in</button>' +
            '  </div>' +
            '  <div class="ts-error ts-hidden"></div>' +
            '</div>' +
            '<div class="ts-footer">Powers surprisingly-popular verdicts &middot; no gold labels needed</div>';

        var slider = panel.querySelector('.ts-slider');
        var output = panel.querySelector('.ts-value');
        slider.addEventListener('input', function () {
            output.textContent = slider.value + '%';
        });
        panel.querySelector('.ts-close').addEventListener('click', hidePanel);
        panel.querySelector('.ts-save').addEventListener('click', function () {
            savePrediction(label, parseInt(slider.value, 10), panel);
        });
        showPanel();
    }

    function renderChip(label, pct) {
        var panel = ensurePanel();
        panel.innerHTML =
            '<div class="ts-chip">' +
            '  <span class="ts-chip-mark">&#10003;</span>' +
            '  <span>Predicted <strong>' + pct + '%</strong> will also say ' + esc(label) + '</span>' +
            '  <button type="button" class="ts-chip-edit">change</button>' +
            '</div>';
        panel.querySelector('.ts-chip-edit').addEventListener('click', function () {
            renderAsk(label, pct);
        });
        showPanel();
    }

    // ---------------------------------------------------------------- api --
    function savePrediction(label, pct, panel) {
        fetch('/truth_serum/api/predict', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                instance_id: instanceId(),
                label: label,
                predicted_pct: pct
            })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }).then(function () {
            state.savedLabel = label;
            state.savedPct = pct;
            renderChip(label, pct);
        }).catch(function () {
            var el = panel.querySelector('.ts-error');
            if (el) {
                el.textContent = 'Could not save — check your connection and try again.';
                el.classList.remove('ts-hidden');
            }
        });
    }

    function onLabelSettled() {
        var label = selectedLabel();
        if (!label) { hidePanel(); return; }
        if (label === state.savedLabel && state.savedPct != null) {
            renderChip(label, state.savedPct);
        } else {
            // Label changed (or first selection): ask again, seeded with the
            // previous prediction when one exists.
            renderAsk(label, state.savedPct);
        }
    }

    function schedule() {
        clearTimeout(state.timer);
        state.timer = setTimeout(onLabelSettled, 700);
    }

    function isTargetInput(el) {
        return el && el.matches &&
            el.matches('input.annotation-input') &&
            el.getAttribute('schema') === cfg.schema;
    }

    document.addEventListener('change', function (e) {
        if (isTargetInput(e.target)) schedule();
    }, true);
    document.addEventListener('click', function (e) {
        if (isTargetInput(e.target)) schedule();
    }, true);

    // Restore state for an already-labeled instance (navigation back).
    function restore() {
        var id = instanceId();
        if (!id) return;
        fetch('/truth_serum/api/mine?instance_id=' + encodeURIComponent(id))
            .then(function (r) { return r.ok ? r.json() : { prediction: null }; })
            .then(function (data) {
                if (!data.prediction) return;
                state.savedLabel = data.prediction.label;
                state.savedPct = data.prediction.predicted_pct;
                // Only surface the chip once the restored radio matches.
                var label = selectedLabel();
                if (label && label === state.savedLabel) {
                    renderChip(state.savedLabel, state.savedPct);
                }
            })
            .catch(function () { /* enhancement only; stay quiet */ });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            setTimeout(restore, 1200); // after populateInputValues restores radios
        });
    } else {
        setTimeout(restore, 1200);
    }
})();

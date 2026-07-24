/**
 * Turn-Level Annotation frontend (shared module).
 *
 * Handles ALL turn-level schemas on the page — deliberately a single module
 * rather than per-schema inline IIFEs, to avoid the IIFE-overwrite bug
 * pattern (inline script init clobbering server-restored values).
 *
 * Contract with annotation.js (see internal/annotation-persistence.md):
 *  - The real state lives in one hidden input per schema:
 *      <input class="annotation-data-input turn-anno-hidden" name="{schema}">
 *    saveAnnotations() picks it up as `{schema}:::_data`; the server restores
 *    it via BeautifulSoup with `value` + `data-server-set="true"`.
 *  - Slot widgets (.ta-chip / .ta-range / .ta-select / .ta-text / .ta-number)
 *    are proxies only: no `annotation-input` class, no schema/label_name
 *    attributes, so the four global persistence functions ignore them.
 *  - clearAllFormInputs() calls window.turnAnnotations.refresh() after its
 *    global input reset so proxy visual state is re-seeded from the hidden
 *    inputs (which survive the reset when server-set).
 *
 * Stored value format (versioned):
 *   {"v":1,"schema_type":"multiselect",
 *    "turns":{"t3":{"values":["hallucination"],"speaker":"...","step_type":"..."}}}
 */
(function () {
    'use strict';

    // stateBySchema[schema] = { schemaType, turns: {tid: {value|values, ...snapshot}} }
    let stateBySchema = {};
    let saveTimer = null;
    const textTimers = {};

    function hiddenInputs() {
        return document.querySelectorAll('input.turn-anno-hidden');
    }

    function hiddenFor(schema) {
        return document.querySelector('input.turn-anno-hidden[data-schema-name="' + CSS.escape(schema) + '"]');
    }

    // ------------------------------------------------------------------
    // Seeding (server value -> state) and serialization (state -> input)
    // ------------------------------------------------------------------

    function seedState() {
        stateBySchema = {};
        hiddenInputs().forEach(function (input) {
            const schema = input.dataset.schemaName;
            if (!schema) return;
            let cfg = {};
            try { cfg = JSON.parse(input.dataset.taConfig || '{}'); } catch (e) { /* noop */ }
            let turns = {};
            // Seed from the server-restored value BEFORE any default init
            // (persistence contract). Prefer the HTML attribute when the
            // server flagged it, falling back to the live property (covers
            // same-page state after our own writes).
            const serverSet = input.getAttribute('data-server-set') === 'true';
            const raw = serverSet ? (input.getAttribute('value') || input.value) : input.value;
            if (raw) {
                try {
                    const parsed = JSON.parse(raw);
                    if (parsed && typeof parsed === 'object' && parsed.turns) {
                        turns = parsed.turns;
                    }
                } catch (e) {
                    console.warn('[turn-annotations] Could not parse stored value for', schema, e);
                }
            }
            stateBySchema[schema] = { schemaType: cfg.schema_type || '', turns: turns };
        });
    }

    function serialize(schema) {
        const state = stateBySchema[schema];
        const input = hiddenFor(schema);
        if (!state || !input) return;
        // Always non-empty once modified so an all-cleared state still reaches
        // the server and overwrites the previously stored value.
        input.value = JSON.stringify({ v: 1, schema_type: state.schemaType, turns: state.turns });
        input.setAttribute('data-modified', 'true');
        scheduleSave();
    }

    function scheduleSave() {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(function () {
            if (typeof window.saveAnnotations === 'function') {
                window.saveAnnotations();
            }
        }, 500);
    }

    function snapshotFromSlot(slot) {
        const snap = {};
        if (slot.dataset.speaker) snap.speaker = slot.dataset.speaker;
        if (slot.dataset.stepType) snap.step_type = slot.dataset.stepType;
        if (slot.dataset.agentId) snap.agent_id = slot.dataset.agentId;
        return snap;
    }

    function turnEntry(schema, tid, slot) {
        const state = stateBySchema[schema];
        if (!state) return null;
        if (!state.turns[tid]) {
            state.turns[tid] = snapshotFromSlot(slot || {});
        }
        return state.turns[tid];
    }

    function dropIfEmpty(schema, tid) {
        const state = stateBySchema[schema];
        if (!state || !state.turns[tid]) return;
        const entry = state.turns[tid];
        const hasValue = ('value' in entry && entry.value !== '' && entry.value !== null) ||
            (Array.isArray(entry.values) && entry.values.length > 0);
        if (!hasValue) delete state.turns[tid];
    }

    // ------------------------------------------------------------------
    // Painting (state -> proxy visuals)
    // ------------------------------------------------------------------

    function paintAll() {
        Object.keys(stateBySchema).forEach(paintSchema);
        updateProgress();
    }

    function paintSchema(schema) {
        const state = stateBySchema[schema];
        if (!state) return;
        const sel = '[data-ta-schema="' + CSS.escape(schema) + '"]';

        // Chips (radio / multiselect / likert)
        document.querySelectorAll('.ta-chip' + sel).forEach(function (chip) {
            const tid = chip.dataset.turnId;
            const entry = state.turns[tid] || {};
            const val = chip.dataset.value;
            let on = false;
            if (Array.isArray(entry.values)) {
                on = entry.values.indexOf(val) !== -1;
            } else if (entry.value !== undefined && entry.value !== null) {
                if (chip.classList.contains('ta-likert')) {
                    // Fill-up-to for likert scales
                    on = parseInt(val, 10) <= parseInt(entry.value, 10);
                    chip.classList.toggle('ta-exact', String(entry.value) === String(val));
                } else {
                    on = String(entry.value) === String(val);
                }
            } else if (chip.classList.contains('ta-likert')) {
                chip.classList.remove('ta-exact');
            }
            chip.classList.toggle('ta-selected', on);
        });

        // Ranges
        document.querySelectorAll('.ta-range' + sel).forEach(function (range) {
            const entry = state.turns[range.dataset.turnId] || {};
            const display = range.parentElement.querySelector('.ta-range-value');
            if (entry.value !== undefined && entry.value !== null && entry.value !== '') {
                range.value = entry.value;
                range.dataset.taArmed = 'true';
                if (display) display.textContent = entry.value;
            } else {
                range.value = range.min;
                range.dataset.taArmed = 'false';
                if (display) display.textContent = '';
            }
        });

        // Selects
        document.querySelectorAll('.ta-select' + sel).forEach(function (select) {
            const entry = state.turns[select.dataset.turnId] || {};
            select.value = (entry.value !== undefined && entry.value !== null) ? entry.value : '';
        });

        // Text
        document.querySelectorAll('.ta-text' + sel).forEach(function (area) {
            const entry = state.turns[area.dataset.turnId] || {};
            const val = (entry.value !== undefined && entry.value !== null) ? entry.value : '';
            if (area.value !== val && document.activeElement !== area) area.value = val;
        });

        // Numbers
        document.querySelectorAll('.ta-number' + sel).forEach(function (num) {
            const entry = state.turns[num.dataset.turnId] || {};
            const val = (entry.value !== undefined && entry.value !== null) ? entry.value : '';
            if (num.value !== String(val) && document.activeElement !== num) num.value = val;
        });
    }

    function updateProgress() {
        document.querySelectorAll('.ta-progress').forEach(function (el) {
            const schema = el.dataset.taSchema;
            const state = stateBySchema[schema];
            if (!state) { el.textContent = ''; return; }
            const total = document.querySelectorAll(
                '.turn-anno-widget[data-ta-schema="' + CSS.escape(schema) + '"]').length;
            const done = Object.keys(state.turns).length;
            el.textContent = total ? ('(' + done + '/' + total + ' turns)') : '';
        });
    }

    // ------------------------------------------------------------------
    // Interaction (event delegation)
    // ------------------------------------------------------------------

    function slotOf(el) {
        return el.closest('.turn-anno-slot');
    }

    document.addEventListener('click', function (e) {
        const chip = e.target.closest('.ta-chip');
        if (chip) {
            e.preventDefault();
            const schema = chip.dataset.taSchema;
            const tid = chip.dataset.turnId;
            const val = chip.dataset.value;
            const multi = chip.dataset.multi === 'true';
            const entry = turnEntry(schema, tid, slotOf(chip));
            if (!entry) return;

            if (multi) {
                if (!Array.isArray(entry.values)) entry.values = [];
                const idx = entry.values.indexOf(val);
                if (idx === -1) entry.values.push(val); else entry.values.splice(idx, 1);
            } else {
                // Toggle: re-clicking the selected value deselects
                if (String(entry.value) === String(val)) delete entry.value;
                else entry.value = chip.classList.contains('ta-likert') ? parseInt(val, 10) : val;
            }
            dropIfEmpty(schema, tid);
            paintSchema(schema);
            updateProgress();
            serialize(schema);
            return;
        }

        const toggle = e.target.closest('.ta-drawer-toggle');
        if (toggle) {
            e.preventDefault();
            const slot = slotOf(toggle);
            if (!slot) return;
            const expanded = toggle.getAttribute('aria-expanded') === 'true';
            toggle.setAttribute('aria-expanded', String(!expanded));
            slot.querySelectorAll('.ta-drawer').forEach(function (d) {
                d.style.display = expanded ? 'none' : '';
            });
        }
    });

    document.addEventListener('input', function (e) {
        const el = e.target;
        if (el.classList && el.classList.contains('ta-range')) {
            const schema = el.dataset.taSchema;
            const entry = turnEntry(schema, el.dataset.turnId, slotOf(el));
            if (!entry) return;
            entry.value = parseFloat(el.value);
            el.dataset.taArmed = 'true';
            const display = el.parentElement.querySelector('.ta-range-value');
            if (display) display.textContent = el.value;
            updateProgress();
            serialize(schema);
        } else if (el.classList && (el.classList.contains('ta-text') || el.classList.contains('ta-number'))) {
            const schema = el.dataset.taSchema;
            const tid = el.dataset.turnId;
            const key = schema + '::' + tid;
            clearTimeout(textTimers[key]);
            textTimers[key] = setTimeout(function () {
                const entry = turnEntry(schema, tid, slotOf(el));
                if (!entry) return;
                if (el.value === '') delete entry.value; else entry.value = el.value;
                dropIfEmpty(schema, tid);
                updateProgress();
                serialize(schema);
            }, 800);
        }
    });

    document.addEventListener('change', function (e) {
        const el = e.target;
        if (el.classList && el.classList.contains('ta-select')) {
            const schema = el.dataset.taSchema;
            const entry = turnEntry(schema, el.dataset.turnId, slotOf(el));
            if (!entry) return;
            if (el.value === '') delete entry.value; else entry.value = el.value;
            dropIfEmpty(schema, el.dataset.turnId);
            updateProgress();
            serialize(schema);
        }
    });

    // ------------------------------------------------------------------
    // Public API
    // ------------------------------------------------------------------

    function init() {
        if (!hiddenInputs().length) return;
        seedState();
        paintAll();
    }

    window.turnAnnotations = {
        /** Re-seed from hidden inputs and repaint (called by clearAllFormInputs). */
        refresh: init,
        /** Clear all in-memory + visual state without touching server-set inputs. */
        resetAll: function () {
            Object.keys(stateBySchema).forEach(function (schema) {
                const input = hiddenFor(schema);
                if (input && input.getAttribute('data-server-set') !== 'true') {
                    stateBySchema[schema].turns = {};
                }
            });
            paintAll();
        },
        /** Test hook: current state snapshot. */
        _state: function () { return stateBySchema; }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    document.addEventListener('instanceChanged', init);
})();

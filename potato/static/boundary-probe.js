/**
 * Boundary Lab — counterfactual boundary probing panel.
 *
 * When the annotator commits a label on the probed schema, this module fetches
 * minimal counterfactual edits of the instance text and asks, one probe at a
 * time: "Would your label survive this edit?" Verdicts (holds / flips / unsure)
 * are recorded server-side and become contrast-set records.
 *
 * Loaded conditionally by base_template_v2.html when boundary_probing.enabled;
 * configuration arrives via window.boundaryConfig = {schema, debounce_ms,
 * rationale_on_flip}.
 *
 * Deliberately non-invasive: no annotation.js changes. Label selection is
 * observed via a document-level capture listener on change/click events for
 * inputs bearing the probed schema attribute.
 */
(function () {
    'use strict';

    var cfg = window.boundaryConfig;
    if (!cfg || !cfg.schema) return;

    var state = {
        probes: [],
        labels: [],
        responses: {},      // probe_id -> response
        originalLabel: null,
        index: 0,           // current probe index
        fetchTimer: null,
        fetchSeq: 0,        // stale-response guard
        panel: null
    };

    // ------------------------------------------------------------ utilities --
    function esc(s) {
        var div = document.createElement('div');
        div.textContent = s == null ? '' : String(s);
        return div.innerHTML;
    }

    function instanceId() {
        var el = document.getElementById('instance_id');
        return el ? el.value : null;
    }

    function apiHeaders() {
        return { 'Content-Type': 'application/json' };
    }

    /** Word-level diff (LCS) between original and edited text.
     *  Returns HTML with <del>/<ins> marks. */
    function diffWords(a, b) {
        var aw = a.split(/(\s+)/), bw = b.split(/(\s+)/);
        var n = aw.length, m = bw.length;
        // LCS table (probe texts are short; O(n*m) is fine)
        var dp = [];
        for (var i = 0; i <= n; i++) { dp.push(new Array(m + 1).fill(0)); }
        for (i = n - 1; i >= 0; i--) {
            for (var j = m - 1; j >= 0; j--) {
                dp[i][j] = aw[i] === bw[j]
                    ? dp[i + 1][j + 1] + 1
                    : Math.max(dp[i + 1][j], dp[i][j + 1]);
            }
        }
        var out = [], x = 0, y = 0;
        function flush(buf, tag) {
            var joined = buf.join('');
            if (!joined) return;
            if (joined.trim() === '') { out.push(esc(joined)); return; }
            out.push('<' + tag + '>' + esc(joined) + '</' + tag + '>');
        }
        var delBuf = [], insBuf = [];
        while (x < n && y < m) {
            if (aw[x] === bw[y]) {
                flush(delBuf, 'del'); delBuf = [];
                flush(insBuf, 'ins'); insBuf = [];
                out.push(esc(aw[x]));
                x++; y++;
            } else if (dp[x + 1][y] >= dp[x][y + 1]) {
                delBuf.push(aw[x++]);
            } else {
                insBuf.push(bw[y++]);
            }
        }
        while (x < n) delBuf.push(aw[x++]);
        while (y < m) insBuf.push(bw[y++]);
        flush(delBuf, 'del');
        flush(insBuf, 'ins');
        return out.join('');
    }

    // --------------------------------------------------------------- panel --
    function ensurePanel() {
        if (state.panel) return state.panel;
        var panel = document.createElement('div');
        panel.id = 'boundary-panel';
        panel.className = 'boundary-panel boundary-hidden';
        panel.setAttribute('role', 'complementary');
        panel.setAttribute('aria-label', 'Boundary probes');
        panel.setAttribute('aria-live', 'polite');
        document.body.appendChild(panel);
        state.panel = panel;
        return panel;
    }

    function renderLoading() {
        var panel = ensurePanel();
        panel.innerHTML =
            '<div class="boundary-header">' +
            '  <span class="boundary-title">&#9889; Boundary probe</span>' +
            '  <button type="button" class="boundary-close" aria-label="Dismiss probes">&times;</button>' +
            '</div>' +
            '<div class="boundary-body boundary-loading">' +
            '  <span class="boundary-spinner" aria-hidden="true"></span>' +
            '  Preparing boundary probes&hellip;' +
            '</div>';
        panel.querySelector('.boundary-close').addEventListener('click', function () {
            state.fetchSeq++; // cancel the in-flight fetch's render
            hidePanel();
        });
        showPanel();
    }

    function hidePanel() {
        if (state.panel) state.panel.classList.add('boundary-hidden');
    }

    function showPanel() {
        ensurePanel().classList.remove('boundary-hidden');
    }

    function answeredCount() {
        return state.probes.filter(function (p) {
            return state.responses[p.probe_id];
        }).length;
    }

    function render() {
        var panel = ensurePanel();
        var total = state.probes.length;
        if (!total) { hidePanel(); return; }

        var done = answeredCount();
        var current = null;
        for (var i = 0; i < total; i++) {
            if (!state.responses[state.probes[i].probe_id]) { current = state.probes[i]; state.index = i; break; }
        }

        var dots = state.probes.map(function (p, idx) {
            var resp = state.responses[p.probe_id];
            var cls = 'boundary-dot';
            if (resp) cls += resp.verdict === 'flips' ? ' flip' : (resp.verdict === 'holds' ? ' hold' : ' unsure');
            else if (current && idx === state.index) cls += ' active';
            return '<span class="' + cls + '"></span>';
        }).join('');

        var header =
            '<div class="boundary-header">' +
            '  <span class="boundary-title">&#9889; Boundary probe</span>' +
            '  <span class="boundary-progress" aria-hidden="true">' + dots + '</span>' +
            '  <button type="button" class="boundary-close" aria-label="Dismiss probes">&times;</button>' +
            '</div>';

        var body;
        if (!current) {
            var flips = state.probes.filter(function (p) {
                var r = state.responses[p.probe_id];
                return r && r.verdict === 'flips';
            }).length;
            var holds = done - flips - state.probes.filter(function (p) {
                var r = state.responses[p.probe_id];
                return r && r.verdict === 'unsure';
            }).length;
            body =
                '<div class="boundary-body boundary-done">' +
                '  <div class="boundary-done-mark">&#10003;</div>' +
                '  <div class="boundary-done-text">Boundary mapped</div>' +
                '  <div class="boundary-done-sub">' + holds + ' hold' + (holds === 1 ? '' : 's') +
                '   &middot; ' + flips + ' flip' + (flips === 1 ? '' : 's') +
                '   &mdash; ' + (holds + flips) + ' contrast pair' + ((holds + flips) === 1 ? '' : 's') +
                '   added to your dataset</div>' +
                '</div>';
        } else {
            var kindChip = current.kind === 'invariance'
                ? '<span class="boundary-kind invariance">paraphrase</span>'
                : '<span class="boundary-kind flip">minimal edit</span>';
            body =
                '<div class="boundary-body">' +
                '  <div class="boundary-question">You said <strong>' + esc(state.originalLabel) +
                '</strong>. Would that survive this ' + kindChip + '?</div>' +
                '  <div class="boundary-diff">' + diffWords(current.original_text || state.originalText || '', current.text) + '</div>' +
                (current.edit_hint ? '<div class="boundary-hint">' + esc(current.edit_hint) + '</div>' : '') +
                '  <div class="boundary-actions">' +
                '    <button type="button" class="boundary-btn holds" data-verdict="holds">Still ' + esc(state.originalLabel) + '</button>' +
                '    <button type="button" class="boundary-btn flips" data-verdict="flips">Label flips&hellip;</button>' +
                '    <button type="button" class="boundary-btn unsure" data-verdict="unsure">Can’t tell</button>' +
                '  </div>' +
                '  <div class="boundary-flip-form boundary-hidden">' +
                '    <div class="boundary-flip-labels">' +
                state.labels.filter(function (l) { return l !== state.originalLabel; })
                    .map(function (l) {
                        return '<button type="button" class="boundary-label-chip" data-label="' + esc(l) + '">' + esc(l) + '</button>';
                    }).join('') +
                '    </div>' +
                (cfg.rationale_on_flip
                    ? '<input type="text" class="boundary-rationale" maxlength="500" ' +
                      'aria-label="Why did the label flip?" placeholder="What crossed the line? (optional)">'
                    : '') +
                '  </div>' +
                '  <div class="boundary-error boundary-hidden"></div>' +
                '</div>';
        }

        panel.innerHTML = header + body +
            '<div class="boundary-footer">Mapping your decision boundary &middot; builds the contrast set</div>';
        wireEvents(panel, current);
        showPanel();
    }

    function wireEvents(panel, current) {
        panel.querySelector('.boundary-close').addEventListener('click', function () {
            hidePanel();
        });
        if (!current) return;

        var flipForm = panel.querySelector('.boundary-flip-form');
        panel.querySelectorAll('.boundary-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var verdict = btn.getAttribute('data-verdict');
                if (verdict === 'flips') {
                    flipForm.classList.toggle('boundary-hidden');
                    btn.classList.toggle('open');
                    var rationale = flipForm.querySelector('.boundary-rationale');
                    if (!flipForm.classList.contains('boundary-hidden') && rationale) rationale.focus();
                } else {
                    submitVerdict(current, verdict, null, null, panel);
                }
            });
        });
        panel.querySelectorAll('.boundary-label-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                var rationaleInput = flipForm.querySelector('.boundary-rationale');
                submitVerdict(current, 'flips', chip.getAttribute('data-label'),
                    rationaleInput ? rationaleInput.value : null, panel);
            });
        });
    }

    function showError(panel, message) {
        var el = panel.querySelector('.boundary-error');
        if (el) {
            el.textContent = message;
            el.classList.remove('boundary-hidden');
        }
    }

    // ----------------------------------------------------------------- api --
    function submitVerdict(probe, verdict, newLabel, rationale, panel) {
        fetch('/boundary/api/respond', {
            method: 'POST',
            headers: apiHeaders(),
            body: JSON.stringify({
                instance_id: instanceId(),
                probe_id: probe.probe_id,
                verdict: verdict,
                new_label: newLabel,
                rationale: rationale
            })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }).then(function (data) {
            state.responses[probe.probe_id] = data.response ||
                { verdict: verdict, new_label: newLabel, rationale: rationale };
            render();
        }).catch(function () {
            showError(panel, 'Could not save — check your connection and try again.');
        });
    }

    function fetchProbes(label) {
        var id = instanceId();
        if (!id || !label) { hidePanel(); return; }
        var seq = ++state.fetchSeq;
        // Show a loading card only if generation is slow (LLM tier); the
        // precomputed/rules tiers respond fast enough to skip it.
        var loadingTimer = setTimeout(function () {
            if (seq === state.fetchSeq) renderLoading();
        }, 400);
        fetch('/boundary/api/probe', {
            method: 'POST',
            headers: apiHeaders(),
            body: JSON.stringify({ instance_id: id, schema: cfg.schema, label: label })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }).then(function (data) {
            clearTimeout(loadingTimer);
            if (seq !== state.fetchSeq) return; // a newer label selection won
            state.probes = (data.probes || []).map(function (p) {
                p.original_text = data.original_text;
                return p;
            });
            state.labels = data.labels || [];
            state.responses = data.responses || {};
            state.originalLabel = data.original_label || label;
            state.originalText = data.original_text || '';
            state.index = 0;
            if (state.probes.length) render(); else hidePanel();
        }).catch(function (err) {
            clearTimeout(loadingTimer);
            if (seq !== state.fetchSeq) return;
            // Silent failure: probing is an enhancement, never a blocker.
            console.warn('Boundary Lab: probe fetch failed', err);
            hidePanel();
        });
    }

    // ------------------------------------------------------ label detection --
    function selectedLabel() {
        var checked = document.querySelector(
            'input.annotation-input[schema="' + cfg.schema + '"]:checked');
        return checked ? checked.getAttribute('label_name') : null;
    }

    function scheduleProbe() {
        clearTimeout(state.fetchTimer);
        state.fetchTimer = setTimeout(function () {
            var label = selectedLabel();
            if (label) fetchProbes(label); else hidePanel();
        }, cfg.debounce_ms || 900);
    }

    function isProbedInput(el) {
        return el && el.matches &&
            el.matches('input.annotation-input') &&
            el.getAttribute('schema') === cfg.schema;
    }

    document.addEventListener('change', function (e) {
        if (isProbedInput(e.target)) scheduleProbe();
    }, true);
    // Radio deselection in Potato happens via click without a change event.
    document.addEventListener('click', function (e) {
        if (isProbedInput(e.target)) scheduleProbe();
    }, true);
})();

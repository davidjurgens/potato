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

    // Defining the helpers is side-effect free, so the "not configured" guard
    // sits on the listener registration at the bottom instead of here. That
    // keeps the rendering helpers reachable from tests without a live server.
    var cfg = window.boundaryConfig || {};

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
            changed += joined.trim().split(/\s+/).length;
            out.push('<' + tag + '>' + esc(joined) + '</' + tag + '>');
        }
        var changed = 0, kept = 0;
        var delBuf = [], insBuf = [];
        while (x < n && y < m) {
            if (aw[x] === bw[y]) {
                flush(delBuf, 'del'); delBuf = [];
                flush(insBuf, 'ins'); insBuf = [];
                if (aw[x].trim() !== '') kept++;
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
        return {
            html: out.join(''),
            // Share of words the edit touched. 0 = identical, 1 = nothing survived.
            churn: (changed + kept) ? changed / (changed + kept) : 0
        };
    }

    /** Above this share of words touched, a word diff stops being readable. */
    var DIFF_CHURN_LIMIT = 0.4;

    /**
     * How to show a probe's text.
     *
     * A word diff is the right presentation for a *minimal* edit: the one
     * phrase that moved is exactly what the annotator has to weigh. It is the
     * wrong presentation for a paraphrase, where nearly every word is replaced
     * and the diff interleaves original and replacement into an unreadable
     * run — `HiHello Sam, couldwould you be able to send meover the Q3 report`.
     * Invariance probes are always paraphrases, and a "flip" probe can be
     * rewritten heavily too, so the churn measure decides rather than the kind
     * alone. When the diff would be noise, both versions are shown whole.
     */
    /**
     * An image probe: the original beside the transformed version.
     *
     * The transform is applied by the browser to the same image — a filter, a
     * mirror, an inset clip, a rectangle over it — so nothing is rendered
     * server-side and remote media is never fetched by Potato. Built with DOM
     * nodes rather than a template string because the src comes from an item
     * field.
     */
    function probeImage(probe) {
        var media = probe.media || {};
        var style = media.style || {};

        function frame(src, caption, transformed) {
            var block = document.createElement('div');
            block.className = 'boundary-imgblock' +
                (transformed ? ' is-edited' : ' is-original');

            var label = document.createElement('span');
            label.className = 'boundary-textlabel';
            label.textContent = caption;
            block.appendChild(label);

            var stage = document.createElement('div');
            stage.className = 'boundary-imgstage';

            var img = document.createElement('img');
            img.src = src;
            img.alt = transformed
                ? 'The item, ' + (probe.edit_hint || 'altered')
                : 'The item as you labelled it';
            img.loading = 'lazy';
            if (transformed) {
                if (style.filter) img.style.filter = style.filter;
                if (style.mirror) img.style.transform = 'scaleX(-1)';
                if (style.inset) {
                    var pct = style.inset.map(function (v) {
                        return (v * 100).toFixed(1) + '%';
                    }).join(' ');
                    img.style.clipPath = 'inset(' + pct + ')';
                }
            }
            stage.appendChild(img);

            if (transformed && style.occlude) {
                var box = document.createElement('div');
                box.className = 'boundary-occluder';
                box.style.left = (style.occlude[0] * 100) + '%';
                box.style.top = (style.occlude[1] * 100) + '%';
                box.style.width = (style.occlude[2] * 100) + '%';
                box.style.height = (style.occlude[3] * 100) + '%';
                stage.appendChild(box);
            }

            block.appendChild(stage);
            return block;
        }

        var pair = document.createElement('div');
        pair.className = 'boundary-imgpair';
        pair.appendChild(frame(media.src, 'Original', false));
        pair.appendChild(frame(media.src,
            probe.kind === 'invariance' ? 'Same image, changed' : 'Changed',
            true));
        return { node: pair, minimal: false };
    }

    function probeText(probe) {
        if (probe && probe.media && probe.media.src) return probeImage(probe);
        var original = probe.original_text || state.originalText || '';
        var edited = probe.text || '';
        var d = diffWords(original, edited);
        var readable = probe.kind !== 'invariance' && d.churn <= DIFF_CHURN_LIMIT;
        if (readable) {
            return {
                html: '<div class="boundary-diff">' + d.html + '</div>',
                minimal: true
            };
        }
        return {
            html:
                '<div class="boundary-textpair">' +
                '  <div class="boundary-textblock is-original">' +
                '    <span class="boundary-textlabel">Original</span>' +
                '    <span class="boundary-textbody">' + esc(original) + '</span>' +
                '  </div>' +
                '  <div class="boundary-textblock is-edited">' +
                '    <span class="boundary-textlabel">' +
                (probe.kind === 'invariance' ? 'Reworded' : 'Edited') + '</span>' +
                '    <span class="boundary-textbody">' + esc(edited) + '</span>' +
                '  </div>' +
                '</div>',
            minimal: false
        };
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
        var panel = ensurePanel();
        panel.classList.remove('boundary-hidden');
        avoidNavButtons(panel);
    }

    /** Keep the bottom-right panel from covering (and swallowing clicks on) Next. */
    function avoidNavButtons(panel) {
        if (window.potatoFloatingPanel) window.potatoFloatingPanel.avoidNav(panel);
    }

    function answeredCount() {
        return state.probes.filter(function (p) {
            return state.responses[p.probe_id];
        }).length;
    }

    //: Set by render() when the current probe is visual; consumed immediately
    //: after innerHTML is written, since a DOM node cannot be concatenated in.
    var pendingMediaNode = null;

    function render() {
        var panel = ensurePanel();
        pendingMediaNode = null;
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
            var shown = probeText(current);
            var isMedia = !!shown.node;
            // Nodes cannot go in a string; a slot is filled in after render.
            if (isMedia) {
                pendingMediaNode = shown.node;
                shown = { html: '<div class="boundary-mediaslot"></div>' };
            }
            // "minimal edit" would be a lie on a probe we could not diff.
            var kindChip = isMedia
                ? '<span class="boundary-kind ' +
                  (current.kind === 'invariance' ? 'invariance">same picture'
                                                 : 'flip">altered picture') +
                  '</span>'
                : current.kind === 'invariance'
                ? '<span class="boundary-kind invariance">paraphrase</span>'
                : '<span class="boundary-kind flip">' +
                  (shown.minimal ? 'minimal edit' : 'rewrite') + '</span>';
            body =
                '<div class="boundary-body">' +
                '  <div class="boundary-question">You said <strong>' + esc(state.originalLabel) +
                '</strong>. Would that survive this ' + kindChip + '?</div>' +
                shown.html +
                (current.edit_hint ? '<div class="boundary-hint">' + esc(current.edit_hint) + '</div>' : '') +
                '  <div class="boundary-actions">' +
                '    <button type="button" class="boundary-btn holds" data-verdict="holds">Still ' + esc(state.originalLabel) + '</button>' +
                '    <button type="button" class="boundary-btn flips" data-verdict="flips">Label flips&hellip;</button>' +
                '    <button type="button" class="boundary-btn unsure" data-verdict="unsure">Can’t tell</button>' +
                '  </div>' +
                // Rationale first: a label chip SUBMITS, so chips-above-input
                // meant the natural click order silently discarded the
                // rationale — the very signal this feature exists to collect.
                '  <div class="boundary-flip-form boundary-hidden">' +
                (cfg.rationale_on_flip
                    ? '<input type="text" class="boundary-rationale" maxlength="500" ' +
                      'aria-label="Why did the label flip?" placeholder="What crossed the line? (optional)">'
                    : '') +
                '    <div class="boundary-flip-caption">Then pick the new label:</div>' +
                '    <div class="boundary-flip-labels">' +
                state.labels.filter(function (l) { return l !== state.originalLabel; })
                    .map(function (l) {
                        return '<button type="button" class="boundary-label-chip" data-label="' + esc(l) + '">' + esc(l) + '</button>';
                    }).join('') +
                '    </div>' +
                '  </div>' +
                '  <div class="boundary-error boundary-hidden"></div>' +
                '</div>';
        }

        panel.innerHTML = header + body +
            '<div class="boundary-footer">Mapping your decision boundary &middot; builds the contrast set</div>';
        if (pendingMediaNode) {
            var slot = panel.querySelector('.boundary-mediaslot');
            if (slot) slot.appendChild(pendingMediaNode);
            pendingMediaNode = null;
        }
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
                    avoidNavButtons(panel);   // the form makes the panel taller
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

    // Presentation helpers, exposed for tests. The rendering decision this
    // exports — diff or whole text — was wrong for every paraphrase probe and
    // nothing could see it, because nothing could call it.
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            diffWords: diffWords,
            probeText: probeText,
            DIFF_CHURN_LIMIT: DIFF_CHURN_LIMIT,
            _setOriginalText: function (t) { state.originalText = t; }
        };
    }

    if (!cfg.schema) return;   // probing not configured for this project

    document.addEventListener('change', function (e) {
        if (isProbedInput(e.target)) scheduleProbe();
    }, true);
    // Radio deselection in Potato happens via click without a change event.
    document.addEventListener('click', function (e) {
        if (isProbedInput(e.target)) scheduleProbe();
    }, true);

    // Resizing moves the nav row, so re-check that the panel still clears it.
    window.addEventListener('resize', function () {
        if (state.panel && !state.panel.classList.contains('boundary-hidden')) {
            avoidNavButtons(state.panel);
        }
    });
})();

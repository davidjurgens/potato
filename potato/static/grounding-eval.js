/**
 * Grounding evaluation: bind each referring expression to a region on the image.
 *
 * ## How the binding works, and why it is a swap rather than a tag
 *
 * There is one image canvas and N expressions. The obvious design — draw
 * everything on the canvas and tag each shape with the expression it belongs
 * to — needs the image manager to carry a foreign field through serialize,
 * restore, undo, copy-from-previous and every exporter, and the first path
 * that drops it silently re-attributes an annotation to the wrong phrase.
 *
 * So the canvas holds **only the active expression's regions**. Selecting a
 * different expression captures what is on the canvas, clears it, and restores
 * that expression's own. The image manager stays exactly what it was and never
 * learns that grounding exists; this file owns the mapping, and the mapping is
 * the thing that gets saved.
 *
 * The cost is that you cannot see all the regions at once. That is a real
 * loss and it is the right trade: seeing them all at once is a display
 * problem, and mis-attributing an annotation is a data problem.
 *
 * ## Three states, not two
 *
 * An expression is answered with a region, answered as **absent**, or not
 * answered. The third is not a kind of the second. An annotator who has not
 * reached a phrase and one who judged that nothing in the picture matches it
 * support opposite conclusions about a model that also produced nothing, so
 * the interface makes "not present" a button and the storage keeps them apart.
 */
(function (global) {
    'use strict';

    class GroundingEvalManager {
        constructor(container, config) {
            this.container = container;
            this.config = config || {};
            this.schemaName = this.config.schemaName;
            this.expressions = [];
            this.predictions = {};
            /** expressionId -> {regions: [...], absent: bool, verdict: string} */
            this.answers = {};
            this.activeId = null;
            this.imageManager = null;
            this.input = document.getElementById('input-' + this.schemaName);
            this.list = document.getElementById('grounding-list-' + this.schemaName);
            this.progress = document.getElementById(
                'grounding-progress-' + this.schemaName);
            this.announcer = document.getElementById(
                'grounding-announce-' + this.schemaName);
        }

        init() {
            this._restoreFromInput();
            this._wireControls();
            this._fetchExpressions();
            this._findImageManager();
            this._installNavGuard();
        }

        // -- data ------------------------------------------------------------

        _fetchExpressions() {
            const url = '/api/grounding/expressions?schema='
                + encodeURIComponent(this.schemaName);
            fetch(url, { credentials: 'same-origin' })
                .then((response) => response.json())
                .then((payload) => {
                    if (payload.error) throw new Error(payload.error);
                    this.predictions = payload.predictions || {};
                    this.warning = payload.warning || '';
                    this.caption = payload.caption || '';
                    if (this.config.expressionSource === 'spans') {
                        // The phrases are whatever the annotator picks out of
                        // the caption, so any restored answers ARE the
                        // expression list: their ids carry the offsets.
                        this._renderCaption();
                        this.expressions = this._expressionsFromAnswers();
                    } else {
                        this.expressions = payload.expressions || [];
                    }
                    this._render();
                    if (this.expressions.length) {
                        this.selectExpression(this.expressions[0].id);
                    }
                })
                .catch((error) => {
                    this._showError(error && error.message
                        ? error.message
                        : 'The referring expressions could not be loaded.');
                });
        }

        /**
         * Find the image annotation manager sharing this page.
         *
         * Polled rather than assumed: the image manager loads its image
         * asynchronously and may not exist when this runs. Giving up after the
         * timeout produces a stated error instead of a page where clicking an
         * expression silently does nothing.
         */
        _findImageManager(attempt) {
            attempt = attempt || 0;
            const containers = document.querySelectorAll(
                '.image-annotation-container');
            for (const element of containers) {
                if (element.annotationManager) {
                    this.imageManager = element.annotationManager;
                    if (this.config.tool) {
                        this.imageManager.setTool(this.config.tool);
                    }
                    this._wireCapture();
                    this._restoreActive();
                    return;
                }
            }
            if (attempt > 60) {
                this._showError(
                    'No image annotation schema was found on this page. '
                    + 'A grounding_eval schema needs one alongside it to draw on.');
                return;
            }
            setTimeout(() => this._findImageManager(attempt + 1), 250);
        }

        // -- caption spans (hallucination localization) ----------------------

        _renderCaption() {
            const element = document.getElementById(
                'grounding-caption-' + this.schemaName);
            if (!element) return;
            element.textContent = this.caption;
            this._highlightGroundedSpans();
        }

        /**
         * Turn the current text selection into an expression.
         *
         * The id encodes the character offsets, which is what makes an answer
         * reload-safe: the caption is the same string every time, so
         * `span:12-27` names the same phrase after a restart. It also means two
         * annotators who select the same phrase produce the same id, which is
         * what any agreement over these answers needs.
         */
        addSelectedSpan() {
            const element = document.getElementById(
                'grounding-caption-' + this.schemaName);
            if (!element) return;
            const selection = global.getSelection && global.getSelection();
            if (!selection || selection.isCollapsed || !selection.rangeCount) return;

            const range = selection.getRangeAt(0);
            if (!element.contains(range.commonAncestorContainer)) return;

            const before = range.cloneRange();
            before.selectNodeContents(element);
            before.setEnd(range.startContainer, range.startOffset);
            const start = before.toString().length;
            const text = range.toString();
            if (!text.trim()) return;
            const end = start + text.length;

            const id = 'span:' + start + '-' + end;
            if (!this.expressions.some((expression) => expression.id === id)) {
                this.expressions.push({ id: id, text: text, start: start, end: end });
                this.expressions.sort((a, b) => (a.start || 0) - (b.start || 0));
            }
            selection.removeAllRanges();
            this._render();
            this.selectExpression(id);
            this._announce('Grounding the phrase "' + text + '".');
        }

        /** Expressions implied by restored answers, so a reload is not blank. */
        _expressionsFromAnswers() {
            const expressions = [];
            const seen = new Set();
            for (const span of (this._restoredSpans || [])) {
                if (span && span.id) {
                    seen.add(span.id);
                    expressions.push({
                        id: span.id, start: span.start, end: span.end,
                        text: span.text
                              || (this.caption || '').slice(span.start, span.end),
                    });
                }
            }
            for (const id of Object.keys(this.answers)) {
                if (seen.has(id)) continue;
                const match = /^span:(\d+)-(\d+)$/.exec(id);
                if (!match) continue;
                const start = parseInt(match[1], 10);
                const end = parseInt(match[2], 10);
                expressions.push({
                    id: id, start: start, end: end,
                    text: (this.caption || '').slice(start, end) || id,
                });
            }
            return expressions.sort((a, b) => a.start - b.start);
        }

        /** Mark the grounded phrases in the caption itself. */
        _highlightGroundedSpans() {
            const element = document.getElementById(
                'grounding-caption-' + this.schemaName);
            if (!element || !this.caption) return;
            const marks = this.expressions
                .filter((expression) => expression.start != null)
                .sort((a, b) => a.start - b.start);
            if (!marks.length) {
                element.textContent = this.caption;
                return;
            }
            element.textContent = '';
            let cursor = 0;
            for (const mark of marks) {
                if (mark.start < cursor) continue;   // overlapping: keep the first
                element.appendChild(document.createTextNode(
                    this.caption.slice(cursor, mark.start)));
                const span = document.createElement('mark');
                span.className = 'grounding-span state-' + this.state(mark.id);
                span.dataset.expression = mark.id;
                span.textContent = this.caption.slice(mark.start, mark.end);
                element.appendChild(span);
                cursor = mark.end;
            }
            element.appendChild(document.createTextNode(this.caption.slice(cursor)));
        }

        /**
         * How much of the caption is grounded, ungrounded, or unexamined.
         *
         * Characters rather than tokens: tokenization is the model's business
         * and two tokenizers disagree, while character offsets are what the
         * annotator actually selected. A consumer that wants tokens can map
         * them from the offsets; the reverse is not possible.
         */
        captionCoverage() {
            const total = (this.caption || '').length;
            let grounded = 0;
            let ungrounded = 0;
            for (const expression of this.expressions) {
                if (expression.start == null) continue;
                const length = expression.end - expression.start;
                const state = this.state(expression.id);
                if (state === 'located') grounded += length;
                else if (state === 'absent') ungrounded += length;
            }
            return {
                caption_chars: total,
                grounded_chars: grounded,
                ungrounded_chars: ungrounded,
                grounded_fraction: total ? grounded / total : 0,
                ungrounded_fraction: total ? ungrounded / total : 0,
            };
        }

        // -- selection -------------------------------------------------------

        selectExpression(expressionId) {
            if (this.activeId === expressionId) return;
            this._captureActive();
            this.activeId = expressionId;
            this._restoreActive();
            this._render();
            const expression = this._expression(expressionId);
            this._announce(expression
                ? `Selected: ${expression.text}`
                : 'Selected an expression.');
        }

        /**
         * Read whatever is on the canvas into the active expression's answer.
         *
         * `_serializeAnnotations()` returns a JSON **string**, not an array —
         * treating it as an array silently captures nothing, which looks
         * exactly like an annotator who drew nothing.
         */
        _captureActive() {
            if (!this.activeId || !this.imageManager) return;
            let regions = [];
            if (this.imageManager._serializeAnnotations) {
                try {
                    const parsed = JSON.parse(
                        this.imageManager._serializeAnnotations() || '[]');
                    if (Array.isArray(parsed)) regions = parsed;
                } catch (error) {
                    console.warn('Could not read the canvas annotations:', error);
                    return;
                }
            }
            const answer = this.answers[this.activeId] || {};
            // Drawing a region withdraws an "absent" claim: they are mutually
            // exclusive answers and leaving both set would make the stored
            // value contradict itself.
            if (regions.length) answer.absent = false;
            answer.regions = regions;
            this.answers[this.activeId] = answer;
            this._save();
        }

        /**
         * Put the active expression's regions back on the canvas.
         *
         * Through the manager's own `_deserializeAnnotations`, not by looping
         * `addAnnotation`: masks are not fabric objects and take a different
         * restore path, and the deserializer is the one place that knows both.
         */
        _restoreActive() {
            if (!this.imageManager) return;

            // Read the answer and raise the guard BEFORE touching the canvas.
            // `clearAnnotations()` fires the capture callback, and with the
            // guard down that callback captures an empty canvas into the
            // expression being switched TO -- erasing the very regions the
            // next two lines are about to restore. The symptom is a region
            // that vanishes when you switch away and back.
            const answer = this.answers[this.activeId];
            const regions = (answer && answer.regions) || [];
            this._restoring = true;
            try {
                if (this.imageManager.clearAnnotations) {
                    this.imageManager.clearAnnotations();
                }
                if (!regions.length) {
                    if (this.imageManager._updateAnnotationData) {
                        this.imageManager._updateAnnotationData();
                    }
                    return;
                }
                this.imageManager._deserializeAnnotations(
                    JSON.stringify(regions));
                if (this.imageManager._updateAnnotationData) {
                    // The deserializer repaints the canvas but does not rewrite
                    // the hidden input, so without this the input still holds
                    // the previous expression's regions.
                    this.imageManager._updateAnnotationData();
                }
            } catch (error) {
                console.warn('Could not restore grounding regions:', error);
            } finally {
                this._restoring = false;
            }
        }

        markAbsent() {
            if (!this.activeId) return;
            if (this.imageManager && this.imageManager.clearAnnotations) {
                this.imageManager.clearAnnotations();
            }
            this.answers[this.activeId] = { regions: [], absent: true };
            this._save();
            this._render();
            this._announce('Marked as not present in the image.');
            this._advance();
        }

        clearAnswer() {
            if (!this.activeId) return;
            if (this.imageManager && this.imageManager.clearAnnotations) {
                this.imageManager.clearAnnotations();
            }
            delete this.answers[this.activeId];
            this._save();
            this._render();
            this._announce('Answer cleared. This expression is unanswered again.');
        }

        setVerdict(value) {
            if (!this.activeId) return;
            const answer = this.answers[this.activeId] || { regions: [] };
            answer.verdict = value || '';
            this.answers[this.activeId] = answer;
            this._save();
            this._render();
        }

        /** Move to the next unanswered expression, if there is one. */
        _advance() {
            const remaining = this.unanswered();
            if (!remaining.length) return;
            const next = remaining.find((id) => id !== this.activeId);
            if (next) this.selectExpression(next);
        }

        // -- state -----------------------------------------------------------

        /** Expression ids with no answer of either kind. */
        unanswered() {
            return this.expressions
                .map((expression) => expression.id)
                .filter((id) => {
                    const answer = this.answers[id];
                    if (!answer) return true;
                    return !answer.absent
                        && !(answer.regions && answer.regions.length);
                });
        }

        state(expressionId) {
            const answer = this.answers[expressionId];
            if (!answer) return 'unanswered';
            if (answer.absent) return 'absent';
            if (answer.regions && answer.regions.length) return 'located';
            return 'unanswered';
        }

        serialize() {
            const regions = {};
            const absent = [];
            const verdicts = {};
            for (const [id, answer] of Object.entries(this.answers)) {
                if (answer.absent) {
                    absent.push(id);
                } else if (answer.regions && answer.regions.length) {
                    regions[id] = answer.regions;
                }
                if (answer.verdict) verdicts[id] = answer.verdict;
            }
            const payload = { regions, absent, verdicts,
                              region_type: this.config.regionType };
            if (this.config.expressionSource === 'spans') {
                payload.spans = this.expressions
                    .filter((expression) => expression.start != null)
                    .map((expression) => ({ id: expression.id,
                                            start: expression.start,
                                            end: expression.end,
                                            text: expression.text }));
                payload.coverage = this.captionCoverage();
            }
            return payload;
        }

        _save() {
            if (!this.input) return;
            this.input.value = JSON.stringify(this.serialize());
            this.input.setAttribute('data-modified', 'true');
            this.input.dispatchEvent(new Event('change', { bubbles: true }));
        }

        _restoreFromInput() {
            if (!this.input || !this.input.value) return;
            try {
                const stored = JSON.parse(this.input.value);
                for (const [id, regions] of Object.entries(stored.regions || {})) {
                    this.answers[id] = { regions: regions, absent: false };
                }
                for (const id of stored.absent || []) {
                    this.answers[id] = { regions: [], absent: true };
                }
                for (const [id, verdict] of Object.entries(stored.verdicts || {})) {
                    this.answers[id] = this.answers[id] || { regions: [] };
                    this.answers[id].verdict = verdict;
                }
                // Spans the annotator selected but did not answer are part of
                // the record too: forgetting them would silently re-open a
                // phrase they had already decided to consider.
                this._restoredSpans = stored.spans || [];
            } catch (error) {
                console.warn('Stored grounding answers could not be parsed:', error);
            }
        }

        clearAnnotations() {
            this.answers = {};
            this.activeId = null;
            if (this.input) this.input.value = '';
            this._render();
        }

        getAnnotationCount() {
            return Object.keys(this.answers).length;
        }

        // -- rendering -------------------------------------------------------

        _render() {
            if (!this.list) return;
            this.list.innerHTML = '';

            if (this.warning) {
                const notice = document.createElement('li');
                notice.className = 'grounding-warning';
                notice.textContent = this.warning;
                this.list.appendChild(notice);
            }

            for (const expression of this.expressions) {
                const state = this.state(expression.id);
                const item = document.createElement('li');
                item.className = 'grounding-item state-' + state
                    + (expression.id === this.activeId ? ' active' : '');

                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'grounding-expression-btn';
                button.dataset.expression = expression.id;
                button.setAttribute('role', 'radio');
                button.setAttribute('aria-checked',
                    expression.id === this.activeId ? 'true' : 'false');
                // The state belongs in the accessible name, not only in the
                // colour: "located" and "not present" are the answer, and a
                // screen-reader user needs them without the styling.
                button.setAttribute('aria-label',
                    `${expression.text} — ${this._stateLabel(state)}`);

                const text = document.createElement('span');
                text.className = 'grounding-expression-text';
                text.textContent = expression.text;
                button.appendChild(text);

                const badge = document.createElement('span');
                badge.className = 'grounding-state';
                badge.setAttribute('aria-hidden', 'true');
                badge.textContent = this._stateLabel(state);
                button.appendChild(badge);

                if (this.predictions && this.predictions[expression.id]) {
                    const flag = document.createElement('span');
                    flag.className = 'grounding-has-prediction';
                    flag.textContent = 'model answer available';
                    button.appendChild(flag);
                }

                item.appendChild(button);
                this.list.appendChild(item);
            }
            this._renderProgress();
            if (this.config.expressionSource === 'spans') {
                this._highlightGroundedSpans();
            }
        }

        _stateLabel(state) {
            if (state === 'located') return 'located';
            if (state === 'absent') return 'not present';
            return 'not answered';
        }

        _renderProgress() {
            if (!this.progress) return;
            const total = this.expressions.length;
            const remaining = this.unanswered();
            const done = total - remaining.length;
            if (!total) {
                this.progress.textContent = '';
                return;
            }
            this.progress.textContent = remaining.length
                ? `${done} of ${total} expressions answered — still to do: `
                  + remaining.map((id) => {
                        const expression = this._expression(id);
                        return expression ? expression.text : id;
                    }).join('; ')
                : `All ${total} expressions answered.`;
        }

        _expression(id) {
            return this.expressions.find((e) => e.id === id) || null;
        }

        _announce(message) {
            if (this.announcer) this.announcer.textContent = message;
        }

        _showError(message) {
            this.container.classList.add('error');
            if (this.progress) this.progress.textContent = message;
            this._announce(message);
        }

        // -- wiring ----------------------------------------------------------

        _wireControls() {
            if (this.list) {
                this.list.addEventListener('click', (event) => {
                    const button = event.target.closest('.grounding-expression-btn');
                    if (button) this.selectExpression(button.dataset.expression);
                });
            }
            const absent = this.container.querySelector('.grounding-absent-btn');
            if (absent) absent.addEventListener('click', () => this.markAbsent());
            const clear = this.container.querySelector('.grounding-clear-btn');
            if (clear) clear.addEventListener('click', () => this.clearAnswer());
            const addSpan = this.container.querySelector('.grounding-add-span-btn');
            if (addSpan) {
                addSpan.addEventListener('click', () => this.addSelectedSpan());
                // Enabled only when there is something selected, so the button
                // never looks available and then does nothing.
                document.addEventListener('selectionchange', () => {
                    const selection = global.getSelection && global.getSelection();
                    const caption = document.getElementById(
                        'grounding-caption-' + this.schemaName);
                    const usable = !!(selection && !selection.isCollapsed && caption
                        && selection.rangeCount
                        && caption.contains(
                            selection.getRangeAt(0).commonAncestorContainer));
                    addSpan.disabled = !usable;
                });
            }

            const verdict = this.container.querySelector('.grounding-verdict-select');
            if (verdict) {
                verdict.addEventListener('change',
                    (event) => this.setVerdict(event.target.value));
            }

            // Capture is wired in _findImageManager, through the image
            // manager's own onAnnotationChange callback -- see the note there.
        }

        /**
         * Capture whatever is drawn, as it is drawn.
         *
         * Through `addAnnotationChangeListener`, NOT a `change` event on the
         * hidden input: `_updateAnnotationData` assigns `input.value` directly
         * and assigning a value fires no event, so a `change` listener never
         * runs and the last region an annotator draws is never saved.
         *
         * And not the `onAnnotationChange` slot either: the image schema's own
         * bootstrap *assigns* it, discarding anything already there, which made
         * companion schemas order-dependent.
         */
        _wireCapture() {
            if (!this.imageManager || this._captureWired) return;
            this._captureWired = true;
            this.imageManager.addAnnotationChangeListener(() => {
                if (this._restoring) return;
                this._captureActive();
                this._render();
            });
        }

        /**
         * Refuse the first Next press while expressions are unanswered.
         *
         * On `document`, in the CAPTURE phase, with stopImmediatePropagation:
         * `#next-btn` navigates from an inline onclick attribute registered at
         * parse time, so a listener on the button itself runs second and the
         * warning flashes past on the way to the next item.
         */
        _installNavGuard() {
            if (!this.config.requireAll) return;
            this._warned = false;
            document.addEventListener('click', (event) => {
                const target = event.target && event.target.closest
                    ? event.target.closest('#next-btn, #submit-btn') : null;
                if (!target) return;
                const remaining = this.unanswered();
                if (!remaining.length || this._warned) return;
                event.preventDefault();
                event.stopImmediatePropagation();
                this._warned = true;
                const message = `${remaining.length} expression(s) still `
                    + 'unanswered. Mark a region, or say it is not present. '
                    + 'Press Next again to continue anyway.';
                if (this.progress) this.progress.textContent = message;
                this._announce(message);
            }, true);
        }
    }

    global.GroundingEvalManager = GroundingEvalManager;
})(typeof window !== 'undefined' ? window : globalThis);

/**
 * VLM critique review queue.
 *
 * Sends the annotations currently on the canvas to /api/critique_annotations,
 * then presents what the model flagged as a queue the annotator works through:
 * see the region, read why, and either act on it or dismiss it.
 *
 * Two rules this file exists to enforce, both of which are easy to lose:
 *
 * 1. **Nothing is applied automatically.** A verdict is advice. Every change
 *    to the annotator's work happens because they pressed a button, and the
 *    reason is on screen when they press it. A "fix all" button would turn a
 *    model that is right most of the time into a dataset that is wrong in a
 *    correlated way, which is worse than the mistakes it corrects.
 *
 * 2. **Confirmations are not celebrated.** The queue leads with what needs a
 *    look and keeps confirmations collapsed. A panel that opens on "9 of 12
 *    correct!" trains people to close it.
 */

(function () {
    'use strict';

    /** Verdicts that get a card in the queue, with how to describe them. */
    const VERDICT_COPY = {
        wrong_label: {
            title: 'Label may be wrong',
            tone: 'warn',
        },
        not_an_object: {
            title: 'May not be an object',
            tone: 'warn',
        },
        loose_boundary: {
            title: 'Boundary may not fit',
            tone: 'info',
        },
    };

    class AnnotationCritiqueReview {
        /**
         * @param {Object} manager - the ImageAnnotationManager to review
         */
        constructor(manager) {
            this.manager = manager;
            this.schema = manager?.config?.schemaName || '';
            this.panel = null;
            this.isLoading = false;
            this.lastResult = null;
            this._dismissed = new Set();
        }

        // -- request ---------------------------------------------------

        /**
         * Run a critique pass over what is currently on the canvas.
         */
        async run() {
            if (this.isLoading) return;
            this.isLoading = true;
            this._ensurePanel();
            this._renderLoading();

            let objects = [];
            try {
                objects = JSON.parse(this.manager._serializeAnnotations() || '[]');
            } catch (e) {
                objects = [];
            }

            // Name the instance explicitly rather than letting the server fall
            // back to its own current-instance pointer. The annotations come
            // from the canvas, so if that pointer ever disagreed with what the
            // canvas is showing, the model would be asked about one image while
            // being handed another image's boxes — and every verdict would be
            // confidently, unfalsifiably wrong.
            const instanceId = document.getElementById('instance_id')?.value || undefined;

            try {
                const response = await fetch('/api/critique_annotations', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        schema: this.schema,
                        objects: objects,
                        instance_id: instanceId,
                    }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || data.error) {
                    this._renderError(data.error ||
                        `The critique service returned ${response.status}.`);
                    return;
                }
                // The verdicts index into the annotation list as it was when
                // the request was sent. If the annotator drew or deleted
                // something while waiting, those indices now point at
                // different shapes, and acting on them would edit the wrong
                // annotation. Detect it and say so rather than acting.
                this._baseline = objects.length;
                this.lastResult = data;
                this._dismissed = new Set();
                this._renderResult(data);
            } catch (error) {
                this._renderError(error.message ||
                    'Could not reach the critique service.');
            } finally {
                this.isLoading = false;
            }
        }

        /** Whether the canvas still matches what was critiqued. */
        _isStale() {
            if (this._baseline === undefined) return false;
            try {
                return this.manager.getAnnotationHandles().length !== this._baseline;
            } catch (e) {
                return false;
            }
        }

        // -- panel -----------------------------------------------------

        _ensurePanel() {
            if (this.panel && this.panel.isConnected) return;
            const container = this.manager?.container ||
                document.querySelector('.image-annotation-container');
            if (!container) return;

            this.panel = document.createElement('section');
            this.panel.className = 'critique-panel';
            this.panel.setAttribute('aria-label', 'AI review of your annotations');
            container.appendChild(this.panel);

            // A live region has to EXIST before its content changes to be
            // announced, so it lives outside the panel body that _clear()
            // wipes on every render. Without it the result is silent: the
            // loading line has role="status", but replacing that node is a
            // removal, not an update to a region, and announces nothing.
            this.announcer = el('p', 'critique-announcer');
            this.announcer.setAttribute('role', 'status');
            this.announcer.setAttribute('aria-live', 'polite');
            container.appendChild(this.announcer);

            this.panel.addEventListener('click', (event) => {
                const button = event.target.closest('button[data-critique-action]');
                if (button) {
                    this._handleAction(button);
                    return;
                }
                const toggle = event.target.closest('.critique-disclosure');
                if (toggle) this._toggleDisclosure(toggle);
            });
        }

        _clear() {
            if (this.panel) this.panel.textContent = '';
        }

        _renderLoading() {
            this._clear();
            if (!this.panel) return;
            const status = el('p', 'critique-status');
            status.setAttribute('role', 'status');
            status.textContent = 'Asking the model to review each region…';
            this.panel.appendChild(status);
        }

        _renderError(message) {
            this._clear();
            if (!this.panel) return;
            const box = el('div', 'critique-error');
            box.setAttribute('role', 'alert');
            box.appendChild(el('strong', '', 'Review unavailable'));
            box.appendChild(el('p', '', message));
            this.panel.appendChild(box);
            this.panel.appendChild(this._closeButton());
            this._announce('Review unavailable. ' + message);
            this._reveal();
        }

        _renderResult(data) {
            this._clear();
            if (!this.panel) return;

            const summary = data.summary || {};
            const verdicts = data.verdicts || [];
            const missed = data.missed || [];
            const flagged = verdicts.filter(v => v.flagged &&
                !this._dismissed.has(v.index));
            const confirmed = verdicts.filter(v => v.verdict === 'confirmed');
            const unsure = verdicts.filter(v => v.verdict === 'uncertain');

            // Header: the count that matters first.
            const header = el('div', 'critique-header');
            const heading = el('h3', 'critique-heading');
            heading.textContent = flagged.length || missed.length
                ? `${flagged.length + missed.length} to look at`
                : 'Nothing flagged';
            header.appendChild(heading);

            const counts = [];
            if (summary.reviewed) counts.push(`${summary.reviewed} region${summary.reviewed === 1 ? '' : 's'} reviewed`);
            if (confirmed.length) counts.push(`${confirmed.length} confirmed`);
            if (unsure.length) counts.push(`${unsure.length} unclear`);
            if (summary.skipped) counts.push(`${summary.skipped} not reviewed`);
            if (counts.length) {
                header.appendChild(el('p', 'critique-counts', counts.join(' · ')));
            }
            header.appendChild(this._closeButton());
            this.panel.appendChild(header);

            if (summary.caveat) {
                this.panel.appendChild(el('p', 'critique-caveat', summary.caveat));
            }

            const staleNotice = el('p', 'critique-stale');
            staleNotice.setAttribute('role', 'status');
            staleNotice.hidden = true;
            staleNotice.textContent =
                'You have changed the annotations since this review ran. ' +
                'Run it again before acting on these.';
            this.panel.appendChild(staleNotice);
            this._staleNotice = staleNotice;

            if (flagged.length) {
                const list = el('ul', 'critique-list');
                flagged.forEach(v => {
                    // Reported at render rather than at request, so the paired
                    // accept/reject latency measures how long the annotator
                    // considered the finding and not how long the model took.
                    // Rubber-stamping a critique is exactly as bad as
                    // rubber-stamping a detection, and this is what lets the
                    // telemetry see it.
                    this._telemetry('ai_suggest', v.index);
                    list.appendChild(this._verdictCard(v));
                });
                this.panel.appendChild(list);
            }

            if (missed.length) {
                this.panel.appendChild(el('h4', 'critique-subheading',
                    `Possibly missed (${missed.length})`));
                const note = el('p', 'critique-note',
                    'The model cannot place these accurately, so they point at ' +
                    'a rough area to check — they are not annotations you can accept.');
                this.panel.appendChild(note);
                const list = el('ul', 'critique-list');
                missed.forEach((m, i) => list.appendChild(this._missedCard(m, i)));
                this.panel.appendChild(list);
            }

            if (!flagged.length && !missed.length) {
                this.panel.appendChild(el('p', 'critique-clean',
                    'The model agreed with every region it could judge. That is ' +
                    'not proof they are right — it did not find a reason to doubt them.'));
            }

            if (confirmed.length || unsure.length) {
                this.panel.appendChild(
                    this._disclosure('Show the regions it did not flag',
                        confirmed.concat(unsure)));
            }

            if (data.model) {
                this.panel.appendChild(el('p', 'critique-provenance',
                    `Reviewed by ${data.model}${data.cached ? ' (cached)' : ''}`));
            }

            this._announce(heading.textContent + '. ' +
                (counts.length ? counts.join(', ') + '.' : ''));
            this._reveal();
        }

        /**
         * Bring the panel into view.
         *
         * It is appended below the canvas, and a canvas plus two toolbars can
         * already fill a laptop viewport — so on a short window the results of
         * a request that took twenty seconds would land off-screen and read as
         * "nothing happened".
         */
        _reveal() {
            if (!this.panel || !this.panel.scrollIntoView) return;
            // An unrequested smooth scroll is exactly what prefers-reduced-motion
            // exists to suppress; jump straight there instead.
            const reduce = typeof window.matchMedia === 'function' &&
                window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            try {
                this.panel.scrollIntoView({
                    block: 'nearest',
                    behavior: reduce ? 'auto' : 'smooth',
                });
            } catch (e) {
                this.panel.scrollIntoView(false);
            }
        }

        _announce(message) {
            if (this.announcer) this.announcer.textContent = message;
        }

        _verdictCard(verdict) {
            const copy = VERDICT_COPY[verdict.verdict] ||
                { title: verdict.verdict, tone: 'info' };
            const card = el('li', `critique-card critique-${copy.tone}`);
            card.dataset.index = String(verdict.index);

            const title = el('div', 'critique-card-title');
            title.appendChild(el('span', 'critique-badge', copy.title));
            title.appendChild(el('span', 'critique-label', verdict.label || '(no label)'));
            card.appendChild(title);

            if (verdict.rationale) {
                card.appendChild(el('p', 'critique-rationale', verdict.rationale));
            }

            const actions = el('div', 'critique-actions');
            actions.appendChild(this._actionButton('show', verdict.index,
                'Show me', 'Select this annotation on the canvas'));

            if (verdict.suggested_label && verdict.suggested_label !== verdict.label) {
                actions.appendChild(this._actionButton('relabel', verdict.index,
                    `Relabel to “${verdict.suggested_label}”`,
                    'Change the label, keeping the shape',
                    { label: verdict.suggested_label }));
            }
            actions.appendChild(this._actionButton('delete', verdict.index,
                'Delete', 'Remove this annotation'));
            actions.appendChild(this._actionButton('dismiss', verdict.index,
                'Keep as is', 'Dismiss this suggestion and keep the annotation'));
            card.appendChild(actions);

            // Visual only. A per-card role="status" would mean up to 24
            // simultaneous live regions, and one that is `hidden` at render
            // then unhidden with its text set in the same tick announces
            // unreliably anyway. _say() speaks through the single announcer.
            const result = el('p', 'critique-card-result');
            result.hidden = true;
            card.appendChild(result);

            return card;
        }

        _missedCard(missed, i) {
            const card = el('li', 'critique-card critique-info');
            const title = el('div', 'critique-card-title');
            title.appendChild(el('span', 'critique-badge', 'Possibly missed'));
            title.appendChild(el('span', 'critique-label', missed.label));
            card.appendChild(title);
            if (missed.rationale) {
                card.appendChild(el('p', 'critique-rationale', missed.rationale));
            }
            if (missed.bbox) {
                const actions = el('div', 'critique-actions');
                actions.appendChild(this._actionButton('hint', i,
                    'Show the area', 'Outline the rough area on the canvas'));
                card.appendChild(actions);
            }
            return card;
        }

        _actionButton(action, index, text, title, extra) {
            const button = el('button', 'critique-btn', text);
            button.type = 'button';
            button.title = title || text;
            button.dataset.critiqueAction = action;
            button.dataset.index = String(index);
            if (extra && extra.label) button.dataset.label = extra.label;
            return button;
        }

        _closeButton() {
            const button = el('button', 'critique-close', '×');
            button.type = 'button';
            button.dataset.critiqueAction = 'close';
            button.dataset.index = '-1';
            button.setAttribute('aria-label', 'Close the review panel');
            return button;
        }

        _disclosure(text, verdicts) {
            const wrapper = el('div', 'critique-disclosure-wrap');
            const toggle = el('button', 'critique-disclosure', text);
            toggle.type = 'button';
            toggle.setAttribute('aria-expanded', 'false');
            const body = el('ul', 'critique-list critique-quiet');
            const bodyId = 'critique-unflagged-' + (this.schema || 'x');
            body.id = bodyId;
            toggle.setAttribute('aria-controls', bodyId);
            body.hidden = true;
            verdicts.forEach(v => {
                const item = el('li', 'critique-card critique-muted');
                const title = el('div', 'critique-card-title');
                title.appendChild(el('span', 'critique-badge',
                    v.verdict === 'confirmed' ? 'Confirmed' : 'Unclear'));
                title.appendChild(el('span', 'critique-label', v.label || '(no label)'));
                item.appendChild(title);
                if (v.rationale) {
                    item.appendChild(el('p', 'critique-rationale', v.rationale));
                }
                const actions = el('div', 'critique-actions');
                actions.appendChild(this._actionButton('show', v.index,
                    'Show me', 'Select this annotation on the canvas'));
                item.appendChild(actions);
                body.appendChild(item);
            });
            toggle._body = body;
            wrapper.appendChild(toggle);
            wrapper.appendChild(body);
            return wrapper;
        }

        _toggleDisclosure(toggle) {
            const body = toggle._body;
            if (!body) return;
            const open = toggle.getAttribute('aria-expanded') === 'true';
            toggle.setAttribute('aria-expanded', open ? 'false' : 'true');
            body.hidden = open;
        }

        // -- actions ---------------------------------------------------

        _handleAction(button) {
            const action = button.dataset.critiqueAction;
            const index = parseInt(button.dataset.index, 10);

            if (action === 'close') {
                if (this.panel) this.panel.remove();
                return;
            }

            if (action === 'hint') {
                this._showMissedArea(index);
                return;
            }

            // Everything below mutates an annotation identified by position,
            // so a canvas that has changed since the review means the position
            // no longer refers to the reviewed shape.
            if (this._isStale() && action !== 'dismiss') {
                if (this._staleNotice) this._staleNotice.hidden = false;
                return;
            }

            const card = button.closest('.critique-card');
            const result = card ? card.querySelector('.critique-card-result') : null;

            if (action === 'show') {
                const focused = this.manager.focusAnnotation(index);
                this._say(result, focused
                    ? 'Selected on the canvas.'
                    : 'This is a brush mask, so it cannot be selected — it is ' +
                      'highlighted in its own colour on the image.');
                return;
            }

            if (action === 'relabel') {
                const label = button.dataset.label;
                const ok = this.manager.relabelAnnotation(index, label);
                this._telemetry(ok ? 'ai_accept' : 'ai_reject', index);
                this._say(result, ok
                    ? `Relabelled to “${label}”.`
                    : `Could not relabel — “${label}” is not a label in this task, ` +
                      'or a mask of that label already exists here.');
                if (ok) this._retire(card, index);
                return;
            }

            if (action === 'delete') {
                const ok = this.manager.deleteAnnotation(index);
                this._telemetry(ok ? 'ai_accept' : 'ai_reject', index);
                if (ok) {
                    // Deleting renumbers everything after it, so the remaining
                    // verdicts now point at the wrong shapes. Say so instead of
                    // leaving buttons that would edit the wrong annotation.
                    this._baseline = undefined;
                    if (this._staleNotice) {
                        this._staleNotice.hidden = false;
                        this._staleNotice.textContent =
                            'Deleting renumbered the annotations, so the rest of ' +
                            'this review no longer lines up. Run it again.';
                    }
                    this._retire(card, index);
                } else {
                    this._say(result, 'Could not delete that annotation.');
                }
                return;
            }

            if (action === 'dismiss') {
                this._telemetry('ai_reject', index);
                this._dismissed.add(index);
                this._retire(card, index);
            }
        }

        _retire(card, index) {
            if (!card) return;
            card.classList.add('critique-done');

            // Move focus BEFORE disabling. Disabling the button that was just
            // pressed drops focus to <body>, so the next Tab restarts from the
            // top of the document — on a 24-finding queue that is punishing,
            // and it is invisible to anyone testing with a mouse.
            const hadFocus = card.contains(document.activeElement);
            const result = card.querySelector('.critique-card-result');

            card.querySelectorAll('button[data-critique-action]').forEach(b => {
                b.disabled = true;
            });

            if (!hadFocus) return;
            const next = card.nextElementSibling &&
                card.nextElementSibling.querySelector('button:not([disabled])');
            if (next) {
                next.focus();
            } else if (result && !result.hidden) {
                result.setAttribute('tabindex', '-1');
                result.focus();
            }
        }

        _say(node, message) {
            if (node) {
                node.textContent = message;
                node.hidden = false;
            }
            this._announce(message);
        }

        /**
         * Outline where the model thinks a missed object is.
         *
         * Deliberately NOT an annotation: it is drawn as a temporary overlay
         * that no serializer sees, because the coordinate is a guess and a
         * guessed coordinate in a dataset is worse than no coordinate.
         */
        _showMissedArea(i) {
            const missed = (this.lastResult?.missed || [])[i];
            const manager = this.manager;
            if (!missed || !missed.bbox || !manager?.canvas || !manager.image) return;

            const image = manager.image;
            const w = image.width * image.scaleX;
            const h = image.height * image.scaleY;
            const [nx, ny, nw, nh] = missed.bbox;

            if (this._hintRect) manager.canvas.remove(this._hintRect);
            this._hintRect = new fabric.Rect({
                left: image.left + nx * w,
                top: image.top + ny * h,
                width: Math.max(4, nw * w),
                height: Math.max(4, nh * h),
                fill: 'transparent',
                stroke: '#b45309',
                strokeWidth: 2,
                strokeDashArray: [8, 4],
                selectable: false,
                evented: false,
                excludeFromExport: true,
            });
            // No annotationData, so getAnnotationHandles() and the serializer
            // both skip it — this is the property that keeps it out of the data.
            manager.canvas.add(this._hintRect);
            manager.canvas.requestRenderAll();

            window.setTimeout(() => {
                if (this._hintRect) {
                    manager.canvas.remove(this._hintRect);
                    this._hintRect = null;
                    manager.canvas.requestRenderAll();
                }
            }, 4000);
        }

        _telemetry(action, index) {
            if (typeof window.recordAnnotationTelemetry !== 'function') return;
            window.recordAnnotationTelemetry(this.schema, action, {
                meta: { sid: `critique-${index}`, src: 'critique' },
            });
        }
    }

    /** Build an element without touching innerHTML. */
    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        // Safari drops a <ul>'s implicit list role when list-style is none,
        // so VoiceOver announces loose text instead of "list, 3 items" — and
        // the item count is this panel's primary structure.
        if (tag === 'ul') node.setAttribute('role', 'list');
        if (tag === 'li') node.setAttribute('role', 'listitem');
        return node;
    }

    window.AnnotationCritiqueReview = AnnotationCritiqueReview;
})();

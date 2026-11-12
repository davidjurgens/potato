/**
 * The prompt box: type "traffic cone", get every traffic cone boxed.
 *
 * WHAT THIS OWNS, AND WHAT IT DELIBERATELY DOES NOT
 * -------------------------------------------------
 * It owns the input, the run button, the status line, and turning a phrase
 * into detections. It does NOT own accepting them: results are handed to the
 * existing visual-AI suggestion path, which already draws each box, lets the
 * annotator resize it, and accepts or rejects it one at a time.
 *
 * That reuse is the point. Model output that lands directly in the annotation
 * store is how a dataset comes to agree with a model rather than with reality
 * — and every quality measure Potato has, inter-annotator agreement included,
 * looks BETTER when that happens, because the geometry is identical to careful
 * work. The only place the difference shows is the timing, which is why
 * accepting a suggestion is a separate, recorded act.
 *
 * WHY DETECTION AND SEGMENTATION ARE SEPARATE STEPS
 * -------------------------------------------------
 * Grounding DINO returns rectangles. When the project also configures the
 * `sam` tool and asks for masks, each accepted rectangle is handed to the SAM
 * decoder as a box prompt — the same path a hand-drawn box takes. Two small
 * permissively licensed models doing what one 3.5 GB licence-gated model does.
 */

(function (global) {
    'use strict';

    class TextPromptTool {
        /**
         * @param {object} options
         * @param {HTMLElement} options.container  the schema's root element
         * @param {object} options.manager   the ImageAnnotationManager
         * @param {object} options.session   a GroundingDinoSession
         * @param {object} [options.assistant] the visual AI assistant, which
         *        owns the accept/reject UI. Absent in tests.
         * @param {boolean} [options.segment] pipe accepted boxes through SAM
         */
        constructor(options = {}) {
            this.container = options.container || null;
            this.manager = options.manager || null;
            this.session = options.session || null;
            this.assistant = options.assistant || null;
            this.segment = !!options.segment;

            this.input = null;
            this.button = null;
            this.statusEl = null;
            this.running = false;
            this.lastDetections = [];
        }

        /**
         * Locate the controls the schema rendered.
         *
         * Deliberately does NOT bind events. The button has to work before
         * this tool exists — pressing Find is what triggers the 145 MB
         * download that constructs it — so the manager owns the listener and
         * calls `run()` once the model is up. A second listener here would
         * fire the detector twice per press.
         */
        attach() {
            if (!this.container) return false;
            this.input = this.container.querySelector('.text-prompt-input');
            this.button = this.container.querySelector('.text-prompt-run');
            this.statusEl = this.container.querySelector('.text-prompt-status');
            return !!(this.input && this.button);
        }

        /** Split the box's contents into phrases. */
        phrases() {
            const raw = this.input ? this.input.value : '';
            return String(raw)
                .split(',')
                .map((p) => p.trim())
                .filter(Boolean);
        }

        _status(message, kind = 'info') {
            if (!this.statusEl) return;
            this.statusEl.textContent = message;
            this.statusEl.dataset.kind = kind;
        }

        _busy(busy) {
            this.running = busy;
            if (this.button) {
                this.button.disabled = busy;
                // A model download is tens of seconds on a first run, so the
                // button has to say something other than "Find" while it waits.
                this.button.textContent = busy ? 'Finding…' : 'Find';
            }
        }

        /**
         * Run the detector over the current image.
         *
         * @returns {Promise<Array|null>} the detections, or null on failure
         */
        async run() {
            if (this.running) return null;
            const phrases = this.phrases();
            if (!phrases.length) {
                this._status('Type what to look for, e.g. "person, bicycle".',
                             'warn');
                return null;
            }
            if (!this.session || !this.manager) return null;

            const image = this.manager.image;
            if (!image) {
                this._status('No image is loaded yet.', 'warn');
                return null;
            }

            this._busy(true);
            this._status('Loading the detector…');
            let detections = null;
            try {
                const element = image.getElement ? image.getElement() : image;
                const width = element.naturalWidth || image.width;
                const height = element.naturalHeight || image.height;
                detections = await this.session.detect(
                    element, width, height, phrases);
            } finally {
                this._busy(false);
            }

            if (detections === null) {
                this._status(this.session.statusMessage()
                             || 'The detector could not run.', 'error');
                return null;
            }

            this.lastDetections = detections;
            if (!detections.length) {
                this._status(
                    `Nothing matched ${phrases.join(', ')}. Try a simpler `
                    + `phrase, or draw it by hand.`, 'warn');
                return detections;
            }

            this._status(
                `${detections.length} suggestion`
                + `${detections.length === 1 ? '' : 's'} — accept or reject `
                + `each one.`);
            this._present(detections);
            return detections;
        }

        /**
         * Hand detections to the suggestion UI.
         *
         * Every model in Potato that proposes geometry goes through this same
         * path, so accepting one is recorded, undoable, and counted in the
         * telemetry that distinguishes review from rubber-stamping.
         */
        _present(detections) {
            // Resolved late as well as early: the schema bootstrap attaches the
            // assistant to the container AFTER building the manager, and this
            // tool may be constructed at either moment.
            if (!this.assistant && this.container) {
                this.assistant = this.container.aiAssistant || null;
            }
            if (this.assistant && this.assistant._renderDetections) {
                this.assistant._renderDetections(detections.map((d) => ({
                    label: d.label,
                    confidence: d.confidence,
                    bbox: d.bbox,
                })));
                return;
            }
            // No assistant is a configuration problem, not a silent one: the
            // annotator asked for something and must be told it went nowhere.
            this._status(
                'Found matches, but this project has no review panel to show '
                + 'them in. Enable ai_support to review suggestions.', 'error');
        }
    }

    const api = { TextPromptTool };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    if (global) {
        global.TextPromptTool = TextPromptTool;
    }
})(typeof window !== 'undefined' ? window : this);

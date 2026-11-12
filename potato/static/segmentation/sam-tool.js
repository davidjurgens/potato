/**
 * The magic-wand tool: click an object, get a mask.
 *
 * Sits between `ImageAnnotationManager` (which owns the canvas and the stored
 * annotations) and `SAMSession` (which owns the model). It holds exactly one
 * piece of state the others should not: the *in-progress* prompt — the points
 * and box the annotator has placed but not yet accepted.
 *
 * WHY A PENDING STATE AT ALL
 * --------------------------
 * A first click rarely lands the mask perfectly. The tool that only ever
 * commits is the one people abandon: they get a nearly-right mask, delete it,
 * and reach for the brush. So a click produces a *preview* which subsequent
 * clicks refine — positive to add, negative to subtract — and only Enter (or
 * the Accept button) turns it into a real annotation.
 *
 * WHAT IT DELIBERATELY DOES NOT DO
 * --------------------------------
 * It never builds an annotation object by hand. Accepting routes through
 * `addAnnotation()`, the same sanctioned entry point AI detections and
 * copy-from-previous use, so the client coordinate contract is enforced on
 * this path too.
 */

(function (global) {
    'use strict';

    /** How the annotator's modifier maps onto SAM's point labels. */
    const POINT = { BACKGROUND: 0, FOREGROUND: 1 };

    /** Preview styling. Distinct from committed masks, deliberately. */
    const PREVIEW_ALPHA = 0.45;
    const PREVIEW_COLOR = '#00b3ff';

    class SAMTool {
        /**
         * @param {object} options
         * @param {object} options.session   a SAMSession
         * @param {object} options.manager   the ImageAnnotationManager
         * @param {function} [options.onStatus] (message, kind) for the UI
         */
        constructor(options = {}) {
            this.session = options.session || null;
            this.manager = options.manager || null;
            this.onStatus = options.onStatus || null;

            this.active = false;
            this.points = [];      // [[x, y, label], ...] in ORIGINAL pixels
            this.box = null;       // [x, y, w, h] in original pixels
            this.preview = null;   // {rle, bbox, score, area}
            this.busy = false;
            this._encodedKey = null;
        }

        _status(message, kind) {
            if (this.onStatus) this.onStatus(message, kind || 'info');
        }

        /** True when a preview exists that could be accepted. */
        hasPreview() {
            return !!(this.preview && this.preview.rle);
        }

        /**
         * Prepare the current image. Safe to call repeatedly; the session
         * caches, so a revisit is free.
         *
         * @param {string} key      image URL, the cache key
         * @param {CanvasImageSource} source
         * @param {number} width    ORIGINAL width
         * @param {number} height   ORIGINAL height
         */
        async prepare(key, source, width, height) {
            if (!this.session) return false;
            if (this._encodedKey === key && this.session.isReady()) return true;

            this.busy = true;
            this._status('Preparing this image for segmentation…', 'busy');
            const embedding = await this.session.encodeImage(
                key, source, width, height);
            this.busy = false;

            if (!embedding) {
                this._status(this.session.statusMessage(), 'error');
                return false;
            }
            this._encodedKey = key;
            this._status('Click an object to segment it.', 'ready');
            return true;
        }

        /**
         * Add a prompt point and refresh the preview.
         *
         * @param {number} x  original image pixels
         * @param {number} y  original image pixels
         * @param {boolean} [negative] subtract instead of add
         */
        async addPoint(x, y, negative) {
            this.points.push([x, y, negative ? POINT.BACKGROUND
                                             : POINT.FOREGROUND]);
            return this._refresh();
        }

        /** Set a box prompt, replacing any previous one. */
        async setBox(x, y, width, height) {
            // A drag of a couple of pixels is a click that wobbled, not a box.
            // Treating it as a box gives SAM a degenerate prompt and a mask
            // that looks like a random fragment.
            if (Math.abs(width) < 4 || Math.abs(height) < 4) {
                return this.addPoint(x, y, false);
            }
            this.box = [
                Math.min(x, x + width), Math.min(y, y + height),
                Math.abs(width), Math.abs(height),
            ];
            return this._refresh();
        }

        /** Drop the most recent point; the preview goes back a step. */
        async undoPoint() {
            if (this.points.length === 0) {
                if (this.box) { this.box = null; return this._refresh(); }
                return null;
            }
            this.points.pop();
            // The refinement chain is built from the PREVIOUS mask, so undoing
            // a point while keeping it would refine against a mask that point
            // helped produce -- the undo would not fully undo.
            if (this.session) this.session.clearRefinement();
            return this._refresh();
        }

        async _refresh() {
            if (!this.session) return null;
            if (this.points.length === 0 && !this.box) {
                this.preview = null;
                this._renderPreview();
                return null;
            }

            this.busy = true;
            const result = await this.session.segment({
                points: this.points,
                box: this.box,
            });
            this.busy = false;

            if (!result) {
                this.preview = null;
                this._status(this.session.statusMessage(), 'error');
                this._renderPreview();
                return null;
            }
            if (!result.rle) {
                // Genuinely empty, not an error: a click on featureless
                // background produces nothing. Say so instead of adding an
                // empty annotation the annotator has to find and delete.
                this.preview = null;
                this._status('Nothing found at that point. Try clicking the '
                           + 'centre of the object.', 'empty');
                this._renderPreview();
                return null;
            }

            this.preview = result;
            // SAM's iou_predictions is a regression head, not a probability:
            // it routinely returns slightly above 1. Showing "confidence 102%"
            // reads as a broken readout, so it is clamped for display only --
            // the raw score is kept on the preview.
            const percent = Math.min(100, Math.round(result.score * 100));
            this._status(
                `Mask ready (confidence ${percent}%). Click again to refine, `
                + `Shift-click to subtract, Enter to accept.`, 'preview');
            this._renderPreview();
            return result;
        }

        /**
         * Commit the preview as a real annotation.
         *
         * Routes through addAnnotation() rather than building the object here,
         * so the client contract is enforced on this path too.
         */
        accept(label) {
            if (!this.hasPreview() || !this.manager) return null;

            const name = label || this.manager.activeLabel;
            const annotation = {
                type: 'mask',
                label: name,
                rle: this.preview.rle,
                // A SAM mask is ONE object, so it must say iscrowd=0 out loud:
                // masks default to crowd, and a COCO export would otherwise
                // merge every segmented instance of a class into one region.
                iscrowd: 0,
            };

            // Every accepted mask is a DISTINCT object and needs its own
            // instance index. Masks are keyed "label#instance", so without one
            // they all land on the bare label key and each accept silently
            // overwrites the last -- segmenting three cats stored one.
            if (typeof this.manager._nextInstanceIndex === 'function') {
                annotation.instance = this.manager._nextInstanceIndex(name);
            }
            const added = this.manager.addAnnotation(annotation);
            this.clear();
            this._status('Mask added.', 'accepted');
            return added;
        }

        /** Throw away the in-progress prompt and preview. */
        clear() {
            this.points = [];
            this.box = null;
            this.preview = null;
            if (this.session) this.session.clearRefinement();
            this._renderPreview();
        }

        /** Called when the annotator switches items. */
        reset() {
            this.clear();
            this._encodedKey = null;
            if (this.session) this.session.reset();
        }

        /**
         * Hand the preview to the manager for drawing.
         *
         * The tool does not paint: the manager owns the canvas, the viewport
         * transform and the mask buffers, and a second painter would drift out
         * of alignment under zoom exactly as the old segmentation manager did.
         */
        _renderPreview() {
            if (!this.manager || !this.manager.setSegmentationPreview) return;
            this.manager.setSegmentationPreview(
                this.preview
                    ? {
                        rle: this.preview.rle,
                        points: this.points,
                        box: this.box,
                        color: PREVIEW_COLOR,
                        alpha: PREVIEW_ALPHA,
                    }
                    : null);
        }
    }

    const api = { SAMTool, POINT, PREVIEW_COLOR, PREVIEW_ALPHA };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    if (global) global.SAMTool = SAMTool;
})(typeof window !== 'undefined' ? window : this);

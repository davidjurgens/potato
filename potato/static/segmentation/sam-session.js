/**
 * Browser-side interactive segmentation session (SAM-class models via ONNX).
 *
 * WHY THE BROWSER IS THE DEFAULT PATH
 * -----------------------------------
 * `pip install potato` plus one `potato download-models` gives working
 * segmentation with no GPU and no outbound network at annotation time — which
 * matters because several groups deploy Potato air-gapped. A server endpoint
 * exists for labs with a GPU that want a bigger model, but it is the exception.
 *
 * THE SPLIT THAT MAKES IT FEEL INSTANT
 * ------------------------------------
 * The encoder is expensive (hundreds of ms) and runs ONCE per image. The
 * decoder is cheap (<100ms) and runs once per click. Keeping them apart, and
 * caching the embedding per image, is the whole reason click-to-segment feels
 * interactive rather than like a request.
 *
 * EVERY FAILURE HAS A NAMED STATE
 * -------------------------------
 * Missing model, unsupported runtime, failed encode: each is reachable in
 * normal use and each needs to say what to do next. A segmentation tool that
 * silently does nothing when the weights are absent is worse than one that is
 * absent.
 *
 * THE TENSOR CONTRACT LIVES IN sam-preprocess.js
 * ----------------------------------------------
 * Deliberately, because it is the part that cannot be guessed — see that
 * file's header and `tests/unit/test_sam_model_pipeline.py`, which checks it
 * against the real weights. Everything here is orchestration.
 */

(function (global) {
    'use strict';

    const isNode = (typeof require === 'function' && typeof module !== 'undefined');
    const base = isNode
        ? require('./model-session.js')
        : { ModelSession: global.ModelSession, MODEL_ERROR: global.MODEL_ERROR };

    const SAM_STATE = {
        IDLE: 'idle',
        LOADING_RUNTIME: 'loading-runtime',
        LOADING_MODEL: 'loading-model',
        ENCODING: 'encoding',
        READY: 'ready',
        ERROR: 'error',
    };

    /**
     * Errors the UI is expected to render differently.
     *
     * The first two are the shared ones, by value as well as by name: a
     * missing model and a dead runtime mean the same thing whichever model is
     * loading, and the base class classifies them. The last two are SAM's own
     * pipeline stages.
     */
    const SAM_ERROR = {
        RUNTIME_UNAVAILABLE: base.MODEL_ERROR.RUNTIME_UNAVAILABLE,
        MODEL_MISSING: base.MODEL_ERROR.MODEL_MISSING,
        ENCODE_FAILED: 'encode-failed',
        DECODE_FAILED: 'decode-failed',
    };

    const preprocess = isNode
        ? require('./sam-preprocess.js')
        : (global && global.SAMPreprocess);

    class SAMSession extends base.ModelSession {
        /**
         * @param {object} options
         * @param {string} options.model         model key, e.g. 'mobile_sam'
         * @param {string} options.modelBaseUrl  where the .onnx files are served
         * @param {object} [options.runtime]     injected ONNX runtime
         * @param {function} [options.onStateChange] called with (state, detail)
         */
        constructor(options = {}) {
            super(Object.assign(
                { modelBaseUrl: '/static/models' }, options,
                { model: options.model || 'mobile_sam' }));

            // Embeddings are keyed by image URL, not by index: an annotator who
            // navigates back to an image should not pay to encode it twice.
            this._embeddings = new Map();
            this._embeddingLimit = options.embeddingLimit || 4;
            this._currentKey = null;
            // Injected canvas factory. Exists so the session can be driven
            // headlessly in tests, and so a Web Worker can supply an
            // OffscreenCanvas without this class knowing about either.
            this.canvasFactory = options.canvasFactory || null;
            // Geometry of the current image, needed to scale every click.
            this._geometry = null;
            // Previous low-res mask, so a second click REFINES the first result
            // instead of starting over.
            this._lastLowResMask = null;
        }

        /**
         * The two graphs SAM needs. Named `encoder`/`decoder` because the
         * split between them is the reason clicking feels instant: the encoder
         * runs once per image, the decoder once per click.
         */
        graphFiles() {
            return { encoder: 'encoder.onnx', decoder: 'decoder.onnx' };
        }

        get _encoder() { return this.graphs.encoder; }

        get _decoder() { return this.graphs.decoder; }

        /** Say what still works, which for segmentation is the manual tools. */
        fallbackHint() {
            return ' The brush and polygon tools still work.';
        }

        /** SAM's own pipeline stages; the shared errors come from the base. */
        extraStatusMessage(kind) {
            switch (kind) {
                case SAM_ERROR.ENCODE_FAILED:
                    return 'This image could not be prepared for segmentation. '
                         + 'The brush and polygon tools still work.';
                case SAM_ERROR.DECODE_FAILED:
                    return 'That click could not be turned into a mask. Try '
                         + 'another point, or use the brush tool.';
                default:
                    return '';
            }
        }

        /**
         * Encode one image, or reuse the cached embedding.
         *
         * @param {string} key    stable identifier (the image URL)
         * @param {CanvasImageSource} source  <img>, canvas or ImageBitmap
         * @param {number} width  ORIGINAL width in pixels
         * @param {number} height ORIGINAL height in pixels
         */
        async encodeImage(key, source, width, height) {
            const cached = this._embeddings.get(key);
            if (cached) {
                // Re-insert to mark it recently USED. Without this the eviction
                // order is least-recently-*inserted*, so an annotator flipping
                // between two images would evict the one they keep returning to.
                this._remember(key, cached);
                this._currentKey = key;
                this._geometry = cached.geometry;
                this._lastLowResMask = null;
                this._setState(SAM_STATE.READY, { cached: true });
                return cached.embedding;
            }

            if (!(await this.load())) return null;

            this._setState(SAM_STATE.ENCODING, { key });
            let tensor;
            try {
                tensor = preprocess.imageToTensor(
                    source, width, height, this.canvasFactory);
            } catch (err) {
                return this._fail(SAM_ERROR.ENCODE_FAILED,
                                  (err && err.message) || String(err));
            }

            let output;
            try {
                const input = new this.runtime.Tensor(
                    'float32', tensor.data, tensor.dims);
                output = await this._encoder.run({ input_image: input });
            } catch (err) {
                return this._fail(SAM_ERROR.ENCODE_FAILED,
                                  (err && err.message) || String(err));
            }

            const embedding = output.image_embeddings
                || output[Object.keys(output)[0]];
            const geometry = {
                scale: tensor.scale,
                origWidth: tensor.origWidth,
                origHeight: tensor.origHeight,
            };
            this._remember(key, { embedding, geometry });
            this._currentKey = key;
            this._geometry = geometry;
            this._lastLowResMask = null;
            this._setState(SAM_STATE.READY, { cached: false });
            return embedding;
        }

        /** Least-recently-used insert, so a long session cannot grow unbounded. */
        _remember(key, entry) {
            if (this._embeddings.has(key)) this._embeddings.delete(key);
            this._embeddings.set(key, entry);
            while (this._embeddings.size > this._embeddingLimit) {
                const oldest = this._embeddings.keys().next().value;
                this._embeddings.delete(oldest);
            }
        }

        /**
         * Turn point/box prompts into a mask.
         *
         * Coordinates are in ORIGINAL IMAGE PIXELS — the space the annotator
         * clicked in. Scaling into SAM's 1024-space happens inside
         * `buildPromptTensors`, once, so no call site can forget it.
         *
         * @param {object} prompts
         * @param {Array} [prompts.points] [[x, y, label], ...] 1=fg, 0=bg
         * @param {Array} [prompts.box]    [x, y, w, h]
         * @param {boolean} [prompts.refine] feed back the previous mask
         * @returns {Promise<object|null>} {rle, bbox, score, area}
         */
        async segment(prompts) {
            if (!this.isReady()) {
                return this._fail(this.errorKind || SAM_ERROR.MODEL_MISSING,
                                  this.error || 'model not loaded');
            }
            const entry = this._embeddings.get(this._currentKey);
            if (!entry) {
                return this._fail(SAM_ERROR.ENCODE_FAILED,
                                  'no embedding for the current image');
            }

            const withMask = Object.assign({}, prompts);
            if (prompts.refine !== false && this._lastLowResMask) {
                withMask.maskInput = this._lastLowResMask;
            }

            const tensors = preprocess.buildPromptTensors(withMask, entry.geometry);
            if (!tensors) {
                return this._fail(SAM_ERROR.DECODE_FAILED,
                                  'no points or box were given');
            }

            let output;
            try {
                const feeds = { image_embeddings: entry.embedding };
                Object.keys(tensors).forEach((name) => {
                    feeds[name] = new this.runtime.Tensor(
                        'float32', tensors[name].data, tensors[name].dims);
                });
                output = await this._decoder.run(feeds);
            } catch (err) {
                return this._fail(SAM_ERROR.DECODE_FAILED,
                                  (err && err.message) || String(err));
            }

            return this._toAnnotation(output, entry.geometry);
        }

        /**
         * Decoder output -> the mask shape the rest of Potato speaks.
         *
         * Returns Potato RLE, not raw logits, because that is what
         * `addAnnotation` takes and what gets stored. Converting here means
         * there is one place that knows the threshold.
         */
        _toAnnotation(output, geometry) {
            const masks = output.masks || output[Object.keys(output)[0]];
            if (!masks || !masks.data) {
                return this._fail(SAM_ERROR.DECODE_FAILED,
                                  'decoder returned no masks');
            }
            const scores = output.iou_predictions
                ? output.iou_predictions.data : null;
            const width = geometry.origWidth;
            const height = geometry.origHeight;

            const best = preprocess.selectBestMask(
                masks.data, scores, width, height);

            // Keep the low-res mask so the NEXT click refines this result.
            if (output.low_res_masks && output.low_res_masks.data) {
                const lowStride = preprocess.LOW_RES_SIZE * preprocess.LOW_RES_SIZE;
                this._lastLowResMask = output.low_res_masks.data.subarray(
                    best.index * lowStride, (best.index + 1) * lowStride);
            }

            const rle = preprocess.logitsToRle(best.logits, width, height);
            if (rle.area === 0) {
                // A real outcome, not an error: a click on featureless
                // background legitimately produces nothing. Saying so beats
                // adding an empty annotation the annotator has to find and
                // delete.
                return { rle: null, bbox: null, score: best.score, area: 0 };
            }

            return {
                rle: { counts: rle.counts, size: rle.size },
                bbox: preprocess.logitsToBbox(best.logits, width, height),
                score: best.score,
                area: rle.area,
            };
        }

        /**
         * Carry a mask from one frame to the next by re-prompting.
         *
         * WHAT THIS IS NOT
         * ----------------
         * This is **not** SAM 2 memory propagation. SAM 2 tracks objects with a
         * memory bank — a `memory_encoder` that stores the predicted mask plus
         * frame features, and a `memory_attention` module that conditions the
         * next frame on it. Neither module appears in ANY published SAM 2 ONNX
         * export (checked across onnx-community, SharpAI, okaris and Suhas-G:
         * all ship `vision_encoder` + `prompt_encoder_mask_decoder` only, which
         * is SAM 2's single-image path). Real propagation is therefore not
         * available in the browser today, and calling this that would be a lie.
         *
         * WHAT IT ACTUALLY DOES
         * ---------------------
         * Seeds the next frame with the previous frame's result: the mask goes
         * in as `mask_input` — the same input iterative refinement uses — plus
         * a positive point at its centroid to anchor which object is meant.
         *
         * That works well for an object moving smoothly and slowly, and fails
         * on fast motion, occlusion, and objects leaving frame. It degrades by
         * producing a visibly wrong mask on the frame where it fails, not by
         * silently drifting, which is why the caller is expected to show each
         * result for confirmation rather than accept a whole run blindly.
         *
         * @param {string} key      the NEXT frame's cache key
         * @param {*} source        the next frame's image source
         * @param {number} width
         * @param {number} height
         * @param {object} seed     {rle, bbox} from the previous frame
         * @returns {Promise<object|null>} same shape as segment()
         */
        async propagateFrom(key, source, width, height, seed) {
            if (!seed || !seed.bbox) return null;

            const embedding = await this.encodeImage(key, source, width, height);
            if (!embedding) return null;

            // The centroid of the previous box is the cheapest anchor that says
            // "this object, not its neighbour". Without a point prompt the
            // decoder has only the prior mask and readily jumps to whatever is
            // most salient nearby.
            const cx = seed.bbox.x + seed.bbox.width / 2;
            const cy = seed.bbox.y + seed.bbox.height / 2;

            this._lastLowResMask = seed.lowRes || null;
            return this.segment({
                points: [[cx, cy, 1]],
                // The previous box constrains the search to roughly where the
                // object was, which is what keeps a nearby distractor out.
                box: [seed.bbox.x, seed.bbox.y, seed.bbox.width, seed.bbox.height],
                refine: !!seed.lowRes,
            });
        }

        /** Drop cached embeddings — call when the annotator leaves the item. */
        reset() {
            this._embeddings.clear();
            this._currentKey = null;
            this._geometry = null;
            this._lastLowResMask = null;
        }

        /** Forget the refinement chain without dropping the embedding. */
        clearRefinement() {
            this._lastLowResMask = null;
        }
    }

    const api = { SAMSession, SAM_STATE, SAM_ERROR };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    if (global) {
        global.SAMSession = SAMSession;
        global.SAM_STATE = SAM_STATE;
        global.SAM_ERROR = SAM_ERROR;
    }
})(typeof window !== 'undefined' ? window : this);

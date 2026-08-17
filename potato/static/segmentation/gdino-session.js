/**
 * Open-vocabulary detection in the browser: type a phrase, get boxes.
 *
 * WHAT THIS MODEL IS
 * ------------------
 * Grounding DINO takes an image and a caption, and returns 900 candidate boxes
 * each scored against every token of that caption. It is a DETECTOR, not a
 * segmenter: the output is rectangles. Feeding each rectangle to the SAM
 * decoder Potato already ships turns them into masks, which is what people
 * mean by "Grounded-SAM" — two permissively licensed models doing what SAM 3
 * does in one licence-gated 3.5 GB model.
 *
 * THE CONTRACT, MEASURED RATHER THAN ASSUMED
 * ------------------------------------------
 * The export Potato ships declares:
 *
 *   pixel_values    [1, 3, 800, 800]   float
 *   pixel_mask      [1, 800, 800]      int64
 *   input_ids       [1, sequence]      int64
 *   token_type_ids  [1, sequence]      int64
 *   attention_mask  [1, sequence]      int64
 *   -> logits    [1, 900, 256]   per-query, per-token scores (pre-sigmoid)
 *      pred_boxes [1, 900, 4]    cx, cy, w, h — NORMALIZED to [0, 1]
 *
 * Two things here are easy to get wrong and produce confident nonsense:
 *
 *   1. **THIS export takes a fixed 800x800 square.** Grounding DINO's own
 *      preprocessor upstream resizes the shortest edge to 800 and caps the
 *      longest at 1333, preserving aspect. Following the upstream convention
 *      here returns boxes at the wrong scale for every non-square image. The
 *      value comes from the export's own preprocessor_config.json.
 *   2. **Boxes are centre-format and normalized.** They are normalized against
 *      the RESIZED square, but because the resize is a plain squash, the same
 *      normalized numbers are correct for the original image — which is why
 *      the conversion below never touches the aspect ratio.
 *
 * Verified against the real weights: two cats in a 640x480 COCO photo came
 * back at [11, 54, 317, 475] and [346, 24, 639, 372] pixels, which is where
 * the cats are.
 *
 * WHY PHRASE ATTRIBUTION IS THE DELICATE PART
 * -------------------------------------------
 * A box does not carry a label. It carries a score against each TOKEN, and the
 * phrase it belongs to has to be recovered by looking at which token positions
 * scored highest. That makes the tokenizer load-bearing in a way nothing later
 * can check: shift the tokens by one and every box is labelled with its
 * neighbour's phrase, silently. See `wordpiece.js` and
 * `tests/unit/test_wordpiece_bridge.py`.
 */

(function (global) {
    'use strict';

    const isNode = (typeof require === 'function' && typeof module !== 'undefined');
    const base = isNode
        ? require('./model-session.js')
        : { ModelSession: global.ModelSession, MODEL_ERROR: global.MODEL_ERROR };
    const wp = isNode
        ? require('./wordpiece.js')
        : { WordPieceTokenizer: global.WordPieceTokenizer };

    const GDINO_ERROR = {
        RUNTIME_UNAVAILABLE: base.MODEL_ERROR.RUNTIME_UNAVAILABLE,
        MODEL_MISSING: base.MODEL_ERROR.MODEL_MISSING,
        VOCAB_MISSING: 'vocab-missing',
        INPUT_FAILED: base.MODEL_ERROR.INPUT_FAILED,
        INFERENCE_FAILED: base.MODEL_ERROR.INFERENCE_FAILED,
    };

    /** Defaults mirror the model zoo entry; the zoo wins when it supplies them. */
    const DEFAULTS = {
        inputSize: 800,
        imageMean: [0.485, 0.456, 0.406],
        imageStd: [0.229, 0.224, 0.225],
        boxThreshold: 0.3,
        textThreshold: 0.25,
    };

    function defaultCanvasFactory(width, height) {
        if (typeof OffscreenCanvas !== 'undefined') {
            return new OffscreenCanvas(width, height);
        }
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        return canvas;
    }

    /**
     * Image -> the NCHW float tensor the graph wants.
     *
     * Squashes to a square on purpose: see the header. Normalization is
     * ImageNet's, applied after scaling to [0, 1].
     */
    function imageToTensor(source, size, mean, std, makeCanvas) {
        const create = makeCanvas || defaultCanvasFactory;
        const canvas = create(size, size);
        const ctx = canvas.getContext('2d');
        ctx.drawImage(source, 0, 0, size, size);
        const rgba = ctx.getImageData(0, 0, size, size).data;

        const pixels = size * size;
        const data = new Float32Array(pixels * 3);
        for (let i = 0; i < pixels; i++) {
            for (let c = 0; c < 3; c++) {
                // NCHW: all of red, then all of green, then all of blue.
                data[c * pixels + i] =
                    ((rgba[i * 4 + c] / 255) - mean[c]) / std[c];
            }
        }
        return { data, dims: [1, 3, size, size] };
    }

    /**
     * Phrases -> the caption Grounding DINO was trained on.
     *
     * Lowercase, separated by " . ", terminated by " .". The separators are
     * not cosmetic: they are how the model knows where one phrase ends, and
     * they become the token positions phrase attribution counts on.
     */
    function buildCaption(phrases) {
        const cleaned = phrases
            .map((p) => String(p || '').trim().toLowerCase())
            .filter(Boolean);
        if (!cleaned.length) return '';
        return `${cleaned.join(' . ')} .`;
    }

    /**
     * Map each token position to the phrase index it belongs to.
     *
     * `[CLS]` and `[SEP]` belong to nothing; a `.` advances to the next
     * phrase and belongs to nothing itself.
     */
    function phrasePositions(tokens) {
        const map = new Map();
        let phrase = 0;
        tokens.forEach((token, index) => {
            if (token === '[CLS]' || token === '[SEP]') return;
            if (token === '.') { phrase += 1; return; }
            map.set(index, phrase);
        });
        return map;
    }

    function sigmoid(x) {
        return 1 / (1 + Math.exp(-x));
    }

    class GroundingDinoSession extends base.ModelSession {
        constructor(options = {}) {
            super(Object.assign({ model: 'grounding_dino_tiny' }, options));
            const config = options.config || {};
            this.inputSize = config.input_size || DEFAULTS.inputSize;
            this.imageMean = config.image_mean || DEFAULTS.imageMean;
            this.imageStd = config.image_std || DEFAULTS.imageStd;
            this.boxThreshold = options.boxThreshold
                ?? config.box_threshold ?? DEFAULTS.boxThreshold;
            this.textThreshold = options.textThreshold
                ?? config.text_threshold ?? DEFAULTS.textThreshold;
            this.modelFile = config.model || 'model.onnx';
            this.vocabUrl = config.vocab || 'vocab.txt';
            // ORT 1.27 cannot load this graph with default optimisation: a
            // fusion pass looks for a cast node it has already folded away.
            // The zoo entry records this; the session honours it.
            this.graphOptimization = config.graph_optimization || null;
            this.canvasFactory = options.canvasFactory || null;
            this.tokenizer = options.tokenizer || null;
            this.fetchImpl = options.fetch
                || (typeof fetch !== 'undefined' ? fetch.bind(global) : null);
        }

        graphFiles() {
            return { detector: this.modelFile };
        }

        modelLabel() {
            return this.model;
        }

        fallbackHint() {
            return ' You can still draw boxes by hand.';
        }

        extraStatusMessage(kind) {
            if (kind === GDINO_ERROR.VOCAB_MISSING) {
                return `The ${this.model} vocabulary file is missing, so text `
                     + `prompts cannot be tokenized. An administrator can `
                     + `reinstall the model with:  potato download-models `
                     + `${this.model}`;
            }
            return '';
        }

        /**
         * ORT needs different session options for this graph, so the base
         * class's plain create() is not enough.
         */
        async load() {
            if (this.isReady() && this.tokenizer) return true;
            if (!this.isReady()) {
                const runtime = await this._getRuntime();
                if (!runtime) return false;
                const options = this.graphOptimization === 'disabled'
                    ? { graphOptimizationLevel: 'disabled' }
                    : undefined;
                this._setState('loading-model', { model: this.model });
                try {
                    this.graphs.detector = await runtime.InferenceSession.create(
                        this._resolveUrl(this.modelFile), options);
                } catch (err) {
                    this.graphs = {};
                    const message = (err && err.message) || String(err);
                    return !!this._fail(this._classifyLoadError(message), message);
                }
            }
            if (!this.tokenizer && !(await this._loadTokenizer())) return false;
            this._clearError();
            this._setState('ready');
            return true;
        }

        async _loadTokenizer() {
            if (!this.fetchImpl) {
                return !!this._fail(GDINO_ERROR.VOCAB_MISSING, 'no fetch available');
            }
            try {
                const response = await this.fetchImpl(this._resolveUrl(this.vocabUrl));
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const text = await response.text();
                this.tokenizer = wp.WordPieceTokenizer.fromVocabText(text);
            } catch (err) {
                return !!this._fail(GDINO_ERROR.VOCAB_MISSING,
                                    (err && err.message) || String(err));
            }
            return true;
        }

        /**
         * Find every object matching the given phrases.
         *
         * @param {CanvasImageSource} source
         * @param {number} width  ORIGINAL width in pixels
         * @param {number} height ORIGINAL height in pixels
         * @param {string[]} phrases  e.g. ['traffic cone', 'person']
         * @param {object} [options] {boxThreshold, textThreshold}
         * @returns {Promise<Array|null>} detections, or null on failure
         */
        async detect(source, width, height, phrases, options = {}) {
            const caption = buildCaption(phrases || []);
            if (!caption) return [];
            if (!(await this.load())) return null;

            let pixels;
            try {
                pixels = imageToTensor(source, this.inputSize, this.imageMean,
                                       this.imageStd, this.canvasFactory);
            } catch (err) {
                return this._fail(GDINO_ERROR.INPUT_FAILED,
                                  (err && err.message) || String(err));
            }

            const encoded = this.tokenizer.encode(caption);
            const length = encoded.ids.length;
            const feeds = {
                pixel_values: this.tensor('float32', pixels.data, pixels.dims),
                pixel_mask: this.tensor(
                    'int64',
                    BigInt64Array.from({ length: this.inputSize * this.inputSize },
                                       () => 1n),
                    [1, this.inputSize, this.inputSize]),
                input_ids: this.tensor(
                    'int64', BigInt64Array.from(encoded.ids, BigInt), [1, length]),
                token_type_ids: this.tensor(
                    'int64', BigInt64Array.from(encoded.tokenTypeIds, BigInt),
                    [1, length]),
                attention_mask: this.tensor(
                    'int64', BigInt64Array.from(encoded.attentionMask, BigInt),
                    [1, length]),
            };

            this._setState('running', { phrases });
            const output = await this.run('detector', feeds);
            if (!output) return null;

            const detections = this.postprocess(
                output, encoded.tokens, phrases, width, height, options);
            this._setState('ready', { count: detections.length });
            return detections;
        }

        /**
         * Model output -> detections in Potato's client contract.
         *
         * Separated from `detect` so it can be tested without a model: this is
         * where phrase attribution and box conversion live, and both are
         * arithmetic rather than inference.
         */
        postprocess(output, tokens, phrases, width, height, options = {}) {
            const boxThreshold = options.boxThreshold ?? this.boxThreshold;
            const textThreshold = options.textThreshold ?? this.textThreshold;

            const logits = output.logits;
            const boxes = output.pred_boxes;
            if (!logits || !boxes) return [];

            const [, queries, tokenSlots] = logits.dims;
            const positions = phrasePositions(tokens);
            const detections = [];

            for (let q = 0; q < queries; q++) {
                const offset = q * tokenSlots;
                let best = 0;
                const weights = new Map();
                for (let t = 0; t < tokenSlots; t++) {
                    const score = sigmoid(logits.data[offset + t]);
                    if (score > best) best = score;
                    if (score <= textThreshold) continue;
                    const phrase = positions.get(t);
                    if (phrase === undefined) continue;
                    weights.set(phrase, (weights.get(phrase) || 0) + score);
                }
                if (best <= boxThreshold || weights.size === 0) continue;

                let phraseIndex = -1;
                let bestWeight = -1;
                weights.forEach((weight, index) => {
                    if (weight > bestWeight) { bestWeight = weight; phraseIndex = index; }
                });
                const label = phrases[phraseIndex];
                if (!label) continue;

                const b = q * 4;
                const cx = boxes.data[b];
                const cy = boxes.data[b + 1];
                const bw = boxes.data[b + 2];
                const bh = boxes.data[b + 3];
                // Clamped because a box may extend past the frame, and a
                // negative origin becomes a negative stored coordinate that
                // every exporter then has to decide what to do with.
                const x = Math.max(0, cx - bw / 2);
                const y = Math.max(0, cy - bh / 2);
                const w = Math.min(1 - x, bw);
                const h = Math.min(1 - y, bh);
                if (w <= 0 || h <= 0) continue;

                detections.push({
                    label,
                    confidence: best,
                    // Normalized, which is what `_renderDetections` and the
                    // client contract both expect. Denormalizing here would
                    // put pixel coordinates into a field documented as [0, 1].
                    bbox: { x, y, width: w, height: h },
                });
            }

            detections.sort((a, b) => b.confidence - a.confidence);
            return detections;
        }
    }

    const api = {
        GroundingDinoSession, GDINO_ERROR, buildCaption, phrasePositions,
        imageToTensor,
    };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    if (global) {
        global.GroundingDinoSession = GroundingDinoSession;
        global.GDINO_ERROR = GDINO_ERROR;
    }
})(typeof window !== 'undefined' ? window : this);

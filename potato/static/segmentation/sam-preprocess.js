/**
 * Turning an image and a click into what the SAM ONNX graphs actually expect.
 *
 * THE CONTRACT, MEASURED RATHER THAN ASSUMED
 * ------------------------------------------
 * The MobileSAM export Potato ships declares:
 *
 *   encoder  input_image      [image_height, image_width, 3]  float, HWC
 *            image_embeddings [1, 256, 64, 64]
 *
 *   decoder  image_embeddings [1, 256, 64, 64]
 *            point_coords     [1, N, 2]          float
 *            point_labels     [1, N]             float, NOT int
 *            mask_input       [1, 1, 256, 256]   float
 *            has_mask_input   [1]                float
 *            orig_im_size     [2]                float, (height, width)
 *            -> masks [1, 1, H, W], iou_predictions, low_res_masks [1,1,256,256]
 *
 * The part that is impossible to guess, and that three plausible readings get
 * wrong, is the coordinate space:
 *
 *   1. The image is resized so its LONGEST SIDE is 1024, preserving aspect,
 *      and that resized image — not the original — is what the encoder takes.
 *      The encoder does its own normalization and padding; it does not resize.
 *   2. Click coordinates are multiplied by that SAME scale factor.
 *   3. `orig_im_size` is the ORIGINAL height and width, and the decoder undoes
 *      the resize internally, so output masks come back at original resolution.
 *
 * Verified against the real weights with three separated targets in a
 * non-square image: mask centroid landed 0.1px from the click, covering 4.5%
 * of the frame, which is exactly the target's area. The three wrong readings —
 * raw original pixels, scaling by 1024/width and 1024/height independently,
 * and feeding the encoder the unresized image — produced errors of 148px, 70px
 * and 70px respectively, each of which still returns a plausible-looking mask.
 *
 * That is why this file exists as its own module with its own tests: every
 * variant "works" in the sense of producing a mask.
 */

(function (global) {
    'use strict';

    /** SAM's fixed input resolution. The encoder's embedding is 1024/16 = 64. */
    const SAM_INPUT_SIZE = 1024;

    /** The decoder's low-res mask side, used for iterative refinement. */
    const LOW_RES_SIZE = 256;

    /** SAM emits logits; a mask is where they exceed zero. */
    const MASK_THRESHOLD = 0.0;

    /** Prompt label values. 2 and 3 are SAM's box-corner sentinels. */
    const LABEL = {
        BACKGROUND: 0,
        FOREGROUND: 1,
        BOX_TOP_LEFT: 2,
        BOX_BOTTOM_RIGHT: 3,
    };

    /**
     * The resize that everything else depends on.
     *
     * @param {number} width  original width in pixels
     * @param {number} height original height in pixels
     * @returns {{scale:number, width:number, height:number}} resized geometry
     */
    function resizeLongestSide(width, height) {
        const longest = Math.max(width, height);
        // A zero-sized image would make the scale infinite and every later
        // coordinate NaN, which surfaces as an empty mask rather than an error.
        const scale = longest > 0 ? SAM_INPUT_SIZE / longest : 1;
        return {
            scale: scale,
            width: Math.round(width * scale),
            height: Math.round(height * scale),
        };
    }

    /**
     * Draw an image into the encoder's input tensor.
     *
     * Returns HWC float32 in 0..255 — NOT normalized and NOT CHW. The export
     * normalizes internally; doing it here as well produces a near-black input
     * and a mask covering everything.
     *
     * @param {CanvasImageSource} source  an <img>, canvas, or ImageBitmap
     * @param {number} width   source width in pixels
     * @param {number} height  source height in pixels
     * @param {function} [makeCanvas]  injected for tests
     * @returns {{data:Float32Array, dims:number[], scale:number,
     *            origWidth:number, origHeight:number}}
     */
    function imageToTensor(source, width, height, makeCanvas) {
        const target = resizeLongestSide(width, height);
        const create = makeCanvas || defaultCanvasFactory;
        const canvas = create(target.width, target.height);
        const ctx = canvas.getContext('2d');

        // willReadFrequently is deliberately not set: this runs once per image,
        // and the hint costs GPU-backed drawing on some browsers.
        ctx.drawImage(source, 0, 0, target.width, target.height);
        const rgba = ctx.getImageData(0, 0, target.width, target.height).data;

        const pixels = target.width * target.height;
        const data = new Float32Array(pixels * 3);
        for (let i = 0; i < pixels; i++) {
            // Drop alpha; SAM takes RGB.
            data[i * 3] = rgba[i * 4];
            data[i * 3 + 1] = rgba[i * 4 + 1];
            data[i * 3 + 2] = rgba[i * 4 + 2];
        }

        return {
            data: data,
            // HWC, no batch dimension. Adding one throws a rank error.
            dims: [target.height, target.width, 3],
            scale: target.scale,
            origWidth: width,
            origHeight: height,
        };
    }

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
     * Build the decoder's prompt tensors from clicks in ORIGINAL image pixels.
     *
     * Callers pass what the annotator actually clicked; the scaling into SAM's
     * 1024-space happens here, once, so no call site can forget it.
     *
     * @param {object} prompts
     * @param {Array} [prompts.points] [[x, y, label], ...] in original pixels
     * @param {Array} [prompts.box]    [x, y, w, h] in original pixels
     * @param {Float32Array} [prompts.maskInput] previous low-res mask
     * @param {object} geometry {scale, origWidth, origHeight}
     * @returns {object} plain tensor descriptors {data, dims}
     */
    function buildPromptTensors(prompts, geometry) {
        const scale = geometry.scale;
        const coords = [];
        const labels = [];

        (prompts.points || []).forEach(function (point) {
            const x = point[0];
            const y = point[1];
            const label = point[2];
            coords.push(x * scale, y * scale);
            labels.push(label === LABEL.BACKGROUND
                ? LABEL.BACKGROUND : LABEL.FOREGROUND);
        });

        if (prompts.box && prompts.box.length === 4) {
            const bx = prompts.box[0];
            const by = prompts.box[1];
            const bw = prompts.box[2];
            const bh = prompts.box[3];
            // Two corners with sentinel labels, rather than a separate input.
            // This is what lets a box and refinement clicks combine in one call.
            coords.push(bx * scale, by * scale);
            labels.push(LABEL.BOX_TOP_LEFT);
            coords.push((bx + bw) * scale, (by + bh) * scale);
            labels.push(LABEL.BOX_BOTTOM_RIGHT);
        }

        if (labels.length === 0) return null;

        const previous = prompts.maskInput || null;

        return {
            point_coords: {
                data: Float32Array.from(coords),
                dims: [1, labels.length, 2],
            },
            point_labels: {
                // Float, not Int32. An integer tensor is a type error here.
                data: Float32Array.from(labels),
                dims: [1, labels.length],
            },
            mask_input: {
                data: previous || new Float32Array(LOW_RES_SIZE * LOW_RES_SIZE),
                dims: [1, 1, LOW_RES_SIZE, LOW_RES_SIZE],
            },
            has_mask_input: {
                data: Float32Array.from([previous ? 1 : 0]),
                dims: [1],
            },
            orig_im_size: {
                // HEIGHT FIRST. Passing (width, height) yields a mask that is
                // silently transposed rather than an error.
                data: Float32Array.from([geometry.origHeight, geometry.origWidth]),
                dims: [2],
            },
        };
    }

    /**
     * Threshold the decoder's mask logits into Potato RLE.
     *
     * Potato RLE is row-major counts alternating between 0-runs and 1-runs,
     * STARTING WITH A 0-RUN, with `size` as [height, width]. That leading zero
     * is not optional: a mask whose first pixel is set still begins with a
     * count of 0, and omitting it inverts the entire mask.
     *
     * @param {Float32Array} logits  masks output, H*W in original resolution
     * @param {number} width
     * @param {number} height
     * @param {number} [threshold]
     * @returns {{counts:number[], size:number[], area:number}}
     */
    function logitsToRle(logits, width, height, threshold) {
        const cut = typeof threshold === 'number' ? threshold : MASK_THRESHOLD;
        const total = width * height;
        const counts = [];
        let current = 0;
        let run = 0;
        let area = 0;

        for (let i = 0; i < total; i++) {
            const value = logits[i] > cut ? 1 : 0;
            area += value;
            if (value === current) {
                run++;
            } else {
                counts.push(run);
                current = 1 - current;
                run = 1;
            }
        }
        counts.push(run);

        return { counts: counts, size: [height, width], area: area };
    }

    /**
     * The bounding box of a thresholded mask, in original pixels.
     * Returns null for an empty mask, which is a real outcome: a click on
     * featureless background can legitimately produce nothing.
     */
    function logitsToBbox(logits, width, height, threshold) {
        const cut = typeof threshold === 'number' ? threshold : MASK_THRESHOLD;
        let minX = width, minY = height, maxX = -1, maxY = -1;
        for (let i = 0; i < width * height; i++) {
            if (logits[i] <= cut) continue;
            const y = (i / width) | 0;
            const x = i - y * width;
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
        }
        if (maxX < 0) return null;
        return {
            x: minX, y: minY,
            width: maxX - minX + 1,
            height: maxY - minY + 1,
        };
    }

    /**
     * Pick the best of a multi-mask decoder output.
     *
     * SAM can emit several candidate masks for one ambiguous click (the object,
     * the part, the whole). The export Potato ships returns one, but the
     * multi-mask variants return three or four, and taking index 0 blindly
     * gives the smallest — usually a fragment of what the annotator meant.
     *
     * @param {Float32Array} masks   flat [B, M, H, W]
     * @param {Float32Array} scores  iou_predictions, one per mask
     * @param {number} width
     * @param {number} height
     * @returns {{index:number, logits:Float32Array, score:number}}
     */
    function selectBestMask(masks, scores, width, height) {
        const stride = width * height;
        const count = Math.max(1, Math.floor(masks.length / stride));
        let best = 0;
        if (scores && scores.length >= count) {
            for (let i = 1; i < count; i++) {
                if (scores[i] > scores[best]) best = i;
            }
        }
        return {
            index: best,
            logits: masks.subarray(best * stride, (best + 1) * stride),
            score: scores && scores.length ? scores[best] : 1,
        };
    }

    const api = {
        SAM_INPUT_SIZE: SAM_INPUT_SIZE,
        LOW_RES_SIZE: LOW_RES_SIZE,
        MASK_THRESHOLD: MASK_THRESHOLD,
        LABEL: LABEL,
        resizeLongestSide: resizeLongestSide,
        imageToTensor: imageToTensor,
        buildPromptTensors: buildPromptTensors,
        logitsToRle: logitsToRle,
        logitsToBbox: logitsToBbox,
        selectBestMask: selectBestMask,
    };

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    if (global) global.SAMPreprocess = api;
})(typeof window !== 'undefined' ? window : this);

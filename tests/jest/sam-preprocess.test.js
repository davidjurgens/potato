/**
 * The SAM tensor contract, driven against the real shipped module.
 *
 * `tests/unit/test_sam_model_pipeline.py` checks these same rules against the
 * actual ONNX weights; this file checks the edge cases that are awkward to
 * reach through a 45 MB model — degenerate sizes, empty masks, RLE parity —
 * and runs in milliseconds so it can gate every commit.
 *
 * The numbers here are not arbitrary: they were measured against MobileSAM.
 * See the header of sam-preprocess.js for what each wrong reading produces.
 */

const p = require('../../potato/static/segmentation/sam-preprocess.js');

describe('resizeLongestSide', () => {
    test('a landscape image scales on its width', () => {
        const r = p.resizeLongestSide(480, 300);
        expect(r.width).toBe(1024);
        expect(r.scale).toBeCloseTo(1024 / 480);
    });

    test('a portrait image scales on its HEIGHT', () => {
        /**
         * The bug where someone "simplifies" the factor to 1024/width. On a
         * landscape image the two agree, so it survives casual testing and
         * then mislocates every mask in a portrait corpus.
         */
        const r = p.resizeLongestSide(300, 480);
        expect(r.height).toBe(1024);
        expect(r.width).toBe(640);
    });

    test('a square image is 1024 on both sides', () => {
        const r = p.resizeLongestSide(512, 512);
        expect(r.width).toBe(1024);
        expect(r.height).toBe(1024);
    });

    test('aspect ratio is preserved', () => {
        const r = p.resizeLongestSide(1600, 900);
        expect(r.width / r.height).toBeCloseTo(1600 / 900, 2);
    });

    test('a zero-sized image does not produce NaN', () => {
        /** An infinite scale makes every later coordinate NaN, which surfaces
         *  as an empty mask rather than an error. */
        const r = p.resizeLongestSide(0, 0);
        expect(Number.isFinite(r.scale)).toBe(true);
    });
});

describe('buildPromptTensors', () => {
    const geometry = Object.assign(p.resizeLongestSide(480, 300),
                                   { origWidth: 480, origHeight: 300 });

    test('it sends every input the decoder declares', () => {
        const t = p.buildPromptTensors({ points: [[100, 100, 1]] }, geometry);
        expect(Object.keys(t).sort()).toEqual([
            'has_mask_input', 'mask_input', 'orig_im_size',
            'point_coords', 'point_labels',
        ]);
    });

    test('coordinates are scaled into SAM space, not passed raw', () => {
        const t = p.buildPromptTensors({ points: [[100, 50, 1]] }, geometry);
        expect(t.point_coords.data[0]).toBeCloseTo(100 * geometry.scale);
        expect(t.point_coords.data[1]).toBeCloseTo(50 * geometry.scale);
    });

    test('orig_im_size is HEIGHT then width', () => {
        /** Transposed rather than an error — invisible on a square image. */
        const t = p.buildPromptTensors({ points: [[1, 1, 1]] }, geometry);
        expect(Array.from(t.orig_im_size.data)).toEqual([300, 480]);
    });

    test('labels are float, not int', () => {
        const t = p.buildPromptTensors({ points: [[1, 1, 1]] }, geometry);
        expect(t.point_labels.data).toBeInstanceOf(Float32Array);
    });

    test('a background point keeps label 0', () => {
        const t = p.buildPromptTensors(
            { points: [[1, 1, 1], [2, 2, 0]] }, geometry);
        expect(Array.from(t.point_labels.data)).toEqual([1, 0]);
    });

    test('a box becomes two corners with sentinel labels 2 and 3', () => {
        const t = p.buildPromptTensors({ box: [10, 20, 30, 40] }, geometry);
        expect(Array.from(t.point_labels.data)).toEqual([2, 3]);
        expect(t.point_coords.data[2]).toBeCloseTo((10 + 30) * geometry.scale);
        expect(t.point_coords.data[3]).toBeCloseTo((20 + 40) * geometry.scale);
    });

    test('points and a box combine in one call', () => {
        const t = p.buildPromptTensors(
            { points: [[5, 5, 1]], box: [10, 20, 30, 40] }, geometry);
        expect(Array.from(t.point_labels.data)).toEqual([1, 2, 3]);
        expect(t.point_coords.dims).toEqual([1, 3, 2]);
    });

    test('no prompt at all returns null rather than an empty tensor', () => {
        expect(p.buildPromptTensors({}, geometry)).toBeNull();
    });

    test('has_mask_input is 0 with no previous mask', () => {
        const t = p.buildPromptTensors({ points: [[1, 1, 1]] }, geometry);
        expect(t.has_mask_input.data[0]).toBe(0);
        expect(t.mask_input.data.length).toBe(256 * 256);
    });

    test('a previous mask turns has_mask_input on', () => {
        const previous = new Float32Array(256 * 256);
        const t = p.buildPromptTensors(
            { points: [[1, 1, 1]], maskInput: previous }, geometry);
        expect(t.has_mask_input.data[0]).toBe(1);
        expect(t.mask_input.data).toBe(previous);
    });
});

describe('logitsToRle', () => {
    test('it starts with a zero run even when pixel 0 is set', () => {
        /**
         * Potato RLE alternates starting with a 0-run. Omitting the leading
         * zero inverts the entire mask, which still renders as a plausible
         * region rather than as an obvious bug.
         */
        const logits = Float32Array.from([1, 1, -1, -1]);
        const rle = p.logitsToRle(logits, 2, 2);
        expect(rle.counts[0]).toBe(0);
        expect(rle.counts).toEqual([0, 2, 2]);
    });

    test('size is [height, width]', () => {
        const rle = p.logitsToRle(new Float32Array(6), 3, 2);
        expect(rle.size).toEqual([2, 3]);
    });

    test('an all-background mask has zero area', () => {
        const rle = p.logitsToRle(Float32Array.from([-1, -2, -3, -4]), 2, 2);
        expect(rle.area).toBe(0);
    });

    test('an all-foreground mask covers everything', () => {
        const rle = p.logitsToRle(Float32Array.from([1, 2, 3, 4]), 2, 2);
        expect(rle.area).toBe(4);
        expect(rle.counts).toEqual([0, 4]);
    });

    test('the counts sum to the pixel count', () => {
        const logits = Float32Array.from([1, -1, 1, -1, 1, -1]);
        const rle = p.logitsToRle(logits, 3, 2);
        const total = rle.counts.reduce((a, b) => a + b, 0);
        expect(total).toBe(6);
    });

    test('exactly zero is background, not foreground', () => {
        /** SAM emits logits; the mask is where they EXCEED zero. */
        const rle = p.logitsToRle(Float32Array.from([0, 0, 0, 0]), 2, 2);
        expect(rle.area).toBe(0);
    });
});

describe('logitsToBbox', () => {
    test('it finds the tight box around the mask', () => {
        // 4x3 image, one set pixel at (2, 1)
        const logits = new Float32Array(12).fill(-1);
        logits[1 * 4 + 2] = 5;
        const bbox = p.logitsToBbox(logits, 4, 3);
        expect(bbox).toEqual({ x: 2, y: 1, width: 1, height: 1 });
    });

    test('an empty mask returns null, which is a real outcome', () => {
        const bbox = p.logitsToBbox(new Float32Array(12).fill(-1), 4, 3);
        expect(bbox).toBeNull();
    });

    test('it spans a rectangular region correctly', () => {
        const logits = new Float32Array(20).fill(-1);
        for (let y = 1; y <= 2; y++) {
            for (let x = 1; x <= 3; x++) logits[y * 5 + x] = 1;
        }
        expect(p.logitsToBbox(logits, 5, 4)).toEqual(
            { x: 1, y: 1, width: 3, height: 2 });
    });
});

describe('selectBestMask', () => {
    test('with one mask it returns that mask', () => {
        const masks = Float32Array.from([1, 2, 3, 4]);
        const best = p.selectBestMask(masks, Float32Array.from([0.9]), 2, 2);
        expect(best.index).toBe(0);
        expect(Array.from(best.logits)).toEqual([1, 2, 3, 4]);
    });

    test('with several it picks the highest-scoring, not the first', () => {
        /**
         * Index 0 is usually the SMALLEST of SAM's candidates — a fragment of
         * what the annotator meant. Taking it blindly is a real bug.
         */
        const masks = Float32Array.from([1, 1, 1, 1, 9, 9, 9, 9, 5, 5, 5, 5]);
        const scores = Float32Array.from([0.3, 0.95, 0.6]);
        const best = p.selectBestMask(masks, scores, 2, 2);
        expect(best.index).toBe(1);
        expect(Array.from(best.logits)).toEqual([9, 9, 9, 9]);
        expect(best.score).toBeCloseTo(0.95);
    });

    test('missing scores fall back to the first mask', () => {
        const masks = Float32Array.from([1, 2, 3, 4]);
        const best = p.selectBestMask(masks, null, 2, 2);
        expect(best.index).toBe(0);
    });
});

describe('imageToTensor', () => {
    /** A stand-in canvas: the packing logic is what matters, not the drawing. */
    function fakeCanvas(width, height) {
        return {
            width, height,
            getContext() {
                return {
                    drawImage() {},
                    getImageData(x, y, w, h) {
                        const data = new Uint8ClampedArray(w * h * 4);
                        for (let i = 0; i < w * h; i++) {
                            data[i * 4] = 10;
                            data[i * 4 + 1] = 20;
                            data[i * 4 + 2] = 30;
                            data[i * 4 + 3] = 255;
                        }
                        return { data };
                    },
                };
            },
        };
    }

    test('it emits HWC with no batch dimension', () => {
        const t = p.imageToTensor({}, 480, 300, fakeCanvas);
        expect(t.dims).toEqual([640, 1024, 3]);
        expect(t.dims.length).toBe(3);
    });

    test('alpha is dropped and channels stay in RGB order', () => {
        const t = p.imageToTensor({}, 64, 64, fakeCanvas);
        expect(t.data[0]).toBe(10);
        expect(t.data[1]).toBe(20);
        expect(t.data[2]).toBe(30);
        expect(t.data[3]).toBe(10);   // next pixel, not alpha
    });

    test('values stay in 0..255 — the encoder normalizes itself', () => {
        /** Normalizing here as well produces a near-black input and a mask
         *  covering the whole image. */
        const t = p.imageToTensor({}, 32, 32, fakeCanvas);
        // reduce, not Math.max(...): a 1024-wide tensor is ~3M floats and
        // spreading that overflows the call stack.
        let max = 0;
        for (let i = 0; i < t.data.length; i++) {
            if (t.data[i] > max) max = t.data[i];
        }
        expect(max).toBeGreaterThan(1);
        expect(max).toBeLessThanOrEqual(255);
    });

    test('it reports the scale and the ORIGINAL size', () => {
        const t = p.imageToTensor({}, 480, 300, fakeCanvas);
        expect(t.scale).toBeCloseTo(1024 / 480);
        expect(t.origWidth).toBe(480);
        expect(t.origHeight).toBe(300);
    });

    test('the buffer length matches the declared dims', () => {
        const t = p.imageToTensor({}, 200, 100, fakeCanvas);
        expect(t.data.length).toBe(t.dims[0] * t.dims[1] * t.dims[2]);
    });
});

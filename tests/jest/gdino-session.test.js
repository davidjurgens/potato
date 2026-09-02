/**
 * Grounding DINO: caption building, phrase attribution, and box conversion.
 *
 * The model is mocked here, and the limit of that is the same as everywhere
 * else in this directory: a mock accepts any tensor. The tensor CONTRACT is
 * checked against the real weights in `tests/unit/test_gdino_js_python_bridge.py`.
 *
 * What is checked here is the arithmetic that mock cannot see — above all
 * PHRASE ATTRIBUTION, which is the part with no downstream detector. A box
 * carries no label; it carries a score per token, and the phrase is recovered
 * from token positions. Get that wrong and every box comes back with its
 * neighbour's label, looking entirely reasonable.
 */

const {
    GroundingDinoSession, buildCaption, phrasePositions, imageToTensor,
} = require('../../potato/static/segmentation/gdino-session.js');
const { WordPieceTokenizer } = require('../../potato/static/segmentation/wordpiece.js');

/** A vocabulary just big enough for the prompts used here. */
const VOCAB = [
    '[PAD]', '[UNK]', '[CLS]', '[SEP]', '.', 'cat', 'dog', 'traffic',
    'light', 'a', 'person', 'red', 'car',
];

function tokenizer() {
    const map = new Map();
    VOCAB.forEach((token, index) => map.set(token, index));
    return new WordPieceTokenizer(map);
}

/** A canvas whose pixels are whatever the test says they are. */
function fakeCanvas(rgbaFor) {
    return (width, height) => ({
        width, height,
        getContext: () => ({
            drawImage() {},
            getImageData: (x, y, w, h) => ({ data: rgbaFor(w, h) }),
        }),
    });
}

function solidRgba(r, g, b) {
    return (w, h) => {
        const data = new Uint8ClampedArray(w * h * 4);
        for (let i = 0; i < w * h; i++) {
            data[i * 4] = r; data[i * 4 + 1] = g; data[i * 4 + 2] = b;
            data[i * 4 + 3] = 255;
        }
        return data;
    };
}

/** A runtime returning fixed logits and boxes. */
function runtimeReturning(output) {
    return {
        Tensor: function (type, data, dims) {
            this.type = type; this.data = data; this.dims = dims;
        },
        InferenceSession: { create: async () => ({ run: async () => output }) },
    };
}

/**
 * Build a logits tensor where query `q` scores `score` on token `tokenIndex`.
 * Everything else is strongly negative, i.e. sigmoid ~ 0.
 */
function logitsWith(entries, queries, tokenSlots) {
    const data = new Float32Array(queries * tokenSlots).fill(-20);
    entries.forEach(({ query, token, logit }) => {
        data[query * tokenSlots + token] = logit;
    });
    return { data, dims: [1, queries, tokenSlots] };
}

function boxesWith(entries, queries) {
    const data = new Float32Array(queries * 4);
    entries.forEach(({ query, box }) => {
        data[query * 4] = box[0];
        data[query * 4 + 1] = box[1];
        data[query * 4 + 2] = box[2];
        data[query * 4 + 3] = box[3];
    });
    return { data, dims: [1, queries, 4] };
}

function session(options = {}) {
    return new GroundingDinoSession(Object.assign({
        tokenizer: tokenizer(),
        canvasFactory: fakeCanvas(solidRgba(0, 0, 0)),
    }, options));
}

describe('caption building', () => {
    test('phrases are joined with the separator the model was trained on', () => {
        expect(buildCaption(['cat', 'dog'])).toBe('cat . dog .');
    });

    test('phrases are lowercased', () => {
        expect(buildCaption(['Traffic Light'])).toBe('traffic light .');
    });

    test('blank phrases are dropped rather than producing an empty slot', () => {
        expect(buildCaption(['cat', '  ', ''])).toBe('cat .');
    });

    test('no phrases means no caption', () => {
        expect(buildCaption([])).toBe('');
    });
});

describe('phrase attribution', () => {
    test('each token maps to the phrase it sits in', () => {
        const tokens = ['[CLS]', 'cat', '.', 'traffic', 'light', '.', '[SEP]'];
        const map = phrasePositions(tokens);
        expect(map.get(1)).toBe(0);          // cat
        expect(map.get(3)).toBe(1);          // traffic
        expect(map.get(4)).toBe(1);          // light — same phrase
    });

    test('separators and specials belong to no phrase', () => {
        const tokens = ['[CLS]', 'cat', '.', 'dog', '.', '[SEP]'];
        const map = phrasePositions(tokens);
        expect(map.has(0)).toBe(false);
        expect(map.has(2)).toBe(false);
        expect(map.has(5)).toBe(false);
    });

    test('a multi-word phrase does not leak into the next one', () => {
        const tokens = ['[CLS]', 'traffic', 'light', '.', 'cat', '.', '[SEP]'];
        const map = phrasePositions(tokens);
        expect(map.get(4)).toBe(1);
    });
});

describe('image preprocessing', () => {
    test('it produces NCHW, not HWC', () => {
        const tensor = imageToTensor({}, 4, [0, 0, 0], [1, 1, 1],
                                     fakeCanvas(solidRgba(255, 0, 0)));
        expect(tensor.dims).toEqual([1, 3, 4, 4]);
        // All of red first: a HWC layout would interleave.
        expect(tensor.data[0]).toBeCloseTo(1.0);
        expect(tensor.data[1]).toBeCloseTo(1.0);
        expect(tensor.data[16]).toBeCloseTo(0.0);   // green plane
        expect(tensor.data[32]).toBeCloseTo(0.0);   // blue plane
    });

    test('it scales to [0,1] before normalising', () => {
        const mean = [0.485, 0.456, 0.406];
        const std = [0.229, 0.224, 0.225];
        const tensor = imageToTensor({}, 2, mean, std,
                                     fakeCanvas(solidRgba(128, 128, 128)));
        const expected = ((128 / 255) - mean[0]) / std[0];
        expect(tensor.data[0]).toBeCloseTo(expected, 5);
    });
});

describe('postprocessing', () => {
    const tokens = ['[CLS]', 'cat', '.', 'dog', '.', '[SEP]'];
    const phrases = ['cat', 'dog'];

    function postprocess(entries, boxes, options) {
        const s = session();
        return s.postprocess(
            { logits: logitsWith(entries, 3, 6), pred_boxes: boxesWith(boxes, 3) },
            tokens, phrases, 200, 100, options);
    }

    test('a query scoring on the first phrase is labelled with it', () => {
        const out = postprocess(
            [{ query: 0, token: 1, logit: 3 }],
            [{ query: 0, box: [0.5, 0.5, 0.2, 0.4] }]);
        expect(out).toHaveLength(1);
        expect(out[0].label).toBe('cat');
    });

    test('a query scoring on the second phrase is labelled with THAT one', () => {
        const out = postprocess(
            [{ query: 1, token: 3, logit: 3 }],
            [{ query: 1, box: [0.5, 0.5, 0.2, 0.4] }]);
        expect(out).toHaveLength(1);
        expect(out[0].label).toBe('dog');
    });

    test('centre-format boxes become top-left corner plus size', () => {
        const out = postprocess(
            [{ query: 0, token: 1, logit: 3 }],
            [{ query: 0, box: [0.5, 0.5, 0.2, 0.4] }]);
        expect(out[0].bbox.x).toBeCloseTo(0.4);
        expect(out[0].bbox.y).toBeCloseTo(0.3);
        expect(out[0].bbox.width).toBeCloseTo(0.2);
        expect(out[0].bbox.height).toBeCloseTo(0.4);
    });

    test('boxes stay normalised rather than becoming pixels', () => {
        const out = postprocess(
            [{ query: 0, token: 1, logit: 3 }],
            [{ query: 0, box: [0.5, 0.5, 0.2, 0.4] }]);
        expect(out[0].bbox.width).toBeLessThanOrEqual(1);
    });

    test('a box running off the edge is clamped into the frame', () => {
        const out = postprocess(
            [{ query: 0, token: 1, logit: 3 }],
            [{ query: 0, box: [0.05, 0.5, 0.4, 0.4] }]);
        expect(out[0].bbox.x).toBe(0);
        expect(out[0].bbox.x + out[0].bbox.width).toBeLessThanOrEqual(1);
    });

    test('low-scoring queries are dropped', () => {
        const out = postprocess(
            [{ query: 0, token: 1, logit: -3 }],
            [{ query: 0, box: [0.5, 0.5, 0.2, 0.4] }]);
        expect(out).toHaveLength(0);
    });

    test('the box threshold is honoured', () => {
        const entries = [{ query: 0, token: 1, logit: 0.5 }];  // sigmoid ~0.62
        const boxes = [{ query: 0, box: [0.5, 0.5, 0.2, 0.2] }];
        expect(postprocess(entries, boxes, { boxThreshold: 0.5 })).toHaveLength(1);
        expect(postprocess(entries, boxes, { boxThreshold: 0.8 })).toHaveLength(0);
    });

    test('a query scoring only on a separator is dropped, not mislabelled', () => {
        // Token 2 is the '.' between phrases. Attributing it to a phrase would
        // hand a real box an arbitrary label.
        const out = postprocess(
            [{ query: 0, token: 2, logit: 3 }],
            [{ query: 0, box: [0.5, 0.5, 0.2, 0.2] }]);
        expect(out).toHaveLength(0);
    });

    test('results come back strongest first', () => {
        const out = postprocess(
            [{ query: 0, token: 1, logit: 1 }, { query: 1, token: 3, logit: 4 }],
            [{ query: 0, box: [0.3, 0.3, 0.1, 0.1] },
             { query: 1, box: [0.7, 0.7, 0.1, 0.1] }]);
        expect(out.map((d) => d.label)).toEqual(['dog', 'cat']);
    });
});

describe('detection end to end against a mocked runtime', () => {
    const output = {
        logits: logitsWith([{ query: 0, token: 1, logit: 4 }], 2, 6),
        pred_boxes: boxesWith([{ query: 0, box: [0.5, 0.5, 0.25, 0.25] }], 2),
    };

    test('an empty prompt asks the model nothing', async () => {
        const runtime = runtimeReturning(output);
        const s = session({ runtime });
        expect(await s.detect({}, 200, 100, [])).toEqual([]);
    });

    test('a prompt returns detections in the client contract shape', async () => {
        const s = session({ runtime: runtimeReturning(output) });
        const out = await s.detect({}, 200, 100, ['cat', 'dog']);
        expect(out).toHaveLength(1);
        expect(out[0]).toMatchObject({
            label: 'cat',
            bbox: { x: expect.any(Number), y: expect.any(Number) },
        });
        expect(out[0].confidence).toBeGreaterThan(0.9);
    });

    test('a missing model reports the model, not the runtime', async () => {
        const runtime = {
            Tensor: function () {},
            InferenceSession: {
                create: async () => { throw new Error('404 Not Found'); },
            },
        };
        const s = session({ runtime });
        expect(await s.detect({}, 10, 10, ['cat'])).toBe(null);
        expect(s.statusMessage()).toContain('download-models grounding_dino_tiny');
    });

    test('a missing vocabulary says so specifically', async () => {
        const s = new GroundingDinoSession({
            runtime: runtimeReturning(output),
            canvasFactory: fakeCanvas(solidRgba(0, 0, 0)),
            fetch: async () => ({ ok: false, status: 404 }),
        });
        expect(await s.detect({}, 10, 10, ['cat'])).toBe(null);
        expect(s.statusMessage()).toContain('vocabulary');
    });
});

/**
 * SAMSession: model loading, embedding cache, and failure classification.
 *
 * The ONNX runtime is mocked here, and the limits of that are worth stating:
 * a mock accepts any tensor shape, which is how an earlier version of this
 * file shipped emitting two of the decoder's six required inputs while its
 * whole suite passed. The tensor CONTRACT is therefore checked against the
 * real weights in `tests/unit/test_sam_model_pipeline.py` and across the
 * language boundary in `test_sam_js_python_bridge.py`.
 *
 * What is checked here is the orchestration those cannot see: what gets
 * re-encoded, what gets evicted, and which error the annotator is shown.
 */

const {
    SAMSession, SAM_STATE, SAM_ERROR,
} = require('../../potato/static/segmentation/sam-session.js');

/** A runtime whose sessions succeed. */
function workingRuntime(runResult) {
    const created = [];
    const result = runResult || {
        masks: { data: new Float32Array([1, -1, -1, 1]), dims: [1, 1, 2, 2] },
        iou_predictions: { data: new Float32Array([0.9]) },
        low_res_masks: { data: new Float32Array(256 * 256), dims: [1, 1, 256, 256] },
        image_embeddings: { data: new Float32Array(4) },
    };
    return {
        created,
        Tensor: function (type, data, dims) { this.type = type; this.data = data; this.dims = dims; },
        InferenceSession: {
            create: async (url) => {
                created.push(url);
                return { run: async () => result };
            },
        },
    };
}

/** A runtime whose model files 404 — i.e. nobody ran download-models. */
function missingModelRuntime() {
    return {
        Tensor: function () {},
        InferenceSession: {
            create: async () => { throw new Error('404 Not Found'); },
        },
    };
}

/** A runtime that cannot start its wasm backend. */
function brokenRuntime() {
    return {
        Tensor: function () {},
        InferenceSession: {
            create: async () => {
                throw new Error('no available backend found. ERR: [wasm] '
                    + 'TypeError: Failed to fetch dynamically imported module: '
                    + 'ort-wasm-simd-threaded.mjs');
            },
        },
    };
}

/** A stand-in for an <img>; only the geometry matters to the session. */
const SOURCE = {};

/** jsdom has no 2d context, so the canvas is injected. */
function headlessCanvas(width, height) {
    return {
        width, height,
        getContext: () => ({
            drawImage() {},
            getImageData: (x, y, w, h) => ({
                data: new Uint8ClampedArray(w * h * 4),
            }),
        }),
    };
}

function fakeCanvasSession(runtime, options) {
    return new SAMSession(Object.assign(
        { runtime, canvasFactory: headlessCanvas }, options || {}));
}

describe('loading', () => {
    test('it creates an encoder and a decoder from the model directory', async () => {
        const runtime = workingRuntime();
        const session = new SAMSession({ runtime, model: 'mobile_sam' });
        expect(await session.load()).toBe(true);
        expect(runtime.created).toEqual([
            '/static/models/mobile_sam/encoder.onnx',
            '/static/models/mobile_sam/decoder.onnx',
        ]);
    });

    test('it honours a configured model base url', async () => {
        const runtime = workingRuntime();
        const session = new SAMSession({ runtime, modelBaseUrl: '/models' });
        await session.load();
        expect(runtime.created[0]).toBe('/models/mobile_sam/encoder.onnx');
    });

    test('a trailing slash does not double up', async () => {
        const runtime = workingRuntime();
        const session = new SAMSession({ runtime, modelBaseUrl: '/models/' });
        await session.load();
        expect(runtime.created[0]).toBe('/models/mobile_sam/encoder.onnx');
    });

    test('loading twice does the work once', async () => {
        const runtime = workingRuntime();
        const session = new SAMSession({ runtime });
        await session.load();
        await session.load();
        expect(runtime.created).toHaveLength(2);
    });

    test('with no runtime at all it reports the runtime, not the model', async () => {
        const session = new SAMSession({});
        expect(await session.load()).toBe(false);
        expect(session.errorKind).toBe(SAM_ERROR.RUNTIME_UNAVAILABLE);
    });
});

describe('failure classification', () => {
    /**
     * The distinction is the whole value of the error: the two have different
     * fixes, and a wrong guess sends an administrator to run the wrong command.
     */
    test('a 404 on the weights means the MODEL is missing', async () => {
        const session = new SAMSession({ runtime: missingModelRuntime() });
        await session.load();
        expect(session.errorKind).toBe(SAM_ERROR.MODEL_MISSING);
        expect(session.statusMessage()).toContain('download-models mobile_sam');
    });

    test('a wasm backend failure means the RUNTIME is missing', async () => {
        /**
         * Found in a real browser: a missing ORT glue module reported "the
         * mobile_sam model is not installed", which is false and unfixable by
         * the command it suggested.
         */
        const session = new SAMSession({ runtime: brokenRuntime() });
        await session.load();
        expect(session.errorKind).toBe(SAM_ERROR.RUNTIME_UNAVAILABLE);
        expect(session.statusMessage()).toContain('download-models onnxruntime');
        expect(session.statusMessage()).not.toContain('mobile_sam model is not');
    });

    test('every error message names a next action', () => {
        const session = new SAMSession({});
        for (const kind of Object.values(SAM_ERROR)) {
            session.errorKind = kind;
            const message = session.statusMessage();
            expect(message.length).toBeGreaterThan(20);
            expect(/install|brush|try|administrator/i.test(message)).toBe(true);
        }
    });

    test('with no error the message is empty', () => {
        expect(new SAMSession({}).statusMessage()).toBe('');
    });
});

describe('embedding cache', () => {
    async function encodeInto(session, key) {
        return session.encodeImage(key, SOURCE, 64, 64);
    }

    test('re-encoding the same image reuses the embedding', async () => {
        const runtime = workingRuntime();
        const session = fakeCanvasSession(runtime);
        await encodeInto(session, 'a.jpg');
        const runsAfterFirst = runtime.created.length;
        await encodeInto(session, 'a.jpg');
        expect(runtime.created.length).toBe(runsAfterFirst);
    });

    test('a different image is encoded again', async () => {
        const session = fakeCanvasSession(workingRuntime());
        await encodeInto(session, 'a.jpg');
        await encodeInto(session, 'b.jpg');
        expect(session._embeddings.size).toBe(2);
    });

    test('the cache is bounded so a long session cannot grow unbounded', async () => {
        const session = fakeCanvasSession(workingRuntime(), { embeddingLimit: 2 });
        for (const key of ['a', 'b', 'c', 'd']) await encodeInto(session, key);
        expect(session._embeddings.size).toBe(2);
    });

    test('eviction is least-recently-USED, not least-recently-added', async () => {
        /**
         * Without re-inserting on a cache HIT, an annotator flipping between
         * two images evicts the one they keep returning to and re-encodes it
         * every single time.
         */
        const session = fakeCanvasSession(workingRuntime(), { embeddingLimit: 2 });
        await encodeInto(session, 'a');
        await encodeInto(session, 'b');
        await encodeInto(session, 'a');   // touch a
        await encodeInto(session, 'c');   // should evict b, not a
        expect(Array.from(session._embeddings.keys()).sort()).toEqual(['a', 'c']);
    });

    test('reset drops everything', async () => {
        const session = fakeCanvasSession(workingRuntime());
        await encodeInto(session, 'a');
        session.reset();
        expect(session._embeddings.size).toBe(0);
        expect(session._currentKey).toBeNull();
    });
});

describe('segmenting', () => {
    async function readySession() {
        const session = fakeCanvasSession(workingRuntime());
        await session.encodeImage('a.jpg', SOURCE, 64, 64);
        return session;
    }

    test('it returns Potato RLE, not raw logits', async () => {
        const session = await readySession();
        const result = await session.segment({ points: [[10, 10, 1]] });
        expect(result.rle).toHaveProperty('counts');
        expect(result.rle).toHaveProperty('size');
    });

    test('an all-background mask reports area 0 rather than an annotation', async () => {
        const runtime = workingRuntime({
            masks: { data: new Float32Array([-1, -1, -1, -1]), dims: [1, 1, 2, 2] },
            iou_predictions: { data: new Float32Array([0.2]) },
            image_embeddings: { data: new Float32Array(4) },
        });
        const session = fakeCanvasSession(runtime);
        await session.encodeImage('a.jpg', SOURCE, 2, 2);
        const result = await session.segment({ points: [[1, 1, 1]] });
        expect(result.area).toBe(0);
        expect(result.rle).toBeNull();
    });

    test('segmenting before encoding fails loudly rather than returning empty', async () => {
        const session = new SAMSession({ runtime: workingRuntime() });
        await session.load();
        const result = await session.segment({ points: [[1, 1, 1]] });
        expect(result).toBeNull();
        expect(session.errorKind).toBe(SAM_ERROR.ENCODE_FAILED);
    });

    test('a prompt with nothing in it is an error, not an empty mask', async () => {
        const session = await readySession();
        const result = await session.segment({});
        expect(result).toBeNull();
        expect(session.errorKind).toBe(SAM_ERROR.DECODE_FAILED);
    });

    test('the low-res mask is kept so the next click refines', async () => {
        const session = await readySession();
        await session.segment({ points: [[10, 10, 1]] });
        expect(session._lastLowResMask).not.toBeNull();
    });

    test('clearRefinement forgets the chain but keeps the embedding', async () => {
        const session = await readySession();
        await session.segment({ points: [[10, 10, 1]] });
        session.clearRefinement();
        expect(session._lastLowResMask).toBeNull();
        expect(session._embeddings.size).toBe(1);
    });
});

describe('state reporting', () => {
    test('it announces each stage so the UI can show progress', async () => {
        const states = [];
        const session = fakeCanvasSession(workingRuntime(), {
            onStateChange: (s) => states.push(s),
        });
        await session.encodeImage('a.jpg', SOURCE, 64, 64);
        expect(states).toContain(SAM_STATE.LOADING_RUNTIME);
        expect(states).toContain(SAM_STATE.LOADING_MODEL);
        expect(states).toContain(SAM_STATE.ENCODING);
        expect(states[states.length - 1]).toBe(SAM_STATE.READY);
    });

    test('a cache hit is reported as cached so no spinner is shown', async () => {
        const details = [];
        const session = fakeCanvasSession(workingRuntime(), {
            onStateChange: (s, d) => details.push(d),
        });
        await session.encodeImage('a.jpg', SOURCE, 64, 64);
        details.length = 0;
        await session.encodeImage('a.jpg', SOURCE, 64, 64);
        expect(details.some(d => d && d.cached === true)).toBe(true);
    });
});

describe('frame-to-frame carry (NOT SAM 2 memory propagation)', () => {
    /**
     * No published SAM 2 ONNX export contains the memory_encoder or
     * memory_attention modules, so real propagation is not available in the
     * browser. What this does is re-prompt the next frame with the previous
     * frame's mask and centroid. These tests pin that it is honest about which
     * inputs it sends, because the difference matters to anyone reading the
     * results.
     */
    async function ready() {
        const session = fakeCanvasSession(workingRuntime());
        await session.encodeImage('frame0', SOURCE, 64, 64);
        return session;
    }

    test('it needs a seed with a bounding box', async () => {
        const session = await ready();
        expect(await session.propagateFrom('frame1', SOURCE, 64, 64, null)).toBeNull();
        expect(await session.propagateFrom('frame1', SOURCE, 64, 64, {})).toBeNull();
    });

    test('it anchors on the previous box centroid', async () => {
        const session = await ready();
        let sent = null;
        const original = session.segment.bind(session);
        session.segment = async (p) => { sent = p; return original(p); };
        await session.propagateFrom('frame1', SOURCE, 64, 64,
            { bbox: { x: 10, y: 20, width: 40, height: 60 } });
        expect(sent.points).toEqual([[30, 50, 1]]);
    });

    test('it constrains the search with the previous box', async () => {
        const session = await ready();
        let sent = null;
        const original = session.segment.bind(session);
        session.segment = async (p) => { sent = p; return original(p); };
        await session.propagateFrom('frame1', SOURCE, 64, 64,
            { bbox: { x: 10, y: 20, width: 40, height: 60 } });
        expect(sent.box).toEqual([10, 20, 40, 60]);
    });

    test('it encodes the NEXT frame, not reuse the previous embedding', async () => {
        const session = await ready();
        await session.propagateFrom('frame1', SOURCE, 64, 64,
            { bbox: { x: 1, y: 1, width: 5, height: 5 } });
        expect(session._currentKey).toBe('frame1');
        expect(session._embeddings.has('frame0')).toBe(true);
    });
});

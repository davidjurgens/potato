/**
 * Where each shape came from, and whether it survives a save.
 *
 * An accepted detection and a hand-drawn box are byte-identical once stored.
 * That is the whole problem: a study that pre-labels with a detector cannot
 * report its own acceptance rate from its own data, because nothing in the
 * data says which boxes the model proposed. `annotation_telemetry` recovers
 * the *rate* from a timing heuristic (a shape added within a window of an
 * accept click), but not *which* box — and the rate is the thing a reviewer
 * will ask to see per-image.
 *
 * These drive the real serializer and the real restore path rather than
 * asserting on hand-built blobs, because the failure to catch is provenance
 * that is written once and then quietly dropped on the first navigation.
 */

const fs = require('fs');
const path = require('path');

global.fabric = {
    Point: function (x, y) { this.x = x; this.y = y; },
    Rect: function (o) { Object.assign(this, o); },
    util: {
        transformPoint: (p, m) => ({
            x: m[0] * p.x + m[2] * p.y + m[4],
            y: m[1] * p.x + m[3] * p.y + m[5],
        }),
    },
};

require('../../potato/static/mask-buffer.js');  // sets window.MaskBuffer

const SRC = path.join(__dirname, '..', '..', 'potato', 'static', 'image-annotation.js');
eval(fs.readFileSync(SRC, 'utf8'));
// Asked of the file rather than restated here. A test that keeps its own copy
// of this list would agree with itself while the file drifted. The eval runs
// in this module's scope, so the source's own `module.exports` assignment puts
// the list within reach.
const PROVENANCE_KEYS = module.exports.PROVENANCE_KEYS;

const IMG_W = 640;
const IMG_H = 480;

/** A canvas that holds objects and records the handlers bound to it. */
function fakeCanvas() {
    const objects = [];
    const handlers = {};
    return {
        objects,
        handlers,
        getObjects: () => objects,
        add: (o) => objects.push(o),
        remove: (o) => {
            const i = objects.indexOf(o);
            if (i >= 0) objects.splice(i, 1);
        },
        renderAll: () => {},
        on: (name, fn) => { handlers[name] = fn; },
    };
}

function makeManager(overrides = {}) {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.image = { width: IMG_W, height: IMG_H, scaleX: 1, scaleY: 1, left: 0, top: 0 };
    m.config = { schemaName: 'regions' };
    m.canvas = fakeCanvas();
    m.masks = {};
    m.maskImgWidth = IMG_W;
    m.maskImgHeight = IMG_H;
    m.currentLabel = 'cell';
    m.currentColor = '#0f0';
    m.currentTool = 'bbox';
    m._saveState = () => {};
    m._updateAnnotationData = () => {};
    m._telemetry = () => {};
    m._announce = () => {};
    m._showMaskCanvas = () => {};
    m._renderAllMasks = () => {};
    return Object.assign(m, overrides);
}

/** A fabric-ish rect the serializer can measure. */
function rect(annotationData, box = { left: 10, top: 20, width: 100, height: 50 }) {
    return {
        annotationData,
        type: 'rect',
        left: box.left, top: box.top,
        width: box.width, height: box.height,
        scaleX: 1, scaleY: 1, angle: 0,
    };
}

function serialize(manager) {
    return JSON.parse(manager._serializeAnnotations());
}

describe('a shape says where it came from', () => {
    test('a hand-drawn box is marked as a person\'s', () => {
        const m = makeManager();
        m.drawingObject = Object.assign(
            rect(null), { width: 100, height: 50 });
        m.canvas.add(m.drawingObject);
        m._finishBbox();

        const [ann] = serialize(m);
        expect(ann.source).toBe('human');
    });

    test('an accepted detection keeps the model and its score', () => {
        const m = makeManager();
        m.canvas.add(rect({
            type: 'bbox', label: 'cell', color: '#0f0',
            source: 'ai', ai_model: 'yolov8n', confidence: 0.82,
        }));

        const [ann] = serialize(m);
        expect(ann.source).toBe('ai');
        expect(ann.ai_model).toBe('yolov8n');
        expect(ann.confidence).toBeCloseTo(0.82, 5);
    });

    test('a confidence of exactly zero is a real score, not a missing one', () => {
        const m = makeManager();
        m.canvas.add(rect({
            type: 'bbox', label: 'cell', color: '#0f0',
            source: 'ai', confidence: 0,
        }));
        expect(serialize(m)[0].confidence).toBe(0);
    });

    test('a shape stored before provenance existed stays unknown', () => {
        // The tempting default is 'human', and it would be wrong for every
        // dataset that was seeded from a detector before this field existed.
        const m = makeManager();
        m.canvas.add(rect({ type: 'bbox', label: 'cell', color: '#0f0' }));

        const ann = serialize(m)[0];
        expect(ann).not.toHaveProperty('source');
    });
});

describe('provenance survives navigating away and back', () => {
    test('a restored shape still names its model', () => {
        const saved = JSON.stringify([{
            type: 'bbox', label: 'cell', color: '#0f0',
            coordinates: { x: 0.1, y: 0.2, width: 0.3, height: 0.25 },
            source: 'ai', ai_model: 'yolov8n', confidence: 0.7,
        }]);

        const m = makeManager();
        m._deserializeAnnotations(saved);
        const [ann] = serialize(m);

        expect(ann.source).toBe('ai');
        expect(ann.ai_model).toBe('yolov8n');
        expect(ann.confidence).toBeCloseTo(0.7, 5);
    });

    test('a restored mask still names its model', () => {
        const m = makeManager();
        m._restoreMaskFromEntry({
            type: 'mask', label: 'cell', color: '#0f0',
            // Two runs: 5 background, 5 foreground, rest background.
            rle: { counts: [5, 5, IMG_W * IMG_H - 10], size: [IMG_H, IMG_W] },
            source: 'ai', ai_model: 'sam2',
        });

        const [entry] = serialize(m);
        expect(entry.type).toBe('mask');
        expect(entry.source).toBe('ai');
        expect(entry.ai_model).toBe('sam2');
    });

    test('a hand-painted mask is marked as a person\'s', () => {
        const m = makeManager({ currentTool: 'brush' });
        m._activeMaskKey = () => 'cell';
        const mask = m._ensureMask();
        mask.buffer.set(3, 3, 1);

        expect(serialize(m)[0].source).toBe('human');
    });
});

describe('a model\'s shape that the annotator moved is not the model\'s any more', () => {
    function bindHandlers(m) {
        m._setupMaskEventListeners = () => {};
        m._setupEventListeners();
        return m.canvas.handlers['object:modified'];
    }

    test('editing an accepted detection marks it edited', () => {
        const m = makeManager();
        const target = rect({
            type: 'bbox', label: 'cell', color: '#0f0',
            source: 'ai', ai_model: 'yolov8n',
        });
        m.canvas.add(target);

        bindHandlers(m)({ target });

        const [ann] = serialize(m);
        expect(ann.source).toBe('ai');
        expect(ann.edited).toBe(true);
    });

    test('editing your own shape does not mark it', () => {
        const m = makeManager();
        const target = rect({
            type: 'bbox', label: 'cell', color: '#0f0', source: 'human',
        });
        m.canvas.add(target);

        bindHandlers(m)({ target });

        expect(serialize(m)[0]).not.toHaveProperty('edited');
    });
});

describe('carry-over from the previous image', () => {
    /**
     * Twenty nudged boxes and twenty freshly drawn ones are the same twenty
     * boxes once stored. `carried_over` is the only thing that separates them,
     * and it was declared before anything produced it.
     */
    function withFetch(objects, run) {
        const original = global.fetch;
        global.fetch = () => Promise.resolve({
            ok: true,
            json: () => Promise.resolve({objects, instance_id: 'img_000'}),
        });
        return run().finally(() => { global.fetch = original; });
    }

    test('a copied shape keeps its origin and gains the carry-over', () => {
        const m = makeManager();
        return withFetch([{
            type: 'bbox', label: 'cell', color: '#0f0',
            coordinates: {x: 0.1, y: 0.1, width: 0.2, height: 0.2},
            source: 'human',
        }], async () => {
            const result = await m.copyFromPrevious();
            expect(result.added).toBe(1);

            const [ann] = serialize(m);
            // A person's box copied forward is still a person's box.
            expect(ann.source).toBe('human');
            expect(ann.carried_over).toBe(true);
        });
    });

    test("a model's box copied forward is still the model's", () => {
        const m = makeManager();
        return withFetch([{
            type: 'bbox', label: 'cell', color: '#0f0',
            coordinates: {x: 0.1, y: 0.1, width: 0.2, height: 0.2},
            source: 'ai', ai_model: 'yolov8n',
        }], async () => {
            await m.copyFromPrevious();
            const [ann] = serialize(m);
            expect(ann.source).toBe('ai');
            expect(ann.ai_model).toBe('yolov8n');
            expect(ann.carried_over).toBe(true);
        });
    });
});

describe('every declared provenance key has something that produces it', () => {
    /**
     * `ai_model` and `carried_over` were declared in PROVENANCE_KEYS, carried
     * by the serializer and written by the COCO exporter before anything
     * produced a value for either. A guard whose subject cannot occur passes
     * for the wrong reason and no mutation finds it, because the guard does
     * fail when its subject is broken.
     *
     * So this asks the opposite question: of the keys declared, which does the
     * running code actually emit? Anything unaccounted for is a plan rather
     * than a feature.
     */
    const PRODUCED_ELSEWHERE = {
        // Written server-side by the importer, and covered by
        // tests/unit/test_shape_provenance.py::TestImportCliWiring.
        import_format: 'potato/importers/cli.py',
    };

    test('nothing in the list is unproduced', () => {
        const produced = new Set();

        // Drawn here.
        const drawn = makeManager();
        drawn.drawingObject = Object.assign(rect(null), {width: 100, height: 50});
        drawn.canvas.add(drawn.drawingObject);
        drawn._finishBbox();
        serialize(drawn).forEach(a => Object.keys(a).forEach(k => produced.add(k)));

        // Accepted from a model, then edited.
        const accepted = makeManager();
        accepted.addAnnotation({
            type: 'bbox', label: 'cell', color: '#0f0',
            coordinates: {x: 0.1, y: 0.1, width: 0.2, height: 0.2},
            source: 'ai', ai_model: 'yolov8n', confidence: 0.5,
        });
        accepted._setupMaskEventListeners = () => {};
        accepted._setupEventListeners();
        accepted.canvas.handlers['object:modified'](
            {target: accepted.canvas.getObjects()[0]});
        serialize(accepted).forEach(a => Object.keys(a).forEach(k => produced.add(k)));

        // Carried over from the previous image.
        const copied = makeManager();
        copied.addAnnotation({
            type: 'bbox', label: 'cell', color: '#0f0',
            coordinates: {x: 0.1, y: 0.1, width: 0.2, height: 0.2},
            source: 'import', carried_over: true, import_format: 'coco',
        });
        serialize(copied).forEach(a => Object.keys(a).forEach(k => produced.add(k)));

        const unproduced = PROVENANCE_KEYS.filter(
            key => !produced.has(key) && !(key in PRODUCED_ELSEWHERE));

        expect(unproduced).toEqual([]);
    });

    test('the elsewhere list names only keys this file really cannot reach', () => {
        // An entry here is an exemption, and an exemption with no subject is a
        // standing permission. If a key becomes reachable from the client, it
        // must leave this list rather than sit in it unchecked.
        const exempt = Object.keys(PRODUCED_ELSEWHERE);
        // An empty list makes the loop below never run. A test that cannot
        // fail is the same defect it is checking for.
        expect(exempt.length).toBeGreaterThan(0);
        expect(PROVENANCE_KEYS.length).toBeGreaterThanOrEqual(6);
        exempt.forEach(key => {
            expect(PROVENANCE_KEYS).toContain(key);
        });
    });
});

describe('addAnnotation, the entry point for everything not drawn here', () => {
    test('carries the provenance the caller declares', () => {
        const m = makeManager();
        const added = m.addAnnotation({
            type: 'bbox', label: 'cell', color: '#0f0',
            coordinates: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 },
            source: 'ai', ai_model: 'yolov8n', confidence: 0.55,
        });

        expect(added).toBe(true);
        const [ann] = serialize(m);
        expect(ann.source).toBe('ai');
        expect(ann.ai_model).toBe('yolov8n');
    });

    test('says so once when a caller declares no origin at all', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
        try {
            const m = makeManager();
            for (let i = 0; i < 3; i++) {
                m.addAnnotation({
                    type: 'bbox', label: 'cell', color: '#0f0',
                    coordinates: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 },
                });
            }
            const complaints = warn.mock.calls.filter(
                (c) => String(c[0]).includes('no `source`'));
            expect(complaints).toHaveLength(1);
        } finally {
            warn.mockRestore();
        }
    });
});

/**
 * Per-object attributes survive a save.
 *
 * Importers put `attributes` on a shape -- CVAT's <attribute> elements, KITTI's
 * truncation and occlusion, MOT's track id and visibility -- and the CVAT,
 * KITTI, MOT and Darwin exporters read them back. The browser used to rebuild
 * every restored shape from type/label/color plus provenance alone, so the
 * first save of an imported item wrote the shape back without them and the
 * export lost them with no warning.
 *
 * Same harness as shape-provenance.test.js: the real serializer and the real
 * restore path, not hand-built blobs.
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

const IMG_W = 640;
const IMG_H = 480;

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
    m.currentLabel = 'car';
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

function serialize(manager) {
    return JSON.parse(manager._serializeAnnotations());
}

/** What the CVAT importer writes for a box with two attributes. */
const IMPORTED_BOX = {
    type: 'bbox', label: 'car', color: '#0f0',
    coordinates: { x: 0.1, y: 0.2, width: 0.3, height: 0.25 },
    source: 'import', import_format: 'cvat',
    attributes: { occluded: 'partial', truncated: '0.4' },
};

describe('imported attributes survive navigating away and back', () => {
    test('a restored box writes its attributes back', () => {
        const m = makeManager();
        m._deserializeAnnotations(JSON.stringify([IMPORTED_BOX]));

        const [ann] = serialize(m);
        expect(ann.attributes).toEqual({ occluded: 'partial', truncated: '0.4' });
    });

    test('two round trips in a row keep them', () => {
        const first = makeManager();
        first._deserializeAnnotations(JSON.stringify([IMPORTED_BOX]));
        const second = makeManager();
        second._deserializeAnnotations(first._serializeAnnotations());

        expect(serialize(second)[0].attributes)
            .toEqual({ occluded: 'partial', truncated: '0.4' });
    });

    test('a restored mask writes its attributes back', () => {
        const m = makeManager();
        m._restoreMaskFromEntry({
            type: 'mask', label: 'car', color: '#0f0',
            rle: { counts: [5, 5, IMG_W * IMG_H - 10], size: [IMG_H, IMG_W] },
            attributes: { occluded: 'heavy' },
        });

        const [entry] = serialize(m);
        expect(entry.type).toBe('mask');
        expect(entry.attributes).toEqual({ occluded: 'heavy' });
    });

    test('moving an imported box keeps its attributes', () => {
        const m = makeManager();
        m._deserializeAnnotations(JSON.stringify([IMPORTED_BOX]));
        m._setupMaskEventListeners = () => {};
        m._setupEventListeners();
        const target = m.canvas.objects[0];
        target.left += 15;
        m.canvas.handlers['object:modified']({ target });

        const [ann] = serialize(m);
        expect(ann.edited).toBe(true);
        expect(ann.attributes).toEqual({ occluded: 'partial', truncated: '0.4' });
    });
});

describe('what is not written', () => {
    test('a shape with no attributes gets no attributes key', () => {
        const m = makeManager();
        const plain = Object.assign({}, IMPORTED_BOX);
        delete plain.attributes;
        m._deserializeAnnotations(JSON.stringify([plain]));

        expect(serialize(m)[0]).not.toHaveProperty('attributes');
    });

    test('an empty attributes object is not written', () => {
        const m = makeManager();
        m._deserializeAnnotations(JSON.stringify([
            Object.assign({}, IMPORTED_BOX, { attributes: {} })]));

        expect(serialize(m)[0]).not.toHaveProperty('attributes');
    });

    test('the stored copy does not alias the restored one', () => {
        const source = { attributes: { occluded: 'none' } };
        const target = carryAttributes({}, source);
        source.attributes.occluded = 'heavy';
        expect(target.attributes.occluded).toBe('none');
    });
});

describe('other paths that rebuild a shape', () => {
    test('undo after an edit restores the attributes', () => {
        const m = makeManager();
        m.history = [];
        m.historyIndex = -1;
        m.maxHistory = 50;
        m._saveState = ImageAnnotationManager.prototype._saveState;
        m._emitStateDelta = () => {};
        m._deserializeAnnotations(JSON.stringify([IMPORTED_BOX]));
        m._saveState();                       // baseline: the imported box
        m.canvas.objects[0].left += 20;
        m._saveState();                       // after a move

        m.undo();

        const [ann] = serialize(m);
        expect(ann.attributes).toEqual({ occluded: 'partial', truncated: '0.4' });
    });

    test('a box copied from the previous image keeps its attributes', () => {
        const m = makeManager();
        const original = global.fetch;
        global.fetch = () => Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ objects: [IMPORTED_BOX], instance_id: 'img_000' }),
        });
        return m.copyFromPrevious().then((result) => {
            expect(result.added).toBe(1);
            const [ann] = serialize(m);
            expect(ann.carried_over).toBe(true);
            expect(ann.attributes).toEqual({ occluded: 'partial', truncated: '0.4' });
        }).finally(() => { global.fetch = original; });
    });
});

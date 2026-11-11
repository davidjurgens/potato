/**
 * Every shape keeps an id through save and reload (live sessions, Phase 4).
 *
 * In a live collaborative session the server merges teammates' drawings
 * shape by shape, by id. A shape whose id changed on every reload would read
 * as deleted and redrawn, and two members moving it at once would leave two
 * copies. Same harness as shape-provenance.test.js: the real serializer and
 * the real restore path.
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

describe('a shape keeps its id', () => {
    test('a new shape is given one, and keeps it on the next save', () => {
        const m = makeManager();
        m.canvas.add(rect({ type: 'bbox', label: 'cell', color: '#0f0' }));
        const first = serialize(m)[0].id;
        expect(first).toEqual(expect.any(String));
        expect(serialize(m)[0].id).toBe(first);
    });

    test('two shapes, two ids; two pages never mint the same', () => {
        const a = makeManager();
        const b = makeManager();
        a.canvas.add(rect({ type: 'bbox', label: 'cell', color: '#0f0' }));
        a.canvas.add(rect({ type: 'bbox', label: 'cell', color: '#0f0' }));
        b.canvas.add(rect({ type: 'bbox', label: 'cell', color: '#0f0' }));
        const ids = [...serialize(a), ...serialize(b)].map((s) => s.id);
        expect(new Set(ids).size).toBe(3);
    });

    test('a restored shape keeps the id it was stored with', () => {
        const saved = JSON.stringify([{
            id: 'ana_1', type: 'bbox', label: 'cell', color: '#0f0',
            coordinates: { x: 0.1, y: 0.2, width: 0.3, height: 0.25 },
        }]);
        const m = makeManager();
        m._deserializeAnnotations(saved);
        expect(serialize(m)[0].id).toBe('ana_1');
    });

    test('a shape stored without an id gets the same id on every page', () => {
        const saved = JSON.stringify([
            { type: 'bbox', label: 'cell', color: '#0f0',
              coordinates: { x: 0.1, y: 0.2, width: 0.3, height: 0.25 } },
            { type: 'bbox', label: 'cell', color: '#0f0',
              coordinates: { x: 0.1, y: 0.2, width: 0.3, height: 0.25 } },
        ]);
        const ana = makeManager();
        const ben = makeManager();
        ana._deserializeAnnotations(saved);
        ben._deserializeAnnotations(saved);
        const ids = serialize(ana).map((s) => s.id);
        expect(ids[0]).toMatch(/^legacy_/);
        expect(ids[1]).toBe(`${ids[0]}_2`);        // the same box stored twice stays two
        expect(serialize(ben).map((s) => s.id)).toEqual(ids);
    });

    test("a mask's id is its store key, so one label's mask is one element", () => {
        const m = makeManager();
        m._restoreMaskFromEntry({
            type: 'mask', label: 'cell', color: '#0f0',
            rle: { counts: [5, 5, IMG_W * IMG_H - 10], size: [IMG_H, IMG_W] },
        });
        expect(serialize(m)[0].id).toBe('mask:cell');
    });
});

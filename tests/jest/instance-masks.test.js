/**
 * Instance-keyed segmentation masks.
 *
 * The default (`semantic`) mode keys masks by bare label, so every stroke of a
 * class merges into one region. That is correct for semantic segmentation and
 * is what Potato has always done — but it means two adjacent cats are one blob,
 * which makes interactive segmentation impossible: SAM returns one mask per
 * OBJECT, and a label-keyed store merges them the moment they arrive.
 *
 * `mask_mode: instance` keys them `label#N`. These tests pin both modes, and
 * pin the two ways a stale instance counter corrupts data: across a label
 * change, and across an instance switch.
 */

const fs = require('fs');
const path = require('path');

require('../../potato/static/mask-buffer.js');  // sets window.MaskBuffer

const SRC = path.join(__dirname, '..', '..', 'potato', 'static', 'image-annotation.js');
eval(fs.readFileSync(SRC, 'utf8'));

const W = 4;
const H = 3;

function makeManager(maskMode) {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.masks = {};
    m.maskImgWidth = W;
    m.maskImgHeight = H;
    m.config = maskMode ? { maskMode } : {};
    m.currentLabel = 'cat';
    m.currentColor = '#ff0000';
    m.activeInstance = null;
    m.history = [];
    m.historyIndex = -1;
    m.maxHistory = 50;
    m.inputId = 'input-seg';
    m._renderAllMasks = jest.fn();
    m._showMaskCanvas = jest.fn();
    m._updateMaskData = jest.fn();
    m._announce = jest.fn();

    const objs = [];
    m.image = { width: W, height: H, scaleX: 1, scaleY: 1, left: 0, top: 0 };
    m.canvas = {
        getObjects: () => objs,
        remove: (o) => { const i = objs.indexOf(o); if (i >= 0) objs.splice(i, 1); },
        add: (o) => objs.push(o),
        renderAll: () => {},
    };
    return m;
}

describe('semantic mode (the default)', () => {
    test('keys masks by bare label', () => {
        const m = makeManager();
        expect(m._activeMaskKey()).toBe('cat');
    });

    test('every stroke of a class targets the same store entry', () => {
        const m = makeManager();
        const first = m._activeMaskKey();
        m.activeInstance = 7;  // must be ignored outside instance mode
        expect(m._activeMaskKey()).toBe(first);
    });

    test('newMaskInstance is a no-op', () => {
        const m = makeManager();
        expect(m.newMaskInstance()).toBe(false);
        expect(m._activeMaskKey()).toBe('cat');
    });
});

describe('instance mode', () => {
    test('keys masks label#N', () => {
        const m = makeManager('instance');
        expect(m._activeMaskKey()).toBe('cat#0');
    });

    test('the same object keeps its key across repeated strokes', () => {
        const m = makeManager('instance');
        const key = m._activeMaskKey();
        expect(m._activeMaskKey()).toBe(key);
    });

    test('a new instance gets the next index', () => {
        const m = makeManager('instance');
        m.masks['cat#0'] = { label: 'cat', instance: 0, data: null };
        m.newMaskInstance();
        expect(m._activeMaskKey()).toBe('cat#1');
    });

    test('indices are per label, not global', () => {
        const m = makeManager('instance');
        m.masks['cat#0'] = { label: 'cat', instance: 0, data: null };
        m.masks['cat#1'] = { label: 'cat', instance: 1, data: null };
        m.currentLabel = 'dog';
        m.activeInstance = null;
        expect(m._activeMaskKey()).toBe('dog#0');
    });

    test('the next index accounts for imported COCO instances', () => {
        // Imported masks are already keyed this way, so a new stroke must not
        // reuse an index an imported object already owns.
        const m = makeManager('instance');
        m.masks['cat#0'] = { label: 'cat', instance: 0, data: null };
        m.masks['cat#5'] = { label: 'cat', instance: 5, data: null };
        expect(m._nextInstanceIndex('cat')).toBe(6);
    });

    test('a label-keyed legacy mask counts as instance 0', () => {
        const m = makeManager('instance');
        m.masks['cat'] = { label: 'cat', data: null };  // no instance field
        expect(m._nextInstanceIndex('cat')).toBe(1);
    });
});

describe('stale instance counters corrupt data', () => {
    test('changing label resets the instance', () => {
        // Otherwise instance 3 of "cat" silently becomes instance 3 of "dog",
        // merging two different objects.
        const m = makeManager('instance');
        m.activeInstance = 3;
        m.canvas.isDrawingMode = false;
        m.setLabel('dog', '#00ff00');
        expect(m.activeInstance).toBeNull();
        expect(m._activeMaskKey()).toBe('dog#0');
    });

    test('re-selecting the SAME label does not reset the instance', () => {
        // Clicking the armed label again is not a new object.
        const m = makeManager('instance');
        m.activeInstance = 3;
        m.canvas.isDrawingMode = false;
        m.setLabel('cat', '#ff0000');
        expect(m.activeInstance).toBe(3);
    });

    test('switching instance resets the counter', () => {
        // clearAnnotations runs on every instance switch. A stale index would
        // make the next image's objects start numbering at 4.
        const m = makeManager('instance');
        m.masks['cat#0'] = { label: 'cat', instance: 0, data: null };
        m.masks['cat#3'] = { label: 'cat', instance: 3, data: null };
        m.activeInstance = 3;

        m.clearAnnotations();

        expect(m.activeInstance).toBeNull();
        expect(Object.keys(m.masks)).toHaveLength(0);
        expect(m._activeMaskKey()).toBe('cat#0');
    });

    test('switching instance clears half-finished shapes too', () => {
        const m = makeManager('instance');
        m.polygonPoints = [{ x: 1, y: 1 }];
        m.keypointPoints = [{ x: 1, y: 1, v: 2 }];
        m.cuboidFront = [{ x: 0, y: 0 }];

        m.clearAnnotations();

        expect(m.polygonPoints).toHaveLength(0);
        expect(m.keypointPoints).toHaveLength(0);
        expect(m.cuboidFront).toBeNull();
    });
});

describe('serialization', () => {
    /** A MaskBuffer with exactly the listed flat pixel indices painted. */
    function maskBuffer(pixels) {
        const buffer = new MaskBuffer(W, H);
        pixels.forEach(i => buffer.set(i));
        return buffer;
    }

    test('instance masks serialize with their instance index', () => {
        const m = makeManager('instance');
        m.masks['cat#0'] = { label: 'cat', color: '#f00', instance: 0,
            iscrowd: 0, buffer: maskBuffer([0, 1]) };
        m.masks['cat#1'] = { label: 'cat', color: '#f00', instance: 1,
            iscrowd: 0, buffer: maskBuffer([5, 6]) };

        const out = JSON.parse(m._serializeAnnotations());

        expect(out).toHaveLength(2);
        // Both carry the real LABEL, not the store key — an exporter reading
        // "cat#1" as a class name would invent a category.
        out.forEach(o => expect(o.label).toBe('cat'));
        expect(out.map(o => o.instance).sort()).toEqual([0, 1]);
        // iscrowd=0 says "one object"; a merged label region is a crowd.
        out.forEach(o => expect(o.iscrowd).toBe(0));
    });

    test('semantic masks still serialize under the bare label', () => {
        const m = makeManager();
        m.masks['cat'] = { label: 'cat', color: '#f00', buffer: maskBuffer([0, 1]) };
        const out = JSON.parse(m._serializeAnnotations());
        expect(out).toHaveLength(1);
        expect(out[0].label).toBe('cat');
        expect(out[0].instance).toBeUndefined();
    });

    test('two instances do not merge into one region', () => {
        const m = makeManager('instance');
        m.masks['cat#0'] = { label: 'cat', color: '#f00', instance: 0,
            buffer: maskBuffer([0]) };
        m.masks['cat#1'] = { label: 'cat', color: '#f00', instance: 1,
            buffer: maskBuffer([11]) };

        const out = JSON.parse(m._serializeAnnotations());
        expect(out).toHaveLength(2);
        expect(out[0].rle).not.toEqual(out[1].rle);
    });
});

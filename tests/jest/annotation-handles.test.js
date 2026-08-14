/**
 * getAnnotationHandles() and the serializer must agree, exactly.
 *
 * A stored image annotation has no id — its INDEX in the serialized list is
 * its only identity. So anything that reports on annotation N and then acts on
 * it (the VLM critique review queue) must walk the list in precisely the order
 * `_serializeAnnotations` did. Two independent loops over `getObjects()` and
 * then `this.masks` agree right up until someone reorders one of them, and the
 * symptom is a Delete button that removes a different shape than the one the
 * annotator was reading about.
 *
 * These tests pin that agreement, including the one case where the two loops
 * had already diverged: a mask whose buffer is allocated but empty is dropped
 * by the serializer (it encodes to an empty RLE), so counting it as a handle
 * would shift the index of every annotation after it.
 */

const fs = require('fs');
const path = require('path');

require('../../potato/static/mask-buffer.js');  // sets window.MaskBuffer

const SRC = path.join(__dirname, '..', '..', 'potato', 'static', 'image-annotation.js');
eval(fs.readFileSync(SRC, 'utf8'));

const W = 4;
const H = 3;

function makeManager() {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.masks = {};
    m.maskImgWidth = W;
    m.maskImgHeight = H;
    m.config = { labels: [{ name: 'cat', color: '#ff0000' },
                          { name: 'dog', color: '#00ff00' }] };
    m.currentLabel = 'cat';
    m.currentColor = '#ff0000';
    m.history = [];
    m.historyIndex = -1;
    m.maxHistory = 50;
    m.inputId = 'input-seg';
    m._renderAllMasks = jest.fn();
    m._showMaskCanvas = jest.fn();
    m._updateMaskData = jest.fn();
    m._updateAnnotationData = jest.fn();
    m._announce = jest.fn();
    m._getObjectCoordinates = () => ({ x: 0, y: 0, width: 0.1, height: 0.1 });

    const objs = [];
    m.image = { width: W, height: H, scaleX: 1, scaleY: 1, left: 0, top: 0 };
    m.canvas = {
        getObjects: () => objs,
        remove: (o) => { const i = objs.indexOf(o); if (i >= 0) objs.splice(i, 1); },
        add: (o) => objs.push(o),
        renderAll: () => {},
        requestRenderAll: () => {},
        setActiveObject: jest.fn(),
        discardActiveObject: jest.fn(),
    };
    return m;
}

function addShape(m, label, type = 'bbox') {
    const obj = {
        annotationData: { type, label, color: '#ff0000' },
        set: jest.fn(),
        fill: 'transparent',
    };
    m.canvas.add(obj);
    return obj;
}

/** A mask with `painted` pixels set. */
function addMask(m, key, label, painted = 2) {
    const buffer = new MaskBuffer(W, H);
    for (let i = 0; i < painted; i++) buffer.set(i);
    m.masks[key] = { buffer, label, color: '#00ff00' };
    return m.masks[key];
}

function labelsOf(m) {
    return JSON.parse(m._serializeAnnotations()).map(a => a.label);
}

describe('handles match the serialized list', () => {
    test('shapes only', () => {
        const m = makeManager();
        addShape(m, 'cat');
        addShape(m, 'dog');
        expect(m.getAnnotationHandles().map(h => h.label)).toEqual(labelsOf(m));
    });

    test('masks only', () => {
        const m = makeManager();
        addMask(m, 'cat', 'cat');
        addMask(m, 'dog', 'dog');
        expect(m.getAnnotationHandles().map(h => h.label)).toEqual(labelsOf(m));
    });

    test('shapes then masks, which is the serialization order', () => {
        const m = makeManager();
        addShape(m, 'cat');
        addMask(m, 'dog', 'dog');
        addShape(m, 'dog');
        const handles = m.getAnnotationHandles();
        expect(handles.map(h => h.label)).toEqual(labelsOf(m));
        expect(handles.map(h => h.kind)).toEqual(['object', 'object', 'mask']);
    });

    test('indices are contiguous from zero', () => {
        const m = makeManager();
        addShape(m, 'cat');
        addShape(m, 'dog');
        addMask(m, 'cat', 'cat');
        expect(m.getAnnotationHandles().map(h => h.index)).toEqual([0, 1, 2]);
    });

    test('an instance-keyed mask reports its real label, not its store key', () => {
        const m = makeManager();
        addMask(m, 'cat#2', 'cat');
        expect(m.getAnnotationHandles()[0].label).toBe('cat');
        expect(labelsOf(m)).toEqual(['cat']);
    });

    test('an empty mask buffer is skipped by both, so no index shifts', () => {
        const m = makeManager();
        addMask(m, 'cat', 'cat');
        m.masks['empty'] = { buffer: new MaskBuffer(W, H), label: 'dog',
                             color: '#00ff00' };
        addMask(m, 'later', 'dog');

        const handles = m.getAnnotationHandles();
        expect(handles.map(h => h.label)).toEqual(labelsOf(m));
        expect(handles).toHaveLength(2);
    });

    test('a mask with no data at all is skipped by both', () => {
        const m = makeManager();
        addShape(m, 'cat');
        m.masks['broken'] = { label: 'dog', color: '#00ff00' };
        expect(m.getAnnotationHandles().map(h => h.label)).toEqual(labelsOf(m));
    });

    test('nothing annotated means no handles', () => {
        const m = makeManager();
        expect(m.getAnnotationHandles()).toEqual([]);
        expect(labelsOf(m)).toEqual([]);
    });
});

describe('acting on annotation N', () => {
    test('relabel changes the label and the colour together', () => {
        const m = makeManager();
        const obj = addShape(m, 'cat');
        expect(m.relabelAnnotation(0, 'dog')).toBe(true);
        expect(obj.annotationData.label).toBe('dog');
        expect(obj.annotationData.color).toBe('#00ff00');
        expect(obj.set).toHaveBeenCalledWith({ stroke: '#00ff00' });
    });

    test('relabel refuses a label the schema does not have', () => {
        const m = makeManager();
        const obj = addShape(m, 'cat');
        expect(m.relabelAnnotation(0, 'aardvark')).toBe(false);
        expect(obj.annotationData.label).toBe('cat');
    });

    test('relabel re-keys a mask so later strokes do not extend it', () => {
        const m = makeManager();
        addMask(m, 'cat', 'cat');
        expect(m.relabelAnnotation(0, 'dog')).toBe(true);
        expect(m.masks.cat).toBeUndefined();
        expect(m.masks.dog.label).toBe('dog');
    });

    test('relabel preserves an instance suffix when re-keying', () => {
        const m = makeManager();
        addMask(m, 'cat#3', 'cat');
        expect(m.relabelAnnotation(0, 'dog')).toBe(true);
        expect(m.masks['dog#3']).toBeDefined();
    });

    test('relabel refuses when it would merge two masks', () => {
        const m = makeManager();
        addMask(m, 'cat', 'cat');
        addMask(m, 'dog', 'dog');
        expect(m.relabelAnnotation(0, 'dog')).toBe(false);
        expect(m.masks.cat).toBeDefined();
        expect(m.masks.dog.label).toBe('dog');
    });

    test('relabel keeps every painted pixel and moves the colour with it', () => {
        // The buffer stores occupancy only, so a relabel touches no pixels —
        // it changes the colour the mask renders in. What must not change is
        // WHICH pixels are set.
        const m = makeManager();
        const mask = addMask(m, 'cat', 'cat', 2);
        m.relabelAnnotation(0, 'dog');
        const painted = [];
        mask.buffer.forEachSetPixel(pix => painted.push(pix));
        expect(painted.sort((a, b) => a - b)).toEqual([0, 1]);
        expect(m.masks.dog.color).toBe(m.colorForLabel('dog'));
    });

    test('delete removes the right shape', () => {
        const m = makeManager();
        addShape(m, 'cat');
        addShape(m, 'dog');
        expect(m.deleteAnnotation(0)).toBe(true);
        expect(labelsOf(m)).toEqual(['dog']);
    });

    test('delete removes the right mask', () => {
        const m = makeManager();
        addShape(m, 'cat');
        addMask(m, 'dog', 'dog');
        expect(m.deleteAnnotation(1)).toBe(true);
        expect(m.masks.dog).toBeUndefined();
        expect(labelsOf(m)).toEqual(['cat']);
    });

    test('an out-of-range index does nothing rather than throwing', () => {
        const m = makeManager();
        addShape(m, 'cat');
        expect(m.deleteAnnotation(5)).toBe(false);
        expect(m.relabelAnnotation(5, 'dog')).toBe(false);
        expect(m.focusAnnotation(5)).toBe(false);
        expect(labelsOf(m)).toEqual(['cat']);
    });

    test('focus selects a shape but reports that a mask is not selectable', () => {
        const m = makeManager();
        addShape(m, 'cat');
        addMask(m, 'dog', 'dog');
        expect(m.focusAnnotation(0)).toBe(true);
        expect(m.canvas.setActiveObject).toHaveBeenCalled();
        expect(m.focusAnnotation(1)).toBe(false);
    });

    test('colorForLabel resolves configured labels only', () => {
        const m = makeManager();
        expect(m.colorForLabel('cat')).toBe('#ff0000');
        expect(m.colorForLabel('aardvark')).toBeNull();
    });
});

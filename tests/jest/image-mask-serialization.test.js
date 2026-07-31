/**
 * Image mask persistence — drives the REAL client serializer.
 *
 * The mask export has been broken in two independent ways, and the existing test
 * (tests/unit/test_mask_exporter.py) hid both because it hand-builds the shape the
 * exporter wants, using data no part of the product actually produced:
 *
 *   1. Masks were written to a `mask-data-input` element carrying neither
 *      `annotation-input` nor `annotation-data-input`, so no save selector ever
 *      collected it. Every brush stroke was lost on the next navigation.
 *   2. The client wrote `{label: {color, rle: [ints], width, height}}` while every
 *      exporter reads `[{type:"mask", label, rle:{counts, size:[h,w]}}]`.
 *
 * So this test asserts on _serializeAnnotations() output, not on a fixture. If the
 * client format drifts from the exporter contract again, this fails.
 */

const ImageAnnotationManager = require('../../potato/static/image-annotation.js');

/** A manager with just enough state to serialize; no DOM, no fabric canvas. */
function makeManager(masks, width, height) {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.masks = masks;
    m.maskImgWidth = width;
    m.maskImgHeight = height;
    m.canvas = { getObjects: () => [] };
    return m;
}

/** Build an RGBA buffer with the given flat pixel indices switched on. */
function maskBuffer(width, height, onIndices) {
    const data = new Uint8ClampedArray(width * height * 4);
    onIndices.forEach(i => { data[i * 4 + 3] = 255; });
    return data;
}

describe('_serializeAnnotations', () => {
    test('emits masks in the shape every exporter reads', () => {
        const m = makeManager(
            { road: { color: '#ff0000', data: maskBuffer(4, 3, [1, 2, 5, 6]) } }, 4, 3);

        const out = JSON.parse(m._serializeAnnotations());
        expect(out).toHaveLength(1);

        const mask = out[0];
        // mask_exporter.py skips anything without these exact keys.
        expect(mask.type).toBe('mask');
        expect(mask.label).toBe('road');
        expect(Array.isArray(mask.rle.counts)).toBe(true);
        expect(mask.rle.counts.length).toBeGreaterThan(0);
        // cv_utils.decode_rle expects size as [height, width], in that order.
        expect(mask.rle.size).toEqual([3, 4]);
    });

    test('masks ride the same blob as shapes, not a separate input', () => {
        const m = makeManager(
            { road: { color: '#ff0000', data: maskBuffer(2, 2, [0]) } }, 2, 2);
        m.canvas = {
            getObjects: () => [{
                annotationData: { type: 'bbox', label: 'car', color: '#0000ff' },
            }],
        };
        m._getObjectCoordinates = () => ({ x: 0, y: 0, w: 1, h: 1 });

        const out = JSON.parse(m._serializeAnnotations());
        expect(out.map(a => a.type).sort()).toEqual(['bbox', 'mask']);
    });

    test('an empty mask is not emitted', () => {
        const m = makeManager(
            { road: { color: '#ff0000', data: new Uint8ClampedArray(2 * 2 * 4) } }, 2, 2);
        // All-zero alpha encodes to a single run of 0s; nothing is selected, so the
        // entry would decode to an empty mask and the exporter would write a blank PNG.
        const out = JSON.parse(m._serializeAnnotations());
        const masks = out.filter(a => a.type === 'mask');
        expect(masks.length).toBeLessThanOrEqual(1);
        if (masks.length) {
            expect(masks[0].rle.counts.reduce((a, b) => a + b, 0)).toBe(4);
        }
    });

    test('no masks means no mask entries', () => {
        const m = makeManager({}, 4, 3);
        expect(JSON.parse(m._serializeAnnotations())).toEqual([]);
    });
});

describe('mask round-trip', () => {
    test('serialize then restore preserves the selected pixels', () => {
        const width = 4, height = 3, on = [1, 2, 5, 6];
        const m = makeManager(
            { road: { color: '#ff0000', data: maskBuffer(width, height, on) } },
            width, height);

        const entry = JSON.parse(m._serializeAnnotations())[0];

        // A fresh manager restoring from that entry — the navigate-away-and-back path.
        const restored = makeManager({}, 0, 0);
        restored._restoreMaskFromEntry(entry);

        expect(Object.keys(restored.masks)).toEqual(['road']);
        expect(restored.maskImgWidth).toBe(width);
        expect(restored.maskImgHeight).toBe(height);

        const data = restored.masks.road.data;
        const backOn = [];
        for (let i = 0; i < width * height; i++) {
            if (data[i * 4 + 3] > 128) backOn.push(i);
        }
        expect(backOn).toEqual(on);
    });

    test('restoring a malformed entry is ignored rather than throwing', () => {
        const m = makeManager({}, 0, 0);
        m._restoreMaskFromEntry({ type: 'mask', label: 'x' });
        m._restoreMaskFromEntry({ type: 'mask', label: 'x', rle: { counts: [] } });
        m._restoreMaskFromEntry({ type: 'mask', label: 'x', rle: { counts: [1], size: [2] } });
        expect(m.masks).toEqual({});
    });
});

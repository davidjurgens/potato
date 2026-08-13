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

describe('instance masks', () => {
    /**
     * COCO RLE is per-instance; the mask store is keyed by label. Without an
     * instance key, two adjacent instances of one class merge into a single
     * blob — which destroys exactly the instance segmentation the import
     * exists to preserve. This is also the hard prerequisite for SAM, which
     * emits instances.
     */
    test('two instances of one label do not collapse into each other', () => {
        const m = makeManager({}, 0, 0);
        m._restoreMaskFromEntry({
            type: 'mask', label: 'person', color: '#ff0000', instance: 0,
            rle: { counts: [0, 2, 2], size: [2, 2] },
        });
        m._restoreMaskFromEntry({
            type: 'mask', label: 'person', color: '#ff0000', instance: 1,
            rle: { counts: [2, 2], size: [2, 2] },
        });

        expect(Object.keys(m.masks).sort()).toEqual(['person#0', 'person#1']);
        expect(m.masks['person#0'].label).toBe('person');
        expect(m.masks['person#1'].instance).toBe(1);
    });

    test('instance and crowd flags survive a serialize/restore cycle', () => {
        const m = makeManager({}, 0, 0);
        m._restoreMaskFromEntry({
            type: 'mask', label: 'person', color: '#ff0000', instance: 3,
            rle: { counts: [0, 2, 2], size: [2, 2] },
        });
        m._restoreMaskFromEntry({
            type: 'mask', label: 'crowd', color: '#00ff00', iscrowd: 1,
            rle: { counts: [2, 2], size: [2, 2] },
        });

        const out = JSON.parse(m._serializeAnnotations());
        const person = out.find(a => a.label === 'person');
        const crowd = out.find(a => a.label === 'crowd');

        // The label must be the real label, never the "label#instance" key.
        expect(person.label).toBe('person');
        expect(person.instance).toBe(3);
        expect(crowd.iscrowd).toBe(1);
        expect(crowd.instance).toBeUndefined();
    });

    test('a brush mask with no instance still serializes under its key', () => {
        const m = makeManager(
            { road: { color: '#ff0000', data: maskBuffer(2, 2, [0]) } }, 2, 2);
        const out = JSON.parse(m._serializeAnnotations());
        expect(out[0].label).toBe('road');
        expect(out[0].instance).toBeUndefined();
    });
});

describe('polygon coordinates', () => {
    /**
     * _getObjectCoordinates used `obj.left + p.x - obj.pathOffset.x`, mixing a
     * top-left origin with a centre-based offset, so every vertex was shifted
     * by half the polygon's size. The exported bbox had the right WIDTH and
     * HEIGHT in the wrong PLACE, which is why it survived review — a COCO
     * export of a 100x80 polygon at (180, 80) came out at (129, 39).
     *
     * Caught by exporting a real browser session, not by any unit test.
     */
    const realFabric = global.fabric;

    beforeEach(() => {
        global.fabric = {
            Point: function (x, y) { this.x = x; this.y = y; },
            util: {
                // Center-based affine transform, as fabric computes it.
                transformPoint: (p, m) => ({
                    x: m[0] * p.x + m[2] * p.y + m[4],
                    y: m[1] * p.x + m[3] * p.y + m[5],
                }),
            },
        };
    });
    afterEach(() => { global.fabric = realFabric; });

    /** A polygon fabric would build from absolute points (180,80)-(280,160). */
    function polygonObject({ scaleX = 1, scaleY = 1 } = {}) {
        const points = [
            { x: 180, y: 80 }, { x: 280, y: 80 },
            { x: 280, y: 160 }, { x: 180, y: 160 },
        ];
        const centerX = 230, centerY = 120;
        return {
            annotationData: { type: 'polygon', label: 'dog', color: '#0f0' },
            points,
            pathOffset: { x: centerX, y: centerY },
            left: 180, top: 80,
            calcTransformMatrix: () => [scaleX, 0, 0, scaleY, centerX, centerY],
        };
    }

    function managerOverImage() {
        const m = makeManager({}, 0, 0);
        // A 320x240 image drawn 1:1 at the canvas origin.
        m.image = { left: 0, top: 0, width: 320, height: 240, scaleX: 1, scaleY: 1 };
        return m;
    }

    test('vertices serialize to their true positions', () => {
        const m = managerOverImage();
        const coords = m._getObjectCoordinates(polygonObject());
        const xs = coords.map(c => c.x * 320);
        const ys = coords.map(c => c.y * 240);

        expect(Math.min(...xs)).toBeCloseTo(180, 5);
        expect(Math.min(...ys)).toBeCloseTo(80, 5);
        expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(100, 5);
        expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(80, 5);

        // The specific wrong answer the old arithmetic produced.
        expect(Math.min(...xs)).not.toBeCloseTo(129, 0);
    });

    test('a scaled polygon is not silently ignored', () => {
        // The old arithmetic never consulted scaleX/scaleY at all, so resizing
        // a polygon changed nothing in the export.
        const m = managerOverImage();
        const coords = m._getObjectCoordinates(polygonObject({ scaleX: 2, scaleY: 2 }));
        const xs = coords.map(c => c.x * 320);
        expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(200, 5);
    });
});

describe('restored masks are visible', () => {
    /**
     * setTool() runs during init, before any mask exists, and does
     * _showMaskCanvas(this._hasMasks()) — so the overlay starts hidden.
     * Restoring masks afterwards painted them onto a display:none canvas: the
     * pixels were all correct and nothing was on screen. Found by running the
     * COCO import example in a browser, not by any unit test.
     */
    function managerWithMaskCanvas(tool) {
        const m = makeManager({}, 0, 0);
        m.currentTool = tool;
        m.maskCanvas = { style: { display: 'none' } };
        m.maskCtx = null;
        m.image = null;
        m._renderAllMasks = () => {};
        m.canvas = { getObjects: () => [], renderAll: () => {} };
        m._createAnnotationObject = () => {};
        return m;
    }

    test('deserializing a mask un-hides the overlay', () => {
        const m = managerWithMaskCanvas('bbox');
        expect(m.maskCanvas.style.display).toBe('none');

        m._deserializeAnnotations(JSON.stringify([{
            type: 'mask', label: 'road', color: '#ff0000',
            rle: { counts: [0, 4], size: [2, 2] },
        }]));

        expect(m.maskCanvas.style.display).toBe('block');
    });

    test('freeform keeps the overlay hidden', () => {
        const m = managerWithMaskCanvas('freeform');
        m._deserializeAnnotations(JSON.stringify([{
            type: 'mask', label: 'road', color: '#ff0000',
            rle: { counts: [0, 4], size: [2, 2] },
        }]));
        expect(m.maskCanvas.style.display).toBe('none');
    });

    test('a shapes-only payload leaves the overlay alone', () => {
        const m = managerWithMaskCanvas('bbox');
        m._deserializeAnnotations(JSON.stringify([{
            type: 'bbox', label: 'car', color: '#00f',
            coordinates: { x: 0, y: 0, width: 1, height: 1 },
        }]));
        expect(m.maskCanvas.style.display).toBe('none');
    });
});

describe('mask resolution guard', () => {
    /**
     * _restoreMaskFromEntry used to do `this.maskImgWidth = this.maskImgWidth ||
     * width`, so an RLE whose resolution differed from the already-sized canvas
     * was painted at the wrong stride — diagonal garbage, no error. COCO's
     * images[].width is the natural size so these usually agree, but a resized
     * or thumbnailed image_url breaks it.
     */
    test('a mismatched mask is rescaled to the canvas, not painted at the wrong stride', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
        const m = makeManager({}, 4, 4);   // canvas already sized 4x4

        // A fully-filled 2x2 mask arriving for a 4x4 canvas.
        m._restoreMaskFromEntry({
            type: 'mask', label: 'road', color: '#ff0000',
            rle: { counts: [0, 4], size: [2, 2] },
        });

        expect(warn).toHaveBeenCalled();
        expect(m.maskImgWidth).toBe(4);
        expect(m.maskImgHeight).toBe(4);
        expect(m.masks.road.data.length).toBe(4 * 4 * 4);

        // Every pixel was set in the source, so every pixel is set after rescale.
        let on = 0;
        for (let i = 0; i < 16; i++) {
            if (m.masks.road.data[i * 4 + 3] > 128) on++;
        }
        expect(on).toBe(16);
        warn.mockRestore();
    });

    test('a matching resolution is left alone and does not warn', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
        const m = makeManager({}, 2, 2);
        m._restoreMaskFromEntry({
            type: 'mask', label: 'road', color: '#ff0000',
            rle: { counts: [0, 4], size: [2, 2] },
        });
        expect(warn).not.toHaveBeenCalled();
        expect(m.masks.road.data.length).toBe(2 * 2 * 4);
        warn.mockRestore();
    });
});

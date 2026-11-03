/**
 * The mask composite of a very large (deep-zoom) image stays within canvas limits.
 *
 * _compositeMasks made one canvas at the image's full pixel size. A whole-slide
 * image is tens of thousands of pixels on a side, past every browser's canvas
 * limit, so the canvas drew nothing and every brush mask vanished without an
 * error. These tests stub the canvas, record every size requested and every
 * draw, and check that the composite is capped and a painted tile still lands
 * on it, while a normal image keeps its full-resolution composite.
 */

require('../../potato/static/mask-buffer.js');
const ImageAnnotationManager = require('../../potato/static/image-annotation.js');

const MAX_SIDE = ImageAnnotationManager.COMPOSITE_MAX_SIDE;
const MAX_AREA = ImageAnnotationManager.COMPOSITE_MAX_AREA;

/** A canvas whose 2D context records the calls made on it. */
function fakeCanvas(log) {
    const canvas = { _w: 0, _h: 0 };
    Object.defineProperty(canvas, 'width', {
        get() { return this._w; },
        set(v) { this._w = v; log.sizes.push(['width', v]); },
    });
    Object.defineProperty(canvas, 'height', {
        get() { return this._h; },
        set(v) { this._h = v; log.sizes.push(['height', v]); },
    });
    const ctx = {
        canvas,
        clearRect: (...a) => log.calls.push(['clearRect', canvas, ...a]),
        createImageData: (w, h) => ({ width: w, height: h,
                                      data: new Uint8ClampedArray(w * h * 4) }),
        putImageData: (img, x, y) => log.calls.push(['putImageData', canvas, img, x, y]),
        drawImage: (...a) => log.calls.push(['drawImage', canvas, ...a]),
    };
    canvas.getContext = () => ctx;
    log.canvases.push(canvas);
    return canvas;
}

function stubCanvases() {
    const log = { sizes: [], calls: [], canvases: [] };
    const real = document.createElement.bind(document);
    const spy = jest.spyOn(document, 'createElement').mockImplementation((tag) =>
        (String(tag).toLowerCase() === 'canvas' ? fakeCanvas(log) : real(tag)));
    return { log, restore: () => spy.mockRestore() };
}

function managerWithMask(width, height, paint) {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.maskImgWidth = width;
    m.maskImgHeight = height;
    const buffer = new MaskBuffer(width, height);
    paint(buffer);
    m.masks = { tumour: { color: '#ff0000', buffer } };
    return m;
}

describe('mask composite size cap', () => {
    let stub;
    beforeEach(() => { stub = stubCanvases(); });
    afterEach(() => stub.restore());

    test('a 100000 x 80000 slide gets a capped composite and the tile still renders', () => {
        // One painted 64x64 tile well inside the slide.
        const x0 = 64 * 781, y0 = 64 * 625;   // tile-aligned
        const m = managerWithMask(100000, 80000, (buffer) => {
            for (let y = y0; y < y0 + 64; y++) buffer.setSpan(y, x0, x0 + 63);   // inclusive
        });

        const composite = m._compositeMasks(m._visibleMasks());
        expect(composite).not.toBeNull();

        // No canvas side over the cap was ever requested, and the area fits.
        for (const [, v] of stub.log.sizes) expect(v).toBeLessThanOrEqual(MAX_SIDE);
        for (const c of stub.log.canvases) {
            expect(c.width * c.height).toBeLessThanOrEqual(MAX_AREA);
        }
        expect(Math.max(composite.width, composite.height)).toBeLessThanOrEqual(MAX_SIDE);
        // The aspect ratio is kept.
        expect(composite.width / composite.height).toBeCloseTo(100000 / 80000, 2);

        // The painted tile is drawn onto the composite, scaled into place.
        const draws = stub.log.calls.filter(c => c[0] === 'drawImage' && c[1] === composite);
        expect(draws).toHaveLength(1);
        const [, , , sx, sy, sw, sh, dx, dy, dw, dh] = draws[0];
        expect([sx, sy, sw, sh]).toEqual([0, 0, 64, 64]);
        const scale = composite.width / 100000;
        expect(dx).toBe(Math.floor(x0 * scale));
        expect(dy).toBe(Math.floor(y0 * scale));
        expect(dw).toBeGreaterThanOrEqual(1);
        expect(dh).toBeGreaterThanOrEqual(1);

        // And the scratch tile it was drawn from held the red paint.
        const put = stub.log.calls.find(c => c[0] === 'putImageData' && c[1] !== composite);
        expect(put).toBeDefined();
        const img = put[2];
        expect(Array.from(img.data.slice(0, 4))).toEqual([255, 0, 0, 255]);
    });

    test('an ordinary image keeps a full-resolution composite', () => {
        const m = managerWithMask(800, 600, (buffer) => buffer.setSpan(10, 5, 20));
        const composite = m._compositeMasks(m._visibleMasks());
        expect([composite.width, composite.height]).toEqual([800, 600]);
        const puts = stub.log.calls.filter(c => c[0] === 'putImageData' && c[1] === composite);
        expect(puts).toHaveLength(1);
        expect(stub.log.calls.some(c => c[0] === 'drawImage')).toBe(false);
    });

    test('the last tile reaches the composite edge and the area stays capped', () => {
        // Audit 105 P3: sized with ceil and drawn with floor, the last column
        // got no tile, and 4051 x 3950 overshot the area cap by 0.01%.
        const width = 8193, height = 64;
        const m = managerWithMask(width, height, (buffer) => {
            for (let y = 0; y < 64; y++) buffer.setSpan(y, width - 1, width - 1);
        });
        const composite = m._compositeMasks(m._visibleMasks());
        const draws = stub.log.calls.filter(c => c[0] === 'drawImage' && c[1] === composite);
        const last = draws.reduce((a, d) => (d[7] > a[7] ? d : a));
        expect(last[7] + last[9]).toBe(composite.width);
        const wide = managerWithMask(4051, 3950, (buffer) => buffer.setSpan(0, 0, 1));
        const capped = wide._compositeMasks(wide._visibleMasks());
        expect(capped.width * capped.height).toBeLessThanOrEqual(MAX_AREA);
    });

    test('the last column is painted at every capped width', () => {
        // Audit 105 N3: drawn at w * (cw / w), the image's right edge came out
        // a hair under cw for some widths (11681 -> 3184.9999999999995) and
        // floored to a pixel short, leaving the last column unpainted.
        const short = [];
        for (let width = 8193; width < 12000; width += 13) {
            stub.log.calls.length = 0;
            const m = managerWithMask(width, 64, (buffer) => {
                for (let y = 0; y < 64; y++) buffer.setSpan(y, width - 1, width - 1);
            });
            const composite = m._compositeMasks(m._visibleMasks());
            const draws = stub.log.calls.filter(c => c[0] === 'drawImage' && c[1] === composite);
            const last = draws.reduce((a, d) => (d[7] > a[7] ? d : a));
            if (last[7] + last[9] !== composite.width) short.push(width);
        }
        expect(short).toEqual([]);
    });

    test('compositeScale caps the side and the area', () => {
        expect(ImageAnnotationManager.compositeScale(1000, 1000)).toBe(1);
        expect(ImageAnnotationManager.compositeScale(8192, 100)).toBeCloseTo(0.5);
        const s = ImageAnnotationManager.compositeScale(4000, 4000);
        expect(4000 * s * 4000 * s).toBeLessThanOrEqual(MAX_AREA + 1);
    });
});

/**
 * The CLIENT's serializer for the Wave 1 geometry primitives.
 *
 * These drive `_getObjectCoordinates` directly rather than hand-building the
 * shape the exporter expects. That distinction is the whole point: two export
 * bugs previously survived a full Python suite because every fixture was
 * hand-written in a shape the browser has never produced. If the client and
 * `cv_utils` disagree, it has to fail here.
 *
 * The ellipse cases carry the sharper lesson. A freshly DRAWN ellipse has
 * originX 'left' (so dragging a corner resizes it) while a RESTORED one has
 * originX 'center' (so rotation pivots correctly). Deriving the centre as
 * `left + rx` is therefore correct for one and wrong by a full radius for the
 * other — the shape would jump on the first save after a reload.
 */

const fs = require('fs');
const path = require('path');

// The polygon/polyline branch delegates its transform maths to fabric rather
// than re-deriving it (an earlier hand-rolled version shifted every vertex by
// half the shape's size). Stub only what that path uses, with fabric's real
// semantics: a 2D affine matrix [a, b, c, d, e, f] applied as
//   x' = a x + c y + e ,  y' = b x + d y + f
global.fabric = {
    Point: function (x, y) { this.x = x; this.y = y; },
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

/** A manager whose image fills the canvas 1:1 at the origin. */
function makeManager() {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.image = { width: IMG_W, height: IMG_H, scaleX: 1, scaleY: 1, left: 0, top: 0 };
    m.config = {};
    return m;
}

/** Minimal stand-ins for the fabric objects the tools create. */
function drawnEllipse({ left, top, rx, ry, angle = 0, scaleX = 1, scaleY = 1 }) {
    return {
        annotationData: { type: 'ellipse', label: 'cell', color: '#0f0' },
        left, top, rx, ry, angle, scaleX, scaleY,
        originX: 'left', originY: 'top',
        // fabric's own accessor, which is what the serializer must use.
        getCenterPoint: () => ({ x: left + rx * scaleX, y: top + ry * scaleY }),
    };
}

function restoredEllipse({ cx, cy, rx, ry, angle = 0 }) {
    return {
        annotationData: { type: 'ellipse', label: 'cell', color: '#0f0' },
        left: cx, top: cy, rx, ry, angle, scaleX: 1, scaleY: 1,
        originX: 'center', originY: 'center',
        getCenterPoint: () => ({ x: cx, y: cy }),
    };
}

function polylineObject(points) {
    const xs = points.map(p => p.x);
    const ys = points.map(p => p.y);
    const minX = Math.min(...xs);
    const minY = Math.min(...ys);
    const maxX = Math.max(...xs);
    const maxY = Math.max(...ys);
    return {
        annotationData: { type: 'polyline', label: 'lane', color: '#f00' },
        points,
        left: minX,
        top: minY,
        scaleX: 1,
        scaleY: 1,
        angle: 0,
        pathOffset: { x: (minX + maxX) / 2, y: (minY + maxY) / 2 },
        calcTransformMatrix: () => [1, 0, 0, 1, (minX + maxX) / 2, (minY + maxY) / 2],
    };
}

describe('polyline serialization', () => {
    test('emits normalized vertices', () => {
        const m = makeManager();
        const obj = polylineObject([
            { x: 64, y: 96 }, { x: 320, y: 120 }, { x: 576, y: 144 },
        ]);

        const coords = m._getObjectCoordinates(obj);

        expect(coords).toHaveLength(3);
        expect(coords[0].x).toBeCloseTo(0.1, 6);
        expect(coords[0].y).toBeCloseTo(0.2, 6);
        expect(coords[2].x).toBeCloseTo(0.9, 6);
        expect(coords[2].y).toBeCloseTo(0.3, 6);
    });

    test('every coordinate is inside the unit square', () => {
        const m = makeManager();
        const coords = m._getObjectCoordinates(polylineObject([
            { x: 0, y: 0 }, { x: IMG_W, y: IMG_H },
        ]));
        coords.forEach(c => {
            expect(c.x).toBeGreaterThanOrEqual(0);
            expect(c.x).toBeLessThanOrEqual(1);
            expect(c.y).toBeGreaterThanOrEqual(0);
            expect(c.y).toBeLessThanOrEqual(1);
        });
    });

    test('is serialized as an array, like a polygon and unlike a bbox', () => {
        const m = makeManager();
        const coords = m._getObjectCoordinates(polylineObject([
            { x: 10, y: 10 }, { x: 20, y: 20 },
        ]));
        expect(Array.isArray(coords)).toBe(true);
    });
});

describe('ellipse serialization', () => {
    test('a freshly drawn ellipse reports its centre, not its corner', () => {
        const m = makeManager();
        // Drawn from (256,216) to (384,264): centre (320,240), rx 64, ry 24.
        const coords = m._getObjectCoordinates(
            drawnEllipse({ left: 256, top: 216, rx: 64, ry: 24 }));

        expect(coords.cx).toBeCloseTo(0.5, 6);
        expect(coords.cy).toBeCloseTo(0.5, 6);
        expect(coords.rx).toBeCloseTo(0.1, 6);
        expect(coords.ry).toBeCloseTo(0.05, 6);
    });

    test('a restored ellipse serializes to the SAME coordinates', () => {
        // The regression that origin-agnostic centre reading exists to prevent:
        // reading `left + rx` here would shift the shape by a full radius.
        const m = makeManager();
        const drawn = m._getObjectCoordinates(
            drawnEllipse({ left: 256, top: 216, rx: 64, ry: 24 }));
        const restored = m._getObjectCoordinates(
            restoredEllipse({ cx: 320, cy: 240, rx: 64, ry: 24 }));

        expect(restored).toEqual(drawn);
    });

    test('survives repeated save/reload without drifting', () => {
        const m = makeManager();
        let coords = m._getObjectCoordinates(
            drawnEllipse({ left: 256, top: 216, rx: 64, ry: 24 }));

        for (let i = 0; i < 5; i++) {
            coords = m._getObjectCoordinates(restoredEllipse({
                cx: coords.cx * IMG_W,
                cy: coords.cy * IMG_H,
                rx: coords.rx * IMG_W,
                ry: coords.ry * IMG_H,
            }));
        }

        expect(coords.cx).toBeCloseTo(0.5, 9);
        expect(coords.cy).toBeCloseTo(0.5, 9);
        expect(coords.rx).toBeCloseTo(0.1, 9);
        expect(coords.ry).toBeCloseTo(0.05, 9);
    });

    test('records the rotation angle', () => {
        const m = makeManager();
        const coords = m._getObjectCoordinates(
            restoredEllipse({ cx: 320, cy: 240, rx: 64, ry: 24, angle: 30 }));
        expect(coords.angle).toBe(30);
    });

    test('accounts for scaling applied by dragging a handle', () => {
        const m = makeManager();
        const coords = m._getObjectCoordinates(
            drawnEllipse({ left: 0, top: 0, rx: 64, ry: 24, scaleX: 2, scaleY: 3 }));
        expect(coords.rx).toBeCloseTo((64 * 2) / IMG_W, 6);
        expect(coords.ry).toBeCloseTo((24 * 3) / IMG_H, 6);
    });

    test('emits the parametric form, not a vertex list', () => {
        // Storing vertices would re-approximate on every save and drift.
        const m = makeManager();
        const coords = m._getObjectCoordinates(
            restoredEllipse({ cx: 320, cy: 240, rx: 64, ry: 24 }));
        expect(Array.isArray(coords)).toBe(false);
        expect(Object.keys(coords).sort()).toEqual(
            ['angle', 'cx', 'cy', 'rx', 'ry']);
    });
});

describe('contract coverage', () => {
    test('unknown types still serialize to null', () => {
        const m = makeManager();
        expect(m._getObjectCoordinates({
            annotationData: { type: 'not_a_real_type' },
        })).toBeNull();
    });

    test('no image means no coordinates', () => {
        const m = makeManager();
        m.image = null;
        expect(m._getObjectCoordinates(
            restoredEllipse({ cx: 1, cy: 1, rx: 1, ry: 1 }))).toBeNull();
    });
});

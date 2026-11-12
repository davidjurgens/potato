/**
 * The arithmetic behind painting points (segment_3d): which points a stroke
 * reaches, and what the stored segments look like afterwards.
 */

const paint = require('../../potato/static/pointcloud/pc-paint.js');

const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

/** Column-major perspective, camera at the origin looking down -z. */
function perspective(fovDeg, aspect, near, far) {
    const f = 1 / Math.tan((fovDeg * Math.PI / 180) / 2);
    const nf = 1 / (near - far);
    return [f / aspect, 0, 0, 0,
            0, f, 0, 0,
            0, 0, (far + near) * nf, -1,
            0, 0, 2 * far * near * nf, 0];
}

describe('projectPoints', () => {
    test('maps NDC onto CSS pixels with y down', () => {
        const screen = paint.projectPoints(
            new Float32Array([-1, 1, 0, 1, -1, 0, 0, 0, 0]), 3, IDENTITY, 200, 100);
        expect(Array.from(screen)).toEqual([0, 0, 200, 100, 100, 50]);
    });

    test('a point ahead of the camera lands at the centre; one behind it lands nowhere', () => {
        const m = perspective(90, 1, 0.1, 100);
        const screen = paint.projectPoints(
            new Float32Array([0, 0, -10, 0, 0, 10, 0, 0, -500]), 3, m, 100, 100);
        expect(screen[0]).toBeCloseTo(50);
        expect(screen[1]).toBeCloseTo(50);
        // Behind the camera: w < 0. Without the guard the perspective divide
        // mirrors it into the middle of the screen, under the brush.
        expect(screen[2]).toBeNaN();
        // Beyond the far plane.
        expect(screen[4]).toBeNaN();
    });
});

describe('brushHits', () => {
    // Four points on screen: three along y = 50, one well above.
    const screen = new Float32Array([25, 50, 50, 50, 75, 50, 50, 10]);

    test('takes points within the radius and no others', () => {
        expect(paint.brushHits(screen, 4, 50, 52, 50, 52, 3, null)).toEqual([1]);
        expect(paint.brushHits(screen, 4, 50, 54, 50, 54, 3, null)).toEqual([]);
    });

    test('a fast stroke covers the whole segment between two events', () => {
        // The events are 50 px apart with a 3 px brush; testing only the event
        // positions would skip the point in the middle.
        expect(paint.brushHits(screen, 4, 25, 50, 75, 50, 3, null)).toEqual([0, 1, 2]);
    });

    test('accept() filters, and an unprojected point is never hit', () => {
        expect(paint.brushHits(screen, 4, 25, 50, 75, 50, 3, (i) => i !== 1)).toEqual([0, 2]);
        const hidden = new Float32Array([NaN, NaN, 50, 50]);
        expect(paint.brushHits(hidden, 2, 50, 50, 50, 50, 80, null)).toEqual([1]);
    });
});

describe('lassoHits', () => {
    test('takes the points inside a concave outline only', () => {
        // A U: the notch between the arms is outside the polygon.
        const u = [[0, 0], [30, 0], [30, 30], [20, 30], [20, 10], [10, 10], [10, 30], [0, 30]];
        const screen = new Float32Array([5, 20, 15, 20, 25, 20, 15, 5, 40, 5]);
        expect(paint.lassoHits(screen, 5, u, null)).toEqual([0, 2, 3]);
    });

    test('fewer than three vertices selects nothing', () => {
        const screen = new Float32Array([5, 5]);
        expect(paint.lassoHits(screen, 1, [[0, 0], [10, 10]], null)).toEqual([]);
    });
});

describe('labels per point', () => {
    test('a later segment wins a point held twice; junk indices are ignored', () => {
        const map = paint.labelsByPoint([
            { type: 'segment_3d', label: 'car', indices: [1, 2, 3] },
            { type: 'cuboid_3d', label: 'car' },
            { type: 'segment_3d', label: 'road', indices: [3, 4, -1, 2.5, 'x'] },
        ]);
        expect(Array.from(map.entries())).toEqual(
            [[1, 'car'], [2, 'car'], [3, 'road'], [4, 'road']]);
    });

    test('paint moves a point between labels and null unlabels it', () => {
        const map = new Map([[1, 'car'], [2, 'car']]);
        expect(paint.paint(map, [2, 3], 'road')).toBe(2);
        expect(paint.paint(map, [2], 'road')).toBe(0);
        expect(paint.paint(map, [1, 9], null)).toBe(1);
        expect(Array.from(map.entries())).toEqual([[2, 'road'], [3, 'road']]);
    });
});

describe('segmentsFrom', () => {
    const colorFor = (label) => ({ car: '#ff0000', road: '#808080' }[label]);

    test('one segment per label, sorted, and no point in two segments', () => {
        const box = { type: 'cuboid_3d', label: 'car' };
        const anns = [
            { type: 'segment_3d', label: 'car', color: '#ff0000', indices: [5, 1, 3] },
            box,
        ];
        const map = paint.labelsByPoint(anns);
        paint.paint(map, [3, 7], 'road');
        const out = paint.segmentsFrom(anns, map, colorFor, ['car', 'road']);
        expect(out).toEqual([
            { type: 'segment_3d', label: 'car', color: '#ff0000', indices: [1, 5] },
            box,
            { type: 'segment_3d', label: 'road', color: '#808080', indices: [3, 7] },
        ]);
        expect(out[1]).toBe(box);
    });

    test('an unchanged segment is the same object; an emptied one is dropped', () => {
        const car = { type: 'segment_3d', label: 'car', color: '#ff0000', indices: [1, 2] };
        const road = { type: 'segment_3d', label: 'road', color: '#808080', indices: [3] };
        const map = paint.labelsByPoint([car, road]);
        paint.paint(map, [3], null);
        const out = paint.segmentsFrom([car, road], map, colorFor, []);
        expect(out).toHaveLength(1);
        expect(out[0]).toBe(car);
    });

    test('two segments with one label merge into the first', () => {
        const a = { type: 'segment_3d', label: 'car', color: '#ff0000', indices: [4], track_id: 2 };
        const b = { type: 'segment_3d', label: 'car', color: '#ff0000', indices: [1] };
        const out = paint.segmentsFrom([a, b], paint.labelsByPoint([a, b]), colorFor, []);
        expect(out).toEqual([{ type: 'segment_3d', label: 'car', color: '#ff0000',
                               indices: [1, 4], track_id: 2 }]);
    });

    test('a model segment a person repainted is marked edited', () => {
        const seg = { type: 'segment_3d', label: 'car', color: '#ff0000',
                      indices: [1], source: 'model' };
        const map = paint.labelsByPoint([seg]);
        paint.paint(map, [2], 'car');
        const out = paint.segmentsFrom([seg], map, colorFor, []);
        expect(out[0]).toMatchObject({ source: 'model', edited: true, indices: [1, 2] });
        expect(seg.edited).toBeUndefined();
    });

    test('new labels follow the configured order, then anything else', () => {
        const map = new Map([[1, 'zebra'], [2, 'road'], [3, 'car']]);
        const out = paint.segmentsFrom([], map, colorFor, ['car', 'road']);
        expect(out.map((o) => o.label)).toEqual(['car', 'road', 'zebra']);
    });
});

describe('paintColors and visibleIndex', () => {
    // A decimated buffer: buffer slot i holds source point indices[i].
    const indices = new Uint32Array([10, 20, 30]);
    const base = new Float32Array([0.1, 0.1, 0.1, 0.2, 0.2, 0.2, 0.3, 0.3, 0.3]);
    const rgbFor = (label) => ({ car: { r: 1, g: 0, b: 0 } }[label] || null);

    test('painted points take their label colour by SOURCE index', () => {
        const out = new Float32Array(9);
        paint.paintColors(out, base, 3, indices, new Map([[20, 'car']]), rgbFor);
        expect(Array.from(out)).toEqual(Array.from(
            new Float32Array([0.1, 0.1, 0.1, 1, 0, 0, 0.3, 0.3, 0.3])));
    });

    test('hidden labels drop out of the draw; unlabelled points stay', () => {
        const map = new Map([[20, 'car'], [30, 'road']]);
        expect(paint.visibleIndex(3, indices, map, null)).toBeNull();
        expect(paint.visibleIndex(3, indices, map, new Set(['bike']))).toBeNull();
        expect(Array.from(paint.visibleIndex(3, indices, map, new Set(['car'])))).toEqual([0, 2]);
    });
});

/**
 * Tracking interpolation for shapes that are not boxes.
 *
 * Driven against the REAL tracking-interpolation.js, not a Python restatement
 * of it. The existing test_tracking_interpolation.py reimplements the maths in
 * Python and asserts against its own copy, which cannot catch a divergence
 * between the two — the class of bug that has bitten the export path twice.
 *
 * The polygon cases carry the weight here. Interpolating two outlines pairwise
 * looks right whenever the annotator happened to trace both the same way, and
 * turns the shape inside out when they did not.
 */

require('../../potato/static/tracking-interpolation.js');

const engine = window.TrackingInterpolationEngine;

function box(x, y, w, h) {
    return { bbox: { x, y, width: w, height: h } };
}

function square(cx, cy, r) {
    return {
        points: [
            { x: cx - r, y: cy - r }, { x: cx + r, y: cy - r },
            { x: cx + r, y: cy + r }, { x: cx - r, y: cy + r },
        ],
    };
}

function centroid(points) {
    const sx = points.reduce((a, p) => a + p.x, 0);
    const sy = points.reduce((a, p) => a + p.y, 0);
    return { x: sx / points.length, y: sy / points.length };
}

function area(points) {
    let sum = 0;
    for (let i = 0; i < points.length; i++) {
        const p = points[i];
        const q = points[(i + 1) % points.length];
        sum += p.x * q.y - q.x * p.y;
    }
    return Math.abs(sum) / 2;
}

describe('boxes still behave exactly as before', () => {
    const track = { keyframes: { 0: box(0, 0, 10, 10), 10: box(100, 0, 10, 10) } };

    test('a keyframe returns its own box', () => {
        expect(engine.interpolate(track, 0)).toEqual(
            { x: 0, y: 0, width: 10, height: 10 });
    });

    test('the midpoint is halfway', () => {
        expect(engine.interpolate(track, 5).x).toBeCloseTo(50);
    });

    test('out of range returns null', () => {
        expect(engine.interpolate(track, 20)).toBeNull();
    });

    test('constant interpolation holds the previous keyframe', () => {
        const held = { ...track, interpolation: 'constant' };
        expect(engine.interpolate(held, 5).x).toBe(0);
    });

    test('the legacy interpolate() still returns a bare bbox', () => {
        const result = engine.interpolate(track, 5);
        expect(result).toHaveProperty('width');
        expect(result).not.toHaveProperty('type');
    });
});

describe('polygon interpolation', () => {
    test('a polygon keyframe round-trips unchanged', () => {
        const track = { keyframes: { 0: square(50, 50, 10) } };
        const shape = engine.interpolateShape(track, 0);
        expect(shape.type).toBe('polygon');
        expect(shape.points).toHaveLength(4);
        expect(shape.interpolated).toBe(false);
    });

    test('a moving polygon lands halfway at the midpoint', () => {
        const track = { keyframes: { 0: square(0, 0, 10), 10: square(100, 0, 10) } };
        const shape = engine.interpolateShape(track, 5);
        expect(shape.type).toBe('polygon');
        expect(centroid(shape.points).x).toBeCloseTo(50, 0);
    });

    test('a growing polygon interpolates its area', () => {
        const track = { keyframes: { 0: square(50, 50, 10), 10: square(50, 50, 20) } };
        const mid = engine.interpolateShape(track, 5);
        // Halfway between a 20x20 and a 40x40 square is a 30x30.
        expect(area(mid.points)).toBeCloseTo(900, -2);
    });

    test('vertex counts need not match between keyframes', () => {
        const pentagon = { points: [] };
        for (let i = 0; i < 5; i++) {
            const a = (i / 5) * Math.PI * 2;
            pentagon.points.push({ x: 50 + 10 * Math.cos(a), y: 50 + 10 * Math.sin(a) });
        }
        const track = { keyframes: { 0: square(50, 50, 10), 10: pentagon } };
        const mid = engine.interpolateShape(track, 5);
        expect(mid).not.toBeNull();
        expect(mid.points.length).toBeGreaterThan(3);
        expect(mid.points.every(p => Number.isFinite(p.x) && Number.isFinite(p.y)))
            .toBe(true);
    });

    test('a different tracing start point does not make the shape spin', () => {
        /**
         * The bug arc-length alignment exists to prevent. Both keyframes are
         * the SAME square; only the vertex the annotator started from differs.
         * Every interpolated frame must therefore be that same square.
         */
        const start = square(50, 50, 10);
        const rotated = { points: [start.points[2], start.points[3],
                                   start.points[0], start.points[1]] };
        const track = { keyframes: { 0: start, 10: rotated } };

        for (const frame of [2, 5, 8]) {
            const mid = engine.interpolateShape(track, frame);
            expect(area(mid.points)).toBeCloseTo(400, -1);
            expect(centroid(mid.points).x).toBeCloseTo(50, 0);
            expect(centroid(mid.points).y).toBeCloseTo(50, 0);
        }
    });

    test('naive pairwise interpolation would have collapsed that shape', () => {
        /**
         * A control proving the previous test can fail: interpolating the
         * rotated correspondence pairwise pulls opposite corners together and
         * the area collapses toward zero at the midpoint.
         */
        const start = square(50, 50, 10).points;
        const rotated = [start[2], start[3], start[0], start[1]];
        const naive = start.map((p, i) => ({
            x: p.x + (rotated[i].x - p.x) * 0.5,
            y: p.y + (rotated[i].y - p.y) * 0.5,
        }));
        expect(area(naive)).toBeLessThan(10);
    });

    test('a polygon carries a bounding box for box-only callers', () => {
        const track = { keyframes: { 0: square(50, 50, 10), 10: square(60, 50, 10) } };
        const bbox = engine.interpolate(track, 5);
        expect(bbox.width).toBeCloseTo(20, 0);
    });

    test('a degenerate polygon does not produce NaN', () => {
        const degenerate = { points: [{ x: 5, y: 5 }, { x: 5, y: 5 }, { x: 5, y: 5 }] };
        const track = { keyframes: { 0: degenerate, 10: square(50, 50, 10) } };
        const mid = engine.interpolateShape(track, 5);
        expect(mid).not.toBeNull();
        expect(mid.points.every(p => Number.isFinite(p.x))).toBe(true);
    });
});

describe('mask interpolation is a hold, and says so', () => {
    const maskA = { rle: { counts: [0, 10, 90], size: [10, 10] } };
    const maskB = { rle: { counts: [0, 50, 50], size: [10, 10] } };
    const track = { keyframes: { 0: maskA, 10: maskB } };

    test('a mask keyframe returns its own rle', () => {
        expect(engine.interpolateShape(track, 0).rle).toBe(maskA.rle);
    });

    test('before the midpoint it holds the earlier mask', () => {
        expect(engine.interpolateShape(track, 3).rle).toBe(maskA.rle);
    });

    test('after the midpoint it holds the later mask', () => {
        expect(engine.interpolateShape(track, 8).rle).toBe(maskB.rle);
    });

    test('a held frame is never reported as interpolated', () => {
        /**
         * The UI needs to distinguish a real annotation from a hold; blending
         * rasters would produce ghosts, so we hold and label it honestly.
         */
        expect(engine.interpolateShape(track, 3).interpolated).toBe(false);
    });
});

describe('mixed-kind tracks', () => {
    test('a kind change between keyframes holds rather than inventing a path', () => {
        const track = {
            keyframes: {
                0: square(50, 50, 10),
                10: { rle: { counts: [0, 10, 90], size: [10, 10] } },
            },
        };
        const mid = engine.interpolateShape(track, 5);
        expect(mid.type).toBe('polygon');
        expect(mid.interpolated).toBe(false);
    });

    test('getTrackKind reports the kind, or mixed', () => {
        expect(engine.getTrackKind({ keyframes: { 0: box(0, 0, 1, 1) } })).toBe('bbox');
        expect(engine.getTrackKind({ keyframes: { 0: square(5, 5, 1) } })).toBe('polygon');
        expect(engine.getTrackKind({
            keyframes: { 0: square(5, 5, 1), 5: box(0, 0, 1, 1) },
        })).toBe('mixed');
    });

    test('getTrackKind on an empty track is null, not a guess', () => {
        expect(engine.getTrackKind({ keyframes: {} })).toBeNull();
    });
});

describe('track metadata', () => {
    test('the range spans the keyframes', () => {
        const track = { keyframes: { 3: box(0, 0, 1, 1), 9: box(0, 0, 1, 1) } };
        expect(engine.getTrackRange(track)).toEqual({ startFrame: 3, endFrame: 9 });
    });

    test('explicit start and end frames win over the keyframes', () => {
        const track = {
            keyframes: { 3: box(0, 0, 1, 1) },
            startFrame: 0, endFrame: 20,
        };
        expect(engine.getTrackRange(track)).toEqual({ startFrame: 0, endFrame: 20 });
    });

    test('keyframes come back numerically sorted, not lexically', () => {
        const track = {
            keyframes: {
                2: box(0, 0, 1, 1), 10: box(0, 0, 1, 1), 1: box(0, 0, 1, 1),
            },
        };
        expect(engine.getKeyframes(track)).toEqual([1, 2, 10]);
    });
});

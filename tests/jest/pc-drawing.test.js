/**
 * The arithmetic behind placing a 3D box by dragging.
 *
 * None of this needs WebGL, which is the whole reason it lives as static
 * functions on the manager rather than inside the mouse handlers: the parts
 * that decide *where the box goes* are checkable, and only the parts that
 * decide *which pixels light up* are not.
 *
 * The tests are geometric rather than golden-value. "A box drawn around a car
 * ends up as tall as the car" holds for any correct implementation and fails
 * for the plausible wrong ones (fitting to the ground, ignoring yaw, using the
 * minimum instead of a percentile).
 */

require('../../potato/static/pointcloud/pc-wire.js');
require('../../potato/static/pointcloud/pc-calibration.js');
const Manager = require('../../potato/static/pointcloud/pc-viewer.js');

const {
    intersectPlaneZ, groundLevel, footprintToCuboid, fitHeightToPoints,
    yawQuaternion, composeYaw, invertYaw, annotationCenter, cuboidCorners,
} = Manager;

/** Yaw of a quaternion, for asserting on rotations without golden values. */
function yawOf(q) {
    return Math.atan2(2 * (q[3] * q[2] + q[0] * q[1]),
                      1 - 2 * (q[1] * q[1] + q[2] * q[2]));
}

describe('intersectPlaneZ', () => {
    test('a ray pointing down hits the plane below it', () => {
        const hit = intersectPlaneZ([0, 0, 10], [0, 0, -1], 0);
        expect(hit).toEqual([0, 0, 0]);
    });

    test('the hit is where the ray actually crosses, not straight down', () => {
        // 45 degrees down and forward from 10 m up: 10 m forward at the plane.
        const s = Math.SQRT1_2;
        const hit = intersectPlaneZ([0, 0, 10], [s, 0, -s], 0);
        expect(hit[0]).toBeCloseTo(10, 6);
        expect(hit[2]).toBe(0);
    });

    test('a ray parallel to the plane never hits it', () => {
        expect(intersectPlaneZ([0, 0, 10], [1, 0, 0], 0)).toBeNull();
    });

    test('a ray pointing away from the plane does not hit it behind us', () => {
        // Looking up at the sky. The line still crosses z = 0 -- BEHIND the
        // camera. Returning that point puts boxes at absurd distances every
        // time the annotator sweeps the mouse above the horizon.
        expect(intersectPlaneZ([0, 0, 10], [0, 0, 1], 0)).toBeNull();
    });

    test('the plane can be below the origin, as a real lidar ground is', () => {
        const hit = intersectPlaneZ([0, 0, 0], [0, 0, -1], -1.7);
        expect(hit[2]).toBeCloseTo(-1.7, 6);
    });

    test('a non-finite direction is rejected rather than propagated', () => {
        expect(intersectPlaneZ([0, 0, 1], [0, 0, NaN], 0)).toBeNull();
    });
});

describe('groundLevel', () => {
    /** A flat road at `z`, with `n` points. */
    function road(z, n) {
        const out = new Float32Array(n * 3);
        for (let i = 0; i < n; i++) {
            out[i * 3] = i * 0.1;
            out[i * 3 + 1] = 0;
            out[i * 3 + 2] = z + (i % 7) * 0.001;
        }
        return out;
    }

    test('a flat scene reports its own height', () => {
        expect(groundLevel(road(-1.7, 1000))).toBeCloseTo(-1.7, 2);
    });

    test('it is not zero for a roof-mounted sensor', () => {
        // The failure this exists to prevent: assuming z = 0 puts every box
        // 1.7 m above the road, floating over the scene.
        expect(groundLevel(road(-1.73, 500))).toBeLessThan(-1.5);
    });

    test('one stray return far below does not drag the ground down', () => {
        const points = road(-1.7, 1000);
        points[2] = -40;            // a multipath reflection under the road
        // The minimum would be -40. A low percentile stays on the tarmac.
        expect(groundLevel(points)).toBeGreaterThan(-2);
    });

    test('an empty cloud is zero rather than an exception', () => {
        expect(groundLevel(new Float32Array(0))).toBe(0);
        expect(groundLevel(null)).toBe(0);
    });

    test('a tall scene still finds the floor, not the middle', () => {
        // A road with a building: 90% of returns are the wall, well above.
        const n = 2000;
        const points = new Float32Array(n * 3);
        for (let i = 0; i < n; i++) {
            points[i * 3 + 2] = (i % 10 === 0) ? -1.7 : 5 + (i % 30) * 0.1;
        }
        expect(groundLevel(points)).toBeLessThan(0);
    });
});

describe('footprintToCuboid', () => {
    test('the footprint spans the drag and sits on the ground', () => {
        const box = footprintToCuboid([2, 3, -1.7], [6, 5, -1.7], 0, -1.7, 1.8);
        expect(box.size[0]).toBeCloseTo(4, 6);
        expect(box.size[1]).toBeCloseTo(2, 6);
        expect(box.size[2]).toBeCloseTo(1.8, 6);
        expect(box.center[0]).toBeCloseTo(4, 6);
        expect(box.center[1]).toBeCloseTo(4, 6);
        // Centre is half the height above the ground, so the base rests on it.
        expect(box.center[2]).toBeCloseTo(-1.7 + 0.9, 6);
    });

    test('the base rests on the ground plane, checked via the corners', () => {
        const box = footprintToCuboid([0, 0, -1.7], [4, 2, -1.7], 0, -1.7, 1.8);
        const zs = cuboidCorners(box.center, box.size, box.rotation)
            .map((c) => c[2]);
        expect(Math.min(...zs)).toBeCloseTo(-1.7, 6);
    });

    test('dragging in either direction gives the same box', () => {
        const forward = footprintToCuboid([2, 3, 0], [6, 5, 0], 0, 0, 1.8);
        const backward = footprintToCuboid([6, 5, 0], [2, 3, 0], 0, 0, 1.8);
        expect(forward.center).toEqual(backward.center);
        expect(forward.size).toEqual(backward.size);
    });

    test('a click rather than a drag produces nothing', () => {
        // A stray click must not leave a degenerate annotation -- the same
        // guard the 2D canvas needed in Wave 0.8.
        expect(footprintToCuboid([1, 1, 0], [1, 1, 0], 0, 0, 1.8)).toBeNull();
        expect(footprintToCuboid([1, 1, 0], [1.02, 1.01, 0], 0, 0, 1.8))
            .toBeNull();
    });

    test('a sliver in one axis is still refused', () => {
        expect(footprintToCuboid([0, 0, 0], [5, 0.01, 0], 0, 0, 1.8)).toBeNull();
    });

    test('yaw is carried into the rotation', () => {
        const box = footprintToCuboid([0, 0, 0], [4, 2, 0], Math.PI / 4, 0, 1.8);
        expect(yawOf(box.rotation)).toBeCloseTo(Math.PI / 4, 6);
    });

    test('missing corners are refused rather than defaulted', () => {
        expect(footprintToCuboid(null, [1, 1, 0], 0, 0, 1.8)).toBeNull();
    });
});

describe('fitHeightToPoints', () => {
    const GROUND = -1.7;

    /** `n` points scattered inside the given XY box, at heights up to `top`. */
    function objectPoints(cx, cy, halfX, halfY, top, n) {
        const out = new Float32Array(n * 3);
        for (let i = 0; i < n; i++) {
            out[i * 3] = cx + ((i % 5) / 4 - 0.5) * 2 * halfX * 0.9;
            out[i * 3 + 1] = cy + (((i / 5 | 0) % 5) / 4 - 0.5) * 2 * halfY * 0.9;
            out[i * 3 + 2] = GROUND + ((i % 11) / 10) * (top - GROUND);
        }
        return out;
    }

    test('the box grows to reach the tallest point inside it', () => {
        const box = footprintToCuboid([8, -1, GROUND], [12, 1, GROUND], 0,
                                      GROUND, 1.7);
        const fitted = fitHeightToPoints(
            box, objectPoints(10, 0, 2, 1, GROUND + 1.45, 200), GROUND);
        // A van at 1.45 m: the default 1.7 would have been wrong by 25 cm.
        expect(fitted.size[2]).toBeCloseTo(1.5, 1);
        expect(fitted.size[2]).toBeGreaterThan(box.size[2] * 0.8);
    });

    test('the fitted box still rests on the ground', () => {
        const box = footprintToCuboid([8, -1, GROUND], [12, 1, GROUND], 0,
                                      GROUND, 1.7);
        const fitted = fitHeightToPoints(
            box, objectPoints(10, 0, 2, 1, GROUND + 1.45, 200), GROUND);
        const zs = cuboidCorners(fitted.center, fitted.size, fitted.rotation)
            .map((c) => c[2]);
        expect(Math.min(...zs)).toBeCloseTo(GROUND, 6);
    });

    test('the footprint is left alone; only height is fitted', () => {
        // The annotator drew the footprint deliberately and can see it from
        // above. Height is the dimension they cannot judge, and the only one
        // the data should override.
        const box = footprintToCuboid([8, -1, GROUND], [12, 1, GROUND], 0,
                                      GROUND, 1.7);
        const fitted = fitHeightToPoints(
            box, objectPoints(10, 0, 0.3, 0.3, GROUND + 1.2, 200), GROUND);
        expect(fitted.size[0]).toBeCloseTo(box.size[0], 6);
        expect(fitted.size[1]).toBeCloseTo(box.size[1], 6);
        expect(fitted.center[0]).toBeCloseTo(box.center[0], 6);
        expect(fitted.center[1]).toBeCloseTo(box.center[1], 6);
    });

    test('a footprint containing only road is not fitted at all', () => {
        // The failure mode if ground returns count as object returns: the
        // road's own millimetre of noise satisfies "there are points here,
        // and they span a range", and the box collapses to a 5 cm pancake
        // lying on the tarmac. Leaving the drawn box alone is right -- the
        // annotator drew around something the lidar did not see.
        const box = footprintToCuboid([8, -1, GROUND], [12, 1, GROUND], 0,
                                      GROUND, 1.7);
        const road = new Float32Array(300 * 3);
        for (let i = 0; i < 300; i++) {
            road[i * 3] = 8.2 + (i % 20) * 0.18;
            road[i * 3 + 1] = -0.9 + ((i / 20) | 0) * 0.12;
            road[i * 3 + 2] = GROUND + (i % 7) * 0.002;   // surface roughness
        }
        expect(fitHeightToPoints(box, road, GROUND)).toBe(box);
    });

    test('an empty footprint leaves the box exactly as drawn', () => {
        // Fitting to nothing would be fabricating a measurement.
        const box = footprintToCuboid([0, 0, GROUND], [2, 2, GROUND], 0,
                                      GROUND, 1.7);
        const far = objectPoints(50, 50, 1, 1, GROUND + 2, 100);
        expect(fitHeightToPoints(box, far, GROUND)).toBe(box);
    });

    test('too few points inside is treated as empty', () => {
        const box = footprintToCuboid([0, 0, GROUND], [4, 4, GROUND], 0,
                                      GROUND, 1.7);
        const sparse = new Float32Array([1, 1, GROUND + 3, 1.1, 1, GROUND + 3]);
        expect(fitHeightToPoints(box, sparse, GROUND)).toBe(box);
    });

    test('the footprint test respects yaw', () => {
        // A long thin box (6 m x 1.2 m) yawed 90 degrees, so its long axis
        // runs along world Y. Points are strung out along Y with height
        // increasing away from the centre: the tall ones are the far ends of
        // the object, more than 0.6 m out.
        //
        // Testing the axis-aligned bounds instead -- the easy mistake -- keeps
        // only the points within 0.6 m of centre, which are exactly the short
        // ones, and fits a box less than half the true height. So the two
        // implementations give clearly different answers rather than both
        // landing on the default.
        const box = footprintToCuboid([-3, -0.6, GROUND], [3, 0.6, GROUND],
                                      0, GROUND, 1.7);
        const rotated = { ...box, rotation: yawQuaternion(Math.PI / 2) };

        const along = new Float32Array(40 * 3);
        for (let i = 0; i < 40; i++) {
            const y = -2.6 + i * 0.13;
            along[i * 3] = 0;
            along[i * 3 + 1] = y;
            along[i * 3 + 2] = GROUND + 0.2 + Math.abs(y) * 0.5;
        }

        const fitted = fitHeightToPoints(rotated, along, GROUND);
        expect(fitted).not.toBe(rotated);
        // Tallest point is at |y| = 2.6: 0.2 + 1.3 = 1.5 m above the ground.
        expect(fitted.size[2]).toBeCloseTo(1.55, 1);
        // An axis-aligned test would see only |y| <= 0.6, capping at 0.5 m.
        expect(fitted.size[2]).toBeGreaterThan(1.0);
    });

    test('no cloud at all leaves the box untouched', () => {
        const box = footprintToCuboid([0, 0, 0], [2, 2, 0], 0, 0, 1.7);
        expect(fitHeightToPoints(box, null, 0)).toBe(box);
    });
});

describe('composeYaw', () => {
    test('rotating from identity gives exactly that yaw', () => {
        expect(yawOf(composeYaw([0, 0, 0, 1], Math.PI / 6)))
            .toBeCloseTo(Math.PI / 6, 9);
    });

    test('rotations accumulate', () => {
        let q = [0, 0, 0, 1];
        for (let i = 0; i < 3; i++) q = composeYaw(q, Math.PI / 12);
        expect(yawOf(q)).toBeCloseTo(Math.PI / 4, 9);
    });

    test('rotating back returns to where it started', () => {
        const start = [0, 0, 0, 1];
        const there = composeYaw(start, 0.7);
        const back = composeYaw(there, -0.7);
        back.forEach((v, i) => expect(v).toBeCloseTo(start[i], 9));
    });

    test('the result stays a unit quaternion', () => {
        // A non-unit quaternion SCALES the box when it becomes a matrix, so
        // repeated rotation must not let error accumulate into a resize.
        let q = [0, 0, 0, 1];
        for (let i = 0; i < 200; i++) q = composeYaw(q, 0.31);
        const norm = Math.sqrt(q.reduce((a, v) => a + v * v, 0));
        expect(norm).toBeCloseTo(1, 9);
    });

    test('yaw is applied in the world frame, so it survives a tilt', () => {
        // A box pitched out of plane still yaws about world Z when the
        // annotator presses q -- otherwise the key does something different
        // depending on how the box is already oriented.
        const pitched = [0.3826834, 0, 0, 0.9238795];
        const turned = composeYaw(pitched, Math.PI / 2);
        const before = cuboidCorners([0, 0, 0], [4, 1, 1], pitched);
        const after = cuboidCorners([0, 0, 0], [4, 1, 1], turned);
        // The long axis was along X; after a quarter turn about Z it is along Y.
        const spanX = (c) => Math.max(...c.map((p) => p[0]))
            - Math.min(...c.map((p) => p[0]));
        const spanY = (c) => Math.max(...c.map((p) => p[1]))
            - Math.min(...c.map((p) => p[1]));
        expect(spanX(before)).toBeGreaterThan(spanY(before));
        expect(spanY(after)).toBeGreaterThan(spanX(after));
    });
});

describe('invertYaw', () => {
    test('it undoes the yaw of a quaternion', () => {
        const inv = invertYaw(yawQuaternion(0.4));
        // Rotating (1, 0) by +0.4 then by the inverse returns to (1, 0).
        const x = Math.cos(0.4);
        const y = Math.sin(0.4);
        expect(x * inv.c - y * inv.s).toBeCloseTo(1, 9);
        expect(x * inv.s + y * inv.c).toBeCloseTo(0, 9);
    });

    test('identity inverts to identity', () => {
        expect(invertYaw([0, 0, 0, 1]).c).toBeCloseTo(1, 9);
        expect(invertYaw([0, 0, 0, 1]).s).toBeCloseTo(0, 9);
    });
});

describe('annotationCenter', () => {
    test('a cuboid reports its centre', () => {
        expect(annotationCenter({ type: 'cuboid_3d',
                                  coordinates: { center: [1, 2, 3] } }))
            .toEqual([1, 2, 3]);
    });

    test('a point reports itself', () => {
        expect(annotationCenter({ type: 'point_3d', coordinates: [4, 5, 6] }))
            .toEqual([4, 5, 6]);
    });

    test('a polyline reports its centroid', () => {
        expect(annotationCenter({ type: 'polyline_3d',
                                  coordinates: [[0, 0, 0], [2, 4, 6]] }))
            .toEqual([1, 2, 3]);
    });

    test('a segment has no centre, and says so rather than guessing', () => {
        // segment_3d is a set of point indices; a centroid would need the
        // cloud, which this function does not have.
        expect(annotationCenter({ type: 'segment_3d', indices: [1, 2] }))
            .toBeNull();
        expect(annotationCenter(null)).toBeNull();
    });
});

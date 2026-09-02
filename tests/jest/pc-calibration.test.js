/**
 * Client-side projection behaviour that has no Python counterpart.
 *
 * The shared maths is checked far more thoroughly by
 * `tests/unit/test_calibration_js_python_bridge.py`, which runs this same file
 * in Node against the real Python across a range of poses. Duplicating those
 * assertions here would only give a second place for them to rot.
 *
 * What IS unique to the browser is `overlapsImage`: the server projects to
 * decide what a box is, the browser projects to decide what to draw, and
 * deciding what to draw includes deciding what to leave out.
 */

const calib = require('../../potato/static/pointcloud/pc-calibration.js');

/** Focal length 100, principal point (50, 50), at the origin looking down +Z. */
const CAM = {
    name: 'test',
    k: [100, 0, 50, 0, 100, 50, 0, 0, 1],
    rt: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0],
    distortion: [0, 0, 0, 0, 0],
};

describe('overlapsImage', () => {
    test('a box in the middle of the frame is drawn', () => {
        expect(calib.overlapsImage([10, 10, 40, 40], 100, 100)).toBe(true);
    });

    test('a box straddling an edge is drawn', () => {
        expect(calib.overlapsImage([-20, 10, 30, 40], 100, 100)).toBe(true);
        expect(calib.overlapsImage([80, 10, 130, 40], 100, 100)).toBe(true);
    });

    test('a box entirely off to one side is not drawn', () => {
        // These project to real pixels -- they are in front of the camera,
        // just outside its field of view. Drawing them puts lines along the
        // panel edge for objects the camera never saw, which makes the
        // verification view actively misleading.
        expect(calib.overlapsImage([200, 10, 260, 40], 100, 100)).toBe(false);
        expect(calib.overlapsImage([-260, 10, -200, 40], 100, 100)).toBe(false);
        expect(calib.overlapsImage([10, 200, 40, 260], 100, 100)).toBe(false);
    });

    test('a box exactly touching the edge is not drawn', () => {
        expect(calib.overlapsImage([100, 10, 140, 40], 100, 100)).toBe(false);
    });

    test('with no known image size, anything projectable is drawn', () => {
        // The image has not loaded yet. Hiding every box until it does would
        // flash the panel empty on every item.
        expect(calib.overlapsImage([200, 10, 260, 40], null, null)).toBe(true);
        expect(calib.overlapsImage(null, null, null)).toBe(false);
    });
});

describe('projectCuboid on a fully invisible box', () => {
    test('a box behind the camera reports itself invisible', () => {
        // Every corner behind the lens. Without the near-plane cull each of
        // them divides by a negative depth and lands somewhere plausible, so
        // this must be false rather than a wireframe in the wrong place.
        const behind = [];
        for (let i = 0; i < 8; i++) {
            behind.push([(i & 1) ? 1 : -1, (i & 2) ? 1 : -1, -5]);
        }
        const out = calib.projectCuboid(CAM, behind);
        expect(out.visible).toBe(false);
        expect(out.edges).toHaveLength(0);
        expect(out.bbox).toBeNull();
    });
});

describe('the module loads without a DOM', () => {
    test('it exports the pure API and nothing that needs a browser', () => {
        // pc-viewer.js requires this file, and pc-viewer.js is itself loaded
        // in Node by three separate test suites. A stray `document` reference
        // here would break all of them.
        expect(typeof calib.projectPoint).toBe('function');
        expect(typeof calib.NEAR_PLANE).toBe('number');
        expect(calib.BOX_EDGES).toHaveLength(12);
    });
});

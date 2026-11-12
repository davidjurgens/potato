/**
 * Projecting 3D annotations into camera images, in the browser.
 *
 * A deliberate mirror of `potato/media/calibration.py`. The two exist because
 * the same maths is needed on both sides — the server projects for exporters
 * and for KITTI's 2D box column, the browser projects sixty times a second
 * while the annotator drags a box — and a round trip per frame is not an
 * option.
 *
 * `tests/unit/test_calibration_js_python_bridge.py` runs this file in Node and
 * compares it to the Python across a range of poses, so the duplication is
 * checked rather than trusted.
 *
 * ## The near plane is the whole game
 *
 * A point behind the camera has negative depth, and dividing by it yields a
 * perfectly plausible pixel — mirrored through the principal point. Project a
 * box straddling the image plane without handling that and it draws inside out
 * across the frame, which reads as an annotator error rather than a bug. So
 * `projectPoint` returns null behind the camera and `projectSegment` clips at
 * the near plane rather than dropping the edge.
 *
 * Nothing here touches three.js or the DOM, so it is unit-testable; the canvas
 * drawing that uses it lives in pc-viewer.js.
 */
(function (root) {
    'use strict';

    /**
     * Depth below which a point counts as behind the camera.
     *
     * Not zero: a point at z = 1e-9 projects to a coordinate in the millions,
     * which is worse than dropping it because it stretches any bounding box
     * computed from the projection. Must match NEAR_PLANE in calibration.py.
     */
    const NEAR_PLANE = 0.05;

    /** Cuboid edges, indexing `PointCloudAnnotationManager.cuboidCorners`. */
    const BOX_EDGES = [
        [0, 1], [1, 2], [2, 3], [3, 0],
        [4, 5], [5, 6], [6, 7], [7, 4],
        [0, 4], [1, 5], [2, 6], [3, 7],
    ];

    /** A sensor-frame point in the camera's own frame (+Z forward). */
    function toCameraFrame(cam, p) {
        const rt = cam.rt;
        const x = +p[0], y = +p[1], z = +p[2];
        return [
            rt[0] * x + rt[1] * y + rt[2] * z + rt[3],
            rt[4] * x + rt[5] * y + rt[6] * z + rt[7],
            rt[8] * x + rt[9] * y + rt[10] * z + rt[11],
        ];
    }

    /** Pixels for a point already in the camera frame, or null. */
    function projectCameraPoint(cam, pc) {
        // `< NEAR_PLANE`, not `<=`: projectSegment clips to exactly the near
        // plane, so a strict test here rejects every clipped point and
        // silently deletes the one case clipping exists to handle. (NaN fails
        // this comparison and is rejected, which is what we want.)
        if (!(pc[2] >= NEAR_PLANE)) return null;
        let xn = pc[0] / pc[2];
        let yn = pc[1] / pc[2];

        const d = cam.distortion || [0, 0, 0, 0, 0];
        if (d[0] || d[1] || d[2] || d[3] || d[4]) {
            const r2 = xn * xn + yn * yn;
            const radial = 1 + d[0] * r2 + d[1] * r2 * r2 + d[4] * r2 * r2 * r2;
            const xd = xn * radial + 2 * d[2] * xn * yn
                + d[3] * (r2 + 2 * xn * xn);
            const yd = yn * radial + d[2] * (r2 + 2 * yn * yn)
                + 2 * d[3] * xn * yn;
            xn = xd;
            yn = yd;
        }

        const k = cam.k;
        return [k[0] * xn + k[1] * yn + k[2], k[3] * xn + k[4] * yn + k[5]];
    }

    /** Pixels for a sensor-frame point, or null behind the camera. */
    function projectPoint(cam, p) {
        return projectCameraPoint(cam, toCameraFrame(cam, p));
    }

    /**
     * The visible part of a sensor-frame segment, in pixels, or null.
     *
     * Clipped against the near plane so an edge running from in front of the
     * camera to behind it draws up to the plane instead of wrapping.
     */
    function projectSegment(cam, a, b) {
        let pa = toCameraFrame(cam, a);
        let pb = toCameraFrame(cam, b);
        const za = pa[2], zb = pb[2];

        if (za < NEAR_PLANE && zb < NEAR_PLANE) return null;
        if (za < NEAR_PLANE || zb < NEAR_PLANE) {
            const t = (NEAR_PLANE - za) / (zb - za);
            const cut = [pa[0] + (pb[0] - pa[0]) * t,
                         pa[1] + (pb[1] - pa[1]) * t,
                         NEAR_PLANE];
            if (za < NEAR_PLANE) pa = cut; else pb = cut;
        }

        const ua = projectCameraPoint(cam, pa);
        const ub = projectCameraPoint(cam, pb);
        if (!ua || !ub) return null;
        return [ua, ub];
    }

    /**
     * A cuboid as drawable 2D geometry: `{edges, bbox, visible}`.
     *
     * `corners` is the eight-corner array `cuboidCorners` produces, so the
     * wireframe drawn on the photograph is the same wireframe drawn in the
     * viewport rather than a second interpretation of the same box.
     */
    function projectCuboid(cam, corners) {
        const edges = [];
        BOX_EDGES.forEach(function (pair) {
            const seg = projectSegment(cam, corners[pair[0]], corners[pair[1]]);
            if (seg) edges.push(seg);
        });

        const front = [];
        corners.forEach(function (c) {
            const uv = projectPoint(cam, c);
            if (uv) front.push(uv);
        });

        let bbox = null;
        if (front.length) {
            const xs = front.map(function (p) { return p[0]; });
            const ys = front.map(function (p) { return p[1]; });
            bbox = [Math.min.apply(null, xs), Math.min.apply(null, ys),
                    Math.max.apply(null, xs), Math.max.apply(null, ys)];
        }
        return { edges: edges, bbox: bbox, visible: edges.length > 0 };
    }

    /**
     * Whether a projected box is worth drawing in this panel.
     *
     * A box entirely off to one side still produces valid pixels, and drawing
     * it puts lines along the panel edge for objects the camera never saw —
     * which makes the verification view actively misleading, since the point
     * of it is "does the box sit on the object in this image".
     */
    function overlapsImage(bbox, width, height) {
        if (!bbox || !width || !height) return Boolean(bbox);
        return bbox[2] > 0 && bbox[0] < width
            && bbox[3] > 0 && bbox[1] < height;
    }

    const api = {
        NEAR_PLANE: NEAR_PLANE,
        BOX_EDGES: BOX_EDGES,
        toCameraFrame: toCameraFrame,
        projectPoint: projectPoint,
        projectSegment: projectSegment,
        projectCuboid: projectCuboid,
        overlapsImage: overlapsImage,
    };

    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (root) root.PointCloudCalibration = api;
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));

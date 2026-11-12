/**
 * Multi-planar reconstruction: three orthographic slabs through the cloud.
 *
 * ## Why a perspective view is not enough
 *
 * Placing an oriented box by eye in a perspective view of a sparse cloud is
 * guesswork, and it is guesswork in a specific direction: the extent along the
 * view axis is the one the projection compresses, so boxes come out
 * systematically short in depth and the error is invisible from the camera that
 * drew them. Every production 3D labelling tool answers this the same way —
 * axis-aligned slabs, where a metre is a metre in both directions on screen.
 *
 * Three panels: **top** (looking down −Z, showing X-Y), **front** (looking
 * along +X, showing Y-Z) and **side** (looking along +Y, showing X-Z). Each
 * shows only the points within a slab of configurable thickness centred on the
 * focus, so a box's own returns are not buried under everything in front of and
 * behind it.
 *
 * ## What is in here and what is not
 *
 * Everything in this file is arithmetic on plain numbers — no three.js, no
 * canvas — so it is unit-tested rather than eyeballed. The rendering and the
 * pointer handling live in `pc-viewer.js`, which owns the DOM.
 *
 * Coordinates are absolute metres in the sensor frame, as everywhere else in
 * the 3D path. See `potato/export/spatial_utils.py`.
 */
(function (root) {
    'use strict';

    /**
     * The three planes.
     *
     * `u` and `v` are the world axes mapped to the panel's horizontal and
     * vertical screen axes; `normal` is the axis the slab is measured along.
     * `flipV` is set where the natural world direction runs opposite to the
     * screen's downward Y — without it the top view is mirrored north-to-south
     * and every box you drag moves the wrong way.
     */
    const PLANES = {
        top:   { label: 'Top (X-Y)',   u: 0, v: 1, normal: 2, flipV: true },
        front: { label: 'Front (Y-Z)', u: 1, v: 2, normal: 0, flipV: true },
        side:  { label: 'Side (X-Z)',  u: 0, v: 2, normal: 1, flipV: true },
    };

    const PLANE_ORDER = ['top', 'front', 'side'];

    /** Default slab thickness in metres. A car is 1.8 m wide; 2 m clears one. */
    const DEFAULT_SLAB = 2.0;

    /** Pointer slop, in pixels, for grabbing an edge rather than the interior. */
    const HANDLE_TOLERANCE = 7;

    /**
     * A panel's world-to-screen mapping.
     *
     * `extent` is the half-width of the world region shown, in metres, on the
     * **longer** screen axis; the shorter axis shows proportionally less, so
     * the scale is identical in u and v. Anisotropic scaling would make a
     * square box render as a rectangle, which is the one thing a slab view
     * exists to rule out.
     */
    function makeView(plane, center, extent, width, height) {
        const spec = PLANES[plane];
        if (!spec) throw new Error(`unknown plane "${plane}"`);
        const scale = Math.min(width, height) / (2 * Math.max(extent, 1e-6));
        return {
            plane, spec, center: center.slice(), extent,
            width, height, scale,
        };
    }

    /** World point -> panel pixel. */
    function worldToPanel(view, point) {
        const { spec, center, scale, width, height } = view;
        const du = point[spec.u] - center[spec.u];
        const dv = point[spec.v] - center[spec.v];
        return {
            x: width / 2 + du * scale,
            y: height / 2 + (spec.flipV ? -dv : dv) * scale,
        };
    }

    /**
     * Panel pixel -> world point, on the slab's centre plane.
     *
     * The inverse of `worldToPanel` for the two in-plane axes; the third takes
     * the slab centre, because a click on a 2D panel says nothing about it.
     */
    function panelToWorld(view, x, y) {
        const { spec, center, scale, width, height } = view;
        const out = center.slice();
        out[spec.u] = center[spec.u] + (x - width / 2) / scale;
        const dv = (y - height / 2) / scale;
        out[spec.v] = center[spec.v] + (spec.flipV ? -dv : dv);
        return out;
    }

    /**
     * Indices of the points inside the slab.
     *
     * Returns indices rather than a filtered copy: a slab of a two-million
     * point cloud is still hundreds of thousands of points, and copying them
     * per panel per frame is the difference between a responsive panel and a
     * stuttering one.
     */
    function slabIndices(positions, view, thickness, stride) {
        const axis = view.spec.normal;
        const lo = view.center[axis] - thickness / 2;
        const hi = view.center[axis] + thickness / 2;
        const step = Math.max(1, stride | 0);
        const out = [];
        const count = Math.floor(positions.length / 3);
        for (let i = 0; i < count; i += step) {
            const v = positions[i * 3 + axis];
            if (v >= lo && v <= hi) out.push(i);
        }
        return out;
    }

    /**
     * The axis-aligned footprint of a cuboid in a panel, in world units.
     *
     * Yaw is honoured by taking the extent of the rotated corners rather than
     * the raw size, so a box turned 45 degrees reads as its true width on
     * screen instead of its nominal one. The drag handles then operate on that
     * envelope, which is what makes resizing a rotated box behave predictably:
     * you are adjusting how much of the world it covers, not editing a number
     * in a frame you cannot see.
     */
    function boxEnvelope(view, coords) {
        const corners = cuboidCorners(coords);
        const spec = view.spec;
        let uMin = Infinity, uMax = -Infinity, vMin = Infinity, vMax = -Infinity;
        corners.forEach((c) => {
            uMin = Math.min(uMin, c[spec.u]);
            uMax = Math.max(uMax, c[spec.u]);
            vMin = Math.min(vMin, c[spec.v]);
            vMax = Math.max(vMax, c[spec.v]);
        });
        return { uMin, uMax, vMin, vMax };
    }

    /** Eight corners of a cuboid in world coordinates. */
    function cuboidCorners(coords) {
        const c = coords.center;
        const s = coords.size;
        const q = coords.rotation || [0, 0, 0, 1];
        const out = [];
        for (let i = 0; i < 8; i++) {
            const local = [
                ((i & 1) ? 0.5 : -0.5) * s[0],
                ((i & 2) ? 0.5 : -0.5) * s[1],
                ((i & 4) ? 0.5 : -0.5) * s[2],
            ];
            const r = rotateByQuat(local, q);
            out.push([c[0] + r[0], c[1] + r[1], c[2] + r[2]]);
        }
        return out;
    }

    /** v' = q v q*, expanded. */
    function rotateByQuat(v, q) {
        const [x, y, z, w] = q;
        const tx = 2 * (y * v[2] - z * v[1]);
        const ty = 2 * (z * v[0] - x * v[2]);
        const tz = 2 * (x * v[1] - y * v[0]);
        return [
            v[0] + w * tx + (y * tz - z * ty),
            v[1] + w * ty + (z * tx - x * tz),
            v[2] + w * tz + (x * ty - y * tx),
        ];
    }

    /**
     * Which part of the box's envelope the pointer is over.
     *
     * Returns one of `'u-min'`, `'u-max'`, `'v-min'`, `'v-max'`, `'move'`, or
     * null. Edges win over the interior so that a box filling the panel can
     * still be resized — the opposite priority makes a large box impossible to
     * shrink, which is a real trap in slab editors.
     */
    function handleAt(view, coords, x, y, tolerance) {
        const tol = tolerance === undefined ? HANDLE_TOLERANCE : tolerance;
        const env = boxEnvelope(view, coords);
        const spec = view.spec;

        const lo = worldToPanel(view, pointOn(view, env.uMin, env.vMin));
        const hi = worldToPanel(view, pointOn(view, env.uMax, env.vMax));
        const left = Math.min(lo.x, hi.x);
        const right = Math.max(lo.x, hi.x);
        const top = Math.min(lo.y, hi.y);
        const bottom = Math.max(lo.y, hi.y);

        const insideY = y >= top - tol && y <= bottom + tol;
        const insideX = x >= left - tol && x <= right + tol;
        if (!insideX || !insideY) return null;

        // The horizontal axis is never flipped, so screen-left is world-min.
        if (Math.abs(x - left) <= tol) return 'u-min';
        if (Math.abs(x - right) <= tol) return 'u-max';
        // The screen's top edge is the world's MAXIMUM on a flipped axis.
        if (Math.abs(y - top) <= tol) return spec.flipV ? 'v-max' : 'v-min';
        if (Math.abs(y - bottom) <= tol) return spec.flipV ? 'v-min' : 'v-max';

        if (x > left && x < right && y > top && y < bottom) return 'move';
        return null;
    }

    function pointOn(view, u, v) {
        const out = view.center.slice();
        out[view.spec.u] = u;
        out[view.spec.v] = v;
        return out;
    }

    /**
     * Apply a drag to a cuboid, returning new coordinates.
     *
     * `handle` comes from :func:`handleAt`; `world` is the pointer's position
     * in world metres. Edge drags move **one** face and leave the opposite one
     * fixed — the whole point of a slab view is adjusting one boundary against
     * the returns behind it, and a symmetric resize would move the far face
     * away from wherever the annotator had just aligned it.
     *
     * Returns the input unchanged for a degenerate result rather than
     * producing a zero- or negative-size box.
     */
    function applyDrag(view, coords, handle, world, offset) {
        const spec = view.spec;
        const next = {
            center: coords.center.slice(),
            size: coords.size.slice(),
            rotation: (coords.rotation || [0, 0, 0, 1]).slice(),
        };

        if (handle === 'move') {
            const shift = offset || [0, 0, 0];
            next.center[spec.u] = world[spec.u] - shift[spec.u];
            next.center[spec.v] = world[spec.v] - shift[spec.v];
            return next;
        }

        const axis = handle.startsWith('u-') ? spec.u : spec.v;
        const env = boxEnvelope(view, coords);
        const isMin = handle.endsWith('-min');
        const lo = handle.startsWith('u-') ? env.uMin : env.vMin;
        const hi = handle.startsWith('u-') ? env.uMax : env.vMax;

        const newLo = isMin ? world[axis] : lo;
        const newHi = isMin ? hi : world[axis];
        const span = newHi - newLo;
        // 5 cm: below this it is a mis-grab, not a resize. A box thinner than
        // that is not something an annotator means to draw, and letting it
        // through produces annotations that export as degenerate geometry.
        if (!(span > 0.05)) return coords;

        // The envelope is the ROTATED extent, so scaling the nominal size by
        // the envelope's ratio keeps a yawed box consistent with what the
        // panel is showing. For an unrotated box the ratio is exactly 1.
        const oldSpan = hi - lo;
        const ratio = oldSpan > 1e-9 ? span / oldSpan : 1;
        const sizeAxis = axisToSizeIndex(axis, coords.rotation);
        next.size[sizeAxis] = Math.max(0.05, coords.size[sizeAxis] * ratio);
        next.center[axis] = (newLo + newHi) / 2;
        return next;
    }

    /**
     * Which of the box's own size components a world axis corresponds to.
     *
     * For an unrotated or yaw-only box this is the identity for Z and the
     * nearest of X/Y for the horizontal axes. Anything more general would need
     * the box's full frame, and editing a tilted box through an axis-aligned
     * envelope is ambiguous by construction — so the mapping is the honest
     * approximation and the perspective view remains the way to adjust a
     * rotated box precisely.
     */
    function axisToSizeIndex(axis, rotation) {
        if (axis === 2) return 2;
        const q = rotation || [0, 0, 0, 1];
        const yaw = 2 * Math.atan2(q[2], q[3]);
        const quarter = Math.round(yaw / (Math.PI / 2)) & 1;
        if (!quarter) return axis;
        return axis === 0 ? 1 : 0;
    }

    /**
     * Where the slab should sit.
     *
     * On the selected box when there is one — that is the thing being edited,
     * and centring anywhere else means its returns are outside the slab. On
     * the camera target otherwise.
     */
    function focusPoint(selection, fallback) {
        if (selection && selection.coordinates && selection.coordinates.center) {
            return selection.coordinates.center.slice();
        }
        if (selection && Array.isArray(selection.coordinates)) {
            return selection.coordinates.slice(0, 3);
        }
        return (fallback || [0, 0, 0]).slice();
    }

    /**
     * A sensible extent for a panel, in metres.
     *
     * Sized to the selected box with room around it, so selecting a
     * pedestrian does not leave them four pixels wide inside a view framed for
     * the whole street.
     */
    function extentFor(selection, fallback) {
        if (selection && selection.coordinates && selection.coordinates.size) {
            const s = selection.coordinates.size;
            return Math.max(2.0, Math.max(s[0], s[1], s[2]) * 1.8);
        }
        return fallback || 20;
    }

    const api = {
        PLANES, PLANE_ORDER, DEFAULT_SLAB, HANDLE_TOLERANCE,
        makeView, worldToPanel, panelToWorld, slabIndices,
        boxEnvelope, cuboidCorners, handleAt, applyDrag,
        focusPoint, extentFor, axisToSizeIndex,
    };

    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (root) root.PointCloudMPR = api;
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));

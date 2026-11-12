/**
 * Per-point painting for `segment_3d` — the parts with no three.js in them.
 *
 * Same split as pc-wire.js: what decides which points a stroke labels, and
 * what the stored segments look like afterwards, is arithmetic that can be
 * wrong without anything looking wrong on screen. Kept here so the Jest suite
 * covers it; pc-viewer.js only feeds it buffers and a camera matrix.
 *
 * The storage contract is unchanged (see potato/export/spatial_utils.py):
 *
 *     {"type": "segment_3d", "label", "color", "indices": [source index, ...]}
 *
 * one object per label, indices into the source file. A point carries at most
 * one label: painting it moves it, erasing removes it.
 */
(function (root) {
    'use strict';

    /**
     * Screen position of every point, in CSS pixels from the canvas's top left.
     *
     * `m` is the 16 column-major elements of projection * view, as three.js
     * stores `Matrix4.elements`. A point behind the camera or outside the
     * near/far range gets NaN, so no hit test can select it: a brush stroke on
     * the road must not label the points behind the viewer.
     */
    function projectPoints(positions, count, m, width, height, out) {
        const screen = out && out.length >= count * 2 ? out : new Float32Array(count * 2);
        for (let i = 0; i < count; i++) {
            const x = positions[i * 3];
            const y = positions[i * 3 + 1];
            const z = positions[i * 3 + 2];
            const w = m[3] * x + m[7] * y + m[11] * z + m[15];
            if (!(w > 0)) {
                screen[i * 2] = NaN;
                screen[i * 2 + 1] = NaN;
                continue;
            }
            const nz = (m[2] * x + m[6] * y + m[10] * z + m[14]) / w;
            if (nz < -1 || nz > 1) {
                screen[i * 2] = NaN;
                screen[i * 2 + 1] = NaN;
                continue;
            }
            const nx = (m[0] * x + m[4] * y + m[8] * z + m[12]) / w;
            const ny = (m[1] * x + m[5] * y + m[9] * z + m[13]) / w;
            screen[i * 2] = (nx + 1) / 2 * width;
            screen[i * 2 + 1] = (1 - ny) / 2 * height;
        }
        return screen;
    }

    /**
     * Buffer indices within `radius` of the segment (x0, y0)-(x1, y1).
     *
     * A segment rather than a point because mousemove events are sparse: a
     * fast stroke moves the cursor several radii between two events, and
     * testing only the event positions leaves unpainted gaps along the line.
     */
    function brushHits(screen, count, x0, y0, x1, y1, radius, accept) {
        const hits = [];
        const r2 = radius * radius;
        const dx = x1 - x0;
        const dy = y1 - y0;
        const len2 = dx * dx + dy * dy;
        const minX = Math.min(x0, x1) - radius;
        const maxX = Math.max(x0, x1) + radius;
        const minY = Math.min(y0, y1) - radius;
        const maxY = Math.max(y0, y1) + radius;
        for (let i = 0; i < count; i++) {
            const px = screen[i * 2];
            const py = screen[i * 2 + 1];
            // NaN fails every comparison, so off-screen points drop out here.
            if (!(px >= minX && px <= maxX && py >= minY && py <= maxY)) continue;
            let t = len2 > 0 ? ((px - x0) * dx + (py - y0) * dy) / len2 : 0;
            t = t < 0 ? 0 : (t > 1 ? 1 : t);
            const ex = px - (x0 + t * dx);
            const ey = py - (y0 + t * dy);
            if (ex * ex + ey * ey > r2) continue;
            if (accept && !accept(i)) continue;
            hits.push(i);
        }
        return hits;
    }

    /** Even-odd test; `polygon` is [[x, y], ...]. */
    function insidePolygon(px, py, polygon) {
        let inside = false;
        for (let a = 0, b = polygon.length - 1; a < polygon.length; b = a++) {
            const ax = polygon[a][0];
            const ay = polygon[a][1];
            const bx = polygon[b][0];
            const by = polygon[b][1];
            if ((ay > py) !== (by > py)
                    && px < (bx - ax) * (py - ay) / (by - ay) + ax) {
                inside = !inside;
            }
        }
        return inside;
    }

    /** Buffer indices whose screen position falls inside the lasso. */
    function lassoHits(screen, count, polygon, accept) {
        if (!Array.isArray(polygon) || polygon.length < 3) return [];
        let minX = Infinity;
        let maxX = -Infinity;
        let minY = Infinity;
        let maxY = -Infinity;
        polygon.forEach(([x, y]) => {
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
        });
        const hits = [];
        for (let i = 0; i < count; i++) {
            const px = screen[i * 2];
            const py = screen[i * 2 + 1];
            if (!(px >= minX && px <= maxX && py >= minY && py <= maxY)) continue;
            if (!insidePolygon(px, py, polygon)) continue;
            if (accept && !accept(i)) continue;
            hits.push(i);
        }
        return hits;
    }

    /**
     * Source index -> label, from the segments in `annotations`.
     *
     * A later segment wins over an earlier one. Data written before painting
     * enforced one label per point can hold a point in two segments; the
     * viewer shows it in the colour drawn last, and the next edit stores it
     * under that label alone.
     */
    function labelsByPoint(annotations) {
        const map = new Map();
        (annotations || []).forEach((obj) => {
            if (!obj || obj.type !== 'segment_3d' || !Array.isArray(obj.indices)) return;
            obj.indices.forEach((raw) => {
                const i = Number(raw);
                if (Number.isInteger(i) && i >= 0) map.set(i, obj.label);
            });
        });
        return map;
    }

    /**
     * Give each source index `label`, or unlabel it when `label` is null.
     * Returns how many points changed.
     */
    function paint(map, sourceIndices, label) {
        let changed = 0;
        sourceIndices.forEach((i) => {
            if (label === null || label === undefined) {
                if (map.delete(i)) changed += 1;
            } else if (map.get(i) !== label) {
                map.set(i, label);
                changed += 1;
            }
        });
        return changed;
    }

    function sameIndices(a, b) {
        if (!Array.isArray(a) || a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++) {
            if (Number(a[i]) !== b[i]) return false;
        }
        return true;
    }

    /**
     * The annotation list with its segments rewritten from `map`.
     *
     * Everything that is not a segment keeps its place. An existing segment
     * keeps its place and its other fields (source, track_id, attributes) and
     * takes its label's indices, sorted; it is returned as the same object when
     * they did not change, so a selection pointing at it stays valid. A second
     * segment with the same label is merged into the first, a segment left with
     * no points is dropped, and a label with no segment yet gets a new one,
     * appended in `labelOrder`.
     */
    function segmentsFrom(annotations, map, colorFor, labelOrder) {
        const groups = new Map();
        map.forEach((label, index) => {
            if (!groups.has(label)) groups.set(label, []);
            groups.get(label).push(index);
        });
        groups.forEach((list) => list.sort((a, b) => a - b));

        const out = [];
        const placed = new Set();
        (annotations || []).forEach((obj) => {
            if (!obj || obj.type !== 'segment_3d') {
                out.push(obj);
                return;
            }
            if (placed.has(obj.label)) return;
            const indices = groups.get(obj.label);
            if (!indices || !indices.length) return;
            placed.add(obj.label);
            if (sameIndices(obj.indices, indices)) {
                out.push(obj);
                return;
            }
            const next = Object.assign({}, obj, { indices });
            // A model's segmentation a person repainted is not the model's
            // answer any more, as with a moved box.
            if (obj.source && obj.source !== 'human') next.edited = true;
            out.push(next);
        });

        const order = (labelOrder || []).filter((l) => groups.has(l));
        groups.forEach((list, label) => { if (order.indexOf(label) < 0) order.push(label); });
        order.forEach((label) => {
            if (placed.has(label)) return;
            out.push({
                type: 'segment_3d',
                label,
                color: colorFor ? colorFor(label) : undefined,
                indices: groups.get(label),
            });
        });
        return out;
    }

    /**
     * Write each point's display colour into `out`: its label's colour when it
     * has one, the cloud's own colour (`base`) otherwise.
     *
     * `rgbFor(label)` returns {r, g, b} in the renderer's colour space, or
     * null for a label with no colour, which leaves the point as it was.
     */
    function paintColors(out, base, count, indices, map, rgbFor) {
        for (let i = 0; i < count; i++) {
            const src = indices ? indices[i] : i;
            const label = map.size ? map.get(src) : undefined;
            const rgb = label !== undefined ? rgbFor(label) : null;
            if (rgb) {
                out[i * 3] = rgb.r;
                out[i * 3 + 1] = rgb.g;
                out[i * 3 + 2] = rgb.b;
            } else {
                out[i * 3] = base[i * 3];
                out[i * 3 + 1] = base[i * 3 + 1];
                out[i * 3 + 2] = base[i * 3 + 2];
            }
        }
        return out;
    }

    /**
     * The buffer indices to draw when some labels are hidden, or null when
     * every point is drawn. Unlabelled points are always drawn.
     */
    function visibleIndex(count, indices, map, hidden) {
        if (!hidden || !hidden.size || !map.size) return null;
        const keep = [];
        for (let i = 0; i < count; i++) {
            const label = map.get(indices ? indices[i] : i);
            if (label === undefined || !hidden.has(label)) keep.push(i);
        }
        return keep.length === count ? null : Uint32Array.from(keep);
    }

    const api = {
        projectPoints, brushHits, lassoHits, insidePolygon,
        labelsByPoint, paint, segmentsFrom, paintColors, visibleIndex,
    };

    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (root) root.PointCloudPaint = api;
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));

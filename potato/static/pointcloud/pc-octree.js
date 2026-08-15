/**
 * Octree traversal for level-of-detail point clouds — the arithmetic half.
 *
 * Split from the renderer for the same reason `pc-wire.js` is: this is where
 * being silently wrong is possible (a frustum test with a flipped sign hides a
 * third of the scene and looks like sparse data), and it can only be tested if
 * it does not need a WebGL context. Nothing here imports three.js; the caller
 * passes plain numbers and gets back a list of node keys.
 *
 * The structure is produced by `potato/media/octree.py`. Its key property:
 * levels are **additive**, so the union of the nodes selected here is a
 * uniform-density sampling of the scene rather than a scene with holes. That is
 * what makes a partially-loaded cloud safe to annotate on — it looks coarse,
 * not incomplete.
 */
(function (root) {
    'use strict';

    /** Points held in memory at once, across all loaded nodes. */
    const DEFAULT_POINT_BUDGET = 2000000;

    /**
     * A node smaller than this on screen is not worth a request.
     *
     * In pixels of projected bounding-sphere diameter. 120 is deliberately
     * generous: the cost of loading one node too many is a fetch, and the cost
     * of loading one too few is an annotator drawing a box around a gap.
     */
    const DEFAULT_MIN_SCREEN_SIZE = 120;

    class OctreeIndex {
        /**
         * @param {object} manifest as served by `?lod=1` — see
         *   `manifest_for_client` in the Python module.
         */
        constructor(manifest) {
            this.manifest = manifest || {};
            this.nodes = new Map();
            (this.manifest.nodes || []).forEach((n) => {
                this.nodes.set(n.key, {
                    key: n.key,
                    level: n.level | 0,
                    bounds: n.bounds,
                    count: n.count | 0,
                    children: n.children || [],
                    // Precomputed: the traversal runs on every camera move and
                    // recomputing a centre from bounds per node per frame is
                    // the kind of cost that only shows up on a big scene.
                    center: centerOf(n.bounds),
                    radius: radiusOf(n.bounds),
                });
            });
            this.root = this.nodes.get('r') || null;
        }

        get totalCount() { return this.manifest.total_count | 0; }
        get depth() { return this.manifest.depth | 0; }
        get bounds() { return this.manifest.bounds || null; }
        get truncated() { return !!this.manifest.truncated; }

        /**
         * Which nodes should be loaded for this view.
         *
         * @param {object} view
         *   - position: camera position [x, y, z]
         *   - planes: six frustum planes [a, b, c, d], normals pointing INWARD
         *     (so a point is inside when a*x + b*y + c*z + d >= 0). Omit to
         *     disable culling, which is what an orthographic slab view wants.
         *   - fovRadians, viewportHeight: for the projected-size metric
         *   - pointBudget, minScreenSize: optional overrides
         * @returns {{keys: string[], points: number, budgetHit: boolean,
         *            culled: number}}
         */
        select(view) {
            const out = { keys: [], points: 0, budgetHit: false, culled: 0 };
            if (!this.root) return out;

            const budget = view.pointBudget || DEFAULT_POINT_BUDGET;
            const minSize = view.minScreenSize === undefined
                ? DEFAULT_MIN_SCREEN_SIZE : view.minScreenSize;
            const scale = projectionScale(view);

            // Highest projected size first, so when the budget runs out it is
            // the far-away nodes that are dropped rather than whichever ones
            // happened to be last in the manifest.
            const queue = [{ node: this.root, size: Infinity }];
            const seen = new Set();

            while (queue.length) {
                queue.sort((a, b) => b.size - a.size);
                const { node } = queue.shift();
                if (seen.has(node.key)) continue;
                seen.add(node.key);

                if (out.points + node.count > budget) {
                    // Not `break`: a large node can be skipped while smaller
                    // ones behind it still fit, and dropping the rest of the
                    // queue would blank the far half of the scene.
                    out.budgetHit = true;
                    continue;
                }

                out.keys.push(node.key);
                out.points += node.count;

                node.children.forEach((key) => {
                    const child = this.nodes.get(key);
                    if (!child) return;
                    if (view.planes && !intersectsFrustum(child, view.planes)) {
                        out.culled += 1;
                        return;
                    }
                    const size = screenSize(child, view.position, scale);
                    if (size < minSize) return;
                    queue.push({ node: child, size });
                });
            }
            return out;
        }

        /** Every node key, coarsest first. For "load it all" on small clouds. */
        allKeys() {
            return Array.from(this.nodes.values())
                .sort((a, b) => a.level - b.level || (a.key < b.key ? -1 : 1))
                .map((n) => n.key);
        }
    }

    /**
     * Pixels per unit of world size at unit distance.
     *
     * `viewportHeight / (2 * tan(fov / 2))` is the pinhole relation: a sphere
     * of radius r at distance d subtends `2 * r * scale / d` pixels.
     */
    function projectionScale(view) {
        const fov = view.fovRadians || (55 * Math.PI / 180);
        const height = view.viewportHeight || 600;
        return height / (2 * Math.tan(fov / 2));
    }

    function screenSize(node, cameraPos, scale) {
        const dx = node.center[0] - cameraPos[0];
        const dy = node.center[1] - cameraPos[1];
        const dz = node.center[2] - cameraPos[2];
        const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
        // Inside the node's own sphere the projection diverges; treating that
        // as "infinitely important" is correct — the camera is in it.
        if (distance <= node.radius) return Infinity;
        return (2 * node.radius * scale) / distance;
    }

    /**
     * Conservative box-vs-frustum test.
     *
     * Tests only the corner furthest along each plane's normal (the "positive
     * vertex"). If that corner is behind the plane, every corner is, and the
     * box is outside. Checking all eight corners would give the same answer for
     * eight times the work; checking the centre only would cull boxes that
     * straddle a plane, which is the failure that looks like missing data.
     */
    function intersectsFrustum(node, planes) {
        const [lo, hi] = node.bounds;
        for (let i = 0; i < planes.length; i++) {
            const p = planes[i];
            const x = p[0] >= 0 ? hi[0] : lo[0];
            const y = p[1] >= 0 ? hi[1] : lo[1];
            const z = p[2] >= 0 ? hi[2] : lo[2];
            if (p[0] * x + p[1] * y + p[2] * z + p[3] < 0) return false;
        }
        return true;
    }

    function centerOf(bounds) {
        const [lo, hi] = bounds;
        return [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
    }

    function radiusOf(bounds) {
        const [lo, hi] = bounds;
        const dx = hi[0] - lo[0], dy = hi[1] - lo[1], dz = hi[2] - lo[2];
        return Math.sqrt(dx * dx + dy * dy + dz * dz) / 2;
    }

    /**
     * Keys to evict, least-recently-visible first.
     *
     * Eviction is by node count rather than by point count because the cost
     * being controlled is GPU buffers, and a buffer's overhead is per-object.
     * Never evicts a node in `keep`: dropping something the current frame needs
     * would make it reload immediately, which is a request loop, not a cache.
     */
    function evictionOrder(loadedKeys, lastSeen, keep, maxLoaded) {
        const kept = new Set(keep || []);
        const candidates = loadedKeys.filter((k) => !kept.has(k));
        const excess = loadedKeys.length - (maxLoaded || 512);
        if (excess <= 0) return [];
        candidates.sort((a, b) => (lastSeen[a] || 0) - (lastSeen[b] || 0));
        return candidates.slice(0, Math.min(excess, candidates.length));
    }

    /**
     * What to say about a partially loaded cloud.
     *
     * The non-LOD viewer says "showing N of M points"; saying nothing here
     * would leave an annotator believing a coarse root node is the whole scan.
     */
    function describeLod(index, selection) {
        const total = index.totalCount;
        const shown = selection.points | 0;
        if (!total) return '';
        if (shown >= total) {
            return `${total.toLocaleString()} points, all loaded.`;
        }
        const detail = selection.budgetHit
            ? ' Detail is capped by the point budget; zoom in for more.'
            : ' More detail loads as you zoom in.';
        return `Showing ${shown.toLocaleString()} of `
            + `${total.toLocaleString()} points.${detail}`;
    }

    const api = {
        OctreeIndex, evictionOrder, describeLod,
        intersectsFrustum, screenSize, projectionScale,
        DEFAULT_POINT_BUDGET, DEFAULT_MIN_SCREEN_SIZE,
    };

    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (root) root.PointCloudOctree = api;
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));

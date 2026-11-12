/**
 * Octree traversal: frustum culling, the screen-size metric, and the budget.
 *
 * These are the parts that fail silently. A flipped sign in the frustum test
 * culls the half of the scene you are looking at, and the viewer renders that
 * as sparse data rather than as an error — so each direction is asserted
 * separately, with a control that proves the test could have gone the other
 * way.
 */

const octree = require('../../potato/static/pointcloud/pc-octree.js');

/** A three-level manifest: root, eight children, and one grandchild branch. */
function manifest() {
    const nodes = [
        { key: 'r', level: 0, count: 1000,
          bounds: [[-10, -10, -10], [10, 10, 10]],
          children: ['r0', 'r7'] },
        // r0 is the -x -y -z octant, r7 is +x +y +z.
        { key: 'r0', level: 1, count: 2000,
          bounds: [[-10, -10, -10], [0, 0, 0]], children: ['r00'] },
        { key: 'r7', level: 1, count: 3000,
          bounds: [[0, 0, 0], [10, 10, 10]], children: [] },
        { key: 'r00', level: 2, count: 4000,
          bounds: [[-10, -10, -10], [-5, -5, -5]], children: [] },
    ];
    return { version: 1, total_count: 10000, depth: 2, spacing: 0.5,
             bounds: [[-10, -10, -10], [10, 10, 10]], nodes };
}

describe('OctreeIndex', () => {
    test('indexes every node and finds the root', () => {
        const index = new octree.OctreeIndex(manifest());
        expect(index.nodes.size).toBe(4);
        expect(index.root.key).toBe('r');
        expect(index.totalCount).toBe(10000);
        expect(index.depth).toBe(2);
    });

    test('an empty manifest selects nothing rather than throwing', () => {
        const index = new octree.OctreeIndex({ nodes: [] });
        expect(index.root).toBeNull();
        expect(index.select({ position: [0, 0, 0] }).keys).toEqual([]);
    });

    test('allKeys is coarsest first, so a small cloud loads usefully', () => {
        const index = new octree.OctreeIndex(manifest());
        expect(index.allKeys()[0]).toBe('r');
    });
});

describe('selection by projected size', () => {
    test('a close camera descends, a distant one does not', () => {
        const index = new octree.OctreeIndex(manifest());
        const near = index.select({
            position: [0, 0, 12], fovRadians: 1.0, viewportHeight: 800,
            minScreenSize: 100 });
        const far = index.select({
            position: [0, 0, 4000], fovRadians: 1.0, viewportHeight: 800,
            minScreenSize: 100 });

        expect(near.keys.length).toBeGreaterThan(far.keys.length);
        expect(far.keys).toEqual(['r']);
    });

    test('a lower threshold loads more nodes', () => {
        const index = new octree.OctreeIndex(manifest());
        const view = { position: [0, 0, 60], fovRadians: 1.0,
                       viewportHeight: 800 };
        const coarse = index.select({ ...view, minScreenSize: 400 });
        const fine = index.select({ ...view, minScreenSize: 10 });
        expect(fine.keys.length).toBeGreaterThan(coarse.keys.length);
    });

    test('a node containing the camera is always worth loading', () => {
        // Inside the sphere the projection diverges; treating that as
        // "unimportant" would empty the view exactly when you zoom in.
        const node = { center: [0, 0, 0], radius: 5 };
        expect(octree.screenSize(node, [1, 1, 1], 500)).toBe(Infinity);
    });

    test('screen size falls with distance', () => {
        const node = { center: [0, 0, 0], radius: 1 };
        const near = octree.screenSize(node, [0, 0, 10], 500);
        const far = octree.screenSize(node, [0, 0, 100], 500);
        expect(near).toBeGreaterThan(far);
        expect(near / far).toBeCloseTo(10, 5);
    });

    test('projectionScale follows the pinhole relation', () => {
        // height / (2 tan(fov/2)): at 90 degrees, tan(45) = 1, so it is h/2.
        expect(octree.projectionScale({
            fovRadians: Math.PI / 2, viewportHeight: 800 })).toBeCloseTo(400, 6);
    });
});

describe('frustum culling', () => {
    // Planes with inward normals: a unit box around the origin extended in +x.
    const insideAll = [
        [1, 0, 0, 100], [-1, 0, 0, 100],
        [0, 1, 0, 100], [0, -1, 0, 100],
        [0, 0, 1, 100], [0, 0, -1, 100],
    ];

    test('a box inside every plane is kept', () => {
        const node = { bounds: [[-1, -1, -1], [1, 1, 1]] };
        expect(octree.intersectsFrustum(node, insideAll)).toBe(true);
    });

    test('a box entirely behind one plane is culled', () => {
        // x >= 5 required; the box spans [-1, 1].
        const planes = [[1, 0, 0, -5]];
        const node = { bounds: [[-1, -1, -1], [1, 1, 1]] };
        expect(octree.intersectsFrustum(node, planes)).toBe(false);
    });

    test('a box straddling a plane is kept, not culled', () => {
        // The failure that looks like missing data: culling on the centre
        // alone would drop this box even though half of it is visible.
        const planes = [[1, 0, 0, 0]];   // keep x >= 0
        const node = { bounds: [[-1, -1, -1], [1, 1, 1]] };
        expect(octree.intersectsFrustum(node, planes)).toBe(true);
    });

    test('culling is applied to children during selection', () => {
        const index = new octree.OctreeIndex(manifest());
        // Keep only x >= 1: r0 spans [-10, 0] and must go; r7 spans [0, 10].
        const planes = [[1, 0, 0, -1]];
        const selection = index.select({
            position: [0, 0, 12], fovRadians: 1.0, viewportHeight: 800,
            minScreenSize: 1, planes });

        expect(selection.keys).toContain('r7');
        expect(selection.keys).not.toContain('r0');
        expect(selection.keys).not.toContain('r00');
        expect(selection.culled).toBeGreaterThan(0);
    });

    test('omitting planes disables culling', () => {
        const index = new octree.OctreeIndex(manifest());
        const selection = index.select({
            position: [0, 0, 12], fovRadians: 1.0, viewportHeight: 800,
            minScreenSize: 1 });
        expect(selection.keys).toContain('r0');
        expect(selection.culled).toBe(0);
    });
});

describe('the point budget', () => {
    test('stops adding once the budget is spent, and says so', () => {
        const index = new octree.OctreeIndex(manifest());
        const selection = index.select({
            position: [0, 0, 12], fovRadians: 1.0, viewportHeight: 800,
            minScreenSize: 1, pointBudget: 3500 });

        expect(selection.points).toBeLessThanOrEqual(3500);
        expect(selection.budgetHit).toBe(true);
    });

    test('a node that does not fit does not block smaller ones behind it', () => {
        // `continue`, not `break`: dropping the rest of the queue would blank
        // the far half of the scene the moment one large node overflowed.
        const index = new octree.OctreeIndex(manifest());
        const selection = index.select({
            position: [0, 0, 12], fovRadians: 1.0, viewportHeight: 800,
            minScreenSize: 1, pointBudget: 3500 });
        // Root (1000) fits; r00 (4000) never does; r0 (2000) still should.
        expect(selection.keys).toContain('r');
        expect(selection.keys).not.toContain('r00');
        expect(selection.keys.length).toBeGreaterThan(1);
    });

    test('a generous budget loads everything reachable', () => {
        const index = new octree.OctreeIndex(manifest());
        const selection = index.select({
            position: [0, 0, 12], fovRadians: 1.0, viewportHeight: 800,
            minScreenSize: 1, pointBudget: 1e9 });
        expect(selection.budgetHit).toBe(false);
        expect(selection.points).toBe(10000);
    });
});

describe('eviction', () => {
    test('drops the least recently seen first', () => {
        const loaded = ['a', 'b', 'c', 'd'];
        const lastSeen = { a: 1, b: 9, c: 2, d: 8 };
        const out = octree.evictionOrder(loaded, lastSeen, [], 2);
        expect(out).toEqual(['a', 'c']);
    });

    test('never evicts something the current frame needs', () => {
        // Evicting a visible node makes it reload immediately: a request loop,
        // not a cache.
        const loaded = ['a', 'b', 'c', 'd'];
        const lastSeen = { a: 1, b: 9, c: 2, d: 8 };
        const out = octree.evictionOrder(loaded, lastSeen, ['a', 'c'], 2);
        expect(out).not.toContain('a');
        expect(out).not.toContain('c');
    });

    test('evicts nothing while under the cap', () => {
        expect(octree.evictionOrder(['a', 'b'], { a: 1, b: 2 }, [], 10))
            .toEqual([]);
    });
});

describe('describeLod', () => {
    test('says how much of the cloud is on screen', () => {
        const index = new octree.OctreeIndex(manifest());
        const text = octree.describeLod(index, { points: 3000 });
        expect(text).toMatch(/3,000/);
        expect(text).toMatch(/10,000/);
        expect(text).toMatch(/zoom in/);
    });

    test('names the budget when it is what is limiting detail', () => {
        // "zoom in for more" is wrong advice when the budget is the cap:
        // zooming in will not load more, and the annotator needs to know.
        const index = new octree.OctreeIndex(manifest());
        const text = octree.describeLod(index, { points: 3000,
                                                 budgetHit: true });
        expect(text).toMatch(/budget/);
    });

    test('says so plainly when everything is loaded', () => {
        const index = new octree.OctreeIndex(manifest());
        expect(octree.describeLod(index, { points: 10000 }))
            .toMatch(/all loaded/);
    });
});

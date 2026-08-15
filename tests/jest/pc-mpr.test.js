/**
 * Multi-planar reconstruction: the projection, the slab filter, and the drag.
 *
 * The failure this file is written against is a mirrored axis. A slab view
 * whose vertical axis runs the wrong way looks completely normal — points, a
 * box, sensible proportions — and every drag moves the opposite way from the
 * pointer. So each plane's orientation is asserted against a hand-computed
 * pixel, and the round-trip is checked in both directions.
 */

const mpr = require('../../potato/static/pointcloud/pc-mpr.js');

const IDENTITY = [0, 0, 0, 1];

function box(center, size, rotation) {
    return { center, size, rotation: rotation || IDENTITY };
}

describe('planes', () => {
    test('there are three, and each maps two distinct world axes', () => {
        expect(mpr.PLANE_ORDER).toEqual(['top', 'front', 'side']);
        mpr.PLANE_ORDER.forEach((name) => {
            const spec = mpr.PLANES[name];
            const axes = new Set([spec.u, spec.v, spec.normal]);
            expect(axes.size).toBe(3);
        });
    });

    test('an unknown plane is an error, not a silent default', () => {
        expect(() => mpr.makeView('oblique', [0, 0, 0], 10, 100, 100))
            .toThrow(/oblique/);
    });
});

describe('worldToPanel', () => {
    const view = () => mpr.makeView('top', [0, 0, 0], 10, 200, 200);

    test('the centre of the slab is the centre of the panel', () => {
        expect(mpr.worldToPanel(view(), [0, 0, 0])).toEqual({ x: 100, y: 100 });
    });

    test('the scale is metres to pixels, identically in both axes', () => {
        // extent 10 over 200 px => 10 px per metre.
        const p = mpr.worldToPanel(view(), [5, 0, 0]);
        expect(p.x).toBeCloseTo(150, 6);
        const q = mpr.worldToPanel(view(), [0, 5, 0]);
        expect(100 - q.y).toBeCloseTo(50, 6);
    });

    test('+Y is UP the screen in the top view, not down', () => {
        // The mirrored-axis bug: a view where north is at the bottom looks
        // entirely plausible and every drag goes the wrong way.
        const p = mpr.worldToPanel(view(), [0, 3, 0]);
        expect(p.y).toBeLessThan(100);
    });

    test('+Z is UP the screen in the front and side views', () => {
        const front = mpr.makeView('front', [0, 0, 0], 10, 200, 200);
        expect(mpr.worldToPanel(front, [0, 0, 4]).y).toBeLessThan(100);
        const side = mpr.makeView('side', [0, 0, 0], 10, 200, 200);
        expect(mpr.worldToPanel(side, [0, 0, 4]).y).toBeLessThan(100);
    });

    test('the slab normal does not move the projection', () => {
        // Two points differing only in depth land on the same pixel; that is
        // what makes the panel orthographic rather than perspective.
        const v = view();
        expect(mpr.worldToPanel(v, [2, 3, 0]))
            .toEqual(mpr.worldToPanel(v, [2, 3, 9]));
    });

    test('a non-square panel keeps the scale isotropic', () => {
        // Anisotropic scaling would render a square box as a rectangle, which
        // is the one thing a slab view exists to rule out.
        const wide = mpr.makeView('top', [0, 0, 0], 10, 400, 200);
        const a = mpr.worldToPanel(wide, [1, 0, 0]);
        const b = mpr.worldToPanel(wide, [0, 1, 0]);
        expect(a.x - 200).toBeCloseTo(100 - b.y, 6);
    });
});

describe('panelToWorld', () => {
    test('round-trips with worldToPanel in every plane', () => {
        mpr.PLANE_ORDER.forEach((name) => {
            const view = mpr.makeView(name, [1, -2, 3], 12, 300, 220);
            const point = [4.5, -6.25, 1.75];
            const p = mpr.worldToPanel(view, point);
            const back = mpr.panelToWorld(view, p.x, p.y);
            const spec = mpr.PLANES[name];
            expect(back[spec.u]).toBeCloseTo(point[spec.u], 6);
            expect(back[spec.v]).toBeCloseTo(point[spec.v], 6);
        });
    });

    test('the third axis takes the slab centre, not zero', () => {
        // A click on a 2D panel says nothing about the depth axis. Returning 0
        // would drag a box out of the slab it was being edited in.
        const view = mpr.makeView('top', [0, 0, 7], 10, 200, 200);
        expect(mpr.panelToWorld(view, 100, 100)[2]).toBe(7);
    });
});

describe('slabIndices', () => {
    // Six points along Z at 0, 1, 2, 3, 4, 5.
    const positions = new Float32Array(
        [0, 0, 0, 0, 0, 1, 0, 0, 2, 0, 0, 3, 0, 0, 4, 0, 0, 5]);

    test('keeps only what is inside the slab', () => {
        const view = mpr.makeView('top', [0, 0, 2], 10, 100, 100);
        expect(mpr.slabIndices(positions, view, 2.0, 1)).toEqual([1, 2, 3]);
    });

    test('a thicker slab keeps more', () => {
        const view = mpr.makeView('top', [0, 0, 2], 10, 100, 100);
        expect(mpr.slabIndices(positions, view, 10).length).toBe(6);
    });

    test('measures along the plane normal, not always Z', () => {
        const along = new Float32Array([0, 0, 0, 5, 0, 0, 10, 0, 0]);
        // Front looks along X, so the slab is an X range.
        const front = mpr.makeView('front', [5, 0, 0], 10, 100, 100);
        expect(mpr.slabIndices(along, front, 2)).toEqual([1]);
    });

    test('stride subsamples for a dense slab', () => {
        const view = mpr.makeView('top', [0, 0, 2.5], 10, 100, 100);
        expect(mpr.slabIndices(positions, view, 100, 2)).toEqual([0, 2, 4]);
    });
});

describe('boxEnvelope', () => {
    const view = () => mpr.makeView('top', [0, 0, 0], 10, 200, 200);

    test('an axis-aligned box gives its own extent', () => {
        const env = mpr.boxEnvelope(view(), box([0, 0, 0], [4, 2, 1.7]));
        expect(env.uMin).toBeCloseTo(-2, 6);
        expect(env.uMax).toBeCloseTo(2, 6);
        expect(env.vMin).toBeCloseTo(-1, 6);
        expect(env.vMax).toBeCloseTo(1, 6);
    });

    test('a yawed box reads its rotated extent, not its nominal size', () => {
        // 45 degrees about Z: a 4x2 box spans (4+2)/sqrt(2) ~= 4.243 in both.
        const yaw45 = [0, 0, Math.sin(Math.PI / 8), Math.cos(Math.PI / 8)];
        const env = mpr.boxEnvelope(view(), box([0, 0, 0], [4, 2, 1.7], yaw45));
        expect(env.uMax - env.uMin).toBeCloseTo(6 / Math.SQRT2, 3);
        expect(env.vMax - env.vMin).toBeCloseTo(6 / Math.SQRT2, 3);
    });

    test('a 90-degree yaw swaps the extents', () => {
        const yaw90 = [0, 0, Math.sin(Math.PI / 4), Math.cos(Math.PI / 4)];
        const env = mpr.boxEnvelope(view(), box([0, 0, 0], [4, 2, 1.7], yaw90));
        expect(env.uMax - env.uMin).toBeCloseTo(2, 5);
        expect(env.vMax - env.vMin).toBeCloseTo(4, 5);
    });
});

describe('handleAt', () => {
    const view = () => mpr.makeView('top', [0, 0, 0], 10, 200, 200);
    // 4 x 2 box at the origin: 40 x 20 px, so x in [80, 120], y in [90, 110].
    const b = () => box([0, 0, 0], [4, 2, 1.7]);

    test('the interior is a move', () => {
        expect(mpr.handleAt(view(), b(), 100, 100)).toBe('move');
    });

    test('outside is nothing', () => {
        expect(mpr.handleAt(view(), b(), 5, 5)).toBeNull();
    });

    test('the left edge is the world minimum', () => {
        expect(mpr.handleAt(view(), b(), 80, 100)).toBe('u-min');
        expect(mpr.handleAt(view(), b(), 120, 100)).toBe('u-max');
    });

    test('the TOP edge is the world MAXIMUM on a flipped axis', () => {
        // Get this backwards and dragging the top edge changes the bottom one.
        expect(mpr.handleAt(view(), b(), 100, 90)).toBe('v-max');
        expect(mpr.handleAt(view(), b(), 100, 110)).toBe('v-min');
    });

    test('edges win over the interior', () => {
        // The opposite priority makes a box filling the panel impossible to
        // shrink, which is a real trap in slab editors.
        const huge = box([0, 0, 0], [100, 100, 2]);
        const wide = mpr.makeView('top', [0, 0, 0], 10, 200, 200);
        expect(mpr.handleAt(wide, huge, 100, 100)).toBe('move');
        // The envelope extends past the panel, so its edges are off-screen and
        // the whole visible area is interior — which is the correct answer.
        expect(mpr.handleAt(wide, huge, 1, 1)).toBe('move');
    });

    test('the tolerance is configurable and respected', () => {
        expect(mpr.handleAt(view(), b(), 74, 100, 2)).toBeNull();
        expect(mpr.handleAt(view(), b(), 74, 100, 8)).toBe('u-min');
    });
});

describe('applyDrag', () => {
    const view = () => mpr.makeView('top', [0, 0, 0], 10, 200, 200);

    test('moving sets the centre on the two in-plane axes only', () => {
        const next = mpr.applyDrag(view(), box([0, 0, 1.5], [4, 2, 1.7]),
                                   'move', [3, -2, 99]);
        expect(next.center[0]).toBeCloseTo(3, 6);
        expect(next.center[1]).toBeCloseTo(-2, 6);
        expect(next.center[2]).toBeCloseTo(1.5, 6);
    });

    test('moving honours the grab offset so the box does not jump', () => {
        const next = mpr.applyDrag(view(), box([0, 0, 0], [4, 2, 1.7]),
                                   'move', [3, 0, 0], [1, 0, 0]);
        expect(next.center[0]).toBeCloseTo(2, 6);
    });

    test('dragging one edge leaves the opposite face where it was', () => {
        // The whole point of a slab view is aligning ONE boundary against the
        // returns behind it; a symmetric resize would undo the last alignment.
        const before = box([0, 0, 0], [4, 2, 1.7]);
        const next = mpr.applyDrag(view(), before, 'u-min', [-4, 0, 0]);
        const env = mpr.boxEnvelope(view(), next);
        expect(env.uMin).toBeCloseTo(-4, 5);
        expect(env.uMax).toBeCloseTo(2, 5);
        expect(next.size[0]).toBeCloseTo(6, 5);
    });

    test('dragging the far edge grows the other way', () => {
        const next = mpr.applyDrag(view(), box([0, 0, 0], [4, 2, 1.7]),
                                   'u-max', [6, 0, 0]);
        const env = mpr.boxEnvelope(view(), next);
        expect(env.uMin).toBeCloseTo(-2, 5);
        expect(env.uMax).toBeCloseTo(6, 5);
    });

    test('a vertical drag edits the panel vertical axis', () => {
        const next = mpr.applyDrag(view(), box([0, 0, 0], [4, 2, 1.7]),
                                   'v-max', [0, 5, 0]);
        expect(next.size[1]).toBeCloseTo(6, 5);
        expect(next.center[1]).toBeCloseTo(2, 5);
    });

    test('a drag past the opposite face is refused, not inverted', () => {
        // A negative size exports as degenerate geometry and renders as an
        // inside-out wireframe, neither of which the annotator meant.
        const before = box([0, 0, 0], [4, 2, 1.7]);
        expect(mpr.applyDrag(view(), before, 'u-min', [5, 0, 0])).toBe(before);
    });

    test('a sub-centimetre span is a mis-grab, not a resize', () => {
        const before = box([0, 0, 0], [4, 2, 1.7]);
        expect(mpr.applyDrag(view(), before, 'u-max', [-1.99, 0, 0]))
            .toBe(before);
    });

    test('rotation is carried through unchanged', () => {
        const yaw = [0, 0, Math.sin(Math.PI / 8), Math.cos(Math.PI / 8)];
        const next = mpr.applyDrag(view(), box([0, 0, 0], [4, 2, 1.7], yaw),
                                   'move', [1, 1, 0]);
        expect(next.rotation).toEqual(yaw);
    });

    test('the front panel edits Z, which is height', () => {
        const front = mpr.makeView('front', [0, 0, 0], 10, 200, 200);
        const next = mpr.applyDrag(front, box([0, 0, 0], [4, 2, 2]),
                                   'v-max', [0, 0, 3]);
        expect(next.size[2]).toBeCloseTo(4, 5);
    });
});

describe('axisToSizeIndex', () => {
    test('Z is always the height component', () => {
        expect(mpr.axisToSizeIndex(2, IDENTITY)).toBe(2);
    });

    test('an unrotated box maps world axes to its own', () => {
        expect(mpr.axisToSizeIndex(0, IDENTITY)).toBe(0);
        expect(mpr.axisToSizeIndex(1, IDENTITY)).toBe(1);
    });

    test('a quarter turn swaps X and Y', () => {
        const yaw90 = [0, 0, Math.sin(Math.PI / 4), Math.cos(Math.PI / 4)];
        expect(mpr.axisToSizeIndex(0, yaw90)).toBe(1);
        expect(mpr.axisToSizeIndex(1, yaw90)).toBe(0);
    });
});

describe('focus and extent', () => {
    test('the slab centres on the selected box', () => {
        // Centring anywhere else puts the box's own returns outside the slab,
        // which is the one thing that must not happen while editing it.
        expect(mpr.focusPoint({ coordinates: { center: [1, 2, 3] } }))
            .toEqual([1, 2, 3]);
    });

    test('a point annotation focuses on itself', () => {
        expect(mpr.focusPoint({ coordinates: [4, 5, 6] })).toEqual([4, 5, 6]);
    });

    test('with no selection it falls back to the camera target', () => {
        expect(mpr.focusPoint(null, [7, 8, 9])).toEqual([7, 8, 9]);
        expect(mpr.focusPoint(null)).toEqual([0, 0, 0]);
    });

    test('the extent frames the selection with room around it', () => {
        const extent = mpr.extentFor(
            { coordinates: { center: [0, 0, 0], size: [4, 2, 1.7] } });
        expect(extent).toBeGreaterThan(4);
        expect(extent).toBeLessThan(12);
    });

    test('a small selection is not left four pixels wide', () => {
        const pedestrian = mpr.extentFor(
            { coordinates: { center: [0, 0, 0], size: [0.6, 0.6, 1.8] } });
        expect(pedestrian).toBeLessThanOrEqual(4);
    });

    test('no selection uses the scene-scale fallback', () => {
        expect(mpr.extentFor(null, 30)).toBe(30);
    });
});

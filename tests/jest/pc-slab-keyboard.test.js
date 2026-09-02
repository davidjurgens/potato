/**
 * The keyboard path through the orthographic slab panels.
 *
 * These panels exist because placing a box by eye in a perspective view is
 * imprecise in a specific direction — the extent along the view axis. So when
 * the only way to adjust a face was a pointer drag, "use the 3D view instead"
 * was not an equivalent alternative for a keyboard user, it was the exact
 * imprecision the panels were built to remove (WCAG 2.1.1).
 *
 * The arithmetic itself lives in pc-mpr.js and is tested there. What is tested
 * here is the mapping from a keypress to that arithmetic, which is where the
 * sign errors live: `flipV` means screen-up is world-positive, and getting it
 * wrong moves every box the opposite way from the arrow in every panel.
 */

require('../../potato/static/pointcloud/pc-mpr.js');
const Manager = require('../../potato/static/pointcloud/pc-viewer.js');
const mpr = global.PointCloudMPR;

function cuboid(center, size) {
    return {
        type: 'cuboid_3d', label: 'car', color: '#ff0000',
        coordinates: {
            center: center.slice(),
            size: (size || [4, 2, 1.5]).slice(),
            rotation: [0, 0, 0, 1],
        },
    };
}

/**
 * A manager wired for the keyboard path only: no WebGL, no canvases.
 *
 * `_slabView` is the real method, so the plane specs and the flip come from
 * pc-mpr rather than from a fixture that could disagree with it.
 */
function makeManager(annotations) {
    const m = Object.create(Manager.prototype);
    m.config = { schema: 'objects', slabThickness: 2.0, mpr: true };
    m.annotations = annotations || [cuboid([0, 0, 0])];
    m.selectedIndex = 0;
    m.meshes = [];
    m.history = [];
    m.historyIndex = -1;
    m.maxHistory = 50;
    m._orbit = { target: { x: 0, y: 0, z: 0 } };
    m.lodIndex = null;
    m.parsed = null;
    m.announced = [];

    m._rebuildMesh = jest.fn();
    m._updateAnnotationData = jest.fn();
    m._drawMpr = jest.fn();
    m._saveState = jest.fn();
    m._render = jest.fn();
    m._highlightSelection = jest.fn();
    m._drawOverlays = jest.fn();
    m._status = jest.fn();
    m._announce = function (msg) { this.announced.push(msg); };

    // A 400x400 panel centred on the origin, which is what _slabView would
    // build from a real canvas. Stubbed at the getBoundingClientRect level so
    // the view construction itself is the real code.
    m.mprPanels = {};
    mpr.PLANE_ORDER.forEach((plane) => {
        m.mprPanels[plane] = {
            canvas: { getBoundingClientRect: () => ({ width: 400, height: 400 }) },
        };
    });
    return m;
}

/** A keydown-shaped object; `preventDefault`/`stopPropagation` are recorded. */
function key(name, mods) {
    return Object.assign({
        key: name,
        shiftKey: false, altKey: false, ctrlKey: false, metaKey: false,
        preventDefault: jest.fn(),
        stopPropagation: jest.fn(),
    }, mods || {});
}

describe('arrow keys move the selected box', () => {
    // The top panel maps world X to screen-horizontal and world Y to
    // screen-vertical, flipped.
    test('right arrow increases world X in the top plane', () => {
        const m = makeManager();
        m._slabKey('top', key('ArrowRight'));
        expect(m.annotations[0].coordinates.center[0]).toBeCloseTo(0.1, 6);
        expect(m.annotations[0].coordinates.center[1]).toBeCloseTo(0, 6);
    });

    test('left arrow decreases world X', () => {
        const m = makeManager();
        m._slabKey('top', key('ArrowLeft'));
        expect(m.annotations[0].coordinates.center[0]).toBeCloseTo(-0.1, 6);
    });

    // The control for the flip. Screen-up must be world-POSITIVE on a flipped
    // axis; without the conversion this comes out -0.1 and the box tracks the
    // opposite of the arrow, which reads as a broken control rather than an
    // inverted one.
    test('up arrow increases world Y in the flipped top plane', () => {
        const m = makeManager();
        expect(mpr.PLANES.top.flipV).toBe(true);
        m._slabKey('top', key('ArrowUp'));
        expect(m.annotations[0].coordinates.center[1]).toBeCloseTo(0.1, 6);
    });

    test('down arrow decreases world Y', () => {
        const m = makeManager();
        m._slabKey('top', key('ArrowDown'));
        expect(m.annotations[0].coordinates.center[1]).toBeCloseTo(-0.1, 6);
    });

    test('each plane moves the axes it actually shows', () => {
        // front is Y-Z, so a horizontal arrow must touch Y and leave X alone.
        const m = makeManager();
        m._slabKey('front', key('ArrowRight'));
        const c = m.annotations[0].coordinates.center;
        expect(c[0]).toBeCloseTo(0, 6);
        expect(c[1]).toBeCloseTo(0.1, 6);
        expect(c[2]).toBeCloseTo(0, 6);
    });

    test('moving never changes the size', () => {
        const m = makeManager();
        m._slabKey('top', key('ArrowRight'));
        m._slabKey('top', key('ArrowUp'));
        expect(m.annotations[0].coordinates.size).toEqual([4, 2, 1.5]);
    });
});

describe('shift and alt move one face', () => {
    test('shift+right pushes the +X face out and leaves -X put', () => {
        const m = makeManager();
        const before = m.annotations[0].coordinates;
        const xMaxBefore = before.center[0] + before.size[0] / 2;
        const xMinBefore = before.center[0] - before.size[0] / 2;

        m._slabKey('top', key('ArrowRight', { shiftKey: true }));

        const after = m.annotations[0].coordinates;
        expect(after.center[0] + after.size[0] / 2)
            .toBeCloseTo(xMaxBefore + 0.05, 6);
        // The whole point of a face drag: the opposite face does not follow.
        expect(after.center[0] - after.size[0] / 2).toBeCloseTo(xMinBefore, 6);
        expect(after.size[0]).toBeCloseTo(4.05, 6);
    });

    test('alt+right pulls the +X face in', () => {
        const m = makeManager();
        m._slabKey('top', key('ArrowRight', { altKey: true }));
        const after = m.annotations[0].coordinates;
        expect(after.size[0]).toBeCloseTo(3.95, 6);
        expect(after.center[0] + after.size[0] / 2).toBeCloseTo(1.95, 6);
    });

    // The arrow names the FACE, not the direction of travel. A scheme where
    // the arrow named the direction would leave two of the four faces
    // unreachable from the keyboard entirely.
    test('shift+left reaches the -X face, which shift+right cannot', () => {
        const m = makeManager();
        m._slabKey('top', key('ArrowLeft', { shiftKey: true }));
        const after = m.annotations[0].coordinates;
        expect(after.center[0] - after.size[0] / 2).toBeCloseTo(-2.05, 6);
        expect(after.center[0] + after.size[0] / 2).toBeCloseTo(2, 6);
    });

    test('shift+up grows the +Y face despite the flip', () => {
        const m = makeManager();
        m._slabKey('top', key('ArrowUp', { shiftKey: true }));
        const after = m.annotations[0].coordinates;
        expect(after.center[1] + after.size[1] / 2).toBeCloseTo(1.05, 6);
        expect(after.center[1] - after.size[1] / 2).toBeCloseTo(-1, 6);
    });

    test('a face cannot be pulled through the box', () => {
        // 0.06 m wide: one 0.05 m inward step would leave 0.01 m, under the
        // degenerate-geometry floor, so applyDrag refuses it.
        const m = makeManager([cuboid([0, 0, 0], [0.06, 2, 1.5])]);
        m._slabKey('top', key('ArrowRight', { altKey: true }));
        expect(m.annotations[0].coordinates.size[0]).toBeCloseTo(0.06, 6);
        // Refusing silently reads as a dropped keypress.
        expect(m.announced.join(' ')).toMatch(/minimum size/i);
        expect(m._saveState).not.toHaveBeenCalled();
    });
});

describe('bookkeeping', () => {
    test('every accepted press is one undo step', () => {
        const m = makeManager();
        m._slabKey('top', key('ArrowRight'));
        m._slabKey('top', key('ArrowRight'));
        // Unlike a drag, which saves once at mouseup: each press is a discrete
        // deliberate edit and should undo on its own.
        expect(m._saveState).toHaveBeenCalledTimes(2);
        expect(m._updateAnnotationData).toHaveBeenCalledTimes(2);
    });

    test('the result is announced, since only pixels changed', () => {
        const m = makeManager();
        m._slabKey('top', key('ArrowRight'));
        expect(m.announced).toHaveLength(1);
        expect(m.announced[0]).toMatch(/m at/);
    });

    test('an unhandled key is left for the page', () => {
        const m = makeManager();
        const e = key('a');
        m._slabKey('top', e);
        expect(e.preventDefault).not.toHaveBeenCalled();
        expect(e.stopPropagation).not.toHaveBeenCalled();
    });

    test('ctrl and meta are left to the browser', () => {
        const m = makeManager();
        const e = key('ArrowRight', { ctrlKey: true });
        m._slabKey('top', e);
        expect(e.preventDefault).not.toHaveBeenCalled();
        expect(m.annotations[0].coordinates.center[0]).toBe(0);
    });

    test('with nothing selected it says so rather than doing nothing', () => {
        const m = makeManager();
        m.selectedIndex = -1;
        m._slabKey('top', key('ArrowRight'));
        expect(m.announced.join(' ')).toMatch(/select a box/i);
    });

    test('a non-cuboid selection is not silently ignored', () => {
        const m = makeManager([{ type: 'point_3d', label: 'p',
                                 coordinates: [1, 1, 1] }]);
        m._slabKey('top', key('ArrowRight'));
        expect(m.announced.join(' ')).toMatch(/select a box/i);
        expect(m.annotations[0].coordinates).toEqual([1, 1, 1]);
    });
});

describe('slab thickness', () => {
    test('brackets change it and keep it in range', () => {
        const m = makeManager();
        m._slabKey('top', key(']'));
        expect(m.config.slabThickness).toBeCloseTo(2.3, 6);
        m._slabKey('top', key('['));
        expect(m.config.slabThickness).toBeCloseTo(2.0, 6);

        for (let i = 0; i < 100; i++) m._slabKey('top', key('['));
        expect(m.config.slabThickness).toBeGreaterThanOrEqual(0.1);
        for (let i = 0; i < 200; i++) m._slabKey('top', key(']'));
        expect(m.config.slabThickness).toBeLessThanOrEqual(200);
    });

    test('the new thickness is announced', () => {
        const m = makeManager();
        m._slabKey('top', key(']'));
        expect(m.announced.join(' ')).toMatch(/2\.3 m/);
    });

    test('the document handler does not also see it', () => {
        const m = makeManager();
        const e = key(']');
        m._slabKey('top', e);
        // A label whose key_value was a bracket would otherwise fire too.
        expect(e.stopPropagation).toHaveBeenCalled();
    });
});

describe('panel markup', () => {
    /** A manager with a real container, so _buildMprPanels can run. */
    function withContainer() {
        document.body.innerHTML = `
            <div class="pointcloud-annotation-container" data-schema="objects">
                <p class="pc-announce" id="pc-announce-objects"
                   role="status" aria-live="polite"></p>
                <div class="pc-mpr"></div>
                <p class="pc-mpr-help" id="pc-mpr-help-objects">keys</p>
            </div>`;
        const m = makeManager();
        m.container = document.querySelector('.pointcloud-annotation-container');
        m._bindSlab = jest.fn();
        m._drawMpr = jest.fn();
        m._buildMprPanels();
        return m;
    }

    test('three panels, one per plane', () => {
        withContainer();
        expect(document.querySelectorAll('.pc-slab-canvas')).toHaveLength(3);
    });

    // The regression this file exists for. The slab canvases took pointer
    // input and carried aria-hidden="true", copied from the camera overlay
    // next door — which really is decorative. Hiding an interactive control
    // from the accessibility tree removes the only way a screen-reader user
    // could learn it exists (WCAG 4.1.2).
    test('a canvas that takes input is never aria-hidden', () => {
        withContainer();
        document.querySelectorAll('.pc-slab-canvas').forEach((c) => {
            expect(c.getAttribute('aria-hidden')).toBeNull();
        });
    });

    test('each canvas is focusable, named, and described', () => {
        withContainer();
        const canvases = [...document.querySelectorAll('.pc-slab-canvas')];
        expect(canvases).not.toHaveLength(0);
        canvases.forEach((c) => {
            expect(c.tabIndex).toBe(0);
            expect(c.getAttribute('role')).toBe('application');
            // Named by its plane: three canvases all called "slab view" are
            // three controls a screen-reader user cannot tell apart.
            expect(c.getAttribute('aria-label')).toMatch(/\(.+\) slab view/);
            expect(c.getAttribute('aria-describedby')).toBe('pc-mpr-help-objects');
        });
        const labels = canvases.map((c) => c.getAttribute('aria-label'));
        expect(new Set(labels).size).toBe(3);
    });

    test('the describedby target is looked up, not string-built', () => {
        // The id is HTML-escaped server-side and config.schema is not, so a
        // built id would drift for any name the escaper touches.
        document.body.innerHTML = `
            <div class="pointcloud-annotation-container" data-schema="odd">
                <div class="pc-mpr"></div>
                <p class="pc-mpr-help" id="pc-mpr-help-odd-name">keys</p>
            </div>`;
        const m = makeManager();
        m.container = document.querySelector('.pointcloud-annotation-container');
        m._bindSlab = jest.fn();
        m._drawMpr = jest.fn();
        m._buildMprPanels();
        expect(document.querySelector('.pc-slab-canvas')
            .getAttribute('aria-describedby')).toBe('pc-mpr-help-odd-name');
    });
});

describe('announcements', () => {
    function withAnnouncer() {
        document.body.innerHTML = `
            <div class="pointcloud-annotation-container">
                <p class="pc-status"></p>
                <p class="pc-announce" role="status" aria-live="polite"></p>
            </div>`;
        const m = makeManager();
        m.container = document.querySelector('.pointcloud-annotation-container');
        delete m._announce;      // use the real one
        delete m._status;
        return m;
    }

    test('an identical repeat still changes the text node', () => {
        // Most screen readers do not re-announce an unchanged string, and
        // nudging a box repeatedly produces runs of them.
        const m = withAnnouncer();
        const el = document.querySelector('.pc-announce');
        m._announce('4.0 x 2.0 x 1.5 m at 0.1, 0.0');
        const first = el.textContent;
        m._announce('4.0 x 2.0 x 1.5 m at 0.1, 0.0');
        expect(el.textContent).not.toBe(first);
        expect(el.textContent.replace(/​/g, '')).toBe(first);
    });

    // The flooding fix: level-of-detail loading rewrites .pc-status about
    // eight times a second while the camera moves.
    test('routine status is shown but not announced', () => {
        const m = withAnnouncer();
        m._status('Level 2 of 4, 180,000 points');
        expect(document.querySelector('.pc-status').textContent)
            .toMatch(/180,000/);
        expect(document.querySelector('.pc-announce').textContent).toBe('');
    });

    test('errors and warnings are announced', () => {
        const m = withAnnouncer();
        m._status('Point cloud is unreadable', 'error');
        expect(document.querySelector('.pc-announce').textContent)
            .toMatch(/unreadable/);
        m._status('This point cloud is empty.', 'warn');
        expect(document.querySelector('.pc-announce').textContent)
            .toMatch(/empty/);
    });
});

describe('cycleSelection', () => {
    const three = () => [cuboid([0, 0, 0]), cuboid([5, 0, 0]),
                         cuboid([10, 0, 0])];

    test('steps forward from nothing selected to the first', () => {
        const m = makeManager(three());
        m.selectedIndex = -1;
        m.cycleSelection(1);
        expect(m.selectedIndex).toBe(0);
    });

    test('steps backward from nothing selected to the last', () => {
        const m = makeManager(three());
        m.selectedIndex = -1;
        m.cycleSelection(-1);
        expect(m.selectedIndex).toBe(2);
    });

    test('wraps in both directions', () => {
        const m = makeManager(three());
        m.selectedIndex = 2;
        m.cycleSelection(1);
        expect(m.selectedIndex).toBe(0);
        m.cycleSelection(-1);
        expect(m.selectedIndex).toBe(2);
    });

    test('announces position, count and label', () => {
        const m = makeManager(three());
        m.selectedIndex = -1;
        m.cycleSelection(1);
        expect(m.announced[0]).toMatch(/1 of 3: car/);
    });

    test('an empty list is a no-op, not an exception', () => {
        const m = makeManager([]);
        m.selectedIndex = -1;
        expect(() => m.cycleSelection(1)).not.toThrow();
        expect(m.selectedIndex).toBe(-1);
    });

    // Without this the slab keys are only usable on a box you have just drawn,
    // because selectedIndex was otherwise set only by drawing or by clicking.
    test('a cycled selection is editable from the slab keys', () => {
        const m = makeManager(three());
        m.selectedIndex = -1;
        m.cycleSelection(-1);
        m._slabKey('top', key('ArrowRight'));
        expect(m.annotations[2].coordinates.center[0]).toBeCloseTo(10.1, 6);
    });
});

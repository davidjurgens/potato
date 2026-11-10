/**
 * Painting points in the viewer: a stroke's effect on the stored segments.
 *
 * No WebGL in jsdom, so three.js is replaced by the few constructors the paint
 * path touches and the camera projects through an identity matrix: a point at
 * (x, y, 0) lands at ((x + 1) * 50, (1 - y) * 50) on a 100 x 100 canvas. The
 * buffers are plain objects shaped like THREE.Points.
 */

global.THREE = {
    Color: class {
        setRGB(r, g, b) { this.r = r; this.g = g; this.b = b; return this; }
    },
    BufferAttribute: class {
        constructor(array, size) { this.array = array; this.itemSize = size; }
    },
    BufferGeometry: class {
        constructor() { this.attributes = {}; this.index = null; }
        setAttribute(name, attr) { this.attributes[name] = attr; return this; }
        getAttribute(name) { return this.attributes[name]; }
        setIndex(index) { this.index = index; }
    },
    Points: class {
        constructor(geometry, material) {
            this.geometry = geometry; this.material = material;
            this.userData = {}; this.visible = true;
        }
    },
    PointsMaterial: class { constructor(opts) { Object.assign(this, opts); } },
    Matrix4: class {
        multiplyMatrices() {
            this.elements = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
            return this;
        }
    },
};
require('../../potato/static/pointcloud/pc-wire.js');
require('../../potato/static/pointcloud/pc-paint.js');
const Manager = require('../../potato/static/pointcloud/pc-viewer.js');

const LABELS = [{ name: 'car', color: '#ff0000' }, { name: 'road', color: '#0000ff' }];

/**
 * Four points: three along the middle row at x = 25, 50, 75 px and one near
 * the top at (50, 10). The buffer is a decimated sample, so slot i holds
 * source point SOURCE[i] -- what is stored must be SOURCE, not i.
 */
const SOURCE = [10, 20, 30, 40];

function fakeBuffer() {
    const count = SOURCE.length;
    const colors = new Float32Array(count * 3).fill(0.5);
    const attr = { array: colors, needsUpdate: false };
    const geometry = {
        index: null,
        getAttribute: (name) => (name === 'color' ? attr : null),
        setIndex(i) { this.index = i; },
    };
    return {
        obj: { geometry, userData: {}, visible: true },
        parsed: {
            count,
            positions: new Float32Array([-0.5, 0, 0, 0, 0, 0, 0.5, 0, 0, 0, 0.8, 0]),
            indices: new Uint32Array(SOURCE),
            header: { count, original_count: 8 },
        },
    };
}

function makeManager(config) {
    const m = new Manager('pc-canvas-objects', 'input-objects',
                          Object.assign({ schema: 'objects', labels: LABELS,
                                          tools: ['segment_3d'], brushSize: 4 }, config || {}));
    const buffer = fakeBuffer();
    Object.assign(m, {
        container: document.querySelector('.pointcloud-annotation-container'),
        canvas: {
            clientWidth: 100, clientHeight: 100, clientLeft: 0, clientTop: 0,
            classList: { toggle() {} },
            getBoundingClientRect: () => ({ left: 0, top: 0 }),
        },
        camera: { updateMatrixWorld() {}, projectionMatrix: {}, matrixWorldInverse: {} },
        scene: { add() {}, remove() {} },
        _render: () => {}, _drawOverlays: () => {},
        _buildMesh(obj) { this.meshes.push(null); },
        cloud: buffer.obj, parsed: buffer.parsed,
        currentTool: 'segment_3d',
    });
    m.setLabel('car', '#ff0000');
    return m;
}

const at = (x, y, extra) => Object.assign({ clientX: x, clientY: y, button: 0 }, extra || {});

/** Brush from (x0, y0) to (x1, y1) in one move, as the window handlers do. */
function stroke(m, x0, y0, x1, y1, extra) {
    m._startStroke(at(x0, y0, extra));
    if (!m._paintStroke) return;
    m._extendStroke(at(x1, y1, extra));
    m._endStroke();
}

const stored = () => JSON.parse(document.getElementById('input-objects').value || '[]');

function rgbAt(m, slot) {
    return Array.from(m.cloud.geometry.getAttribute('color').array.slice(slot * 3, slot * 3 + 3));
}

beforeEach(() => {
    document.body.innerHTML = `
      <div class="pointcloud-annotation-container annotation-form">
        <input type="hidden" id="input-objects" value="">
        <p class="pc-status"></p><p class="pc-announce" aria-live="polite"></p>
      </div>`;
});

test('a brush stroke stores one segment of SOURCE indices and recolours them', () => {
    const m = makeManager();
    stroke(m, 25, 50, 75, 50);
    expect(stored()).toEqual([
        { type: 'segment_3d', label: 'car', color: '#ff0000', indices: [10, 20, 30] },
    ]);
    expect(rgbAt(m, 1)).toEqual([1, 0, 0]);
    expect(rgbAt(m, 3)).toEqual([0.5, 0.5, 0.5]);
    expect(document.querySelector('.pc-announce').textContent)
        .toBe('Painted 3 points as car (3 car points in all).');
});

test('repainting moves a point to the new class; no point is in two segments', () => {
    const m = makeManager();
    stroke(m, 25, 50, 75, 50);
    m.setLabel('road', '#0000ff');
    stroke(m, 50, 50, 50, 50);
    expect(stored()).toEqual([
        { type: 'segment_3d', label: 'car', color: '#ff0000', indices: [10, 30] },
        { type: 'segment_3d', label: 'road', color: '#0000ff', indices: [20] },
    ]);
    expect(rgbAt(m, 1)).toEqual([0, 0, 1]);
});

test('Shift+drag erases, puts the cloud colour back, and drops an emptied segment', () => {
    const m = makeManager();
    stroke(m, 50, 10, 50, 10);
    expect(stored()).toHaveLength(1);
    stroke(m, 50, 10, 50, 10, { shiftKey: true });
    expect(stored()).toEqual([]);
    expect(rgbAt(m, 3)).toEqual([0.5, 0.5, 0.5]);
});

test('the Erase toggle unlabels without a modifier', () => {
    const m = makeManager();
    stroke(m, 25, 50, 75, 50);
    m.setPaintErase(true);
    stroke(m, 25, 50, 25, 50);
    expect(stored()[0].indices).toEqual([20, 30]);
});

test('points of a hidden class are not repainted, and are left out of the draw', () => {
    const m = makeManager();
    stroke(m, 25, 50, 50, 50);
    m.applyLabelVisibility(new Set(['car']));
    expect(Array.from(m.cloud.geometry.index.array)).toEqual([2, 3]);

    m.setLabel('road', '#0000ff');
    stroke(m, 25, 50, 75, 50);
    expect(stored()).toEqual([
        { type: 'segment_3d', label: 'car', color: '#ff0000', indices: [10, 20] },
        { type: 'segment_3d', label: 'road', color: '#0000ff', indices: [30] },
    ]);
    // Erasing does not reach them either.
    stroke(m, 25, 50, 75, 50, { shiftKey: true });
    expect(stored()).toEqual([
        { type: 'segment_3d', label: 'car', color: '#ff0000', indices: [10, 20] },
    ]);
});

test('painting with a hidden class is refused', () => {
    const m = makeManager();
    m.applyLabelVisibility(new Set(['car']));
    stroke(m, 25, 50, 75, 50);
    expect(stored()).toEqual([]);
    expect(document.querySelector('.pc-status').textContent).toMatch(/car is hidden/);
});

test('a lasso labels the points inside its outline when released', () => {
    const m = makeManager();
    m.setPaintMode('lasso');
    m._startStroke(at(40, 0));
    [[60, 0], [60, 60], [40, 60]].forEach(([x, y]) => m._extendStroke(at(x, y)));
    expect(stored()).toEqual([]);
    m._endStroke();
    expect(stored()[0].indices).toEqual([20, 40]);
});

test('a lasso dragged in a straight line says to draw a loop', () => {
    const m = makeManager();
    m.setPaintMode('lasso');
    m._startStroke(at(20, 50));
    m._extendStroke(at(80, 50));
    m._endStroke();
    expect(stored()).toEqual([]);
    expect(document.querySelector('.pc-status').textContent)
        .toBe('Draw a loop around the points to lasso them.');
});

test('Escape mid-stroke puts back what the stroke had painted', () => {
    const m = makeManager();
    m._startStroke(at(25, 50));
    m._extendStroke(at(75, 50));
    expect(rgbAt(m, 0)).toEqual([1, 0, 0]);
    expect(m.cancelStroke()).toBe(true);
    expect(rgbAt(m, 0)).toEqual([0.5, 0.5, 0.5]);
    expect(stored()).toEqual([]);
});

test('undo restores the previous segments and their colours', () => {
    const m = makeManager();
    stroke(m, 25, 50, 25, 50);
    stroke(m, 75, 50, 75, 50);
    expect(m.undo()).toBe(true);
    expect(stored()[0].indices).toEqual([10]);
    expect(rgbAt(m, 2)).toEqual([0.5, 0.5, 0.5]);
});

test('relabelling a segment into a painted class merges the two', () => {
    const m = makeManager();
    stroke(m, 25, 50, 25, 50);
    m.setLabel('road', '#0000ff');
    stroke(m, 75, 50, 75, 50);
    m.currentTool = null;
    expect(m.relabelAnnotation(0, 'road')).toBe(true);
    expect(stored()).toEqual([
        { type: 'segment_3d', label: 'road', color: '#0000ff', indices: [10, 30] },
    ]);
    expect(m.selectedIndex).toBe(0);
});

test('choosing a class while painting does not relabel the selected segment', () => {
    const m = makeManager();
    stroke(m, 25, 50, 25, 50);
    m.selectedIndex = 0;
    m._markUserSelection();
    m.setLabel('road', '#0000ff', true);
    expect(stored()[0].label).toBe('car');
});

test('clearAnnotations drops the label map and the stroke in flight', () => {
    const m = makeManager();
    stroke(m, 25, 50, 75, 50);
    m._startStroke(at(50, 10));
    m.clearAnnotations();
    expect(m._pointLabels.size).toBe(0);
    expect(m._paintStroke).toBeNull();
    expect(rgbAt(m, 0)).toEqual([0.5, 0.5, 0.5]);
});

test('restored segments colour a buffer that arrives afterwards', () => {
    document.getElementById('input-objects').value = JSON.stringify([
        { type: 'segment_3d', label: 'road', color: '#0000ff', indices: [40] }]);
    const m = makeManager();
    m._restoreFromInput();
    const late = fakeBuffer();
    m._applyPaint(late.obj, late.parsed);
    expect(Array.from(late.obj.geometry.getAttribute('color').array.slice(9, 12))).toEqual([0, 0, 1]);
});

test('arming the tool on a sampled cloud warns that only shown points get labels', () => {
    const m = makeManager();
    m.currentTool = null;
    m.setTool('segment_3d');
    expect(document.querySelector('.pc-status').textContent)
        .toMatch(/sampled to 4 of 8 points/);
});

test('under LOD a stroke stores the source indices of a node, and arming warns', () => {
    const m = makeManager();
    const node = fakeBuffer();
    m.cloud = null;
    m.lodIndex = { totalCount: 50 };
    m.lodNodes = new Map([['r0', node.obj]]);
    m.lodParsed = new Map([['r0', node.parsed]]);
    m.currentTool = null;
    m.setTool('segment_3d');
    expect(document.querySelector('.pc-status').textContent)
        .toMatch(/only the 4 of 50 points loaded/);
    stroke(m, 25, 50, 75, 50);
    expect(stored()[0].indices).toEqual([10, 20, 30]);
    // A node that loads after the stroke takes the paint as it is built.
    const late = m._pointsObject(fakeBuffer().parsed);
    expect(Array.from(late.geometry.getAttribute('color').array.slice(0, 3))).toEqual([1, 0, 0]);
    expect(Array.from(late.geometry.getAttribute('color').array.slice(9, 12)))
        .not.toEqual([1, 0, 0]);
});

test('a painted segment needs no per-object attributes', () => {
    window.ObjectAttributes = require('../../potato/static/object-attributes.js');
    const m = makeManager({
        attributes: [{ name: 'occluded', type: 'select', options: ['none', 'partial'],
                       required: true }],
    });
    m.attributePanel = document.createElement('section');
    m.attributePanel.innerHTML = '<p class="attribute-panel-hint"></p>'
        + '<div class="attribute-fields"></div><p class="attribute-panel-status"></p>';
    stroke(m, 25, 50, 75, 50);
    expect(m.container.getAttribute('data-incomplete-reason')).toBeNull();
    delete window.ObjectAttributes;
});

test('the class-visibility manager is keyed by this schema and project', () => {
    const seen = [];
    global.LabelVisibilityManager = class { constructor(opts) { seen.push(opts); } };
    window.config = { annotation_task_name: 'kitti' };
    const m = makeManager();
    m._bindToolbar();
    expect(seen[0]).toMatchObject({ schemaName: 'objects', projectKey: 'kitti' });
    delete global.LabelVisibilityManager;
    delete window.config;
});

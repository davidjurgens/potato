/**
 * Relabeling a cuboid from the class buttons.
 *
 * The buttons and keys only set the class of the next object, so a cuboid with
 * the wrong class had to be deleted and drawn again. With an object the
 * annotator selected they now relabel it, and in a sequence the whole track.
 * The object the viewer selects itself after drawing is left alone.
 */

require('../../potato/static/pointcloud/pc-wire.js');
const Manager = require('../../potato/static/pointcloud/pc-viewer.js');

function makeManager() {
    const m = Object.create(Manager.prototype);
    m.config = { schema: 'objects',
                 labels: [{ name: 'Car', color: '#ff0000' },
                          { name: 'Van', color: '#0000ff' }] };
    m.inputId = 'input-objects';
    m.annotations = [];
    m.meshes = [];
    m.history = [];
    m.historyIndex = -1;
    m.maxHistory = 50;
    m.selectedIndex = -1;
    m._render = jest.fn();
    m._rebuildMeshes = jest.fn();
    m._saveState = jest.fn();
    m._updateAnnotationData = jest.fn();
    return m;
}

function cuboid(label, extra) {
    return Object.assign({ type: 'cuboid_3d', label, color: '#ff0000',
                           coordinates: { center: [0, 0, 0], size: [4, 2, 1.5],
                                          rotation: [0, 0, 0, 1] } }, extra || {});
}

test('a class button relabels the cuboid the annotator selected', () => {
    const m = makeManager();
    m.annotations = [cuboid('Car', { source: 'ai' }), cuboid('Car')];
    m.selectedIndex = 0;
    m._markUserSelection();               // a click or a cycle key
    m.setLabel('Van', '#0000ff', true);
    expect(m.annotations[0].label).toBe('Van');
    expect(m.annotations[0].color).toBe('#0000ff');
    expect(m.annotations[0].edited).toBe(true);
    expect(m.annotations[1].label).toBe('Car');
});

test('choosing the class for the next box leaves the one just drawn', () => {
    const m = makeManager();
    m.annotations = [cuboid('Car')];
    m.selectedIndex = 0;                  // selected by the viewer after drawing
    m._relabelTarget = null;
    m.setLabel('Van', '#0000ff', true);
    expect(m.annotations[0].label).toBe('Car');
    expect(m.currentLabel).toBe('Van');
});

test('in a sequence the whole track takes the new class', () => {
    const m = makeManager();
    m.frames = [{}, {}, {}];
    m.sequenceStore = [cuboid('Car', { track_id: 7, frame: 0 }),
                       cuboid('Car', { track_id: 7, frame: 2 }),
                       cuboid('Car', { track_id: 8, frame: 0 })];
    m.annotations = [cuboid('Car', { track_id: 7, frame: 0 })];
    m.selectedIndex = 0;
    m._markUserSelection();
    m.setLabel('Van', '#0000ff', true);
    expect(m.sequenceStore.map((o) => o.label)).toEqual(['Van', 'Van', 'Car']);
});

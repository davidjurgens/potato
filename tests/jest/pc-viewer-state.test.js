/**
 * PointCloudAnnotationManager save/restore and lifecycle state.
 *
 * The renderer needs WebGL, which jsdom does not have, so the manager is driven
 * against a **stub scene** here and the rendering itself is verified in a real
 * browser. What that leaves testable is exactly the part that has historically
 * broken: what reaches the hidden input, what comes back, and what survives an
 * instance switch.
 *
 * That last one is not hypothetical. The image manager shipped **three**
 * separate cross-instance data-corruption bugs, every one of them from state
 * that was not a fabric object and so was missed by a canvas-scoped clear. In
 * this manager *nothing* is scene-managed, so `clearAnnotations` has to name
 * every field, and these tests are what stop the next one being forgotten.
 */

require('../../potato/static/pointcloud/pc-wire.js');
const Manager = require('../../potato/static/pointcloud/pc-viewer.js');

/** A manager with just enough state to exercise the data path, no WebGL. */
function makeManager(config) {
    const m = Object.create(Manager.prototype);
    m.config = Object.assign({
        schema: 'objects',
        labels: [{ name: 'car', color: '#ff0000' },
                 { name: 'person', color: '#0000ff' }],
    }, config || {});
    m.inputId = 'input-objects';
    m.annotations = [];
    m.meshes = [];
    m.history = [];
    m.historyIndex = -1;
    m.maxHistory = 50;
    m.currentTool = null;
    m._hiddenLabels = null;
    // Scene stub: records what was added and removed so leaks are visible.
    m.scene = { added: [], removed: [],
                add(o) { this.added.push(o); },
                remove(o) { this.removed.push(o); } };
    m._render = jest.fn();
    m._buildMesh = function (obj) { this.meshes.push({ obj, visible: true }); };
    return m;
}

function cuboid(label, color, center) {
    return {
        type: 'cuboid_3d', label, color,
        coordinates: { center, size: [4, 2, 1.5], rotation: [0, 0, 0, 1] },
    };
}

beforeEach(() => {
    document.body.innerHTML = '<input type="hidden" id="input-objects" value="">';
});

describe('addAnnotation', () => {
    test('accepts a client-contract cuboid and writes it to the input', () => {
        const m = makeManager();
        expect(m.addAnnotation(cuboid('car', '#ff0000', [1, 2, 3]))).toBe(true);

        const stored = JSON.parse(document.getElementById('input-objects').value);
        expect(stored).toHaveLength(1);
        expect(stored[0].type).toBe('cuboid_3d');
        expect(stored[0].coordinates.center).toEqual([1, 2, 3]);
    });

    test('coordinates are stored as given, never normalized', () => {
        // The single most likely mistake when copying the 2D manager: image
        // annotations are normalized to [0, 1], 3D is absolute metres.
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [123.5, -47.25, 2.0]));
        const stored = JSON.parse(document.getElementById('input-objects').value);
        expect(stored[0].coordinates.center).toEqual([123.5, -47.25, 2.0]);
    });

    test('refuses a type outside the contract instead of storing it', () => {
        // An unknown type reaches the exporter and becomes an annotation
        // nothing can read. Better to refuse loudly at the entry point.
        const m = makeManager();
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
        expect(m.addAnnotation({ type: 'bbox', label: 'car' })).toBe(false);
        expect(m.addAnnotation(null)).toBe(false);
        expect(m.annotations).toHaveLength(0);
        expect(warn).toHaveBeenCalled();
        warn.mockRestore();
    });

    test('every accepted annotation gets exactly one mesh slot', () => {
        // Meshes are addressed by the same index as annotations, so a missing
        // slot silently shifts every later annotation's mesh.
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.addAnnotation({ type: 'point_3d', label: 'person', color: '#00f',
                          coordinates: [1, 1, 1] });
        expect(m.meshes).toHaveLength(2);
        expect(m.annotations).toHaveLength(2);
    });
});

describe('handles match the serialized list', () => {
    test('index is identity, in serialization order', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.addAnnotation(cuboid('person', '#0000ff', [5, 0, 0]));

        const handles = m.getAnnotationHandles();
        const serialized = JSON.parse(m.serialize());
        expect(handles.map((h) => h.label)).toEqual(
            serialized.map((a) => a.label));
        expect(handles.map((h) => h.index)).toEqual([0, 1]);
    });

    test('deleting shifts the handles and the input together', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.addAnnotation(cuboid('person', '#0000ff', [5, 0, 0]));

        expect(m.deleteAnnotation(0)).toBe(true);
        expect(m.getAnnotationHandles().map((h) => h.label)).toEqual(['person']);
        expect(JSON.parse(m.serialize()).map((a) => a.label)).toEqual(['person']);
        expect(m.meshes).toHaveLength(1);
        expect(m.scene.removed).toHaveLength(1);
    });

    test('deleting out of range is a no-op, not a corruption', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        expect(m.deleteAnnotation(7)).toBe(false);
        expect(m.deleteAnnotation(-1)).toBe(false);
        expect(m.annotations).toHaveLength(1);
    });
});

describe('relabel', () => {
    test('moves the colour with the label', () => {
        // A shape keeping the old class's colour reads as still being that
        // class on every later glance.
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        expect(m.relabelAnnotation(0, 'person')).toBe(true);

        const stored = JSON.parse(m.serialize())[0];
        expect(stored.label).toBe('person');
        expect(stored.color).toBe('#0000ff');
    });

    test('refuses a label that is not in the schema', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        expect(m.relabelAnnotation(0, 'unicorn')).toBe(false);
        expect(JSON.parse(m.serialize())[0].label).toBe('car');
    });

    test('geometry is untouched', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [1.5, 2.5, 3.5]));
        m.relabelAnnotation(0, 'person');
        expect(JSON.parse(m.serialize())[0].coordinates.center)
            .toEqual([1.5, 2.5, 3.5]);
    });
});

describe('restore from the hidden input', () => {
    test('round-trips through serialize and restore', () => {
        const first = makeManager();
        first.addAnnotation(cuboid('car', '#ff0000', [1, 2, 3]));
        first.addAnnotation({ type: 'polyline_3d', label: 'person',
                              color: '#0000ff',
                              coordinates: [[0, 0, 0], [1, 1, 1]] });
        const saved = first.serialize();

        // A fresh manager on the same instance: the navigate-away-and-back path.
        document.getElementById('input-objects').value = saved;
        const second = makeManager();
        second._restoreFromInput();

        expect(second.serialize()).toBe(saved);
        expect(second.meshes).toHaveLength(2);
    });

    test('a malformed stored value is ignored rather than thrown', () => {
        // One bad blob must not take down the whole annotation page.
        document.getElementById('input-objects').value = '{not json';
        const m = makeManager();
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
        expect(() => m._restoreFromInput()).not.toThrow();
        expect(m.annotations).toEqual([]);
        warn.mockRestore();
    });

    test('a stored object rather than an array is ignored', () => {
        document.getElementById('input-objects').value = '{"a": 1}';
        const m = makeManager();
        m._restoreFromInput();
        expect(m.annotations).toEqual([]);
    });

    test('an empty input restores nothing and does not crash', () => {
        const m = makeManager();
        m._restoreFromInput();
        expect(m.annotations).toEqual([]);
    });
});

describe('clearAnnotations', () => {
    test('empties every piece of state that survives an instance switch', () => {
        // This runs on EVERY instance switch. Anything left behind is
        // attributed to the next item — three separate bugs of exactly this
        // shape shipped in the image manager.
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.addAnnotation(cuboid('person', '#0000ff', [5, 0, 0]));
        m.setTool = () => {};
        m.currentTool = 'cuboid_3d';

        m.clearAnnotations();

        expect(m.annotations).toEqual([]);
        expect(m.meshes).toEqual([]);
        expect(m.currentTool).toBeNull();
        expect(m.history).toEqual([]);
        expect(m.historyIndex).toBe(-1);
        expect(document.getElementById('input-objects').value).toBe('[]');
    });

    test('every mesh is removed from the scene, not just dropped', () => {
        // Dropping the array without removing from the scene leaves the
        // previous item's boxes floating over the next cloud.
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.addAnnotation(cuboid('person', '#0000ff', [5, 0, 0]));
        m.clearAnnotations();
        expect(m.scene.removed).toHaveLength(2);
    });

    test('a cleared manager serializes as empty for the next item', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.clearAnnotations();
        expect(JSON.parse(m.serialize())).toEqual([]);
        expect(m.getAnnotationCount()).toBe(0);
    });
});

describe('applyLabelVisibility', () => {
    test('hides only the named class', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.addAnnotation(cuboid('person', '#0000ff', [5, 0, 0]));

        m.applyLabelVisibility(new Set(['car']));
        expect(m.meshes.map((x) => x.visible)).toEqual([false, true]);
    });

    test('hiding never removes anything from what gets saved', () => {
        // Presentation only. A hidden class must still export.
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.addAnnotation(cuboid('person', '#0000ff', [5, 0, 0]));

        m.applyLabelVisibility(new Set(['car', 'person']));
        expect(JSON.parse(m.serialize()).map((a) => a.label))
            .toEqual(['car', 'person']);
    });

    test('showing everything again restores them', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.applyLabelVisibility(new Set(['car']));
        m.applyLabelVisibility(new Set());
        expect(m.meshes.every((x) => x.visible)).toBe(true);
    });
});

describe('undo and redo', () => {
    test('undo removes the last annotation and rewrites the input', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.addAnnotation(cuboid('person', '#0000ff', [5, 0, 0]));

        expect(m.undo()).toBe(true);
        expect(JSON.parse(m.serialize()).map((a) => a.label)).toEqual(['car']);
        // The input is what the save path reads; leaving it stale would keep
        // the undone annotation in the saved record.
        expect(JSON.parse(document.getElementById('input-objects').value))
            .toHaveLength(1);
    });

    test('redo puts it back', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        m.addAnnotation(cuboid('person', '#0000ff', [5, 0, 0]));
        m.undo();
        expect(m.redo()).toBe(true);
        expect(JSON.parse(m.serialize())).toHaveLength(2);
    });

    test('undo past the beginning and redo past the end are no-ops', () => {
        const m = makeManager();
        m.addAnnotation(cuboid('car', '#ff0000', [0, 0, 0]));
        for (let i = 0; i < 8; i++) m.undo();
        for (let i = 0; i < 8; i++) m.redo();
        expect(JSON.parse(m.serialize())).toHaveLength(1);
    });
});

describe('finding the cloud for an item', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    test('reads a display field wired to the schema', () => {
        document.body.innerHTML =
            '<div data-field-key="point_cloud" data-source-url="scans/a.pcd"></div>';
        const m = makeManager({ sourceField: 'point_cloud' });
        expect(m._cloudUrl()).toBe('/media/pointcloud/scans/a.pcd');
    });

    test('falls back to the instance text, which is where text_key lands', () => {
        document.body.innerHTML = '<div id="text-content">scene_0001.bin</div>';
        const m = makeManager({ sourceField: 'point_cloud' });
        expect(m._cloudUrl()).toBe('/media/pointcloud/scene_0001.bin');
    });

    test('max_points rides along when the schema sets it', () => {
        document.body.innerHTML = '<div id="text-content">a.bin</div>';
        const m = makeManager({ maxPoints: 250000 });
        expect(m._cloudUrl()).toBe('/media/pointcloud/a.bin?max_points=250000');
    });

    test('prose is not mistaken for a path', () => {
        // Otherwise a text item next to this schema produces a request for the
        // sentence it contains, and the 404 blames the wrong thing.
        document.body.innerHTML =
            '<div id="text-content">The van is crossing from the left.</div>';
        expect(makeManager()._cloudUrl()).toBeNull();
    });

    test('a remote cloud still goes through the converter', () => {
        // The browser must never be handed PCD or LAS directly.
        document.body.innerHTML =
            '<div data-field-key="point_cloud" data-source-url="https://x.test/a.las"></div>';
        expect(makeManager()._cloudUrl()).toContain('/media/pointcloud/');
    });

    test.each([
        ['a.pcd', true], ['a.PLY', true], ['scan.bin', true], ['a.las', true],
        ['a.xyz', true], ['a.png', false], ['', false], ['notes', false],
        ['two words.bin', false],
    ])('looksLikeCloud(%s) === %s', (value, expected) => {
        expect(Manager.looksLikeCloud(value)).toBe(expected);
    });
});

describe('sibling modules', () => {
    /**
     * The viewer resolves pc-wire, pc-calibration, pc-octree and pc-mpr into
     * module-level consts. Forgetting one is a plain ReferenceError at first
     * use — and because the schema attaches the manager to the container
     * BEFORE calling init(), a throw in init leaves a half-built manager that
     * every readiness check still accepts. The viewer then sits there silently
     * dead: no cloud, no panels, no error.
     *
     * Adding the MPR panels shipped exactly that. These tests make a missing
     * sibling a two-second failure instead.
     */
    test('every sibling module is loadable from the viewer directory', () => {
        ['pc-wire.js', 'pc-calibration.js', 'pc-octree.js', 'pc-mpr.js']
            .forEach((name) => {
                const mod = require(`../../potato/static/pointcloud/${name}`);
                expect(mod).toBeTruthy();
            });
    });

    test('the viewer names each of them', () => {
        // Source-level, because the consts are closed over by the IIFE and are
        // not reachable from the exported class.
        const fs = require('fs');
        const src = fs.readFileSync(
            require.resolve('../../potato/static/pointcloud/pc-viewer.js'),
            'utf8');
        ['PointCloudWire', 'PointCloudCalibration', 'PointCloudOctree',
         'PointCloudMPR'].forEach((global) => {
            expect(src).toContain(global);
        });
    });

    test('every global the viewer reads is declared as a const', () => {
        // The actual defect: `root.PointCloudMPR` was referenced through a
        // local name that was never declared, so the global existing was not
        // enough.
        const fs = require('fs');
        const src = fs.readFileSync(
            require.resolve('../../potato/static/pointcloud/pc-viewer.js'),
            'utf8');
        ['wire', 'calib', 'octree', 'mpr'].forEach((name) => {
            expect(src).toMatch(
                new RegExp(`const ${name} = \\(root && root\\.PointCloud`));
        });
    });
});

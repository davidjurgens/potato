/**
 * Point-cloud sequences: the store of keyframes, the per-frame view the
 * viewer edits, and the merge between them (pc-sequence.js), plus the
 * viewer's frame navigation, copy-forward and delete-track.
 */

window.ObjectAttributes = require('../../potato/static/object-attributes.js');
require('../../potato/static/pointcloud/pc-wire.js');
const seq = require('../../potato/static/pointcloud/pc-sequence.js');
window.PointCloudSequence = seq;
const Manager = require('../../potato/static/pointcloud/pc-viewer.js');

function box(frame, track, x, extra) {
    return Object.assign({
        type: 'cuboid_3d', label: 'car', color: '#f00', frame, track_id: track,
        attributes: {},
        coordinates: { center: [x, 0, 0], size: [4, 2, 1.5], rotation: [0, 0, 0, 1] },
    }, extra || {});
}

describe('pc-sequence', () => {
    test('a list or a {frames} object is a sequence; a path is not', () => {
        expect(seq.framesOf(['a.bin', 'b.bin'])).toEqual(['a.bin', 'b.bin']);
        expect(seq.framesOf({ frames: ['a.bin'], fps: 10 })).toEqual(['a.bin']);
        expect(seq.framesOf('a.bin')).toBeNull();
    });

    test('between keyframes the box is interpolated; outside them it is absent', () => {
        const store = [box(0, 't1', 0), box(4, 't1', 8)];
        const [mid] = seq.viewAt(store, 1);
        expect(mid.interpolated).toBe(true);
        expect(mid.coordinates.center[0]).toBeCloseTo(2);
        expect(seq.viewAt(store, 4)[0].interpolated).toBeUndefined();
        expect(seq.viewAt(store, 5)).toEqual([]);
    });

    test('an untouched interpolation is not stored; an edited one becomes a keyframe', () => {
        const store = [box(0, 't1', 0), box(4, 't1', 8)];
        const view = seq.viewAt(store, 2);
        expect(seq.mergeView(store, 2, view)).toHaveLength(2);
        view[0].coordinates.center = [5, 0, 0];
        const merged = seq.mergeView(store, 2, view);
        expect(merged.map((k) => k.frame).sort()).toEqual([0, 2, 4]);
        expect(merged.find((k) => k.frame === 2)).not.toHaveProperty('_from');
        expect(view[0].interpolated).toBeUndefined();
    });

    test('rounding from the origin shift is not an edit', () => {
        const store = [box(0, 't1', 0), box(4, 't1', 8)];
        const view = seq.viewAt(store, 1);
        view[0].coordinates.center = view[0].coordinates.center.map((v) => v + 4e-7);
        expect(seq.mergeView(store, 1, view)).toHaveLength(2);
    });

    test('a new object gets the frame and a fresh track id', () => {
        const store = [box(0, 't1', 0), box(0, 't7', 3)];
        const fresh = box(undefined, undefined, 9);
        delete fresh.track_id;
        const merged = seq.mergeView(store, 0, seq.viewAt(store, 0).concat([fresh]));
        expect(merged.find((k) => k.coordinates.center[0] === 9))
            .toMatchObject({ frame: 0, track_id: 't8' });
    });

    test('label and attributes set on one frame apply to the whole track', () => {
        const store = [box(0, 't1', 0), box(4, 't1', 8)];
        const view = seq.viewAt(store, 2);       // interpolated, geometry untouched
        view[0].attributes = { occluded: 'partial' };
        view[0].label = 'truck';
        const merged = seq.mergeView(store, 2, view);
        expect(merged).toHaveLength(2);
        merged.forEach((k) => expect(k).toMatchObject({ label: 'truck',
                                                        attributes: { occluded: 'partial' } }));
    });

    test('a keyframe missing from the view was deleted', () => {
        const store = [box(0, 't1', 0), box(2, 't1', 2), box(4, 't1', 4)];
        expect(seq.mergeView(store, 2, []).map((k) => k.frame)).toEqual([0, 4]);
    });

    test('rotation interpolates the short way round', () => {
        const yaw = (deg) => [0, 0, Math.sin(deg * Math.PI / 360), Math.cos(deg * Math.PI / 360)];
        const store = [box(0, 't1', 0, { coordinates: { center: [0, 0, 0], size: [1, 1, 1], rotation: yaw(170) } }),
                       box(2, 't1', 0, { coordinates: { center: [0, 0, 0], size: [1, 1, 1], rotation: yaw(-170) } })];
        const [x, y, z, w] = seq.viewAt(store, 1)[0].coordinates.rotation;
        expect(Math.abs(Math.abs(2 * Math.atan2(z, w) * 180 / Math.PI) - 180)).toBeLessThan(1e-6);
    });
});

describe('viewer on a sequence', () => {
    function makeManager(stored) {
        document.body.innerHTML = `
          <div class="pointcloud-annotation-container annotation-form">
            <div data-instance-json='${JSON.stringify({ id: 's1', point_cloud: ['f0.bin', 'f1.bin', 'f2.bin', 'f3.bin'] })}'></div>
            <input type="hidden" id="input-objects" value='${JSON.stringify(stored || [])}'>
            <div class="pc-frames" hidden>
              <button data-frame-step="-1"></button><input type="range" class="pc-frame-slider">
              <button data-frame-step="1"></button><span class="pc-frame-label"></span>
              <button data-frame-action="copy-forward"></button>
              <button data-frame-action="delete-track"></button>
            </div>
            <p class="pc-status"></p><p class="pc-announce" aria-live="polite"></p>
          </div>`;
        const m = new Manager('pc-canvas-objects', 'input-objects',
                              { schema: 'objects', labels: [{ name: 'car', color: '#f00' }] });
        const container = document.querySelector('.pointcloud-annotation-container');
        Object.assign(m, {
            container,
            scene: { add() {}, remove() {} }, _render: () => {}, _drawOverlays: () => {},
            _buildMesh(obj) { this.meshes.push({ obj, material: {} }); },
            _loadCloud: jest.fn(),
            currentLabel: 'car', currentColor: '#f00',
        });
        m.frames = seq.framesOf(['f0.bin', 'f1.bin', 'f2.bin', 'f3.bin']);
        m._bindFrames();
        m._restoreFromInput();
        return m;
    }
    const stored = () => JSON.parse(document.getElementById('input-objects').value);

    test('the frame bar shows, and the cloud path follows the frame', () => {
        const m = makeManager();
        expect(document.querySelector('.pc-frames').hidden).toBe(false);
        expect(m._cloudPath()).toBe('f0.bin');
        m.goToFrame(2);
        expect(m._cloudPath()).toBe('f2.bin');
        expect(m._loadCloud).toHaveBeenCalled();
        expect(document.querySelector('.pc-frame-label').textContent).toBe('Frame 3 of 4');
    });

    test('copy forward, move, and the frame between is interpolated, not stored', () => {
        const m = makeManager();
        m._addLocal(box(undefined, undefined, 0));
        m.selectedIndex = 0;
        m.copyForward();                         // keyframe at 1, now on frame 1
        m.copyForward();                         // keyframe at 2, now on frame 2
        expect(m.frameIndex).toBe(2);
        m.annotations[m.selectedIndex].coordinates.center = [6, 0, 0];
        m._updateAnnotationData();
        m._mergeFrame();
        // Drop the middle keyframe: frame 1 is then interpolated between 0 and 2.
        m.goToFrame(1);
        m.selectedIndex = 0;
        m.deleteAnnotation(0);
        m.goToFrame(1, 't1');
        expect(m.annotations[0].interpolated).toBe(true);
        expect(m.annotations[0].coordinates.center[0]).toBeCloseTo(3);
        expect(stored().map((k) => [k.frame, k.track_id])).toEqual([[0, 't1'], [2, 't1']]);
        expect(stored()[0]).not.toHaveProperty('interpolated');
    });

    test('deleting a middle keyframe leaves the interpolation in its place', () => {
        const m = makeManager([box(0, 't1', 0), box(1, 't1', 5), box(2, 't1', 2)]);
        m.goToFrame(1);
        expect(m.deleteAnnotation(0)).toBe(true);
        expect(m.annotations).toHaveLength(1);
        expect(m.annotations[0].interpolated).toBe(true);
        expect(m.annotations[0].coordinates.center[0]).toBeCloseTo(1);
        expect(stored().map((k) => k.frame)).toEqual([0, 2]);
    });

    test('an interpolated object cannot be deleted on its own; delete track removes it', () => {
        const m = makeManager([box(0, 't1', 0), box(2, 't1', 2)]);
        m.goToFrame(1);
        expect(m.deleteAnnotation(0)).toBe(false);
        expect(document.querySelector('.pc-status').textContent).toMatch(/interpolated/);
        m.selectedIndex = 0;
        m.deleteSelectedTrack();
        expect(stored()).toEqual([]);
    });

    test('restored keyframes come back on their frames', () => {
        const m = makeManager([box(0, 't1', 0), box(3, 't1', 3)]);
        expect(m.annotations).toHaveLength(1);
        m.goToFrame(3);
        expect(m.annotations[0].interpolated).toBeUndefined();
        expect(m.annotations[0].coordinates.center[0]).toBe(3);
    });
});

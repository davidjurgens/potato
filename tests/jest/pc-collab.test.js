/**
 * Live collaborative sessions: the point cloud viewer's applier
 * (window.potatoCollabWidgets.spatial_annotation) and collision-proof ids.
 *
 * collab.js writes a teammate's answer into the hidden input, then calls
 * apply(ctx). The viewer keeps its own copy of the objects, so apply must
 * replace that copy and redraw, without saving. WebGL is stubbed: the scene
 * records what is in it, which is what the canvas would draw.
 */

window.ObjectAttributes = require('../../potato/static/object-attributes.js');
require('../../potato/static/pointcloud/pc-wire.js');
const seq = require('../../potato/static/pointcloud/pc-sequence.js');
window.PointCloudSequence = seq;
const Manager = require('../../potato/static/pointcloud/pc-viewer.js');

const SCHEMA = 'objects';

function cuboid(label, x, extra) {
    return Object.assign({
        type: 'cuboid_3d', label, color: label === 'car' ? '#ff0000' : '#0000ff',
        coordinates: { center: [x, 0, 0], size: [4, 2, 1.5], rotation: [0, 0, 0, 1] },
    }, extra || {});
}

/** The generator's container markup (spatial_annotation.py), trimmed. */
function markup(stored, frames) {
    const record = frames ? { id: 's1', point_cloud: frames } : { id: 'i1', point_cloud: 'a.bin' };
    return `
      <div data-instance-json='${JSON.stringify(record)}'></div>
      <div class="pointcloud-annotation-container annotation-form" data-schema="${SCHEMA}"
           data-annotation-type="spatial_annotation" data-schema-name="${SCHEMA}">
        <fieldset>
          <canvas id="pc-canvas-${SCHEMA}" class="pc-canvas"></canvas>
          <p class="pc-status" id="pc-status-${SCHEMA}"></p>
          <div class="pc-frames" hidden>
            <button type="button" class="tool-btn" data-frame-step="-1"></button>
            <input type="range" class="pc-frame-slider" min="0" max="0" value="0">
            <button type="button" class="tool-btn" data-frame-step="1"></button>
            <span class="pc-frame-label" aria-live="polite">Frame 1 of 1</span>
            <button type="button" class="tool-btn" data-frame-action="copy-forward"></button>
            <button type="button" class="tool-btn" data-frame-action="delete-track"></button>
          </div>
          <p class="pc-announce" id="pc-announce-${SCHEMA}"></p>
          <input type="hidden" name="${SCHEMA}" id="input-${SCHEMA}"
                 class="annotation-data-input" value='${JSON.stringify(stored || [])}'>
        </fieldset>
      </div>`;
}

/** A viewer on the generator's markup, with a scene that records its meshes. */
function makePage(stored, frames) {
    document.body.innerHTML = markup(stored, frames);
    const m = new Manager(`pc-canvas-${SCHEMA}`, `input-${SCHEMA}`, {
        schema: SCHEMA,
        labels: [{ name: 'car', color: '#ff0000' }, { name: 'person', color: '#0000ff' }],
    });
    const container = document.querySelector('.pointcloud-annotation-container');
    const live = new Set();
    Object.assign(m, {
        container,
        canvas: document.getElementById(`pc-canvas-${SCHEMA}`),
        scene: { add(o) { live.add(o); }, remove(o) { live.delete(o); } },
        _render: () => {}, _loadCloud: jest.fn(),
        _buildMesh(obj) { const mesh = { label: obj.label, x: (obj.coordinates.center || obj.coordinates)[0], material: {} }; this.scene.add(mesh); this.meshes.push(mesh); },
        currentLabel: 'car', currentColor: '#ff0000',
    });
    if (frames) {
        m.frames = seq.framesOf(frames);
        m._bindFrames();
    }
    m._restoreFromInput();
    container.annotationManager = m;
    return { m, live, input: document.getElementById(`input-${SCHEMA}`) };
}

/** What collab.js does: answer into the input, then apply(ctx). */
function applyTeammate(value) {
    const input = document.getElementById(`input-${SCHEMA}`);
    const json = value === null ? '' : JSON.stringify(value);
    input.value = json;
    input.setAttribute('value', json);
    const widget = (window.potatoCollabWidgets || {}).spatial_annotation;
    if (!widget) return false;
    return widget.apply({
        schema: SCHEMA,
        form: document.querySelector(`[data-schema-name="${SCHEMA}"]`),
        input, inputs: [], value: json || null,
        labels: json ? { _data: json } : null,
    });
}

const drawn = (live) => [...live].map((mesh) => `${mesh.label}@${mesh.x}`).sort();

describe('spatial_annotation live applier', () => {
    let fetchSpy;
    beforeEach(() => {
        fetchSpy = jest.fn(() => Promise.resolve({ ok: true, json: () => ({}) }));
        global.fetch = fetchSpy;
        window.saveAnnotations = jest.fn();
    });

    test('a teammate answer replaces what this page draws', () => {
        const { m, live } = makePage([cuboid('car', 0, { id: 'a' })]);
        expect(drawn(live)).toEqual(['car@0']);
        expect(applyTeammate([cuboid('person', 5, { id: 'b' }), cuboid('car', 9, { id: 'c' })])).toBe(true);
        expect(drawn(live)).toEqual(['car@9', 'person@5']);
        expect(m.annotations.map((a) => a.id)).toEqual(['b', 'c']);
    });

    test('null clears every object', () => {
        const { m, live } = makePage([cuboid('car', 0), cuboid('person', 3)]);
        expect(applyTeammate(null)).toBe(true);
        expect(drawn(live)).toEqual([]);
        expect(m.annotations).toEqual([]);
    });

    test('applying saves nothing', () => {
        const { input } = makePage([cuboid('car', 0)]);
        const changed = jest.fn();
        input.addEventListener('change', changed);
        expect(applyTeammate([cuboid('person', 5)])).toBe(true);
        expect(fetchSpy).not.toHaveBeenCalled();
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(changed).not.toHaveBeenCalled();
        expect(input.hasAttribute('data-modified')).toBe(false);
    });

    test('applying twice does not duplicate', () => {
        const { m, live } = makePage([]);
        const answer = [cuboid('person', 5, { id: 'b' })];
        applyTeammate(answer);
        applyTeammate(answer);
        expect(drawn(live)).toEqual(['person@5']);
        expect(m.meshes).toHaveLength(1);
    });

    test('the selection follows its object by id', () => {
        const { m } = makePage([cuboid('car', 0, { id: 'a' }), cuboid('car', 2, { id: 'k' })]);
        m.selectedIndex = 1;
        applyTeammate([cuboid('person', 5, { id: 'b' }), cuboid('car', 2, { id: 'a' }), cuboid('car', 7, { id: 'k' })]);
        expect(m.selectedIndex).toBe(2);
        expect(m.annotations[m.selectedIndex].id).toBe('k');
    });

    test('a sequence: the store is replaced and the frame stays', () => {
        const frames = ['f0.bin', 'f1.bin', 'f2.bin'];
        const { m, live } = makePage([cuboid('car', 0, { frame: 0, track_id: 't1', id: 'k0' })], frames);
        m.goToFrame(1);
        applyTeammate([cuboid('person', 4, { frame: 1, track_id: 't2_zz', id: 'k1' }),
                       cuboid('car', 6, { frame: 1, track_id: 't3_zz', id: 'k2' })]);
        expect(m.frameIndex).toBe(1);
        expect(drawn(live)).toEqual(['car@6', 'person@4']);
        expect(document.querySelector('.pc-frame-label').textContent).toBe('Frame 2 of 3 (2 keyframes)');
        applyTeammate(null);
        expect(drawn(live)).toEqual([]);
        expect(document.querySelector('.pc-frame-label').textContent).toBe('Frame 2 of 3');
    });

    test('no viewer for the scheme: false, so the page shows the banner', () => {
        document.body.innerHTML = markup([]);
        expect(applyTeammate([cuboid('car', 0)])).toBe(false);
    });
});

describe('point cloud ids do not collide across pages', () => {
    /** A fresh page: the viewer and sequence modules loaded anew. */
    function freshModules() {
        let mods;
        jest.isolateModules(() => {
            require('../../potato/static/pointcloud/pc-wire.js');
            const s = require('../../potato/static/pointcloud/pc-sequence.js');
            window.PointCloudSequence = s;
            mods = { seq: s, Manager: require('../../potato/static/pointcloud/pc-viewer.js') };
        });
        window.PointCloudSequence = seq;
        return mods;
    }

    test('two pages each drawing their first object get different ids', () => {
        const a = freshModules();
        const b = freshModules();
        expect(a.Manager.newObjectId()).not.toEqual(b.Manager.newObjectId());
    });

    test('a drawn object gets an id; one that arrives with an id keeps it', () => {
        const { m, input } = makePage([]);
        m._addLocal(cuboid('car', 0));
        m._addLocal(cuboid('car', 1, { id: 'imported-7' }));
        const stored = JSON.parse(input.value);
        expect(stored[0].id).toMatch(/^pc_[a-z0-9]+_\d+$/);
        expect(stored[1].id).toBe('imported-7');
    });

    test('two pages each starting their first track get different track ids', () => {
        const a = freshModules().seq;
        const b = freshModules().seq;
        const first = (s) => s.mergeView([], 0, [cuboid('car', 0)])[0];
        const ta = first(a), tb = first(b);
        expect(ta.track_id).toMatch(/^t1_[a-z0-9]+$/);
        expect(ta.track_id).not.toEqual(tb.track_id);
        expect(ta.id).not.toEqual(tb.id);
    });

    test('numbering continues past restored ids, old and new form, which stay as stored', () => {
        const store = [cuboid('car', 0, { frame: 0, track_id: 't7' }),
                       cuboid('car', 1, { frame: 0, track_id: 't9_abc123' })];
        const merged = seq.mergeView(store, 0, seq.viewAt(store, 0).concat([cuboid('car', 2)]));
        expect(merged.map((k) => k.track_id).slice(0, 2)).toEqual(['t7', 't9_abc123']);
        expect(merged[2].track_id).toMatch(/^t10_[a-z0-9]+$/);
        expect(merged[0]).not.toHaveProperty('id');
    });

    test('each keyframe is its own element: copy forward and an edited interpolation get new ids', () => {
        const k0 = cuboid('car', 0, { frame: 0, track_id: 't1', id: 'k0' });
        const copied = seq.copyForward([k0], k0, 0);
        expect(copied[1].id).not.toEqual('k0');
        const store = [k0, cuboid('car', 4, { frame: 2, track_id: 't1', id: 'k2' })];
        const view = seq.viewAt(store, 1);
        view[0].coordinates.center = [9, 9, 0];
        const merged = seq.mergeView(store, 1, view);
        const ids = merged.map((k) => k.id);
        expect(new Set(ids).size).toBe(3);
        expect(ids).toEqual(expect.arrayContaining(['k0', 'k2']));
    });
});

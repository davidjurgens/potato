/**
 * Live collaborative sessions: the DICOM volume viewer's applier
 * (window.potatoCollabWidgets.volume_annotation) and collision-proof shape ids.
 *
 * collab.js writes a teammate's answer into the hidden input, then calls
 * apply(ctx). The viewer holds its masks and shapes itself, so apply must
 * replace them and redraw, without saving. Masks load label by label, so a
 * label missing from the new answer (or a null answer) must still be cleared.
 *
 * The canvases are mocked: each overlay records what it drew since its last
 * clearRect, which is what the annotator sees on that slice.
 */

const SCHEMA = 'organs';
const N = 4;   // a 4 x 4 x 4 volume; the cursor starts on axial slice 2

/** The generator's markup (volume_annotation.py), axial view only. */
function markup(stored, record) {
    return `
      <div data-instance-json='${JSON.stringify(record || { id: 'v1', volume: 'ct/case1.nii.gz' })}'></div>
      <div class="volume-annotation-container annotation-form" data-schema="${SCHEMA}"
           data-annotation-type="volume_annotation" data-schema-name="${SCHEMA}" data-grid-columns="1">
        <fieldset>
          <legend>Segment</legend>
          <div class="vol-toolbar" role="toolbar" aria-label="Volume tools">
            <button type="button" class="tool-btn" data-tool="navigate" aria-pressed="false">Navigate</button><button type="button" class="tool-btn" data-tool="brush" aria-pressed="false">Brush</button><button type="button" class="tool-btn" data-tool="box" aria-pressed="false">Box</button>
            <label class="vol-brush">Brush
              <input type="range" class="vol-brush-size" min="1" max="15" step="0.5" value="2.0"></label>
            <label class="vol-window">Window <select class="vol-window-select"></select></label>
            <button type="button" class="tool-btn" data-action="interpolate">Interpolate</button>
            <button type="button" class="tool-btn" data-action="undo">Undo</button>
          </div>
          <div class="vol-labels" role="group" aria-label="Labels"><button type="button" class="vol-label-btn" data-label="liver" aria-pressed="false"><span class="vol-label-dot" aria-hidden="true"></span>liver</button><button type="button" class="vol-label-btn" data-label="kidney" aria-pressed="false"><span class="vol-label-dot" aria-hidden="true"></span>kidney</button></div>
          <div class="vol-views"><div class="vol-view" data-axis="axial"><div class="vol-view-head"><span class="vol-view-name">Axial</span><span class="vol-slice-label" data-slice-label="axial"></span></div><div class="vol-stage" tabindex="0" role="application"><canvas class="vol-image"></canvas><canvas class="vol-overlay"></canvas></div><input type="range" class="vol-slider" data-axis="axial" min="0" max="0" value="0"></div></div>
          <dl class="vol-tags" hidden></dl>
          <ul class="vol-shapes" aria-label="Boxes and polygons"></ul>
          <p class="vol-status" role="status" aria-live="polite"></p>
          <input type="hidden" name="${SCHEMA}" id="input-${SCHEMA}"
                 class="annotation-data-input" value='${stored ? JSON.stringify(stored) : ''}'>
        </fieldset>
      </div>`;
}

// Canvas and ImageData, which jsdom lacks.
global.ImageData = class {
    constructor(w, h) { this.width = w; this.height = h; this.data = new Uint8ClampedArray(w * h * 4); }
};
HTMLCanvasElement.prototype.getContext = function () {
    if (this._ctx) return this._ctx;
    const canvas = this;
    const ops = [];
    this._ops = ops;
    this._ctx = {
        clearRect() { ops.length = 0; },
        putImageData(image) { canvas._image = image; },
        drawImage(src) {
            const colours = {};
            const d = (src._image || { data: [] }).data;
            for (let p = 0; p < d.length; p += 4) {
                if (d[p + 3]) { const k = `${d[p]},${d[p + 1]},${d[p + 2]}`; colours[k] = (colours[k] || 0) + 1; }
            }
            ops.push({ op: 'mask', colours });
        },
        rect() { ops.push({ op: 'rect' }); },
        strokeRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, closePath() {}, stroke() {},
        setLineDash() {},
    };
    return this._ctx;
};

require('../../potato/static/volume-annotation.js');
const RLE = window.VolumeAnnotationRLE;

/** One axial slice with `cells` (flat i + j * N) set. */
function slice(cells) {
    const plane = new Uint8Array(N * N);
    cells.forEach((c) => { plane[c] = 1; });
    return RLE.encode(plane);
}

function answer(masks, shapes) {
    return { volume: 'ct/case1.nii.gz', shape: [N, N, N], labels: ['liver', 'kidney'],
             masks: masks || {}, shapes: shapes || [] };
}

function box(label, id) {
    return { id, label, axis: 'axial', index: 2, type: 'box', points: [[0, 0, 2], [2, 2, 2]] };
}

/** `prefill`: what /media/volume-tools/prefill returns for the item's RTSTRUCT. */
async function makePage(stored, { prefill } = {}) {
    const record = prefill ? { id: 'v1', volume: 'ct/case1.nii.gz', rtstruct: 'ct/case1.rtstruct.dcm' } : null;
    document.body.innerHTML = markup(stored, record);
    global.fetch = jest.fn((url) => Promise.resolve({
        ok: true,
        json: () => Promise.resolve(String(url).includes('/media/volume-tools/prefill') ? prefill
            : { shape: [N, N, N], spacing: [1, 1, 1], windows: [], tags: {} }),
    }));
    const container = document.querySelector('.volume-annotation-container');
    const m = new window.VolumeAnnotationManager(container, `input-${SCHEMA}`, {
        schema: SCHEMA, sourceField: 'volume', tools: ['navigate', 'brush', 'box'],
        toolKeys: {}, labels: [{ name: 'liver', color: '#ff0000' }, { name: 'kidney', color: '#00ff00' }],
        brushSize: 2, prefillField: prefill ? 'rtstruct' : undefined,
    });
    container.annotationManager = m;
    await m.init();
    global.fetch.mockClear();
    return { m, input: document.getElementById(`input-${SCHEMA}`) };
}

/** What collab.js does: answer into the input, then apply(ctx). */
function applyTeammate(value) {
    const input = document.getElementById(`input-${SCHEMA}`);
    const json = value === null ? '' : JSON.stringify(value);
    input.value = json;
    input.setAttribute('value', json);
    input.removeAttribute('data-modified');
    const widget = (window.potatoCollabWidgets || {}).volume_annotation;
    if (!widget) return false;
    return widget.apply({
        schema: SCHEMA, form: document.querySelector(`[data-schema-name="${SCHEMA}"]`),
        input, inputs: [], value: json || null, labels: json ? { _data: json } : null,
    });
}

/** What the axial overlay shows now: mask pixels by colour, and box count. */
function axial() {
    const ops = document.querySelector('.vol-view[data-axis="axial"] .vol-overlay')._ops;
    const colours = {};
    ops.filter((o) => o.op === 'mask').forEach((o) => Object.assign(colours, o.colours));
    return { colours, boxes: ops.filter((o) => o.op === 'rect').length };
}

const listed = () => Array.from(document.querySelectorAll('.vol-shapes li .vol-shape-go'))
    .map((b) => b.textContent);

describe('volume_annotation live applier', () => {
    beforeEach(() => { window.saveAnnotations = jest.fn(); });

    test('a teammate answer replaces masks and shapes, and a label it lacks is cleared', async () => {
        await makePage(answer({ liver: { 2: slice([0, 1, 2]) } }, [box('liver', 'a')]));
        expect(axial().colours).toEqual({ '255,0,0': 3 });
        expect(listed()).toEqual(['liver: box on axial 3']);

        expect(applyTeammate(answer({ kidney: { 2: slice([5, 6]) } }, [box('kidney', 'b'), box('kidney', 'c')]))).toBe(true);
        expect(axial().colours).toEqual({ '0,255,0': 2 });
        expect(axial().boxes).toBe(2);
        expect(listed()).toEqual(['kidney: box on axial 3', 'kidney: box on axial 3']);
    });

    test('null clears every mask and shape', async () => {
        const { m } = await makePage(answer({ liver: { 2: slice([0, 1]) } }, [box('liver', 'a')]));
        expect(applyTeammate(null)).toBe(true);
        expect(axial()).toEqual({ colours: {}, boxes: 0 });
        expect(listed()).toEqual([]);
        expect(m._hasAnything()).toBe(false);
    });

    test('applying saves nothing', async () => {
        const { input } = await makePage(answer({ liver: { 2: slice([0]) } }));
        const changed = jest.fn();
        input.addEventListener('change', changed);
        expect(applyTeammate(answer({}, [box('kidney', 'b')]))).toBe(true);
        expect(global.fetch).not.toHaveBeenCalled();
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(changed).not.toHaveBeenCalled();
        expect(input.hasAttribute('data-modified')).toBe(false);
    });

    test('applying twice does not duplicate', async () => {
        await makePage(null);
        const a = answer({ liver: { 2: slice([3]) } }, [box('liver', 'b')]);
        applyTeammate(a);
        applyTeammate(a);
        expect(listed()).toHaveLength(1);
        expect(axial()).toEqual({ colours: { '255,0,0': 1 }, boxes: 1 });
    });

    test('before the volume has loaded: false, so the page shows the banner', () => {
        document.body.innerHTML = markup(null);
        const container = document.querySelector('.volume-annotation-container');
        container.annotationManager = new window.VolumeAnnotationManager(
            container, `input-${SCHEMA}`, { schema: SCHEMA, labels: [] });
        expect(applyTeammate(answer())).toBe(false);
    });
});

// An unanswered item starts from its RTSTRUCT (status line and masks); a
// stored answer reloads without either. Live, a teammate's answer must drop
// the status line, and a cleared answer must show the prefill again, without
// saving: the team's answer is still none.
describe('the RTSTRUCT prefill in a live session', () => {
    const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
    const PREFILL = { masks: { liver: { 2: slice([0, 1, 2]) } }, unmatched: [] };
    const status = () => document.querySelector('.vol-status').textContent;

    beforeEach(() => { window.saveAnnotations = jest.fn(); });

    test("a teammate's answer replaces the prefill and its status line", async () => {
        await makePage(null, { prefill: PREFILL });
        expect(status()).toBe("Started from the item's RTSTRUCT.");
        expect(axial().colours).toEqual({ '255,0,0': 3 });

        expect(applyTeammate(answer({ kidney: { 2: slice([5]) } }))).toBe(true);
        await flush();
        expect(status()).toBe('');
        expect(axial().colours).toEqual({ '0,255,0': 1 });
    });

    test('a cleared answer shows the prefill again, without saving', async () => {
        const { m, input } = await makePage(null, { prefill: PREFILL });
        applyTeammate(answer({ kidney: { 2: slice([5]) } }));
        const changed = jest.fn();
        input.addEventListener('change', changed);

        expect(applyTeammate(null)).toBe(true);
        await flush();
        expect(axial().colours).toEqual({ '255,0,0': 3 });
        expect(status()).toBe("Started from the item's RTSTRUCT.");
        expect(m.serialize().prefilled_from).toBe('rtstruct');
        expect(input.value).toBe('');
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(changed).not.toHaveBeenCalled();
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(global.fetch.mock.calls.map((c) => String(c[0])).filter((u) => !u.includes('/prefill')))
            .toEqual([]);
    });

    test("a teammate's answer that arrives while the prefill loads wins", async () => {
        await makePage(null, { prefill: PREFILL });
        applyTeammate(null);
        applyTeammate(answer({ kidney: { 2: slice([5]) } }));
        await flush();
        expect(axial().colours).toEqual({ '0,255,0': 1 });
        expect(status()).toBe('');
    });
});

describe('volume shape ids do not collide across pages', () => {
    function freshModule() {
        let cls;
        jest.isolateModules(() => {
            require('../../potato/static/volume-annotation.js');
            cls = window.VolumeAnnotationManager;
        });
        return cls;
    }

    test('two pages each drawing their first box get different ids', () => {
        const a = freshModule();
        const b = freshModule();
        expect(typeof a.newShapeId).toBe('function');
        expect(a.newShapeId()).not.toEqual(b.newShapeId());
    });

    test('a drawn box is stored with an id', async () => {
        const { m, input } = await makePage(null);
        const view = m.views.axial;
        m.tool = 'box';
        m._box = { view, start: [0, 0], end: [2, 2] };
        m._pointerUp(view);
        const stored = JSON.parse(input.value);
        expect(stored.shapes).toHaveLength(1);
        expect(stored.shapes[0].id).toMatch(/^vol_[a-z0-9]+_\d+$/);
    });
});

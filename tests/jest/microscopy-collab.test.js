/**
 * Live collaborative sessions: the microscopy widget's applier
 * (window.potatoCollabWidgets.microscopy), its restore path
 * (PotatoMicroscopy.reload), and collision-proof region ids.
 *
 * The widget keeps its regions and cells in private state read once at
 * setup, so a teammate's answer written into the hidden input was never
 * shown. collab.js writes the answer into the input (label key
 * `<schema>:::<schema>`), then calls apply(ctx).
 *
 * OpenSeadragon is mocked as an identity viewport 100 px wide; the regions
 * are SVG nodes in `.mic-shapes`, the lists are `.mic-roi-list` and
 * `.mic-cell-list`, all real DOM.
 */

const SCHEMA = 'cells';
const W = 100, H = 80;

/** The generator's markup (microscopy.py), verbatim but for the value. */
function markup(stored) {
    const cfg = JSON.stringify({
        schema: SCHEMA,
        labels: [{ name: 'tumor', color: '#ff0000' }, { name: 'stroma', color: '#00ff00' }],
        cellLabels: [{ name: 'tumor', color: '#ff0000' }, { name: 'stroma', color: '#00ff00' }],
        tools: ['bbox', 'polygon', 'landmark'], minRois: 0, minCells: 0, height: 520,
    }).replace(/"/g, '&quot;');
    const value = stored ? JSON.stringify(stored).replace(/"/g, '&quot;') : '';
    return `
      <input id="instance_id" type="hidden" value="item-1">
      <form id="${SCHEMA}" class="annotation-form microscopy" action="javascript:void(0)"
            data-annotation-type="microscopy" data-schema-name="${SCHEMA}"
            data-microscopy-config='${cfg}' data-grid-columns="1">
        <fieldset schema="${SCHEMA}">
          <legend class="mic-title">Classify</legend>
          <div class="mic-root"><p class="mic-status" role="status">Loading image…</p></div>
          <input type="hidden" class="annotation-input microscopy-input"
                 id="${SCHEMA}_${SCHEMA}_hidden" name="${SCHEMA}:::${SCHEMA}"
                 schema="${SCHEMA}" label_name="${SCHEMA}" validation="" value="${value}">
        </fieldset>
      </form>`;
}

let viewers;
function mockOpenSeadragon() {
    viewers = [];
    const OSD = function (options) {
        const handlers = {};
        const canvas = document.createElement('div');
        options.element.appendChild(canvas);
        const v = {
            handlers,
            canvas,
            addHandler(name, fn) { handlers[name] = fn; },
            destroy() {},
            viewport: {
                viewportToViewerElementCoordinates: (p) => ({ x: p.x * W, y: p.y * W }),
                viewerElementToViewportCoordinates: (p) => ({ x: p.x / W, y: p.y / W }),
            },
        };
        viewers.push(v);
        return v;
    };
    OSD.Point = function (x, y) { this.x = x; this.y = y; };
    window.OpenSeadragon = OSD;
}

// The cell layer is a 2D canvas, which jsdom lacks: keep what was painted.
HTMLCanvasElement.prototype.getContext = function () {
    const canvas = this;
    return this._ctx || (this._ctx = {
        createImageData: (w, h) => ({ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }),
        putImageData(image) { canvas._image = image; },
    });
};

/** Pixels of the cell layer painted in each class colour. */
function cellPaint() {
    const image = document.querySelector('.mic-cell-layer')._image;
    const out = {};
    if (!image) return out;
    for (let p = 0; p < image.data.length; p += 4) {
        const k = `${image.data[p]},${image.data[p + 1]},${image.data[p + 2]}`;
        if (k === '255,0,0' || k === '0,255,0') out[k] = (out[k] || 0) + 1;
    }
    return out;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

/** A page with the widget loaded and its image open. */
async function makePage(stored, { fresh } = {}) {
    document.body.innerHTML = markup(stored);
    mockOpenSeadragon();
    global.fetch = jest.fn((url) => {
        if (String(url).indexOf('/api/microscopy/labels') === 0) {
            // A 10 x 8 label raster at 1/10 scale: cell 3 in the first two
            // rows, cell 7 in rows 4 and 5.
            const ids = new Uint16Array(10 * 8);
            ids.fill(3, 0, 20);
            ids.fill(7, 40, 60);
            const headers = { 'X-Label-Width': '10', 'X-Label-Height': '8',
                              'X-Label-Bytes': '2', 'X-Label-Scale': '10' };
            return Promise.resolve({ ok: true, headers: { get: (h) => headers[h] },
                                     arrayBuffer: () => Promise.resolve(ids.buffer) });
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ width: W, height: H, size_z: 1, size_t: 1, channels: [],
                                          dtype: 'uint8', dzi: {}, version: 1,
                                          label_image: 'masks/cells.tif' }),
        });
    });
    let api;
    if (fresh || !window.PotatoMicroscopy) {
        delete window.PotatoMicroscopy;
        jest.isolateModules(() => { require('../../potato/static/microscopy.js'); });
    } else {
        window.PotatoMicroscopy.init();
    }
    api = window.PotatoMicroscopy;
    for (let i = 0; i < 5; i++) await flush();
    viewers[viewers.length - 1].handlers.open();
    for (let i = 0; i < 5; i++) await flush();
    global.fetch.mockClear();
    const form = document.getElementById(SCHEMA);
    return { api, form, input: form.querySelector('.microscopy-input') };
}

function roi(label, id, x) {
    return { id, type: 'bbox', label, color: label === 'tumor' ? '#ff0000' : '#00ff00', z: 0, t: 0,
             coordinates: { x: x || 0.1, y: 0.1, width: 0.2, height: 0.2 } };
}

function answer(rois, cells) {
    return { image: { width: W, height: H }, rois: rois || [], cells: cells || [], label_image: null };
}

/** What collab.js does: answer into the scheme's hidden input, then apply(ctx). */
function applyTeammate(value) {
    const form = document.querySelector(`form[data-schema-name="${SCHEMA}"]`);
    const input = form.querySelector('input.annotation-input[type="hidden"]');
    const json = value === null ? '' : JSON.stringify(value);
    input.value = json;
    input.setAttribute('value', json);
    const widget = (window.potatoCollabWidgets || {})[form.getAttribute('data-annotation-type')];
    if (!widget) return false;
    return widget.apply({ schema: SCHEMA, form, input: null, inputs: [input], value: null,
                          labels: json ? { [SCHEMA]: json } : null });
}

const shapes = () => Array.from(document.querySelectorAll('.mic-shapes .mic-roi'))
    .map((n) => `${n.tagName}:${n.getAttribute('x')}`);
const roiRows = () => Array.from(document.querySelectorAll('.mic-roi-list .mic-roi-label'))
    .map((s) => s.value);
const cellRows = () => Array.from(document.querySelectorAll('.mic-cell-list .mic-cell-go'))
    .map((b) => b.textContent);

describe('microscopy live applier', () => {
    beforeEach(() => { window.saveAnnotations = jest.fn(); });

    test('a teammate answer replaces the regions and cells on screen', async () => {
        await makePage(answer([roi('tumor', 'a', 0.1)], [{ label_id: 3, class: 'tumor', z: 0, t: 0 }]));
        expect(roiRows()).toEqual(['tumor']);
        expect(cellRows()).toEqual(['Cell 3: tumor']);
        expect(cellPaint()).toEqual({ '255,0,0': 20 });

        expect(applyTeammate(answer([roi('stroma', 'b', 0.5), roi('tumor', 'c', 0.3)],
                                    [{ id: 'cell_7', label_id: 7, class: 'stroma', z: 0, t: 0 }]))).toBe(true);
        expect(roiRows()).toEqual(['stroma', 'tumor']);
        expect(shapes()).toEqual(['rect:50', 'rect:30']);
        expect(document.querySelector('.mic-roi-count').textContent).toBe('(2)');
        expect(cellRows()).toEqual(['Cell 7: stroma']);
        expect(document.querySelector('.mic-cell-count').textContent).toBe('(1)');
        expect(cellPaint()).toEqual({ '0,255,0': 20 });
    });

    test('null clears every region and cell', async () => {
        await makePage(answer([roi('tumor', 'a')], [{ label_id: 3, class: 'tumor', z: 0, t: 0 }]));
        expect(applyTeammate(null)).toBe(true);
        expect(shapes()).toEqual([]);
        expect(document.querySelector('.mic-roi-count').textContent).toBe('(0)');
        expect(document.querySelector('.mic-roi-list .mic-empty')).not.toBeNull();
        expect(cellRows()).toEqual([]);
        expect(cellPaint()).toEqual({});
    });

    test('applying saves nothing', async () => {
        const { input } = await makePage(answer([roi('tumor', 'a')]));
        const changed = jest.fn();
        input.addEventListener('change', changed);
        expect(applyTeammate(answer([roi('stroma', 'b')]))).toBe(true);
        expect(global.fetch).not.toHaveBeenCalled();
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(changed).not.toHaveBeenCalled();
        expect(input.hasAttribute('data-modified')).toBe(false);
    });

    test('applying twice does not duplicate', async () => {
        await makePage(null);
        const a = answer([roi('tumor', 'a')], [{ label_id: 3, class: 'tumor', z: 0, t: 0 }]);
        applyTeammate(a);
        applyTeammate(a);
        expect(shapes()).toHaveLength(1);
        expect(roiRows()).toHaveLength(1);
        expect(cellRows()).toHaveLength(1);
    });

    test('later edits build on the applied answer, not the stale one', async () => {
        const { form, input } = await makePage(answer([roi('tumor', 'a'), roi('tumor', 'x', 0.6)]));
        applyTeammate(answer([roi('stroma', 'b')]));
        // Delete the teammate's region through the UI: the save must hold
        // nothing, not the region this page loaded with.
        form.querySelector('.mic-roi-list .mic-remove').click();
        expect(input.value).toBe('');
    });
});

describe('microscopy region ids', () => {
    test('two pages each drawing their first region get different ids', async () => {
        const a = (await makePage(null, { fresh: true })).api.newRoiId();
        const b = (await makePage(null, { fresh: true })).api.newRoiId();
        expect(a).not.toEqual(b);
    });

    test('a classified cell is keyed by the cell; a restored one keeps its stored shape', async () => {
        const { form, input } = await makePage(answer([], [{ label_id: 3, class: 'tumor', z: 0, t: 0 }]));
        const pick = (id, cls) => {
            form.querySelector('.mic-cell-id').value = String(id);
            form.querySelector('.mic-cell-find .mic-cell-go').click();
            form.querySelector(`.mic-cell-class[data-class="${cls}"]`).click();
        };
        pick(7, 'stroma');
        pick(3, 'stroma');
        const cells = JSON.parse(input.value).cells;
        expect(cells.find((c) => c.label_id === 7).id).toBe('cell_7');
        expect(cells.find((c) => c.label_id === 3)).not.toHaveProperty('id');
    });

    test('a drawn region is stored with an id', async () => {
        const { form, input } = await makePage(null, { fresh: true });
        form.querySelector('.mic-tool[data-tool="landmark"]').click();
        viewers[viewers.length - 1].handlers['canvas-click']({ quick: true, position: { x: 20, y: 30 } });
        const stored = JSON.parse(input.value);
        expect(stored.rois).toHaveLength(1);
        expect(stored.rois[0].id).toMatch(/^roi_[a-z0-9]+_\d+$/);
    });
});

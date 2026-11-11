/**
 * Live collaborative sessions: the map widget's applier
 * (window.potatoCollabWidgets.geo_annotation), its replace-style restore
 * (PotatoGeoAnnotation.reload), and collision-proof feature ids.
 *
 * The widget's own restore() runs once and appends; a teammate's answer
 * written into the hidden input was never drawn. collab.js writes the answer
 * into the input (label key `<schema>:::<schema>`), then calls apply(ctx).
 *
 * The real vendored OpenLayers runs here; jsdom only lacks ResizeObserver.
 * What is checked is the feature list (the keyboard route to the map, and
 * the map's own content one to one) and the map's vector source.
 */

const fs = require('fs');
const path = require('path');

global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
(0, eval)(fs.readFileSync(path.join(__dirname, '../../potato/static/vendor/ol-10.9.0/ol.js'), 'utf8'));

const SCHEMA = 'places';

function attrJson(obj) {
    return JSON.stringify(obj).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
        .replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/{/g, '&#123;').replace(/}/g, '&#125;');
}

const REGIONS = { type: 'FeatureCollection', features: [
    { type: 'Feature', id: 'A', properties: { name: 'Alpha' },
      geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] } },
    { type: 'Feature', id: 'B', properties: { name: 'Beta' },
      geometry: { type: 'Polygon', coordinates: [[[2, 0], [3, 0], [3, 1], [2, 0]]] } },
] };

/** The generator's markup (geo_annotation.py) for a task, with a stored answer. */
function markup(task, stored) {
    const cfg = {
        schema: SCHEMA, task,
        labels: [{ name: 'road', color: '#ff0000' }, { name: 'river', color: '#0000ff' }],
        tools: ['point', 'polygon'], feature_text: null,
        basemap: { tiles: '/tiles/{z}/{x}/{y}.png', attribution: 'Test' },
        basemap_field: null, preannotation_field: null, predictions_field: null,
        coordinate_order: 'lonlat', projection: 'EPSG:3857', center: null, zoom: null,
        snapping: false, min_features: null, max_features: null,
        require_all_regions: false, required: false,
    };
    const inline = task === 'classify_region' ? ` data-geo-basemap="${attrJson(REGIONS)}"` : '';
    const value = stored ? attrJson(stored) : '';
    return `
      <input id="instance_id" type="hidden" value="item-1">
      <form id="${SCHEMA}" class="annotation-form geo-annotation" action="javascript:void(0)"
            data-annotation-type="geo_annotation" data-schema-name="${SCHEMA}" data-geo-task="${task}"
            data-geo-config="${attrJson(cfg)}"${inline} data-grid-columns="1">
        <fieldset schema="${SCHEMA}">
          <legend class="geo-title">Mark places</legend>
          <div class="geo-toolbar" role="toolbar" aria-label="Map tools"></div>
          <div class="geo-map" tabindex="0" role="application" aria-label="Map."
               style="height: 440px"><p class="geo-loading" role="status">Loading map…</p></div>
          <p class="geo-status" role="status" aria-live="polite"></p>
          <div class="geo-features"></div>
          <input type="hidden" class="annotation-input geo-annotation-input"
                 id="${SCHEMA}_${SCHEMA}_hidden" name="${SCHEMA}:::${SCHEMA}"
                 schema="${SCHEMA}" label_name="${SCHEMA}" validation="" value="${value}"
                 ${stored ? 'data-server-set="true"' : ''}>
        </fieldset>
      </form>`;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

async function makePage(task, stored, { fresh } = {}) {
    document.body.innerHTML = markup(task, stored);
    global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
    if (fresh || !window.PotatoGeoAnnotation) {
        delete window.PotatoGeoAnnotation;
        jest.isolateModules(() => { require('../../potato/static/geo-annotation.js'); });
    } else {
        window.PotatoGeoAnnotation.init();
    }
    for (let i = 0; i < 6; i++) await flush();
    const form = document.getElementById(SCHEMA);
    expect(form.getAttribute('data-geo-ready')).toBe('true');
    global.fetch.mockClear();
    return { form, input: form.querySelector('.geo-annotation-input'),
             state: window.PotatoGeoAnnotation.state(SCHEMA) };
}

function point(id, label, lon) {
    return { type: 'Feature', id, properties: { label, tool: 'point' },
             geometry: { type: 'Point', coordinates: [lon, 10] } };
}
const fc = (features) => ({ type: 'FeatureCollection', features });

/** What collab.js does: answer into the scheme's hidden input, then apply(ctx). */
function applyTeammate(value) {
    const form = document.querySelector(`form[data-schema-name="${SCHEMA}"]`);
    const input = form.querySelector('input.annotation-input[type="hidden"]');
    const json = value === null ? '' : JSON.stringify(value);
    input.value = json;
    input.setAttribute('value', json);
    if (json) input.setAttribute('data-server-set', 'true'); else input.removeAttribute('data-server-set');
    const widget = (window.potatoCollabWidgets || {})[form.getAttribute('data-annotation-type')];
    if (!widget) return false;
    return widget.apply({ schema: SCHEMA, form, input: null, inputs: [input], value: null,
                          labels: json ? { [SCHEMA]: json } : null });
}

const rows = () => Array.from(document.querySelectorAll('.geo-feature-list .geo-feature')).map((li) =>
    `${li.getAttribute('data-feature-id')}:${li.querySelector('.geo-feature-label').value}`);
const title = () => document.querySelector('.geo-list-title').textContent;

describe('geo_annotation live applier (draw)', () => {
    beforeEach(() => { window.saveAnnotations = jest.fn(); });

    test('a teammate answer replaces the features on the map and in the list', async () => {
        const { state } = await makePage('draw', fc([point('f1', 'road', 1), point('f2', 'road', 2)]));
        expect(rows()).toEqual(['f1:road', 'f2:road']);
        expect(applyTeammate(fc([point('f1', 'river', 5), point('f3_zz9abc', 'road', 6)]))).toBe(true);
        expect(rows()).toEqual(['f1:river', 'f3_zz9abc:road']);
        expect(title()).toBe('Features on the map (2)');
        expect(state.source.getFeatures().map((f) => f.getId()).sort()).toEqual(['f1', 'f3_zz9abc']);
        expect(state.source.getFeatureById('f1').get('label')).toBe('river');
    });

    test('null clears the map', async () => {
        const { state } = await makePage('draw', fc([point('f1', 'road', 1)]));
        expect(applyTeammate(null)).toBe(true);
        expect(rows()).toEqual([]);
        expect(document.querySelector('.geo-empty')).not.toBeNull();
        expect(state.source.getFeatures()).toHaveLength(0);
    });

    test('applying saves nothing', async () => {
        const { input } = await makePage('draw', fc([point('f1', 'road', 1)]));
        const changed = jest.fn();
        input.addEventListener('change', changed);
        input.addEventListener('input', changed);
        expect(applyTeammate(fc([point('f2', 'river', 3)]))).toBe(true);
        expect(global.fetch).not.toHaveBeenCalled();
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(changed).not.toHaveBeenCalled();
        expect(input.hasAttribute('data-modified')).toBe(false);
    });

    test('applying twice does not duplicate', async () => {
        const { state } = await makePage('draw', null);
        const answer = fc([point('f4_abc123', 'road', 1)]);
        applyTeammate(answer);
        applyTeammate(answer);
        expect(rows()).toEqual(['f4_abc123:road']);
        expect(state.source.getFeatures()).toHaveLength(1);
    });

    test('the selection follows its feature', async () => {
        const { state } = await makePage('draw', fc([point('f1', 'road', 1), point('f2', 'road', 2)]));
        document.querySelector('.geo-feature[data-feature-id="f2"] .geo-show').click();
        expect(state.selectedId).toBe('f2');
        applyTeammate(fc([point('f2', 'river', 9)]));
        expect(rows()).toEqual(['f2:river']);
        expect(state.selectedId).toBe('f2');
        expect(document.querySelector('.geo-feature.geo-selected').getAttribute('data-feature-id')).toBe('f2');
    });
});

describe('geo_annotation live applier (classify_region)', () => {
    const assigned = (pairs) => fc(pairs.map(([region, label]) => ({
        type: 'Feature', geometry: null, properties: { region, region_name: '', label } })));
    const regionValues = () => Array.from(document.querySelectorAll('.geo-region-label')).map((s) => s.value);

    test('assignments are replaced, and null clears them', async () => {
        await makePage('classify_region', assigned([['A', 'road']]));
        expect(regionValues()).toEqual(['road', '']);
        expect(applyTeammate(assigned([['B', 'river']]))).toBe(true);
        expect(regionValues()).toEqual(['', 'river']);
        expect(title()).toBe('Regions (1 of 2 labelled)');
        expect(applyTeammate(null)).toBe(true);
        expect(regionValues()).toEqual(['', '']);
        expect(title()).toBe('Regions (0 of 2 labelled)');
    });
});

describe('geo feature ids', () => {
    test('two pages each adding their first feature get different ids', async () => {
        const ids = [];
        for (let i = 0; i < 2; i++) {
            const { form, input } = await makePage('draw', null, { fresh: true });
            form.querySelector('.geo-add-centre').click();
            ids.push(JSON.parse(input.value).features[0].id);
        }
        expect(ids[0]).toMatch(/^f1_[a-z0-9]+$/);
        expect(ids[1]).toMatch(/^f1_[a-z0-9]+$/);
        expect(ids[0]).not.toEqual(ids[1]);
    });

    test('restored ids are kept, old and new form, and new ones number past them', async () => {
        const { form, input } = await makePage('draw', fc([point('f7', 'road', 1), point('f9_abc123', 'road', 2)]));
        form.querySelector('.geo-add-centre').click();
        const ids = JSON.parse(input.value).features.map((f) => f.id);
        expect(ids.slice(0, 2)).toEqual(['f7', 'f9_abc123']);
        expect(ids[2]).toMatch(/^f10_[a-z0-9]+$/);
        expect(Array.from(document.querySelectorAll('.geo-feature-name')).map((n) => n.textContent))
            .toEqual(['Point 7', 'Point 9', 'Point 10']);
    });
});

/**
 * The per-object attribute panel under the image canvas.
 *
 * Drives the real ImageAnnotationManager methods against a jsdom copy of the
 * markup the generator writes, with a fake fabric canvas. Persistence through
 * save is covered by shape-attributes.test.js; this covers what the panel
 * writes and what it tells the form.
 */

const fs = require('fs');
const path = require('path');

global.fabric = {
    Point: function (x, y) { this.x = x; this.y = y; },
    Rect: function (o) { Object.assign(this, o); },
    util: { transformPoint: (p) => p },
};
require('../../potato/static/mask-buffer.js');
const SRC = path.join(__dirname, '..', '..', 'potato', 'static', 'image-annotation.js');
eval(fs.readFileSync(SRC, 'utf8'));

const DEFS = [
    { name: 'occlusion', type: 'select', options: ['none', 'partial', 'heavy'],
      required: true, default: 'none' },
    { name: 'truncated', type: 'bool', required: false, default: false },
    { name: 'share', type: 'number', required: false,
      show_if: { attribute: 'truncated', equals: true } },
    { name: 'parked', type: 'bool', required: false, labels: ['car'] },
    { name: 'activity', type: 'multi', options: ['walking', 'standing'],
      required: false, labels: ['person'] },
];

function setupDom() {
    document.body.innerHTML = `
      <form class="annotation-form" data-schema-name="objs">
        <div class="image-annotation-container" data-schema="objs">
          <section class="object-attribute-panel">
            <p class="attribute-panel-hint"></p>
            <div class="attribute-fields"></div>
            <p class="attribute-panel-status"></p>
            <input type="hidden" class="attribute-requirement" validation="required" value="ok">
          </section>
          <input type="hidden" id="input-objs" value="">
        </div>
      </form>`;
}

function makeManager(objects) {
    const m = Object.create(ImageAnnotationManager.prototype);
    let active = null;
    m.config = { schemaName: 'objs', attributes: DEFS };
    m.attributeDefs = DEFS;
    m.inputId = 'input-objs';
    m.image = { width: 100, height: 100, scaleX: 1, scaleY: 1, left: 0, top: 0 };
    m.masks = {};
    m.canvas = {
        getObjects: () => objects,
        getActiveObject: () => active,
        setActive: (o) => { active = o; },
        on: () => {},
    };
    m._saveState = jest.fn();
    m._telemetry = () => {};
    return m;
}

function rect(data) {
    return { annotationData: data, type: 'rect', left: 10, top: 10, width: 20,
             height: 20, scaleX: 1, scaleY: 1, angle: 0 };
}

beforeEach(setupDom);

describe('defaults', () => {
    test('a shape someone drew gets the declared defaults once', () => {
        const drawn = rect({ type: 'bbox', label: 'car', color: '#00f', source: 'human' });
        const m = makeManager([drawn]);
        m._updateAnnotationData();
        expect(drawn.annotationData.attributes).toEqual({ occlusion: 'none', truncated: false });
    });

    test('a cleared field stays cleared', () => {
        const drawn = rect({ type: 'bbox', label: 'car', color: '#00f', source: 'human' });
        const m = makeManager([drawn]);
        m._updateAnnotationData();
        delete drawn.annotationData.attributes.occlusion;
        m._updateAnnotationData();
        expect(drawn.annotationData.attributes).not.toHaveProperty('occlusion');
    });

    test("a model's shape keeps exactly what it arrived with", () => {
        const predicted = rect({ type: 'bbox', label: 'car', color: '#00f', source: 'ai' });
        const m = makeManager([predicted]);
        m._updateAnnotationData();
        expect(predicted.annotationData).not.toHaveProperty('attributes');
    });
});

describe('the panel', () => {
    function panelFor(data) {
        const obj = rect(data);
        const m = makeManager([obj]);
        m.canvas.setActive(obj);
        m._renderAttributePanel();
        return { m, obj, fields: () => [...document.querySelectorAll('.attribute-field')] };
    }

    test('shows only the attributes for the shape\'s label', () => {
        const { fields } = panelFor({ type: 'bbox', label: 'person', source: 'human', attributes: {} });
        expect(fields().map(f => f.dataset.attribute))
            .toEqual(['occlusion', 'truncated', 'share', 'activity']);
    });

    test('show_if hides a field until its condition holds', () => {
        const { fields } = panelFor({ type: 'bbox', label: 'car', source: 'human', attributes: {} });
        const share = fields().find(f => f.dataset.attribute === 'share');
        expect(share.hidden).toBe(true);
        const truncated = fields().find(f => f.dataset.attribute === 'truncated')
            .querySelector('input');
        truncated.checked = true;
        truncated.dispatchEvent(new Event('change'));
        expect(share.hidden).toBe(false);
    });

    test('a control writes the typed value and saves', () => {
        const { m, obj, fields } = panelFor({ type: 'bbox', label: 'car', source: 'human', attributes: {} });
        const select = fields()[0].querySelector('select');
        select.value = 'heavy';
        select.dispatchEvent(new Event('change'));
        expect(obj.annotationData.attributes.occlusion).toBe('heavy');
        expect(m._saveState).toHaveBeenCalled();
        expect(JSON.parse(document.getElementById('input-objs').value)[0].attributes.occlusion)
            .toBe('heavy');
    });

    test('a multi attribute stores the ticked options as a list', () => {
        const { obj, fields } = panelFor({ type: 'bbox', label: 'person', source: 'human', attributes: {} });
        const boxes = fields().find(f => f.dataset.attribute === 'activity')
            .querySelectorAll('input[type=checkbox]');
        boxes[0].checked = true;
        boxes[0].dispatchEvent(new Event('change'));
        boxes[1].checked = true;
        boxes[1].dispatchEvent(new Event('change'));
        expect(obj.annotationData.attributes.activity).toEqual(['walking', 'standing']);
    });

    test("changing a model's shape marks it edited", () => {
        const { obj, fields } = panelFor({ type: 'bbox', label: 'car', source: 'ai', attributes: {} });
        const select = fields()[0].querySelector('select');
        select.value = 'partial';
        select.dispatchEvent(new Event('change'));
        expect(obj.annotationData.edited).toBe(true);
    });
});

describe('required attributes', () => {
    test('a missing required value blocks the form with a reason', () => {
        const blank = rect({ type: 'bbox', label: 'car', source: 'ai', attributes: {} });
        const m = makeManager([blank]);
        m._updateAttributeRequirement();
        const form = document.querySelector('.annotation-form');
        expect(form.getAttribute('data-incomplete-reason'))
            .toBe('1 object still needs required attributes');
        // The hidden input only enrolls the form; the reason decides.
        expect(document.querySelector('.attribute-requirement').value).toBe('ok');
    });

    test('filling it in clears the reason', () => {
        const done = rect({ type: 'bbox', label: 'car', source: 'ai', attributes: { occlusion: 'none' } });
        const m = makeManager([done]);
        m._updateAttributeRequirement();
        expect(document.querySelector('.annotation-form').hasAttribute('data-incomplete-reason'))
            .toBe(false);
    });

    test('a required field hidden by show_if does not block', () => {
        const defs = [{ name: 'flag', type: 'bool', required: false },
                      { name: 'why', type: 'text', required: true,
                        show_if: { attribute: 'flag', equals: true } }];
        const obj = rect({ type: 'bbox', label: 'car', source: 'human', attributes: { flag: false } });
        const m = makeManager([obj]);
        m.attributeDefs = defs;
        expect(m._shapesMissingAttributes()).toHaveLength(0);
        obj.annotationData.attributes.flag = true;
        expect(m._shapesMissingAttributes()).toHaveLength(1);
    });
});

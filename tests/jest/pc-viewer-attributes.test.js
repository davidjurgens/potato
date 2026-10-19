/**
 * Per-object attributes on point-cloud objects: a placed object gets the
 * declared defaults, the panel follows the selection and edits the selected
 * object, and the attributes reach the hidden input with the geometry.
 */

window.ObjectAttributes = require('../../potato/static/object-attributes.js');
require('../../potato/static/pointcloud/pc-wire.js');
const Manager = require('../../potato/static/pointcloud/pc-viewer.js');

const DEFS = [{ name: 'occluded', type: 'select', options: ['none', 'partial'],
                default: 'none', required: true, labels: ['car'] }];

function makeManager() {
    const m = new Manager('pc-canvas-objects', 'input-objects',
                          { schema: 'objects', labels: [{ name: 'car', color: '#f00' }],
                            attributes: DEFS });
    Object.assign(m, {
        container: document.querySelector('.pointcloud-annotation-container'),
        attributePanel: document.querySelector('.object-attribute-panel'),
        scene: { add() {}, remove() {} }, _render: () => {}, _drawOverlays: () => {},
        _buildMesh(obj) { this.meshes.push({ obj, material: {} }); },
        currentLabel: 'car', currentColor: '#f00',
    });
    return m;
}

beforeEach(() => {
    document.body.innerHTML = `
      <div class="pointcloud-annotation-container annotation-form">
        <input type="hidden" id="input-objects" value="">
        <section class="object-attribute-panel"><p class="attribute-panel-hint"></p>
          <div class="attribute-fields"></div><p class="attribute-panel-status"></p></section>
      </div>`;
});

test('a placed point gets the defaults and they are saved', () => {
    const m = makeManager();
    m._placePoint([1, 2, 3]);
    const stored = JSON.parse(document.getElementById('input-objects').value);
    expect(stored[0].attributes).toEqual({ occluded: 'none' });
});

test('the panel edits the selected object; a blank required value is reported', () => {
    const m = makeManager();
    m._placePoint([1, 2, 3]);
    m.selectedIndex = 0;
    m._highlightSelection();
    const select = document.querySelector('.object-attribute-panel select');
    expect(select.value).toBe('none');
    select.value = 'partial';
    select.dispatchEvent(new Event('change'));
    expect(JSON.parse(document.getElementById('input-objects').value)[0].attributes)
        .toEqual({ occluded: 'partial' });
    select.value = '';
    select.dispatchEvent(new Event('change'));
    expect(m.container.getAttribute('data-incomplete-reason'))
        .toBe('1 object still needs required attributes');
});

test('a restored object without attributes is not given defaults', () => {
    const m = makeManager();
    m.addAnnotation({ type: 'point_3d', label: 'car', coordinates: [0, 0, 0] });
    expect(JSON.parse(document.getElementById('input-objects').value)[0].attributes).toBeUndefined();
});

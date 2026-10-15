/**
 * A stored or pre-annotated shape with no `color` must still be drawn.
 *
 * `_createAnnotationObject` passed `ann.color` straight to `_colorWithAlpha`,
 * which called `.slice` on undefined; the throw dropped the shape, so a
 * `pre_annotation` box written without a colour showed "Annotations: 0" with
 * no warning (found by potato-skill on 2.10.3). The label's configured colour
 * is used, then the default.
 */

global.fabric = {
    Rect: function (opts) { Object.assign(this, opts); },
    Circle: function (opts) { Object.assign(this, opts); },
    Polygon: function (points, opts) { this.points = points; Object.assign(this, opts); },
    Polyline: function (points, opts) { this.points = points; Object.assign(this, opts); },
};

require('../../potato/static/mask-buffer.js');
const ImageAnnotationManager = require('../../potato/static/image-annotation.js');

function makeManager(labels) {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.config = {labels: labels || []};
    m.image = {width: 200, height: 100, scaleX: 1, scaleY: 1, left: 0, top: 0};
    const objs = [];
    m.canvas = {add: (o) => objs.push(o), getObjects: () => objs, renderAll: () => {}};
    return {m, objs};
}

const BOX = {type: 'bbox', label: 'car',
             coordinates: {x: 0.1, y: 0.1, width: 0.2, height: 0.2}};

test('a box without a colour takes its label colour', () => {
    const {m, objs} = makeManager([{name: 'car', color: '#00AA00'}]);
    m._createAnnotationObject(Object.assign({}, BOX));
    expect(objs).toHaveLength(1);
    expect(objs[0].stroke).toBe('#00AA00');
    expect(objs[0].fill).toBe('rgba(0, 170, 0, 0.2)');
    expect(objs[0].annotationData.color).toBe('#00AA00');
});

test('a box whose label has no colour falls back to the default', () => {
    const {m, objs} = makeManager(['car']);
    m._createAnnotationObject(Object.assign({}, BOX));
    expect(objs).toHaveLength(1);
    expect(objs[0].stroke).toBe('#FF6B6B');
});

test('a colour that is not six-digit hex is used as given', () => {
    const {m, objs} = makeManager([]);
    m._createAnnotationObject(Object.assign({}, BOX, {color: 'red'}));
    expect(objs).toHaveLength(1);
    expect(objs[0].stroke).toBe('red');
});

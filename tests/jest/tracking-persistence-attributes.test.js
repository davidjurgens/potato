/**
 * Video tracks are saved, and carry per-track attributes.
 *
 * TrackingUIManager kept its tracks to itself: the generator overrode a
 * `save()` nothing called and loaded from a `getAnnotationData()` that does not
 * exist, so tracks drawn in tracking mode never reached the server. The
 * manager now calls `onChange` after every change (never while loading), and
 * keyframes carry a box normalized to the video picture.
 */

const fs = require('fs');
const path = require('path');

const ObjectAttributes = require('../../potato/static/object-attributes.js');

function loadTracking() {
    const source = fs.readFileSync(
        path.join(__dirname, '../../potato/static/tracking-ui.js'), 'utf8');
    const module_ = { exports: {} };
    const win = { ObjectAttributes };
    (new Function('module', 'exports', 'window', source))(module_, module_.exports, win);
    return module_.exports.TrackingUIManager || win.TrackingUIManager;
}

const TrackingUIManager = loadTracking();
const DEFS = [
    { name: 'occluded', type: 'select', options: ['none', 'partial'], default: 'none', required: true },
    { name: 'moving', type: 'bool' },
];

function manager(saves) {
    return new TrackingUIManager({
        canvas: null,
        video: {
            currentTime: 0, videoWidth: 400, videoHeight: 200,
            getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 200 }),
        },
        onChange: (tracks) => saves.push(JSON.parse(JSON.stringify(tracks))),
        config: { attributes: DEFS, schemaName: 'objects' },
    });
}

function withCanvas(m) {
    // The overlay canvas, 800x400 on screen and in its backing store: the
    // picture fills it, so box (200, 100, 80, 40) is (0.25, 0.25, 0.1, 0.1).
    m.canvas = { width: 800, height: 400, style: {},
                 classList: { add() {}, remove() {} },
                 getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 400 }) };
    m.video.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 400 });
    m._getCurrentFrame = () => 12;
    m._renderTrackPanel = () => {};
    m.renderOverlay = () => {};
    return m;
}

test('every change is reported, with the tracks and their attributes', () => {
    const saves = [];
    const m = withCanvas(manager(saves));
    m.createTrack('car', '#f00');
    m.addKeyframe({ x: 200, y: 100, width: 80, height: 40 });
    const last = saves[saves.length - 1];
    const track = Object.values(last)[0];
    expect(track.label).toBe('car');
    expect(track.attributes).toEqual({ occluded: 'none' });   // the default, once
    expect(track.keyframes[12].bboxNorm).toEqual({ x: 0.25, y: 0.25, width: 0.1, height: 0.1 });
    m.deleteTrack(track.id);
    expect(saves[saves.length - 1]).toEqual({});
});

test('loading saved tracks does not save them again', () => {
    const saves = [];
    const m = withCanvas(manager(saves));
    m.loadTrackingData({ track_4: { id: 'track_4', label: 'car', keyframes: {}, attributes: { moving: true } } });
    expect(saves).toEqual([]);
    expect(m.nextTrackId).toBe(5);
    m.setInterpolation('track_4', 'step');
    expect(saves).toHaveLength(1);
    expect(saves[0].track_4.attributes).toEqual({ moving: true });
});

test('a required attribute left blank marks the form incomplete', () => {
    const form = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
                   removeAttribute(k) { delete this.attrs[k]; } };
    const saves = [];
    const m = withCanvas(manager(saves));
    m.form = form;
    m.createTrack('car');
    expect(form.attrs['data-incomplete-reason']).toBeUndefined();
    m.tracks[m.activeTrackId].attributes.occluded = undefined;
    m._changed();
    expect(form.attrs['data-incomplete-reason']).toBe('1 track still needs required attributes');
});

describe('ObjectAttributes', () => {
    test('defaults and show_if', () => {
        const defs = [{ name: 'a', type: 'select', options: ['x'], default: 'x', labels: ['car'] },
                      { name: 'b', type: 'text', show_if: { attribute: 'a', equals: 'x' } }];
        expect(ObjectAttributes.defaults(defs, 'car')).toEqual({ a: 'x' });
        expect(ObjectAttributes.defaults(defs, 'person')).toEqual({});
        expect(ObjectAttributes.visible(defs[1], { a: 'x' })).toBe(true);
        expect(ObjectAttributes.visible(defs[1], {})).toBe(false);
    });

    test('the panel edits the values and reports each change', () => {
        document.body.innerHTML = `<section class="object-attribute-panel">
            <p class="attribute-panel-hint"></p><div class="attribute-fields"></div>
            <p class="attribute-panel-status"></p></section>`;
        const panel = document.querySelector('.object-attribute-panel');
        const values = {};
        const changes = [];
        ObjectAttributes.render({ panel, defs: DEFS, label: 'car', values, idPrefix: 't',
                                  onChange: v => changes.push(Object.assign({}, v)) });
        const select = panel.querySelector('select');
        select.value = 'partial';
        select.dispatchEvent(new Event('change'));
        const box = panel.querySelector('input[type=checkbox]');
        box.checked = true;
        box.dispatchEvent(new Event('change'));
        expect(values).toEqual({ occluded: 'partial', moving: true });
        expect(changes).toHaveLength(2);
        ObjectAttributes.render({ panel, defs: DEFS, label: null, values: {}, idPrefix: 't', noun: 'track' });
        expect(panel.querySelector('.attribute-panel-hint').textContent).toBe('Select a track to set its attributes.');
    });
});

/**
 * per_keyframe attributes on video tracks: a value set on a frame holds
 * until the next keyframe that changes it; setting one on an interpolated
 * frame pins a keyframe there; redrawing a keyframe keeps what was set on it.
 * The server reads the same rule in potato/server_utils/track_attributes.py.
 */

const fs = require('fs');
const path = require('path');

const ObjectAttributes = require('../../potato/static/object-attributes.js');

function load() {
    const win = { ObjectAttributes };
    for (const file of ['tracking-interpolation.js', 'tracking-ui.js']) {
        const source = fs.readFileSync(path.join(__dirname, '../../potato/static', file), 'utf8');
        const module_ = { exports: {} };
        (new Function('module', 'exports', 'window', source))(module_, module_.exports, win);
        if (module_.exports.TrackingUIManager) win.TrackingUIManager = module_.exports.TrackingUIManager;
    }
    window.TrackingInterpolationEngine = win.TrackingInterpolationEngine;
    window.ObjectAttributes = ObjectAttributes;
    return win.TrackingUIManager;
}

const TrackingUIManager = load();
const DEFS = [
    { name: 'occluded', type: 'select', options: ['none', 'partial'], default: 'none', per_keyframe: true },
    { name: 'moving', type: 'bool' },
];

function manager() {
    document.body.innerHTML = `<section class="object-attribute-panel">
        <p class="attribute-panel-hint"></p><div class="attribute-fields"></div>
        <p class="attribute-panel-status"></p></section>`;
    const saves = [];
    const m = new TrackingUIManager({
        canvas: null,
        video: { currentTime: 0, videoWidth: 400, videoHeight: 200,
                 getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 200 }) },
        onChange: (tracks) => saves.push(JSON.parse(JSON.stringify(tracks))),
        config: { attributes: DEFS, schemaName: 'objects' },
    });
    m.attributePanel = document.querySelector('.object-attribute-panel');
    m._renderTrackPanel = () => { m._renderAttributePanel(); };
    m.renderOverlay = () => {};
    let frame = 0;
    m._getCurrentFrame = () => frame;
    m.at = (f) => { frame = f; m._renderAttributePanel(); };
    m.saves = saves;
    return m;
}

function track(m) {
    m.createTrack('car');
    m.at(0);
    m.addKeyframe({ x: 0, y: 0, width: 40, height: 40 });
    m.at(30);
    m.addKeyframe({ x: 300, y: 0, width: 40, height: 40 });
    return m.tracks[m.activeTrackId];
}

function choose(value) {
    const select = document.querySelector('select');
    select.value = value;
    select.dispatchEvent(new Event('change'));
}

test('a value holds from its keyframe to the next, and null clears it', () => {
    const m = manager();
    const t = track(m);
    t.keyframes[30].attributes = { occluded: 'partial' };
    expect(m.attributesAt(t, 10).occluded).toBe('none');
    expect(m.attributesAt(t, 30).occluded).toBe('partial');
    t.keyframes[30].attributes = { occluded: null };
    expect('occluded' in m.attributesAt(t, 30)).toBe(false);
});

test('setting it on an interpolated frame pins a keyframe there', () => {
    const m = manager();
    const t = track(m);
    m.at(12);
    choose('partial');
    expect(t.keyframes[12]).toBeDefined();
    expect(t.keyframes[12].bbox.x).toBeCloseTo(120);       // the interpolated box, kept
    expect(t.keyframes[12].attributes).toEqual({ occluded: 'partial' });
    expect(t.attributes.occluded).toBe('none');            // the track's own value is untouched
    expect(m.attributesAt(t, 20).occluded).toBe('partial');
    const saved = m.saves[m.saves.length - 1][t.id];
    expect(saved.keyframes[12].attributes).toEqual({ occluded: 'partial' });
    // Back on frame 5 the panel shows the value there.
    m.at(5);
    expect(document.querySelector('select').value).toBe('none');
});

test('a per-track attribute still goes on the track', () => {
    const m = manager();
    const t = track(m);
    m.at(12);
    const box = document.querySelector('input[type=checkbox]');
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    expect(t.attributes.moving).toBe(true);
    expect(t.keyframes[12]).toBeUndefined();               // nothing to pin for it
});

test('outside the track nothing is stored and the panel says why', () => {
    const m = manager();
    const t = track(m);
    m.at(45);
    choose('partial');
    expect(t.keyframes[45]).toBeUndefined();
    expect(document.querySelector('.attribute-panel-status').textContent).toMatch(/outside the track/);
    expect(document.querySelector('select').value).toBe('none');
});

test('redrawing a keyframe keeps what was set on it', () => {
    const m = manager();
    const t = track(m);
    m.at(30);
    choose('partial');
    m.addKeyframe({ x: 310, y: 0, width: 40, height: 40 });
    expect(t.keyframes[30].attributes).toEqual({ occluded: 'partial' });
    expect(t.keyframes[30].bbox.x).toBe(310);
});

test('a value being typed survives playback, and the panel catches up on blur', () => {
    const m = manager();
    m.attributeDefs = DEFS.concat([{ name: 'note', type: 'text', per_keyframe: true }]);
    const t = track(m);
    m.at(10);
    const input = document.querySelector('input[type="text"]');
    input.focus();
    input.value = 'brake lights';
    m.at(11);
    m.at(12);   // playback moves on while the annotator types
    expect(document.querySelector('input[type="text"]')).toBe(input);
    expect(input.value).toBe('brake lights');
    input.dispatchEvent(new Event('change'));
    // Committed where typing started, frame 10, which is pinned as a keyframe.
    expect(t.keyframes[10].attributes.note).toBe('brake lights');
    input.blur();
    const fresh = document.querySelector('input[type="text"]');
    expect(fresh).not.toBe(input);
    expect(fresh.value).toBe('brake lights');   // holds from 10 to 12
    expect(document.querySelector('.attribute-scope').textContent).toContain('frame 12');
});

test('the panel shows a committed value when focusout arrives before change', () => {
    const m = manager();
    m.attributeDefs = DEFS.concat([{ name: 'note', type: 'text', per_keyframe: true }]);
    m.renderOverlay = () => { m._renderAttributePanel(); };   // as the real overlay does
    track(m);
    m.at(10);
    const input = document.querySelector('input[type="text"]');
    input.focus();
    input.value = 'brake lights';
    m.at(12);
    input.blur();              // Chrome on Tab: the panel catches up first...
    input.dispatchEvent(new Event('change'));   // ...then the value commits
    expect(document.querySelector('input[type="text"]').value).toBe('brake lights');
});

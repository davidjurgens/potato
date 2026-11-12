/**
 * video_annotation in a live collaborative session (collab.js applyWidget).
 *
 * A teammate's answer must replace what this page shows (segments, keyframes,
 * frame classifications, object tracks), and showing it must not save. Also:
 * restoring a stored answer used to save partway through, with the segments
 * and none of the keyframes, and track ids from a per-page counter collided
 * between two members' pages.
 *
 * The REAL video-annotation.js, tracking-ui.js and collab.js run here; the
 * markup is the generator's (schemas/video_annotation.py, scripts removed).
 */

const fs = require('fs');
const path = require('path');

const STATIC = path.join(__dirname, '..', '..', 'potato', 'static');

// Generator output for {name: clips, mode: combined, labels: run, walk}.
const MARKUP = `
    <form id="clips" class="annotation-form video-annotation" action="javascript:void(0)" data-annotation-type="video_annotation" data-schema-name="clips" data-grid-columns="1"
          data-schema-name="clips">
        <fieldset schema="clips">
            <legend>Mark clips</legend>
            <div class="video-annotation-container" data-schema="clips" data-mode="combined">
                <div class="video-preview-panel">
                    <video id="video-clips" class="video-element" controls></video>
                    <canvas id="tracking-canvas-clips" class="tracking-overlay" style="display: none;"></canvas>
                </div>
                <div class="video-annotation-toolbar">
                    <button type="button" class="label-btn" data-label="run" data-color="#FF0000" title="run">run</button><button type="button" class="label-btn" data-label="walk" data-color="#00FF00" title="walk">walk</button>
                    <div class="tracking-controls-group">
                        <button type="button" class="tracking-btn" data-action="create-track" title="Create a new object track (T)">+ Track</button>
                        <button type="button" class="tracking-btn delete-btn" data-action="delete-track" title="Delete selected track" disabled>Delete Track</button>
                    </div>
                    <div class="segment-group" title="Segment creation controls">
                        <button type="button" class="segment-btn delete-btn" data-action="delete-segment" title="Delete the currently selected segment (Keyboard: Delete)" disabled>Delete</button>
                    </div>
                    <div class="count-group">
                        <span class="segment-count">Segments: <span class="count-value">0</span></span>
                    </div>
                </div>
                <div class="timeline-wrapper">
                    <div id="zoomview-clips" class="timeline-container" style="height: 70px;"></div>
                    <div id="overview-clips" class="overview-container" style="height: 40px;"></div>
                </div>
                <div class="annotation-list-container">
                    <h4>Annotations</h4>
                    <div id="annotation-list-clips" class="annotation-list"></div>
                </div>
                <div id="segment-questions-clips" class="segment-questions-panel" style="display: none;">
                    <h4>Segment Details</h4>
                    <div class="segment-questions-content"></div>
                </div>
                <div id="tracking-panel-clips" class="tracking-panel" style="display: block;">
                    <h4>Object Tracks</h4>
                    <div class="tracking-track-list"></div>
                </div>
                <input type="hidden"
                       name="clips"
                       id="input-clips"
                       class="annotation-data-input"
                       validation=""
                       autocomplete="off"
                       value="">
            </div>
        </fieldset>
    </form>`;

const CONFIG = {
    schemaName: 'clips', mode: 'combined', videoFps: 30,
    labels: [{ name: 'run', color: '#FF0000' }, { name: 'walk', color: '#00FF00' }],
};

/** A Peaks stand-in that keeps what is drawn on the timeline. */
function fakePeaks() {
    const segs = new Map();
    const points = new Map();
    const collection = (map) => ({
        add: (x) => { if (map.has(x.id)) throw new Error('duplicate id ' + x.id); map.set(x.id, x); },
        removeById: (id) => { map.delete(id); },
        getSegment: (id) => map.get(id) || null,
        removeAll: () => map.clear(),
    });
    return { segments: collection(segs), points: collection(points),
             _segments: segs, _points: points, destroy() {} };
}

const ANSWER_A = {
    video_metadata: { duration: 10, fps: 30, width: 0, height: 0, frameCount: 0 },
    segments: [{ id: 'segment_aaaaaa_1', start_time: 1, end_time: 2, start_frame: 30,
                 end_frame: 60, label: 'run', annotations: { q: 'yes' } }],
    frame_annotations: {},
    keyframes: [{ id: 'keyframe_aaaaaa_2', frame: 90, time: 3, label: 'run', color: '#FFD700' }],
    tracking: {},
    tracks: {
        track_aaaaaa_1: { id: 'track_aaaaaa_1', label: 'car', color: '#f00', interpolation: 'linear',
                          keyframes: { 0: { frame: 0, bbox: { x: 1, y: 1, width: 5, height: 5 } } } },
    },
};

const ANSWER_B = {
    video_metadata: { duration: 10, fps: 30, width: 0, height: 0, frameCount: 0 },
    segments: [
        { id: 'segment_bbbbbb_1', start_time: 4, end_time: 5, label: 'walk', annotations: {} },
        { id: 'segment_bbbbbb_2', start_time: 6, end_time: 7, label: 'walk', annotations: {} },
    ],
    frame_annotations: { 120: { id: 'frame_120', frame: 120, time: 4, label: 'run', color: '#f00' } },
    keyframes: [],
    tracking: {},
    tracks: {
        track_bbbbbb_1: { id: 'track_bbbbbb_1', label: 'dog', color: '#0f0', interpolation: 'linear', keyframes: {} },
        track_bbbbbb_2: { id: 'track_bbbbbb_2', label: 'cat', color: '#00f', interpolation: 'linear', keyframes: {} },
    },
};

let VideoAnnotationManager;
let TrackingUIManager;
let client;
let manager;
let fetchCalls;
let changes;

function loadScripts() {
    delete window.potatoCollabWidgets;
    delete window.TrackingUIManager;
    jest.isolateModules(() => {
        VideoAnnotationManager = require('../../potato/static/video-annotation.js');
    });
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(path.join(STATIC, 'tracking-ui.js'), 'utf8'))();
    TrackingUIManager = window.TrackingUIManager;
}

function bootCollab() {
    fetchCalls = [];
    window.fetch = jest.fn((input, init) => {
        fetchCalls.push({ input, init });
        return Promise.resolve({ ok: true, status: 200, clone() { return this; },
                                 json: () => Promise.resolve({ events: [], cursor: 0, answer: {} }) });
    });
    window.potatoCollab = { sid: 'RED', me: 'ben', instance_id: 'v1', rev: 1, cursor: 0,
                            team_user: 'team-red', transport: 'poll', poll_interval_ms: 100000, base: '' };
    delete window.potatoCollabClient;
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(path.join(STATIC, 'collab.js'), 'utf8'))();
    client = window.potatoCollabClient;
    // collab.js wrapped fetch; the shared setup clears a mock after each test.
    window.fetch.mockClear = () => {};
}

/** The page as the generator's init script leaves it, showing `answer`. */
function page(answer) {
    document.body.innerHTML = MARKUP;
    const input = document.getElementById('input-clips');
    if (answer) {
        input.value = JSON.stringify(answer);
        input.setAttribute('data-server-set', 'true');
    }
    changes = 0;
    input.addEventListener('change', () => { changes += 1; });
    const container = document.querySelector('.video-annotation-container');
    const m = new VideoAnnotationManager({
        container, videoId: 'video-clips', zoomviewId: 'zoomview-clips', overviewId: 'overview-clips',
        inputId: 'input-clips', annotationListId: 'annotation-list-clips',
        questionsId: 'segment-questions-clips', trackingCanvasId: 'tracking-canvas-clips', config: CONFIG,
    });
    container.videoAnnotationManager = m;
    m.videoMetadata.duration = 10;
    m.peaks = fakePeaks();
    m.trackingManager = new TrackingUIManager({
        canvas: document.getElementById('tracking-canvas-clips'),
        video: document.getElementById('video-clips'),
        annotationManager: m,
        onChange: () => m._saveData(),
        config: { videoFps: 30, schemaName: 'clips' },
    });
    m._loadExistingAnnotations();      // what loadVideo does once metadata is in
    return m;
}

function apply(answer) {
    const key = 'L:clips:::_data';
    return client.applyKeys(new Set([key]), answer ? { [key]: JSON.stringify(answer) } : {});
}

const listLabels = () => Array.from(document.querySelectorAll('#annotation-list-clips .annotation-item'))
    .map((el) => el.querySelector('.annotation-label').textContent + '@' + el.dataset.id);
const trackItems = () => Array.from(document.querySelectorAll('.tracking-track-list .tracking-track-item'))
    .map((el) => el.dataset.trackId);
const count = () => document.querySelector('.count-value').textContent;

beforeAll(() => {
    HTMLCanvasElement.prototype.getContext = () => null;
});

beforeEach(() => {
    jest.useFakeTimers();
    loadScripts();
    bootCollab();
    window.saveAnnotations = jest.fn();
    manager = page(ANSWER_A);
    fetchCalls.length = 0;
    changes = 0;
});

afterEach(() => {
    if (manager) manager.destroy();
    jest.useRealTimers();
    window.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
});

describe('restoring the stored answer', () => {
    test('shows segments, keyframes and tracks from the input', () => {
        expect(listLabels()).toEqual(['run@segment_aaaaaa_1', 'run@keyframe_aaaaaa_2']);
        expect(trackItems()).toEqual(['track_aaaaaa_1']);
        expect(count()).toBe('1');
    });

    test('writes nothing and fires no change: the keyframes stay in the input', () => {
        // Before: each restored segment saved the input with the segments so
        // far and no keyframes, and fired `change`, so the autosave stored
        // the item without its keyframes.
        expect(changes).toBe(0);
        const stored = JSON.parse(document.getElementById('input-clips').value);
        expect(stored.keyframes.map((k) => k.id)).toEqual(['keyframe_aaaaaa_2']);
    });

    test('keeps per-segment answers and colours segments by label', () => {
        const seg = manager.segments[0];
        expect(seg.annotations).toEqual({ q: 'yes' });
        expect(seg.color).toBe('#FF0000');
    });
});

describe('live applier', () => {
    test('is registered for the type the generator emits', () => {
        const form = document.querySelector('form[data-schema-name="clips"]');
        expect(form.getAttribute('data-annotation-type')).toBe('video_annotation');
        expect(typeof window.potatoCollabWidgets.video_annotation.apply).toBe('function');
    });

    test("a teammate's answer replaces what is shown", () => {
        const shown = apply(ANSWER_B);
        expect(shown.has('L:clips:::_data')).toBe(true);
        expect(listLabels()).toEqual(['walk@segment_bbbbbb_1', 'walk@segment_bbbbbb_2', 'run@frame_120']);
        expect(count()).toBe('2');
        expect(trackItems()).toEqual(['track_bbbbbb_1', 'track_bbbbbb_2']);
        expect([...manager.peaks._segments.keys()]).toEqual(['segment_bbbbbb_1', 'segment_bbbbbb_2']);
        expect([...manager.peaks._points.keys()]).toEqual(['frame_120']);
    });

    test('a null answer clears everything', () => {
        expect(apply(null).has('L:clips:::_data')).toBe(true);
        expect(listLabels()).toEqual([]);
        expect(document.querySelector('#annotation-list-clips .no-annotations')).not.toBeNull();
        expect(count()).toBe('0');
        expect(trackItems()).toEqual([]);
        expect(manager.peaks._segments.size + manager.peaks._points.size).toBe(0);
        expect(document.getElementById('input-clips').value).toBe('');
    });

    test('applying does not save', () => {
        apply(ANSWER_B);
        apply(null);
        expect(changes).toBe(0);
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(fetchCalls.filter((c) => String(c.input).includes('updateinstance'))).toEqual([]);
    });

    test('applying twice does not duplicate', () => {
        apply(ANSWER_B);
        apply(ANSWER_B);
        expect(listLabels()).toHaveLength(3);
        expect(trackItems()).toHaveLength(2);
        expect(manager.segments).toHaveLength(2);
    });

    test('a selection on a track that is gone goes with it', () => {
        manager.trackingManager.activeTrackId = 'track_aaaaaa_1';
        apply(ANSWER_B);
        expect(manager.trackingManager.activeTrackId).toBeNull();
        expect(document.querySelector('[data-action="delete-track"]').disabled).toBe(true);
    });

    test('the next edit saves the teammate answer plus the edit', () => {
        apply(ANSWER_B);
        manager.createSegment(8, 9, 'run');
        const stored = JSON.parse(document.getElementById('input-clips').value);
        expect(stored.segments.map((s) => s.id).slice(0, 2)).toEqual(['segment_bbbbbb_1', 'segment_bbbbbb_2']);
        expect(stored.segments).toHaveLength(3);
        expect(Object.keys(stored.tracks)).toEqual(['track_bbbbbb_1', 'track_bbbbbb_2']);
    });
});

describe('ids', () => {
    test("two pages' first tracks get different ids", () => {
        const opts = { canvas: null, video: null, config: {} };
        const a = new TrackingUIManager(opts);
        const b = new TrackingUIManager(opts);
        a._renderTrackPanel = b._renderTrackPanel = () => {};
        a.root = b.root = document.createElement('div');
        expect(a.createTrack('car')).not.toBe(b.createTrack('car'));
    });

    test('restored ids are kept, and new ones do not reuse them', () => {
        const t = manager.trackingManager;
        t.loadTrackingData({ track_7: { id: 'track_7', label: 'old', keyframes: {} } });
        const id = t.createTrack('new');
        expect(Object.keys(t.tracks)).toEqual(['track_7', id]);
        expect(id).toMatch(/^track_[a-z0-9]+_\d+$/);
    });

    test("two pages' first segments get different ids", () => {
        const one = page(null).createSegment(1, 2, 'run').id;
        const two = page(null).createSegment(1, 2, 'run').id;
        expect(one).not.toBe(two);
    });
});

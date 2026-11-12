/**
 * tiered_annotation in a live collaborative session (collab.js applyWidget).
 *
 * A teammate's answer replaces every tier on this page, including tiers the
 * answer leaves out (they used to keep their old annotations), and showing it
 * does not save. New annotation ids carry a per-page nonce, and ELAN time
 * slots are named by their time, so two members' saves cannot give one slot
 * key two different times.
 *
 * The REAL tiered-annotation.js and collab.js run here; the markup is the
 * generator's (schemas/tiered_annotation.py, scripts removed).
 */

const fs = require('fs');
const path = require('path');

const STATIC = path.join(__dirname, '..', '..', 'potato', 'static');

// Generator output for two independent tiers, `words` and `notes`.
const MARKUP = `
<form id="tiers" class="annotation-form tiered-annotation-container" data-annotation-type="tiered_annotation" data-schema-name="tiers" data-grid-columns="1"
      action="javascript:void(0)"
      data-annotation-type="tiered_annotation"
      data-schema-name="tiers">
    <fieldset schema="tiers">
        <legend>Tiers</legend>
        <div class="tiered-media-panel" id="media-panel-tiers">
        <audio id="media-tiers" class="tiered-media-player tiered-audio-player" controls preload="metadata"></audio>
        </div>
        <div class="tier-toolbar" id="tier-toolbar-tiers">
            <div class="tier-toolbar-left">
                <select class="tier-select" id="tier-select-tiers">
                    <option value="words">words</option>
                    <option value="notes">notes</option>
                </select>
            </div>
            <div class="tier-toolbar-center">
                <div class="label-buttons-container" id="labels-tiers"></div>
            </div>
            <div class="time-display" id="time-display-tiers">
                <span class="current-time">00:00.000</span>
                <span class="total-time">00:00.000</span>
            </div>
        </div>
        <div class="tiered-timeline-container" id="timeline-container-tiers">
            <div class="waveform-overview-container">
                <div class="waveform-overview" id="overview-tiers"></div>
            </div>
            <div class="zoomed-timeline-container" id="zoomed-container-tiers">
                <span class="zoomed-timeline-range" id="zoomed-range-tiers">0:00 - 0:10</span>
                <div class="zoomed-waveform" id="zoomview-tiers"></div>
                <div class="zoomed-timeline-scroll" id="zoomed-scroll-tiers">
                    <canvas class="zoomed-timeline-canvas" id="zoomed-canvas-tiers"></canvas>
                </div>
                <div class="zoomed-timeline-controls">
                    <button type="button" id="zoomed-left-tiers" title="Scroll left"></button>
                    <input type="range" class="zoomed-timeline-slider" id="zoomed-slider-tiers" min="0" max="100" value="0">
                    <button type="button" id="zoomed-right-tiers" title="Scroll right"></button>
                </div>
            </div>
            <div class="tier-rows-container" id="tier-rows-tiers">
                <div class="tier-row" data-tier="words" data-tier-type="independent" style="height: 50px;">
                    <div class="tier-canvas-container"><canvas class="tier-canvas" id="tier-canvas-tiers-words"></canvas></div>
                </div>
                <div class="tier-row" data-tier="notes" data-tier-type="independent" style="height: 50px;">
                    <div class="tier-canvas-container"><canvas class="tier-canvas" id="tier-canvas-tiers-notes"></canvas></div>
                </div>
            </div>
            <div class="time-axis" id="time-axis-tiers"></div>
        </div>
        <div class="tiered-annotation-list-panel">
            <div class="annotation-list" id="annotation-list-tiers"></div>
        </div>
        <input type="hidden" name="tiers"
               id="input-tiers"
               class="annotation-data-input" value="">
    </fieldset>
</form>`;

const TIERS = [
    { name: 'words', tier_type: 'independent', parent_tier: null, constraint_type: 'none', point: false,
      labels: [{ name: 'W', color: '#4ECDC4' }] },
    { name: 'notes', tier_type: 'independent', parent_tier: null, constraint_type: 'none', point: false,
      labels: [{ name: 'N', color: '#FF6B6B' }] },
];

const ann = (id, tier, start, end, label) => ({ id, tier, start_time: start, end_time: end, label,
                                                color: '#cccccc', parent_id: null, value: '' });

const ANSWER_A = { annotations: {
    words: [ann('ann_1_aaaaaa_1', 'words', 0, 1000, 'W')],
    notes: [ann('ann_1_aaaaaa_2', 'notes', 500, 900, 'N')],
} };

// `notes` is absent: in this answer that tier is empty.
const ANSWER_B = { annotations: {
    words: [ann('ann_2_bbbbbb_1', 'words', 2000, 3000, 'W'), ann('ann_2_bbbbbb_2', 'words', 3000, 4000, 'W')],
} };

/** A Peaks stand-in that keeps what is drawn on the waveform. */
function fakePeaks() {
    const segs = new Map();
    const points = new Map();
    const collection = (map) => ({
        add: (x) => { if (map.has(x.id)) throw new Error('duplicate id ' + x.id); map.set(x.id, x); },
        removeById: (id) => { map.delete(id); },
        removeAll: () => map.clear(),
        getSegment: (id) => map.get(id) || null,
        getPoint: (id) => map.get(id) || null,
    });
    return { segments: collection(segs), points: collection(points), _segments: segs,
             views: { getView: () => null }, on() {}, destroy() {} };
}

/** A 2d context that accepts every call (jsdom has no canvas). */
function stubContext() {
    return new Proxy({}, {
        get(target, key) {
            if (key in target) return target[key];
            if (key === 'measureText') return () => ({ width: 0 });
            return () => {};
        },
        set(target, key, value) { target[key] = value; return true; },
    });
}

let client;
let fetchCalls;
let changes;
let manager;
let renders;

function bootCollab() {
    fetchCalls = [];
    window.fetch = jest.fn((input, init) => {
        fetchCalls.push({ input, init });
        return Promise.resolve({ ok: true, status: 200, clone() { return this; },
                                 json: () => Promise.resolve({ events: [], cursor: 0, answer: {} }) });
    });
    window.potatoCollab = { sid: 'RED', me: 'ben', instance_id: 't1', rev: 1, cursor: 0,
                            team_user: 'team-red', transport: 'poll', poll_interval_ms: 100000, base: '' };
    delete window.potatoCollabClient;
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(path.join(STATIC, 'collab.js'), 'utf8'))();
    client = window.potatoCollabClient;
    window.fetch.mockClear = () => {};
}

/** The page as initialize() leaves it, showing `answer`. */
function page(answer, extraConfig) {
    document.body.innerHTML = MARKUP;
    const input = document.getElementById('input-tiers');
    if (answer) {
        input.value = JSON.stringify(answer);
        input.setAttribute('data-server-set', 'true');
    }
    changes = 0;
    input.addEventListener('change', () => { changes += 1; });
    const form = document.getElementById('tiers');
    const m = new window.TieredAnnotationManager(form, Object.assign({
        schemaName: 'tiers', mediaType: 'audio', sourceField: 'audio_url', tiers: TIERS,
    }, extraConfig || {}));
    form._tieredManager = m;
    m._initializeTierViews();
    m._initializeZoomedTimeline();
    m.peaks = fakePeaks();
    renders = 0;
    Object.values(m.tierViews).forEach((view) => {
        const real = view.render.bind(view);
        view.render = () => { renders += 1; real(); };
    });
    m._loadExistingAnnotations();
    m._renderAllTiers();
    return m;
}

function apply(answer) {
    const key = 'L:tiers:::_data';
    return client.applyKeys(new Set([key]), answer ? { [key]: JSON.stringify(answer) } : {});
}

const listed = () => Array.from(document.querySelectorAll('#annotation-list-tiers .annotation-list-tier-header'))
    .map((el) => el.textContent);
const items = () => document.querySelectorAll('#annotation-list-tiers .annotation-list-item');

beforeAll(() => {
    HTMLCanvasElement.prototype.getContext = () => stubContext();
    delete window.potatoCollabWidgets;
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(path.join(STATIC, 'tiered-annotation.js'), 'utf8'))();
});

beforeEach(() => {
    jest.useFakeTimers();
    bootCollab();
    window.saveAnnotations = jest.fn();
    manager = page(ANSWER_A);
    fetchCalls.length = 0;
    changes = 0;
});

afterEach(() => {
    jest.useRealTimers();
    window.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
});

describe('live applier', () => {
    test('is registered for the type the generator emits', () => {
        expect(document.getElementById('tiers').getAttribute('data-annotation-type')).toBe('tiered_annotation');
        expect(typeof window.potatoCollabWidgets.tiered_annotation.apply).toBe('function');
    });

    test("a teammate's answer replaces every tier, the ones it leaves out too", () => {
        expect(listed()).toEqual(['words (1)', 'notes (1)']);
        renders = 0;
        expect(apply(ANSWER_B).has('L:tiers:::_data')).toBe(true);
        expect(listed()).toEqual(['words (2)']);
        expect(items()).toHaveLength(2);
        expect(manager.annotations.notes).toEqual([]);
        expect([...manager.peaks._segments.keys()]).toEqual(['ann_2_bbbbbb_1', 'ann_2_bbbbbb_2']);
        expect(renders).toBeGreaterThanOrEqual(2);       // both tier canvases redrawn
    });

    test('a null answer clears everything', () => {
        expect(apply(null).has('L:tiers:::_data')).toBe(true);
        expect(listed()).toEqual([]);
        expect(items()).toHaveLength(0);
        expect(manager.peaks._segments.size).toBe(0);
    });

    test('a null answer shows the transcript seed, as an unanswered item does', () => {
        const seeded = page(ANSWER_A, { transcriptField: 'transcript', transcriptTier: 'words' });
        const record = document.createElement('div');
        record.setAttribute('data-instance-json', JSON.stringify({ _transcripts: { transcript: {
            turns: [{ turn_id: 'u1', start: 0, end: 1.5, text: 'hi' }] } } }));
        document.body.appendChild(record);
        apply(null);
        expect(seeded.annotations.words.map((a) => a.id)).toEqual(['turn-u1']);
        expect(seeded.annotations.notes).toEqual([]);
        expect(listed()).toEqual(['words (1)']);
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
        expect(items()).toHaveLength(2);
        expect(manager.annotations.words).toHaveLength(2);
    });

    test('a selection survives when its annotation is still there', () => {
        manager.selectedAnnotation = manager.annotations.words[0];
        apply({ annotations: { words: [ann('ann_1_aaaaaa_1', 'words', 0, 1200, 'W')] } });
        expect(manager.selectedAnnotation.end_time).toBe(1200);
        expect(document.querySelector('.annotation-list-item.selected')).not.toBeNull();
        apply(ANSWER_B);
        expect(manager.selectedAnnotation).toBeNull();
    });
});

describe('ids and time slots', () => {
    test("two pages' first annotations get different ids, even in one millisecond", () => {
        const now = jest.spyOn(Date, 'now').mockReturnValue(1700000000000);
        try {
            const one = page(null).createAnnotation('words', 0, 1, 'W').id;
            const two = page(null).createAnnotation('words', 0, 1, 'W').id;
            expect(one).not.toBe(two);
        } finally {
            now.mockRestore();
        }
    });

    test('a slot keeps its key when an earlier boundary is added', () => {
        const m = page(null);
        m.createAnnotation('words', 1, 2, 'W');
        const before = m._generateTimeSlots();
        m.createAnnotation('notes', 0.5, 0.8, 'N');
        const after = m._generateTimeSlots();
        Object.keys(before).forEach((key) => expect(after[key]).toBe(before[key]));
    });

    test('two pages name a shared time the same', () => {
        const a = page(null);
        a.createAnnotation('words', 1, 2, 'W');
        const slotsA = a._generateTimeSlots();
        const b = page(null);
        b.createAnnotation('words', 0.2, 1, 'W');
        const slotsB = b._generateTimeSlots();
        Object.keys(slotsA).filter((k) => k in slotsB).forEach((k) => expect(slotsB[k]).toBe(slotsA[k]));
        expect(Object.values(slotsA)).toContain(1000);
        expect(Object.keys(slotsA).find((k) => slotsA[k] === 1000))
            .toBe(Object.keys(slotsB).find((k) => slotsB[k] === 1000));
    });
});

/**
 * interval_label in a live collaborative session (collab.js applyWidget).
 *
 * The widget's state is private to its module and PotatoIntervalLabel.init()
 * leaves an already set-up form alone, so a teammate's answer could not be
 * shown without a reload. restore() replaces the intervals and events and
 * redraws, without saving. New intervals and events carry an id with a
 * per-page nonce, so the server's merge (by id) can tell two members' entries
 * apart and match one entry edited by both.
 *
 * The REAL interval-label.js and collab.js run here; the time_series plot is
 * a stub that records what it is asked to draw. The markup is the
 * generator's (schemas/interval_label.py).
 */

const fs = require('fs');
const path = require('path');

const STATIC = path.join(__dirname, '..', '..', 'potato', 'static');

function config(overrides) {
    const cfg = Object.assign({
        schema: 'stages', signalField: 'eeg', mode: 'free', epochLength: 30.0,
        labels: [
            { name: 'wake', key: '1', color: '#0072B2', kind: 'interval', tooltip: '' },
            { name: 'N1', key: '2', color: '#E69F00', kind: 'interval', tooltip: '' },
            { name: 'arousal', key: '3', color: '#009E73', kind: 'event', tooltip: '' },
        ],
        channelScope: 'all', autoAdvance: true, allowOverlap: true, nextKey: ']', previousKey: '[',
        preAnnotations: true, requireAllEpochs: false, minAnnotations: 0,
    }, overrides || {});
    return JSON.stringify(cfg).replace(/"/g, '&quot;');
}

// Generator output for {name: stages, signal_field: eeg, labels: [wake, N1, arousal (event)]}.
const markup = (cfg) => `
    <input id="instance_id" type="hidden" value="i1">
    <form id="stages" class="annotation-form interval-label" action="javascript:void(0)"
          data-annotation-type="interval_label" data-schema-name="stages"
          data-il-config='${cfg}' data-grid-columns="1">
        <fieldset schema="stages">
            <legend class="il-title">Stages</legend>
            <div class="il-labels" role="toolbar" aria-label="Labels"><button type="button" class="il-label" data-label="wake" data-kind="interval" aria-pressed="false"><span class="il-swatch" style="background:#0072B2" aria-hidden="true"></span><kbd class="il-key">1</kbd><span class="il-name">wake</span><span class="il-kind"></span></button><button type="button" class="il-label" data-label="N1" data-kind="interval" aria-pressed="false"><span class="il-swatch" style="background:#E69F00" aria-hidden="true"></span><kbd class="il-key">2</kbd><span class="il-name">N1</span><span class="il-kind"></span></button><button type="button" class="il-label" data-label="arousal" data-kind="event" aria-pressed="false"><span class="il-swatch" style="background:#009E73" aria-hidden="true"></span><kbd class="il-key">3</kbd><span class="il-name">arousal</span><span class="il-kind"> (event)</span></button></div>
            <p class="il-pre" hidden>
                <span class="il-pre-text"></span>
                <button type="button" class="il-keep">Keep these</button>
                <button type="button" class="il-discard">Discard them</button>
            </p>
            <p class="il-message" role="status" aria-live="polite"></p>
            <div class="il-list-wrap">
                <table class="il-list">
                    <caption class="il-list-caption">Labelled intervals and events</caption>
                    <thead><tr><th scope="col">Time</th><th scope="col">Label</th>
                        <th scope="col">Channel</th><th scope="col"><span class="il-sr">Actions</span></th></tr></thead>
                    <tbody></tbody>
                </table>
                <p class="il-empty">Nothing labelled yet.</p>
            </div>
            <input type="hidden" class="annotation-input interval-label-input"
                   id="stages_stages_hidden" name="stages:::stages"
                   schema="stages" label_name="stages"
                   validation="" value="">
        </fieldset>
    </form>`;

/** A time_series plot that records what the scheme draws on it. */
function fakePlot() {
    const handlers = {};
    return {
        handlers, overlays: null,
        meta: { tStart: 0, tEnd: 300 },
        epochLength: null,
        on(name, fn) { (handlers[name] = handlers[name] || []).push(fn); },
        fire(name, arg) { (handlers[name] || []).forEach((fn) => fn(arg)); },
        setBrushScope() {}, setEpochMode() {},
        setOverlays(o) { this.overlays = o; },
        setOverviewMarks() {},
        getView: () => ({ start: 0, end: 300 }),
        timeLabel: (t) => String(t),
        epochIndex: () => 0, epochCount: () => 10,
        epochBounds: (k) => ({ start: k * 30, end: (k + 1) * 30 }),
        step() {}, epoch() {},
    };
}

const A = { intervals: [{ id: 'iv_aaaaaa_1', start: 0, end: 30, label: 'wake', channel: null }], events: [] };
const B = {
    intervals: [{ id: 'iv_bbbbbb_1', start: 30, end: 60, label: 'N1', channel: null },
                { id: 'iv_bbbbbb_2', start: 90, end: 120, label: 'wake', channel: 'C3' }],
    events: [{ id: 'ev_bbbbbb_3', time: 41.25, label: 'arousal', channel: null }],
};

let client;
let fetchCalls;
let changes;
let plot;

function loadWidget() {
    delete window.PotatoIntervalLabel;
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(path.join(STATIC, 'interval-label.js'), 'utf8'))();
}

function bootCollab() {
    window.potatoCollab = { sid: 'RED', me: 'ben', instance_id: 'i1', rev: 1, cursor: 0,
                            team_user: 'team-red', transport: 'poll', poll_interval_ms: 100000, base: '' };
    delete window.potatoCollabClient;
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(path.join(STATIC, 'collab.js'), 'utf8'))();
    client = window.potatoCollabClient;
    window.fetch.mockClear = () => {};
}

/** The page once the scheme has bound its plot, showing `answer`. */
function page(answer, cfgOverrides) {
    document.body.innerHTML = markup(config(cfgOverrides));
    const input = document.getElementById('stages_stages_hidden');
    if (answer) {
        input.value = JSON.stringify(answer);
        input.setAttribute('data-server-set', 'true');
    }
    changes = 0;
    input.addEventListener('change', () => { changes += 1; });
    plot = fakePlot();
    window.PotatoTimeSeries = { whenReady: (field, cb) => cb(plot) };
    window.PotatoIntervalLabel.init();
    return document.getElementById('stages');
}

function apply(answer) {
    const key = 'L:stages:::stages';
    return client.applyKeys(new Set([key]), answer ? { [key]: JSON.stringify(answer) } : {});
}

const listRows = () => Array.from(document.querySelectorAll('#stages .il-list tbody tr'))
    .map((tr) => tr.querySelector('.il-when').textContent + ' ' + tr.children[1].textContent.trim());
const stored = () => JSON.parse(document.getElementById('stages_stages_hidden').value || '{"intervals":[],"events":[]}');

beforeAll(() => {
    fetchCalls = [];
    window.fetch = jest.fn((input, init) => {
        fetchCalls.push({ input, init });
        // The item's pre-annotations (/api/signals/preannotations), when a test sets them.
        const body = String(input).includes('/api/signals/preannotations') && window.__pre
            ? window.__pre : { events: [], cursor: 0, answer: {} };
        return Promise.resolve({ ok: true, status: 200, clone() { return this; },
                                 json: () => Promise.resolve(body) });
    });
    bootCollab();
    loadWidget();
});

beforeEach(() => {
    window.saveAnnotations = jest.fn();
    page(A);
    fetchCalls.length = 0;
    changes = 0;
});

describe('live applier', () => {
    test('is registered for the type the generator emits', () => {
        expect(document.getElementById('stages').getAttribute('data-annotation-type')).toBe('interval_label');
        expect(typeof window.potatoCollabWidgets.interval_label.apply).toBe('function');
        expect(listRows()).toEqual(['0–30 wake']);
    });

    test("a teammate's answer replaces the list and the plot overlays", () => {
        expect(apply(B).has('L:stages:::stages')).toBe(true);
        expect(listRows()).toEqual(['30–60 N1', '41.25 arousal (event)', '90–120 wake']);
        expect(document.querySelector('#stages .il-empty').hidden).toBe(true);
        expect(document.getElementById('stages').getAttribute('data-il-count')).toBe('3');
        expect(plot.overlays.intervals.map((iv) => iv.label)).toEqual(['N1', 'wake']);
        expect(plot.overlays.events.map((ev) => ev.time)).toEqual([41.25]);
    });

    test('a null answer clears it', () => {
        expect(apply(null).has('L:stages:::stages')).toBe(true);
        expect(listRows()).toEqual([]);
        expect(document.querySelector('#stages .il-empty').hidden).toBe(false);
        expect(plot.overlays.intervals).toEqual([]);
        expect(document.getElementById('stages').getAttribute('data-il-count')).toBe('0');
    });

    test('applying does not save', () => {
        apply(B);
        apply(null);
        expect(changes).toBe(0);
        expect(document.getElementById('stages_stages_hidden').hasAttribute('data-modified')).toBe(false);
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(fetchCalls.filter((c) => String(c.input).includes('updateinstance'))).toEqual([]);
    });

    test('applying twice does not duplicate', () => {
        apply(B);
        apply(B);
        expect(listRows()).toHaveLength(3);
        expect(plot.overlays.intervals).toHaveLength(2);
    });

    test('a selection survives when its entry is still there', () => {
        apply(B);
        plot.fire('click', { time: 45, channel: null });     // inside N1 30-60
        expect(document.querySelectorAll('#stages .il-row.il-selected')).toHaveLength(1);
        apply({ intervals: [{ id: 'iv_bbbbbb_1', start: 30, end: 60, label: 'wake', channel: null }], events: [] });
        const sel = document.querySelectorAll('#stages .il-row.il-selected');
        expect(sel).toHaveLength(1);
        expect(sel[0].textContent).toContain('wake');
    });

    test('the next edit saves the teammate answer plus the edit', () => {
        apply(B);
        plot.fire('brush', { start: 150, end: 160 });
        expect(stored().intervals.map((iv) => iv.id).slice(0, 2)).toEqual(['iv_bbbbbb_1', 'iv_bbbbbb_2']);
        expect(stored().intervals).toHaveLength(3);
        expect(stored().events).toHaveLength(1);
    });
});

describe('ids', () => {
    test("two pages' first intervals get different ids", () => {
        page(null);
        plot.fire('brush', { start: 10, end: 20 });
        const first = stored().intervals[0].id;
        loadWidget();                                    // another page
        page(null);
        plot.fire('brush', { start: 10, end: 20 });
        const second = stored().intervals[0].id;
        expect(first).toBeTruthy();
        expect(second).toBeTruthy();
        expect(first).not.toBe(second);
    });

    test('an event gets an id, and a stored id is kept on save', () => {
        page(A);
        window.PotatoIntervalLabel._states.get(document.getElementById('stages')).active = 'arousal';
        plot.fire('click', { time: 5, channel: null });
        const value = stored();
        expect(value.intervals[0].id).toBe('iv_aaaaaa_1');
        expect(value.events[0].id).toMatch(/^ev_[a-z0-9]+_\d+$/);
    });

    test('splitting an interval gives the new part its own id', () => {
        page({ intervals: [{ id: 'iv_aaaaaa_1', start: 0, end: 100, label: 'wake', channel: null }], events: [] },
             { allowOverlap: false });
        plot.fire('brush', { start: 40, end: 60 });
        const ids = stored().intervals.map((iv) => iv.id);
        expect(ids).toHaveLength(3);
        expect(new Set(ids).size).toBe(3);
        expect(ids).toContain('iv_aaaaaa_1');
    });
});

// An item with no entries offers the file's annotations (Keep these /
// Discard them), so a reload of a cleared item shows them. A cleared answer
// shown live must too, without saving.
describe('a cleared answer shows the pre-annotations', () => {
    const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
    const FROM_FILE = { intervals: [], events: [{ time: 200.5, label: 'arousal', channel: null, source: 'file' }] };

    beforeEach(() => { window.__pre = FROM_FILE; });
    afterEach(() => { delete window.__pre; });

    test("they come back pending, with the prompt, and nothing is saved", async () => {
        apply(B);
        await flush();
        expect(listRows()).toHaveLength(3);
        fetchCalls.length = 0;

        expect(apply(null).has('L:stages:::stages')).toBe(true);
        await flush();
        expect(listRows()).toEqual(['200.5 arousal (event) · from file']);
        expect(document.querySelector('#stages .il-pre').hidden).toBe(false);
        expect(document.querySelector('#stages .il-empty').hidden).toBe(true);
        expect(plot.overlays.events.map((ev) => ev.time)).toEqual([200.5]);
        const input = document.getElementById('stages_stages_hidden');
        expect(input.value).toBe('');
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(changes).toBe(0);
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(fetchCalls.filter((c) => String(c.input).includes('updateinstance'))).toEqual([]);
    });

    test("a teammate's answer that arrives while they load wins", async () => {
        apply(null);
        apply(B);
        await flush();
        expect(listRows()).toHaveLength(3);
        expect(document.querySelector('#stages .il-pre').hidden).toBe(true);
    });
});

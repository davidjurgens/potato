/**
 * spectrogram_annotation in a live collaborative session (collab.js
 * applyWidget).
 *
 * The widget's state is private to its module and PotatoSpectrogram.init()
 * leaves an already set-up form alone, so a teammate's answer could not be
 * shown without a reload. restore() replaces the boxes and redraws, without
 * saving.
 *
 * The REAL spectrogram-annotation.js and collab.js run here (Web Audio and
 * the canvas are stubbed); the markup is the generator's
 * (schemas/spectrogram_annotation.py).
 */

const fs = require('fs');
const path = require('path');

const STATIC = path.join(__dirname, '..', '..', 'potato', 'static');

// Generator output for {name: calls, labels: [song, call], source_field: audio}.
const CONFIG = '{&quot;schema&quot;: &quot;calls&quot;, &quot;labels&quot;: [{&quot;name&quot;: &quot;song&quot;, &quot;color&quot;: &quot;#2563eb&quot;, &quot;key&quot;: &quot;1&quot;}, {&quot;name&quot;: &quot;call&quot;, &quot;color&quot;: &quot;#dc2626&quot;, &quot;key&quot;: &quot;2&quot;}], &quot;sourceField&quot;: &quot;audio&quot;, &quot;minFreq&quot;: 0.0, &quot;maxFreq&quot;: null, &quot;fftSize&quot;: 1024, &quot;colormap&quot;: &quot;viridis&quot;, &quot;height&quot;: 280, &quot;minBoxes&quot;: 0, &quot;maxBoxes&quot;: null}';
const MARKUP = `
    <input id="instance_id" type="hidden" value="i1">
    <form id="calls" class="annotation-form spectrogram-annotation" action="javascript:void(0)"
          data-annotation-type="spectrogram_annotation" data-schema-name="calls"
          data-spectrogram-config='${CONFIG}' data-grid-columns="1">
        <fieldset schema="calls">
            <legend class="sg-title">Calls</legend>
            <div class="sg-root">
                <p class="sg-loading" role="status">Loading audio…</p>
            </div>
            <input type="hidden" class="annotation-data-input spectrogram-input"
                   id="input-calls" name="calls" schema="calls"
                   validation="" value="">
        </fieldset>
    </form>`;

const box = (id, start, end, label) => ({ id, start_s: start, end_s: end, low_hz: 500, high_hz: 1500,
                                          label, source: 'human' });
const ANSWER_A = [box('box_aaaaaa_1', 0.1, 0.2, 'song')];
const ANSWER_B = [box('box_bbbbbb_1', 0.3, 0.4, 'call'), box('box_bbbbbb_2', 0.5, 0.6, 'song')];

let client;
let fetchCalls;
let changes;
let decodes;

function bootCollab() {
    window.potatoCollab = { sid: 'RED', me: 'ben', instance_id: 'i1', rev: 1, cursor: 0,
                            team_user: 'team-red', transport: 'poll', poll_interval_ms: 100000, base: '' };
    delete window.potatoCollabClient;
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(path.join(STATIC, 'collab.js'), 'utf8'))();
    client = window.potatoCollabClient;
    window.fetch.mockClear = () => {};
}

async function flush() {
    for (let i = 0; i < 20; i++) await Promise.resolve();
}

/** The page once the widget has set itself up (and, unless told, decoded). */
async function page(answer, { hold, status } = {}) {
    // The navbar's status badge (base_template_v2.html), when a test needs it.
    document.body.innerHTML = (status ? `<div class="annotation-status-indicator" id="annotation-status">
        <span class="status-badge ${status}">${status}</span></div>` : '') + MARKUP;
    const input = document.getElementById('input-calls');
    if (answer) {
        input.value = JSON.stringify(answer);
        input.setAttribute('data-server-set', 'true');
    }
    changes = 0;
    input.addEventListener('change', () => { changes += 1; });
    decodes = [];
    window.__holdDecode = !!hold;
    window.PotatoSpectrogram.init();
    await flush();
    return document.getElementById('calls');
}

const drawn = () => Array.from(document.querySelectorAll('#calls .sg-boxes .sg-box'))
    .map((el) => el.querySelector('.sg-tag').textContent);
const rows = () => document.querySelectorAll('#calls .sg-list tbody tr');
const counted = () => document.querySelector('#calls .sg-count').textContent;

function apply(answer) {
    const key = 'L:calls:::_data';
    return client.applyKeys(new Set([key]), answer ? { [key]: JSON.stringify(answer) } : {});
}

beforeAll(() => {
    HTMLCanvasElement.prototype.getContext = () => ({
        createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
        putImageData() {},
    });
    window.AudioContext = class {
        constructor() { this.sampleRate = 8000; this.currentTime = 0; this.state = 'running'; }
        decodeAudioData(data, ok) {
            const buffer = { duration: 1, sampleRate: 8000, length: 8000, numberOfChannels: 1,
                             getChannelData: () => new Float32Array(8000) };
            if (window.__holdDecode) { decodes.push(() => ok(buffer)); return undefined; }
            ok(buffer);
            return undefined;
        }
    };
    window.potatoInstanceField = () => '/media/clip.wav';
    fetchCalls = [];
    window.fetch = jest.fn((input, init) => {
        fetchCalls.push({ input, init });
        return Promise.resolve({ ok: true, status: 200, clone() { return this; },
                                 arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)),
                                 json: () => Promise.resolve({ events: [], cursor: 0, answer: {} }) });
    });
    bootCollab();
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(path.join(STATIC, 'spectrogram-annotation.js'), 'utf8'))();
});

beforeEach(async () => {
    window.saveAnnotations = jest.fn();
    await page(ANSWER_A);
    fetchCalls.length = 0;
    changes = 0;
});

describe('live applier', () => {
    test('is registered for the type the generator emits', () => {
        expect(document.getElementById('calls').getAttribute('data-annotation-type')).toBe('spectrogram_annotation');
        expect(typeof window.potatoCollabWidgets.spectrogram_annotation.apply).toBe('function');
        expect(drawn()).toEqual(['song']);
    });

    test("a teammate's answer replaces the boxes", () => {
        expect(apply(ANSWER_B).has('L:calls:::_data')).toBe(true);
        expect(drawn()).toEqual(['call', 'song']);
        expect(rows()).toHaveLength(2);
        expect(counted()).toBe('2 boxes');
    });

    test('a null answer clears them', () => {
        expect(apply(null).has('L:calls:::_data')).toBe(true);
        expect(drawn()).toEqual([]);
        expect(rows()).toHaveLength(0);
        expect(document.querySelector('#calls .sg-list-wrap').hidden).toBe(true);
    });

    test('applying does not save', () => {
        apply(ANSWER_B);
        apply(null);
        const input = document.getElementById('input-calls');
        expect(changes).toBe(0);
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(fetchCalls.filter((c) => String(c.input).includes('updateinstance'))).toEqual([]);
    });

    test('applying twice does not duplicate', () => {
        apply(ANSWER_B);
        apply(ANSWER_B);
        expect(drawn()).toHaveLength(2);
        expect(rows()).toHaveLength(2);
    });

    test('the selected box stays selected when it is still there', () => {
        document.querySelector('#calls .sg-box').dispatchEvent(new Event('focus'));
        expect(document.querySelectorAll('#calls .sg-box.sg-selected')).toHaveLength(1);
        apply([box('box_aaaaaa_1', 0.1, 0.3, 'song')].concat(ANSWER_B));
        const selected = document.querySelectorAll('#calls .sg-box.sg-selected');
        expect(selected).toHaveLength(1);
        expect(selected[0].querySelector('.sg-tag').textContent).toBe('song');
        expect(selected[0].getAttribute('aria-label')).toContain('0.10 to 0.30 s');
    });

    test('an answer that arrives before the audio is decoded is drawn once it is', async () => {
        await page(ANSWER_A, { hold: true });
        expect(drawn()).toEqual([]);                    // nothing drawn yet
        expect(apply(ANSWER_B).has('L:calls:::_data')).toBe(true);
        decodes.forEach((finish) => finish());
        await flush();
        expect(drawn()).toEqual(['call', 'song']);
    });

    test('the next edit saves the teammate answer plus the edit', () => {
        apply(ANSWER_B);
        document.querySelector('#calls .sg-box').dispatchEvent(new Event('focus'));
        // Selecting redraws the boxes, so take the node again.
        document.querySelector('#calls .sg-box.sg-selected')
            .dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true }));
        const stored = JSON.parse(document.getElementById('input-calls').value);
        expect(stored.map((b) => b.id)).toEqual(['box_bbbbbb_2']);
    });
});

// The server writes pre-annotations (a Raven table's boxes) into the input
// only while the item has no answer, so a reload of a cleared item shows
// them again. A cleared answer shown live must too, without saving.
describe('a cleared answer shows the pre-annotations', () => {
    const imported = (start, end, label) => ({ start_s: start, end_s: end, low_hz: 500, high_hz: 1500,
                                               label, source: 'import', import_format: 'raven' });
    const PREFILL = [imported(0.1, 0.2, 'song'), imported(0.4, 0.5, 'call')];

    test('the boxes an unanswered item opened with come back, quietly', async () => {
        await page(PREFILL, { status: 'unlabeled' });
        expect(drawn()).toEqual(['song', 'call']);
        apply(ANSWER_B);
        expect(drawn()).toEqual(['call', 'song']);
        changes = 0;

        expect(apply(null).has('L:calls:::_data')).toBe(true);
        expect(drawn()).toEqual(['song', 'call']);
        expect(rows()).toHaveLength(2);
        expect(counted()).toBe('2 boxes');
        // In the input as a reload puts them, so Next keeps them as a reload's would.
        const input = document.getElementById('input-calls');
        expect(JSON.parse(input.value)).toEqual(PREFILL);
        expect(input.getAttribute('data-server-set')).toBe('true');
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(changes).toBe(0);
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(fetchCalls.filter((c) => String(c.input).includes('updateinstance'))).toEqual([]);
    });

    test('an answer the page loaded with is not taken for pre-annotations', async () => {
        await page(PREFILL, { status: 'labeled' });
        apply(null);
        expect(drawn()).toEqual([]);
        expect(document.getElementById('input-calls').value).toBe('');
    });
});

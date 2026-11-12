/**
 * Live sessions: a teammate's answer reaches the episode, rollout, grounding,
 * region-caption and turn-level widgets.
 *
 * Each widget read its hidden input once, on load, and kept its own copy of the
 * answer after that. collab.js writes a teammate's answer into the input and
 * calls `window.potatoCollabWidgets[type].apply(ctx)`; these tests load the
 * real widget files over the markup the real generators emit, apply a
 * teammate's answer, and check what the annotator sees against a page freshly
 * loaded with that answer.
 *
 * episode_annotation, rollout_evaluation, grounding_eval and region_caption
 * render as a <div>, not a <form>, so collab.js's form lookup does not find
 * them yet; their appliers are called here the way collab.js calls them, with
 * the input already written. turn_level renders a <form> and goes through
 * collab.js end to end.
 */

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const REPO = path.join(__dirname, '..', '..');
const STATIC = path.join(REPO, 'potato', 'static');
const source = (name) => fs.readFileSync(path.join(STATIC, name), 'utf8');
const SOURCES = {
    episode: source('episode-timeline.js'),
    rollout: source('rollout-eval.js'),
    grounding: source('grounding-eval.js'),
    caption: source('region-caption.js'),
    turns: source('turn-annotations.js'),
    collab: source('collab.js'),
};
// eslint-disable-next-line no-new-func
const load = (name) => new Function(SOURCES[name])();

if (typeof CSS === 'undefined') global.CSS = {};
if (!CSS.escape) CSS.escape = (v) => String(v).replace(/["\\]/g, '\\$&');

const TURN_SCHEME = {
    annotation_type: 'radio', name: 'stance', description: 'Stance',
    labels: ['good', 'bad'], turn_binding: { field: 'conversation' },
};
const TONE_SCHEME = Object.assign({}, TURN_SCHEME, { name: 'tone', labels: ['calm', 'sharp'] });
const TURNS = [{ speaker: 'a', text: 'x' }, { speaker: 'b', text: 'y' }];

let markup;
beforeAll(() => {
    const code = `
import json, sys, logging
logging.disable(logging.CRITICAL)
from potato.server_utils.schemas.episode_annotation import generate_episode_annotation_layout as ep
from potato.server_utils.schemas.rollout_evaluation import generate_rollout_evaluation_layout as ro
from potato.server_utils.schemas.grounding_eval import generate_grounding_eval_layout as ge
from potato.server_utils.schemas.region_caption import generate_region_caption_layout as rc
from potato.server_utils.turn_annotations import generate_turn_level_anchor_layout, render_turn_slot
schemes = json.loads(sys.argv[1]); turns = json.loads(sys.argv[2])
out = {
    'episode': ep({'annotation_type': 'episode_annotation', 'name': 'ep', 'description': 'd'})[0],
    'rollout': ro({'annotation_type': 'rollout_evaluation', 'name': 'ro', 'description': 'd',
                   'streams': ['a', 'b'], 'rubric': {'safety': 'how safe'}})[0],
    'grounding': ge({'annotation_type': 'grounding_eval', 'name': 'g', 'description': 'd',
                     'predictions_field': 'predictions'})[0],
    'caption': rc({'annotation_type': 'region_caption', 'name': 'rc', 'description': 'd'})[0],
    'turns': ''.join(generate_turn_level_anchor_layout(s)[0] for s in schemes)
             + ''.join(render_turn_slot(schemes, t, i, 'conversation') for i, t in enumerate(turns)),
}
sys.stdout.write(json.dumps(out))
`;
    markup = JSON.parse(execFileSync('python', ['-c', code, JSON.stringify([TURN_SCHEME, TONE_SCHEME]),
        JSON.stringify(TURNS)], { cwd: REPO, encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'] }));
    load('episode');
    load('rollout');
    load('grounding');
    load('caption');
    load('turns');
});

// ---------------------------------------------------------------------------
// Harness

let fetchCalls;
let routes;
beforeEach(() => {
    fetchCalls = [];
    routes = {};
    window.fetch = jest.fn((url) => {
        fetchCalls.push(String(url));
        const key = Object.keys(routes).find((prefix) => String(url).startsWith(prefix));
        const body = key ? routes[key] : {};
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body),
                                 clone() { return this; } });
    });
    window.saveAnnotations = jest.fn();
    // Canvas: record what each draw paints (jsdom has no 2D context).
    HTMLCanvasElement.prototype.getContext = function () {
        const canvas = this;
        const ctx = {};
        return new Proxy(ctx, {
            get(target, prop) {
                if (prop in target) return target[prop];
                if (prop === 'clearRect') return () => { canvas._texts = []; };
                if (prop === 'fillText') return (text) => { (canvas._texts = canvas._texts || []).push(String(text)); };
                if (prop === 'measureText') return () => ({ width: 10 });
                return () => {};
            },
            set(target, prop, value) { target[prop] = value; return true; },
        });
    };
    HTMLCanvasElement.prototype.getBoundingClientRect = () => ({
        left: 0, top: 0, width: 600, height: 300, right: 600, bottom: 300 });
});

async function settle() {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

/** Mount generated markup, with the hidden input as the server renders it. */
function mount(html, inputSelector, answer, before) {
    const scripts = [];
    const body = html.replace(/<script>([\s\S]*?)<\/script>/g, (m, s) => { scripts.push(s); return ''; });
    document.body.innerHTML = (before || '') + body;
    const input = document.querySelector(inputSelector);
    if (answer !== null && answer !== undefined) {
        const json = typeof answer === 'string' ? answer : JSON.stringify(answer);
        input.value = json;
        input.setAttribute('value', json);
        input.setAttribute('data-server-set', 'true');
    }
    // eslint-disable-next-line no-new-func
    scripts.forEach((s) => new Function(s)());
    return input;
}

/** What collab.js does before calling a widget: write the answer, then apply. */
function applyTeammate(type, schema, input, answer) {
    const json = answer === null ? '' : JSON.stringify(answer);
    input.value = json;
    input.setAttribute('value', json);
    input.removeAttribute('data-modified');
    if (json) input.setAttribute('data-server-set', 'true');
    else input.removeAttribute('data-server-set');
    const form = document.querySelector(`[data-schema-name="${schema}"]`);
    return window.potatoCollabWidgets[type].apply({
        schema, form, input, inputs: [], value: json || null,
        labels: json ? { _data: json } : null,
    });
}

function controls(root) {
    return Array.from(root.querySelectorAll('input, select, textarea'))
        .filter((el) => el.type !== 'hidden')
        .map((el) => [el.name || el.className, el.value, !!el.checked, !!el.disabled]);
}

function watchSaves(input) {
    const seen = { changes: 0 };
    input.addEventListener('change', () => { seen.changes += 1; });
    return seen;
}

function expectNoSave(input, seen) {
    expect(seen.changes).toBe(0);
    expect(input.hasAttribute('data-modified')).toBe(false);
    expect(window.saveAnnotations).not.toHaveBeenCalled();
    expect(fetchCalls.filter((u) => u.includes('/updateinstance'))).toHaveLength(0);
}

// ---------------------------------------------------------------------------
// episode_annotation

describe('episode_annotation', () => {
    const LOCAL = {
        phases: [{ id: 'p1', start: 0, end: 3, label: 'reach' }],
        reward: [{ t: 1, value: 0.5 }],
        outcome: { result: 'success', cause: '' },
        instructions: [{ text: 'mine', start: null, end: null }],
    };
    const REMOTE = {
        phases: [{ id: 'q1', start: 2, end: 6, label: 'grasp' },
                 { id: 'q2', start: 6, end: 9, label: 'place' }],
        reward: [],
        outcome: { result: 'failure', cause: 'collision' },
        instructions: [{ text: 'theirs', start: 2, end: 6 }],
    };

    async function page(answer) {
        routes = { '/api/current_instance': { data: { episode: 'ep1' } },
                   '/api/episode/': { fps: 10, duration: 10, num_frames: 100, streams: [], series: [] } };
        const input = mount(markup.episode, '#input-ep', answer);
        await settle();
        const box = document.querySelector('.episode-annotation-container');
        return { input, box, manager: box.annotationManager };
    }

    function view({ box, manager }) {
        manager.draw();
        const canvas = box.querySelector('canvas');
        return JSON.stringify({
            drawn: (canvas._texts || []).filter((t) => !['Phase', 'Reward'].includes(t)),
            controls: controls(box),
            span: box.querySelector('.episode-relabel-span').textContent,
            count: manager.getAnnotationCount(),
        });
    }

    test('the answers are visibly different', async () => {
        const a = view(await page(LOCAL));
        const b = view(await page(REMOTE));
        const none = view(await page(null));
        expect(a).not.toBe(b);
        expect(b).not.toBe(none);
        expect(JSON.parse(b).drawn).toEqual(['grasp', 'place']);
    });

    test("a teammate's answer replaces the one on screen, and saves nothing", async () => {
        const expected = view(await page(REMOTE));
        const p = await page(LOCAL);
        const seen = watchSaves(p.input);
        expect(applyTeammate('episode_annotation', 'ep', p.input, REMOTE)).toBe(true);
        expect(view(p)).toBe(expected);
        expect(p.box.querySelector('input[value="failure"]').checked).toBe(true);
        expect(p.box.querySelector('.episode-cause').value).toBe('collision');
        expect(p.box.querySelector('.episode-relabel').value).toBe('theirs');
        expectNoSave(p.input, seen);
    });

    test('a cleared answer clears everything', async () => {
        const expected = view(await page(null));
        const p = await page(LOCAL);
        const seen = watchSaves(p.input);
        expect(applyTeammate('episode_annotation', 'ep', p.input, null)).toBe(true);
        expect(view(p)).toBe(expected);
        expect(p.manager.getAnnotationCount()).toBe(0);
        expectNoSave(p.input, seen);
    });

    test('applying twice changes nothing more, and an edit after it saves once', async () => {
        const expected = view(await page(REMOTE));
        const p = await page(LOCAL);
        applyTeammate('episode_annotation', 'ep', p.input, REMOTE);
        applyTeammate('episode_annotation', 'ep', p.input, REMOTE);
        expect(view(p)).toBe(expected);
        const seen = watchSaves(p.input);
        const partial = p.box.querySelector('input[value="partial"]');
        partial.checked = true;
        partial.dispatchEvent(new Event('change', { bubbles: true }));
        expect(seen.changes).toBe(1);
        expect(JSON.parse(p.input.value).outcome.result).toBe('partial');
    });

    test('two pages drawing their first phase mint different ids', async () => {
        async function drawPhase() {
            load('episode');   // a fresh page load
            const p = await page(null);
            p.manager.setPhase('reach');
            const canvas = p.box.querySelector('canvas');
            canvas.dispatchEvent(new MouseEvent('mousedown', { clientX: 60, clientY: 20, bubbles: true }));
            canvas.dispatchEvent(new MouseEvent('mouseup', { clientX: 300, clientY: 20, bubbles: true }));
            return JSON.parse(p.input.value).phases;
        }
        const first = await drawPhase();
        const second = await drawPhase();
        expect(first).toHaveLength(1);
        expect(first[0].id).toMatch(/^phase_[a-z0-9]+_1$/);
        expect(second[0].id).toMatch(/^phase_[a-z0-9]+_1$/);
        expect(first[0].id).not.toBe(second[0].id);
    });

    test('splitting a phase gives the right-hand piece its own id', async () => {
        const p = await page({ phases: [{ id: 'keep', start: 0, end: 10, label: 'reach' }] });
        p.manager.setPhase('grasp');
        const canvas = p.box.querySelector('canvas');
        canvas.dispatchEvent(new MouseEvent('mousedown', { clientX: 240, clientY: 20, bubbles: true }));
        canvas.dispatchEvent(new MouseEvent('mouseup', { clientX: 360, clientY: 20, bubbles: true }));
        const phases = JSON.parse(p.input.value).phases;
        expect(phases.map((s) => s.label)).toEqual(['reach', 'grasp', 'reach']);
        expect(phases[0].id).toBe('keep');
        expect(new Set(phases.map((s) => s.id)).size).toBe(3);
    });
});

// ---------------------------------------------------------------------------
// rollout_evaluation

describe('rollout_evaluation', () => {
    const SET = { fps: 10, streams: [{ stream_id: 'a', name: 'Alpha', url: 'a.mp4' },
                                      { stream_id: 'b', name: 'Beta', url: 'b.mp4' }] };
    const LOCAL = {
        violations: [{ id: 'm1', stream: 'a', t: 1.2, type: 'gravity_violation', severity: 2, note: '' }],
        clean: [], preference: { winner: 'a', confidence: '1', rubric: { safety: 2 } },
        counterfactual: { verdict: '', t: null, note: '' },
    };
    const REMOTE = {
        violations: [{ id: 'n1', stream: 'b', t: 3.4, type: 'interpenetration', severity: 3, note: 'x' }],
        clean: ['a'], preference: { winner: 'b', confidence: '3', rubric: { safety: 5 } },
        counterfactual: { verdict: 'plausible', t: 2, note: 'theirs' },
    };

    async function page(answer) {
        routes = { '/api/rollout/set': SET };
        const input = mount(markup.rollout, '#input-ro', answer);
        await settle();
        const box = document.querySelector('.rollout-eval-container');
        return { input, box, manager: box.annotationManager };
    }

    function view({ box }) {
        return JSON.stringify({
            controls: controls(box),
            timeline: box.querySelector('canvas').getAttribute('aria-label'),
            where: box.querySelector('.rollout-violation-where').textContent,
        });
    }

    test('the answers are visibly different', async () => {
        const a = view(await page(LOCAL));
        const b = view(await page(REMOTE));
        expect(a).not.toBe(b);
        expect(JSON.parse(b).timeline).toContain('Beta: 1 break');
    });

    test("a teammate's answer replaces the one on screen, and saves nothing", async () => {
        const expected = view(await page(REMOTE));
        const p = await page(LOCAL);
        const seen = watchSaves(p.input);
        expect(applyTeammate('rollout_evaluation', 'ro', p.input, REMOTE)).toBe(true);
        expect(view(p)).toBe(expected);
        expect(p.box.querySelector('input[name="rollout-winner-ro"][value="b"]').checked).toBe(true);
        expectNoSave(p.input, seen);
    });

    test('a cleared answer clears everything', async () => {
        const expected = view(await page(null));
        const p = await page(LOCAL);
        expect(applyTeammate('rollout_evaluation', 'ro', p.input, null)).toBe(true);
        expect(view(p)).toBe(expected);
        expect(p.manager.getAnnotationCount()).toBe(0);
    });

    test('the selected mark stays selected when the answer still has it', async () => {
        const p = await page(LOCAL);
        p.manager.selectViolation(0);
        const edited = JSON.parse(JSON.stringify(LOCAL));
        edited.violations[0].note = 'their note';
        edited.violations.unshift({ id: 'n0', stream: 'b', t: 0.5, type: 'gravity_violation', severity: 1, note: '' });
        applyTeammate('rollout_evaluation', 'ro', p.input, edited);
        expect(p.manager.violations[p.manager.selectedViolation].id).toBe('m1');
        expect(p.box.querySelector('.rollout-violation-note').value).toBe('their note');
    });

    test('applying twice changes nothing more', async () => {
        const expected = view(await page(REMOTE));
        const p = await page(LOCAL);
        applyTeammate('rollout_evaluation', 'ro', p.input, REMOTE);
        applyTeammate('rollout_evaluation', 'ro', p.input, REMOTE);
        expect(view(p)).toBe(expected);
    });

    test('two pages marking their first break mint different ids', async () => {
        async function mark() {
            load('rollout');   // a fresh page load
            const p = await page(null);
            document.dispatchEvent(new KeyboardEvent('keydown', { key: '1', bubbles: true }));
            p.box.querySelector('.rollout-mark').click();
            p.manager.destroy();
            return JSON.parse(p.input.value).violations;
        }
        const first = await mark();
        const second = await mark();
        expect(first).toHaveLength(1);
        expect(first[0].id).toMatch(/^mark_[a-z0-9]+_1$/);
        expect(first[0].id).not.toBe(second[0].id);
    });
});

// ---------------------------------------------------------------------------
// grounding_eval and region_caption share an image canvas

function imageCanvas(shapes) {
    const manager = {
        shapes: shapes || [], listeners: [], _hydrating: false, canvasEvents: 0,
        setTool() {},
        addAnnotationChangeListener(fn) { this.listeners.push(fn); },
        _serializeAnnotations() { return JSON.stringify(this.shapes); },
        clearAnnotations() { this.shapes = []; this._updateAnnotationData(); },
        _deserializeAnnotations(json) { this.shapes = JSON.parse(json); },
        // Like the real manager: the change event is held while hydrating;
        // listeners always run.
        _updateAnnotationData() {
            if (!this._hydrating) this.canvasEvents += 1;
            this.listeners.forEach((fn) => fn());
        },
    };
    return manager;
}

const BOX = (x) => ({ type: 'bbox', label: 'referent', coordinates: { x, y: 0.1, width: 0.2, height: 0.2 } });

describe('grounding_eval', () => {
    const LOCAL = { regions: { e1: [BOX(0.1)] }, absent: [], verdicts: { e1: 'wrong_object' } };
    // The teammate never answered e1: this page's e1 must not survive.
    const REMOTE = { regions: { e2: [BOX(0.5)] }, absent: [], verdicts: { e2: 'correct' } };

    async function page(answer) {
        routes = { '/api/grounding/expressions': {
            expressions: [{ id: 'e1', text: 'the cat' }, { id: 'e2', text: 'the dog' }], predictions: {} } };
        const image = imageCanvas();
        const input = mount(markup.grounding, '#input-g', answer,
            '<div class="image-annotation-container" data-schema="img"></div>'
            + '<input class="annotation-data-input" name="img">');
        // The image schema attaches its manager as it boots; the grounding
        // widget polls for it.
        document.querySelector('.image-annotation-container').annotationManager = image;
        const box = document.querySelector('.grounding-eval-container');
        box.groundingManager._findImageManager();
        await settle();
        return { input, box, image, manager: box.groundingManager };
    }

    function view({ box, image }) {
        return JSON.stringify({
            items: Array.from(box.querySelectorAll('.grounding-item'))
                .map((li) => [li.className, li.textContent]),
            progress: box.querySelector('.grounding-progress').textContent,
            verdict: box.querySelector('.grounding-verdict-select').value,
            canvas: image.shapes,
        });
    }

    test('the answers are visibly different', async () => {
        const a = view(await page(LOCAL));
        const b = view(await page(REMOTE));
        const none = view(await page(null));
        expect(a).not.toBe(b);
        expect(b).not.toBe(none);
        // A stored verdict is shown for the active expression (it used to
        // come back as "not judged").
        expect(JSON.parse(a).verdict).toBe('wrong_object');
    });

    test("a teammate's answer replaces, not merges, and saves nothing", async () => {
        const expected = view(await page(REMOTE));
        const p = await page(LOCAL);
        const seen = watchSaves(p.input);
        const before = p.image.canvasEvents;
        expect(applyTeammate('grounding_eval', 'g', p.input, REMOTE)).toBe(true);
        expect(view(p)).toBe(expected);
        // e1 was located here and is unanswered there: the region is gone.
        expect(p.box.querySelector('.grounding-item.state-unanswered').textContent).toContain('the cat');
        expect(p.image.shapes).toEqual([]);
        // ...and so is the verdict this page had on it.
        expect(p.box.querySelector('.grounding-verdict-select').value).toBe('');
        expectNoSave(p.input, seen);
        expect(p.image.canvasEvents).toBe(before);
    });

    test('a cleared answer clears everything', async () => {
        const expected = view(await page(null));
        const p = await page(LOCAL);
        expect(applyTeammate('grounding_eval', 'g', p.input, null)).toBe(true);
        expect(view(p)).toBe(expected);
        expect(p.manager.unanswered()).toEqual(['e1', 'e2']);
    });

    test("the image canvas restoring shapes is not taken as this page's drawing", async () => {
        const p = await page(LOCAL);
        const seen = watchSaves(p.input);
        // The image scheme's own live update puts a teammate's canvas back.
        p.image._hydrating = true;
        p.image.shapes = [BOX(0.9)];
        p.image._updateAnnotationData();
        p.image._hydrating = false;
        expect(p.manager.answers.e1.regions).toEqual([BOX(0.1)]);
        expectNoSave(p.input, seen);
    });

    test('applying twice changes nothing more', async () => {
        const expected = view(await page(REMOTE));
        const p = await page(LOCAL);
        applyTeammate('grounding_eval', 'g', p.input, REMOTE);
        applyTeammate('grounding_eval', 'g', p.input, REMOTE);
        expect(view(p)).toBe(expected);
    });

    // A session member has no current instance of their own (the item is the
    // team's), so the phrases came back 404 and the list stayed empty. The
    // page names the item it shows.
    test('the expressions request names the item on the page', async () => {
        mount(markup.grounding, '#input-g', null,
            '<input type="hidden" id="instance_id" value="item 7&8">');
        await settle();
        const asked = fetchCalls.filter((u) => u.startsWith('/api/grounding/expressions'));
        expect(asked).toEqual(['/api/grounding/expressions?schema=g&instance_id=item%207%268']);
    });
});

describe('region_caption', () => {
    const R1 = BOX(0.1);
    const R2 = BOX(0.6);
    const LOCAL = { captions: [{ region: R1, caption: 'mine' }, { region: R2, caption: '' }] };
    const REMOTE = { captions: [{ region: R1, caption: '' }, { region: R2, caption: 'theirs' }] };

    function page(answer) {
        const image = imageCanvas([R1, R2]);
        const input = mount(markup.caption, '#input-rc', answer,
            '<div class="image-annotation-container" data-schema="img"></div>');
        document.querySelector('.image-annotation-container').annotationManager = image;
        const box = document.querySelector('.region-caption-container');
        box.regionCaptionManager._findImageManager();
        input.removeAttribute('data-modified');
        return { input, box, image, manager: box.regionCaptionManager };
    }

    function view({ box }) {
        return JSON.stringify({
            rows: Array.from(box.querySelectorAll('.region-caption-item')).map((li) => [
                li.className, li.querySelector('label').textContent,
                li.querySelector('textarea').value]),
            progress: box.querySelector('.region-caption-progress').textContent,
        });
    }

    test('the answers are visibly different', () => {
        expect(view(page(LOCAL))).not.toBe(view(page(REMOTE)));
        expect(view(page(REMOTE))).not.toBe(view(page(null)));
    });

    test("a teammate's answer replaces the captions, and saves nothing", () => {
        const expected = view(page(REMOTE));
        const p = page(LOCAL);
        const seen = watchSaves(p.input);
        expect(applyTeammate('region_caption', 'rc', p.input, REMOTE)).toBe(true);
        expect(view(p)).toBe(expected);
        expectNoSave(p.input, seen);
    });

    test('a cleared answer clears every caption', () => {
        const expected = view(page(null));
        const p = page(LOCAL);
        applyTeammate('region_caption', 'rc', p.input, null);
        expect(view(p)).toBe(expected);
        expect(p.manager.getAnnotationCount()).toBe(0);
    });

    test("a caption for a region the canvas does not have yet waits for it", () => {
        const p = page(null);
        const R3 = BOX(0.8);
        applyTeammate('region_caption', 'rc', p.input,
            { captions: [{ region: R3, caption: 'new shape' }] });
        expect(p.manager.entries.map((e) => e.caption)).toEqual(['', '']);
        // The teammate's region arrives on the canvas as a restore.
        p.image._hydrating = true;
        p.image.shapes = [R1, R2, R3];
        p.image._updateAnnotationData();
        p.image._hydrating = false;
        expect(p.manager.entries.map((e) => e.caption)).toEqual(['', '', 'new shape']);
        expect(p.input.hasAttribute('data-modified')).toBe(false);
    });

    test('applying twice keeps one row per region, and typing saves once', () => {
        const p = page(LOCAL);
        applyTeammate('region_caption', 'rc', p.input, REMOTE);
        applyTeammate('region_caption', 'rc', p.input, REMOTE);
        expect(p.box.querySelectorAll('.region-caption-item')).toHaveLength(2);
        const seen = watchSaves(p.input);
        const field = p.box.querySelectorAll('textarea')[0];
        field.value = 'typed';
        field.dispatchEvent(new Event('input', { bubbles: true }));
        expect(seen.changes).toBe(1);
    });
});

// ---------------------------------------------------------------------------
// turn_level: a <form>, so collab.js finds it

describe('turn_level (through collab.js)', () => {
    let client;

    function page(answer, otherEdit) {
        const input = mount(markup.turns, 'input.turn-anno-hidden[name="stance"]', answer);
        window.turnAnnotations.refresh();   // what the module does on load
        if (otherEdit) otherEdit();
        return input;
    }

    function bootCollab() {
        window.potatoCollab = { sid: 'RED', me: 'ben', instance_id: 'c1', rev: 4, cursor: 10,
            team_user: 'team-red', transport: 'poll', poll_interval_ms: 100000, base: '' };
        delete window.potatoCollabClient;
        load('collab');
        client = window.potatoCollabClient;
        window.fetch.mockClear = () => {};
    }

    const selected = (schema) => Array.from(document.querySelectorAll(
        `.ta-chip.ta-selected[data-ta-schema="${schema || 'stance'}"]`))
        .map((c) => `${c.dataset.turnId}=${c.dataset.value}`);
    const answer = (turns) => ({ v: 1, schema_type: 'radio', turns });

    beforeEach(() => {
        jest.useFakeTimers();
        bootCollab();
    });
    afterEach(() => jest.useRealTimers());

    test("a teammate's answer is shown, and saves nothing", () => {
        const input = page(answer({ t0: { value: 'good' } }));
        expect(selected()).toEqual(['t0=good']);
        const seen = watchSaves(input);
        const shown = client.applyKeys(new Set(['L:stance:::_data']),
            { 'L:stance:::_data': JSON.stringify(answer({ t1: { value: 'bad' } })) });
        expect(shown.has('L:stance:::_data')).toBe(true);
        expect(selected()).toEqual(['t1=bad']);
        expect(document.querySelector('.ta-progress[data-ta-schema="stance"]').textContent).toBe('(1/2 turns)');
        jest.runOnlyPendingTimers();
        expectNoSave(input, seen);
    });

    test('a cleared answer clears the chips', () => {
        page(answer({ t0: { value: 'good' } }));
        client.applyKeys(new Set(['L:stance:::_data']), {});
        expect(selected()).toEqual([]);
    });

    test("a click after an apply records one edit on top of the teammate's answer", () => {
        const input = page(null);
        client.applyKeys(new Set(['L:stance:::_data']),
            { 'L:stance:::_data': JSON.stringify(answer({ t1: { value: 'bad' } })) });
        client.applyKeys(new Set(['L:stance:::_data']),
            { 'L:stance:::_data': JSON.stringify(answer({ t1: { value: 'bad' } })) });
        document.querySelector('.ta-chip[data-turn-id="t0"][data-value="good"]').click();
        expect(JSON.parse(input.value).turns).toEqual({
            t1: { value: 'bad' }, t0: expect.objectContaining({ value: 'good' }) });
    });
});

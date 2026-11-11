/**
 * Live sessions: a teammate's answer reaches the trace-review widgets.
 *
 * These sixteen schemes keep their answer in one hidden `annotation-input` and
 * draw everything from it in a `build()` inside their inline script, which ran
 * once on page load. collab.js writes a teammate's answer into the input and
 * asks `window.potatoCollabWidgets[type].apply(ctx)` to show it; with no
 * applier the page could only show a "reload" banner, and the widget went on
 * drawing (and saving) its old copy.
 *
 * Each test drives the real collab.js `applyKeys` over the real generated
 * markup and script. The check is the visible widget: after a teammate's answer
 * is applied, the form must look exactly like a page freshly loaded with that
 * answer.
 *
 * The widgets' scripts are generated inline by the Python schemas, so they are
 * rendered with python once and run here.
 */

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const REPO = path.join(__dirname, '..', '..');
const COLLAB = fs.readFileSync(path.join(REPO, 'potato', 'static', 'collab.js'), 'utf8');

/**
 * type -> {scheme extras, instance data, two answers, a control that saves}.
 * `click(form)` performs one edit; it must save exactly once.
 */
const CASES = {
    agent_interaction_graph: {
        instance: { steps: [{ agent: 'planner' }, { agent: 'coder' }, { agent: 'planner' }] },
        local: { critical_nodes: ['planner'] },
        remote: { critical_nodes: ['coder'], edges: { 'planner->coder': 'problematic' } },
        click: (f) => f.querySelector('.aig-node[data-node="planner"]').dispatchEvent(
            new MouseEvent('click', { bubbles: true })),
    },
    agent_scorecard: {
        instance: { steps: [{ agent: 'a' }, { agent: 'b' }] },
        local: { agents: { a: { contribution: 2 } } },
        remote: { agents: { b: { 'role fidelity': 4 } }, team: { efficiency: 5 } },
        click: (f) => f.querySelector('.asc-sbtn[data-group="team"][data-v="1"]').click(),
    },
    consensus_tracking: {
        instance: { conversation: [{ speaker: 'x', text: 'let us do A' },
                                   { speaker: 'y', text: 'agreed' }] },
        local: [{ turn: 0, act: 'proposal', agent_id: 'x' }],
        remote: [{ turn: 1, act: 'agreement', agent_id: 'y', ref: 0 }],
        click: (f) => f.querySelector('.ct-act[data-turn="0"][data-act="decision"]').click(),
    },
    emergent_behavior: {
        instance: { steps: [{ agent: 'a', content: 'one' }, { agent: 'b', content: 'two' }] },
        local: { collusion: { turns: [0], note: 'mine' } },
        remote: { groupthink: { turns: [0, 1], note: 'theirs' } },
        click: (f) => f.querySelector('.eb-cb[data-b="role_drift"][data-t="1"]').click(),
    },
    failure_attribution: {
        instance: { steps: [{ agent: 'a', content: 'x' }, { agent: 'b', content: 'y' }] },
        local: { responsible_agent: 'a', decisive_step: 0, reason: 'mine' },
        remote: { responsible_agent: 'b', decisive_step: 1, reason: 'theirs' },
        click: (f) => {
            const sel = f.querySelector('.fa-agent');
            sel.value = 'a';
            sel.dispatchEvent(new Event('change', { bubbles: true }));
        },
    },
    gui_trajectory: {
        instance: { steps: [{ screenshot: 'a.png', action: 'click ok', x: 0.1, y: 0.2 },
                            { screenshot: 'b.png', action: 'type' }] },
        local: [{ index: 0, step: 0, verdict: 'correct', notes: '' }],
        remote: [{ index: 1, step: 1, verdict: 'hallucinated', notes: 'theirs' }],
        click: (f) => f.querySelector('.gt-vbtn[data-idx="0"][data-v="wrong_action"]').click(),
    },
    handoff_review: {
        instance: { steps: [{ agent: 'a' }, { agent: 'b' }, { agent: 'a' }] },
        local: [{ index: 0, step: 1, from: 'a', to: 'b', flags: ['garbling'], quality: 2 }],
        remote: [{ index: 1, step: 2, from: 'b', to: 'a', flags: ['info_loss'], quality: 5 }],
        click: (f) => f.querySelector('.hr-flag[data-idx="0"][data-f="goal_drift"]').click(),
    },
    multimodal_reasoning: {
        instance: { steps: [{ type: 'text', text: 'think' }, { type: 'action', action: 'go' }] },
        local: [{ index: 0, step: 0, type: 'text', verdict: 'coherent', notes: '' }],
        remote: [{ index: 1, step: 1, type: 'action', verdict: 'incoherent', notes: 'theirs' }],
        click: (f) => f.querySelector('.mmr-vbtn[data-idx="0"][data-v="uncertain"]').click(),
    },
    speech_transcript: {
        instance: { audio: 'call.mp3',
                    segments: [{ start: 0, end: 1, speaker: 'u', text: 'hello' },
                               { start: 1, end: 2, speaker: 'a', text: 'hi' }] },
        local: [{ index: 0, start: 0, end: 1, errors: ['asr_error'], correction: '' }],
        remote: [{ index: 1, start: 1, end: 2, errors: ['disfluency'], correction: 'hi there' }],
        click: (f) => f.querySelector('.st-ebtn[data-idx="0"][data-e="tts_artifact"]').click(),
        media: 'audio',
    },
    table_grid: {
        instance: { image: 't.png' },
        local: { rows: 2, cols: 2, cells: { '0,0': 'col_header' } },
        remote: { rows: 3, cols: 4, cells: { '1,2': 'row_header', '2,3': 'empty' } },
        click: (f) => f.querySelector('.tbg-cell[data-r="0"][data-c="1"]').click(),
    },
    temporal_grounding: {
        instance: { video: 'clip.mp4', events: [{ prompt: 'door opens' }, { prompt: 'dog barks' }] },
        local: { events: { 0: { start: 1, end: 2 } } },
        remote: { events: { 1: { start: 3.5, end: 4 } } },
        click: (f) => {
            const inp = f.querySelector('.tg-start[data-idx="0"]');
            inp.value = '0.5';
            inp.dispatchEvent(new Event('input', { bubbles: true }));
        },
        media: 'video',
    },
    tool_call_review: {
        instance: { steps: [{ tool_call: { name: 'search', args: { q: 'x' } } },
                            { tool_call: { name: 'open', args: { url: 'y' } } }] },
        local: [{ index: 0, step: 0, tool: 'search', verdict: 'correct', notes: '' }],
        remote: [{ index: 1, step: 1, tool: 'open', verdict: 'wrong_args', notes: 'theirs' }],
        click: (f) => f.querySelector('.tcr-vbtn[data-idx="0"][data-v="wrong_tool"]').click(),
    },
    tool_contention: {
        instance: { calls: [{ agent: 'a', tool: 'write', resource: 'db', start: 0, end: 2 },
                            { agent: 'b', tool: 'write', resource: 'db', start: 1, end: 3 },
                            { agent: 'a', tool: 'read', resource: 'fs', start: 4, end: 6 },
                            { agent: 'b', tool: 'read', resource: 'fs', start: 5, end: 7 }] },
        local: { contentions: { 0: 'benign' } },
        remote: { contentions: { 1: 'deadlock' } },
        click: (f) => f.querySelector('.tc-lbtn[data-idx="0"][data-l="race_condition"]').click(),
    },
    voice_interaction: {
        instance: { audio: 'v.mp3',
                    turns: [{ speaker: 'user', start: 0, end: 2, text: 'so' },
                            { speaker: 'agent', start: 1, end: 3, text: 'yes' },
                            { speaker: 'user', start: 4, end: 6, text: 'and' },
                            { speaker: 'agent', start: 5, end: 7, text: 'ok' }] },
        local: { overlaps: { 0: 'backchannel' }, rating: 2 },
        remote: { overlaps: { 1: 'agent_should_resume' }, rating: 4 },
        click: (f) => f.querySelector('.vi-rbtn[data-v="1"]').click(),
        media: 'audio',
    },
    process_reward: {
        scheme: { mode: 'per_step' },
        instance: { steps: [{ action: 'one' }, { action: 'two' }, { action: 'three' }] },
        local: { mode: 'per_step', steps: [{ index: 0, reward: 1 }, { index: 1, reward: -1 }] },
        remote: { mode: 'per_step', steps: [{ index: 0, reward: -1 }, { index: 1 },
                                            { index: 2, reward: 1 }] },
        // Reset is bound on every rebuild; it used to stack a handler each time.
        click: (f) => f.querySelector('.prm-reset-btn').click(),
    },
    code_review: {
        instance: {},
        local: { verdict: 'approve', comments: [{ id: 'c_a_1', category: 'bug', file: 'a.py', line: 3, text: 'mine' }],
                 file_ratings: {} },
        remote: { verdict: 'request_changes',
                  comments: [{ id: 'c_b_1', category: 'style', file: 'b.py', line: 9, text: 'theirs' },
                             { id: 'c_b_2', category: 'question', file: '', line: null, text: 'why?' }],
                  file_ratings: {} },
        click: (f) => f.querySelector('.cr-add-comment-btn').click(),
    },
};

const TYPES = Object.keys(CASES);

let rendered;
beforeAll(() => {
    const code = `
import json, sys, importlib, logging
logging.disable(logging.CRITICAL)
cases = json.loads(sys.argv[1])
out = {}
for t, extra in cases.items():
    m = importlib.import_module('potato.server_utils.schemas.' + t)
    scheme = dict(annotation_type=t, name='s_' + t, description='d', **extra)
    out[t] = getattr(m, 'generate_%s_layout' % t)(scheme)[0]
sys.stdout.write(json.dumps(out))
`;
    const schemes = {};
    TYPES.forEach((t) => { schemes[t] = CASES[t].scheme || {}; });
    rendered = JSON.parse(execFileSync('python', ['-c', code, JSON.stringify(schemes)],
        { cwd: REPO, encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'] }));
});

let fetchCalls;
let client;

function attr(text) {
    return String(text).replace(/&/g, '&amp;').replace(/'/g, '&#39;');
}

/** The page as the server renders it: instance data, the scheme, its stored answer. */
function mount(type, answer) {
    const html = rendered[type];
    const scripts = [];
    const body = html.replace(/<script>([\s\S]*?)<\/script>/g, (m, s) => { scripts.push(s); return ''; });
    document.body.innerHTML = `<div id="instance-json-data" data-instance-json='${
        attr(JSON.stringify(CASES[type].instance))}'></div>${body}`;
    const input = hiddenInput(type);
    if (answer !== null && answer !== undefined) {
        const json = JSON.stringify(answer);
        input.value = json;
        input.setAttribute('value', json);
        input.setAttribute('data-server-set', 'true');
    }
    // eslint-disable-next-line no-new-func
    scripts.forEach((s) => new Function(s)());
    return document.getElementById('s_' + type);
}

function hiddenInput(type) {
    return document.querySelector(`input.annotation-input[schema="s_${type}"]`);
}

/** Everything the annotator can see in the form, as one comparable value. */
function view(form) {
    const clone = form.cloneNode(true);
    clone.querySelectorAll('input[type="hidden"]').forEach((el) => el.remove());
    const controls = Array.from(form.querySelectorAll('input, select, textarea'))
        .filter((el) => el.type !== 'hidden')
        .map((el) => [el.tagName, el.className, el.value, !!el.checked]);
    return JSON.stringify({
        html: clone.innerHTML,
        controls,
        incomplete: form.getAttribute('data-incomplete-reason'),
    });
}

function bootCollab() {
    fetchCalls = [];
    window.fetch = jest.fn((input, init) => {
        fetchCalls.push({ input: String(input), init });
        return Promise.resolve({
            ok: true, status: 200,
            json: () => Promise.resolve({ events: [], cursor: 0, answer: {} }),
            clone() { return this; },
        });
    });
    window.potatoCollab = {
        sid: 'RED', me: 'ben', instance_id: 'c1', rev: 4, cursor: 10,
        team_user: 'team-red', transport: 'poll', poll_interval_ms: 100000, base: '',
    };
    delete window.potatoCollabClient;
    // eslint-disable-next-line no-new-func
    new Function(COLLAB)();
    client = window.potatoCollabClient;
    // collab.js wrapped fetch; the shared setup clears a mock between tests.
    window.fetch.mockClear = () => {};
}

/** A teammate's answer for this scheme, through collab.js. */
function applyTeammate(type, answer) {
    const key = `L:s_${type}:::s_${type}`;
    const payload = answer === null ? {} : { [key]: JSON.stringify(answer) };
    return client.applyKeys(new Set([key]), payload);
}

beforeEach(() => {
    jest.useFakeTimers();
    bootCollab();
    window.saveAnnotations = jest.fn();
});

afterEach(() => {
    jest.useRealTimers();
    window.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
});

describe.each(TYPES)('%s', (type) => {
    const spec = CASES[type];

    test('the two answers look different, and different from no answer', () => {
        const a = view(mount(type, spec.local));
        const b = view(mount(type, spec.remote));
        const none = view(mount(type, null));
        expect(a).not.toBe(b);
        expect(b).not.toBe(none);
        expect(a).not.toBe(none);
    });

    test("a teammate's answer replaces the one on screen", () => {
        const expected = view(mount(type, spec.remote));
        const form = mount(type, spec.local);
        const shown = applyTeammate(type, spec.remote);
        expect(shown.has(`L:s_${type}:::s_${type}`)).toBe(true);
        expect(view(form)).toBe(expected);
    });

    test('a cleared answer clears the widget', () => {
        const expected = view(mount(type, null));
        const form = mount(type, spec.local);
        expect(applyTeammate(type, null).size).toBe(1);
        expect(view(form)).toBe(expected);
    });

    test('applying saves nothing', () => {
        const form = mount(type, spec.local);
        const input = hiddenInput(type);
        let changes = 0;
        input.addEventListener('change', () => { changes += 1; });
        applyTeammate(type, spec.remote);
        applyTeammate(type, null);
        jest.runOnlyPendingTimers();
        expect(changes).toBe(0);
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(fetchCalls.filter((c) => c.input.includes('/updateinstance'))).toHaveLength(0);
        expect(form).toBeTruthy();
    });

    test('applying twice draws once and binds once', () => {
        const expected = view(mount(type, spec.remote));
        const form = mount(type, spec.local);
        applyTeammate(type, spec.remote);
        applyTeammate(type, spec.remote);
        expect(view(form)).toBe(expected);

        // One edit after two applies is one save, not three.
        const input = hiddenInput(type);
        let changes = 0;
        input.addEventListener('change', () => { changes += 1; });
        spec.click(form);
        expect(changes).toBe(1);
        expect(input.getAttribute('data-modified')).toBe('true');
    });

    if (spec.media) {
        test('the player survives an apply (playback and playhead are kept)', () => {
            const form = mount(type, spec.local);
            const player = form.querySelector(spec.media);
            expect(player).not.toBeNull();
            applyTeammate(type, spec.remote);
            expect(form.querySelector(spec.media)).toBe(player);
        });
    }
});

describe('two schemes of one type on a page', () => {
    test('applying to one leaves the other alone', () => {
        // The widgets used to look cards up page-wide, so painting one scheme
        // could repaint the other's identically indexed cards.
        const html = rendered.tool_call_review;
        const second = html.replace(/s_tool_call_review/g, 's_other');
        const scripts = [];
        const strip = (h) => h.replace(/<script>([\s\S]*?)<\/script>/g, (m, s) => { scripts.push(s); return ''; });
        document.body.innerHTML = `<div data-instance-json='${attr(JSON.stringify(CASES.tool_call_review.instance))}'></div>`
            + strip(second) + strip(html);   // the other scheme first in the page
        const other = document.querySelector('input.annotation-input[schema="s_other"]');
        const otherAnswer = JSON.stringify([{ index: 1, step: 1, tool: 'open', verdict: 'correct', notes: '' }]);
        other.value = otherAnswer;
        other.setAttribute('value', otherAnswer);
        // eslint-disable-next-line no-new-func
        scripts.forEach((s) => new Function(s)());
        const otherForm = document.getElementById('s_other');
        const before = view(otherForm);
        applyTeammate('tool_call_review', CASES.tool_call_review.remote);
        expect(view(otherForm)).toBe(before);
        expect(document.querySelector('#s_tool_call_review .tcr-vbtn.selected').getAttribute('data-v'))
            .toBe('wrong_args');
    });
});

describe('code_review comment ids', () => {
    function addComment(text) {
        const form = mount('code_review', null);
        form.querySelector('.cr-add-comment-btn').click();
        const box = form.querySelector('.cr-comment-card .cr-comment-text');
        box.value = text;
        box.dispatchEvent(new Event('input', { bubbles: true }));
        return JSON.parse(hiddenInput('code_review').value).comments[0];
    }

    test('two pages adding their first comment mint different ids', () => {
        // The server merges comment lists by id; a shared first id would let
        // one annotator's comment overwrite the other's.
        const first = addComment('from page one');
        const second = addComment('from page two');
        expect(first.id).toMatch(/^c_[a-z0-9]+_1$/);
        expect(second.id).toMatch(/^c_[a-z0-9]+_1$/);
        expect(first.id).not.toBe(second.id);
    });

    test('a stored comment keeps its id', () => {
        const form = mount('code_review', CASES.code_review.local);
        const box = form.querySelector('.cr-comment-card .cr-comment-text');
        box.value = 'edited';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        expect(JSON.parse(hiddenInput('code_review').value).comments[0].id).toBe('c_a_1');
    });
});

describe('keyboard focus', () => {
    test('the control being used keeps focus and caret across a redraw', () => {
        const form = mount('tool_call_review', CASES.tool_call_review.local);
        let notes = form.querySelector('.tcr-notes[data-idx="1"]');
        notes.focus();
        notes.value = 'abcdef';
        notes.setSelectionRange(2, 4);
        applyTeammate('tool_call_review', CASES.tool_call_review.remote);
        notes = form.querySelector('.tcr-notes[data-idx="1"]');
        expect(document.activeElement).toBe(notes);
        expect(notes.value).toBe('theirs');
        expect([notes.selectionStart, notes.selectionEnd]).toEqual([2, 4]);
    });
});

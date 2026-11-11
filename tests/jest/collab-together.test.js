/**
 * The live-session client's working-together features (collab.js, Phase 5):
 * the stage line for blind answers and sign-off, quick polls, @mentions,
 * catch-up after time away, the offline save queue, a refused save under
 * conflict_policy: reject, read-only observers, and what counts as "no
 * change" after a teammate's drawing is put on screen.
 *
 * Booted over the real rail template, so the elements are the ones the
 * server renders.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..', 'potato');
const SOURCE = path.join(ROOT, 'static', 'collab.js');
const RAIL = fs.readFileSync(path.join(ROOT, 'templates', '_collab_rail.html'), 'utf8')
    .replace(/\{#-[\s\S]*?-#\}/g, '')
    .replace('{{ collab_context.name }}', 'Team Red');

let fetchCalls;
let respond;
let client;

function jsonResponse(body, status) {
    return {
        ok: (status || 200) < 400, status: status || 200,
        json: () => Promise.resolve(body), clone() { return this; },
    };
}

function boot(extra) {
    document.body.innerHTML = `<div id="main-content"><div id="annotation-forms">
        <form data-schema-name="stance" data-annotation-type="radio">
        <input class="stance shadcn-radio-input annotation-input" type="radio" name="stance"
               value="pro" schema="stance" label_name="pro"></form></div></div>${RAIL}`;
    fetchCalls = [];
    respond = () => jsonResponse({ events: [], cursor: 10, answer: {} });
    window.fetch = jest.fn((input, init) => {
        fetchCalls.push({ input, init });
        return Promise.resolve().then(() => respond(input, init));
    });
    try { localStorage.clear(); sessionStorage.clear(); } catch (e) { /* none */ }
    window.potatoCollab = Object.assign({
        sid: 'RED', me: 'ben', instance_id: 'c1', rev: 4, cursor: 10,
        team_user: 'team-red', transport: 'poll', poll_interval_ms: 100000, base: '',
        role: 'member', sync_view: true, single_select: [{ name: 'stance', options: ['pro', 'con'] }],
    }, extra || {});
    delete window.potatoSaveHooks;
    delete window.potatoNavigation;
    delete window.potatoCollabClient;
    delete window.potatoCollabAppliers;
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(SOURCE, 'utf8'))();
    client = window.potatoCollabClient;
    window.fetch.mockClear = () => {};
}

function sessionState(over) {
    return Object.assign({
        session_id: 'RED', name: 'Team Red', mode: 'follow', leader: 'ana', status: 'open',
        item_ids: ['c1', 'c2'], cursor: 10, leader_view: 'c1',
        members: [{ username: 'ana', role: 'leader', active: true, viewing: 'c1', following: true },
                  { username: 'ben', role: 'member', active: true, viewing: 'c1', following: true }],
        me: { username: 'ben', role: 'member', active: true, viewing: 'c1', following: true },
        items: { c1: { rev: 4, ready: [], signed_off: false, blind: false, blind_done: [] } },
        polls: [], require_signoff: false, blind_first: false,
    }, over || {});
}

const flush = () => new Promise((r) => jest.requireActual('timers').setImmediate(r));

beforeEach(() => { jest.useFakeTimers(); boot(); });
afterEach(() => {
    jest.useRealTimers();
    window.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
});

describe('the stage line', () => {
    test('blind: how many are done, and a way to hand in', () => {
        client.consume({ events: [], state: sessionState({
            blind_first: true, items: { c1: { rev: 0, ready: [], blind: true, blind_done: ['ana'] } } }) });
        expect(document.getElementById('collab-bar-stage').textContent)
            .toBe('Answer on your own first · 1 of 2 done');
        expect(document.getElementById('collab-blind-done').hidden).toBe(false);
        // Only the leader can reveal early.
        expect(document.getElementById('collab-reveal').hidden).toBe(true);
    });

    test('blind and handed in: the form is locked', () => {
        client.consume({ events: [], state: sessionState({
            items: { c1: { rev: 0, ready: [], blind: true, blind_done: ['ben'] } } }) });
        expect(document.getElementById('annotation-forms').hasAttribute('inert')).toBe(true);
        expect(document.getElementById('collab-blind-done').hidden).toBe(true);
    });

    test('sign-off: the count and my own mark', () => {
        client.consume({ events: [], state: sessionState({
            require_signoff: true, items: { c1: { rev: 4, ready: ['ben'], signed_off: false, blind: false } } }) });
        expect(document.getElementById('collab-bar-stage').textContent).toBe('1 of 2 ready');
        const button = document.getElementById('collab-signoff');
        expect(button.hidden).toBe(false);
        expect(button.getAttribute('aria-pressed')).toBe('true');
    });
});

describe('answering on your own first', () => {
    test('once the item opens, the page that showed my own answer saves nothing', async () => {
        boot({ blind: true, blind_first: true });
        client.consume({ events: [{ seq: 11, ts: 1, type: 'revealed', user: null,
                                    data: { instance_id: 'c1' } }],
                         state: sessionState({ items: { c1: { rev: 1, blind: false, blind_done: [] } } }) });
        const r = await window.fetch('/updateinstance', {
            method: 'POST', body: JSON.stringify({ instance_id: 'c1', annotations: { 'scene:::city': 'city' } }) });
        expect(r.ok).toBe(true);
        expect(fetchCalls.some((c) => String(c.input).startsWith('/updateinstance'))).toBe(false);
    });

    test("a blind page's saves say so, for the server to check", () => {
        boot({ blind: true, blind_first: true });
        expect(window.potatoSaveHooks.decorate({ instance_id: 'c1' }).collab.rendered_blind).toBe(true);
        boot();
        expect(window.potatoSaveHooks.decorate({ instance_id: 'c1' }).collab.rendered_blind).toBeUndefined();
    });

    test("while answers are blind, where a teammate is working is not shown", () => {
        const presence = [{ user: 'ana', instance_id: 'c1', focus: 'stance', ts: 1, seq: 1 }];
        client.consume({ events: [], presence: presence, state: sessionState({
            items: { c1: { rev: 0, blind: true, blind_done: [] } } }) });
        expect(document.querySelector('.collab-editing-badge')).toBeNull();
        client.consume({ events: [], presence: presence, state: sessionState() });
        expect(document.querySelector('.collab-editing-badge').textContent).toBe('ana is editing');
    });
});

describe('quick polls', () => {
    const open = {
        poll_id: 'p9', instance_id: 'c1', question: 'Stance?', options: ['pro', 'con'],
        schema: 'stance', opened_by: 'ana', opened_at: 1, open: true, voted: ['ana'], my_vote: null,
    };

    test('an open poll offers its options and hides the votes', () => {
        client.consume({ events: [], state: sessionState({ polls: [open] }) });
        const card = document.getElementById('collab-poll');
        expect(card.hidden).toBe(false);
        expect([...card.querySelectorAll('[data-vote]')].map((b) => b.dataset.vote)).toEqual(['pro', 'con']);
        expect(card.textContent).toContain('1 of 2 voted');
        // Ben did not open it and does not lead: no close button.
        expect(card.querySelector('[data-poll-close]')).toBeNull();
    });

    test('a vote goes to the poll', async () => {
        client.consume({ events: [], state: sessionState({ polls: [open] }) });
        document.querySelector('[data-vote="con"]').click();
        await flush();
        const call = fetchCalls.find((c) => String(c.input).endsWith('/poll/p9/vote'));
        expect(JSON.parse(call.init.body)).toEqual({ option: 'con' });
    });

    test('a closed poll shows who chose what and offers the winner', () => {
        const closed = Object.assign({}, open, {
            open: false, counts: { pro: 0, con: 2 }, winner: 'con', applied: false,
            votes: { ana: 'con', ben: 'con' } });
        client.consume({ events: [], state: sessionState({ polls: [closed] }) });
        const card = document.getElementById('collab-poll');
        expect(card.textContent).toContain('Result: con');
        expect(card.textContent).toContain('ana, ben');
        expect(card.querySelector('[data-apply="1"]').textContent).toBe('Use con');
    });
});

describe('mentions and time away', () => {
    test('mentions name members once, in any case, with a trailing full stop', () => {
        expect(client.mentionsIn('@Ben, see this. And @ben. Not @zed or me@ana', ['ana', 'ben']))
            .toEqual(['ben']);
    });

    test("a mention of me in chat says so", () => {
        client.consume({ events: [{ seq: 11, ts: 1, type: 'message', user: 'ana',
                                    data: { text: '@ben look', mentions: ['ben'] } }],
                         state: sessionState() });
        expect(document.getElementById('collab-toast').textContent).toContain('ana mentioned you');
        expect(document.querySelector('.collab-mentions-me .collab-mention').textContent).toBe('@ben');
    });

    test('the summary of what others did leaves out my own', () => {
        const events = [
            { type: 'edit', user: 'ana' }, { type: 'edit', user: 'ana' },
            { type: 'edit', user: 'chen' }, { type: 'edit', user: 'ben' },
            { type: 'message', user: 'chen' }, { type: 'viewing', user: 'ana' },
        ];
        expect(client.summarizeAway(events, 'ben')).toEqual({
            count: 4, text: '2 changes by ana, 1 by chen · 1 message' });
    });
});

describe('saves', () => {
    function widgetInput(arrived) {
        const form = document.createElement('form');
        form.setAttribute('data-schema-name', 'grid');
        form.innerHTML = `<input type="hidden" class="annotation-input" name="grid:::structure"
            schema="grid" label_name="structure" value="" data-arrived-value="${arrived}">`;
        document.getElementById('annotation-forms').appendChild(form);
        return form.querySelector('input');
    }
    function widgetWrites(input, value) {
        input.value = value;
        input.dispatchEvent(new Event('change', { bubbles: true }));     // not trusted
    }
    async function teammateEdits() {
        respond = (input) => (String(input).includes('/item/')
            ? jsonResponse({ rev: 5, answer: { 'L:stance:::pro': 'pro' } })
            : jsonResponse({ events: [], cursor: 11 }));
        window.potatoApplyRemoteLabels = jest.fn();
        client.handleEvents([{ type: 'edit', user: 'ana', seq: 11, ts: Date.now() / 1000,
                               data: { instance_id: 'c1', rev: 5, ops: [{ key: 'L:stance:::pro' }] } }]);
        for (let i = 0; i < 4; i += 1) { jest.advanceTimersByTime(400); await flush(); }
    }

    test("a widget's load-time default, later cleared, is not saved when a teammate edits", async () => {
        // table_grid writes its default size while it sets itself up, then
        // annotation.js empties the input: nothing was edited.
        const input = widgetInput('');
        widgetWrites(input, '{"rows":3,"cols":3}');
        input.value = '';
        window.saveAnnotations = jest.fn();
        jest.advanceTimersByTime(5000);
        await teammateEdits();
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(window.potatoApplyRemoteLabels).toHaveBeenCalled();
        delete window.saveAnnotations;
    });

    test('an empty answer in any shape is not an edit', async () => {
        const input = widgetInput('');
        widgetWrites(input, '{"captions":[]}');        // region_caption before its canvas loads
        window.saveAnnotations = jest.fn();
        jest.advanceTimersByTime(5000);
        await teammateEdits();
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        expect(window.potatoApplyRemoteLabels).toHaveBeenCalled();
        delete window.saveAnnotations;
    });

    test("a widget's real edit that no autosave took is saved before a teammate's change", async () => {
        const input = widgetInput('');
        widgetWrites(input, '{"rows":4,"cols":3}');
        window.saveAnnotations = jest.fn();
        jest.advanceTimersByTime(5000);
        await teammateEdits();
        expect(window.saveAnnotations).toHaveBeenCalledWith({ background: true });
        expect(window.potatoApplyRemoteLabels).not.toHaveBeenCalled();
        delete window.saveAnnotations;
    });

    test('a save the network drops is kept and sent again', async () => {
        respond = (input) => {
            if (String(input).startsWith('/updateinstance')) throw new TypeError('Failed to fetch');
            return jsonResponse({ events: [], cursor: 10 });
        };
        await expect(window.fetch('/updateinstance', {
            method: 'POST', body: JSON.stringify({ instance_id: 'c1', annotations: { 'stance:::pro': 'pro' } }),
        })).rejects.toThrow('Failed to fetch');
        expect(client.offlineQueue()).toHaveLength(1);
        expect(document.getElementById('collab-offline').hidden).toBe(false);

        respond = () => jsonResponse({ status: 'success' });
        await client.flushOffline();
        expect(client.offlineQueue()).toHaveLength(0);
        const resent = fetchCalls.filter((c) => String(c.input).startsWith('/updateinstance')).pop();
        const body = JSON.parse(resent.init.body);
        expect(body.collab.base_rev).toBe(4);      // still the revision it was made on
        expect(body.annotations).toEqual({ 'stance:::pro': 'pro' });
    });

    test('after a refused save the scheme is based on the revision now shown', async () => {
        respond = (input) => (String(input).includes('/item/')
            ? jsonResponse({ rev: 6, answer: { 'L:stance:::pro': 'pro' } })
            : jsonResponse({ events: [], cursor: 10 }));
        window.potatoApplyRemoteLabels = jest.fn();
        client.onSaveResult({ rejected: true, rev_before: 6, rev: 6,
                              conflicts: [{ key: 'L:stance', user: 'ana' }] });
        await flush(); await flush();
        expect(window.potatoApplyRemoteLabels).toHaveBeenCalledWith({ stance: { pro: 'pro' } });
        const next = window.potatoSaveHooks.decorate({ instance_id: 'c1' });
        expect(next.collab.base_rev).toBe(4);
        expect(next.collab.stale).toEqual({ 'L:stance': 6 });
        expect(document.getElementById('collab-toast').textContent).toContain('ana changed');
    });

    test('a partly refused save moves the base, shows theirs, and sends nothing again', async () => {
        respond = (input) => (String(input).includes('/item/')
            ? jsonResponse({ rev: 5, answer: { 'L:stance:::pro': 'pro', 'L:note:::text_box': 'hm' } })
            : jsonResponse({ events: [], cursor: 10 }));
        window.potatoApplyRemoteLabels = jest.fn();
        window.saveAnnotations = jest.fn();
        client.onSaveResult({ rejected: true, partial: true, rev_before: 4, rev: 5,
                              conflicts: [{ key: 'L:stance', user: 'ana' }] });
        await flush(); await flush();
        jest.advanceTimersByTime(1000);
        expect(window.potatoApplyRemoteLabels).toHaveBeenCalledWith({ stance: { pro: 'pro' } });
        expect(window.saveAnnotations).not.toHaveBeenCalled();
        const next = window.potatoSaveHooks.decorate({ instance_id: 'c1' });
        expect(next.collab.base_rev).toBe(5);
        expect(document.getElementById('collab-toast').textContent).toContain('Partly saved');
        expect(document.getElementById('collab-toast').textContent).toContain('other changes are saved');
        delete window.saveAnnotations;
    });

    test('a save refused because the server signed me out is kept, and the page says so', async () => {
        respond = (input) => (String(input).startsWith('/updateinstance')
            ? jsonResponse({ error: 'Not logged in' }, 401)
            : jsonResponse({ events: [], cursor: 10 }));
        const r = await window.fetch('/updateinstance', {
            method: 'POST', body: JSON.stringify({ instance_id: 'c1', annotations: { 'stance:::pro': 'pro' } }),
        });
        expect(r.status).toBe(401);
        expect(client.offlineQueue()).toHaveLength(1);
        const banner = document.getElementById('collab-offline');
        expect(banner.hidden).toBe(false);
        expect(banner.textContent).toContain('signed out');
        expect(banner.querySelector('[data-role="signin"]').hidden).toBe(false);
    });

    test('a queued change is not dropped when sending it finds me signed out', async () => {
        respond = (input) => {
            if (String(input).startsWith('/updateinstance')) throw new TypeError('Failed to fetch');
            return jsonResponse({ events: [], cursor: 10 });
        };
        await expect(window.fetch('/updateinstance', {
            method: 'POST', body: JSON.stringify({ instance_id: 'c1', annotations: { 'stance:::pro': 'pro' } }),
        })).rejects.toThrow('Failed to fetch');
        respond = () => jsonResponse({ error: 'Not logged in' }, 401);
        await client.flushOffline();
        expect(client.offlineQueue()).toHaveLength(1);
        expect(document.getElementById('collab-offline').textContent).toContain('signed out');

        // Signed in again: the next page's first poll sends it.
        respond = () => jsonResponse({ status: 'success' });
        await client.flushOffline();
        expect(client.offlineQueue()).toHaveLength(0);
    });

    test('an observer page saves nothing', async () => {
        boot({ role: 'observer' });
        const r = await window.fetch('/updateinstance', { method: 'POST', body: '{"instance_id":"c1"}' });
        expect((await r.json()).observer).toBe(true);
        expect(fetchCalls.some((c) => String(c.input).startsWith('/updateinstance'))).toBe(false);
        expect(document.getElementById('annotation-forms').hasAttribute('inert')).toBe(true);
    });

    test("a teammate's drawing on screen is the new 'unchanged'", () => {
        const input = document.createElement('input');
        input.className = 'annotation-data-input';
        input.name = 'objects';
        document.getElementById('annotation-forms').appendChild(input);
        // The widget re-serializes what it was given (here: adds an id).
        window.potatoCollabAppliers = { objects: (s, value, el) => { el.value = '[{"id":"x"}]'; return true; } };
        const shown = client.applyKeys(new Set(['L:objects:::_data']), { 'L:objects:::_data': '[{}]' });
        expect(shown.has('L:objects:::_data')).toBe(true);
        expect(input._arrivedWith).toBe('[{"id":"x"}]');
    });
});

/**
 * The live-session client on the annotation page (collab.js).
 *
 * - Requests about the item on the page carry the session (header for data
 *   reads, body field for saves); the annotator's own paradata does not.
 * - base_rev, the revision the page reflects, moves past a teammate's edit
 *   only once it is on screen, and past this page's own save at once.
 * - A blob scheme no widget can update live is remembered as stale at the
 *   revision the page still shows, so a later save cannot undo the change.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'collab.js');

let fetchCalls;
let client;

function boot(extra) {
    // The radio markup the server renders (radio.py): the shared applier
    // finds a scheme's inputs by class and schema attribute.
    document.body.innerHTML = ['critical', 'neutral'].map((l) => `<form data-schema-name="stance"
        data-annotation-type="radio"><input class="stance shadcn-radio-input annotation-input"
        type="radio" name="stance" value="${l}" schema="stance" label_name="${l}"></form>`).join('');
    fetchCalls = [];
    window.fetch = jest.fn((input, init) => {
        fetchCalls.push({ input, init });
        return Promise.resolve({
            ok: true, status: 200,
            json: () => Promise.resolve({ events: [], cursor: 0, answer: {} }),
            clone() { return this; },
        });
    });
    window.potatoCollab = Object.assign({
        sid: 'RED', me: 'ben', instance_id: 'c1', rev: 4, cursor: 10,
        team_user: 'team-red', transport: 'poll', poll_interval_ms: 100000, base: '',
    }, extra || {});
    delete window.potatoSaveHooks;
    delete window.potatoNavigation;
    delete window.potatoCollabClient;
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(SOURCE, 'utf8'))();
    client = window.potatoCollabClient;
    // The shared setup clears `fetch` as a mock around every test.
    window.fetch.mockClear = () => {};
}

beforeEach(() => {
    jest.useFakeTimers();
    boot();
});

afterEach(() => {
    jest.useRealTimers();
    // collab.js replaced fetch with its wrapper; the shared setup clears a mock.
    window.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
});

describe('routing', () => {
    test('item data reads carry the session; paradata does not', async () => {
        await window.fetch('/api/spans/c1');
        await window.fetch('/get_annotations?instance_id=c1');
        await window.fetch('/api/track_interactions', { method: 'POST' });
        const sent = fetchCalls.slice(-3).map((c) => c.init && c.init.headers
            && c.init.headers.get && c.init.headers.get('X-Potato-Collab'));
        expect(sent).toEqual(['RED', 'RED', undefined]);
    });

    test('another origin never gets the header', () => {
        expect(client.isOwnedPath(client.pathOf('https://example.org/api/spans/c1'))).toBe(false);
    });

    test('a save carries the session, the base and a save id', () => {
        const payload = window.potatoSaveHooks.decorate({ instance_id: 'c1' });
        expect(payload.collab.sid).toBe('RED');
        expect(payload.collab.base_rev).toBe(4);
        expect(payload.collab.save_id).toMatch(/^ben-/);
    });

    test('navigation goes through the session', () => {
        expect(window.potatoNavigation.endpoint).toBe('/collab/api/RED/navigate');
    });
});

describe('base revision', () => {
    test("this page's own save moves the base at once", () => {
        client.onSaveResult({ rev_before: 4, rev: 5, overwrote: [] });
        expect(client.state.baseRev).toBe(5);
    });

    test('a save that landed after an unseen teammate edit does not', () => {
        client.onSaveResult({ rev_before: 5, rev: 6, overwrote: [] });
        expect(client.state.baseRev).toBe(4);
    });

    test("a teammate's edit waits until it is on screen", () => {
        client.handleEvents([{ seq: 11, type: 'edit', user: 'ana', ts: 1,
            data: { instance_id: 'c1', rev: 5, ops: [{ key: 'L:stance:::neutral' }] } }]);
        expect(client.state.baseRev).toBe(4);
        expect(client.state.pendingRemote).toHaveLength(1);
    });

    test('edits to other items do not touch this page', () => {
        client.handleEvents([{ seq: 11, type: 'edit', user: 'ana', ts: 1,
            data: { instance_id: 'c2', rev: 9, ops: [] } }]);
        expect(client.state.pendingRemote).toHaveLength(0);
    });
});

describe('applying a teammate change', () => {
    test('labels go to the shared applier with the whole scheme', () => {
        const calls = [];
        window.potatoApplyRemoteLabels = (changes) => calls.push(changes);
        const shown = client.applyKeys(new Set(['L:stance:::critical']), {
            'L:stance:::critical': 'critical', 'L:frames:::health': 'health',
        });
        expect(calls).toEqual([{ stance: { critical: 'critical' } }]);
        expect(shown.has('L:stance:::critical')).toBe(true);
    });

    test('a cleared scheme is sent as null', () => {
        const calls = [];
        window.potatoApplyRemoteLabels = (changes) => calls.push(changes);
        client.applyKeys(new Set(['L:stance:::critical']), {});
        expect(calls).toEqual([{ stance: null }]);
    });

    test('a blob with no live applier is not reported as shown', () => {
        window.potatoApplyRemoteLabels = () => {};
        delete window.potatoCollabAppliers;
        const shown = client.applyKeys(new Set(['L:img:::_data']), { 'L:img:::_data': '[]' });
        expect(shown.has('L:img:::_data')).toBe(false);
    });

    test('a registered applier takes the blob', () => {
        window.potatoCollabAppliers = { img: (schema, value) => value === '[1]' };
        const shown = client.applyKeys(new Set(['L:img:::_data']), { 'L:img:::_data': '[1]' });
        expect(shown.has('L:img:::_data')).toBe(true);
    });
});

describe('widgets that keep their own copy of the answer', () => {
    function widgetForm(type, schema, value) {
        const form = document.createElement('form');
        form.setAttribute('data-schema-name', schema);
        form.setAttribute('data-annotation-type', type);
        form.innerHTML = `<input type="hidden" class="annotation-input" schema="${schema}"
            label_name="${schema}" name="${schema}:::${schema}" value='${value}'>`;
        document.body.appendChild(form);
        return form.querySelector('input');
    }

    test('one with no live update is not reported as shown, and its input is left alone', () => {
        // Setting the input alone would leave the widget drawing (and later
        // saving) the old answer over the teammate's.
        const input = widgetForm('geo_annotation', 'map', '{"features":[]}');
        const calls = [];
        window.potatoApplyRemoteLabels = (changes) => calls.push(changes);
        const shown = client.applyKeys(new Set(['L:map:::map']), { 'L:map:::map': '{"features":[1]}' });
        expect(shown.size).toBe(0);
        expect(calls).toEqual([]);
        expect(input.value).toBe('{"features":[]}');
    });

    test('a registered widget gets the answer, already in its input', () => {
        const input = widgetForm('geo_annotation', 'map', '');
        const seen = [];
        window.potatoCollabWidgets = { geo_annotation: { apply(ctx) {
            seen.push([ctx.schema, ctx.labels, ctx.inputs[0].value, ctx.inputs[0].getAttribute('value')]);
            return true;
        } } };
        const shown = client.applyKeys(new Set(['L:map:::map']), { 'L:map:::map': '{"f":1}' });
        expect(shown.has('L:map:::map')).toBe(true);
        expect(seen).toEqual([['map', { map: '{"f":1}' }, '{"f":1}', '{"f":1}']]);
        expect(input.getAttribute('data-server-set')).toBe('true');
        delete window.potatoCollabWidgets;
    });

    test('a scheme rendered in a div (point cloud, volume) is found too', () => {
        const box = document.createElement('div');
        box.setAttribute('data-schema-name', 'scene');
        box.setAttribute('data-annotation-type', 'spatial_annotation');
        box.innerHTML = '<input type="hidden" class="annotation-data-input" name="scene">';
        document.body.appendChild(box);
        const seen = [];
        window.potatoCollabWidgets = { spatial_annotation: { apply(ctx) { seen.push(ctx.form); return true; } } };
        expect(client.applyKeys(new Set(['L:scene:::_data']), { 'L:scene:::_data': '[]' })
            .has('L:scene:::_data')).toBe(true);
        expect(seen).toEqual([box]);
        delete window.potatoCollabWidgets;
    });

    test('a widget the restore pass redraws is shown, unless the value was cleared', () => {
        widgetForm('ranking', 'order', 'a,b');
        const calls = [];
        window.potatoApplyRemoteLabels = (changes) => calls.push(changes);
        expect(client.applyKeys(new Set(['L:order:::order']), { 'L:order:::order': 'b,a' })
            .has('L:order:::order')).toBe(true);
        expect(calls).toEqual([{ order: { order: 'b,a' } }]);
        expect(client.applyKeys(new Set(['L:order:::order']), {}).size).toBe(0);
    });

    test('a failing widget is not reported as shown', () => {
        widgetForm('geo_annotation', 'map', '');
        window.potatoCollabWidgets = { geo_annotation: { apply() { throw new Error('boom'); } } };
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
        expect(client.applyKeys(new Set(['L:map:::map']), { 'L:map:::map': '{}' }).size).toBe(0);
        warn.mockRestore();
        delete window.potatoCollabWidgets;
    });
});

describe('links, coreference chains and events', () => {
    afterEach(() => {
        delete window.spanLinkManagers;
        delete window.eventAnnotationManagers;
    });

    test('every link scheme and coreference scheme reloads', () => {
        const a = { reload: jest.fn() }, b = { reload: jest.fn() }, coref = { reload: jest.fn() };
        window.spanLinkManagers = { rel: a, dep: b };
        const box = document.createElement('div');
        box.className = 'coref-container';
        box._coreferenceManager = coref;
        document.body.appendChild(box);
        const shown = client.applyKeys(new Set(['K:link_1']), {});
        expect(shown.has('K:link_1')).toBe(true);
        [a, b, coref].forEach((m) => expect(m.reload).toHaveBeenCalled());
    });

    test('events reload through their per-scheme managers', () => {
        const m = { reload: jest.fn(), loadExistingEvents: jest.fn() };
        window.eventAnnotationManagers = { ev: m };
        expect(client.applyKeys(new Set(['E:event_1']), {}).has('E:event_1')).toBe(true);
        expect(m.reload).toHaveBeenCalled();
        expect(m.loadExistingEvents).not.toHaveBeenCalled();
    });

    test('with no manager on the page, the change is not reported as shown', () => {
        expect(client.applyKeys(new Set(['K:link_1', 'E:e1']), {}).size).toBe(0);
    });
});

describe('saves made outside saveAnnotations', () => {
    test("a span manager's own save is given the session", async () => {
        await window.fetch('/updateinstance', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instance_id: 'c1', type: 'span', schema: 'ner', state: [] }),
        });
        const sent = JSON.parse(fetchCalls[fetchCalls.length - 1].init.body);
        expect(sent.collab.sid).toBe('RED');
        expect(sent.collab.base_rev).toBe(4);
        expect(sent.type).toBe('span');
    });

    test('a save that already names the session is left alone', async () => {
        const body = JSON.stringify({ instance_id: 'c1', collab: { sid: 'RED', base_rev: 2 } });
        await window.fetch('/updateinstance', { method: 'POST', body });
        expect(fetchCalls[fetchCalls.length - 1].init.body).toBe(body);
    });
});

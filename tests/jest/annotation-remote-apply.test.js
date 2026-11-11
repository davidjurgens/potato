/**
 * The hooks a live collaborative page uses on the shared annotation page:
 *
 * - applyRemoteLabels() shows a teammate's answer for some schemes without a
 *   reload. It must empty what they cleared (populateInputValues never
 *   empties anything), leave every other scheme alone -- including this
 *   annotator's own unsaved edit -- and fire nothing a save listener would
 *   take as this annotator's input.
 * - decorateSavePayload() lets a feature add to both save paths, and a hook
 *   that throws must not cost the annotator the save.
 * - navigationEndpoint() is /annotate unless a page installs its own.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'annotation.js');
const NAMES = ['applyRemoteLabels', 'syncAnnotationsFromDOM', 'restoreInputEvent',
               'decorateSavePayload', 'navigationEndpoint'];

function extractFunction(source, name) {
    const start = source.indexOf(`function ${name}(`);
    if (start === -1) throw new Error(`${name}() not found in annotation.js`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for (let j = open; j < source.length; j++) {
        if (source[j] === '{') depth++;
        else if (source[j] === '}') {
            depth--;
            if (depth === 0) return source.slice(start, j + 1);
        }
    }
    throw new Error(`unbalanced braces reading ${name}()`);
}

let api;
let populated;

function load() {
    const src = fs.readFileSync(SOURCE, 'utf8');
    const body = NAMES.map((name) => extractFunction(src, name)).join('\n');
    populated = 0;
    api = new Function('onPopulate', `
        let currentAnnotations = {};
        function debugLog() {}
        function populateInputValues() { onPopulate(currentAnnotations); }
        ${body}
        return {applyRemoteLabels, syncAnnotationsFromDOM, decorateSavePayload,
                navigationEndpoint, annotations: () => currentAnnotations};
    `)(() => { populated += 1; });
}

function input(type, schema, label, value) {
    const el = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') el.type = type;
    el.className = 'annotation-input';
    el.setAttribute('schema', schema);
    el.setAttribute('label_name', label);
    if (value !== undefined) el.value = value;
    document.body.appendChild(el);
    return el;
}

let changes;

beforeEach(() => {
    document.body.innerHTML = '';
    delete window.potatoSaveHooks;
    delete window.potatoNavigation;
    load();
    changes = [];
    document.addEventListener('change', (e) => changes.push(e.target), true);
});

describe('applyRemoteLabels', () => {
    test('a teammate picking another radio option moves the selection', () => {
        const pos = input('radio', 'sentiment', 'positive', 'positive');
        const neg = input('radio', 'sentiment', 'negative', 'negative');
        pos.checked = true;

        api.applyRemoteLabels({sentiment: {negative: 'true'}});

        expect(pos.checked).toBe(false);
        expect(neg.checked).toBe(true);
        expect(api.annotations().sentiment).toEqual({negative: 'true'});
    });

    test('a cleared text answer is emptied, not left on screen', () => {
        const box = input('textarea', 'why', 'text_box', 'old reason');

        api.applyRemoteLabels({why: null});

        expect(box.value).toBe('');
        expect(api.annotations().why).toBeUndefined();
    });

    test('a removed checkbox is unchecked and the rest of the scheme follows', () => {
        const a = input('checkbox', 'topics', 'sports', 'sports');
        const b = input('checkbox', 'topics', 'politics', 'politics');
        a.checked = true;
        b.checked = true;

        api.applyRemoteLabels({topics: {politics: 'politics'}});

        expect(a.checked).toBe(false);
        expect(b.checked).toBe(true);
    });

    test('my unsaved edit on another scheme survives', () => {
        input('radio', 'sentiment', 'positive', 'positive');
        const mine = input('text', 'note', 'text_box');
        mine.value = 'typing this now';

        api.applyRemoteLabels({sentiment: {positive: 'true'}});

        expect(mine.value).toBe('typing this now');
        expect(api.annotations().note).toEqual({text_box: 'typing this now'});
    });

    test('a hidden answer is marked as server-set so the next sync keeps it', () => {
        const hidden = input('hidden', 'rank', 'order');

        api.applyRemoteLabels({rank: {order: 'b,a,c'}});
        expect(hidden.value).toBe('b,a,c');
        expect(hidden.getAttribute('data-server-set')).toBe('true');
        api.syncAnnotationsFromDOM();
        expect(api.annotations().rank).toEqual({order: 'b,a,c'});

        api.applyRemoteLabels({rank: null});
        expect(hidden.value).toBe('');
        expect(hidden.hasAttribute('data-server-set')).toBe(false);
    });

    test('nothing it does looks like this annotator answering', () => {
        input('radio', 'sentiment', 'positive', 'positive');
        const box = input('text', 'note', 'text_box');
        const inputs = [];
        box.addEventListener('input', (e) => inputs.push(e));

        api.applyRemoteLabels({sentiment: {positive: 'true'}, note: {text_box: 'theirs'}});

        expect(changes).toEqual([]);
        expect(inputs.length).toBe(1);
        expect(inputs[0].detail && inputs[0].detail.potatoRestore).toBe(true);
    });

    test('custom schemes get their redraw', () => {
        api.applyRemoteLabels({anything: null});
        expect(populated).toBe(1);
    });
});

describe('decorateSavePayload', () => {
    test('with no hook the payload goes out as built', () => {
        const payload = {instance_id: 'i1'};
        expect(api.decorateSavePayload(payload)).toBe(payload);
    });

    test('an installed hook adds to the payload', () => {
        window.potatoSaveHooks = {decorate: (p) => Object.assign(p, {collab: {sid: 'S'}})};
        expect(api.decorateSavePayload({instance_id: 'i1'}))
            .toEqual({instance_id: 'i1', collab: {sid: 'S'}});
    });

    test('a hook that throws does not cost the save', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
        window.potatoSaveHooks = {decorate: () => { throw new Error('boom'); }};
        expect(api.decorateSavePayload({instance_id: 'i1'})).toEqual({instance_id: 'i1'});
        warn.mockRestore();
    });
});

describe('navigationEndpoint', () => {
    test('is /annotate by default', () => {
        expect(api.navigationEndpoint()).toBe('/annotate');
    });

    test('follows a page that installs its own', () => {
        window.potatoNavigation = {endpoint: '/collab/api/ABC/navigate'};
        expect(api.navigationEndpoint()).toBe('/collab/api/ABC/navigate');
    });
});

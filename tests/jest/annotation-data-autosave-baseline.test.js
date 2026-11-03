/**
 * The autosave of blob inputs (canvas, grounding, captions, timelines) saves
 * only an edit, measured against a baseline (audit 102):
 *
 * - The baseline is the value the server rendered, from data-arrived-value.
 *   On a hidden input `.value` rewrites the `value` attribute, so a widget
 *   that wrote an empty answer while it set itself up replaced the arrival
 *   value, and its prelabel arriving next was stored as an edit.
 * - It moves to whatever a save sends. Fixed at arrival forever, an edit
 *   undone back to the arrival value after a save was never saved.
 * - Every change event restarts the timer, so a redraw that passes through
 *   a different value and back saves nothing.
 * - A save already pending from a widget's direct call still happens.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'annotation.js');
const NAMES = ['setupAnnotationDataAutosave', 'annotationDataChanged', 'sameAnnotationData',
               'isEmptyAnnotationData', 'scheduleAnnotationDataSave',
               'anyAnnotationDataChanged', 'collectAnnotationDataInputs'];

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
let saves;

function load() {
    const src = fs.readFileSync(SOURCE, 'utf8');
    const body = NAMES.map((name) => extractFunction(src, name)).join('\n');
    saves = [];
    api = new Function('record', `
        let currentInstance = {id: 'i1'};
        let textSaveTimer = null;
        let conditionalSaveTimer = null;
        function debugLog() {}
        function saveAnnotations() {
            const sent = collectAnnotationDataInputs({});
            record(sent);
        }
        ${body}
        return {setupAnnotationDataAutosave, scheduleAnnotationDataSave};
    `)((sent) => saves.push(sent));
}

function input(name, rendered, live) {
    const el = document.createElement('input');
    el.type = 'hidden';
    el.className = 'annotation-data-input';
    el.name = name;
    el.setAttribute('data-arrived-value', rendered);
    el.value = live === undefined ? rendered : live;
    document.body.appendChild(el);
    return el;
}

function change(el, value) {
    el.value = value;
    el.dispatchEvent(new Event('change', {bubbles: true}));
}

beforeEach(() => {
    document.body.innerHTML = '';
    jest.useFakeTimers();
    load();
});

afterEach(() => jest.useRealTimers());

const PRELABEL = '{"captions": [{"region": {"type": "bbox", "label": "object"}, "caption": "a mug"}]}';
const COMPACT = '{"captions":[{"region":{"type":"bbox","label":"object","color":"#f00"},"caption":"a mug"}]}';

test('a prelabel the widget re-writes after an early blank is not an edit', () => {
    // The widget wrote a blank before autosave was wired, as region_caption does.
    const el = input('captions', PRELABEL, '{"captions":[]}');
    api.setupAnnotationDataAutosave();
    change(el, COMPACT);           // same answer, new spacing and a colour
    jest.advanceTimersByTime(2000);
    expect(saves).toHaveLength(0);
});

test('an edit undone back to the arrival value after a save is saved too', () => {
    const el = input('ground', '');
    api.setupAnnotationDataAutosave();
    change(el, '{"regions":{"0":[{"type":"bbox"}]}}');
    jest.advanceTimersByTime(900);
    expect(saves).toHaveLength(1);
    change(el, '');                // "Clear this answer"
    jest.advanceTimersByTime(900);
    expect(saves).toHaveLength(2);
});

test('a redraw that passes through another value and back saves nothing', () => {
    const el = input('captions', PRELABEL);
    api.setupAnnotationDataAutosave();
    change(el, '{"captions":[]}');
    jest.advanceTimersByTime(500);
    change(el, COMPACT);
    jest.advanceTimersByTime(2000);
    expect(saves).toHaveLength(0);
});

test('a direct save already pending still happens', () => {
    const el = input('canvas', '[]');
    api.setupAnnotationDataAutosave();
    api.scheduleAnnotationDataSave();          // a widget asking to save
    change(el, '[]');                          // an unchanged event in the meantime
    jest.advanceTimersByTime(900);
    expect(saves).toHaveLength(1);
});


test('a region with no caption is not part of a caption answer', () => {
    // The canvas prelabel had a second region the caption prelabel did not
    // caption; the widget lists it with an empty caption (audit 102, R1).
    const el = input('captions', PRELABEL);
    api.setupAnnotationDataAutosave();
    change(el, COMPACT.replace(']}', ',{"region":{"type":"polygon"},"caption":""}]}'));
    jest.advanceTimersByTime(2000);
    expect(saves).toHaveLength(0);
    change(el, COMPACT.replace(']}', ',{"region":{"type":"polygon"},"caption":"a cup"}]}'));
    jest.advanceTimersByTime(2000);
    expect(saves).toHaveLength(1);
});

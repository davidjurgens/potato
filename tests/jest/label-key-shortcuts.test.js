/**
 * Label shortcuts (annotation.js installLabelKeyShortcuts) fire on keyup, so a
 * widget that handled the key on keydown could not stop them: pressing triage's
 * `1` accepted the item and also ticked a radio bound to `1`, Ctrl+C ticked a
 * label bound to `c`, and typing in a <select> ran shortcuts. A keyup now acts
 * only when this page saw its keydown, with no modifier, and nothing called
 * preventDefault on it.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'annotation.js');

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

beforeAll(() => {
    const src = fs.readFileSync(SOURCE, 'utf8');
    const install = new Function(
        'selectPairwiseTile', 'selectPairwiseOption', 'selectBwsTile',
        `${extractFunction(src, 'isEditableElement')}
         ${extractFunction(src, 'installLabelKeyShortcuts')}
         return installLabelKeyShortcuts;`)(() => {}, () => {}, () => {});
    install();
});

let widgetPrevents;
const widget = (e) => { if (widgetPrevents.has(e.key)) e.preventDefault(); };

beforeEach(() => {
    widgetPrevents = new Set();
    document.addEventListener('keydown', widget);
    document.body.innerHTML = `
        <input type="checkbox" id="cb-1" data-key="1">
        <input type="checkbox" id="cb-c" data-key="c">
        <select id="sel"><option>a</option><option>c</option></select>
        <div id="ce" contenteditable="true" tabindex="0"></div>`;
    document.body.focus();
});

afterEach(() => document.removeEventListener('keydown', widget));

function press(key, opts = {}) {
    const { code = '', down = {}, up = {} } = opts;
    const target = document.activeElement || document.body;
    target.dispatchEvent(new KeyboardEvent('keydown',
        { key, code, bubbles: true, cancelable: true, ...down }));
    target.dispatchEvent(new KeyboardEvent('keyup',
        { key: up.key || key, code, bubbles: true, cancelable: true, ...up }));
}

const checked = (id) => document.getElementById(id).checked;

test('a plain key toggles its label', () => {
    press('1');
    expect(checked('cb-1')).toBe(true);
});

test('a key a widget handled on keydown does not also toggle a label', () => {
    widgetPrevents.add('1');                      // triage accept, card-sort zone
    press('1');
    expect(checked('cb-1')).toBe(false);
});

test('Ctrl, Cmd or Alt with the key does not toggle a label', () => {
    press('c', { down: { ctrlKey: true }, up: { ctrlKey: true } });
    press('c', { down: { metaKey: true } });      // Cmd released before the c
    press('c', { down: { altKey: true }, up: { altKey: true } });
    expect(checked('cb-c')).toBe(false);
});

test('a keyup with no keydown on this page does nothing', () => {
    document.body.dispatchEvent(new KeyboardEvent('keyup', { key: '1', bubbles: true }));
    expect(checked('cb-1')).toBe(false);
});

test('typing in a select runs no shortcut', () => {
    document.getElementById('sel').focus();
    press('c');
    expect(checked('cb-c')).toBe(false);
});

test('typing in a contenteditable region runs no shortcut', () => {
    document.getElementById('ce').focus();
    expect(document.activeElement.id).toBe('ce');
    press('c');
    expect(checked('cb-c')).toBe(false);
});

test('Shift released before the key still pairs by physical key', () => {
    press('!', { code: 'Digit1', up: { key: '1' } });   // Shift+1 down, 1 up
    expect(checked('cb-1')).toBe(true);
});

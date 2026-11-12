/**
 * Left and right arrows change the item (annotation.js installArrowNavigation),
 * unless something on the page already used the key. Before, the listener sat
 * on document and ignored preventDefault, so on a video or audio page ArrowRight
 * seeked five seconds and also moved to the next item, and an arrow on a
 * focused range-slider thumb moved the thumb and changed the item.
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

const moves = [];

beforeAll(() => {
    const src = fs.readFileSync(SOURCE, 'utf8');
    new Function('navigateToPrevious', 'navigateToNext',
        `${extractFunction(src, 'isEditableElement')}
         ${extractFunction(src, 'installArrowNavigation')}
         installArrowNavigation();`)(() => moves.push('prev'), () => moves.push('next'));
});

let viewerKeepsArrows;
// A page-level viewer, registered after annotation.js as the real ones are.
const viewer = (e) => { if (viewerKeepsArrows && e.key.startsWith('Arrow')) e.preventDefault(); };

beforeEach(() => {
    moves.length = 0;
    viewerKeepsArrows = false;
    delete window.potatoTrial;
    document.addEventListener('keydown', viewer);
    document.body.innerHTML = '<select id="sel"><option>a</option><option>b</option></select>'
        + '<div id="thumb" role="slider" tabindex="0"></div>';
    document.body.focus();
});

afterEach(() => document.removeEventListener('keydown', viewer));

function press(key, target = document.activeElement || document.body) {
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
}

test('arrows change the item', () => {
    press('ArrowRight');
    press('ArrowLeft');
    expect(moves).toEqual(['next', 'prev']);
});

test('an arrow a viewer used does not also change the item', () => {
    viewerKeepsArrows = true;                   // video seek, audio seek
    press('ArrowRight');
    expect(moves).toEqual([]);
});

test('an arrow on an element that keeps it does not change the item', () => {
    const thumb = document.getElementById('thumb');
    thumb.addEventListener('keydown', (e) => e.preventDefault());   // range slider
    thumb.focus();
    press('ArrowRight');
    expect(moves).toEqual([]);
});

test('an arrow in a select picks an option', () => {
    document.getElementById('sel').focus();
    press('ArrowRight');
    expect(moves).toEqual([]);
});

test('a running timed trial keeps the arrows', () => {
    window.potatoTrial = { ownsKeys: true };
    press('ArrowRight');
    expect(moves).toEqual([]);
});

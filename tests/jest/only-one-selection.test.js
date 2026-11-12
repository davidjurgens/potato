/**
 * onlyOne() — the single-select enforcer behind radio, likert, confidence and
 * the span-label palette.
 *
 * It shipped ending in `checkbox.checked = true`. For the `type="radio"`
 * schemas that is a no-op, so nothing looked wrong; for the span palette,
 * which is `type="checkbox"`, it meant the browser's own untoggle was undone
 * a microtask later and an armed code could never be turned off. Measured in
 * Chrome with a capture-phase listener: `checked` was false entering the
 * handler and true by the time `change` fired.
 *
 * That mattered beyond a stuck checkbox. Applying a code consumes the text
 * selection, and the in-vivo `i` shortcut needs a live one, so once any code
 * was armed there was no way back to minting without reloading the page —
 * in an open-coding project, that is the main workflow.
 *
 * Two test files already claimed to cover this function. Both re-implemented
 * it — one in Python, one in JavaScript — so neither could ever fail. This one
 * runs the source that ships.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'annotation.js');

/** Pull one top-level function out of a script that cannot be imported. */
function extractFunction(source, name) {
    const start = source.indexOf(`function ${name}(`);
    if (start === -1) throw new Error(`${name}() not found in annotation.js`);
    let i = source.indexOf('{', start);
    let depth = 0;
    for (let j = i; j < source.length; j++) {
        if (source[j] === '{') depth++;
        else if (source[j] === '}') {
            depth--;
            if (depth === 0) return source.slice(start, j + 1);
        }
    }
    throw new Error(`unbalanced braces reading ${name}()`);
}

let onlyOne;

beforeAll(() => {
    const src = extractFunction(fs.readFileSync(SOURCE, 'utf8'), 'onlyOne');
    // debugLog is defined elsewhere in annotation.js; the function under test
    // must not depend on it doing anything.
    onlyOne = new Function('debugLog', `${src}; return onlyOne;`)(() => {});
});

/** A palette of same-class inputs, as the span schema renders them. */
function palette(type, values) {
    document.body.innerHTML = '';
    return values.map((value) => {
        const input = document.createElement('input');
        input.type = type;
        input.className = 'codes shadcn-span-checkbox';
        input.value = value;
        input.name = type === 'radio' ? 'codes' : `span_label:::codes`;
        document.body.appendChild(input);
        return input;
    });
}

/** What the browser does before the inline onclick runs. */
function clickAndEnforce(input) {
    if (input.type === 'checkbox') input.checked = !input.checked;
    else input.checked = true;
    onlyOne(input);
}

describe('the span palette (type=checkbox)', () => {
    test('arming a code selects it and nothing else', () => {
        const [a, b, c] = palette('checkbox', ['access', 'cost', 'trust']);
        clickAndEnforce(a);
        expect([a.checked, b.checked, c.checked]).toEqual([true, false, false]);
    });

    test('arming a second code moves the selection', () => {
        const [a, b, c] = palette('checkbox', ['access', 'cost', 'trust']);
        clickAndEnforce(a);
        clickAndEnforce(b);
        expect([a.checked, b.checked, c.checked]).toEqual([false, true, false]);
    });

    test('clicking the armed code again disarms it', () => {
        // The regression. Without this, in-vivo coding is unreachable.
        const [a, b] = palette('checkbox', ['access', 'cost']);
        clickAndEnforce(a);
        clickAndEnforce(a);
        expect(a.checked).toBe(false);
        expect(b.checked).toBe(false);
    });

    test('disarming and re-arming works repeatedly', () => {
        const [a] = palette('checkbox', ['access', 'cost']);
        for (let i = 0; i < 3; i++) {
            clickAndEnforce(a);
            expect(a.checked).toBe(true);
            clickAndEnforce(a);
            expect(a.checked).toBe(false);
        }
    });

    test('nothing armed is a reachable state', () => {
        const inputs = palette('checkbox', ['access', 'cost', 'trust']);
        clickAndEnforce(inputs[1]);
        clickAndEnforce(inputs[1]);
        expect(inputs.some((i) => i.checked)).toBe(false);
    });
});

describe('the radio schemas are unaffected', () => {
    test('picking a label selects exactly one', () => {
        const [a, b, c] = palette('radio', ['pos', 'neg', 'neutral']);
        clickAndEnforce(b);
        expect([a.checked, b.checked, c.checked]).toEqual([false, true, false]);
    });

    test('clicking the selected label leaves it selected', () => {
        // Native radio behaviour: a click cannot clear it, and onlyOne must
        // not invent a way to.
        const [a, b] = palette('radio', ['pos', 'neg']);
        clickAndEnforce(a);
        clickAndEnforce(a);
        expect(a.checked).toBe(true);
        expect(b.checked).toBe(false);
    });
});

describe('it only touches its own group', () => {
    test('a differently-classed input is left alone', () => {
        const [a] = palette('checkbox', ['access', 'cost']);
        const other = document.createElement('input');
        other.type = 'checkbox';
        other.className = 'themes shadcn-multiselect-checkbox';
        other.value = 'access';          // same value, different group
        other.checked = true;
        document.body.appendChild(other);

        clickAndEnforce(a);
        expect(other.checked).toBe(true);
    });
});

describe('the source itself', () => {
    test('does not force the clicked input checked', () => {
        const src = extractFunction(fs.readFileSync(SOURCE, 'utf8'), 'onlyOne');
        expect(src).not.toMatch(/checkbox\.checked\s*=\s*true/);
    });

    test('and the flag that masked it is gone', () => {
        const src = extractFunction(fs.readFileSync(SOURCE, 'utf8'), 'onlyOne');
        expect(src).not.toContain('data-just-checked');
    });
});

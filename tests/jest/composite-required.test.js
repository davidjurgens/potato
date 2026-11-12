/**
 * `required` on a composite widget meant "touched once", not "answered".
 *
 * validateRequiredFields tests hidden inputs with
 * `!input.value || input.value.trim() === ''`, so any non-empty JSON passed. An
 * agent_scorecard declaring four agents by two dimensions plus two team
 * dimensions asks ten questions and was satisfied by one; a failure_attribution
 * with a null decisive step was satisfied by naming an agent.
 *
 * `budgetShortfall` already solved this shape for constant_sum. Only the widget
 * knows how many cells it declared, so each one writes `data-incomplete-reason`
 * on its form and `compositeShortfall` reads it.
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

let compositeShortfall;
beforeAll(() => {
    const src = fs.readFileSync(SOURCE, 'utf8');
    compositeShortfall = new Function(
        `${extractFunction(src, 'compositeShortfall')}; return compositeShortfall;`)();
});

function form(reason) {
    const el = document.createElement('form');
    el.className = 'annotation-form';
    if (reason !== undefined) el.setAttribute('data-incomplete-reason', reason);
    return el;
}

describe('compositeShortfall', () => {
    test('a widget with nothing to declare is satisfied', () => {
        expect(compositeShortfall(form())).toBeNull();
    });

    test('a cleared reason is satisfied', () => {
        expect(compositeShortfall(form(''))).toBeNull();
    });

    test('whitespace is not a reason', () => {
        expect(compositeShortfall(form('   '))).toBeNull();
    });

    test('the reason is returned for the error banner', () => {
        expect(compositeShortfall(form('3 of 10 scored'))).toBe('3 of 10 scored');
    });

    test('it is trimmed, so the banner does not gain a stray space', () => {
        expect(compositeShortfall(form(' 3 of 10 scored '))).toBe('3 of 10 scored');
    });

    test('a missing form is not an error', () => {
        expect(compositeShortfall(null)).toBeNull();
    });

    test.each([
        ['3 of 10 scored'],
        ['2 of 5 handoffs reviewed'],
        ['no decisive step chosen'],
        ['turn #3 still needs the turn it refers to'],
    ])('the reasons the widgets actually write survive the round trip: %s', (reason) => {
        expect(compositeShortfall(form(reason))).toBe(reason);
    });
});

describe('validateRequiredFields consults it', () => {
    test('the check is wired in, not just defined', () => {
        const src = fs.readFileSync(SOURCE, 'utf8');
        const body = extractFunction(src, 'validateRequiredFields');
        expect(body).toContain('compositeShortfall(group.form)');
    });

    test('a declared shortfall becomes the reason shown to the annotator', () => {
        const src = fs.readFileSync(SOURCE, 'utf8');
        const body = extractFunction(src, 'validateRequiredFields');
        // The reason must reach `unfilledSchemas`, which is what the banner reads.
        expect(body).toMatch(/reason = declared/);
        expect(body).toContain('reason: reason');
    });
});

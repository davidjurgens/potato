/**
 * Messages that annotation.js builds use the configured `ui_language`.
 *
 * The page template puts the resolved strings in `window.UI_LANG`. Before, the
 * required-fields banner was always English ("Please answer the required
 * question(s): ..."), also on a study with `ui_language: de`.
 *
 * These run the functions that ship, pulled out of the source.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'annotation.js');

/** Pull one top-level `function` or `const` block out of annotation.js. */
function extractBlock(source, head) {
    const start = source.indexOf(head);
    if (start === -1) throw new Error(`${head} not found in annotation.js`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for (let j = open; j < source.length; j++) {
        if (source[j] === '{') depth++;
        else if (source[j] === '}') {
            depth--;
            if (depth === 0) return source.slice(start, j + 1) + ';';
        }
    }
    throw new Error(`unbalanced braces reading ${head}`);
}

let uiText;
let updateRequiredFieldsError;

beforeAll(() => {
    const src = fs.readFileSync(SOURCE, 'utf8');
    const code = [
        extractBlock(src, 'const UI_TEXT_FALLBACK = {'),
        extractBlock(src, 'function uiText('),
        extractBlock(src, 'function escapeHtml('),
        extractBlock(src, 'function updateRequiredFieldsError('),
    ].join('\n');
    ({ uiText, updateRequiredFieldsError } = new Function(
        `${code}; return { uiText, updateRequiredFieldsError };`)());
});

beforeEach(() => {
    delete window.UI_LANG;
    document.body.innerHTML = '<div class="potato-nav"></div>';
});

describe('uiText()', () => {
    test('uses the English fallback when the page has no UI_LANG', () => {
        expect(uiText('navigation_failed')).toBe('Navigation failed. Please try again.');
    });

    test('uses the configured string and fills placeholders', () => {
        window.UI_LANG = { budget_allocated: '{sum} von {total} vergeben' };
        expect(uiText('budget_allocated', { sum: 40, total: 100 })).toBe('40 von 100 vergeben');
    });

    test('keeps a placeholder that the caller did not give', () => {
        window.UI_LANG = { budget_allocated: '{sum} / {total} {unit}' };
        expect(uiText('budget_allocated', { sum: 1, total: 2 })).toBe('1 / 2 {unit}');
    });
});

describe('updateRequiredFieldsError()', () => {
    const one = [{ name: 'q1', label: 'Frage 1', reason: null }];
    const two = [...one, { name: 'q2', label: 'Frage 2', reason: null }];

    test('English singular and plural are unchanged', () => {
        updateRequiredFieldsError(one);
        let text = document.getElementById('required-fields-error').textContent.trim();
        expect(text).toBe('Please answer the required question: Frage 1');

        updateRequiredFieldsError(two);
        text = document.getElementById('required-fields-error').textContent.trim();
        expect(text).toBe('Please answer the required questions: Frage 1, Frage 2');
    });

    test('German uses the singular and plural strings from UI_LANG', () => {
        window.UI_LANG = {
            required_question_one: 'Bitte beantworten Sie die Pflichtfrage:',
            required_question_many: 'Bitte beantworten Sie die Pflichtfragen:',
        };
        updateRequiredFieldsError(one);
        let text = document.getElementById('required-fields-error').textContent.trim();
        expect(text).toBe('Bitte beantworten Sie die Pflichtfrage: Frage 1');

        updateRequiredFieldsError(two);
        text = document.getElementById('required-fields-error').textContent.trim();
        expect(text).toBe('Bitte beantworten Sie die Pflichtfragen: Frage 1, Frage 2');
    });

    test('a translated string is shown as text, not as markup', () => {
        window.UI_LANG = { required_question_one: '<b>x</b>' };
        updateRequiredFieldsError(one);
        const banner = document.getElementById('required-fields-error');
        expect(banner.querySelector('b')).toBeNull();
        expect(banner.textContent).toContain('<b>x</b>');
    });
});

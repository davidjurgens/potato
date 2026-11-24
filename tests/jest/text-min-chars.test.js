/**
 * `min_chars` on a `text` scheme blocks navigation, and its counter is live.
 *
 * Before, `min_chars` only rendered a counter. validateRequiredFields did not
 * read it, so Next accepted 5 characters where the study asked for 200, and
 * on phase pages nothing bound the counter, so it stayed at 0.
 *
 * The functions run here are the real ones, read from annotation.js. The
 * forms copy the markup that schemas/textbox.py renders.
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

const NAMES = [
    'textAnswerLength', 'textShortfall', 'isSchemaHiddenByDisplayLogic',
    'budgetShortfall', 'compositeShortfall', 'validateRequiredFields',
    'updateRequiredFieldsError', 'updateAllCharCounters',
];

let api;
beforeAll(() => {
    const src = fs.readFileSync(SOURCE, 'utf8');
    const body = NAMES.map(n => extractFunction(src, n)).join('\n');
    api = new Function(`
        let hasAttemptedForwardValidation = false;
        ${body}
        return { ${NAMES.join(', ')},
                 attempt: () => { hasAttemptedForwardValidation = true; } };
    `)();
});

function box(schema, label, { textarea = false, required = false, min = 20 } = {}) {
    const id = `${schema}_${label}_text`;
    const tag = textarea ? 'textarea' : 'input type="text"';
    const close = textarea ? '</textarea>' : '';
    return `
        <div class="shadcn-textbox-item">
            ${label === 'text_box' ? '' : `<label for="${id}">${label}</label>`}
            <${tag} class="${schema} shadcn-textbox-input annotation-input" id="${id}"
                name="${schema}:::${label}" validation="${required ? 'required' : ''}">${close}
            <div class="shadcn-textbox-char-counter" data-input-id="${id}" data-min-chars="${min}">
                <span class="shadcn-textbox-char-count">0</span>/${min} min characters
            </div>
        </div>`;
}

function page(schema, labels, opts = {}) {
    const min = opts.min === undefined ? 20 : opts.min;
    document.body.innerHTML = `
        <div class="schema-container">
        <form id="${schema}" class="annotation-form textbox" data-schema-name="${schema}"
              data-min-chars="${min}" data-too-short-text="${opts.template || '{count} of {min} characters'}">
            <fieldset><legend>Define populism</legend>
                ${labels.map(l => box(schema, l, { ...opts, min })).join('')}
            </fieldset>
        </form>
        </div>
        <div class="potato-nav"></div>`;
    return document.getElementById(schema);
}

function type(input, text) {
    input.value = text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
}

describe('textShortfall', () => {
    test('text below the minimum is short, with the trimmed count', () => {
        const form = page('def', ['text_box']);
        form.querySelector('input').value = '  hello  ';
        expect(api.textShortfall(form)).toBe('5 of 20 characters');
    });

    test('text at the minimum is complete', () => {
        const form = page('def', ['text_box']);
        form.querySelector('input').value = 'x'.repeat(20);
        expect(api.textShortfall(form)).toBeNull();
    });

    test('an optional empty box is complete; a required one is short', () => {
        expect(api.textShortfall(page('def', ['text_box']))).toBeNull();
        expect(api.textShortfall(page('def', ['text_box'], { required: true })))
            .toBe('0 of 20 characters');
    });

    test('a textarea is checked the same way', () => {
        const form = page('def', ['text_box'], { textarea: true });
        form.querySelector('textarea').value = 'short';
        expect(api.textShortfall(form)).toBe('5 of 20 characters');
    });

    test('each box of a multi-box scheme is named', () => {
        const form = page('def', ['Pro', 'Contra']);
        form.querySelector('#def_Pro_text').value = 'x'.repeat(25);
        form.querySelector('#def_Contra_text').value = 'abc';
        expect(api.textShortfall(form)).toBe('Contra: 3 of 20 characters');
    });

    test('the reason uses the localized template', () => {
        const form = page('def', ['text_box'], { template: '{count} von {min} Zeichen' });
        form.querySelector('input').value = 'kurz';
        expect(api.textShortfall(form)).toBe('4 von 20 Zeichen');
    });

    test('a form without min_chars has nothing to say', () => {
        expect(api.textShortfall(page('def', ['text_box'], { min: 0 }))).toBeNull();
    });
});

describe('validateRequiredFields', () => {
    test('short text blocks navigation and the error names the field', () => {
        const form = page('def', ['text_box']);
        form.querySelector('input').value = 'too short';
        expect(api.validateRequiredFields({ showErrors: true })).toBe(false);
        const error = document.getElementById('required-fields-error');
        expect(error.textContent).toContain('Define populism');
        expect(error.textContent).toContain('9 of 20 characters');
        expect(form.classList.contains('required-unfilled')).toBe(true);
    });

    test('long enough text lets the annotator go', () => {
        const form = page('def', ['text_box']);
        form.querySelector('input').value = 'x'.repeat(20);
        expect(api.validateRequiredFields({ showErrors: true })).toBe(true);
    });

    test('a required short textarea blocks', () => {
        const form = page('def', ['text_box'], { textarea: true, required: true });
        form.querySelector('textarea').value = 'abc';
        expect(api.validateRequiredFields()).toBe(false);
    });

    test('one short box of a multi-box scheme blocks', () => {
        const form = page('def', ['Pro', 'Contra']);
        form.querySelector('#def_Pro_text').value = 'x'.repeat(25);
        form.querySelector('#def_Contra_text').value = 'abc';
        expect(api.validateRequiredFields()).toBe(false);
        form.querySelector('#def_Contra_text').value = 'y'.repeat(20);
        expect(api.validateRequiredFields()).toBe(true);
    });

    test('a question hidden by display logic does not block', () => {
        const form = page('def', ['text_box']);
        form.querySelector('input').value = 'abc';
        form.parentElement.classList.add('display-logic-hidden');
        expect(api.validateRequiredFields()).toBe(true);
    });
});

describe('updateAllCharCounters', () => {
    test('the counter shows the trimmed length and follows the typing', () => {
        const form = page('def', ['text_box']);
        const input = form.querySelector('input');
        const counter = form.querySelector('.shadcn-textbox-char-counter');
        api.updateAllCharCounters();
        expect(counter.querySelector('.shadcn-textbox-char-count').textContent).toBe('0');

        type(input, '  hello ');
        expect(counter.querySelector('.shadcn-textbox-char-count').textContent).toBe('5');
        expect(counter.classList.contains('char-count-unmet')).toBe(true);

        type(input, 'x'.repeat(20));
        expect(counter.querySelector('.shadcn-textbox-char-count').textContent).toBe('20');
        expect(counter.classList.contains('char-count-met')).toBe(true);
    });

    test('typing refreshes the error after a blocked attempt', () => {
        const form = page('def', ['text_box']);
        const input = form.querySelector('input');
        api.updateAllCharCounters();
        api.attempt();
        type(input, 'abc');
        expect(document.getElementById('required-fields-error').style.display).toBe('block');
        type(input, 'x'.repeat(20));
        expect(document.getElementById('required-fields-error').style.display).toBe('none');
    });

    test('a second call does not bind a second listener', () => {
        const form = page('def', ['text_box']);
        api.updateAllCharCounters();
        api.updateAllCharCounters();
        expect(form.querySelector('input').dataset.charCounterBound).toBe('true');
    });
});

describe('phase pages bind the counter', () => {
    test('the phase-page start-up calls updateAllCharCounters', () => {
        const src = fs.readFileSync(SOURCE, 'utf8');
        const start = src.indexOf('if (window.config && !window.config.is_annotation_page) {');
        const branch = src.slice(start, src.indexOf('return;', start));
        expect(branch).toContain('updateAllCharCounters()');
    });
});

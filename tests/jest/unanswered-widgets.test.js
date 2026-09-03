/**
 * The client half of "an untouched widget is not an answer".
 *
 * Three functions in annotation.js decide what a widget is reporting, and each
 * of them had a hole:
 *
 *  - `loadAnnotations()` only synced a `<select>` to the server's rendering when
 *    the server had rendered a selection. With none, whatever Chrome had
 *    restored from the previous document stayed in the box and was recorded as
 *    this instance's answer.
 *  - `validateRequiredFields()` checked each input for emptiness and nothing
 *    else, so `constant_sum` and `soft_label` — whose whole point is that the
 *    parts add up to a declared total — passed on any non-empty partial split.
 *  - `clearAllFormInputs()` renumbered a `ranking` between instances but left
 *    the rows in the previous instance's order, so an item with no ranking
 *    opened showing the last item's answer as its default.
 *
 * These run the functions that ship, pulled out of the source.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'annotation.js');

/** Pull one top-level function out of a script that cannot be imported. */
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

let src;
beforeAll(() => { src = fs.readFileSync(SOURCE, 'utf8'); });

describe('budgetShortfall() — the total a budget schema declares', () => {
    let budgetShortfall;
    beforeAll(() => {
        budgetShortfall = new Function(
            `${extractFunction(src, 'budgetShortfall')}; return budgetShortfall;`)();
    });

    /** A constant_sum form as the generator renders it. */
    function constantSum(total, values) {
        const form = document.createElement('form');
        form.setAttribute('data-constant-sum-total', String(total));
        values.forEach(v => {
            const input = document.createElement('input');
            input.type = 'number';
            input.className = 'constant-sum-number annotation-input';
            input.value = v;
            form.appendChild(input);
        });
        return form;
    }

    test('a full allocation is no shortfall', () => {
        expect(budgetShortfall(constantSum(100, ['25', '25', '25', '25']))).toBeNull();
    });

    test('the under-allocation the widget displayed but did not enforce', () => {
        // "Allocated: 40 / 100 · Remaining: 60", and Next used to advance.
        expect(budgetShortfall(constantSum(100, ['10', '10', '10', '10'])))
            .toEqual({sum: 40, total: 100});
    });

    test('an empty box counts as zero rather than aborting the sum', () => {
        expect(budgetShortfall(constantSum(100, ['', '30', '30', '30'])))
            .toEqual({sum: 90, total: 100});
    });

    test('over-allocation is caught too', () => {
        // soft_label redistributes to hold its total, except where min_per_label
        // floors stop the other sliders absorbing the difference.
        const form = document.createElement('form');
        form.setAttribute('data-soft-label-total', '100');
        ['100', '30', '30'].forEach(v => {
            const s = document.createElement('input');
            s.type = 'range';
            s.className = 'soft-label-slider annotation-input';
            s.value = v;
            form.appendChild(s);
        });
        expect(budgetShortfall(form)).toEqual({sum: 160, total: 100});
    });

    test('a form that is not a budget schema is left alone', () => {
        const form = document.createElement('form');
        form.innerHTML = '<input type="text" class="annotation-input" value="hi">';
        expect(budgetShortfall(form)).toBeNull();
    });

    test('a budget form with no parts yet is not reported as short', () => {
        const form = document.createElement('form');
        form.setAttribute('data-constant-sum-total', '100');
        expect(budgetShortfall(form)).toBeNull();
    });

    test('a non-numeric total is ignored rather than treated as zero', () => {
        const form = constantSum(100, ['50']);
        form.setAttribute('data-constant-sum-total', 'lots');
        expect(budgetShortfall(form)).toBeNull();
    });
});

describe('the ranking rows go back to the config order between instances', () => {
    let clearRanking;

    /**
     * clearAllFormInputs() is long and touches globals this test has no use for.
     * Run only the ranking block, located by its marker comment.
     */
    beforeAll(() => {
        const whole = extractFunction(src, 'clearAllFormInputs');
        const start = whole.indexOf('    // Clear ranking visual state');
        const end = whole.indexOf('    // Clear hierarchical multiselect checkboxes');
        expect(start).toBeGreaterThan(-1);
        expect(end).toBeGreaterThan(start);
        clearRanking = new Function(whole.slice(start, end));
    });

    function page({order, placeholder, serverSet}) {
        document.body.innerHTML = `
          <fieldset>
            <input type="hidden" class="annotation-input ranking-order-input"
                   value="" data-placeholder-order="${placeholder}"
                   ${serverSet ? 'data-server-set="true"' : ''}>
            <div class="ranking-list">
              ${order.map((v, i) => `
                <div class="ranking-item" data-value="${v}">
                  <span class="ranking-rank">${i + 1}</span>
                </div>`).join('')}
            </div>
          </fieldset>`;
    }

    const rows = () => [...document.querySelectorAll('.ranking-item')]
        .map(i => i.getAttribute('data-value'));
    const ranks = () => [...document.querySelectorAll('.ranking-rank')]
        .map(r => r.textContent);

    test("the previous instance's order does not become the next one's default", () => {
        page({order: ['a', 'c', 'b'], placeholder: 'a,b,c'});
        clearRanking();
        expect(rows()).toEqual(['a', 'b', 'c']);
    });

    test('the numbers follow the rows', () => {
        page({order: ['c', 'b', 'a'], placeholder: 'a,b,c'});
        clearRanking();
        expect(ranks()).toEqual(['1', '2', '3']);
    });

    test('a server-restored ranking is left where the server put it', () => {
        page({order: ['a', 'c', 'b'], placeholder: 'a,b,c', serverSet: true});
        clearRanking();
        expect(rows()).toEqual(['a', 'c', 'b']);
    });

    test('a label the placeholder does not name is not dropped', () => {
        page({order: ['a', 'b', 'z'], placeholder: 'a,b'});
        clearRanking();
        expect(rows()).toHaveLength(3);
        expect(rows()).toContain('z');
    });
});

describe('a select reports what the server rendered, not what Chrome kept', () => {
    /**
     * The select block of loadAnnotations(), which is async and reaches for
     * globals. Extracted by its marker comment and run against a local
     * currentAnnotations.
     */
    let syncSelects;
    beforeAll(() => {
        const whole = extractFunction(src, 'loadAnnotations');
        const start = whole.indexOf('        // Read select dropdown state');
        const end = whole.indexOf('        // Read hidden input state');
        expect(start).toBeGreaterThan(-1);
        expect(end).toBeGreaterThan(start);
        syncSelects = new Function('currentAnnotations', whole.slice(start, end));
    });

    function select({options, serverSelected, browserValue}) {
        document.body.innerHTML = `
          <select class="annotation-input" schema="frame" label_name="select-one">
            <option value="" ${serverSelected === '' ? 'selected' : ''} disabled>-- select one --</option>
            ${options.map(o => `<option value="${o}" ${serverSelected === o ? 'selected' : ''}>${o}</option>`).join('')}
          </select>`;
        const el = document.querySelector('select');
        if (browserValue !== undefined) el.value = browserValue;  // what Chrome restored
        return el;
    }

    test('a restored answer is adopted', () => {
        const el = select({options: ['a', 'b'], serverSelected: 'b'});
        const annotations = {};
        syncSelects(annotations);
        expect(el.value).toBe('b');
        expect(annotations.frame['select-one']).toBe('b');
    });

    test("a fresh instance drops the previous instance's selection", () => {
        // No server selection; the browser has carried 'a' across the navigation.
        const el = select({options: ['a', 'b'], serverSelected: '', browserValue: 'a'});
        const annotations = {};
        syncSelects(annotations);
        expect(el.value).toBe('');
        expect(annotations.frame).toBeUndefined();
    });

    test('the placeholder is what a cleared select lands on', () => {
        const el = select({options: ['a', 'b'], serverSelected: '', browserValue: 'b'});
        syncSelects({});
        expect(el.selectedIndex).toBe(0);
        expect(el.options[0].value).toBe('');
    });
});

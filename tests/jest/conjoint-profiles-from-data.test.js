/**
 * A conjoint fed profiles from the data has to render them.
 *
 * `conjoint.py` accepts `attributes` OR `profiles_field`, but only emits
 * attribute rows for entries in `attributes`. A config that used
 * `profiles_field` -- the whole point of which is that the profiles live in the
 * data -- therefore had no `.conjoint-attr-value` cells for populateConjoint to
 * fill, and rendered three blank cards with a radio under each. The annotator
 * was asked to choose between nothing, `validate --strict` said OK, and the
 * server logged nothing.
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

let buildRows;
beforeAll(() => {
    const src = fs.readFileSync(SOURCE, 'utf8');
    buildRows = new Function(
        `${extractFunction(src, 'buildConjointRowsFromData')}; return buildConjointRowsFromData;`)();
});

function cards(n) {
    document.body.innerHTML = Array.from({length: n}, (_, i) => `
        <div class="conjoint-profile-card" data-profile="${i + 1}">
          <table class="conjoint-profile-table"><tbody></tbody></table>
        </div>`).join('');
    return document.querySelectorAll('.conjoint-profile-card');
}

const namesIn = card => [...card.querySelectorAll('.conjoint-attr-name')].map(c => c.textContent);

describe('rows built from the profiles own keys', () => {
    const PROFILES = [
        {Hosting: 'Self-hosted', Cost: 'Free'},
        {Hosting: 'Cloud', Cost: '$20/mo'},
        {Hosting: 'Cloud', Cost: 'Free'},
    ];

    test('every card gets a cell per attribute', () => {
        const cs = cards(3);
        buildRows(cs, PROFILES);
        expect(document.querySelectorAll('.conjoint-attr-value').length).toBe(6);
    });

    test('the cells carry the data-attr populateConjoint looks up', () => {
        const cs = cards(3);
        buildRows(cs, PROFILES);
        expect(cs[0].querySelector('.conjoint-attr-value[data-attr="Hosting"]')).not.toBeNull();
        expect(cs[2].querySelector('.conjoint-attr-value[data-attr="Cost"]')).not.toBeNull();
    });

    test('the rows line up across cards when a profile omits a key', () => {
        // Otherwise the rows below shift up and the annotator silently compares
        // Cost against Support.
        const cs = cards(3);
        buildRows(cs, [
            {Hosting: 'Self-hosted', Cost: 'Free'},
            {Hosting: 'Cloud', Support: 'Email'},
            {Cost: '$20/mo'},
        ]);
        expect(namesIn(cs[0])).toEqual(['Hosting', 'Cost', 'Support']);
        expect(namesIn(cs[1])).toEqual(namesIn(cs[0]));
        expect(namesIn(cs[2])).toEqual(namesIn(cs[0]));
    });

    test('a missing value shows as an em dash, not a gap', () => {
        const cs = cards(2);
        buildRows(cs, [{Hosting: 'Cloud'}, {Cost: 'Free'}]);
        const cell = cs[0].querySelector('.conjoint-attr-value[data-attr="Cost"]');
        expect(cell.textContent).toBe('—');
    });

    test('attribute names are set as text, not parsed as markup', () => {
        const cs = cards(1);
        buildRows(cs, [{'<img src=x onerror=alert(1)>': 'v'}]);
        expect(cs[0].querySelectorAll('img').length).toBe(0);
        expect(namesIn(cs[0])[0]).toBe('<img src=x onerror=alert(1)>');
    });

    test('profiles with no keys leave the table alone', () => {
        const cs = cards(2);
        buildRows(cs, [{}, {}]);
        expect(document.querySelectorAll('.conjoint-attr-row').length).toBe(0);
    });

    test('a non-object entry in the array does not throw', () => {
        const cs = cards(2);
        expect(() => buildRows(cs, [null, {Cost: 'Free'}])).not.toThrow();
        expect(namesIn(cs[0])).toEqual(['Cost']);
    });
});

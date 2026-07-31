/**
 * Answer collapse — JavaScript half of the Python/JS parity pair.
 *
 * The Python half is tests/unit/test_answer_collapse.py. Both drive
 * tests/data/answer_collapse_cases.json. If they disagree, a conditional question can
 * be shown in the browser while the export treats it as hidden — which silently drops
 * the answer from the exported data. That divergence is exactly what this pair exists
 * to prevent, so add new cases to the shared JSON rather than to either file.
 */

const fs = require('fs');
const path = require('path');

const { DisplayLogicManager } = require('../../potato/static/display-logic.js');

const CASES = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', 'data', 'answer_collapse_cases.json'), 'utf8')
).cases;

describe('collapseEntries — shared parity cases', () => {
    CASES.forEach(testCase => {
        test(testCase.name, () => {
            const result = DisplayLogicManager.collapseEntries(
                testCase.entries, testCase.annotation_type);
            // Python omits a schema when there is nothing to compare; JS returns null.
            const normalized = result === undefined ? null : result;
            expect(normalized).toEqual(testCase.expected);
        });
    });
});

describe('isSelected', () => {
    test.each([[true], [1], ['true'], ['TRUE']])('%p counts as selected', value => {
        expect(DisplayLogicManager.isSelected('Yes', value)).toBe(true);
    });

    test('a value echoing its own label counts as selected', () => {
        // The shape the current frontend writes for radio and multiselect.
        expect(DisplayLogicManager.isSelected('en', 'en')).toBe(true);
    });

    test.each([[false], [0], [''], ['false'], [null]])('%p is not selected', value => {
        expect(DisplayLogicManager.isSelected('Yes', value)).toBe(false);
    });

    test('unrelated typed text is not a selection', () => {
        expect(DisplayLogicManager.isSelected('Yes', 'some typed text')).toBe(false);
    });
});

describe('exempt labels', () => {
    test('free_response is the only exemption, matching Python', () => {
        expect([...DisplayLogicManager.EXEMPT_LABELS]).toEqual(['free_response']);
    });
});

describe('transformRawAnnotations', () => {
    let manager;

    beforeEach(() => {
        manager = new DisplayLogicManager();
        // No DOM schemas in this environment; hints come from the argument.
        manager.getSchemaTypeHints = () => ({});
    });

    test('collapses the nested {schema: {label: value}} shape', () => {
        const raw = { langs: { en: 'en', fr: 'fr' }, q: { Yes: 'Yes' } };
        expect(manager.transformRawAnnotations(raw, { langs: 'multiselect', q: 'radio' }))
            .toEqual({ langs: ['en', 'fr'], q: 'Yes' });
    });

    test('omits schemas with nothing to compare', () => {
        const raw = { blank: { text_box: '' } };
        expect(manager.transformRawAnnotations(raw, { blank: 'text' })).toEqual({});
    });

    test('passes a already-scalar schema value straight through', () => {
        expect(manager.transformRawAnnotations({ q: 'Yes' }, {})).toEqual({ q: 'Yes' });
    });

    test('tolerates null and non-object input', () => {
        expect(manager.transformRawAnnotations(null, {})).toEqual({});
        expect(manager.transformRawAnnotations('nonsense', {})).toEqual({});
    });
});

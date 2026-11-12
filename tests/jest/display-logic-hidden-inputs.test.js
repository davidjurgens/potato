/**
 * getAnnotationsFromDOM must see hidden inputs.
 *
 * The tile-based widgets — pairwise, bws, ranking, triage, and the rest of the
 * `data-schema=` family — put their answer in an
 * `input[type=hidden].annotation-input`. The DOM collector read six selectors,
 * none of which matched one, so a display_logic gate naming one of those
 * schemas saw no answer at all on any page that reaches this fallback (phase
 * pages, where annotation.js's currentAnnotations does not exist).
 *
 * The data-modified / data-server-set guard is not optional: browsers restore a
 * hidden input's .value across a reload, so an untouched input can be holding
 * the previous instance's answer.
 */

const { DisplayLogicManager } = require('../../potato/static/display-logic.js');

function hiddenInput({schema, label, value, touched}) {
    const input = document.createElement('input');
    input.type = 'hidden';
    input.className = 'annotation-input pairwise-value';
    input.setAttribute('schema', schema);
    input.setAttribute('label_name', label);
    input.value = value;
    if (touched) input.setAttribute('data-modified', 'true');
    document.body.appendChild(input);
    return input;
}

describe('getAnnotationsFromDOM — hidden inputs', () => {
    let manager;

    beforeEach(() => {
        document.body.innerHTML = '';
        manager = new DisplayLogicManager();
    });

    test('a touched hidden input is collected', () => {
        hiddenInput({schema: 'which_better', label: 'selection', value: 'A', touched: true});

        expect(manager.getAnnotationsFromDOM()).toEqual({which_better: 'A'});
    });

    test('a server-restored hidden input is collected', () => {
        const input = hiddenInput(
            {schema: 'which_better', label: 'selection', value: 'B', touched: false});
        input.setAttribute('data-server-set', 'true');

        expect(manager.getAnnotationsFromDOM()).toEqual({which_better: 'B'});
    });

    test('an untouched hidden input is ignored', () => {
        // Browser-restored form state, not an answer this instance has.
        hiddenInput({schema: 'which_better', label: 'selection', value: 'A', touched: false});

        expect(manager.getAnnotationsFromDOM()).toEqual({});
    });

    test('an empty hidden input is ignored', () => {
        hiddenInput({schema: 'which_better', label: 'selection', value: '', touched: true});

        expect(manager.getAnnotationsFromDOM()).toEqual({});
    });

    test('a two-label widget keeps both labels', () => {
        // bws writes best and worst under one schema.
        hiddenInput({schema: 'bws', label: 'best', value: 'item_2', touched: true});
        hiddenInput({schema: 'bws', label: 'worst', value: 'item_4', touched: true});

        // Neither label echoes its value, so the collapse falls through to the
        // last scalar rather than inventing a selection.
        expect(manager.getAnnotationsFromDOM()).toEqual({bws: 'item_4'});
    });

    test('hidden inputs do not displace the other widget types', () => {
        hiddenInput({schema: 'which_better', label: 'selection', value: 'A', touched: true});

        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.className = 'annotation-input';
        radio.setAttribute('schema', 'confidence');
        radio.setAttribute('label_name', 'high');
        radio.checked = true;
        document.body.appendChild(radio);

        expect(manager.getAnnotationsFromDOM())
            .toEqual({which_better: 'A', confidence: 'high'});
    });
});

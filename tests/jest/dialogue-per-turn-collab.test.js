/**
 * Live sessions: per-turn ratings on a dialogue display show a teammate's
 * ratings without a reload (instance-display.js).
 *
 * A per-turn rating scheme is not an annotation scheme: it has no form, no
 * element with its name as id, and no data-annotation-type, so collab.js's
 * type registry cannot find it. Its save key ends in `:::_data`, though, and
 * collab.js then asks `window.potatoCollabAppliers[schema]`, after writing
 * the value into `input.annotation-data-input[name=schema]`, which is this
 * display's hidden input. That is the hook instance-display.js registers.
 *
 * Markup is DialogueDisplay.render()'s own output.
 */

const { loadStatic, bootCollab, applyTeam, watchSaves, countChanges } = require('./misc-collab-harness');

const DIALOGUE = `
        <div class="dialogue-display-content has-per-turn-ratings" data-field-key="conv">
            <div class="dialogue-turn turn-even speaker-0" data-speaker-index="0"><span class="dialogue-speaker" data-speaker="User">User:</span> <span class="dialogue-text"  >hi</span></div>
<div class="dialogue-turn turn-odd speaker-1" data-speaker-index="1"><span class="dialogue-speaker" data-speaker="Agent">Agent:</span> <span class="dialogue-text"  >hello</span><div class="per-turn-rating" data-field="conv" data-turn="1" data-schema="turn_quality">
            <span class="ptr-schema-label">Turn Quality:</span>
            <span class="ptr-label ptr-min">Poor</span>
            <div class="ptr-values" role="radiogroup" aria-label="Turn Quality, turn 2"><span class="ptr-value" role="radio" aria-checked="false" tabindex="0" aria-label="1 of 3, Poor" data-field="conv" data-turn="1" data-value="1" data-schema="turn_quality" title="1">1</span>
<span class="ptr-value" role="radio" aria-checked="false" tabindex="-1" aria-label="2 of 3" data-field="conv" data-turn="1" data-value="2" data-schema="turn_quality" title="2">2</span>
<span class="ptr-value" role="radio" aria-checked="false" tabindex="-1" aria-label="3 of 3, Good" data-field="conv" data-turn="1" data-value="3" data-schema="turn_quality" title="3">3</span></div>
            <span class="ptr-label ptr-max">Good</span>
        </div></div>
<div class="dialogue-turn turn-even speaker-1" data-speaker-index="1"><span class="dialogue-speaker" data-speaker="Agent">Agent:</span> <span class="dialogue-text"  >bye</span><div class="per-turn-rating" data-field="conv" data-turn="2" data-schema="turn_quality">
            <span class="ptr-schema-label">Turn Quality:</span>
            <span class="ptr-label ptr-min">Poor</span>
            <div class="ptr-values" role="radiogroup" aria-label="Turn Quality, turn 3"><span class="ptr-value" role="radio" aria-checked="false" tabindex="0" aria-label="1 of 3, Poor" data-field="conv" data-turn="2" data-value="1" data-schema="turn_quality" title="1">1</span>
<span class="ptr-value" role="radio" aria-checked="false" tabindex="-1" aria-label="2 of 3" data-field="conv" data-turn="2" data-value="2" data-schema="turn_quality" title="2">2</span>
<span class="ptr-value" role="radio" aria-checked="false" tabindex="-1" aria-label="3 of 3, Good" data-field="conv" data-turn="2" data-value="3" data-schema="turn_quality" title="3">3</span></div>
            <span class="ptr-label ptr-max">Good</span>
        </div></div>
            <input type="hidden" class="annotation-data-input per-turn-hidden" name="turn_quality" id="per-turn-ratings-conv-turn_quality" data-schema-name="turn_quality" value="" />
        </div>
        `;

let client, calls;

function boot(stored) {
    document.body.innerHTML = '<input type="hidden" id="instance_id" value="item-1">'
        + '<div class="instance-display-container"><div class="display-field" data-field-key="conv">'
        + DIALOGUE + '</div></div>';
    if (stored) {
        const h = document.getElementById('per-turn-ratings-conv-turn_quality');
        h.value = stored;
        h.setAttribute('value', stored);
        h.setAttribute('data-server-set', 'true');
    }
    delete window.potatoCollabAppliers;
    delete window.instanceDisplayManager;
    loadStatic('instance-display.js');
    ({ client, calls } = bootCollab());
}

// What a rater sees: the chosen value per rated turn, '-' for none.
const ratings = () => ['1', '2'].map((turn) => {
    const on = document.querySelector(`.ptr-value[data-turn="${turn}"][aria-checked="true"]`);
    return on ? on.dataset.value : '-';
});
const filled = (turn) => document.querySelectorAll(`.ptr-value[data-turn="${turn}"].ptr-selected`).length;

describe('per-turn ratings live applier', () => {
    test('collab.js finds no scheme form for the rating schema', () => {
        boot('');
        expect(document.querySelector('form[data-schema-name="turn_quality"]')).toBeNull();
        expect(document.getElementById('turn_quality')).toBeNull();
    });

    test("a teammate's ratings replace the ones shown", () => {
        boot('{"1": 3}');
        expect(ratings()).toEqual(['3', '-']);
        const shown = applyTeam(client, 'turn_quality', { _data: '{"2": 2}' });
        expect(shown.has('L:turn_quality:::_data')).toBe(true);
        expect(ratings()).toEqual(['-', '2']);
        expect(filled('1')).toBe(0);
        expect(filled('2')).toBe(2);
    });

    test('no answer clears every turn', () => {
        boot('{"1": 3, "2": 1}');
        const shown = applyTeam(client, 'turn_quality', null, ['_data']);
        expect(shown.has('L:turn_quality:::_data')).toBe(true);
        expect(ratings()).toEqual(['-', '-']);
        expect(document.querySelectorAll('.ptr-selected')).toHaveLength(0);
    });

    test('applying saves nothing; twice, one click is one rating', () => {
        boot('{"1": 1}');
        const watch = watchSaves(calls);
        const input = document.getElementById('per-turn-ratings-conv-turn_quality');
        const changes = countChanges(input);
        applyTeam(client, 'turn_quality', { _data: '{"1": 2}' });
        applyTeam(client, 'turn_quality', { _data: '{"1": 2}' });
        expect(ratings()).toEqual(['2', '-']);
        expect(changes.n).toBe(0);
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
        // The page's own click still works once, on the teammate's ratings.
        document.querySelector('.ptr-value[data-turn="2"][data-value="3"]').click();
        expect(JSON.parse(input.value)).toEqual({ 1: 2, 2: 3 });
        expect(ratings()).toEqual(['2', '3']);
    });
});

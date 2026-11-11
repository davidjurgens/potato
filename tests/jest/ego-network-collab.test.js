/**
 * Live sessions: ego_network shows a teammate's network without a reload
 * (ego-network.js registers the applier), and two browsers adding a person
 * at once make two different alter ids.
 *
 * Markup is ego_network.py's own output for a three-stage, stacked scheme.
 */

const { loadStatic, bootCollab, applyTeam, watchSaves, countChanges } = require('./misc-collab-harness');

const MARKUP = `
    <form id="net" class="annotation-form ego-network" action="javascript:void(0)"
          data-annotation-type="ego_network" data-schema-name="net"
          data-ego-config='{&quot;schema&quot;: &quot;net&quot;, &quot;layout&quot;: &quot;stacked&quot;, &quot;stages&quot;: [{&quot;type&quot;: &quot;name_generator&quot;, &quot;id&quot;: &quot;mentioned&quot;, &quot;title&quot;: &quot;People&quot;, &quot;prompt&quot;: &quot;Add&quot;, &quot;min_alters&quot;: 0}, {&quot;type&quot;: &quot;name_interpreter&quot;, &quot;id&quot;: &quot;role&quot;, &quot;title&quot;: &quot;About each person&quot;, &quot;prompt&quot;: &quot;Answer these questions about each person you named.&quot;, &quot;questions&quot;: [{&quot;name&quot;: &quot;role&quot;, &quot;type&quot;: &quot;radio&quot;, &quot;description&quot;: &quot;{name}&quot;, &quot;required&quot;: false, &quot;labels&quot;: [{&quot;name&quot;: &quot;family&quot;, &quot;text&quot;: &quot;family&quot;}, {&quot;name&quot;: &quot;friend&quot;, &quot;text&quot;: &quot;friend&quot;}]}]}, {&quot;type&quot;: &quot;dyad_census&quot;, &quot;id&quot;: &quot;ties&quot;, &quot;title&quot;: &quot;Who knows whom&quot;, &quot;prompt&quot;: &quot;Do {a} and {b} know each other?&quot;, &quot;yes_label&quot;: &quot;Yes&quot;, &quot;no_label&quot;: &quot;No&quot;}]}' data-grid-columns="1">
        <fieldset schema="net">
            <legend class="en-title">Net</legend>
            <div class="en-root">
                <p class="en-loading" role="status">Loading…</p>
            </div>
            <input type="hidden" class="annotation-input ego-network-input"
                   id="net_net_hidden" name="net:::net"
                   schema="net" label_name="net"
                   validation="" value="">
        </fieldset>
    </form>
    `;

const answer = (people, ties) => JSON.stringify({
    alters: people.map(([id, name]) => ({ id, name, named_in: ['mentioned'] })),
    attributes: {}, ties: ties || [], positions: {}, census: {}, tie_attributes: {},
});

let client, calls;

function page(stored) {
    document.body.innerHTML = '<input type="hidden" id="instance_id" value="item-1">' + MARKUP;
    if (stored) {
        const h = document.getElementById('net_net_hidden');
        h.value = stored;
        h.setAttribute('data-server-set', 'true');
    }
}

function boot(stored) {
    page(stored);
    delete window.PotatoEgoNetwork;
    delete window.potatoCollabWidgets;
    loadStatic('ego-network.js');
    ({ client, calls } = bootCollab());
}

const names = () => Array.from(document.querySelectorAll('.en-stage-name_generator .en-chip-name'))
    .map((n) => n.textContent);
const stored = () => JSON.parse(document.getElementById('net_net_hidden').value || '{"alters":[]}');

function addPerson(name) {
    const input = document.querySelector('.en-name-input');
    input.value = name;
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
}

describe('ego_network live applier', () => {
    test('the page draws its own network first', () => {
        boot(answer([['a1', 'Ann'], ['a2', 'Bob']]));
        expect(names()).toEqual(['Ann', 'Bob']);
    });

    test("a teammate's network replaces the one shown", () => {
        boot(answer([['a1', 'Ann'], ['a2', 'Bob']]));
        const shown = applyTeam(client, 'net', { net: answer([['a1', 'Ann'], ['a3_x1y2z3', 'Cara']]) });
        expect(shown.has('L:net:::net')).toBe(true);
        expect(names()).toEqual(['Ann', 'Cara']);
        // The census redraws for the new pair too.
        expect(document.querySelector('.en-stage-dyad_census').textContent).toMatch(/Cara/);
        expect(document.querySelector('.en-stage-dyad_census').textContent).not.toMatch(/Bob/);
    });

    test('no answer clears every stage', () => {
        boot(answer([['a1', 'Ann'], ['a2', 'Bob']]));
        const shown = applyTeam(client, 'net', null, ['net']);
        expect(shown.has('L:net:::net')).toBe(true);
        expect(names()).toEqual([]);
        expect(document.querySelectorAll('.en-chip')).toHaveLength(0);
    });

    test('applying saves nothing, and twice draws each person once', () => {
        boot(answer([['a1', 'Ann']]));
        const watch = watchSaves(calls);
        const input = document.getElementById('net_net_hidden');
        const changes = countChanges(input);
        const team = answer([['a1', 'Ann'], ['a2', 'Bob']]);
        applyTeam(client, 'net', { net: team });
        applyTeam(client, 'net', { net: team });
        expect(names()).toEqual(['Ann', 'Bob']);
        expect(changes.n).toBe(0);
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(input.value).toBe(team);
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
        // One Enter adds one person: no listener was bound twice.
        addPerson('Dee');
        expect(changes.n).toBe(1);
        expect(stored().alters.map((a) => a.name)).toEqual(['Ann', 'Bob', 'Dee']);
    });
});

describe('alter ids', () => {
    function firstIdOnAFreshPage() {
        page('');
        delete window.PotatoEgoNetwork;
        loadStatic('ego-network.js');
        addPerson('Ann');
        return stored().alters[0].id;
    }

    test('two pages adding their first person make different ids', () => {
        const one = firstIdOnAFreshPage();
        const two = firstIdOnAFreshPage();
        expect(one).toMatch(/^a1_[0-9a-z]+$/);
        expect(two).toMatch(/^a1_[0-9a-z]+$/);
        expect(one).not.toBe(two);
    });

    test('a new id counts past restored ones, which keep their ids', () => {
        page(answer([['a3', 'Ann'], ['a5_k2x9q1', 'Bob']]));
        delete window.PotatoEgoNetwork;
        loadStatic('ego-network.js');
        addPerson('Cara');
        const ids = stored().alters.map((a) => a.id);
        expect(ids.slice(0, 2)).toEqual(['a3', 'a5_k2x9q1']);
        expect(ids[2]).toMatch(/^a6_[0-9a-z]+$/);
    });
});

/**
 * Coreference mention selection and chain persistence.
 *
 * The manager listened for `spanSelected` / `spanDeselected`, which nothing in
 * Potato dispatched. `selectedSpanIds` was never appended to, so Add to Chain,
 * Merge Chains and Remove Mention were disabled no matter how many mentions the
 * annotator drew, and New Chain did nothing. The scheme looked finished.
 *
 * Its `_save()` was the second half of the same problem: it assigned the hidden
 * input's value and stopped. That input carries neither the schema/label_name
 * attributes nor the `annotation-input` class syncAnnotationsFromDOM requires,
 * so a chain never reached the server and came back as "0 chains".
 */

require('../../potato/static/coreference-manager.js');

const CoreferenceManager = window.CoreferenceManager;

function setupPage(config) {
    document.body.innerHTML = `
        <input type="hidden" id="instance_id" value="doc_1">
        <div id="span-overlays">
          <div class="span-overlay-pure" data-annotation-id="mentions_PERSON_0_10"
               data-schema="mentions" data-label="PERSON">John Smith</div>
          <div class="span-overlay-pure" data-annotation-id="mentions_PERSON_52_54"
               data-schema="mentions" data-label="PERSON">he</div>
          <div class="span-overlay-pure" data-annotation-id="other_ORG_1_4"
               data-schema="other" data-label="ORG">Acme</div>
        </div>
        <div class="coreference-container" data-coref-config='${JSON.stringify(config)}'>
          <div id="${config.schemaName}_chain_list"></div>
          <span id="${config.schemaName}_chain_count"></span>
          <input type="hidden" id="${config.schemaName}_chain_data"
                 name="span_link:::${config.schemaName}" value="[]">
          <button id="${config.schemaName}_new_chain"></button>
          <button id="${config.schemaName}_add_to_chain"></button>
          <button id="${config.schemaName}_merge_chains"></button>
          <button id="${config.schemaName}_remove_mention"></button>
        </div>`;
    return document.querySelector('.coreference-container');
}

const CONFIG = {schemaName: 'chains', spanSchema: 'mentions', entityTypes: [], allowSingletons: true};

let fetchCalls;
let managers;

/** Track every manager a test builds so afterEach can detach it.
 *  Without this, each test's document-level click listener survives into the
 *  next one and a single click is translated into an event several times. */
function build(container) {
    const manager = new CoreferenceManager(container);
    managers.push(manager);
    return manager;
}

afterEach(() => {
    managers.forEach(m => m.destroy());
    managers = [];
});

beforeEach(() => {
    managers = [];
    fetchCalls = [];
    global.fetch = jest.fn((url, opts) => {
        fetchCalls.push({url, opts});
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({status: 'success', links: []}),
        });
    });
});

function click(el) {
    el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
}

describe('mention selection', () => {
    test('clicking a mention selects it', () => {
        const container = setupPage(CONFIG);
        const manager = build(container);

        click(document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]'));

        expect(manager.selectedSpanIds).toEqual(['mentions_PERSON_0_10']);
    });

    test('clicking it again deselects it', () => {
        const container = setupPage(CONFIG);
        const manager = build(container);
        const overlay = document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]');

        click(overlay);
        click(overlay);

        expect(manager.selectedSpanIds).toEqual([]);
    });

    test('a mention from another span schema is ignored', () => {
        const container = setupPage(CONFIG);
        const manager = build(container);

        click(document.querySelector('[data-annotation-id="other_ORG_1_4"]'));

        expect(manager.selectedSpanIds).toEqual([]);
    });

    test('overlays are made clickable — the stylesheet sets pointer-events: none', () => {
        const container = setupPage(CONFIG);
        build(container);

        const overlay = document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]');
        expect(overlay.style.pointerEvents).toBe('auto');
        expect(overlay.classList.contains('coref-selectable')).toBe(true);
    });

    test('span_link owns the click while its link mode is active', () => {
        const container = setupPage(CONFIG);
        const manager = build(container);
        document.body.classList.add('span-link-mode-active');

        click(document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]'));

        expect(manager.selectedSpanIds).toEqual([]);
        document.body.classList.remove('span-link-mode-active');
    });

    test('a dispatched spanSelected event still works', () => {
        // The events stay the seam, so the span layer can take this over.
        const container = setupPage(CONFIG);
        const manager = build(container);

        document.dispatchEvent(new CustomEvent('spanSelected', {
            detail: {spanId: 'mentions_PERSON_52_54', schema: 'mentions'},
        }));

        expect(manager.selectedSpanIds).toEqual(['mentions_PERSON_52_54']);
    });
});

describe('button states follow the selection', () => {
    test('nothing selected leaves the chain buttons disabled', () => {
        const container = setupPage(CONFIG);
        build(container);

        expect(document.getElementById('chains_new_chain').disabled).toBe(true);
        expect(document.getElementById('chains_remove_mention').disabled).toBe(true);
    });

    test('one selected mention enables New Chain and Remove Mention', () => {
        const container = setupPage(CONFIG);
        build(container);

        click(document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]'));

        expect(document.getElementById('chains_new_chain').disabled).toBe(false);
        expect(document.getElementById('chains_remove_mention').disabled).toBe(false);
    });
});

describe('selection outlines follow state, not the click', () => {
    test('a selected mention is outlined', () => {
        const container = setupPage(CONFIG);
        build(container);
        const overlay = document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]');

        click(overlay);

        expect(overlay.classList.contains('coref-selected')).toBe(true);
    });

    test('creating a chain clears the outlines with the selection', () => {
        // createChain() empties selectedSpanIds in code. A class toggled only at
        // the click stayed behind, leaving mentions outlined as selected while
        // the buttons had already gone back to disabled.
        const container = setupPage(CONFIG);
        const manager = build(container);
        const overlay = document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]');

        click(overlay);
        manager.createChain();

        expect(manager.selectedSpanIds).toEqual([]);
        expect(overlay.classList.contains('coref-selected')).toBe(false);
    });
});

describe('chains reach the server', () => {
    test('creating a chain POSTs link_annotations to /updateinstance', () => {
        const container = setupPage(CONFIG);
        const manager = build(container);

        click(document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]'));
        click(document.querySelector('[data-annotation-id="mentions_PERSON_52_54"]'));
        manager.createChain();

        const post = fetchCalls.find(c => c.url === '/updateinstance');
        expect(post).toBeDefined();
        const body = JSON.parse(post.opts.body);
        expect(body.instance_id).toBe('doc_1');
        expect(body.link_annotations).toHaveLength(1);
        expect(body.link_annotations[0].span_ids)
            .toEqual(['mentions_PERSON_0_10', 'mentions_PERSON_52_54']);
    });

    test('the hidden input still carries the value for form submission', () => {
        const container = setupPage(CONFIG);
        const manager = build(container);

        click(document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]'));
        manager.createChain();

        const stored = JSON.parse(document.getElementById('chains_chain_data').value);
        expect(stored).toHaveLength(1);
        expect(stored[0].schema).toBe('chains');
    });

    test('deleting a chain DELETEs it rather than only dropping it locally', () => {
        const container = setupPage(CONFIG);
        const manager = build(container);

        click(document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]'));
        manager.createChain();
        const chainId = manager.chains[0].id;
        manager.deleteChain(chainId);

        expect(manager.chains).toHaveLength(0);
        const del = fetchCalls.find(c => c.opts && c.opts.method === 'DELETE');
        expect(del).toBeDefined();
        expect(del.url).toContain(chainId);
    });

    test('deleteChain removes the chain locally', () => {
        // _deleteChain(chainId) and the network helper must not share a name:
        // a class body's later definition wins, and the local removal was the
        // one that lost.
        const container = setupPage(CONFIG);
        const manager = build(container);

        click(document.querySelector('[data-annotation-id="mentions_PERSON_0_10"]'));
        manager.createChain();
        manager.deleteChain(manager.chains[0].id);

        expect(document.getElementById('chains_chain_count').textContent).toBe('0 chains');
    });
});

describe('chains come back', () => {
    test('stored links are loaded from /api/links', async () => {
        global.fetch = jest.fn((url) => Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                status: 'success',
                links: [{
                    id: 'chain_1', schema: 'chains', link_type: 'PERSON',
                    span_ids: ['mentions_PERSON_0_10', 'mentions_PERSON_52_54'],
                    direction: 'undirected', properties: {color: '#6E56CF'},
                }],
            }),
        }));

        const container = setupPage(CONFIG);
        const manager = build(container);
        await new Promise(r => setTimeout(r, 0));

        expect(manager.chains).toHaveLength(1);
        expect(manager.chains[0].spanIds).toHaveLength(2);
        expect(document.getElementById('chains_chain_count').textContent).toBe('1 chain');
    });

    test('a restored chain does not collide with the next new one', async () => {
        global.fetch = jest.fn(() => Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                status: 'success',
                links: [{id: 'chain_1', schema: 'chains', link_type: 'PERSON',
                         span_ids: ['mentions_PERSON_0_10']}],
            }),
        }));

        const container = setupPage(CONFIG);
        const manager = build(container);
        await new Promise(r => setTimeout(r, 0));

        click(document.querySelector('[data-annotation-id="mentions_PERSON_52_54"]'));
        manager.createChain();

        const ids = manager.chains.map(c => c.id);
        expect(new Set(ids).size).toBe(ids.length);
    });

    test('links belonging to another scheme are ignored', async () => {
        global.fetch = jest.fn(() => Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                status: 'success',
                links: [{id: 'l1', schema: 'some_other_links', link_type: 'X',
                         span_ids: ['mentions_PERSON_0_10']}],
            }),
        }));

        const container = setupPage(CONFIG);
        const manager = build(container);
        await new Promise(r => setTimeout(r, 0));

        expect(manager.chains).toHaveLength(0);
    });
});

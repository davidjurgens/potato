/**
 * Reloading links, coreference chains and events in place.
 *
 * A live session shows a teammate's change by asking each manager to load the
 * item's stored links or events again. Before these methods existed the
 * session client called managers that were not there (the globals are maps
 * per scheme), so the change waited for a page reload. A reload after the
 * last link, chain or event was removed elsewhere must also clear what the
 * page still draws, which the first-load paths never had to do.
 */

const fs = require('fs');
const path = require('path');

require('../../potato/static/coreference-manager.js');

function extract(file, names) {
    const src = fs.readFileSync(path.join(__dirname, '..', '..', 'potato', 'static', file), 'utf8');
    const bodies = names.map((name) => {
        const re = new RegExp(`\\n    (async )?${name}\\(`);
        const m = re.exec(src);
        if (!m) throw new Error(`${name}() not found in ${file}`);
        const start = m.index + 1;
        const open = src.indexOf('{', start);
        let depth = 0;
        for (let j = open; j < src.length; j++) {
            if (src[j] === '{') depth++;
            else if (src[j] === '}') {
                depth--;
                if (depth === 0) return src.slice(start, j + 1);
            }
        }
        throw new Error(`unbalanced ${name}()`);
    });
    // eslint-disable-next-line no-new-func
    return new Function(`return {${bodies.join(',')}};`)();
}

function respondWith(body) {
    global.fetch = jest.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) }));
}

const settle = () => new Promise((r) => setTimeout(r, 0));

describe('coreference chains', () => {
    function page() {
        document.body.innerHTML = `
            <input type="hidden" id="instance_id" value="doc_1">
            <div class="coref-container" data-coref-config='${JSON.stringify(
                { schemaName: 'chains', spanSchema: 'mentions', entityTypes: [], allowSingletons: true })}'>
              <div id="chains_chain_list"></div><span id="chains_chain_count"></span>
              <input type="hidden" id="chains_chain_data" name="span_link:::chains" value="[]">
              <button id="chains_new_chain"></button><button id="chains_add_to_chain"></button>
              <button id="chains_merge_chains"></button><button id="chains_remove_mention"></button>
            </div>`;
        return document.querySelector('.coref-container');
    }
    let manager;
    afterEach(() => manager && manager.destroy());

    test("a teammate's chain appears", async () => {
        respondWith({ links: [] });
        manager = new window.CoreferenceManager(page());
        await settle();
        respondWith({ links: [{ id: 'chain_x', schema: 'chains', span_ids: ['a', 'b'], link_type: '' }] });
        manager.reload();
        await settle();
        expect(manager.chains.map((c) => c.id)).toEqual(['chain_x']);
    });

    test('removing the last chain elsewhere clears it here', async () => {
        respondWith({ links: [{ id: 'chain_x', schema: 'chains', span_ids: ['a', 'b'] }] });
        manager = new window.CoreferenceManager(page());
        await settle();
        expect(manager.chains).toHaveLength(1);
        respondWith({ links: [] });
        manager.reload();
        await settle();
        expect(manager.chains).toEqual([]);
        expect(document.getElementById('chains_chain_data').value).toBe('[]');
        expect(document.getElementById('chains_chain_count').textContent).not.toContain('1');
    });

    test('two pages never make the same new chain id', async () => {
        // Each page numbers its chains from 1; two members in one session
        // would both store "chain_1", and the later save would replace the
        // earlier chain.
        respondWith({ links: [] });
        const ids = [];
        for (let i = 0; i < 2; i++) {
            const m = new window.CoreferenceManager(page());
            await settle();
            m.selectedSpanIds = ['a', 'b'];
            m.createChain();
            ids.push(m.chains[0].id);
            m.destroy();
        }
        expect(ids[0]).not.toBe(ids[1]);
        ids.forEach((id) => expect(id).toMatch(/^chain_[a-z0-9]+_1$/));
    });
});

describe('events', () => {
    function manager(events) {
        const m = Object.assign(extract('event-annotation.js', ['reload', 'loadExistingEvents']), {
            schemaName: 'ev', events, _loadedForInstance: 'doc_1', getInstanceId: () => 'doc_1',
            updateEventDataInput: jest.fn(), updateUI: jest.fn(), renderArcs: jest.fn(),
        });
        return m;
    }
    beforeEach(() => { window.currentInstanceId = 'doc_1'; jest.spyOn(console, 'log').mockImplementation(() => {}); });
    afterEach(() => { delete window.currentInstanceId; console.log.mockRestore(); });

    test('a reload fetches again although this item was loaded', async () => {
        respondWith({ events: [{ id: 'e1' }, { id: 'e2' }] });
        const m = manager([{ id: 'e1' }]);
        await m.reload();
        expect(global.fetch).toHaveBeenCalled();
        expect(m.events.map((e) => e.id)).toEqual(['e1', 'e2']);
        expect(m.renderArcs).toHaveBeenCalled();
    });

    test('a first load of an item already loaded is still skipped', async () => {
        respondWith({ events: [] });
        const m = manager([{ id: 'e1' }]);
        await m.loadExistingEvents();
        expect(global.fetch).not.toHaveBeenCalled();
    });

    test('removing the last event elsewhere clears it here', async () => {
        respondWith({ events: [] });
        const m = manager([{ id: 'e1' }]);
        await m.reload();
        expect(m.events).toEqual([]);
        expect(m.updateEventDataInput).toHaveBeenCalled();
        expect(m.renderArcs).toHaveBeenCalled();
    });
});

describe('span links', () => {
    test('removing the last link elsewhere clears the arcs', async () => {
        const m = Object.assign(extract('span-link-manager.js', ['reload']), {
            links: [{ id: 'l1' }],
            loadExistingLinks: jest.fn(async function () { this.links = []; }),
            renderArcs: jest.fn(),
        });
        await m.reload();
        expect(m.renderArcs).toHaveBeenCalled();
    });

    test('a reload that brings links draws them through the loader', async () => {
        const m = Object.assign(extract('span-link-manager.js', ['reload']), {
            links: [],
            loadExistingLinks: jest.fn(async function () { this.links = [{ id: 'l2' }]; }),
            renderArcs: jest.fn(),
        });
        await m.reload();
        expect(m.loadExistingLinks).toHaveBeenCalled();
        expect(m.renderArcs).not.toHaveBeenCalled();
    });
});

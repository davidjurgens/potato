/**
 * Spans look and read the same whether they were drawn on load or client-side.
 *
 * The server used to wrap every stored span inline in a padded, coloured
 * `.span-highlight`, and span-core.js drew its overlays on top. Only a
 * reloaded page had the wrappers; a span made by the annotator, or a
 * teammate's span applied live, had only the overlay. The text sat further
 * right per preceding span after a reload, link and event arcs moved, and
 * every consumer that read the wrappers worked on a reload and failed live:
 *
 * - coreference named its mentions from the wrapper text, so the chain list
 *   read "John Smith, He" after a reload and "(span sw_m1), (span sw_m2)" live;
 * - span_link's list named the spans from the wrappers when the overlays were
 *   not drawn yet, and said "unknown" without them;
 * - event arcs found the wrappers before the overlays existed, and without
 *   them were drawn against nothing and never again;
 * - the entity-link tooltip listened only on the wrappers.
 *
 * The server no longer wraps; these cover each consumer without the wrappers.
 */

const fs = require('fs');
const path = require('path');

const STATIC = path.join(__dirname, '..', '..', 'potato', 'static');

/** A class declared at the top level of a page script. */
function loadClass(file, name) {
    const src = fs.readFileSync(path.join(STATIC, file), 'utf8');
    // eslint-disable-next-line no-new-func
    return new Function(`${src}\nreturn ${name};`)();
}

const settle = () => new Promise((r) => setTimeout(r, 0));

function spansRendered() {
    document.dispatchEvent(new CustomEvent('potato:spansRendered', {detail: {}}));
}

function respondWith(byUrl) {
    global.fetch = jest.fn((url) => {
        const key = Object.keys(byUrl).find((k) => String(url).startsWith(k));
        const body = key ? byUrl[key] : {};
        return Promise.resolve({
            ok: true, status: 200,
            json: () => Promise.resolve(body),
            text: () => Promise.resolve(JSON.stringify(body)),
        });
    });
}

afterEach(() => {
    delete window.spanManager;
    document.body.innerHTML = '';
});

describe('coreference names its mentions without the server wrappers', () => {
    require('../../potato/static/coreference-manager.js');
    const CoreferenceManager = window.CoreferenceManager;

    const CHAIN = {
        id: 'chain_1', schema: 'chains', link_type: 'PERSON',
        span_ids: ['sw_m1', 'sw_m2'], direction: 'undirected',
        properties: {color: '#3b82f6'},
    };

    function page() {
        document.body.innerHTML = `
            <input type="hidden" id="instance_id" value="coref_001">
            <div id="span-overlays"></div>
            <div class="coref-container" data-coref-config='${JSON.stringify(
                {schemaName: 'chains', spanSchema: 'mentions', entityTypes: ['PERSON'],
                 allowSingletons: true})}'>
              <div id="chains_chain_list"></div><span id="chains_chain_count"></span>
              <input type="hidden" id="chains_chain_data" name="span_link:::chains" value="[]">
              <button id="chains_new_chain"></button><button id="chains_add_to_chain"></button>
              <button id="chains_merge_chains"></button><button id="chains_remove_mention"></button>
            </div>`;
        return document.querySelector('.coref-container');
    }

    function mentions() {
        return Array.from(document.querySelectorAll('.coref-chain-mention-tag'))
            .map((el) => el.textContent);
    }

    let manager;
    afterEach(() => manager && manager.destroy());

    test('the chain list names mentions from the span manager, with no overlay drawn', async () => {
        window.spanManager = {getSpans: () => [
            {id: 'sw_m1', schema: 'mentions', label: 'PERSON', start: 0, end: 10, text: 'John Smith'},
            {id: 'sw_m2', schema: 'mentions', label: 'PERSON', start: 30, end: 32, text: 'He'},
        ]};
        respondWith({'/api/links/': {links: [CHAIN]}});

        manager = new CoreferenceManager(page());
        await settle();

        expect(mentions()).toEqual(['John Smith', 'He']);
    });

    test('a list drawn before the spans arrived is redrawn when they do', async () => {
        let spans = [];
        window.spanManager = {getSpans: () => spans};
        respondWith({'/api/links/': {links: [CHAIN]}});

        manager = new CoreferenceManager(page());
        await settle();
        expect(mentions()).toEqual(['(span sw_m1)', '(span sw_m2)']);

        spans = [
            {id: 'sw_m1', schema: 'mentions', label: 'PERSON', start: 0, end: 10, text: 'John Smith'},
            {id: 'sw_m2', schema: 'mentions', label: 'PERSON', start: 30, end: 32, text: 'He'},
        ];
        spansRendered();

        expect(mentions()).toEqual(['John Smith', 'He']);
    });

    test('a mention overlay drawn after the chains still gets its chain colour', async () => {
        window.spanManager = {getSpans: () => []};
        respondWith({'/api/links/': {links: [CHAIN]}});

        manager = new CoreferenceManager(page());
        await settle();

        // span-core draws the overlays, then announces it.
        document.getElementById('span-overlays').innerHTML = `
            <div class="span-overlay-pure" data-annotation-id="sw_m1" data-schema="mentions"
                 data-label="PERSON"><div class="span-highlight-segment"></div></div>`;
        spansRendered();

        const overlay = document.querySelector('[data-annotation-id="sw_m1"]');
        expect(overlay.classList.contains('coref-mention-highlight-background')).toBe(true);
        expect(overlay.style.getPropertyValue('--chain-color')).toBe('#3b82f6');
    });
});

describe('span_link names its spans without the server wrappers', () => {
    const SpanLinkManager = loadClass('span-link-manager.js', 'SpanLinkManager');
    // jsdom has no CSS.escape; the ids here need no escaping.
    beforeAll(() => {
        if (!global.CSS) global.CSS = {};
        if (!global.CSS.escape) global.CSS.escape = (s) => String(s);
    });

    function page() {
        document.body.innerHTML = `
            <input type="hidden" id="instance_id" value="item_1">
            <div id="instance-text"><div id="text-content">John Smith works for Google.</div>
              <div id="span-overlays"></div></div>
            <div id="relations" class="span-link-container" data-span-schema="entities"
                 data-show-arcs="false">
              <div id="relations_link_list"></div>
              <input type="hidden" id="relations_link_data" value="[]">
            </div>`;
    }

    function chips() {
        return Array.from(document.querySelectorAll('#relations_link_list .link-chip'))
            .map((el) => el.textContent.trim());
    }

    const LINK = {id: 'sw_link_1', schema: 'relations', link_type: 'WORKS_FOR',
                  span_ids: ['sw_p1', 'sw_o1'], direction: 'directed'};
    const SPANS = [
        {id: 'sw_p1', schema: 'entities', label: 'PERSON', start: 0, end: 10, text: 'John Smith'},
        {id: 'sw_o1', schema: 'entities', label: 'ORGANIZATION', start: 20, end: 26, text: 'Google'},
    ];

    test('a span with no overlay yet is named from the span manager', async () => {
        page();
        window.spanManager = {getSpans: () => SPANS};
        respondWith({'/api/links/': {links: [LINK]}});

        const manager = new SpanLinkManager('relations', 'entities');
        manager.waitForSpansAndRender = () => {};
        await settle();
        manager.updateLinkList();

        expect(chips()).toEqual(['PERSON', 'ORGANIZATION']);
    });

    test('a list drawn before the spans arrived is redrawn when they do', async () => {
        page();
        let spans = [];
        window.spanManager = {getSpans: () => spans};
        respondWith({'/api/links/': {links: [LINK]}});

        const manager = new SpanLinkManager('relations', 'entities');
        manager.waitForSpansAndRender = () => {};
        await settle();
        await settle();
        expect(chips()).toEqual(['unknown', 'unknown']);

        spans = SPANS;
        spansRendered();

        expect(chips()).toEqual(['PERSON', 'ORGANIZATION']);
    });
});

describe('event arcs are redrawn once the spans they anchor to exist', () => {
    const EventAnnotationManager = loadClass('event-annotation.js', 'EventAnnotationManager');

    test('the spans arriving after the events redraws the arcs', async () => {
        document.body.innerHTML = `
            <input type="hidden" id="instance_id" value="item_1">
            <div id="events" class="event-annotation-container" data-span-schema="entities"
                 data-show-arcs="false">
              <div id="events_event_list"></div>
              <input type="hidden" id="events_event_data" value="[]">
            </div>`;
        respondWith({'/api/events/': {events: [{
            id: 'ev1', schema: 'events', event_type: 'ATTACK', trigger_span_id: 'sw_e_t',
            arguments: [{role: 'attacker', span_id: 'sw_e_p', text: 'John Smith'}],
        }]}});

        const manager = new EventAnnotationManager('events', 'entities');
        await settle();
        await settle();
        expect(manager.events).toHaveLength(1);

        manager.renderArcsWhenReady = jest.fn();
        spansRendered();

        expect(manager.renderArcsWhenReady).toHaveBeenCalled();
    });
});

describe('span-core draws a span stored without a field', () => {
    const { SpanManager } = require('../../potato/static/span-core.js');
    const TEXT = 'John Smith went to the store. He bought some milk.';

    function page(fieldText) {
        document.body.innerHTML = `
            <input type="hidden" id="instance_id" value="coref_001">
            <div id="instance-text" style="display: none;">
              <div id="text-content" data-offset-basis="dom"
                   data-original-text="${TEXT}">${TEXT}</div>
            </div>
            <div class="display-field" data-span-target="true">
              <div id="text-content-text" class="text-content"
                   data-original-text="${fieldText}">${fieldText}</div>
              <div id="span-overlays-text" class="span-overlays-field"></div>
            </div>`;
    }

    function manager() {
        const m = new SpanManager();
        m.fieldStrategies = {text: {getCanonicalText: () =>
            document.getElementById('text-content-text').getAttribute('data-original-text')}};
        m.renderSpanOverlay = jest.fn();
        m.applyControlCompaction = () => {};
        m.annotations = {spans: [
            {id: 'sw_m1', schema: 'mentions', label: 'PERSON', start: 0, end: 10},
        ]};
        return m;
    }

    test('on the span-target field showing the item text', () => {
        page(TEXT);
        const m = manager();

        m.renderSpansNow();

        expect(m.renderSpanOverlay).toHaveBeenCalledTimes(1);
        const [, , , container] = m.renderSpanOverlay.mock.calls[0];
        expect(container.id).toBe('span-overlays-text');
    });

    test('never on a field showing other text: the offsets index the item text', () => {
        page('A different passage entirely.');
        const m = manager();

        m.renderSpansNow();

        expect(m.renderSpanOverlay).not.toHaveBeenCalled();
    });
});

describe('the entity-link tooltip shows on a span overlay', () => {
    test('hovering a linked overlay\'s label shows its knowledge-base entry', () => {
        document.body.innerHTML = `
            <form data-entity-linking='{"auto_search": false}' data-schema-name="ents"></form>
            <div id="span-overlays">
              <div class="span-overlay-pure has-entity-link" data-annotation-id="s1"
                   data-schema="ents" data-kb-id="Q42" data-kb-source="wikidata"
                   data-kb-label="Douglas Adams">
                <div class="span-highlight-segment"></div>
                <div class="span-controls"><div class="span-label">PER</div></div>
              </div>
            </div>`;
        jest.isolateModules(() => require('../../potato/static/entity-linking.js'));
        window.EntityLinking.init();

        document.querySelector('.span-label')
            .dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));

        const tooltip = document.getElementById('el-entity-tooltip');
        expect(tooltip).not.toBeNull();
        expect(tooltip.textContent).toContain('Q42');
        expect(tooltip.textContent).toContain('Douglas Adams');
    });
});

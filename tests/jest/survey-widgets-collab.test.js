/**
 * Live sessions: free_list, triad_test, listening_test and interlinear_gloss
 * show a teammate's answer without a reload. Each keeps its state in a
 * private WeakMap and its setup() does nothing for an instance it already
 * drew, so each registers an applier that replaces that state.
 *
 * Markup is each generator's own output; every test goes through collab.js.
 */

const { loadStatic, bootCollab, applyTeam, watchSaves, countChanges, flush } = require('./misc-collab-harness');

const FREE_LIST = `
    <form id="fl" class="annotation-form free-list" action="javascript:void(0)"
          data-annotation-type="free_list" data-schema-name="fl"
          data-free-list-config='{&quot;schema&quot;: &quot;fl&quot;, &quot;min_items&quot;: null, &quot;max_items&quot;: null, &quot;time_limit_s&quot;: null, &quot;allow_duplicates&quot;: false, &quot;placeholder&quot;: &quot;Type an item, then press Enter&quot;, &quot;max_length&quot;: 200}' data-grid-columns="1">
        <fieldset schema="fl">
            <legend class="fl-title">List</legend>
            
            <div class="fl-root" data-entry-id="fl-fl-entry">
                <p class="fl-loading" role="status">Loading…</p>
            </div>
            <input type="hidden" class="annotation-input free-list-input"
                   id="fl_fl_hidden" name="fl:::fl"
                   schema="fl" label_name="fl"
                   validation="" value="">
        </fieldset>
    </form>
    `;
const FREE_LIST_TIMED = `
    <form id="flt" class="annotation-form free-list" action="javascript:void(0)"
          data-annotation-type="free_list" data-schema-name="flt"
          data-free-list-config='{&quot;schema&quot;: &quot;flt&quot;, &quot;min_items&quot;: null, &quot;max_items&quot;: null, &quot;time_limit_s&quot;: 60, &quot;allow_duplicates&quot;: false, &quot;placeholder&quot;: &quot;Type an item, then press Enter&quot;, &quot;max_length&quot;: 200}' data-grid-columns="1">
        <fieldset schema="flt">
            <legend class="fl-title">List</legend>
            
            <div class="fl-root" data-entry-id="flt-fl-entry">
                <p class="fl-loading" role="status">Loading…</p>
            </div>
            <input type="hidden" class="annotation-input free-list-input"
                   id="flt_flt_hidden" name="flt:::flt"
                   schema="flt" label_name="flt"
                   validation="" value="">
        </fieldset>
    </form>
    `;
const TRIAD = `
    <form id="tt" class="annotation-form triad-test" action="javascript:void(0)"
          data-annotation-type="triad_test" data-schema-name="tt"
          data-triad-config='{&quot;schema&quot;: &quot;tt&quot;, &quot;labels&quot;: null, &quot;items_field&quot;: &quot;items&quot;, &quot;design&quot;: &quot;auto&quot;, &quot;max_triads&quot;: null, &quot;question&quot;: &quot;Which is most different?&quot;}' data-grid-columns="1">
        <fieldset schema="tt">
            <legend class="tt-title">Triad</legend>
            
            <div class="tt-root" tabindex="-1">
                <p class="tt-loading" role="status">Loading the triads…</p>
            </div>
            <input type="hidden" class="annotation-input triad-test-input"
                   id="tt_tt_hidden" name="tt:::tt"
                   schema="tt" label_name="tt"
                   validation="" value="">
        </fieldset>
    </form>
    `;
const LISTENING = `
    <form id="lt" class="annotation-form listening-test" action="javascript:void(0)"
          data-annotation-type="listening_test" data-schema-name="lt"
          data-listening-config='{&quot;schema&quot;: &quot;lt&quot;, &quot;method&quot;: &quot;mushra&quot;}' data-grid-columns="1">
        <fieldset schema="lt">
            <legend class="lt-title">Listen</legend>
            
            <div class="lt-root" tabindex="0" aria-label="Listening test controls">
                <p class="lt-loading" role="status">Loading audio…</p>
            </div>
            <input type="hidden" class="annotation-input listening-test-input"
                   id="lt_lt_hidden" name="lt:::lt"
                   schema="lt" label_name="lt"
                   validation="" value="">
        </fieldset>
    </form>
    `;
const GLOSS = `
    <form id="igt" class="annotation-form interlinear-gloss" action="javascript:void(0)"
          data-annotation-type="interlinear_gloss" data-schema-name="igt"
          data-igt-config='{&quot;schema&quot;: &quot;igt&quot;, &quot;sourceField&quot;: &quot;text&quot;, &quot;morphemesField&quot;: &quot;&quot;, &quot;glossField&quot;: &quot;&quot;, &quot;translationField&quot;: &quot;&quot;, &quot;tiers&quot;: [], &quot;abbreviations&quot;: null, &quot;language&quot;: &quot;&quot;, &quot;metalanguage&quot;: &quot;&quot;, &quot;translation&quot;: true}' data-grid-columns="1">
        <fieldset schema="igt">
            <legend class="igt-title">Gloss</legend>
            
            <div class="igt-root">
                <p class="igt-loading" role="status">Loading the words…</p>
            </div>
            <input type="hidden" class="annotation-input interlinear-gloss-input"
                   id="igt_igt_hidden" name="igt:::igt"
                   schema="igt" label_name="igt"
                   validation="" value="">
        </fieldset>
    </form>
    `;

let client, calls;

function page(html, hiddenId, stored) {
    document.body.innerHTML = '<input type="hidden" id="instance_id" value="item-1">' + html;
    if (stored) {
        const h = document.getElementById(hiddenId);
        h.value = stored;
        h.setAttribute('value', stored);
        h.setAttribute('data-server-set', 'true');
    }
}

function expectNoSave(watch, changes, input) {
    expect(changes.n).toBe(0);
    expect(input.hasAttribute('data-modified')).toBe(false);
    expect(watch.posts()).toHaveLength(0);
    expect(watch.saveAnnotations).not.toHaveBeenCalled();
}

// ---------------------------------------------------------------------------

describe('free_list', () => {
    const list = (items, extra) => JSON.stringify(Object.assign({
        items, timings_ms: items.map((_, i) => 1000 * (i + 1)), elapsed_ms: 1000 * items.length,
        time_up: false, started: true,
    }, extra || {}));
    const shownItems = () => Array.from(document.querySelectorAll('.fl-item-text')).map((n) => n.textContent);

    function boot(html, stored) {
        page(html, html === FREE_LIST ? 'fl_fl_hidden' : 'flt_flt_hidden', stored);
        delete window.PotatoFreeList;
        delete window.potatoCollabWidgets;
        loadStatic('free-list.js');
        ({ client, calls } = bootCollab());
    }

    test("a teammate's list replaces the one shown, keeping what is being typed", () => {
        boot(FREE_LIST, list(['dog', 'cat']));
        expect(shownItems()).toEqual(['dog', 'cat']);
        document.querySelector('.fl-entry').value = 'hor';
        const shown = applyTeam(client, 'fl', { fl: list(['owl', 'emu', 'yak']) });
        expect(shown.has('L:fl:::fl')).toBe(true);
        expect(shownItems()).toEqual(['owl', 'emu', 'yak']);
        expect(document.querySelector('.fl-count').textContent).toBe('3 items');
        expect(document.querySelector('.fl-entry').value).toBe('hor');
    });

    test('no answer empties the list', () => {
        boot(FREE_LIST, list(['dog', 'cat']));
        applyTeam(client, 'fl', null, ['fl']);
        expect(shownItems()).toEqual([]);
        expect(document.querySelector('.fl-count').textContent).toBe('0 items');
    });

    test('applying saves nothing; twice, one Enter still adds one item', () => {
        boot(FREE_LIST, list(['dog']));
        const watch = watchSaves(calls);
        const input = document.getElementById('fl_fl_hidden');
        const changes = countChanges(input);
        applyTeam(client, 'fl', { fl: list(['owl']) });
        applyTeam(client, 'fl', { fl: list(['owl']) });
        expect(shownItems()).toEqual(['owl']);
        expectNoSave(watch, changes, input);
        const entry = document.querySelector('.fl-entry');
        entry.value = 'bat';
        entry.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        expect(changes.n).toBe(1);
        expect(JSON.parse(input.value).items).toEqual(['owl', 'bat']);
    });

    test('a running timed list does not save when a teammate changes it', () => {
        boot(FREE_LIST_TIMED, list(['dog'], { elapsed_ms: 12000 }));
        const watch = watchSaves(calls);
        const input = document.getElementById('flt_flt_hidden');
        const changes = countChanges(input);
        applyTeam(client, 'flt', { flt: list(['owl', 'emu'], { elapsed_ms: 17000 }) });
        expect(shownItems()).toEqual(['owl', 'emu']);
        expect(document.querySelector('.fl-clock-value').textContent).toBe('0:43');
        expectNoSave(watch, changes, input);
    });
});

// ---------------------------------------------------------------------------

describe('triad_test', () => {
    const triads = (odd) => JSON.stringify({ design: 'steiner', triads: [
        ['apple', 'pear', 'fig', odd[0]], ['apple', 'kiwi', 'fig', odd[1]], ['pear', 'kiwi', 'fig', odd[2]]] });
    const checked = () => Array.from(document.querySelectorAll('.tt-option[aria-checked="true"]'))
        .map((b) => b.querySelector('.tt-item').textContent);
    const progress = () => document.querySelector('.tt-progress').textContent;

    function boot(stored) {
        page(TRIAD, 'tt_tt_hidden', stored);
        delete window.PotatoTriadTest;
        delete window.potatoCollabWidgets;
        loadStatic('triad-test.js');
        ({ client, calls } = bootCollab());
    }

    test("a teammate's choices replace the ones shown", () => {
        boot(triads(['fig', null, null]));
        expect(progress()).toBe('Triad 2 of 3 · 1 answered');
        const shown = applyTeam(client, 'tt', { tt: triads(['apple', 'kiwi', 'pear']) });
        expect(shown.has('L:tt:::tt')).toBe(true);
        expect(progress()).toBe('Triad 2 of 3 · 3 answered');
        expect(checked()).toEqual(['kiwi']);
        expect(document.querySelector('.tt-done').hidden).toBe(false);
    });

    test('no answer clears every choice at once', () => {
        boot(triads(['fig', 'kiwi', null]));
        jest.spyOn(console, 'error').mockImplementation(() => {});    // no item list here
        applyTeam(client, 'tt', null, ['tt']);
        expect(progress()).toMatch(/· 0 answered$/);
        expect(checked()).toEqual([]);
        expect(document.querySelectorAll('.tt-option')).toHaveLength(3);
        console.error.mockRestore();
    });

    test("no answer shows this member's own plan, as a fresh load of the unanswered item does", async () => {
        const ITEMS = { items: ['apple', 'pear', 'fig', 'kiwi'] };
        const shownTriads = () => {
            const seen = [];
            for (let i = 0; ; i++) {
                seen.push(Array.from(document.querySelectorAll('.tt-option .tt-item')).map((e) => e.textContent));
                const next = document.querySelector('.tt-next');
                if (next.disabled) break;
                next.click();
            }
            return seen;
        };
        const bootAs = (stored) => {
            page(TRIAD, 'tt_tt_hidden', stored);
            window.config = { username: 'ana' };
            delete window.PotatoTriadDesign;
            delete window.PotatoTriadTest;
            delete window.potatoCollabWidgets;
            ({ client, calls } = bootCollab((url) => (/instance_data/.test(url) ? ITEMS : undefined)));
            loadStatic('triad-design.js');
            loadStatic('triad-test.js');
        };
        // A fresh load of the unanswered item: ana's own plan.
        bootAs(null);
        await flush();
        const fresh = shownTriads();
        expect(fresh.length).toBeGreaterThan(1);
        // ana's page holds ben's answer (ben's own order), then ben clears it.
        const bensOrder = fresh.slice().reverse().map((t) => t.slice().reverse())
            .map((t) => t.concat([t[0]]));
        bootAs(JSON.stringify({ design: 'complete', triads: bensOrder }));
        document.querySelector('.tt-next').click();
        const watch = watchSaves(calls);
        const input = document.getElementById('tt_tt_hidden');
        const changes = countChanges(input);
        applyTeam(client, 'tt', null, ['tt']);
        await flush();
        expect(progress()).toBe(`Triad 1 of ${fresh.length} · 0 answered`);
        expect(shownTriads()).toEqual(fresh);
        expect(checked()).toEqual([]);
        expectNoSave(watch, changes, input);
        delete window.config;
    });

    test('applying saves nothing; twice, one click is one choice', () => {
        boot(triads(['fig', null, null]));
        const watch = watchSaves(calls);
        const input = document.getElementById('tt_tt_hidden');
        const changes = countChanges(input);
        applyTeam(client, 'tt', { tt: triads(['pear', null, null]) });
        applyTeam(client, 'tt', { tt: triads(['pear', null, null]) });
        expectNoSave(watch, changes, input);
        expect(document.querySelectorAll('.tt-option')).toHaveLength(3);
        document.querySelector('.tt-option[data-position="1"]').click();
        expect(changes.n).toBe(1);
        expect(JSON.parse(input.value).triads[1][3]).toBe('kiwi');
    });
});

// ---------------------------------------------------------------------------

describe('listening_test', () => {
    const view = {
        method: 'mushra', slots: [{ slot: 's1', url: '/audio/1' }, { slot: 's2', url: '/audio/2' }],
        reference: '/audio/ref', scale: ['Bad', 'Poor', 'Fair', 'Good', 'Excellent'],
        require_all_played: false, require_full_playback: false, require_one_at_100: false,
    };

    function audioContext() {
        return class {
            constructor() { this.currentTime = 0; this.state = 'running'; this.destination = {}; }
            decodeAudioData(buf, ok) { ok({ duration: 4 }); }
            createGain() { return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, value: 1 }, connect() {} }; }
            createBufferSource() { return { connect() {}, start() {}, stop() {} }; }
            resume() {}
        };
    }

    async function boot(stored) {
        page(LISTENING, 'lt_lt_hidden', stored);
        window.AudioContext = audioContext();
        delete window.PotatoListeningTest;
        delete window.potatoCollabWidgets;
        ({ client, calls } = bootCollab((url) => {
            if (url.indexOf('/api/listening/plan') === 0) return view;
            return { ok: true, status: 200, json: () => Promise.resolve({}),
                arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) };
        }));
        loadStatic('listening-test.js');
        for (let i = 0; i < 6; i++) await flush();
    }

    const ratings = () => Array.from(document.querySelectorAll('.lt-row')).map((row) =>
        row.querySelector('.lt-value').textContent + (row.querySelector('.lt-slider').classList.contains('lt-rated') ? '' : '?'));

    test("a teammate's ratings replace the ones shown", async () => {
        await boot(JSON.stringify({ ratings: { s1: 40 }, played: [] }));
        expect(ratings()).toEqual(['40', '–?']);
        const shown = applyTeam(client, 'lt', { lt: JSON.stringify({ ratings: { s2: 90 }, played: ['s2'] }) });
        expect(shown.has('L:lt:::lt')).toBe(true);
        expect(ratings()).toEqual(['–?', '90']);
        expect(document.querySelector('.lt-slider[data-slot="s2"]').value).toBe('90');
        expect(document.querySelector('.lt-play[data-slot="s2"]').classList.contains('lt-heard')).toBe(true);
    });

    test('no answer clears every rating', async () => {
        await boot(JSON.stringify({ ratings: { s1: 40, s2: 70 }, played: [] }));
        applyTeam(client, 'lt', null, ['lt']);
        expect(ratings()).toEqual(['–?', '–?']);
        expect(document.getElementById('lt').getAttribute('data-incomplete-reason')).toMatch(/rate Sample 1, Sample 2/);
    });

    test('applying saves nothing and twice draws each slider once', async () => {
        await boot(JSON.stringify({ ratings: { s1: 40 }, played: [] }));
        const watch = watchSaves(calls);
        const input = document.getElementById('lt_lt_hidden');
        const changes = countChanges(input);
        const team = JSON.stringify({ ratings: { s1: 10, s2: 20 }, played: [] });
        applyTeam(client, 'lt', { lt: team });
        applyTeam(client, 'lt', { lt: team });
        expect(ratings()).toEqual(['10', '20']);
        expect(document.querySelectorAll('.lt-slider')).toHaveLength(2);
        expect(input.value).toBe(team);
        expectNoSave(watch, changes, input);
    });
});

// ---------------------------------------------------------------------------

describe('interlinear_gloss', () => {
    const gloss = (pairs, translation) => JSON.stringify({
        words: [['Ni-ka', pairs[0]], ['ama', pairs[1]]].map(([word, p]) => ({ word, morphemes: p[0], gloss: p[1] })),
        translation: translation || '' });
    const cells = (tier) => Array.from(document.querySelectorAll(`.igt-input[data-tier="${tier}"]`)).map((i) => i.value);

    function boot(stored) {
        page(GLOSS, 'igt_igt_hidden', stored);
        window.potatoInstanceFields = () => ({ text: 'Ni-ka ama.' });
        delete window.PotatoInterlinearGloss;
        delete window.potatoCollabWidgets;
        loadStatic('interlinear-gloss.js');
        ({ client, calls } = bootCollab());
    }

    test("a teammate's glosses replace the ones shown", () => {
        boot(gloss([['Ni-ka', '1SG-NOM'], ['ama', 'mother']]));
        expect(cells('gloss')).toEqual(['1SG-NOM', 'mother']);
        const shown = applyTeam(client, 'igt', { igt: gloss([['Ni-ka', '1PL-ERG'], ['am-a', 'mother-DEF']], 'We, the mother') });
        expect(shown.has('L:igt:::igt')).toBe(true);
        expect(cells('gloss')).toEqual(['1PL-ERG', 'mother-DEF']);
        expect(cells('morphemes')).toEqual(['Ni-ka', 'am-a']);
        expect(document.querySelector('.igt-translation').value).toBe('We, the mother');
        expect(document.querySelectorAll('.igt-word[data-status="ok"]')).toHaveLength(2);
    });

    test('no answer goes back to the unglossed words', () => {
        boot(gloss([['Ni-ka', '1SG-NOM'], ['ama', 'mother']], 'I, mother'));
        applyTeam(client, 'igt', null, ['igt']);
        expect(cells('gloss')).toEqual(['', '']);
        expect(cells('morphemes')).toEqual(['Ni-ka', 'ama']);
        expect(document.querySelector('.igt-translation').value).toBe('');
        expect(document.getElementById('igt_igt_hidden').value).toBe('');
    });

    test('applying saves nothing; twice, typing writes once', () => {
        boot(gloss([['Ni-ka', '1SG-NOM'], ['ama', 'mother']]));
        const watch = watchSaves(calls);
        const input = document.getElementById('igt_igt_hidden');
        const changes = countChanges(input);
        const team = gloss([['Ni-ka', '1PL-ERG'], ['ama', 'mother']]);
        applyTeam(client, 'igt', { igt: team });
        applyTeam(client, 'igt', { igt: team });
        expect(document.querySelectorAll('.igt-word:not(.igt-head)')).toHaveLength(2);
        expect(input.value).toBe(team);
        expectNoSave(watch, changes, input);
        const cell = document.querySelector('.igt-input[data-tier="gloss"]');
        cell.value = '1PL-ABS';
        cell.dispatchEvent(new Event('input', { bubbles: true }));
        expect(changes.n).toBe(1);
        expect(JSON.parse(input.value).words[0].gloss).toBe('1PL-ABS');
    });
});

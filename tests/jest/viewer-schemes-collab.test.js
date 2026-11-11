/**
 * Live sessions: peak_picking and viewer_selection show a teammate's
 * selection without a reload (viewers/peak-picking.js and
 * viewers/viewer-selection.js register the appliers).
 *
 * The real viewer framework (viewers/viewer-framework.js) mounts a viewer
 * whose adapter is a stand-in: Plotly, 3Dmol and igv.js do not run in jsdom.
 * Its painter writes the selection onto the stage element, the stand-in
 * for the plot. Scheme markup is the generators' own output.
 */

const { loadStatic, bootCollab, applyTeam, watchSaves, countChanges, flush } = require('./misc-collab-harness');

const PEAKS = `
    <form id="pp" class="annotation-form peak-picking" action="javascript:void(0)"
          data-annotation-type="peak_picking" data-schema-name="pp"
          data-peak-config='{&quot;schema&quot;: &quot;pp&quot;, &quot;viewerField&quot;: &quot;spec&quot;, &quot;peakFields&quot;: [{&quot;name&quot;: &quot;label&quot;, &quot;type&quot;: &quot;text&quot;, &quot;label&quot;: &quot;Label&quot;, &quot;required&quot;: false}], &quot;regionFields&quot;: [{&quot;name&quot;: &quot;label&quot;, &quot;type&quot;: &quot;text&quot;, &quot;label&quot;: &quot;Label&quot;, &quot;required&quot;: false}], &quot;minPeaks&quot;: null, &quot;maxPeaks&quot;: null, &quot;requireReview&quot;: false, &quot;allowManual&quot;: true}' data-grid-columns="1">
        <fieldset schema="pp">
            <legend class="pp-title">Peaks</legend>
            
            <section class="pp-suggestions" hidden aria-labelledby="pp-sugg-title">
                <div class="pp-section-head">
                    <h4 class="pp-section-title" id="pp-sugg-title">Suggested peaks</h4>
                    <span class="pp-sugg-count"></span>
                    <span class="pp-head-actions">
                        <button type="button" class="pp-btn pp-accept-all">Accept all</button>
                        <button type="button" class="pp-btn pp-reject-all">Reject all</button>
                    </span>
                </div>
                <ul class="pp-sugg-list"></ul>
                <p class="pp-rejected" hidden></p>
            </section>
            <section class="pp-peaks" aria-labelledby="pp-peaks-title">
                <div class="pp-section-head">
                    <h4 class="pp-section-title" id="pp-peaks-title">Peaks</h4>
                    <span class="pp-peak-count"></span>
                </div>
                <p class="pp-empty">No peaks picked yet.</p>
                <div class="pp-table-wrap"><table class="pp-table pp-peak-table" hidden>
                    <thead></thead><tbody></tbody></table></div>
            </section>
            <section class="pp-regions" hidden aria-labelledby="pp-regions-title">
                <div class="pp-section-head">
                    <h4 class="pp-section-title" id="pp-regions-title">Integrals</h4>
                </div>
                <div class="pp-table-wrap"><table class="pp-table pp-region-table">
                    <thead></thead><tbody></tbody></table></div>
            </section>
            <div class="pp-add"><label class="pp-add-label" for="pp-add-x">Add a peak at</label><input type="text" inputmode="decimal" id="pp-add-x" class="pp-add-x" autocomplete="off" aria-describedby="pp-add-hint"><button type="button" class="pp-btn pp-add-btn">Add peak</button><span class="pp-add-hint" id="pp-add-hint"></span></div>
            <p class="pp-message" role="status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input peak-picking-input"
                   id="pp_pp_hidden" name="pp:::pp"
                   schema="pp" label_name="pp"
                   validation="" value="">
        </fieldset>
    </form>
    `;
const SELECTION = `
    <form id="vs" class="annotation-form viewer-selection" action="javascript:void(0)"
          data-annotation-type="viewer_selection" data-schema-name="vs"
          data-selection-config='{&quot;schema&quot;: &quot;vs&quot;, &quot;viewerField&quot;: &quot;seq&quot;, &quot;labels&quot;: [], &quot;minSelections&quot;: null, &quot;maxSelections&quot;: null}' data-grid-columns="1">
        <fieldset schema="vs">
            <legend class="vs-title">Sel</legend>
            
            
            <p class="vs-context" hidden></p>
            <p class="vs-empty">Nothing selected yet.</p>
            <ul class="vs-list" aria-label="Selected"></ul>
            <p class="vs-count"></p>
            <p class="vs-message" role="status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input viewer-selection-input"
                   id="vs_vs_hidden" name="vs:::vs"
                   schema="vs" label_name="vs"
                   validation="" value="">
        </fieldset>
    </form>
    `;

let client, calls;

function viewerHtml(field) {
    return `<div class="potato-viewer" data-viewer-kind="stub"
        data-viewer-config='{"field": "${field}", "kind": "stub"}'><div class="pv-stage"></div></div>`;
}

const keyOf = (it) => (it.kind === 'region' ? `r:${it.from}:${it.to}` : it.kind === 'peak' ? `p:${it.x}` : `i:${it.pos}`);

async function boot(html, field, scheme, hiddenId, stored, context) {
    document.body.innerHTML = '<input type="hidden" id="instance_id" value="item-1">' + viewerHtml(field) + html;
    if (stored) {
        const h = document.getElementById(hiddenId);
        h.value = stored;
        h.setAttribute('data-server-set', 'true');
    }
    window.potatoViewers = {};
    delete window.PotatoViewerFramework;
    delete window.PotatoPeakPicking;
    delete window.PotatoViewerSelection;
    delete window.potatoCollabWidgets;
    loadStatic('viewers/viewer-framework.js');
    window.PotatoViewerFramework.register('stub', {
        key: keyOf,
        normalizeItem: (it) => (it && typeof it === 'object' ? Object.assign({}, it) : null),
        describe: (it) => keyOf(it),
        context,
        init(ctx) {
            ctx.viewer.addPainter((sel) => {
                ctx.stage.setAttribute('data-items', sel.items.map(keyOf).join(' '));
                ctx.stage.setAttribute('data-context', JSON.stringify(context.map((k) => sel[k] === undefined ? null : sel[k])));
            });
        },
        start: () => Promise.resolve(),
    });
    loadStatic(scheme);
    for (let i = 0; i < 4; i++) await flush();
    ({ client, calls } = bootCollab());
}

const stage = () => document.querySelector('.pv-stage');

// ---------------------------------------------------------------------------

describe('peak_picking', () => {
    const peaks = (xs, rejected) => JSON.stringify({ viewer: 'stub',
        items: xs.map((x) => ({ kind: 'peak', x, y: 10, source: 'manual' })), rejected: rejected || [] });
    const rows = () => Array.from(document.querySelectorAll('.pp-peak-table tbody tr .pp-pos')).map((c) => c.textContent);
    const bootPeaks = (stored) => boot(PEAKS, 'spec', 'viewers/peak-picking.js', 'pp_pp_hidden', stored, ['rejected']);

    test('the page draws its own peaks first', async () => {
        await bootPeaks(peaks([1.5, 7.25], [3.2]));
        expect(rows()).toEqual(['1.5', '7.25']);
        expect(stage().getAttribute('data-items')).toBe('p:1.5 p:7.25');
    });

    test("a teammate's peaks replace the table and the plot", async () => {
        await bootPeaks(peaks([1.5, 7.25], [3.2]));
        // An answer saved with no rejected suggestions carries no `rejected`.
        const team = JSON.stringify({ viewer: 'stub', items: [{ kind: 'peak', x: 2, y: 10, source: 'manual' }] });
        const shown = applyTeam(client, 'pp', { pp: team });
        expect(shown.has('L:pp:::pp')).toBe(true);
        expect(rows()).toEqual(['2']);
        expect(stage().getAttribute('data-items')).toBe('p:2');
        // The rejected list is the teammate's (none), not the one shown before.
        expect(stage().getAttribute('data-context')).toBe('[[]]');
    });

    test('no answer clears the peaks and the rejected suggestions', async () => {
        await bootPeaks(peaks([1.5], [3.2]));
        applyTeam(client, 'pp', null, ['pp']);
        expect(rows()).toEqual([]);
        expect(document.querySelector('.pp-empty').hidden).toBe(false);
        expect(stage().getAttribute('data-items')).toBe('');
        expect(stage().getAttribute('data-context')).toBe('[[]]');
    });

    test('applying saves nothing; twice, each peak is listed once', async () => {
        await bootPeaks(peaks([1.5]));
        const watch = watchSaves(calls);
        const input = document.getElementById('pp_pp_hidden');
        const changes = countChanges(input);
        applyTeam(client, 'pp', { pp: peaks([4, 5]) });
        applyTeam(client, 'pp', { pp: peaks([4, 5]) });
        expect(rows()).toEqual(['4', '5']);
        expect(changes.n).toBe(0);
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
        // One Remove click removes one peak and saves once.
        document.querySelector('.pp-peak-table .pp-remove').click();
        expect(changes.n).toBe(1);
        expect(rows()).toEqual(['5']);
    });
});

// ---------------------------------------------------------------------------

describe('viewer_selection', () => {
    const sel = (positions, locus) => JSON.stringify(Object.assign({ viewer: 'stub',
        items: positions.map((pos) => ({ pos })) }, locus ? { locus } : {}));
    const listed = () => Array.from(document.querySelectorAll('.vs-list .vs-desc')).map((d) => d.textContent);
    const bootSel = (stored) => boot(SELECTION, 'seq', 'viewers/viewer-selection.js', 'vs_vs_hidden', stored, ['locus']);

    test("a teammate's selection replaces the list and the viewer", async () => {
        await bootSel(sel([10, 20], 'chr1:1-100'));
        expect(listed()).toEqual(['i:10', 'i:20']);
        const shown = applyTeam(client, 'vs', { vs: sel([30], 'chr2:5-50') });
        expect(shown.has('L:vs:::vs')).toBe(true);
        expect(listed()).toEqual(['i:30']);
        expect(stage().getAttribute('data-items')).toBe('i:30');
        expect(stage().getAttribute('data-context')).toBe('["chr2:5-50"]');
        expect(document.querySelector('.vs-count').textContent).toBe('1 selected');
    });

    test('no answer selects nothing; the view position stays', async () => {
        await bootSel(sel([10, 20], 'chr1:1-100'));
        applyTeam(client, 'vs', null, ['vs']);
        expect(listed()).toEqual([]);
        expect(document.querySelector('.vs-empty').hidden).toBe(false);
        expect(stage().getAttribute('data-items')).toBe('');
        expect(stage().getAttribute('data-context')).toBe('["chr1:1-100"]');
    });

    test('applying saves nothing; twice, each selection is listed once', async () => {
        await bootSel(sel([10]));
        const watch = watchSaves(calls);
        const input = document.getElementById('vs_vs_hidden');
        const changes = countChanges(input);
        applyTeam(client, 'vs', { vs: sel([1, 2]) });
        applyTeam(client, 'vs', { vs: sel([1, 2]) });
        expect(listed()).toEqual(['i:1', 'i:2']);
        expect(changes.n).toBe(0);
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
        document.querySelector('.vs-list .vs-remove').click();
        expect(changes.n).toBe(1);
        expect(listed()).toEqual(['i:2']);
    });
});

/**
 * Live sessions: multi_document_event shows a teammate's change without a
 * reload (multi-document-event.js registers the applier).
 *
 * The events live in the shared Event Registry (/corpus/api/*); the scheme's
 * hidden input is the team's answer, the list of event ids this document is
 * in. The scheme's container is a <div>, found by collab.js through its id.
 */

const { loadStatic, bootCollab, applyTeam, watchSaves, countChanges, flush } = require('./misc-collab-harness');

const MARKUP = `
    <div id="mde" class="mde-container annotation-form" data-annotation-type="multi_document_event" data-schema-name="mde" data-grid-columns="1"
         data-annotation-type="multi_document_event"
         data-scheme-name="mde"
         data-schema-name="mde"
         data-allow-create="true"
         data-slots='[{&quot;name&quot;: &quot;who&quot;, &quot;description&quot;: &quot;&quot;, &quot;type&quot;: &quot;text&quot;}]'>

        <div class="mde-header">
            <h4 class="mde-title">Events</h4>
        </div>

        <!-- Events this document belongs to / can be added to -->
        <div class="mde-events-section">
            <div class="mde-section-header">
                <label class="mde-section-label">Events</label>
                <button type="button" class="mde-create-btn" data-role="create-event"
                        >
                    + New event
                </button>
            </div>
            <div class="mde-event-list" data-role="event-list">
                <p class="mde-empty">Loading events…</p>
            </div>
        </div>

        <!-- Active event editor: slots + evidence -->
        <div class="mde-editor" data-role="editor" style="display:none;">
            <div class="mde-editor-head">
                <input type="text" class="mde-editor-title" data-role="editor-title"
                       placeholder="Event name…">
                <label class="mde-membership">
                    <input type="checkbox" data-role="membership-toggle">
                    This document belongs to this event
                </label>
            </div>
            <div class="mde-slots" data-role="slots"></div>
        </div>

        <!-- Cite-evidence hint (shown while awaiting a span selection) -->
        <div class="mde-cite-hint" data-role="cite-hint" style="display:none;">
            Select text in the document to cite it as evidence for
            <strong data-role="cite-slot"></strong>.
            <button type="button" data-role="cite-cancel">Cancel</button>
        </div>

        <!-- The per-annotator answer: which events THIS annotator put this
             document in. The Event Registry is shared by everyone, and its
             \`member_doc_ids\` carries no annotator, so without this input the
             per-annotator answer existed nowhere -- not in user_state.json, not
             in the export, not in /admin/iaa.

             \`class="annotation-input"\` plus schema/label_name is what makes
             syncAnnotationsFromDOM read it; the JS also stamps \`data-modified\`
             when it writes, which is the second half of that contract. -->
        <input type="hidden" class="annotation-input mde-data-input"
               id="mde_mde_hidden" name="mde:::mde"
               schema="mde" label_name="mde"
               validation="" value="">
    </div>
    `;

let client, calls, registry;

const ev = (id, title, members) => ({ id, title, member_doc_ids: members, slot_values: {}, evidence: [],
    provenance: 'annotator', updated_at: 1 });

async function settle() { for (let i = 0; i < 5; i++) await flush(); }

async function boot(initial) {
    document.body.innerHTML = '<input type="hidden" id="instance_id" value="item-1">' + MARKUP;
    const h = document.getElementById('mde_mde_hidden');
    h.value = JSON.stringify(initial);
    h.setAttribute('data-server-set', 'true');
    registry = [ev('e1', 'Flood', ['item-1'])];
    ({ client, calls } = bootCollab((url) => {
        if (url.indexOf('/corpus/api/event_template') === 0) return { slots: [{ name: 'who' }] };
        if (url.indexOf('/corpus/api/events') === 0) return { events: registry };
        return {};
    }));
    window.mdeManagers = {};
    delete window.potatoCollabWidgets;
    loadStatic('multi-document-event.js');
    await settle();
}

const rows = () => Array.from(document.querySelectorAll('.mde-event-row')).map((r) =>
    r.querySelector('.mde-event-open').textContent.trim()
    + (/this doc/.test(r.querySelector('.mde-event-meta').textContent) ? '*' : ''));

describe('multi_document_event live applier', () => {
    test('the page lists the registry first', async () => {
        await boot(['e1']);
        expect(rows()).toEqual(['Flood*']);
    });

    test("a teammate's events replace the list shown", async () => {
        await boot(['e1']);
        registry = [ev('e2', 'Storm', ['item-1']), ev('e3', 'Fire', ['item-9'])];
        const shown = applyTeam(client, 'mde', { mde: JSON.stringify(['e2']) });
        expect(shown.has('L:mde:::mde')).toBe(true);
        await settle();
        expect(rows()).toEqual(['Storm*', 'Fire']);
        expect(document.getElementById('mde_mde_hidden').value).toBe('["e2"]');
    });

    test('no answer: the emptied registry shows no events', async () => {
        await boot(['e1']);
        registry = [];
        const shown = applyTeam(client, 'mde', null, ['mde']);
        expect(shown.has('L:mde:::mde')).toBe(true);
        await settle();
        expect(rows()).toEqual([]);
        expect(document.querySelector('.mde-empty').textContent).toMatch(/No events yet/);
    });

    test('applying saves nothing, and twice draws each event once', async () => {
        await boot(['e1']);
        const watch = watchSaves(calls);
        const input = document.getElementById('mde_mde_hidden');
        const changes = countChanges(input);
        registry = [ev('e1', 'Flood', []), ev('e2', 'Storm', ['item-1'])];
        applyTeam(client, 'mde', { mde: JSON.stringify(['e2']) });
        applyTeam(client, 'mde', { mde: JSON.stringify(['e2']) });
        await settle();
        expect(rows()).toEqual(['Flood', 'Storm*']);
        expect(changes.n).toBe(0);
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(input.value).toBe('["e2"]');
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
    });

    test("the redraw never rewrites the team's answer as this annotator's", async () => {
        // The registry has moved on since the teammate saved: redrawing it
        // must not mirror it into the input, stamp it, and fire a save.
        await boot(['e1']);
        const input = document.getElementById('mde_mde_hidden');
        const changes = countChanges(input);
        registry = [ev('e1', 'Flood', ['item-1']), ev('e2', 'Storm', ['item-1'])];
        applyTeam(client, 'mde', { mde: JSON.stringify(['e2']) });
        await settle();
        expect(rows()).toEqual(['Flood*', 'Storm*']);
        expect(input.value).toBe('["e2"]');
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(changes.n).toBe(0);
    });
});

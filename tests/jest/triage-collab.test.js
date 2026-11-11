/**
 * Live sessions: a triage decision a teammate made shows without a reload
 * (triage.js registers the applier).
 *
 * triage was trusted to annotation.js's restore pass, but nothing in
 * populateInputValues() redraws the triage buttons: the hidden input took the
 * teammate's value while the old button stayed lit. Markup is triage.py's
 * own output.
 */

const { loadStatic, bootCollab, applyTeam, watchSaves, countChanges } = require('./misc-collab-harness');

const TRIAGE = `
    <form id="tri" class="annotation-form triage" action="javascript:void(0)"
          data-annotation-id=""
          data-annotation-type="triage"
          data-schema-name="tri"
          data-auto-advance="true"
          data-grid-columns="1">
        <fieldset schema="tri">
            <legend class="triage-title">Keep?</legend>

            <!-- Hidden input to store the decision value -->
            <input type="hidden"
                   id="tri_value"
                   name="tri:::decision"
                   class="annotation-input triage-input"
                   schema="tri"
                   label_name="decision"
                   value="">

            <div class="triage-container">
                <!-- Triage buttons -->
                <div class="triage-buttons">
                    <button type="button"
                            class="triage-btn triage-accept"
                            data-value="accept"
                            data-schema="tri"
                            data-key="1">
                        <span class="triage-btn-icon">&#10003;</span>
                        <span class="triage-btn-label">Keep</span>
                        <span class="triage-btn-key">[1]</span>
                    </button>

                    <button type="button"
                            class="triage-btn triage-reject"
                            data-value="reject"
                            data-schema="tri"
                            data-key="2">
                        <span class="triage-btn-icon">&#10007;</span>
                        <span class="triage-btn-label">Discard</span>
                        <span class="triage-btn-key">[2]</span>
                    </button>

                    <button type="button"
                            class="triage-btn triage-skip"
                            data-value="skip"
                            data-schema="tri"
                            data-key="3">
                        <span class="triage-btn-icon">&#8594;</span>
                        <span class="triage-btn-label">Unsure</span>
                        <span class="triage-btn-key">[3]</span>
                    </button>
                </div>
    
                <!-- Progress indicator (populated by JavaScript) -->
                <div class="triage-progress" id="triage-progress-tri">
                    <div class="triage-progress-bar">
                        <div class="triage-progress-fill" style="width: 0%"></div>
                    </div>
                    <div class="triage-progress-text">
                        <span class="triage-progress-current">0</span> /
                        <span class="triage-progress-total">0</span>
                    </div>
                </div>
        
            </div>
        </fieldset>
    </form>
    `;

let client, calls;

function boot(stored) {
    document.body.innerHTML = '<input type="hidden" id="instance_id" value="item-1">' + TRIAGE;
    if (stored) {
        const h = document.getElementById('tri_value');
        h.value = stored;
        h.setAttribute('data-server-set', 'true');
    }
    delete window.triageManager;
    delete window.potatoCollabWidgets;
    loadStatic('triage.js');
    ({ client, calls } = bootCollab());
}

const lit = () => Array.from(document.querySelectorAll('.triage-btn.selected')).map((b) => b.dataset.value);
const pressed = () => Array.from(document.querySelectorAll('.triage-btn[aria-pressed="true"]')).map((b) => b.dataset.value);

describe('triage live applier', () => {
    test('the page lights its own decision first', () => {
        boot('accept');
        expect(lit()).toEqual(['accept']);
    });

    test("a teammate's decision replaces the one lit", () => {
        boot('accept');
        const shown = applyTeam(client, 'tri', { decision: 'reject' });
        expect(shown.has('L:tri:::decision')).toBe(true);
        expect(lit()).toEqual(['reject']);
        expect(pressed()).toEqual(['reject']);
    });

    test('no decision unlights every button', () => {
        boot('accept');
        const shown = applyTeam(client, 'tri', null, ['decision']);
        expect(shown.has('L:tri:::decision')).toBe(true);
        expect(lit()).toEqual([]);
        expect(pressed()).toEqual([]);
    });

    test('applying saves nothing and does not advance', () => {
        boot('accept');
        const watch = watchSaves(calls);
        window.navigateToNext = jest.fn();
        const input = document.getElementById('tri_value');
        const changes = countChanges(input);
        applyTeam(client, 'tri', { decision: 'skip' });
        applyTeam(client, 'tri', { decision: 'skip' });
        expect(lit()).toEqual(['skip']);
        expect(changes.n).toBe(0);
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
        expect(window.navigateToNext).not.toHaveBeenCalled();
    });
});

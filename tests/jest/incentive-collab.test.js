/**
 * Live sessions: price_list, bdm and belief_elicitation show a teammate's
 * answer without a reload (incentive-elicitation.js registers the appliers).
 *
 * Markup is the generators' own output (price_list.py, bdm.py,
 * belief_elicitation.py). Each test goes through collab.js's applyKeys, so
 * the scheme is found the way a session page finds it.
 */

const { loadStatic, bootCollab, applyTeam, watchSaves, countChanges } = require('./misc-collab-harness');

const PRICE_LIST = `
    <form id="risk" class="annotation-form price-list incentive-widget" action="javascript:void(0)"
          data-annotation-type="price_list" data-schema-name="risk"
          data-price-list='{&quot;rows&quot;: 3, &quot;single_switch&quot;: false}' data-grid-columns="1">
        <fieldset schema="risk">
            <legend class="iw-title">Choose</legend>
            
            <div class="pl-table">
                <div class="pl-head" aria-hidden="true"><span class="pl-num">#</span>
                    <span>Option A</span><span>Option B</span></div>
                <div class="pl-row" role="radiogroup" aria-label="Decision 1" data-row="0"><span class="pl-num" aria-hidden="true">1</span><button type="button" role="radio" aria-checked="false" class="pl-choice" data-row="0" data-choice="A" aria-label="Decision 1, Option A: $2"><span class="pl-mark" aria-hidden="true"></span><span class="pl-tag" aria-hidden="true">A</span><span class="pl-text">$2</span></button><button type="button" role="radio" aria-checked="false" class="pl-choice" data-row="0" data-choice="B" aria-label="Decision 1, Option B: $3"><span class="pl-mark" aria-hidden="true"></span><span class="pl-tag" aria-hidden="true">B</span><span class="pl-text">$3</span></button></div><div class="pl-row" role="radiogroup" aria-label="Decision 2" data-row="1"><span class="pl-num" aria-hidden="true">2</span><button type="button" role="radio" aria-checked="false" class="pl-choice" data-row="1" data-choice="A" aria-label="Decision 2, Option A: $2"><span class="pl-mark" aria-hidden="true"></span><span class="pl-tag" aria-hidden="true">A</span><span class="pl-text">$2</span></button><button type="button" role="radio" aria-checked="false" class="pl-choice" data-row="1" data-choice="B" aria-label="Decision 2, Option B: $4"><span class="pl-mark" aria-hidden="true"></span><span class="pl-tag" aria-hidden="true">B</span><span class="pl-text">$4</span></button></div><div class="pl-row" role="radiogroup" aria-label="Decision 3" data-row="2"><span class="pl-num" aria-hidden="true">3</span><button type="button" role="radio" aria-checked="false" class="pl-choice" data-row="2" data-choice="A" aria-label="Decision 3, Option A: $2"><span class="pl-mark" aria-hidden="true"></span><span class="pl-tag" aria-hidden="true">A</span><span class="pl-text">$2</span></button><button type="button" role="radio" aria-checked="false" class="pl-choice" data-row="2" data-choice="B" aria-label="Decision 3, Option B: $5"><span class="pl-mark" aria-hidden="true"></span><span class="pl-tag" aria-hidden="true">B</span><span class="pl-text">$5</span></button></div>
            </div>
            <p class="iw-status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input incentive-input"
                   id="risk_risk_hidden" name="risk:::risk"
                   schema="risk" label_name="risk"
                   validation="" value="">
        </fieldset>
    </form>
    `;
const BDM = `
    <form id="wtp" class="annotation-form bdm incentive-widget" action="javascript:void(0)"
          data-annotation-type="bdm" data-schema-name="wtp"
          data-bdm='{&quot;min&quot;: 0.0, &quot;max&quot;: 10.0, &quot;step&quot;: 0.01, &quot;input&quot;: &quot;number&quot;, &quot;currency&quot;: &quot;$&quot;}' data-grid-columns="1">
        <fieldset schema="wtp">
            <legend class="iw-title">Bid</legend>
            
            <div class="bdm-entry">
            <label class="bdm-label" for="wtp_wtp_hidden_entry">Your bid</label>
            <div class="bdm-number-row">
                <span class="bdm-currency" aria-hidden="true">$</span>
                <input type="number" class="bdm-number" id="wtp_wtp_hidden_entry" min="0" max="10" step="0.01"
                       inputmode="decimal" autocomplete="off" aria-describedby="wtp_wtp_hidden_entry_range">
            </div></div>
            <p class="bdm-range iw-hint" id="wtp_wtp_hidden_entry_range">Any amount from $0.00 to $10.00.</p>
            <p class="iw-status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input incentive-input"
                   id="wtp_wtp_hidden" name="wtp:::wtp"
                   schema="wtp" label_name="wtp"
                   validation="" value="">
        </fieldset>
    </form>
    `;
const BDM_SLIDER = `
    <form id="wtp2" class="annotation-form bdm incentive-widget" action="javascript:void(0)"
          data-annotation-type="bdm" data-schema-name="wtp2"
          data-bdm='{&quot;min&quot;: 0.0, &quot;max&quot;: 10.0, &quot;step&quot;: 0.01, &quot;input&quot;: &quot;slider&quot;, &quot;currency&quot;: &quot;$&quot;}' data-grid-columns="1">
        <fieldset schema="wtp2">
            <legend class="iw-title">Bid</legend>
            
            <div class="bdm-entry">
            <label class="bdm-label" for="wtp2_wtp2_hidden_entry">Your bid</label>
            <div class="bdm-slider-row">
                <span class="bdm-end" aria-hidden="true">$0.00</span>
                <input type="range" class="bdm-slider" id="wtp2_wtp2_hidden_entry" min="0" max="10" step="0.01"
                       value="5" aria-describedby="wtp2_wtp2_hidden_entry_range">
                <span class="bdm-end" aria-hidden="true">$10.00</span>
                <output class="bdm-value" for="wtp2_wtp2_hidden_entry">&ndash;</output>
            </div></div>
            <p class="bdm-range iw-hint" id="wtp2_wtp2_hidden_entry_range">Any amount from $0.00 to $10.00.</p>
            <p class="iw-status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input incentive-input"
                   id="wtp2_wtp2_hidden" name="wtp2:::wtp2"
                   schema="wtp2" label_name="wtp2"
                   validation="" value="">
        </fieldset>
    </form>
    `;
const BELIEF_POINT = `
    <form id="prob" class="annotation-form belief-elicitation incentive-widget" action="javascript:void(0)"
          data-annotation-type="belief_elicitation" data-schema-name="prob"
          data-belief='{&quot;mode&quot;: &quot;point&quot;, &quot;step&quot;: 1}' data-grid-columns="1">
        <fieldset schema="prob">
            <legend class="iw-title">P?</legend>
            
            
            <div class="be-point">
                <label class="be-label" for="prob_prob_hidden_entry">Probability (0 to 100%)</label>
                <div class="be-slider-row">
                    <input type="range" class="be-slider" id="prob_prob_hidden_entry" min="0" max="100" step="1"
                           value="50" aria-valuetext="not set">
                    <output class="be-value" for="prob_prob_hidden_entry">&ndash;</output>
                </div>
                <div class="be-ends" aria-hidden="true">
                    <span>0% &middot; Certainly not</span>
                    <span>Certainly &middot; 100%</span>
                </div>
            </div>
            <p class="iw-status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input incentive-input"
                   id="prob_prob_hidden" name="prob:::prob"
                   schema="prob" label_name="prob"
                   validation="" value="">
        </fieldset>
    </form>
    `;
const BELIEF_BINS = `
    <form id="dist" class="annotation-form belief-elicitation incentive-widget" action="javascript:void(0)"
          data-annotation-type="belief_elicitation" data-schema-name="dist"
          data-belief='{&quot;mode&quot;: &quot;bins&quot;, &quot;bins&quot;: 3, &quot;total&quot;: 100}' data-grid-columns="1">
        <fieldset schema="dist">
            <legend class="iw-title">D?</legend>
            
            
            <div class="be-bins" role="group" aria-label="Points per range"><div class="be-bin" data-bin="0"><label class="be-bin-label" for="dist_dist_hidden_entry_0">0-10</label><input type="number" class="be-bin-input" id="dist_dist_hidden_entry_0" data-bin="0" min="0" max="100" step="1" inputmode="numeric" autocomplete="off" placeholder="0"><span class="be-bar" aria-hidden="true"><span class="be-bar-fill"></span></span></div><div class="be-bin" data-bin="1"><label class="be-bin-label" for="dist_dist_hidden_entry_1">10-20</label><input type="number" class="be-bin-input" id="dist_dist_hidden_entry_1" data-bin="1" min="0" max="100" step="1" inputmode="numeric" autocomplete="off" placeholder="0"><span class="be-bar" aria-hidden="true"><span class="be-bar-fill"></span></span></div><div class="be-bin" data-bin="2"><label class="be-bin-label" for="dist_dist_hidden_entry_2">20+</label><input type="number" class="be-bin-input" id="dist_dist_hidden_entry_2" data-bin="2" min="0" max="100" step="1" inputmode="numeric" autocomplete="off" placeholder="0"><span class="be-bar" aria-hidden="true"><span class="be-bar-fill"></span></span></div></div>
            <p class="be-total" aria-live="polite">
                Total: <strong class="be-sum">0</strong> of 100
                <span class="be-left"></span>
            </p>
            <p class="iw-status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input incentive-input"
                   id="dist_dist_hidden" name="dist:::dist"
                   schema="dist" label_name="dist"
                   validation="" value="">
        </fieldset>
    </form>
    `;

let client, calls;

function boot(html, stored) {
    document.body.innerHTML = '<input type="hidden" id="instance_id" value="item-1">' + html;
    Object.keys(stored || {}).forEach((id) => {
        const h = document.getElementById(id);
        h.value = stored[id];
        h.setAttribute('value', stored[id]);
        h.setAttribute('data-server-set', 'true');
    });
    delete window.PotatoIncentiveWidgets;
    delete window.potatoCollabWidgets;
    loadStatic('incentive-elicitation.js');
    ({ client, calls } = bootCollab());
}

const chosen = () => Array.from(document.querySelectorAll('.pl-choice[aria-checked="true"]'))
    .map((b) => b.getAttribute('data-row') + b.getAttribute('data-choice'));

describe('price_list', () => {
    beforeEach(() => boot(PRICE_LIST, {
        risk_risk_hidden: JSON.stringify({ choices: ['A', 'A', 'B'], switches: 1, multiple_switching: false }),
    }));

    test('the page draws its own answer first', () => {
        expect(chosen()).toEqual(['0A', '1A', '2B']);
    });

    test("a teammate's choices replace the ones shown", () => {
        const shown = applyTeam(client, 'risk', {
            risk: JSON.stringify({ choices: ['B', null, 'A'], switches: 1, multiple_switching: false }),
        });
        expect(shown.has('L:risk:::risk')).toBe(true);
        expect(chosen()).toEqual(['0B', '2A']);
        expect(document.querySelector('.pl-row[data-row="1"]').classList.contains('pl-answered')).toBe(false);
        expect(document.querySelector('.iw-status').textContent).toBe('2 of 3 decisions made.');
    });

    test('no answer clears every row', () => {
        const shown = applyTeam(client, 'risk', null, ['risk']);
        expect(shown.has('L:risk:::risk')).toBe(true);
        expect(chosen()).toEqual([]);
        expect(document.querySelectorAll('.pl-answered')).toHaveLength(0);
        expect(document.querySelector('.iw-status').textContent).toBe('0 of 3 decisions made.');
    });

    test('applying saves nothing', () => {
        const watch = watchSaves(calls);
        const changes = countChanges(document.getElementById('risk_risk_hidden'));
        applyTeam(client, 'risk', { risk: JSON.stringify({ choices: ['B', 'B', 'B'] }) });
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
        expect(changes.n).toBe(0);
        expect(document.getElementById('risk_risk_hidden').hasAttribute('data-modified')).toBe(false);
    });

    test('applying twice binds nothing twice: one click is one choice', () => {
        const answer = { risk: JSON.stringify({ choices: ['A', null, null] }) };
        applyTeam(client, 'risk', answer);
        applyTeam(client, 'risk', answer);
        const changes = countChanges(document.getElementById('risk_risk_hidden'));
        document.querySelector('.pl-choice[data-row="1"][data-choice="B"]').click();
        expect(changes.n).toBe(1);
        expect(chosen()).toEqual(['0A', '1B']);
    });
});

describe('bdm', () => {
    test("a teammate's bid replaces the one typed here", () => {
        boot(BDM, { wtp_wtp_hidden: JSON.stringify({ bid: 2.5 }) });
        expect(document.querySelector('.bdm-number').value).toBe('2.5');
        const shown = applyTeam(client, 'wtp', { wtp: JSON.stringify({ bid: 7.25 }) });
        expect(shown.has('L:wtp:::wtp')).toBe(true);
        expect(document.querySelector('.bdm-number').value).toBe('7.25');
        expect(document.querySelector('.iw-status').textContent).toBe('Your bid: $7.25.');
    });

    test('no answer empties the box and the status', () => {
        boot(BDM, { wtp_wtp_hidden: JSON.stringify({ bid: 2.5 }) });
        applyTeam(client, 'wtp', null, ['wtp']);
        expect(document.querySelector('.bdm-number').value).toBe('');
        expect(document.querySelector('.iw-status').textContent).toBe('');
        expect(document.getElementById('wtp').getAttribute('data-incomplete-reason')).toBe('enter a bid');
    });

    test('the slider form follows too, and applying twice saves nothing', () => {
        boot(BDM_SLIDER, { wtp2_wtp2_hidden: JSON.stringify({ bid: 1 }) });
        const watch = watchSaves(calls);
        const changes = countChanges(document.getElementById('wtp2_wtp2_hidden'));
        applyTeam(client, 'wtp2', { wtp2: JSON.stringify({ bid: 9 }) });
        applyTeam(client, 'wtp2', { wtp2: JSON.stringify({ bid: 9 }) });
        expect(document.querySelector('.bdm-slider').value).toBe('9');
        expect(document.querySelector('.bdm-value').textContent).toBe('$9.00');
        applyTeam(client, 'wtp2', null, ['wtp2']);
        expect(document.querySelector('.bdm-slider').classList.contains('bdm-set')).toBe(false);
        expect(document.querySelector('.bdm-value').textContent).toBe('–');
        // The thumb goes back to where an unanswered item draws it.
        expect(document.querySelector('.bdm-slider').value).toBe('5');
        expect(changes.n).toBe(0);
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
    });
});

describe('belief_elicitation', () => {
    test('point: the reported probability replaces this one', () => {
        boot(BELIEF_POINT, { prob_prob_hidden: JSON.stringify({ report: 20 }) });
        expect(document.querySelector('.be-value').textContent).toBe('20%');
        applyTeam(client, 'prob', { prob: JSON.stringify({ report: 85 }) });
        expect(document.querySelector('.be-slider').value).toBe('85');
        expect(document.querySelector('.be-value').textContent).toBe('85%');
        applyTeam(client, 'prob', null, ['prob']);
        expect(document.querySelector('.be-value').textContent).toBe('–');
        expect(document.querySelector('.be-slider').classList.contains('be-set')).toBe(false);
    });

    test('point: a cleared report puts the thumb where a fresh load draws it', () => {
        boot(BELIEF_POINT, { prob_prob_hidden: JSON.stringify({ report: 20 }) });
        expect(document.querySelector('.be-slider').value).toBe('20');
        applyTeam(client, 'prob', { prob: JSON.stringify({ report: 85 }) });
        applyTeam(client, 'prob', null, ['prob']);
        const slider = document.querySelector('.be-slider');
        expect(slider.value).toBe('50');
        expect(slider.getAttribute('aria-valuetext')).toBe('not set');
    });

    test('bins: every bin takes the teammate value, and none empties them', () => {
        boot(BELIEF_BINS, { dist_dist_hidden: JSON.stringify({ bins: [50, 50, 0] }) });
        const watch = watchSaves(calls);
        const changes = countChanges(document.getElementById('dist_dist_hidden'));
        const values = () => Array.from(document.querySelectorAll('.be-bin-input')).map((i) => i.value);
        applyTeam(client, 'dist', { dist: JSON.stringify({ bins: [10, 20, 70] }) });
        expect(values()).toEqual(['10', '20', '70']);
        expect(document.querySelector('.be-sum').textContent).toBe('100');
        expect(document.querySelectorAll('.be-bar-fill')[2].style.width).toBe('70%');
        applyTeam(client, 'dist', { dist: JSON.stringify({ bins: [10, 20, 70] }) });
        expect(values()).toEqual(['10', '20', '70']);
        applyTeam(client, 'dist', null, ['dist']);
        expect(values()).toEqual(['', '', '']);
        expect(document.querySelector('.be-sum').textContent).toBe('0');
        expect(changes.n).toBe(0);
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
    });
});

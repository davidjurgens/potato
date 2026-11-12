/**
 * card_sort could only be done with a mouse.
 *
 * The markup was `<div class="card-sort-card" draggable="true">` and nothing
 * else: no tabindex, no role, no aria, no click-to-assign, no move buttons.
 * `grep -c "tabindex\|role=\|aria-" potato/server_utils/schemas/card_sort.py`
 * was 0. A keyboard-only or screen-reader annotator could not sort a single
 * card, and HTML5 drag-and-drop does not work on touch either, so tablets were
 * out as well. ranking.py is the precedent: it ships Move up / Move down
 * buttons with aria-labels beside the same drag gesture.
 *
 * The widget's script is generated inline by the Python schema, so these tests
 * render it with python and run the result.
 */

const {execFileSync} = require('child_process');
const path = require('path');

const REPO = path.join(__dirname, '..', '..');

function renderCardSort(scheme) {
    const code = `
import json, sys
from potato.server_utils.schemas.card_sort import generate_card_sort_layout
html, _ = generate_card_sort_layout(json.loads(sys.argv[1]))
sys.stdout.write(html)
`;
    return execFileSync('python', ['-c', code, JSON.stringify(scheme)],
        {cwd: REPO, encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore']});
}

const SCHEME = {
    annotation_type: 'card_sort',
    name: 'outcomes',
    description: 'Sort these outcomes.',
    mode: 'closed',
    groups: ['Critical', 'Important'],
};

let html;
beforeAll(() => { html = renderCardSort(SCHEME); });

/** Put the widget in the document and run its inline script. */
function mount() {
    const body = html.replace(/<script>[\s\S]*?<\/script>/, '');
    const script = /<script>([\s\S]*?)<\/script>/.exec(html)[1];
    document.body.innerHTML = body;
    new Function(script)();
    // The initial cards are built by annotation.js's populateCardSort, which
    // delegates to the exported createCard. Do the same here.
    const source = document.getElementById('outcomes-source-items');
    ['serious adverse events', 'blood pressure'].forEach(text => {
        source.appendChild(window._cardSortCreateCard(text, 'outcomes', '__source__'));
    });
    window._cardSortBindZones('outcomes');
    return source;
}

const held = () => document.querySelector('.card-sort-card.card-sort-held');
const groupOf = name => document.querySelector(`[data-drop-group="${name}"]`);
const textsIn = name => [...groupOf(name).querySelectorAll('.card-sort-card')]
    .map(c => c.dataset.cardText);
const live = () => document.getElementById('outcomes-live').textContent;

function press(el, key) {
    el.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true, cancelable: true}));
}

describe('every card is reachable and announced', () => {
    beforeEach(mount);

    test('cards are focusable and expose a role', () => {
        const card = document.querySelector('.card-sort-card');
        expect(card.getAttribute('tabindex')).toBe('0');
        expect(card.getAttribute('role')).toBe('button');
        expect(card.getAttribute('aria-pressed')).toBe('false');
    });

    test('the label says what the card is and where it is', () => {
        const card = document.querySelector('.card-sort-card');
        expect(card.getAttribute('aria-label'))
            .toBe('serious adverse events. In the unsorted list. Press Enter to pick it up.');
    });

    test('every drop zone is focusable and labelled, including the source', () => {
        const zones = [...document.querySelectorAll('[data-drop-group]')];
        expect(zones.map(z => z.getAttribute('data-drop-group')))
            .toEqual(['__source__', 'Critical', 'Important']);
        zones.forEach(z => {
            expect(z.getAttribute('tabindex')).toBe('0');
            expect(z.getAttribute('aria-label')).toBeTruthy();
        });
    });

    test('the keyboard path is described on the page, not just implemented', () => {
        const hint = document.getElementById('outcomes-kbd-hint')
            .textContent.replace(/\s+/g, ' ');
        expect(hint).toMatch(/press Enter to pick it up/i);
        expect(hint).toMatch(/Escape to put it back down/i);
    });
});

describe('picking a card up and dropping it', () => {
    beforeEach(mount);

    test('Enter picks up, and says so', () => {
        const card = document.querySelector('.card-sort-card');
        press(card, 'Enter');
        expect(held()).toBe(card);
        expect(card.getAttribute('aria-pressed')).toBe('true');
        expect(live()).toMatch(/Picked up serious adverse events/);
    });

    test('Enter on a group moves the held card there', () => {
        press(document.querySelector('.card-sort-card'), 'Enter');
        press(groupOf('Critical'), 'Enter');

        expect(textsIn('Critical')).toEqual(['serious adverse events']);
        expect(live()).toBe('Moved serious adverse events to Critical.');
        expect(held()).toBeNull();
    });

    test('the moved card keeps focus, so the next Tab starts from there', () => {
        press(document.querySelector('.card-sort-card'), 'Enter');
        press(groupOf('Critical'), 'Enter');

        expect(document.activeElement.dataset.cardText).toBe('serious adverse events');
    });

    test('a number key sends a card straight to that group', () => {
        // 1 is the first group on screen; the unsorted list is not numbered.
        press(document.querySelector('.card-sort-card'), '1');
        expect(textsIn('Critical')).toEqual(['serious adverse events']);
        expect(held()).toBeNull();
    });

    test('the numbers follow the order the groups appear in', () => {
        press(document.querySelector('.card-sort-card'), '2');
        expect(textsIn('Important')).toEqual(['serious adverse events']);
        expect(textsIn('Critical')).toEqual([]);
    });

    test('a number with no group behind it does nothing', () => {
        press(document.querySelector('.card-sort-card'), '9');
        expect(textsIn('Critical')).toEqual([]);
        expect(textsIn('Important')).toEqual([]);
        expect(held()).toBeNull();
    });

    test('Escape puts the card back down without moving it', () => {
        const card = document.querySelector('.card-sort-card');
        press(card, 'Enter');
        press(card, 'Escape');

        expect(held()).toBeNull();
        expect(textsIn('Critical')).toEqual([]);
        expect(live()).toMatch(/back down/);
    });

    test('Enter twice on the same card is a pick up then a put down', () => {
        const card = document.querySelector('.card-sort-card');
        press(card, 'Enter');
        press(card, 'Enter');
        expect(held()).toBeNull();
    });

    test('a card can be sent back to the unsorted list', () => {
        press(document.querySelector('.card-sort-card'), 'Enter');
        press(groupOf('Critical'), 'Enter');
        press(groupOf('Critical').querySelector('.card-sort-card'), 'Enter');
        press(groupOf('__source__'), 'Enter');

        expect(textsIn('Critical')).toEqual([]);
        expect(textsIn('__source__').length).toBe(2);
    });

    test('the moved card reports its new group to a screen reader', () => {
        press(document.querySelector('.card-sort-card'), 'Enter');
        press(groupOf('Critical'), 'Enter');

        expect(groupOf('Critical').querySelector('.card-sort-card')
            .getAttribute('aria-label')).toBe(
            'serious adverse events. In Critical. Press Enter to pick it up.');
    });

    test('Enter on a group with nothing held does nothing', () => {
        press(groupOf('Critical'), 'Enter');
        expect(textsIn('Critical')).toEqual([]);
        expect(live()).toBe('');
    });
});

describe('the held state ends when the move does', () => {
    beforeEach(mount);

    const holding = () => document.getElementById('outcomes')
        .classList.contains('card-sort-holding');

    test('picking up arms the drop zones', () => {
        press(document.querySelector('.card-sort-card'), 'Enter');
        expect(holding()).toBe(true);
    });

    test('completing a move disarms them again', () => {
        // `.card-sort-holding` is what dashes every drop zone border. Left on
        // after a drop, the one signal that means "a card is in the air, choose
        // a target" stayed on for the rest of the item and meant nothing.
        press(document.querySelector('.card-sort-card'), 'Enter');
        press(groupOf('Critical'), 'Enter');
        expect(holding()).toBe(false);
    });

    test('a number-key move disarms them too', () => {
        press(document.querySelector('.card-sort-card'), '1');
        expect(holding()).toBe(false);
    });

    test('Escape disarms them', () => {
        const card = document.querySelector('.card-sort-card');
        press(card, 'Enter');
        press(card, 'Escape');
        expect(holding()).toBe(false);
    });

    test('dropping a card onto the group it is already in disarms them', () => {
        press(document.querySelector('.card-sort-card'), 'Enter');
        press(groupOf('__source__'), 'Enter');
        expect(holding()).toBe(false);
    });
});

describe('the answer is written where the page reads it', () => {
    beforeEach(mount);

    test('a keyboard move updates the hidden input and flags it modified', () => {
        press(document.querySelector('.card-sort-card'), 'Enter');
        press(groupOf('Critical'), 'Enter');

        const input = document.querySelector('#outcomes .card-sort-data-input');
        expect(JSON.parse(input.value)).toEqual({
            Critical: ['serious adverse events'], Important: [],
        });
        expect(input.getAttribute('data-modified')).toBe('true');
    });
});

describe('the pointer path still works, and does not double-fire', () => {
    beforeEach(mount);

    test('a real click picks a card up (this is also the touch path)', () => {
        const card = document.querySelector('.card-sort-card');
        card.dispatchEvent(new MouseEvent('click', {bubbles: true, detail: 1}));
        expect(held()).toBe(card);
    });

    test('the synthetic click that follows Enter is ignored', () => {
        // Pressing Enter on a role="button" fires keydown *and* a click with
        // detail 0. Without the guard the card was picked up and put straight
        // back down, and the keyboard path did nothing at all.
        const card = document.querySelector('.card-sort-card');
        press(card, 'Enter');
        card.dispatchEvent(new MouseEvent('click', {bubbles: true, detail: 0}));
        expect(held()).toBe(card);
    });

    test('clicking a group drops the held card', () => {
        const card = document.querySelector('.card-sort-card');
        card.dispatchEvent(new MouseEvent('click', {bubbles: true, detail: 1}));
        groupOf('Critical').dispatchEvent(new MouseEvent('click', {bubbles: true, detail: 1}));
        expect(textsIn('Critical')).toEqual(['serious adverse events']);
    });
});

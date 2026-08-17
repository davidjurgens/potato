/**
 * Where a floating annotation card is allowed to land.
 *
 * The placement helper scores candidate positions against everything the
 * annotator needs to reach. It was counting those equally, which made
 * "cover the navbar" and "cover Next" the same price — so Boundary Lab's
 * expanded flip form, too tall to sit at its authored anchor without covering
 * Next, cleared Next by climbing over the header instead. Observed live at
 * 1500x812: the card ran from y=30 to y=455, burying progress, the jump box
 * and Logout.
 *
 * jsdom does no layout, so geometry is injected. That is the right level for
 * this: place() is arithmetic over rectangles, and the bug was in the
 * arithmetic, not in the measuring.
 */

require('../../potato/static/floating-panel-utils.js');

const VIEWPORT_H = 812;
let VIEWPORT_W = 1500;

/** Give an element a fixed layout box that place() can read. */
function withBox(el, { left, top, width, height }) {
    el.getBoundingClientRect = () => ({
        left, top, width, height,
        right: left + width, bottom: top + height, x: left, y: top,
    });
    Object.defineProperty(el, 'offsetWidth', { value: width, configurable: true });
    Object.defineProperty(el, 'offsetHeight', { value: height, configurable: true });
    return el;
}

function overlaps(a, b) {
    return !(a.right <= b.left || a.left >= b.right ||
             a.bottom <= b.top || a.top >= b.bottom);
}

/** Where place() actually put the card, in viewport coordinates. */
function placedBox(panel, width, height) {
    const bottom = parseFloat(panel.style.bottom);
    const left = parseFloat(panel.style.left);
    return {
        left, right: left + width,
        top: VIEWPORT_H - bottom - height,
        bottom: VIEWPORT_H - bottom,
    };
}

function setUpPage({ panelHeight, panelWidth = 400, viewportW = 1500 }) {
    VIEWPORT_W = viewportW;
    document.body.innerHTML = '';
    Object.defineProperty(document.documentElement, 'clientWidth',
        { value: VIEWPORT_W, configurable: true });
    Object.defineProperty(document.documentElement, 'clientHeight',
        { value: VIEWPORT_H, configurable: true });

    const navbar = document.createElement('nav');
    navbar.className = 'potato-navbar';
    withBox(navbar, { left: 0, top: 0, width: VIEWPORT_W, height: 54 });
    document.body.appendChild(navbar);

    const next = document.createElement('button');
    next.id = 'next-btn';
    withBox(next, { left: VIEWPORT_W - 414, top: 468, width: 96, height: 44 });
    document.body.appendChild(next);

    // A column of label radios down the middle of the form.
    const inputs = [];
    for (let i = 0; i < 3; i++) {
        const input = document.createElement('input');
        input.className = 'annotation-input';
        withBox(input, { left: 330, top: 320 + i * 33, width: 16, height: 16 });
        document.body.appendChild(input);
        inputs.push(input);
    }

    const panel = document.createElement('div');
    panel.className = 'boundary-panel';
    // The authored anchor: right: 20px, bottom: 20px.
    withBox(panel, {
        left: VIEWPORT_W - panelWidth - 20,
        top: VIEWPORT_H - panelHeight - 20,
        width: panelWidth, height: panelHeight,
    });
    document.body.appendChild(panel);

    // place() resets the inline anchor and re-reads computed bottom.
    window.getComputedStyle = () => ({
        display: 'block', visibility: 'visible', bottom: '20px',
    });

    return { navbar, next, inputs, panel };
}

describe('a card tall enough to collide has to give something up', () => {
    const PANEL_H = 425;   // the expanded flip form, measured
    let page, box;

    beforeEach(() => {
        page = setUpPage({ panelHeight: PANEL_H });
        window.potatoFloatingPanel.place(page.panel);
        box = placedBox(page.panel, 400, PANEL_H);
    });

    test('it does not take the navbar', () => {
        expect(overlaps(box, page.navbar.getBoundingClientRect())).toBe(false);
    });

    test('it does not take Next', () => {
        expect(overlaps(box, page.next.getBoundingClientRect())).toBe(false);
    });

    test('it stays inside the viewport', () => {
        expect(box.top).toBeGreaterThanOrEqual(0);
        expect(box.bottom).toBeLessThanOrEqual(VIEWPORT_H);
        expect(box.left).toBeGreaterThanOrEqual(0);
        expect(box.right).toBeLessThanOrEqual(VIEWPORT_W);
    });
});

describe('an uncrowded page keeps the authored design', () => {
    test('a short card stays at its CSS anchor', () => {
        const page = setUpPage({ panelHeight: 180 });
        window.potatoFloatingPanel.place(page.panel);
        const box = placedBox(page.panel, 400, 180);
        // bottom: 20px, right: 20px — nothing moved it.
        expect(VIEWPORT_H - box.bottom).toBe(20);
        expect(VIEWPORT_W - box.right).toBe(20);
        expect(overlaps(box, page.next.getBoundingClientRect())).toBe(false);
    });
});

describe('given room, it costs nothing at all', () => {
    test('a wide viewport has a spot that covers none of it', () => {
        const page = setUpPage({ panelHeight: 425 });
        window.potatoFloatingPanel.place(page.panel);
        const box = placedBox(page.panel, 400, 425);
        const covered = [page.navbar, page.next, ...page.inputs]
            .filter((el) => overlaps(box, el.getBoundingClientRect()));
        expect(covered).toHaveLength(0);
    });
});

describe('weighting, not counting', () => {
    /**
     * Narrow enough that the card cannot dodge sideways, so a real choice has
     * to be made. Counting rects picks "cover Next" (1 rect) over "cover three
     * radios" (3 rects) — which is the wrong way round, and is what shipped.
     */
    test('three radios are a cheaper loss than one Next button', () => {
        const page = setUpPage({ panelHeight: 340, viewportW: 520 });
        window.potatoFloatingPanel.place(page.panel);
        const box = placedBox(page.panel, 400, 340);

        expect(overlaps(box, page.navbar.getBoundingClientRect())).toBe(false);
        expect(overlaps(box, page.next.getBoundingClientRect())).toBe(false);
        expect(page.inputs.some((i) => overlaps(box, i.getBoundingClientRect())))
            .toBe(true);
    });
});

describe('nothing to protect', () => {
    test('a bare page leaves the card alone', () => {
        document.body.innerHTML = '';
        const panel = document.createElement('div');
        withBox(panel, { left: 1080, top: 600, width: 400, height: 180 });
        document.body.appendChild(panel);
        window.potatoFloatingPanel.place(panel);
        expect(panel.style.bottom).toBe('');
    });
});

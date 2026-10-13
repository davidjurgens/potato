/**
 * A span highlight must not make the words it labels hard to read.
 *
 * The highlight segment is painted ON TOP of the text. /api/colors sends label
 * colours at alpha 0.8 -- the value label chips and image tools want -- and
 * createOverlay used to paint that straight onto the text. The covered words
 * then measured 1.7:1 in the worst palette colour (about 2:1 for the default
 * purple): the text being annotated was the least readable text on the page.
 *
 * The annotation surface's bar for text read all day is 7:1 (.impeccable.md).
 */

const {
    SpanManager, UnifiedPositioningStrategy, spanFillColour, spanEdgeColour, SPAN_FILL_ALPHA,
} = require('../../potato/static/span-core.js');

const PAGE_BG = [245, 247, 251];   // --light-bg, behind #instance-text
const CARD_BG = [255, 255, 255];
const TEXT = [9, 9, 11];           // --foreground

const lin = (v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
};
const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
const over = (top, alpha, bottom) => top.map((t, i) => alpha * t + (1 - alpha) * bottom[i]);
const parts = (css) => css.match(/[\d.]+/g).map(Number);

/** Contrast of TEXT under a segment filled with `fill`, on `bg`. */
function coveredContrast(fill, bg) {
    const [r, g, b, a] = parts(fill);
    const background = over([r, g, b], a, bg);
    const text = over([r, g, b], a, TEXT);
    const hi = Math.max(lum(background), lum(text));
    const lo = Math.min(lum(background), lum(text));
    return (hi + 0.05) / (lo + 0.05);
}

// What /api/colors actually sends for every palette entry.
const SERVER_COLOURS = SpanManager.FALLBACK_PALETTE.map(
    (triple) => `rgba${triple.replace(')', ', 0.8)')}`);

describe('highlight fill', () => {
    test.each(SERVER_COLOURS)('%s keeps the covered text at 7:1', (colour) => {
        const fill = spanFillColour(colour);
        expect(coveredContrast(fill, PAGE_BG)).toBeGreaterThanOrEqual(7);
        expect(coveredContrast(fill, CARD_BG)).toBeGreaterThanOrEqual(7);
    });

    test('the old behaviour (fill = server colour) fails the same check', () => {
        // Guard for the guard: painting the 0.8 colour unchanged is the bug.
        const worst = Math.min(...SERVER_COLOURS.map((c) => coveredContrast(c, PAGE_BG)));
        expect(worst).toBeLessThan(3);
    });

    test('keeps the label hue', () => {
        expect(spanFillColour('rgba(34, 197, 94, 0.8)'))
            .toBe(`rgba(34, 197, 94, ${SPAN_FILL_ALPHA})`);
    });

    test('never raises an alpha that is already lower', () => {
        expect(spanFillColour('rgba(110, 86, 207, 0.15)')).toBe('rgba(110, 86, 207, 0.15)');
    });

    test('accepts every format the colour map can hold', () => {
        expect(spanFillColour('(239, 68, 68)')).toBe(`rgba(239, 68, 68, ${SPAN_FILL_ALPHA})`);
        expect(spanFillColour('#6e56cf')).toBe(`rgba(110, 86, 207, ${SPAN_FILL_ALPHA})`);
        expect(spanFillColour('#abc')).toBe(`rgba(170, 187, 204, ${SPAN_FILL_ALPHA})`);
        expect(spanFillColour('rgb(1, 2, 3)')).toBe(`rgba(1, 2, 3, ${SPAN_FILL_ALPHA})`);
        // A named colour cannot be parsed; it is still thinned, not painted solid.
        expect(spanFillColour('gold')).toContain('color-mix');
    });

    test('the outline stays strong enough to show the span extent', () => {
        expect(spanEdgeColour('rgba(110, 86, 207, 0.15)')).toBe('rgba(110, 86, 207, 0.8)');
    });
});

describe('createOverlay paints the capped fill', () => {
    function overlayFor(colour, extra = {}) {
        document.body.innerHTML = '<div id="instance-text"></div>';
        const m = Object.create(UnifiedPositioningStrategy.prototype);
        const span = { id: 's1', label: 'certain', schema: 'certainty', start: 0, end: 7, ...extra };
        return m.createOverlay(span, [{ x: 10, y: 30, width: 60, height: 20 }], { color: colour });
    }

    test('a regular span segment is filled at no more than the cap', () => {
        const overlay = overlayFor('rgba(110, 86, 207, 0.8)');
        const segment = overlay.querySelector('.span-highlight-segment');
        const alpha = parts(segment.style.backgroundColor)[3];
        expect(alpha).toBeLessThanOrEqual(SPAN_FILL_ALPHA);
    });

    test('the delete control is a named button', () => {
        const overlay = overlayFor('rgba(110, 86, 207, 0.8)');
        const del = overlay.querySelector('.span-delete-btn');
        expect(del.type).toBe('button');
        expect(del.getAttribute('aria-label')).toBe('Remove certain span');
        // No inline colour: span-styles.css paints it --destructive-text (checked
        // in the browser by tests/selenium/test_span_highlight_contrast_ui.py).
        expect(del.style.backgroundColor).toBe('');
    });

    test('the chip is a fixed 18px and sits above the segment, not on it', () => {
        const overlay = overlayFor('rgba(110, 86, 207, 0.8)');
        const controls = overlay.querySelector('.span-controls');
        const segment = overlay.querySelector('.span-highlight-segment');
        const chipTop = parseFloat(controls.style.top);
        const chipHeight = parseFloat(controls.style.height);
        const segTop = parseFloat(segment.style.top);
        expect(chipHeight).toBe(18);
        // Bottom of the chip clears the glyph top (segment top + 2px padding).
        expect(chipTop + chipHeight).toBeLessThan(segTop + 2);
    });
});

/**
 * A double-click finishes a polygon, and it must not leave the last vertex
 * behind three times.
 *
 * A real double-click is mousedown/up, mousedown/up, THEN `dblclick`. Both of
 * those extra downs run through `_addPolygonPoint` before `mouse:dblclick`
 * completes the shape, so an annotator drawing a triangle produced FIVE
 * vertices — the final one repeated. Invisible on screen, wrong in the data:
 * vertex counts, exports and any polygon measure that walks vertices all see a
 * different shape from the one drawn.
 *
 * It hid because the Jest tests built point lists directly and the first Chrome
 * pass dispatched a bare `dblclick` — a gesture no browser produces. Only
 * Playwright's real `dblclick` reproduced it.
 *
 * The tolerance is the interesting part: the pointer drifts a pixel or two
 * between the two clicks of a double-click, so exact equality would miss most
 * of them, and too generous a window would eat vertices an annotator meant.
 */

require('../../potato/static/mask-buffer.js');
const ImageAnnotationManager = require('../../potato/static/image-annotation.js');

/** Just enough manager to call the trimmer. */
function trimmer() {
    return Object.create(ImageAnnotationManager.prototype);
}

function trim(points, tolerance) {
    return trimmer()._withoutTrailingDuplicates(points, tolerance);
}

const P = (x, y) => ({ x, y });

describe('trailing duplicates from a double-click', () => {
    test('a triangle finished by double-clicking keeps three vertices', () => {
        // Exactly what the DOM delivers: three deliberate clicks, then the two
        // downs of the double-click on the same spot.
        const drawn = [P(10, 10), P(90, 20), P(50, 80), P(50, 80), P(50, 80)];
        expect(trim(drawn)).toEqual([P(10, 10), P(90, 20), P(50, 80)]);
    });

    test('a two-point polyline survives the same gesture', () => {
        const drawn = [P(10, 10), P(90, 20), P(90, 20), P(90, 20)];
        expect(trim(drawn)).toEqual([P(10, 10), P(90, 20)]);
    });

    test('a pixel of drift between the two clicks still counts as a repeat', () => {
        const drawn = [P(10, 10), P(90, 20), P(50, 80), P(51, 81), P(51, 79)];
        expect(trim(drawn)).toEqual([P(10, 10), P(90, 20), P(51, 79)]);
    });

    test('the kept vertex is the LAST position, not the first of the run', () => {
        // The final mouseup is where the annotator's pointer actually ended.
        const drawn = [P(10, 10), P(90, 20), P(50, 80), P(51, 81)];
        expect(trim(drawn).pop()).toEqual(P(51, 81));
    });
});

describe('what must not be trimmed', () => {
    test('deliberate vertices further apart than the tolerance are kept', () => {
        const drawn = [P(10, 10), P(90, 20), P(50, 80), P(56, 86)];
        expect(trim(drawn)).toHaveLength(4);
    });

    test('a repeat in the MIDDLE is the annotator’s business', () => {
        // Only a run at the end is the closing gesture; clicking twice in one
        // spot mid-path is a choice, and silently rewriting it would be worse
        // than the duplicate.
        const drawn = [P(10, 10), P(50, 50), P(50, 50), P(90, 20)];
        expect(trim(drawn)).toEqual(drawn);
    });

    test('a shape with no repeats is returned unchanged', () => {
        const drawn = [P(10, 10), P(90, 20), P(50, 80)];
        expect(trim(drawn)).toEqual(drawn);
    });

    test('a single point is never trimmed away to nothing', () => {
        expect(trim([P(10, 10)])).toEqual([P(10, 10)]);
        expect(trim([])).toEqual([]);
    });

    test('it does not mutate the list it was given', () => {
        const drawn = [P(10, 10), P(90, 20), P(50, 80), P(50, 80)];
        const copy = drawn.map(p => ({ ...p }));
        trim(drawn);
        expect(drawn).toEqual(copy);
    });
});

describe('the control', () => {
    test('without trimming, the double-click gesture yields five vertices', () => {
        // Proves the assertions above are load-bearing: this is the shape the
        // browser actually produced before the fix.
        const drawn = [P(10, 10), P(90, 20), P(50, 80), P(50, 80), P(50, 80)];
        expect(drawn).toHaveLength(5);
        expect(trim(drawn)).toHaveLength(3);
    });
});

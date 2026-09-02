/**
 * How a Boundary Lab probe presents its edited text.
 *
 * Driven live in Chrome, an invariance probe rendered like this:
 *
 *   HiHello Sam, couldwould you be able to send meover the Q3 report
 *   whenwhenever you gethave a chance? Nomoment? rushAbsolutely atno allhurry
 *
 * — a word-level diff of a full paraphrase, interleaving both versions. The
 * annotator is being asked whether their label survives that rewording and
 * cannot read the rewording. A word diff earns its place on a *minimal* edit
 * and nowhere else, so the decision is made on how much of the text moved.
 *
 * These tests drive the real renderer rather than a fixture: they assert on
 * what probeText() actually returns for probes of each shape.
 */

const boundary = require('../../potato/static/boundary-probe.js');

const ORIGINAL =
    "Hi Sam, could you send me the Q3 report when you get a chance? " +
    "No rush at all — thanks so much!";

/** The real flip probe from examples/advanced/boundary-probing. */
const MINIMAL_EDIT = {
    kind: 'flip',
    original_text: ORIGINAL,
    text:
        "Hi Sam, could you send me the Q3 report when you get a chance? " +
        "This is the third time I'm asking — thanks so much!",
};

/** The real invariance probe from the same file. */
const PARAPHRASE = {
    kind: 'invariance',
    original_text: ORIGINAL,
    text:
        "Hello Sam, would you be able to send over the Q3 report whenever you " +
        "have a moment? Absolutely no hurry — thank you!",
};

/** Strip tags the way a reader sees the text. */
function textOf(html) {
    const el = document.createElement('div');
    el.innerHTML = html;
    return el.textContent;
}

describe('churn measurement', () => {
    test('a one-phrase edit leaves most of the sentence standing', () => {
        const d = boundary.diffWords(ORIGINAL, MINIMAL_EDIT.text);
        expect(d.churn).toBeLessThanOrEqual(boundary.DIFF_CHURN_LIMIT);
    });

    test('a paraphrase moves most of it', () => {
        const d = boundary.diffWords(ORIGINAL, PARAPHRASE.text);
        expect(d.churn).toBeGreaterThan(boundary.DIFF_CHURN_LIMIT);
    });

    test('identical text has no churn and no markup', () => {
        const d = boundary.diffWords(ORIGINAL, ORIGINAL);
        expect(d.churn).toBe(0);
        expect(d.html).not.toMatch(/<(del|ins)>/);
    });
});

describe('a minimal edit is still shown as a diff', () => {
    const shown = boundary.probeText(MINIMAL_EDIT);

    test('it marks what was removed and what replaced it', () => {
        expect(shown.minimal).toBe(true);
        expect(shown.html).toContain('<del>');
        expect(shown.html).toContain('<ins>');
    });

    test('the unchanged part is not marked up', () => {
        expect(shown.html).toContain('Hi Sam, could you send me the Q3 report');
    });
});

describe('a paraphrase is shown whole, both versions', () => {
    const shown = boundary.probeText(PARAPHRASE);

    test('it is not a diff', () => {
        expect(shown.minimal).toBe(false);
        expect(shown.html).not.toMatch(/<(del|ins)>/);
    });

    test('the reworded sentence is readable end to end', () => {
        // The exact string, uninterrupted — the thing the diff destroyed.
        expect(textOf(shown.html)).toContain(PARAPHRASE.text);
    });

    test('the original is kept alongside it, so the two can be compared', () => {
        expect(textOf(shown.html)).toContain(ORIGINAL);
        expect(shown.html).toContain('boundary-textblock is-original');
        expect(shown.html).toContain('boundary-textblock is-edited');
    });

    test('each block says which version it is', () => {
        expect(textOf(shown.html)).toContain('Original');
        expect(textOf(shown.html)).toContain('Reworded');
    });

    test('which is necessary: diffing it destroys the sentence', () => {
        // Guards the reason for the fallback. If someone decides the diff is
        // fine after all, this is the evidence they have to argue with.
        const diffed = textOf(boundary.diffWords(ORIGINAL, PARAPHRASE.text).html);
        expect(diffed).not.toContain(PARAPHRASE.text);
        expect(diffed).toContain('HiHello');
    });
});

describe('a heavily rewritten flip probe also drops the diff', () => {
    const REWRITE = {
        kind: 'flip',
        original_text: ORIGINAL,
        text: 'Send the Q3 report. Now. This is the last time I ask.',
    };
    const shown = boundary.probeText(REWRITE);

    test('kind alone does not decide it — churn does', () => {
        expect(shown.minimal).toBe(false);
        expect(textOf(shown.html)).toContain(REWRITE.text);
    });

    test('and it is labelled Edited rather than Reworded', () => {
        expect(textOf(shown.html)).toContain('Edited');
    });
});

describe('text is escaped on both paths', () => {
    const NASTY = '<img src=x onerror=alert(1)>';

    test('in the diff', () => {
        const shown = boundary.probeText({
            kind: 'flip', original_text: 'a b c d e f g h', text: 'a b c d e f g ' + NASTY,
        });
        expect(shown.html).not.toContain('<img');
        expect(shown.html).toContain('&lt;img');
    });

    test('in the whole-text pair', () => {
        const shown = boundary.probeText({
            kind: 'invariance', original_text: 'a b c', text: NASTY,
        });
        expect(shown.html).not.toContain('<img');
        expect(shown.html).toContain('&lt;img');
    });
});

describe('missing original text does not throw', () => {
    test('falls back to the stored instance text', () => {
        boundary._setOriginalText(ORIGINAL);
        const shown = boundary.probeText({ kind: 'invariance', text: PARAPHRASE.text });
        expect(textOf(shown.html)).toContain(ORIGINAL);
    });

    test('and survives having neither', () => {
        boundary._setOriginalText(null);
        const shown = boundary.probeText({ kind: 'flip', text: 'anything at all' });
        expect(textOf(shown.html)).toContain('anything at all');
    });
});

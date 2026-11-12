/**
 * Video shortcuts must not collide across handlers.
 *
 * `video-annotation.js` and `tracking-ui.js` both bind keydown on `document`,
 * so a key claimed by both fires BOTH. Two such collisions were introduced and
 * caught during Wave 4:
 *
 *   `.`      already frame-stepping -- would have stepped a frame AND jumped
 *            to the next keyframe on one press
 *   `Ctrl+K` `case 'k'` had no modifier guard, so the tracking keyframe and
 *            the mode keyframe both fired
 *
 * A collision is invisible in unit tests of either file alone, and in a browser
 * it looks like the video "jumping" rather than like a shortcut bug. So the key
 * tables are asserted against each other directly, from the source.
 */

const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..', '..', 'potato', 'static');
const videoSource = fs.readFileSync(path.join(root, 'video-annotation.js'), 'utf8');
const trackingSource = fs.readFileSync(path.join(root, 'tracking-ui.js'), 'utf8');

/** Unmodified single-letter/punctuation keys video-annotation.js claims. */
function videoSwitchKeys(source) {
    const keys = new Set();
    const re = /case\s+'([^']{1,10})':/g;
    let match;
    while ((match = re.exec(source)) !== null) {
        keys.add(match[1]);
    }
    return keys;
}

describe('video-annotation.js key table', () => {
    const keys = videoSwitchKeys(videoSource);

    test('it still owns frame stepping on , and .', () => {
        expect(keys.has(',')).toBe(true);
        expect(keys.has('.')).toBe(true);
    });

    test('it still owns plain k', () => {
        expect(keys.has('k')).toBe(true);
    });
});

describe('tracking-ui.js does not take keys video already owns', () => {
    test('keyframe navigation is shifted, not plain , and .', () => {
        // The unshifted pair belongs to frame stepping.
        expect(trackingSource).toMatch(/e\.key === '<' \|\| e\.key === '>'/);
        expect(trackingSource).toMatch(/e\.shiftKey/);
    });

    test('the plain , and . keys are never handled unconditionally', () => {
        /**
         * Guards against a future edit reintroducing `if (e.key === ',')`
         * without the shift check.
         */
        const unguarded = /if\s*\(\s*e\.key === ','\s*\|\|\s*e\.key === '\.'\s*\)/;
        expect(unguarded.test(trackingSource)).toBe(false);
    });

    test('setKeyframeHere requires a modifier', () => {
        expect(trackingSource).toMatch(/e\.key === 'k' && \(e\.ctrlKey \|\| e\.metaKey\)/);
    });

    test('new-track uses t and explicitly excludes the modified press', () => {
        expect(trackingSource).toMatch(/e\.key === 't' && !e\.ctrlKey && !e\.metaKey/);
    });
});

describe('video-annotation.js guards its letter shortcuts against modifiers', () => {
    test("case 'k' breaks out on ctrl or meta", () => {
        /**
         * Without this, Ctrl+K fires the mode keyframe as well as the tracking
         * one -- the second collision found in Wave 4.
         */
        const kBlock = videoSource.slice(videoSource.indexOf("case 'k':"),
                                         videoSource.indexOf("case 'c':"));
        expect(kBlock).toMatch(/ctrlKey \|\| event\.metaKey/);
    });
});

describe('both handlers ignore keystrokes aimed at text fields', () => {
    test('tracking-ui checks the active element', () => {
        expect(trackingSource).toMatch(/document\.activeElement/);
        expect(trackingSource).toMatch(/isContentEditable/);
        expect(trackingSource).toMatch(/SELECT/);
    });

    test('video-annotation checks the event target', () => {
        expect(videoSource).toMatch(/tagName === 'INPUT' \|\| event\.target\.tagName === 'TEXTAREA'/);
    });
});

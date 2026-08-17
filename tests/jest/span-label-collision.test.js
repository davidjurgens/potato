/**
 * Overlapping codes must not bury the text they are about.
 *
 * Each span draws a label chip in the strip above its first line, anchored at
 * the span's start. Coding one sentence with five overlapping codes — routine
 * in qualitative work — drew five wide chips across the same strip. Observed
 * live: "I couldn't get an appointment for almost three weeks" was completely
 * hidden behind five "access barriers" chips.
 *
 * Two things fix it, and both are tested here: the gutter the chips live in
 * (so a chip never lands on the line above), and collapsing the chips that
 * would still collide with each other.
 */

const { SpanManager } = require('../../potato/static/span-core.js');

const box = (left, top, width = 110, height = 18) => ({
    left, top, right: left + width, bottom: top + height,
});

describe('planning which chips collapse', () => {
    test('chips that do not touch all keep their text', () => {
        const plan = SpanManager.planControlCompaction([
            box(0, 0), box(200, 0), box(400, 0),
        ]);
        expect(plan).toEqual([false, false, false]);
    });

    test('the first of a collision keeps its text, the rest collapse', () => {
        // Five codes on one passage: what actually happened in the browser.
        const plan = SpanManager.planControlCompaction([
            box(10, 100), box(14, 100), box(20, 100), box(12, 100), box(18, 100),
        ]);
        expect(plan).toEqual([false, true, true, true, true]);
    });

    test('chips on different lines do not collide', () => {
        const plan = SpanManager.planControlCompaction([
            box(10, 100), box(10, 140), box(10, 180),
        ]);
        expect(plan).toEqual([false, false, false]);
    });

    test('a chip may keep its text if it clears the one before it', () => {
        const plan = SpanManager.planControlCompaction([
            box(10, 100), box(15, 100), box(300, 100),
        ]);
        expect(plan).toEqual([false, true, false]);
    });

    test('collision is measured against kept chips, not collapsed ones', () => {
        // Third chip clears the first, but overlaps the (collapsed) second.
        // It should still keep its text: a dot is not something to dodge.
        const plan = SpanManager.planControlCompaction([
            box(0, 0), box(50, 0), box(140, 0),
        ]);
        expect(plan).toEqual([false, true, false]);
    });

    test('edge-touching chips are not a collision', () => {
        const plan = SpanManager.planControlCompaction([
            box(0, 0, 100), box(100, 0, 100),
        ]);
        expect(plan).toEqual([false, false]);
    });

    test('nothing to plan', () => {
        expect(SpanManager.planControlCompaction([])).toEqual([]);
        expect(SpanManager.planControlCompaction(null)).toEqual([]);
    });
});

describe('applying the plan to rendered chips', () => {
    function overlaysWith(boxes) {
        document.body.innerHTML = '<div id="span-overlays"></div>';
        const host = document.getElementById('span-overlays');
        boxes.forEach((b, i) => {
            const controls = document.createElement('div');
            controls.className = 'span-controls';
            controls.dataset.index = String(i);
            controls.getBoundingClientRect = () => b;
            host.appendChild(controls);
        });
        return host;
    }

    const manager = () => Object.create(SpanManager.prototype);

    test('collided chips are marked compact', () => {
        const host = overlaysWith([box(10, 100), box(14, 100), box(600, 100)]);
        manager().applyControlCompaction(host);
        const marked = Array.from(host.querySelectorAll('.span-controls'))
            .map((c) => c.classList.contains('is-compact'));
        expect(marked).toEqual([false, true, false]);
    });

    test('a single chip is never compacted', () => {
        const host = overlaysWith([box(10, 100)]);
        manager().applyControlCompaction(host);
        expect(host.querySelector('.span-controls').classList.contains('is-compact'))
            .toBe(false);
    });

    test('re-rendering re-measures from the expanded state', () => {
        // If a chip stayed compact across renders, the second pass would
        // measure a dot and wrongly conclude there was room for everything.
        const host = overlaysWith([box(10, 100), box(14, 100)]);
        const m = manager();
        m.applyControlCompaction(host);
        m.applyControlCompaction(host);
        const marked = Array.from(host.querySelectorAll('.span-controls'))
            .map((c) => c.classList.contains('is-compact'));
        expect(marked).toEqual([false, true]);
    });

    test('an absent overlay container is not an error', () => {
        expect(() => manager().applyControlCompaction(null)).not.toThrow();
    });
});

describe('the gutter the chips live in', () => {
    function page(showLabels) {
        document.body.innerHTML = `
            <form class="annotation-form span"
                  ${showLabels ? '' : 'data-show-span-labels="false"'}></form>
            <div id="instance-text"></div>`;
        return document.getElementById('instance-text');
    }

    test('is opened when labels are drawn', () => {
        const text = page(true);
        Object.create(SpanManager.prototype).applyLabelGutter();
        expect(text.classList.contains('span-labels-on')).toBe(true);
    });

    test('is left closed when the task hides labels', () => {
        const text = page(false);
        Object.create(SpanManager.prototype).applyLabelGutter();
        expect(text.classList.contains('span-labels-on')).toBe(false);
    });

    test('covers every field container in multi-field mode', () => {
        document.body.innerHTML = `
            <form class="annotation-form span"></form>
            <div id="text-content-body"></div>
            <div id="text-content-title"></div>`;
        Object.create(SpanManager.prototype).applyLabelGutter();
        expect(document.getElementById('text-content-body')
            .classList.contains('span-labels-on')).toBe(true);
        expect(document.getElementById('text-content-title')
            .classList.contains('span-labels-on')).toBe(true);
    });
});

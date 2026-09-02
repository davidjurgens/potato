/**
 * Episode timeline arithmetic: the time axis, the segmentation, the curve.
 *
 * The defect this file is written against is a **segmentation that stops being
 * one**. Overlapping phases make "what was the robot doing at t?" ambiguous,
 * and they break the temporal-IoU agreement silently, because that measure
 * assumes a partition. Every insertion path is checked for it.
 */

const Manager = require('../../potato/static/episode-timeline.js');

describe('the time axis', () => {
    test('maps seconds to pixels linearly', () => {
        expect(Manager.timeToX(0, 10, 500)).toBe(0);
        expect(Manager.timeToX(5, 10, 500)).toBe(250);
        expect(Manager.timeToX(10, 10, 500)).toBe(500);
    });

    test('round-trips through xToTime', () => {
        const t = 3.7;
        expect(Manager.xToTime(Manager.timeToX(t, 10, 640), 10, 640))
            .toBeCloseTo(t, 6);
    });

    test('clamps a pointer dragged past the edges', () => {
        // A drag that leaves the canvas must not produce a negative start or
        // an end past the episode; both export as nonsense frame indices.
        expect(Manager.xToTime(-50, 10, 500)).toBe(0);
        expect(Manager.xToTime(9999, 10, 500)).toBe(10);
    });

    test('a zero-duration episode does not divide by zero', () => {
        expect(Manager.timeToX(1, 0, 500)).toBe(0);
        expect(Manager.xToTime(100, 0, 500)).toBe(0);
    });
});

describe('insertSegment', () => {
    const seg = (start, end, label) => ({ start, end, label });

    test('adds to an empty timeline', () => {
        expect(Manager.insertSegment([], seg(0, 1, 'reach')))
            .toEqual([seg(0, 1, 'reach')]);
    });

    test('keeps the result sorted', () => {
        let out = Manager.insertSegment([], seg(3, 4, 'b'));
        out = Manager.insertSegment(out, seg(0, 1, 'a'));
        expect(out.map((s) => s.label)).toEqual(['a', 'b']);
    });

    test('truncates the left neighbour it overlaps', () => {
        const out = Manager.insertSegment([seg(0, 2, 'a')], seg(1, 3, 'b'));
        expect(out).toEqual([seg(0, 1, 'a'), seg(1, 3, 'b')]);
    });

    test('truncates the right neighbour it overlaps', () => {
        const out = Manager.insertSegment([seg(2, 4, 'a')], seg(1, 3, 'b'));
        expect(out).toEqual([seg(1, 3, 'b'), seg(3, 4, 'a')]);
    });

    test('splits a segment it lands inside', () => {
        const out = Manager.insertSegment([seg(0, 10, 'a')], seg(4, 6, 'b'));
        expect(out).toEqual([seg(0, 4, 'a'), seg(4, 6, 'b'), seg(6, 10, 'a')]);
    });

    test('removes a segment it covers entirely', () => {
        // Left behind as a zero-width sliver it would be invisible on screen
        // and exported as a degenerate row.
        const out = Manager.insertSegment([seg(2, 3, 'a')], seg(0, 10, 'b'));
        expect(out).toEqual([seg(0, 10, 'b')]);
    });

    test('never leaves two segments overlapping', () => {
        // The invariant the temporal-IoU agreement depends on.
        let out = [];
        [[0, 5, 'a'], [3, 8, 'b'], [1, 4, 'c'], [7, 9, 'd'], [0, 2, 'e']]
            .forEach(([s, e, l]) => {
                out = Manager.insertSegment(out, seg(s, e, l));
            });
        for (let i = 1; i < out.length; i++) {
            expect(out[i].start).toBeGreaterThanOrEqual(out[i - 1].end);
        }
    });

    test('a sub-threshold remnant is dropped, not kept at zero width', () => {
        // The new segment starts 20 ms into the old one, so the remnant is
        // 20 ms wide — below MIN_SEGMENT, invisible on screen, and exported as
        // a row nobody meant to create.
        const out = Manager.insertSegment([seg(1.0, 2.0, 'a')],
                                          seg(1.02, 3.0, 'b'));
        expect(out.map((s) => s.label)).toEqual(['b']);
        expect(Manager.MIN_SEGMENT).toBeGreaterThan(0.02);
    });
});

describe('segmentAt', () => {
    const segments = [{ start: 0, end: 2, label: 'a' },
                      { start: 3, end: 5, label: 'b' }];

    test('finds the interior', () => {
        expect(Manager.segmentAt(segments, 1)).toEqual({ index: 0, edge: null });
        expect(Manager.segmentAt(segments, 4)).toEqual({ index: 1, edge: null });
    });

    test('finds nothing in a gap', () => {
        expect(Manager.segmentAt(segments, 2.5)).toBeNull();
    });

    test('reports which edge, within tolerance', () => {
        expect(Manager.segmentAt(segments, 0.05, 0.1))
            .toEqual({ index: 0, edge: 'start' });
        expect(Manager.segmentAt(segments, 1.95, 0.1))
            .toEqual({ index: 0, edge: 'end' });
    });

    test('without tolerance an edge is still inside the segment', () => {
        expect(Manager.segmentAt(segments, 0).edge).toBe('start');
    });
});

describe('resizeSegment', () => {
    const segments = () => [{ start: 0, end: 4, label: 'a' },
                            { start: 5, end: 8, label: 'b' }];

    test('moves the start and leaves the end alone', () => {
        const out = Manager.resizeSegment(segments(), 0, 'start', 1);
        expect(out[0]).toEqual({ start: 1, end: 4, label: 'a' });
    });

    test('moves the end and leaves the start alone', () => {
        const out = Manager.resizeSegment(segments(), 0, 'end', 3);
        expect(out[0]).toEqual({ start: 0, end: 3, label: 'a' });
    });

    test('does not push the neighbour', () => {
        // A drag that shoved the next segment along would undo an alignment
        // the annotator had already made.
        const out = Manager.resizeSegment(segments(), 0, 'end', 7);
        expect(out.find((s) => s.label === 'b'))
            .toEqual({ start: 5, end: 8, label: 'b' });
    });

    test('refuses to invert a segment', () => {
        const before = segments();
        const out = Manager.resizeSegment(before, 0, 'start', 9);
        expect(out[0].end).toBeGreaterThan(out[0].start);
    });

    test('an unknown index changes nothing', () => {
        const before = segments();
        expect(Manager.resizeSegment(before, 99, 'start', 1)).toBe(before);
    });
});

describe('the reward curve', () => {
    test('adds a sample', () => {
        expect(Manager.setReward([], 1, 0.5)).toEqual([{ t: 1, value: 0.5 }]);
    });

    test('stays sorted by time', () => {
        let out = Manager.setReward([], 3, 0.3);
        out = Manager.setReward(out, 1, 0.1);
        expect(out.map((p) => p.t)).toEqual([1, 3]);
    });

    test('replaces a nearby sample rather than accumulating', () => {
        // Dragging fires a pointer event every few pixels; without the snap
        // the stored curve is mostly noise about the annotator's mouse.
        let out = Manager.setReward([], 1.0, 0.2);
        out = Manager.setReward(out, 1.01, 0.9);
        expect(out).toEqual([{ t: 1.01, value: 0.9 }]);
    });

    test('keeps a genuinely distinct sample', () => {
        let out = Manager.setReward([], 1.0, 0.2);
        out = Manager.setReward(out, 2.0, 0.9);
        expect(out.length).toBe(2);
    });

    test('interpolates between samples', () => {
        const curve = [{ t: 0, value: 0 }, { t: 2, value: 1 }];
        expect(Manager.rewardAt(curve, 1)).toBeCloseTo(0.5, 6);
    });

    test('returns null outside the drawn range', () => {
        // "Did not say" is not "said zero". A reward model trained on the
        // second when the first was true learns that unlabelled regions are
        // bad.
        const curve = [{ t: 1, value: 0.5 }, { t: 2, value: 1 }];
        expect(Manager.rewardAt(curve, 0.5)).toBeNull();
        expect(Manager.rewardAt(curve, 3)).toBeNull();
    });

    test('an empty curve is null everywhere', () => {
        expect(Manager.rewardAt([], 1)).toBeNull();
    });

    test('matches the Python implementation at the endpoints', () => {
        // `potato/server_utils/iaa/episodes.py:reward_at` scores what the
        // annotator saw. If the two interpolations disagree the number is
        // unattributable to the curve they drew.
        const curve = [{ t: 0, value: 0.25 }, { t: 4, value: 0.75 }];
        expect(Manager.rewardAt(curve, 0)).toBeCloseTo(0.25, 6);
        expect(Manager.rewardAt(curve, 4)).toBeCloseTo(0.75, 6);
        expect(Manager.rewardAt(curve, 2)).toBeCloseTo(0.5, 6);
    });
});

describe('chooseLanes', () => {
    const series = (n) => Array.from({ length: n },
                                     (_v, i) => ({ name: `s${i}` }));

    test('an explicit list wins, in the order the config gave', () => {
        const out = Manager.chooseLanes(series(5), ['s3', 's1'], 8);
        expect(out.lanes.map((s) => s.name).sort()).toEqual(['s1', 's3']);
        expect(out.hidden).toBe(3);
    });

    test('a name that does not exist is simply absent', () => {
        const out = Manager.chooseLanes(series(2), ['s0', 'nope'], 8);
        expect(out.lanes.map((s) => s.name)).toEqual(['s0']);
    });

    test('without a list it caps and reports what was left out', () => {
        // A 14-joint arm with velocities is 28 channels; drawing them all
        // makes each lane 12 pixels tall and none of them legible. Silently
        // dropping half is how an annotator concludes the data does not
        // contain something it does.
        const out = Manager.chooseLanes(series(28), null, 8);
        expect(out.lanes.length).toBe(8);
        expect(out.hidden).toBe(20);
    });

    test('nothing hidden when everything fits', () => {
        expect(Manager.chooseLanes(series(3), null, 8).hidden).toBe(0);
    });
});

describe('formatTime', () => {
    test('two decimals under a minute', () => {
        expect(Manager.formatTime(3.14159)).toBe('3.14 s');
    });

    test('minutes and seconds above one minute', () => {
        expect(Manager.formatTime(75.5)).toBe('1:15.50');
    });

    test('a non-finite time does not print NaN at the annotator', () => {
        expect(Manager.formatTime(NaN)).toBe('0.00 s');
        expect(Manager.formatTime(Infinity)).toBe('0.00 s');
    });
});

describe('coverage', () => {
    test('sums the annotated time', () => {
        expect(Manager.coverage([{ start: 0, end: 2 }, { start: 3, end: 4 }]))
            .toBe(3);
    });

    test('an empty segmentation covers nothing', () => {
        expect(Manager.coverage([])).toBe(0);
    });
});

/**
 * The arithmetic and the bookkeeping behind rollout evaluation.
 *
 * Two things here are load-bearing and easy to get subtly wrong:
 *
 * **The frame/time round trip.** A break-point is quoted as a frame and stored
 * as a time. If `frameAt` and `timeOfFrame` are not exact inverses, a mark
 * moves every time it is saved and reloaded — slowly, invisibly, and in a way
 * that shows up only as inflated disagreement in the agreement report months
 * later. The tests below pin the inversion across the whole frame range, and
 * pin the half-frame offset that makes it hold.
 *
 * **The clean/unanswered distinction.** `unresolvedStreams` is what separates
 * "watched it, nothing wrong" from "never got to it". Those two readings give
 * opposite detection agreements, so the function that tells them apart is
 * worth more tests than its four lines suggest.
 */

const Manager = require('../../potato/static/rollout-eval.js');

const {
    frameAt, timeOfFrame, snapToFrame, insertViolation, violationAt,
    unresolvedStreams, describeViolation, formatTime, timeToX, xToTime,
} = Manager;

function mark(stream, t, extra) {
    return Object.assign({ stream, t, type: 'interpenetration', severity: 2,
                           note: '' }, extra || {});
}

describe('frame and time', () => {
    test('timeOfFrame lands in the middle of the frame, not on its edge', () => {
        // The whole point: frame/fps is a boundary and which frame a browser
        // shows at a boundary is unspecified.
        expect(timeOfFrame(0, 25)).toBeCloseTo(0.02, 10);
        expect(timeOfFrame(1, 25)).toBeCloseTo(0.06, 10);
        expect(timeOfFrame(10, 25)).toBeCloseTo(0.42, 10);
    });

    test('frameAt inverts timeOfFrame exactly, across the range', () => {
        [24, 25, 29.97, 30, 60].forEach((fps) => {
            for (let frame = 0; frame < 500; frame += 1) {
                expect(frameAt(timeOfFrame(frame, fps), fps)).toBe(frame);
            }
        });
    });

    test('the inversion FAILS on frame boundaries, which is why the offset exists',
         () => {
        // Guards the offset itself: without it, this is the behaviour, and it
        // is wrong for roughly half the frames at any given rate.
        const fps = 29.97;
        let wrong = 0;
        for (let frame = 0; frame < 500; frame += 1) {
            if (Math.floor((frame / fps) * fps) !== frame) wrong += 1;
        }
        expect(wrong).toBeGreaterThan(0);
    });

    test('no declared rate means no frame number, rather than a guessed one', () => {
        expect(frameAt(3.4, 0)).toBeNull();
        expect(frameAt(3.4, undefined)).toBeNull();
        expect(timeOfFrame(4, 0)).toBe(0);
    });

    test('snapToFrame quantises to the frame the annotator is looking at', () => {
        expect(snapToFrame(0.079, 25)).toBeCloseTo(0.06, 10);   // frame 1
        expect(snapToFrame(0.081, 25)).toBeCloseTo(0.10, 10);   // frame 2
    });

    test('snapToFrame leaves the time alone when nothing declares a rate', () => {
        // Snapping to a guessed grid would move every mark by an unknown
        // amount, which is worse than not snapping.
        expect(snapToFrame(3.4187, 0)).toBe(3.4187);
    });
});

describe('inserting marks', () => {
    test('a mark is kept and the list stays sorted by time', () => {
        let v = [];
        v = insertViolation(v, mark('a', 3.0));
        v = insertViolation(v, mark('a', 1.0));
        v = insertViolation(v, mark('b', 2.0));
        expect(v.map((m) => m.t)).toEqual([1.0, 2.0, 3.0]);
    });

    test('a second mark within the merge window replaces the first', () => {
        // Replacing rather than refusing: the second press is the annotator's
        // considered answer.
        let v = insertViolation([], mark('a', 2.0, { note: 'first' }));
        v = insertViolation(v, mark('a', 2.1, { note: 'second' }));
        expect(v).toHaveLength(1);
        expect(v[0].note).toBe('second');
    });

    test('the merge window is per stream, not global', () => {
        // Two rollouts breaking at the same instant is the COMMON case -- the
        // same prompt, two generators failing on the same object -- so merging
        // across streams would silently delete half the data.
        let v = insertViolation([], mark('a', 2.0));
        v = insertViolation(v, mark('b', 2.0));
        expect(v).toHaveLength(2);
    });

    test('a mark outside the window is a separate break', () => {
        let v = insertViolation([], mark('a', 2.0));
        v = insertViolation(v, mark('a', 2.4));
        expect(v).toHaveLength(2);
    });
});

describe('selecting a mark by time', () => {
    const marks = [mark('a', 1.0), mark('a', 3.0), mark('b', 1.05)];

    test('finds the nearest mark on the right stream', () => {
        expect(violationAt(marks, 'a', 1.02, 0.2)).toBe(0);
        expect(violationAt(marks, 'b', 1.02, 0.2)).toBe(2);
    });

    test('returns null outside the tolerance rather than the nearest anywhere',
         () => {
        // A click in empty space means "no mark here"; returning the closest
        // one selects something the annotator was not pointing at.
        expect(violationAt(marks, 'a', 2.0, 0.2)).toBeNull();
    });

    test('prefers the closer of two candidates inside the window', () => {
        const dense = [mark('a', 1.0), mark('a', 1.1)];
        expect(violationAt(dense, 'a', 1.08, 0.5)).toBe(1);
    });
});

describe('answered, clean and unanswered', () => {
    const ids = ['real', 'gen_a', 'gen_b'];

    test('a stream with a mark counts as answered', () => {
        expect(unresolvedStreams(ids, [mark('gen_a', 2.0)], []))
            .toEqual(['real', 'gen_b']);
    });

    test('a stream marked clean counts as answered', () => {
        expect(unresolvedStreams(ids, [], ['real'])).toEqual(['gen_a', 'gen_b']);
    });

    test('nothing said about a stream leaves it unanswered', () => {
        // The distinction the whole `clean` layer exists for: without it this
        // case is indistinguishable from "watched it, nothing wrong", and the
        // two give opposite detection agreements.
        expect(unresolvedStreams(ids, [], [])).toEqual(ids);
    });

    test('answering every stream leaves nothing pending', () => {
        expect(unresolvedStreams(ids, [mark('gen_a', 1.0)], ['real', 'gen_b']))
            .toEqual([]);
    });
});

describe('what a screen reader is told', () => {
    test('a mark is described with its frame, its type and its panel', () => {
        expect(describeViolation(mark('gen_a', 0.42), 'B', 25))
            .toBe('B: interpenetration at frame 10, 0.42 s.');
    });

    test('with no frame rate the time carries it alone', () => {
        expect(describeViolation(mark('gen_a', 0.42), 'B', 0))
            .toBe('B: interpenetration at 0.42 s.');
    });

    test('an unset type is named rather than left blank', () => {
        expect(describeViolation({ stream: 'a', t: 1.0, type: '' }, 'A', 0))
            .toContain('unclassified');
    });
});

describe('timeline coordinates', () => {
    test('time and pixels round-trip', () => {
        expect(xToTime(timeToX(2.5, 5, 600), 5, 600)).toBeCloseTo(2.5, 10);
    });

    test('a zero-length rollout produces no coordinates rather than NaN', () => {
        // Reachable for real: the duration is 0 until a video reports its
        // metadata, and NaN here would silently paint every mark at the origin.
        expect(timeToX(2.5, 0, 600)).toBe(0);
        expect(xToTime(300, 0, 600)).toBe(0);
    });

    test('clicks outside the strip clamp into the rollout', () => {
        expect(xToTime(-50, 5, 600)).toBe(0);
        expect(xToTime(9999, 5, 600)).toBe(5);
    });
});

describe('formatTime', () => {
    test('seconds below a minute, with a stable width', () => {
        expect(formatTime(0)).toBe('0.00 s');
        expect(formatTime(3.456)).toBe('3.46 s');
    });

    test('minutes above one', () => {
        expect(formatTime(75.5)).toBe('1:15.50');
    });

    test('a non-finite duration does not leak NaN into the readout', () => {
        expect(formatTime(Infinity)).toBe('0.00 s');
    });
});

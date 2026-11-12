/**
 * Seek to a frame, then ask which frame you are on. It has to be that frame.
 *
 * It was not. `seekToFrame(n)` sets `currentTime = n / fps`, and the browser
 * stores that a hair below the exact value: seeking to frame 14 of a 12 fps
 * clip reads back 1.166666, and 1.166666 * 12 is 13.999992. Flooring answered
 * 13, so every keyframe an annotator drew after seeking was filed one frame
 * early — quietly, for every annotator, on every clip.
 *
 * Measured in a real browser before the fix: asking for 14 gave 13, 26 gave
 * 25, 40 gave 39. Frame 0 was right, which is why it survived so long.
 */

const fs = require('fs');
const path = require('path');

function loadManager() {
    const source = fs.readFileSync(
        path.join(__dirname, '../../potato/static/video-annotation.js'), 'utf8');
    const module_ = { exports: {} };
    const win = {};
    // eslint-disable-next-line no-new-func
    (new Function('module', 'exports', 'window', 'document', source))(
        module_, module_.exports, win, undefined);
    return module_.exports;
}

const VideoAnnotationManager = loadManager();

/** A manager with just enough of a video element to answer the question. */
function managerAt(fps) {
    const instance = Object.create(VideoAnnotationManager.prototype);
    instance.videoEl = { currentTime: 0, duration: 100 };
    instance.videoMetadata = { fps };
    return instance;
}

describe('frame index after a seek', () => {
    test.each([
        [12, 0], [12, 1], [12, 14], [12, 26], [12, 40],
        [25, 7], [25, 33], [30, 1], [30, 29], [30, 101],
    ])('%i fps: seeking to frame %i reports that frame', (fps, frame) => {
        const m = managerAt(fps);
        m.seekToFrame(frame);
        // Reproduce the browser's storage error, which is what breaks this:
        // Chrome hands the value back truncated to six decimal places, so it
        // is slightly BELOW what was written.
        m.videoEl.currentTime =
            Math.floor(m.videoEl.currentTime * 1e6) / 1e6;
        expect(m.getCurrentFrame()).toBe(frame);
    });

    test('the exact failing value from a real browser', () => {
        // Chrome returned this for seekToFrame(14) at 12 fps.
        const m = managerAt(12);
        m.videoEl.currentTime = 1.166666;
        expect(m.getCurrentFrame()).toBe(14);
    });
});

describe('frame index during playback', () => {
    test('a time in the middle of a frame still floors to that frame', () => {
        // The epsilon absorbs representation error, and nothing more: playback
        // sits between frames and must report the frame being shown.
        const m = managerAt(12);
        m.videoEl.currentTime = 1.2;      // 14.4 frames in
        expect(m.getCurrentFrame()).toBe(14);
        m.videoEl.currentTime = 1.24;     // 14.88 frames in
        expect(m.getCurrentFrame()).toBe(14);
    });

    test('it does not round up to the next frame', () => {
        const m = managerAt(12);
        m.videoEl.currentTime = 1.2499;   // still frame 14
        expect(m.getCurrentFrame()).toBe(14);
        m.videoEl.currentTime = 1.25;     // frame 15 begins
        expect(m.getCurrentFrame()).toBe(15);
    });

    test('time zero is frame zero', () => {
        const m = managerAt(30);
        m.videoEl.currentTime = 0;
        expect(m.getCurrentFrame()).toBe(0);
    });
});

describe('the control', () => {
    test('a plain floor fails the case this fixes', () => {
        // Proves the assertions above are load-bearing rather than incidental.
        expect(Math.floor(1.166666 * 12)).toBe(13);
        expect(Math.floor(1.166666 * 12 + 1e-3)).toBe(14);
        // And an epsilon that looks generous but is not: the error here is
        // 8e-6 of a frame, so 1e-6 does not clear it.
        expect(Math.floor(1.166666 * 12 + 1e-6)).toBe(13);
    });
});

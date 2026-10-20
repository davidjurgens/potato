/**
 * The tracker's "current / total" readout. It read both numbers from
 * Peaks.js, which does not start on a video with no audio track, so on such
 * a video (a FiftyOne clip, a screen recording) it stayed at 0:00 / 0:00.
 */

const fs = require('fs');
const path = require('path');

function loadManager() {
    const source = fs.readFileSync(
        path.join(__dirname, '../../potato/static/video-annotation.js'), 'utf8');
    const module_ = { exports: {} };
    // eslint-disable-next-line no-new-func
    (new Function('module', 'exports', 'window', 'document', source))(
        module_, module_.exports, {}, undefined);
    return module_.exports;
}

const VideoAnnotationManager = loadManager();

function managerWithoutPeaks(currentTime, duration) {
    const current = { textContent: '' };
    const total = { textContent: '' };
    const m = Object.create(VideoAnnotationManager.prototype);
    m.peaks = null;
    m.videoEl = { currentTime, duration };
    m.container = { querySelector: sel => (sel === '.current-time' ? current
        : sel === '.total-time' ? total : null) };
    m._formatTime = VideoAnnotationManager.prototype._formatTime;
    return { m, current, total };
}

test('without Peaks the readout comes from the video element', () => {
    const { m, current, total } = managerWithoutPeaks(1.5, 4);
    m._updateTimeDisplay();
    expect(`${current.textContent} / ${total.textContent}`).toBe(
        `${m._formatTime(1.5)} / ${m._formatTime(4)}`);
    expect(total.textContent).not.toBe(m._formatTime(0));
});

test('a duration the browser does not know yet reads as zero, not NaN', () => {
    const { m, total } = managerWithoutPeaks(0, NaN);
    m._updateTimeDisplay();
    expect(total.textContent).toBe(m._formatTime(0));
});

/**
 * `propagateForward`: what the server sends becomes what the annotator sees.
 *
 * The failure this file exists for produced no error at all. Propagation
 * returned thirty frames of masks, the status line said "30 frames tracked",
 * and the video did not change — because `renderOverlay` skips any keyframe
 * without a `bbox`, and a mask keyframe had only an RLE. It was found by
 * looking at a screenshot.
 *
 * Also covered: the video src is a URL and the server wants a media-relative
 * path, which the traversal guard refuses if you send the URL.
 */

const fs = require('fs');
const path = require('path');

function loadTracking() {
    const source = fs.readFileSync(
        path.join(__dirname, '../../potato/static/tracking-ui.js'), 'utf8');
    const module_ = { exports: {} };
    const win = {};
    // eslint-disable-next-line no-new-func
    (new Function('module', 'exports', 'window', source))(
        module_, module_.exports, win);
    return module_.exports.TrackingUIManager || win.TrackingUIManager;
}

const TrackingUIManager = loadTracking();

function manager(overrides = {}) {
    const instance = Object.create(TrackingUIManager.prototype);
    Object.assign(instance, {
        tracks: {
            track_1: {
                id: 'track_1', label: 'disc', color: '#d1495b',
                keyframes: { 0: { frame: 0, type: 'bbox',
                                  bbox: { x: 0.1, y: 0.4, width: 0.13, height: 0.19 } } },
            },
        },
        activeTrackId: 'track_1',
        config: { fps: 12, schemaName: 'tracks', videoPath: '/media/clip.webm' },
        // The overlay canvas is NOT the video's natural size, which is the
        // whole reason the conversions below are real rather than identity.
        canvas: {
            width: 600, height: 400,
            getBoundingClientRect: () => ({ left: 0, top: 0,
                                            width: 600, height: 400 }),
        },
        video: {
            currentTime: 0, currentSrc: 'http://host/media/clip.webm',
            videoWidth: 480, videoHeight: 320,
            // The element the picture is letterboxed inside.
            getBoundingClientRect: () => ({ left: 0, top: 0,
                                            width: 600, height: 400 }),
        },
        _getCurrentFrame: () => 0,
        _updateTrackRange: () => {},
        _renderTrackPanel: () => {},
        renderOverlay: () => {},
        _propagationStatus: function (message, kind) {
            this.status = message; this.statusKind = kind;
        },
    }, overrides);
    return instance;
}

function respondWith(payload, ok = true) {
    global.fetch = jest.fn(async (url, options) => {
        global.fetch.lastCall = { url, body: JSON.parse(options.body) };
        return { ok, json: async () => payload };
    });
}

function trackedFrames(count, withBbox = true) {
    return Array.from({ length: count }, (_, i) => ({
        frame: i + 1,
        visible: true,
        score: 3.0,
        rle: { counts: [10, 5], size: [320, 480] },
        bbox: withBbox
            ? { x: 0.1 + i * 0.02, y: 0.4, width: 0.13, height: 0.19 }
            : null,
    }));
}

describe('the media path', () => {
    const cases = [
        ['http://localhost:8732/media/occlusion.webm', 'occlusion.webm'],
        ['/media/occlusion.webm', 'occlusion.webm'],
        ['media/nested/clip.webm', 'nested/clip.webm'],
        ['occlusion.webm', 'occlusion.webm'],
        ['', ''],
    ];
    test.each(cases)('%s becomes %s', (input, expected) => {
        expect(manager()._mediaRelativePath(input)).toBe(expected);
    });

    test('the timeline\'s own frame rate goes with the request', async () => {
        // Frame numbers coming back are only meaningful in the rate the
        // client counts in. Leaving it out let the server extract at a
        // probed-or-guessed rate and return masks for other moments.
        respondWith({ frames: trackedFrames(1), occluded: 0 });
        const m = manager({ config: { fps: 12, videoFps: 12,
                                      schemaName: 'tracks' } });
        await m.propagateForward();
        expect(global.fetch.lastCall.body.fps).toBe(12);
    });

    test('a full URL is not sent to the server', async () => {
        respondWith({ frames: trackedFrames(2), occluded: 0 });
        const m = manager({ config: { fps: 12, schemaName: 'tracks' } });
        await m.propagateForward();
        // The traversal guard refuses an absolute URL, and the annotator sees
        // "that video could not be found" for a file that is right there.
        expect(global.fetch.lastCall.body.video).toBe('clip.webm');
    });
});

describe('turning results into keyframes', () => {
    test('every tracked frame becomes a keyframe', async () => {
        respondWith({ frames: trackedFrames(3), occluded: 0 });
        const m = manager();
        await m.propagateForward();
        expect(Object.keys(m.tracks.track_1.keyframes).sort())
            .toEqual(['0', '1', '2', '3']);
    });

    test('a mask keyframe carries the bbox, or it draws nothing', async () => {
        respondWith({ frames: trackedFrames(2), occluded: 0 });
        const m = manager();
        await m.propagateForward();
        const keyframe = m.tracks.track_1.keyframes[1];
        expect(keyframe.type).toBe('mask');
        expect(keyframe.rle).toBeTruthy();
        expect(keyframe.bbox).toBeTruthy();
    });

    test('the bbox arrives in CANVAS pixels, inside the letterboxed picture',
         async () => {
        // Two ways to get this wrong, both of which look like a tracker that
        // almost works: leaving the box normalized draws a sub-pixel rectangle
        // in the corner, and ignoring the letterbox offsets it by the width of
        // the black bars.
        respondWith({ frames: trackedFrames(1), occluded: 0 });
        const m = manager();
        const content = m.videoContentRect();
        await m.propagateForward();
        expect(m.tracks.track_1.keyframes[1].bbox).toEqual({
            x: content.left + 0.1 * content.width,
            y: content.top + 0.4 * content.height,
            width: 0.13 * content.width,
            height: 0.19 * content.height,
        });
    });

    test('the picture rect accounts for the black bars', () => {
        // 480x320 in a 600x400 canvas: same aspect, so it fills. Make it
        // wider and the bars appear.
        const wide = manager({
            canvas: { width: 800, height: 400,
                      getBoundingClientRect: () => ({ left: 0, top: 0,
                                                      width: 800, height: 400 }) },
            video: { videoWidth: 480, videoHeight: 320,
                     currentSrc: '/media/clip.webm',
                     getBoundingClientRect: () => ({ left: 0, top: 0,
                                                     width: 800, height: 400 }) },
        });
        const content = wide.videoContentRect();
        expect(content.width).toBeCloseTo(600);   // 320 tall * 1.5
        expect(content.left).toBeCloseTo(100);    // (800 - 600) / 2
        expect(content.top).toBeCloseTo(0);
    });

    test('the canvas may be inset from the video it overlays', () => {
        // The measured case: the overlay is inset 45px from the bottom of the
        // video element to clear the native controls, so the two boxes are
        // different heights and the picture has to be fitted inside the
        // VIDEO's box, not the canvas's.
        const inset = manager({
            canvas: { width: 828, height: 355,
                      getBoundingClientRect: () => ({ left: 226, top: 187,
                                                      width: 828, height: 355 }) },
            video: { videoWidth: 480, videoHeight: 320,
                     currentSrc: '/media/clip.webm',
                     getBoundingClientRect: () => ({ left: 226, top: 187,
                                                     width: 828, height: 400 }) },
        });
        const content = inset.videoContentRect();
        const fit = Math.min(828 / 480, 400 / 320);   // 1.25, height-limited
        expect(content.width).toBeCloseTo(480 * fit);           // 600
        expect(content.left).toBeCloseTo((828 - 600) / 2);      // 114
        expect(content.top).toBeCloseTo(0);
    });

    test('with no video dimensions yet it declines instead of guessing',
         async () => {
        respondWith({ frames: trackedFrames(1), occluded: 0 });
        const m = manager({ video: { currentSrc: '/media/clip.webm',
                                     videoWidth: 0, videoHeight: 0 } });
        expect(await m.propagateForward()).toBe(null);
        expect(m.status).toMatch(/still loading/);
    });

    test('the normalized box is kept too, because that is what gets stored',
         async () => {
        respondWith({ frames: trackedFrames(1), occluded: 0 });
        const m = manager();
        await m.propagateForward();
        expect(m.tracks.track_1.keyframes[1].bboxNorm)
            .toEqual({ x: 0.1, y: 0.4, width: 0.13, height: 0.19 });
    });

    test('the prompt point is scaled from canvas space into VIDEO space',
         async () => {
        // The seed keyframe is in canvas pixels and the model wants video
        // pixels. Skipping this scales the prompt by 600/480 and tracks
        // whatever happens to be at the wrong place.
        respondWith({ frames: trackedFrames(1), occluded: 0 });
        const m = manager();
        await m.propagateForward();
        const m2 = manager();
        const content = m2.videoContentRect();
        const [x, y] = global.fetch.lastCall.body.points[0];
        // Seed box centre in canvas space, mapped back through the picture
        // rect into the video's own pixels.
        expect(x).toBeCloseTo((0.1 + 0.065 - content.left) / content.scale, 5);
        expect(y).toBeCloseTo((0.4 + 0.095 - content.top) / content.scale, 5);
    });

    test("the model's frames are marked as its own", async () => {
        respondWith({ frames: trackedFrames(1), occluded: 0 });
        const m = manager();
        await m.propagateForward();
        expect(m.tracks.track_1.keyframes[1].source).toBe('sam2');
    });

    test('an occluded frame is skipped rather than filled with a guess', async () => {
        const frames = trackedFrames(2);
        frames[0].visible = false;
        frames[0].rle = null;
        respondWith({ frames, occluded: 1 });
        const m = manager();
        await m.propagateForward();
        expect(m.tracks.track_1.keyframes[1]).toBeUndefined();
        expect(m.status).toMatch(/1 where the object was hidden/);
    });
});

describe('what the annotator is told', () => {
    test('a truncated run says so, with the numbers', async () => {
        respondWith({
            frames: trackedFrames(2), occluded: 0,
            truncated: true, max_frames: 2, requested_frames: 40,
        });
        const m = manager();
        await m.propagateForward();
        expect(m.status).toMatch(/stopped at the 2-frame limit of 40 requested/);
    });

    test('no track selected asks for one instead of failing quietly', async () => {
        respondWith({ frames: [], occluded: 0 });
        const m = manager({ activeTrackId: null });
        expect(await m.propagateForward()).toBe(null);
        expect(m.status).toMatch(/Select a track/);
    });

    test('no seed keyframe explains what is missing', async () => {
        respondWith({ frames: [], occluded: 0 });
        const m = manager();
        m.tracks.track_1.keyframes = {};
        expect(await m.propagateForward()).toBe(null);
        expect(m.status).toMatch(/Draw the object on this frame first/);
    });

    test('a server error is shown rather than swallowed', async () => {
        respondWith({ error: 'That video could not be found' }, false);
        const m = manager();
        expect(await m.propagateForward()).toBe(null);
        expect(m.status).toBe('That video could not be found');
        expect(m.statusKind).toBe('error');
    });
});

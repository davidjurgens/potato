"""
SAM 2 mask propagation, driven in a browser against the real model.

Chrome does not decode media in the hidden tab the Chrome-MCP loop uses, so
this surface can only be checked here. That mattered: the screenshot pass that
first exercised propagation found five defects at once — mask keyframes drawing
nothing because they carried no bbox, the client sending a full URL the
traversal guard refuses, a frame index off by one after every seek, the server
inventing 25 fps for a 12 fps clip, and the overlay canvas squashing everything
by 11%.

The clip is synthetic so the answer is knowable. `make_clip.py` renders a
480x320, 48-frame, 12 fps clip in which a radius-30 disc travels

    x(f) = 40 + f * (480 - 120) / 47        y(f) = 160 + 30 * f / 48

and passes behind an opaque bar at x in [210, 275]. A second disc sits still at
(70, 260) throughout, so "track whatever moves" is not enough to pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS = REPO_ROOT / "potato" / "models" / "sam2_video_tiny"
MEDIA = REPO_ROOT / "examples" / "video" / "mask-propagation" / "media"

WIDTH, HEIGHT, FRAMES, FPS = 480, 320, 48, 12
RADIUS = 30
BAR_X = (210, 275)


def truth(frame):
    """Where the disc actually is on this frame, in video pixels."""
    return (40 + frame * (WIDTH - 120) / (FRAMES - 1),
            HEIGHT / 2 + 30 * (frame / FRAMES))


def visible_fraction(frame):
    """How much of the disc's width is not covered by the bar, as 0..1.

    The bar is 65 px and the disc 60, so at no integer frame is the disc
    *completely* hidden — at its worst, frame 26 leaves a sliver about a pixel
    wide. An earlier version of this file asked for full occlusion and found
    no such frame, which is a fact about the clip rather than the tracker.
    """
    x, _ = truth(frame)
    left, right = x - RADIUS, x + RADIUS
    covered = max(0.0, min(right, BAR_X[1]) - max(left, BAR_X[0]))
    return max(0.0, (2 * RADIUS - covered) / (2 * RADIUS))


def behind_bar(frame):
    """Frames where the disc is mostly swallowed by the bar."""
    return visible_fraction(frame) < 0.15


#: Mirrors examples/video/mask-propagation/config.yaml. `source_field` is what
#: tells the display where the video lives; without it the player gets no src,
#: never decodes, and every readiness wait times out with no hint as to why.
SCHEMES = [{
    "annotation_type": "video_annotation",
    "name": "tracks",
    "description": "Draw the disc once, then press Track forward",
    "source_field": "video_url",
    "mode": "tracking",
    "video_fps": FPS,
    "show_timecode": True,
    "frame_stepping": True,
    "labels": [{"name": "disc", "color": "#d1495b"},
               {"name": "distractor", "color": "#2f9e6f"}],
    "tracking_options": {"interpolation": "linear", "auto_advance_frames": 5},
    "propagation": {"max_frames": FRAMES},
}]


def models_present():
    return ((MODELS / "vision_encoder.onnx").is_file()
            and (MODELS / "memory_attention.onnx").is_file())


@pytest.fixture
def propagation_server(make_server):
    import shutil
    if not models_present():
        pytest.skip("run `potato download-models sam2_video_tiny` first")
    if not (MEDIA / "occlusion.webm").is_file():
        pytest.skip("run examples/video/mask-propagation/make_clip.py first")
    if shutil.which("ffmpeg") is None:
        pytest.skip("server-side propagation reads frames with ffmpeg")
    return make_server(
        SCHEMES,
        items=[{"id": f"clip_{i}", "video_url": "/media/occlusion.webm",
                "description": "Track the red disc."} for i in (1, 2, 3)],
        extra_config={
            "media_directory": str(MEDIA),
            # text_key is the video URL, as in the example: the display resolves
            # the media from the instance text.
            "item_properties": {"id_key": "id", "text_key": "video_url"},
        },
    )


class TestMaskPropagation(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_selector(".video-annotation-container", timeout=30_000)
        # Everything downstream needs real dimensions; without a decode the
        # coordinate maths silently divides by zero.
        page.wait_for_function(
            """() => {
                const c = document.querySelector('.video-annotation-container');
                const m = c && c.videoAnnotationManager
                          && c.videoAnnotationManager.trackingManager;
                const el = m && (m.video || c.querySelector('video'));
                return !!(el && el.videoWidth > 0 && el.duration > 0);
            }""", timeout=60_000)

    def _seed(self, page, frame=0):
        """Put a box around the disc on `frame`, in the canvas space the UI uses."""
        x, y = truth(frame)
        return page.evaluate(
            """([vx, vy, radius]) => {
                const c = document.querySelector('.video-annotation-container');
                const mgr = c.videoAnnotationManager.trackingManager;
                const rect = mgr.videoContentRect();
                const toCanvas = (ix, iy) => ({
                    x: rect.left + (ix / 480) * rect.width,
                    y: rect.top + (iy / 320) * rect.height,
                });
                const topLeft = toCanvas(vx - radius, vy - radius);
                const bottomRight = toCanvas(vx + radius, vy + radius);
                mgr.createTrack('disc', '#d1495b');
                mgr.addShapeKeyframe({
                    type: 'bbox',
                    bbox: {x: topLeft.x, y: topLeft.y,
                           width: bottomRight.x - topLeft.x,
                           height: bottomRight.y - topLeft.y},
                });
                return Object.keys(mgr.tracks[mgr.activeTrackId].keyframes);
            }""", [x, y, RADIUS])

    def _propagate(self, page, frames=20, timeout=600_000):
        page.evaluate(
            """(frames) => {
                const c = document.querySelector('.video-annotation-container');
                window.__done = null;
                c.videoAnnotationManager.trackingManager
                    .propagateForward({frames: frames})
                    .then(r => { window.__done = r || {}; })
                    .catch(e => { window.__done = {error: String(e)}; });
            }""", frames)
        page.wait_for_function("() => window.__done !== null", timeout=timeout)
        return page.evaluate("() => window.__done")

    def _keyframes(self, page):
        return page.evaluate(
            """() => {
                const c = document.querySelector('.video-annotation-container');
                const mgr = c.videoAnnotationManager.trackingManager;
                const track = mgr.tracks[mgr.activeTrackId];
                return Object.entries(track.keyframes).map(([f, k]) => ({
                    frame: Number(f), type: k.type,
                    hasRle: !!k.rle, hasBbox: !!k.bbox,
                    bboxNorm: k.bboxNorm || null, source: k.source || null,
                }));
            }""")

    # ---- the request ----

    @pytest.mark.timeout(900)
    def test_the_request_carries_a_media_relative_path_and_the_real_fps(
            self, page, propagation_server):
        """
        Two ways this failed before: sending the video's full URL, which the
        traversal guard refuses so a file sitting in the media directory
        reports "could not be found"; and omitting the frame rate, so the
        server picked its own and returned masks for other moments entirely.
        """
        self._open(page, propagation_server)
        self._seed(page)
        sent = page.evaluate(
            """async () => {
                const c = document.querySelector('.video-annotation-container');
                const mgr = c.videoAnnotationManager.trackingManager;
                const realFetch = window.fetch;
                let captured = null;
                window.fetch = function (url, options) {
                    if (String(url).includes('/api/track/propagate')) {
                        captured = JSON.parse(options.body);
                    }
                    return realFetch.apply(this, arguments);
                };
                await mgr.propagateForward({frames: 2});
                window.fetch = realFetch;
                return captured;
            }""")
        assert sent is not None, "propagateForward never called the endpoint"
        assert sent["video"] == "occlusion.webm", sent["video"]
        assert sent["fps"] == FPS, sent["fps"]

    # ---- the answer ----

    @pytest.mark.timeout(900)
    def test_it_tracks_the_disc_to_where_the_disc_actually_is(
            self, page, propagation_server):
        self._open(page, propagation_server)
        self._seed(page)
        result = self._propagate(page, frames=20)
        assert not result.get("error"), result

        frames = [k for k in self._keyframes(page)
                  if k["frame"] > 0 and k["bboxNorm"]]
        assert frames, f"propagation produced no tracked frames: {result}"

        checked = 0
        for k in frames:
            if behind_bar(k["frame"]):
                continue
            expected_x, expected_y = truth(k["frame"])
            box = k["bboxNorm"]
            got_x = (box["x"] + box["width"] / 2) * WIDTH
            got_y = (box["y"] + box["height"] / 2) * HEIGHT
            # Eight pixels on a radius-30 disc: comfortably inside the object,
            # far outside the 65 px the bar is wide, and nowhere near the
            # stationary distractor at (70, 260).
            assert abs(got_x - expected_x) < 8, (
                f"frame {k['frame']}: x {got_x:.1f}, disc at {expected_x:.1f}")
            assert abs(got_y - expected_y) < 8, (
                f"frame {k['frame']}: y {got_y:.1f}, disc at {expected_y:.1f}")
            checked += 1
        assert checked >= 5, f"only {checked} visible frames were checked"

    @pytest.mark.timeout(900)
    def test_it_does_not_latch_onto_the_stationary_distractor(
            self, page, propagation_server):
        """
        The clip holds a second disc at (70, 260) that never moves. A tracker
        that lost the object and settled on the nearest blob would still return
        confident masks, so this asks specifically that it did not.
        """
        self._open(page, propagation_server)
        self._seed(page)
        self._propagate(page, frames=20)

        for k in self._keyframes(page):
            if k["frame"] == 0 or not k["bboxNorm"]:
                continue
            box = k["bboxNorm"]
            cx = (box["x"] + box["width"] / 2) * WIDTH
            cy = (box["y"] + box["height"] / 2) * HEIGHT
            assert not (abs(cx - 70) < 25 and abs(cy - 260) < 25), (
                f"frame {k['frame']} landed on the stationary distractor")

    @pytest.mark.timeout(900)
    def test_every_propagated_frame_carries_a_bbox_as_well_as_a_mask(
            self, page, propagation_server):
        """
        The overlay skips a keyframe with no bbox. Propagation returning only
        RLE meant "30 frames tracked" over a video that never changed — a
        silent success, which is the failure mode this whole file exists for.
        """
        self._open(page, propagation_server)
        self._seed(page)
        self._propagate(page, frames=20)

        propagated = [k for k in self._keyframes(page) if k["source"] == "sam2"]
        assert propagated, "nothing was marked as coming from the model"
        for k in propagated:
            assert k["hasRle"], f"frame {k['frame']} has no mask"
            assert k["hasBbox"], (
                f"frame {k['frame']} has a mask but no bbox, so it draws nothing")

    @pytest.mark.timeout(900)
    def test_behind_the_bar_it_reports_a_sliver_or_nothing_at_all(
            self, page, propagation_server):
        """
        The bar is 65 px and the disc 60, so the disc is never quite gone — at
        frame 26 about a pixel of it still shows. What must not happen is a
        confident full-size box drawn over the bar, which is a tracker
        inventing geometry rather than reporting what it can see.
        """
        self._open(page, propagation_server)
        self._seed(page)
        result = self._propagate(page, frames=30)

        occluded_frames = {f for f in range(1, 31) if behind_bar(f)}
        assert occluded_frames, "the fixture no longer contains an occlusion"

        for k in self._keyframes(page):
            if k["frame"] not in occluded_frames or not k["bboxNorm"]:
                continue
            width_px = k["bboxNorm"]["width"] * WIDTH
            assert width_px < 0.5 * (2 * RADIUS), (
                f"frame {k['frame']} is {visible_fraction(k['frame']):.0%} "
                f"visible but reports a {width_px:.0f} px box")

    @pytest.mark.timeout(900)
    def test_it_finds_the_disc_again_after_the_occlusion(
            self, page, propagation_server):
        """
        The reason for using SAM 2 rather than re-prompting frame by frame: a
        tracker with a memory picks the object up on the far side of the bar.
        """
        self._open(page, propagation_server)
        self._seed(page)
        # Far enough for the disc to come out the other side completely: it
        # clears the bar's right edge at frame 35 (x - 30 > 275).
        self._propagate(page, frames=40)

        last_hidden = max(f for f in range(1, 41) if behind_bar(f))
        after = [k for k in self._keyframes(page)
                 if k["frame"] > last_hidden and k["bboxNorm"]]
        assert after, (
            f"nothing tracked after the occlusion ended at frame {last_hidden}")

        # Compared on the first frame where the disc is COMPLETELY clear of the
        # bar. On the frames in between it is still half-covered, and the mask
        # correctly hugs the visible sliver — measured 280 against a true
        # centre of 254.5, which is the sliver's centre, not a tracking error.
        clear = [k for k in after if visible_fraction(k["frame"]) >= 0.999]
        assert clear, "the disc never emerges fully within the propagated range"

        k = min(clear, key=lambda k: k["frame"])
        expected_x, _ = truth(k["frame"])
        got_x = (k["bboxNorm"]["x"] + k["bboxNorm"]["width"] / 2) * WIDTH
        assert abs(got_x - expected_x) < 12, (
            f"re-acquired at x={got_x:.1f}, disc at {expected_x:.1f}")


class TestOverlayGeometry(BasePlaywrightTest):
    """
    The overlay canvas is inset from the video to clear the native controls, so
    its box and the video's are different sizes. Fitting the picture inside the
    CANVAS instead of the VIDEO displayed everything squashed by 11% — including
    hand-drawn boxes, not just propagated ones.
    """

    @pytest.mark.timeout(300)
    def test_the_picture_rect_is_fitted_inside_the_video_element(
            self, page, propagation_server):
        self._open = TestMaskPropagation._open.__get__(self)
        self._open(page, propagation_server)

        measured = page.evaluate(
            """() => {
                const c = document.querySelector('.video-annotation-container');
                const mgr = c.videoAnnotationManager.trackingManager;
                const el = mgr.video || c.querySelector('video');
                const rect = mgr.videoContentRect();
                const videoRect = el.getBoundingClientRect();
                const canvasRect = mgr.canvas.getBoundingClientRect();
                return {
                    rect: rect,
                    natural: [el.videoWidth, el.videoHeight],
                    videoBox: [videoRect.width, videoRect.height],
                    canvasBox: [canvasRect.width, canvasRect.height],
                    backing: [mgr.canvas.width, mgr.canvas.height],
                };
            }""")

        natural_ratio = measured["natural"][0] / measured["natural"][1]
        shown_ratio = measured["rect"]["width"] / measured["rect"]["height"]
        assert abs(shown_ratio - natural_ratio) < 0.02, (
            f"the picture rect is not the video's aspect ratio: {measured}")

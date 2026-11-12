"""
Does the tracker actually track? Real weights, known motion, measured IoU.

WHY THE TEST IS BEHAVIOURAL RATHER THAN NUMERICAL
--------------------------------------------------
There is no reference implementation to compare against: the PyTorch SAM 2 is
a 900 MB download and this is an ONNX export of it. So the oracle is the world
instead. A disc moves across a synthetic scene on a path this test knows, the
tracker is prompted once on frame 0, and every later mask is scored against
where the disc actually is.

That catches what matters. A memory bank assembled in the wrong order, padded
with zeros instead of repeats, or missing its temporal encodings does not
raise — it returns a plausible mask that drifts. Drift is exactly what an IoU
against known truth measures.

The controls matter as much as the assertions. Tracking that "works" with the
memory bank zeroed would mean the memory is doing nothing and the loop is
re-prompting in disguise, which is the thing this replaces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("onnxruntime")
pytest.importorskip("PIL")

from potato.models_cli import DEFAULT_MODEL_DIR  # noqa: E402

MODEL_DIR = DEFAULT_MODEL_DIR / "sam2_video_tiny"

pytestmark = pytest.mark.skipif(
    not (MODEL_DIR / "memory_attention.onnx").exists(),
    reason="needs sam2_video_tiny (potato download-models sam2_video_tiny)")

WIDTH, HEIGHT = 320, 240
RADIUS = 34
#: A disc crossing the frame left to right, drifting down. Slow enough that a
#: correct tracker keeps it and fast enough that a broken one loses it.
PATH = [(70, 90), (100, 100), (130, 112), (160, 122), (190, 132), (220, 140)]


def frames():
    from PIL import Image, ImageDraw

    out = []
    for cx, cy in PATH:
        image = Image.new("RGB", (WIDTH, HEIGHT), (235, 235, 230))
        draw = ImageDraw.Draw(image)
        # A distractor that never moves. Without one, "track the only thing in
        # the scene" is not a test of tracking.
        draw.rectangle([20, 180, 90, 225], fill=(90, 120, 90))
        draw.ellipse([cx - RADIUS, cy - RADIUS, cx + RADIUS, cy + RADIUS],
                     fill=(200, 70, 60))
        out.append(image)
    return out


def truth_mask(index):
    cx, cy = PATH[index]
    ys, xs = np.mgrid[0:HEIGHT, 0:WIDTH]
    return ((xs - cx) ** 2 + (ys - cy) ** 2) <= RADIUS ** 2


def iou(a, b):
    if a is None or b is None:
        return 0.0
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


@pytest.fixture(scope="module")
def tracked():
    from potato.ai.sam2_video import SAM2VideoTracker

    tracker = SAM2VideoTracker(MODEL_DIR)
    return tracker.track(frames(), [(PATH[0][0], PATH[0][1], 1)])


class TestTracking:
    def test_the_seed_frame_segments_what_was_clicked(self, tracked):
        assert iou(tracked[0].mask, truth_mask(0)) > 0.8, (
            "the prompted frame itself is wrong, so nothing later can be right")

    def test_every_later_frame_follows_the_object(self, tracked):
        scores = [iou(result.mask, truth_mask(i))
                  for i, result in enumerate(tracked)]
        assert all(score > 0.7 for score in scores), (
            f"the mask drifted off the disc: per-frame IoU {[round(s, 3) for s in scores]}")

    def test_it_does_not_decay_across_the_sequence(self, tracked):
        """Drift shows up as the last frames being much worse than the first."""
        first = iou(tracked[0].mask, truth_mask(0))
        last = iou(tracked[-1].mask, truth_mask(len(tracked) - 1))
        assert last > first - 0.15, (
            f"quality fell from {first:.3f} to {last:.3f} across "
            f"{len(tracked)} frames, which is what a mis-assembled memory bank "
            f"looks like")

    def test_the_object_is_reported_visible_throughout(self, tracked):
        assert all(result.visible for result in tracked), (
            "the model reported an occlusion in a sequence with none")

    def test_it_tracks_the_disc_and_not_the_distractor(self, tracked):
        """A tracker that latches onto the wrong object still looks confident."""
        distractor = np.zeros((HEIGHT, WIDTH), dtype=bool)
        distractor[180:226, 20:91] = True
        for result in tracked:
            assert iou(result.mask, distractor) < 0.2


class TestMemoryIsLoadBearing:
    """The memory bank has to be doing something, or this is re-prompting."""

    def test_zeroed_memory_tracks_worse(self):
        """Zeros are a valid memory meaning 'empty scene', and it shows."""
        from potato.ai.sam2_video import SAM2VideoTracker

        sequence = frames()

        honest = SAM2VideoTracker(MODEL_DIR)
        good = honest.track(sequence, [(PATH[0][0], PATH[0][1], 1)])
        good_score = np.mean([iou(r.mask, truth_mask(i))
                              for i, r in enumerate(good)])

        broken = SAM2VideoTracker(MODEL_DIR)
        broken.start(sequence[0], [(PATH[0][0], PATH[0][1], 1)])
        original_bank = broken._bank

        def zeroed():
            memory, memory_pos = original_bank()
            return np.zeros_like(memory), memory_pos

        broken._bank = zeroed
        blind = [broken.step(frame) for frame in sequence[1:]]
        blind_score = np.mean([iou(r.mask, truth_mask(i + 1))
                               for i, r in enumerate(blind)])

        assert good_score > blind_score + 0.05, (
            f"zeroing the memory bank changed almost nothing "
            f"({good_score:.3f} vs {blind_score:.3f}), so the memory is not "
            f"what is doing the tracking")

    def test_the_bank_is_the_size_the_graph_declares(self):
        from potato.ai.sam2_video import SAM2VideoTracker

        tracker = SAM2VideoTracker(MODEL_DIR)
        sequence = frames()
        tracker.start(sequence[0], [(PATH[0][0], PATH[0][1], 1)])
        memory, memory_pos = tracker._bank()
        # 7 mask memories x 4096 tokens + 16 pointers x 4 chunks.
        assert memory.shape == (28736, 1, 64), memory.shape
        assert memory_pos.shape == (28736, 1, 64)

    def test_short_history_pads_by_repeating_not_by_zeroing(self):
        from potato.ai.sam2_video import SAM2VideoTracker

        tracker = SAM2VideoTracker(MODEL_DIR)
        sequence = frames()
        tracker.start(sequence[0], [(PATH[0][0], PATH[0][1], 1)])
        memory, _ = tracker._bank()
        mask_part = memory[:7 * 4096]
        assert np.abs(mask_part).sum() > 0
        # Every one of the seven slots must carry signal: a zero-filled slot is
        # a memory that says "nothing here".
        for slot in range(7):
            block = mask_part[slot * 4096:(slot + 1) * 4096]
            assert np.abs(block).sum() > 0, f"memory slot {slot} is empty"

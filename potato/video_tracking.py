"""
Server-side video propagation: prompt one frame, get masks for the rest.

WHY THIS RUNS ON THE SERVER WHEN SEGMENTATION RUNS IN THE BROWSER
------------------------------------------------------------------
Potato's interactive segmentation deliberately runs in the annotator's browser:
one image, one click, sub-second, no GPU, works air-gapped. Video propagation
is a different shape of problem and gets a different answer.

* **The model is five graphs and 181 MB**, against 45 MB for click-to-segment.
* **The cost is per frame, not per click.** A hundred-frame clip in WebAssembly
  is minutes of a frozen tab; the same loop server-side is seconds on a GPU and
  a bearable wait on a CPU.
* **The frames are already here.** The video sits in the media directory. The
  browser would have to decode and re-upload every frame it wanted tracked.

So the browser does what interactivity demands, and the server does what
throughput demands. Neither is a fallback for the other.

HONESTY ABOUT LIMITS
--------------------
Propagation is bounded by `max_frames` and reports when it stopped early rather
than quietly returning a short answer — a truncated result that reads as
complete is the failure mode this codebase keeps finding. Occluded frames come
back explicitly empty, because SAM 2 reports occlusion itself and guessing a
mask there would be worse than admitting the object is hidden.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: How many frames one request may propagate through. A whole clip at 30 fps is
#: tens of thousands of frames and minutes of CPU; the annotator asked for a
#: shot, not a film.
DEFAULT_MAX_FRAMES = 120

#: Where the tracker's weights live, relative to the model directory.
MODEL_KEY = "sam2_video_tiny"


class TrackingUnavailable(RuntimeError):
    """Raised when the model or its dependencies are missing.

    Carries the command to fix it: an administrator seeing "tracking failed"
    learns nothing, and the fix is one line.
    """


@dataclass
class PropagationResult:
    """What came back for one frame."""

    frame: int
    visible: bool
    score: float
    rle: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame": self.frame,
            "visible": self.visible,
            "score": round(self.score, 4),
            "rle": self.rle,
        }


@dataclass
class PropagationRequest:
    """One propagation job."""

    video_path: Path
    #: Points in ORIGINAL frame pixels, as (x, y, label) with 1 for foreground.
    points: Sequence[Tuple[float, float, int]]
    start_frame: int = 0
    frames: int = 30
    fps: Optional[float] = None
    max_frames: int = DEFAULT_MAX_FRAMES
    model_dir: Optional[Path] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def model_available(model_dir: Optional[Path] = None) -> bool:
    """True when the tracker could actually run."""
    from potato.models_cli import DEFAULT_MODEL_DIR

    root = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR / MODEL_KEY
    return (root / "memory_attention.onnx").exists()


def _require_model(model_dir: Optional[Path]) -> Path:
    from potato.models_cli import DEFAULT_MODEL_DIR

    root = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR / MODEL_KEY
    if not (root / "memory_attention.onnx").exists():
        raise TrackingUnavailable(
            f"The {MODEL_KEY} model is not installed. An administrator can add "
            f"it with:  potato download-models {MODEL_KEY}")
    try:
        import onnxruntime  # noqa: F401,PLC0415
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise TrackingUnavailable(
            "Video propagation needs onnxruntime:  pip install onnxruntime"
        ) from exc
    return root


def _frame_paths(video_path: Path, start: int, count: int,
                 fps: Optional[float]) -> Tuple[List[Path], Path]:
    """Extract the frames this job needs, and where they landed."""
    from potato.media.video import (VideoTranscodeError, extract_frames,
                                    ffmpeg_available, probe_video)

    if not ffmpeg_available():
        raise TrackingUnavailable(
            "Video propagation needs ffmpeg to read frames. Install it, or "
            "annotate keyframes by hand.")

    temp_dir = Path(tempfile.mkdtemp(prefix="potato-track-"))
    rate = fps
    if rate is None:
        info = probe_video(str(video_path))
        rate = float(info.get("fps") or 0) or 25.0

    try:
        extract_frames(str(video_path), str(temp_dir), fps=rate)
    except VideoTranscodeError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise TrackingUnavailable(str(exc)) from exc

    everything = sorted(temp_dir.glob("*.jpg")) or sorted(temp_dir.glob("*.png"))
    window = everything[start:start + count]
    if not window:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise TrackingUnavailable(
            f"Frame {start} is past the end of this video, which has "
            f"{len(everything)} frames.")
    return window, temp_dir


def propagate(request: PropagationRequest) -> Dict[str, Any]:
    """
    Track one object from `start_frame` forward.

    Returns a dict with per-frame results, the model used, and whether the run
    was cut short by the frame budget.
    """
    from PIL import Image

    from potato.ai.sam2_video import SAM2VideoTracker
    from potato.export.cv_utils import bitmap_to_rle

    model_dir = _require_model(request.model_dir)

    wanted = max(1, int(request.frames))
    truncated = wanted > request.max_frames
    count = min(wanted, request.max_frames)

    frame_paths, temp_dir = _frame_paths(
        request.video_path, int(request.start_frame), count, request.fps)
    try:
        images = [Image.open(path).convert("RGB") for path in frame_paths]
        tracker = SAM2VideoTracker(model_dir)
        tracked = tracker.track(images, request.points)

        results: List[PropagationResult] = []
        for offset, item in enumerate(tracked):
            rle = None
            if item.mask is not None:
                height, width = item.mask.shape
                # `bitmap_to_rle` takes a flat 0/1 bitmap, which is also what
                # every exporter reads, so the mask leaves here in exactly the
                # shape the rest of Potato stores.
                flat = item.mask.astype("uint8").reshape(-1).tolist()
                rle = bitmap_to_rle(flat, height, width)
            results.append(PropagationResult(
                frame=int(request.start_frame) + offset,
                visible=item.visible,
                score=item.object_score,
                rle=rle,
            ))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    payload: Dict[str, Any] = {
        "model": MODEL_KEY,
        "frames": [r.to_dict() for r in results],
        "occluded": sum(1 for r in results if not r.visible),
    }
    if truncated:
        # Said out loud. A short answer that reads as complete is the failure
        # this codebase keeps rediscovering.
        payload["truncated"] = True
        payload["requested_frames"] = wanted
        payload["max_frames"] = request.max_frames
    return payload

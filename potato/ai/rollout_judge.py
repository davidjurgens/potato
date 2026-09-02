"""
VLM-as-judge over a generated rollout: where does the world stop making sense?

The point is not to replace the annotator. It is to make automated world-model
benchmarks **checkable**: a judge that reports a break-point can be scored
against a human one with the same statistic humans are scored against each
other with (:mod:`potato.server_utils.iaa.rollouts`), and the resulting
alignment is a number a benchmark paper can quote instead of asserting that its
automatic metric correlates with human judgement.

## Why a contact sheet rather than a frame sequence

Almost every vision endpoint Potato can reach takes **one** image per call.
Sending frames one at a time asks the model "is this frame wrong?", which it
cannot answer — a physically impossible state is usually only visible as a
*change*, and a single frame of a floating cup looks like a cup on a shelf.

So the frames go up as one numbered grid. The model sees the sequence, can
compare tile N against tile N-1, and answers with a tile number. That is the
same information a human gets from scrubbing, compressed into what the API
accepts.

## The resolution is part of the answer

A 12-tile sheet of a 6-second clip localises a break to ±0.25 s and no better.
Comparing that against human marks at a 0.04 s tolerance would report a
disagreement that is an artifact of the sampling, so every prediction carries
its own ``resolution`` and :func:`align_with_humans` refuses to evaluate below
it rather than producing a number that looks like a finding.

## Failure is not a verdict

A model that timed out has said nothing about the rollout. It gets an ``error``
prediction that is excluded from alignment, never a "no break found" — counting
an outage as agreement with an annotator who also found nothing is how an
automatic metric flatters itself.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Frames sampled per rollout. Twelve fits a 4x3 sheet that stays legible after
#: the endpoint's own downscaling; more tiles means smaller tiles, and a
#: violation nobody can see is not localised by asking harder.
DEFAULT_TILES = 12

#: Longest side of the assembled sheet, in pixels. Above this most endpoints
#: downscale anyway and the upload is wasted.
MAX_SHEET_LONG_SIDE = 1536


class RolloutJudgeError(RuntimeError):
    """The judge could not run. The message names the next action."""


@dataclass
class BreakPrediction:
    """One model verdict about one rollout."""

    instance_id: str
    schema_name: str
    stream_id: str
    #: Seconds, or None when the model reported no break.
    t: Optional[float] = None
    violation_type: str = ""
    confidence: float = 0.0
    rationale: str = ""
    #: Half the sampling interval: the best this prediction can localise to.
    #: Carried per-prediction because it depends on the clip's own length.
    resolution: float = 0.0
    model_name: str = ""
    prompt_version: str = ""
    #: Set when the call failed. An errored prediction is excluded from
    #: alignment rather than counted as "no break".
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "schema_name": self.schema_name,
            "stream_id": self.stream_id,
            "t": self.t,
            "violation_type": self.violation_type,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "resolution": self.resolution,
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BreakPrediction":
        return cls(
            instance_id=data.get("instance_id", ""),
            schema_name=data.get("schema_name", ""),
            stream_id=data.get("stream_id", ""),
            t=data.get("t"),
            violation_type=data.get("violation_type", ""),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            rationale=data.get("rationale", ""),
            resolution=float(data.get("resolution", 0.0) or 0.0),
            model_name=data.get("model_name", ""),
            prompt_version=data.get("prompt_version", ""),
            error=data.get("error", ""),
        )


# ---------------------------------------------------------------------------
# Frame sampling and the contact sheet
# ---------------------------------------------------------------------------

def sample_times(duration: float, tiles: int = DEFAULT_TILES) -> List[float]:
    """
    The timestamps to grab, evenly spread and never at the very edges.

    Offset by half an interval on each side: the first and last frames of a
    generated clip are the two least informative — the first is the conditioning
    frame, which is correct by construction, and the last is often a fade or a
    truncation artifact. Sampling them wastes two of twelve tiles.
    """
    if duration <= 0 or tiles < 1:
        return []
    step = duration / tiles
    return [step * (i + 0.5) for i in range(tiles)]


def sheet_resolution(duration: float, tiles: int = DEFAULT_TILES) -> float:
    """
    How precisely a tile number can name a moment: half the sampling interval.

    Half, not whole: a break reported at tile N happened somewhere between the
    midpoints of tiles N-1 and N, so the true instant is within half an
    interval of the tile's own timestamp.
    """
    if duration <= 0 or tiles < 1:
        return 0.0
    return duration / tiles / 2.0


def extract_at_times(video_path: str, times: Sequence[float],
                     out_dir: str) -> List[Tuple[float, str]]:
    """
    Pull individual frames at specific timestamps with ffmpeg.

    One ``-ss`` seek per frame rather than an ``fps=`` filter, because the
    filter's output timestamps are only approximately the ones asked for and
    the whole value of this is that a tile number maps back to a known instant.
    A judge break-point off by an unknown fraction of a second cannot be scored
    against a human one.
    """
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        raise RolloutJudgeError(
            "Judging a rollout needs ffmpeg to sample frames. Install ffmpeg, "
            "or run the judge on a machine that has it.")

    out: List[Tuple[float, str]] = []
    for index, t in enumerate(times):
        path = os.path.join(out_dir, f"tile_{index:03d}.jpg")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.4f}", "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "3", path],
                capture_output=True, text=True, timeout=60, check=False)
        except (subprocess.SubprocessError, OSError) as exc:
            raise RolloutJudgeError(f"Could not sample frames: {exc}")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            out.append((t, path))
    if not out:
        raise RolloutJudgeError(
            f"ffmpeg produced no frames from {os.path.basename(video_path)}. "
            f"The file may be truncated or in a codec ffmpeg cannot read.")
    return out


def build_contact_sheet(frames: Sequence[Tuple[float, str]], columns: int = 4):
    """
    Assemble numbered tiles into one image.

    The number is drawn *on* the tile rather than described in the prompt,
    because a model asked to count tiles in reading order gets it wrong often
    enough to make the timestamps meaningless — and a wrong tile number is
    indistinguishable from a wrong verdict once it is a timestamp.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise RolloutJudgeError(
            "Judging a rollout needs Pillow to assemble the frames. "
            "Install it with: pip install Pillow")

    tiles = [Image.open(path).convert("RGB") for _t, path in frames]
    if not tiles:
        raise RolloutJudgeError("no frames to assemble")

    cols = max(1, min(columns, len(tiles)))
    rows = math.ceil(len(tiles) / cols)
    tile_w = max(t.width for t in tiles)
    tile_h = max(t.height for t in tiles)

    # Scale down before assembling, not after: a 4x3 sheet of 1080p frames is a
    # 12-megapixel upload that every endpoint downscales anyway.
    scale = min(1.0, MAX_SHEET_LONG_SIDE / max(tile_w * cols, tile_h * rows))
    tile_w = max(1, int(tile_w * scale))
    tile_h = max(1, int(tile_h * scale))

    sheet = Image.new("RGB", (tile_w * cols, tile_h * rows), (17, 21, 28))
    draw = ImageDraw.Draw(sheet)
    for index, tile in enumerate(tiles):
        x = (index % cols) * tile_w
        y = (index // cols) * tile_h
        sheet.paste(tile.resize((tile_w, tile_h)), (x, y))
        label = str(index + 1)
        # A filled plate behind the number, because a white number on a white
        # tabletop is invisible and the model then guesses the ordering.
        draw.rectangle([x + 2, y + 2, x + 26, y + 22], fill=(17, 21, 28))
        draw.text((x + 8, y + 6), label, fill=(255, 255, 255))
    return sheet


def build_prompt(types: Sequence[str], tiles: int, prompt: str = "") -> str:
    """The instruction. Explicit about the "no break" answer being allowed."""
    taxonomy = "\n".join(f"- {t}" for t in types)
    scenario = (f"\nThe scenario being generated: {prompt}\n" if prompt else "")
    return (
        f"You are shown {tiles} frames from a generated video, in time order, "
        f"numbered 1 to {tiles} in the top-left corner of each frame.\n"
        f"{scenario}\n"
        f"Find the FIRST frame at which the scene stops being physically or "
        f"causally coherent — where something happens that could not happen in "
        f"the real world. Compare each frame against the ones before it; a "
        f"single frame in isolation is rarely wrong.\n\n"
        f"Categories:\n{taxonomy}\n\n"
        f"If every frame is coherent, answer with break_tile = 0. Do not invent "
        f"a violation to have something to report.\n\n"
        f"Answer as JSON: {{\"break_tile\": <0 to {tiles}>, \"violation_type\": "
        f"\"<one category, or empty>\", \"confidence\": <0.0 to 1.0>, "
        f"\"rationale\": \"<one sentence>\"}}")


def parse_verdict(raw: Any, frames: Sequence[Tuple[float, str]],
                  types: Sequence[str]) -> Dict[str, Any]:
    """
    Turn whatever the model returned into a tile, a time and a category.

    Everything is re-validated rather than trusted. Open models return the tile
    as a string, the category outside the vocabulary, and the JSON inside a
    fenced block often enough that trusting the declared schema would
    manufacture findings — the same lesson the critique parser records.
    """
    payload = _as_dict(raw)
    if payload is None:
        return {"error": "the model did not return usable JSON"}

    tile = payload.get("break_tile", payload.get("break_frame"))
    try:
        tile = int(float(tile))
    except (TypeError, ValueError):
        return {"error": f"unusable break_tile {tile!r}"}

    if tile <= 0:
        return {"t": None, "violation_type": "",
                "confidence": _confidence(payload),
                "rationale": str(payload.get("rationale") or "")}
    if tile > len(frames):
        # Out of range is a real and common failure — the model counted tiles
        # it could not see. Clamping would silently place the break at the end
        # of the clip, which is a plausible-looking wrong answer.
        return {"error": f"the model named tile {tile} of {len(frames)}"}

    declared = str(payload.get("violation_type") or "").strip().lower()
    matched = next((t for t in types if t.lower() == declared), "")
    return {
        "t": frames[tile - 1][0],
        "violation_type": matched,
        "confidence": _confidence(payload),
        "rationale": str(payload.get("rationale") or ""),
        "unknown_type": declared if declared and not matched else "",
    }


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------

class RolloutJudge:
    """Judges one rollout set with a vision endpoint."""

    def __init__(self, config: Any, endpoint: Any,
                 options: Optional[Dict[str, Any]] = None):
        self.config = config
        self.endpoint = endpoint
        options = options or {}
        self.tiles = int(options.get("tiles", DEFAULT_TILES))
        self.columns = int(options.get("columns", 4))

    def judge_stream(self, video_path: str, duration: float,
                     types: Sequence[str], *,
                     instance_id: str = "", schema_name: str = "",
                     stream_id: str = "", prompt: str = "",
                     prompt_version: str = "") -> BreakPrediction:
        """Sample, assemble, ask, parse. Never raises — a failure is a verdict
        marked with its error, which alignment excludes."""
        prediction = BreakPrediction(
            instance_id=instance_id, schema_name=schema_name,
            stream_id=stream_id,
            resolution=sheet_resolution(duration, self.tiles),
            model_name=getattr(self.endpoint, "model_name", "") or "",
            prompt_version=prompt_version)

        try:
            with tempfile.TemporaryDirectory(prefix="rollout-judge-") as tmp:
                frames = extract_at_times(
                    video_path, sample_times(duration, self.tiles), tmp)
                sheet = build_contact_sheet(frames, self.columns)
                image_data = _sheet_to_image_data(sheet)
                raw = self._query(
                    build_prompt(types, len(frames), prompt), image_data)
                verdict = parse_verdict(raw, frames, types)
        except RolloutJudgeError as exc:
            prediction.error = str(exc)
            return prediction
        except Exception as exc:  # noqa: BLE001
            logger.warning("Rollout judge failed on %s/%s: %s",
                           instance_id, stream_id, exc)
            prediction.error = str(exc)
            return prediction

        if "error" in verdict:
            prediction.error = verdict["error"]
            return prediction
        prediction.t = verdict["t"]
        prediction.violation_type = verdict["violation_type"]
        prediction.confidence = verdict["confidence"]
        prediction.rationale = verdict["rationale"]
        return prediction

    def _query(self, prompt: str, image_data) -> Any:
        from potato.ai.prompt.models_module import CLASS_REGISTRY

        output_format = CLASS_REGISTRY.get("rollout_break")
        return self.endpoint.query_with_image(prompt, image_data, output_format)


# ---------------------------------------------------------------------------
# Alignment against humans
# ---------------------------------------------------------------------------

def align_with_humans(predictions: Sequence[BreakPrediction],
                      human: Dict[str, Dict[str, Any]],
                      tolerance: float = 0.5) -> Dict[str, Any]:
    """
    Score judge break-points against human ones.

    ``human`` is ``{f"{instance_id}::{stream_id}": {"t": <seconds or None>,
    "type": <category or "">}}`` — one consensus human answer per rollout,
    however the caller chose to derive it.

    Three numbers, mirroring the human-vs-human decomposition so a dashboard can
    put them side by side:

    * **detection** — does the judge agree a rollout breaks at all? Reported as
      a confusion count rather than as alpha, because with one judge and one
      consensus human there are two "annotators" and alpha over two raters with
      a heavily skewed marginal is unstable; the counts are what a reader can
      actually check.
    * **localization** — mean absolute offset among the rollouts where both
      found a break.
    * **category** — how often the categories match, among those.

    Refuses a tolerance finer than the coarsest prediction's resolution: a
    contact sheet cannot localise below half its sampling interval, and a
    disagreement at that scale would be an artifact of the sampling rather than
    a finding about the judge.
    """
    usable = [p for p in predictions if not p.error]
    excluded = len(predictions) - len(usable)

    coarsest = max((p.resolution for p in usable), default=0.0)
    if usable and tolerance < coarsest:
        return {
            "error": (
                f"a tolerance of {tolerance:g} s is finer than the judge's own "
                f"resolution ({coarsest:g} s — half the frame-sampling "
                f"interval). Raise the tolerance, or raise the tile count so "
                f"the judge samples more finely."),
            "n_predictions": len(predictions),
            "n_excluded_errors": excluded,
        }

    both = hit = judge_only = human_only = neither = 0
    offsets: List[float] = []
    category_hits = 0
    category_total = 0

    for prediction in usable:
        key = f"{prediction.instance_id}::{prediction.stream_id}"
        truth = human.get(key)
        if truth is None:
            continue
        human_t = truth.get("t")
        if prediction.t is None and human_t is None:
            neither += 1
        elif prediction.t is None:
            human_only += 1
        elif human_t is None:
            judge_only += 1
        else:
            both += 1
            offset = abs(float(prediction.t) - float(human_t))
            offsets.append(offset)
            if offset <= tolerance:
                hit += 1
                if truth.get("type"):
                    category_total += 1
                    if prediction.violation_type == truth.get("type"):
                        category_hits += 1

    compared = both + judge_only + human_only + neither
    return {
        "tolerance": tolerance,
        "judge_resolution": coarsest,
        "n_predictions": len(predictions),
        "n_excluded_errors": excluded,
        "n_compared": compared,
        "detection": {
            "both_found": both, "judge_only": judge_only,
            "human_only": human_only, "neither_found": neither,
            "agreement_rate": ((both + neither) / compared) if compared else None,
        },
        "localization": {
            "n_pairs": len(offsets),
            "mean_offset": (sum(offsets) / len(offsets)) if offsets else None,
            "within_tolerance": hit,
            "hit_rate": (hit / both) if both else None,
        },
        "category": {
            "n_compared": category_total,
            "matched": category_hits,
            "match_rate": ((category_hits / category_total)
                           if category_total else None),
        },
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _sheet_to_image_data(sheet, quality: int = 88):
    """Encode the sheet the way the vision endpoints expect an image."""
    from potato.ai.critique_service import crop_to_image_data

    return crop_to_image_data(sheet, quality=quality)


def _confidence(payload: Dict[str, Any]) -> float:
    try:
        value = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, value))


def _as_dict(raw: Any) -> Optional[Dict[str, Any]]:
    """
    Whatever the endpoint returned, as a dict — or None.

    Open models fence their JSON and pydantic-shaped returns are objects, so
    three shapes reach here. ``parseStringToJson``'s job, on the Python side.
    """
    import json
    import re

    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        try:
            return raw.model_dump()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(raw, "dict"):
        try:
            return raw.dict()
        except Exception:  # noqa: BLE001
            pass
    if isinstance(raw, str):
        text = raw.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if fenced:
            text = fenced.group(1).strip()
        brace = re.search(r"\{.*\}", text, re.S)
        if brace:
            text = brace.group(0)
        try:
            parsed = json.loads(text)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None

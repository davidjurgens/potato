"""
Runs a VLM critique pass over one image's annotations.

The I/O half of :mod:`potato.ai.critique`: resolves the image, renders one crop
per annotation with the annotator's own outline drawn onto it, queries a vision
endpoint per crop, and assembles the verdicts. All of the judgement rules --
what counts as a flag, how a response is parsed, what confidence gates -- live
in the pure module and are tested without a model.

Why the outline is drawn rather than described: asking "is this boundary tight?"
about a crop that does not show the boundary means the model answers about a
boundary it invented. Drawing it is the difference between a question the model
can answer and one where any answer is noise.

Why crops rather than one whole-image call: a 4000x3000 photograph downsampled
to a model's input resolution loses the twenty-pixel object entirely, so the
model confirms annotations it cannot see. Cropping puts the region at a
resolution where the question is answerable, which is the whole reason this
catches things a whole-image detector does not.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from potato.ai.critique import (
    CritiqueError,
    CritiqueRegion,
    CritiqueSummary,
    CritiqueVerdict,
    DEFAULT_CONTEXT_RATIO,
    DEFAULT_COVERAGE_RATIO,
    DEFAULT_MAX_REGIONS,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_CROP_PX,
    MissedObject,
    build_missed_prompt,
    build_region_prompt,
    crop_window,
    parse_missed,
    parse_region_verdict,
    regions_from_objects,
    summarize,
    suppress_covered,
)

logger = logging.getLogger(__name__)

#: Colour of the outline drawn onto each crop. Must match the wording in
#: ``critique.build_region_prompt``'s ``outline_colour``, or the prompt points
#: the model at a colour that is not in the picture.
OUTLINE_RGB = (255, 0, 0)
OUTLINE_NAME = "bright red"

#: Crops are upscaled to at least this long side. A 30x20 crop fed to a vision
#: tower that patches at 14px has barely two patches of signal; upscaling does
#: not add information but it stops the region being quantised away.
MIN_CROP_LONG_SIDE = 336

#: ...and downscaled to at most this, so a 2000px crop does not cost tokens
#: for detail the model cannot use.
MAX_CROP_LONG_SIDE = 768

#: Concurrent model calls. One per region, serially, is ~3s x N -- long enough
#: that annotators stop using the feature. Kept low because a self-hosted
#: single-GPU server is the common case and swamping it makes every request
#: slower, not just these.
DEFAULT_MAX_WORKERS = 4


@dataclass
class CritiqueResult:
    """Everything one critique pass produced."""

    instance_id: str = ""
    schema: str = ""
    verdicts: List[CritiqueVerdict] = field(default_factory=list)
    missed: List[MissedObject] = field(default_factory=list)
    summary: Optional[CritiqueSummary] = None
    model: str = ""
    image_width: int = 0
    image_height: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "schema": self.schema,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "missed": [m.to_dict() for m in self.missed],
            "summary": self.summary.to_dict() if self.summary else {},
            "model": self.model,
            "image_width": self.image_width,
            "image_height": self.image_height,
        }


# --------------------------------------------------------------------------
# Image loading
# --------------------------------------------------------------------------

def _require_pillow():
    try:
        from PIL import Image, ImageDraw  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise CritiqueError(
            "Annotation critique needs Pillow to crop regions. "
            "Install it with: pip install Pillow"
        ) from exc
    from PIL import Image, ImageDraw

    return Image, ImageDraw


def load_image(reference: str, config: Any, timeout: int = 30):
    """Open the image an item refers to, as PIL RGB.

    Accepts the three shapes items actually carry: a ``/media/...`` URL path,
    a filesystem path, and a remote URL. Remote images ARE fetched here, unlike
    ``vision_features`` which refuses to -- that module ranks a whole unlabeled
    pool from a background thread, while this is one image on one click.
    """
    Image, _ = _require_pillow()

    ref = str(reference or "").strip()
    if not ref:
        raise CritiqueError("This item has no image to critique.")

    if ref.startswith(("http://", "https://")):
        try:
            import io

            import requests

            response = requests.get(ref, timeout=timeout)
            response.raise_for_status()
            return Image.open(io.BytesIO(response.content)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise CritiqueError(f"Could not fetch the image: {exc}") from exc

    from potato.media.paths import resolve_media_url

    path = resolve_media_url(config, ref, context="Critique")
    if path is None:
        # Not under media/ -- try it as a plain path relative to task_dir,
        # which is how configs that predate the media directory reference
        # files. Traversal above task_dir is refused for the same reason the
        # media guard exists: these bytes leave the machine.
        task_dir = os.path.realpath(config.get("task_dir", "."))
        candidate = os.path.realpath(os.path.join(task_dir, ref.lstrip("/")))
        if not (candidate == task_dir or candidate.startswith(task_dir + os.sep)):
            raise CritiqueError("Refusing to read an image outside the project.")
        if not os.path.isfile(candidate):
            raise CritiqueError(f"Image not found: {reference}")
        path = candidate

    try:
        with Image.open(path) as image:
            return image.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise CritiqueError(f"Could not read the image: {exc}") from exc


# --------------------------------------------------------------------------
# Crop rendering
# --------------------------------------------------------------------------

def render_region_crop(image, region: CritiqueRegion,
                       context_ratio: float = DEFAULT_CONTEXT_RATIO,
                       min_px: int = DEFAULT_MIN_CROP_PX):
    """Crop around ``region`` and draw its outline onto the crop.

    The outline is the region's real geometry where one exists -- a polygon is
    drawn as a polygon, a mask as its outline -- and its bbox otherwise. Drawing
    every type as a rectangle would ask the model whether a box is tight around
    an object the annotator actually traced, which is a different and much
    easier question than the one worth asking.
    """
    Image, ImageDraw = _require_pillow()

    window = crop_window(region.bbox, image.width, image.height,
                         context_ratio=context_ratio, min_px=min_px)
    crop = image.crop((window.x0, window.y0, window.x1, window.y1))

    # Scale before drawing so the outline stays a constant on-screen width
    # rather than being resampled into a smear on a heavily upscaled crop.
    long_side = max(crop.width, crop.height)
    if long_side > 0:
        if long_side < MIN_CROP_LONG_SIDE:
            factor = MIN_CROP_LONG_SIDE / long_side
        elif long_side > MAX_CROP_LONG_SIDE:
            factor = MAX_CROP_LONG_SIDE / long_side
        else:
            factor = 1.0
    else:
        factor = 1.0

    if factor != 1.0:
        crop = crop.resize(
            (max(1, int(round(crop.width * factor))),
             max(1, int(round(crop.height * factor)))),
            Image.Resampling.LANCZOS,
        )

    draw = ImageDraw.Draw(crop)
    width = max(2, int(round(max(crop.width, crop.height) / 160)))

    points = region.points
    if points and len(points) >= 2:
        local = [(p[0] * factor, p[1] * factor)
                 for p in window.shift(points)]
        closed = region.type != "polyline"
        draw.line(local + ([local[0]] if closed and len(local) > 2 else []),
                  fill=OUTLINE_RGB, width=width)
    else:
        x, y, w, h = window.shift_bbox(region.bbox)
        draw.rectangle(
            [x * factor, y * factor, (x + w) * factor, (y + h) * factor],
            outline=OUTLINE_RGB, width=width,
        )

    return crop, window


def crop_to_image_data(crop, quality: int = 88):
    """Encode a PIL crop as the :class:`ImageData` endpoints accept."""
    import base64
    import io

    from potato.ai.ai_endpoint import ImageData

    buffer = io.BytesIO()
    crop.save(buffer, format="JPEG", quality=quality)
    return ImageData(
        source="base64",
        data=base64.b64encode(buffer.getvalue()).decode("utf-8"),
        width=crop.width,
        height=crop.height,
        mime_type="image/jpeg",
    )


# --------------------------------------------------------------------------
# The pass
# --------------------------------------------------------------------------

class CritiqueService:
    """Critiques one image's annotations with a vision endpoint."""

    def __init__(self, config: Any, endpoint: Any, options: Optional[Dict] = None):
        self.config = config
        self.endpoint = endpoint
        options = options or {}
        self.context_ratio = float(options.get("context_ratio",
                                               DEFAULT_CONTEXT_RATIO))
        self.min_crop_px = int(options.get("min_crop_px", DEFAULT_MIN_CROP_PX))
        self.min_confidence = float(options.get("min_confidence",
                                                DEFAULT_MIN_CONFIDENCE))
        self.max_regions = int(options.get("max_regions", DEFAULT_MAX_REGIONS))
        self.coverage_ratio = float(options.get("coverage_ratio",
                                                DEFAULT_COVERAGE_RATIO))
        self.max_workers = max(1, int(options.get("max_workers",
                                                  DEFAULT_MAX_WORKERS)))
        self.check_missed = bool(options.get("check_missed", True))

    # -- one region ----------------------------------------------------

    def _query(self, prompt: str, image_data) -> Any:
        """One vision call, tolerant of endpoints with different signatures."""
        from potato.ai.prompt.models_module import CLASS_REGISTRY

        output_format = CLASS_REGISTRY.get("annotation_critique")
        return self.endpoint.query_with_image(prompt, image_data, output_format)

    def critique_region(self, image, region: CritiqueRegion,
                        labels: Sequence[str], description: str
                        ) -> CritiqueVerdict:
        """Render, ask, parse. Never raises -- a failure is an error verdict."""
        try:
            crop, _ = render_region_crop(
                image, region,
                context_ratio=self.context_ratio,
                min_px=self.min_crop_px,
            )
            image_data = crop_to_image_data(crop)
            prompt = build_region_prompt(region, labels, description,
                                         outline_colour=OUTLINE_NAME)
            raw = self._query(prompt, image_data)
            return parse_region_verdict(raw, region, labels,
                                        min_confidence=self.min_confidence)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Critique of region %d failed: %s", region.index, exc)
            verdict = CritiqueVerdict(index=region.index, label=region.label)
            # An error is NOT a flag. A model that timed out has said nothing
            # about the annotation, and showing it in the review queue would
            # manufacture a finding out of an outage.
            verdict.verdict = "uncertain"
            verdict.error = str(exc)
            verdict.rationale = "The model could not be reached for this region."
            return verdict

    # -- missed objects ------------------------------------------------

    def find_missed(self, image, regions: Sequence[CritiqueRegion],
                    labels: Sequence[str], description: str
                    ) -> List[MissedObject]:
        try:
            whole = image
            long_side = max(whole.width, whole.height)
            if long_side > MAX_CROP_LONG_SIDE * 2:
                Image, _ = _require_pillow()
                factor = (MAX_CROP_LONG_SIDE * 2) / long_side
                whole = whole.resize(
                    (max(1, int(whole.width * factor)),
                     max(1, int(whole.height * factor))),
                    Image.Resampling.LANCZOS)
            image_data = crop_to_image_data(whole)
            prompt = build_missed_prompt(regions, labels, description)
            raw = self._query(prompt, image_data)
            found = parse_missed(raw, labels,
                                 min_confidence=self.min_confidence)
            # A "missed" object sitting on an annotation that already exists is
            # the per-region verdict's finding, reported twice.
            return suppress_covered(found, regions, image.width, image.height,
                                    coverage_ratio=self.coverage_ratio)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Missed-object pass failed: %s", exc)
            return []

    # -- the whole pass ------------------------------------------------

    def critique(self, objects: Sequence[Any], image_reference: str,
                 labels: Sequence[str], description: str = "",
                 instance_id: str = "", schema: str = "") -> CritiqueResult:
        """Critique every annotation on one image.

        Raises :class:`CritiqueError` only for failures that make the whole
        pass impossible (no image, no Pillow). Per-region failures degrade to
        ``uncertain`` verdicts so one bad crop does not lose the other 23.
        """
        image = load_image(image_reference, self.config)
        regions = regions_from_objects(objects, image.width, image.height)

        skipped = max(0, len(objects) - len(regions))
        if len(regions) > self.max_regions:
            # Reported, never silent: a truncated review that reads as complete
            # is worse than no review.
            skipped += len(regions) - self.max_regions
            regions = regions[:self.max_regions]

        verdicts: List[CritiqueVerdict] = []
        if regions:
            if self.max_workers > 1 and len(regions) > 1:
                with concurrent.futures.ThreadPoolExecutor(
                        max_workers=min(self.max_workers, len(regions))) as pool:
                    futures = {
                        pool.submit(self.critique_region, image, region,
                                    labels, description): region
                        for region in regions
                    }
                    for future in concurrent.futures.as_completed(futures):
                        verdicts.append(future.result())
            else:
                verdicts = [self.critique_region(image, r, labels, description)
                            for r in regions]

        # as_completed returns in finish order; the review queue reads far
        # better in the order the annotator drew them.
        verdicts.sort(key=lambda v: v.index)

        missed: List[MissedObject] = []
        if self.check_missed and labels:
            missed = self.find_missed(image, regions, labels, description)

        return CritiqueResult(
            instance_id=instance_id,
            schema=schema,
            verdicts=verdicts,
            missed=missed,
            summary=summarize(verdicts, missed, skipped=skipped),
            model=str(getattr(self.endpoint, "model", "") or ""),
            image_width=image.width,
            image_height=image.height,
        )

"""
Boundary probes for images.

The text probes ask "does your label survive this minimal edit?". The visual
equivalent asks the same question of a transformed image, and the transforms
split the same two ways:

* **invariance** — greyscale, a mirror, a slight crop, a brightness shift.
  A label that depends on any of these is a label that will not replicate.
  These are the visual analogue of a paraphrase, and they double as quality
  control exactly the way paraphrase probes do.
* **flip** — occlusion of a region, heavy blur. Enough evidence is removed
  that the honest answer may well change, which is what makes them
  informative: an annotator who never flips on an occluded image is either
  labelling from context or not looking.

Every transform is expressed as something the browser applies to the original
image — a CSS filter, a mirror, an inset clip, a rectangle drawn over it. No
pixels are processed and nothing is written to disk, so a probe costs one
`<img>` tag and works on remote media the server never fetches.

The one thing this cannot do is generate a *semantic* counterfactual — the same
scene with the object removed. That needs image editing, and inventing one with
a generative model would put a fabricated image in front of an annotator and
call it the item. Out of scope on purpose.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Tuple

KIND_FLIP = "flip"
KIND_INVARIANCE = "invariance"

#: (transform, kind, hint). Ordered by how much they usually cost the
#: annotator, cheapest first, so a small budget spends it on the mildest edits.
_TRANSFORMS: List[Tuple[Dict[str, Any], str, str]] = [
    ({"filter": "grayscale(1)"}, KIND_INVARIANCE, "colour removed"),
    ({"mirror": True}, KIND_INVARIANCE, "mirrored left to right"),
    ({"filter": "brightness(0.7)"}, KIND_INVARIANCE, "darker"),
    ({"filter": "brightness(1.35) saturate(0.7)"}, KIND_INVARIANCE,
     "brighter and washed out"),
    ({"crop": [0.08, 0.08, 0.08, 0.08]}, KIND_INVARIANCE, "cropped in slightly"),
    ({"filter": "blur(3px)"}, KIND_FLIP, "blurred"),
    ({"occlude": [0.32, 0.30, 0.36, 0.40]}, KIND_FLIP, "centre covered"),
    ({"occlude": [0.0, 0.55, 1.0, 0.45]}, KIND_FLIP, "lower half covered"),
    ({"crop": [0.3, 0.3, 0.0, 0.0]}, KIND_FLIP, "only the bottom-right corner"),
]


def transform_id(reference: str, transform: Dict[str, Any]) -> str:
    """Stable id for a (image, transform) pair.

    Keyed on the transform's canonical JSON rather than a description, so
    editing a hint's wording does not orphan the verdicts already collected
    against it.
    """
    raw = f"{reference}\x00{json.dumps(transform, sort_keys=True)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def describe(transform: Dict[str, Any]) -> str:
    """Plain words for a transform — used in the accessible name."""
    for candidate, _kind, hint in _TRANSFORMS:
        if candidate == transform:
            return hint
    return "altered"


def generate_image_probes(reference: str, n_flip: int, n_invariance: int
                          ) -> List[Tuple[Dict[str, Any], str, str]]:
    """Up to ``n_flip`` + ``n_invariance`` transforms for one image.

    Deterministic: the same image gets the same probes on every annotator's
    screen, which is what makes the verdicts comparable.
    """
    if not reference:
        return []
    chosen: List[Tuple[Dict[str, Any], str, str]] = []
    flips = invariances = 0
    for transform, kind, hint in _TRANSFORMS:
        if kind == KIND_FLIP and flips < n_flip:
            chosen.append((transform, kind, hint))
            flips += 1
        elif kind == KIND_INVARIANCE and invariances < n_invariance:
            chosen.append((transform, kind, hint))
            invariances += 1
        if flips >= n_flip and invariances >= n_invariance:
            break
    # Flips first, invariance last: the same ordering the text probes use.
    return ([c for c in chosen if c[1] == KIND_FLIP]
            + [c for c in chosen if c[1] == KIND_INVARIANCE])


def to_style(transform: Dict[str, Any]) -> Dict[str, Any]:
    """The client-side recipe for one transform.

    Returned as data rather than a CSS string so the client can put each piece
    where it belongs (a filter on the image, an inset on its clip, a rectangle
    over it) and nothing from an item field is ever interpolated into markup.
    """
    style: Dict[str, Any] = {}
    if transform.get("filter"):
        style["filter"] = str(transform["filter"])
    if transform.get("mirror"):
        style["mirror"] = True
    crop = transform.get("crop")
    if isinstance(crop, (list, tuple)) and len(crop) == 4:
        # top, right, bottom, left as fractions, matching CSS inset() order.
        style["inset"] = [max(0.0, min(0.9, float(v))) for v in crop]
    occlude = transform.get("occlude")
    if isinstance(occlude, (list, tuple)) and len(occlude) == 4:
        style["occlude"] = [max(0.0, min(1.0, float(v))) for v in occlude]
    return style

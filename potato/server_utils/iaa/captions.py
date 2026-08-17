"""
Agreement over free-text captions, and over captions attached to regions.

Two annotators describing the same thing rarely use the same words. "a man in a
red shirt" and "person wearing a crimson top" are the same answer and share no
content word, so every exact-match coefficient scores them as total
disagreement. That is why caption agreement is almost never reported — and why
reporting it is worth doing.

## The distance is pluggable, and the default is honest about being weak

Krippendorff's alpha already accepts a callable distance
(:func:`~potato.server_utils.iaa.alpha.krippendorff_alpha`), so nothing new is
needed at the coefficient level. What is needed is a δ over text:

- ``embedding`` — cosine distance between sentence embeddings. Needs
  ``sentence-transformers``, which is an optional dependency.
- ``token`` — 1 − Jaccard over content tokens. The default, because it always
  works, and **it is a poor proxy**: it scores the two phrases above as
  complete disagreement. It is reported under its own name rather than as
  "semantic similarity" so nobody quotes it as one.

**The embedding distance is better, not good.** Measured against
``all-MiniLM-L6-v2`` (``tests/unit/test_caption_embedding_distance.py``, which
runs on request rather than in the suite):

===============================================  =========  =======
pair                                             embedding  token
===============================================  =========  =======
"a man in a red shirt" / "person wearing a
crimson top"                                         0.598    1.000
"a small dog on the grass" / "a puppy in the
lawn"                                                0.358    1.000
"two people talking" / "a pair of individuals
conversing"                                          0.127    1.000
"a man in a red shirt" / "an empty parking lot"      1.000    1.000
===============================================  =========  =======

So the headline example — the one this docstring opens with — still lands at
0.6, well away from "the same sentence". Substituting both the colour word and
the garment word is hard for a small model. What holds robustly is the
*separation*: every paraphrase sits below every unrelated pair by a wide margin,
which is the property alpha needs, and it is what the test asserts. Read a
single embedding-distance value as a rough ordering, not as a semantic verdict,
and prefer a larger model when the captions are long or domain-specific.

The choice is surfaced in the report rather than buried, because an alpha of
0.3 under the token distance and an alpha of 0.3 under embeddings are different
findings — the first may be entirely an artifact of vocabulary.

## Captions are compared per matched region, not per item

Two annotators who both wrote three captions for an image did not necessarily
write them about the same three things. Captions are therefore compared only
within regions that matched geometrically, using the same matcher the geometry
report uses; unmatched regions are a *detection* disagreement and are counted
there instead of being scored as a caption disagreement, which would blame the
wrong thing.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .alpha import krippendorff_alpha

logger = logging.getLogger(__name__)

#: Words carrying no content for this purpose. Deliberately short: an
#: aggressive stop list starts deciding which words are meaningful, and for
#: "the cup behind the kettle" the prepositions are the answer.
_STOPWORDS = frozenset({
    "a", "an", "the", "of", "is", "are", "was", "were", "be", "being", "been",
    "and", "or", "to", "it", "its", "this", "that", "these", "those",
})

_TOKEN = re.compile(r"[a-z0-9']+")

#: How far apart two regions may be and still be considered the same object.
#: The same default the geometry report uses, so the two agree about what
#: "matched" means.
DEFAULT_MATCH_IOU = 0.5


def tokens(text: str) -> frozenset:
    """Content tokens of a caption, lowercased."""
    return frozenset(t for t in _TOKEN.findall(str(text or "").lower())
                     if t not in _STOPWORDS)


def token_distance(a: str, b: str) -> float:
    """
    1 − Jaccard over content tokens.

    Cheap, dependency-free, and **not a measure of meaning**. Two correct
    paraphrases sharing no vocabulary score 1.0 — complete disagreement — which
    is why the report names the distance it used.
    """
    left, right = tokens(a), tokens(b)
    if not left and not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return 1.0 - len(left & right) / len(union)


def embedding_distance_fn(model_name: str = "all-MiniLM-L6-v2"
                          ) -> Optional[Callable[[str, str], float]]:
    """
    A cosine-distance δ over sentence embeddings, or None if unavailable.

    Returns None rather than raising so a caller can fall back and *say so*.
    The import is inside the function because ``sentence-transformers`` pulls in
    torch, and Potato's boot path must not load the ML stack (invariant 6).
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None

    try:
        model = SentenceTransformer(model_name)
    except Exception as exc:  # noqa: BLE001 - a model download can fail
        logger.warning("Could not load the embedding model %s: %s",
                       model_name, exc)
        return None

    cache: Dict[str, Any] = {}

    def encode(text: str):
        key = str(text or "")
        if key not in cache:
            cache[key] = model.encode(key, normalize_embeddings=True)
        return cache[key]

    def distance(a: str, b: str) -> float:
        left, right = encode(a), encode(b)
        cosine = float(sum(x * y for x, y in zip(left, right)))
        # Clamped: normalized vectors put cosine in [-1, 1], and a distance
        # outside [0, 1] makes alpha's arithmetic meaningless.
        return max(0.0, min(1.0, 1.0 - cosine))

    return distance


def caption_alpha(rows: Sequence[Tuple[str, str, str]],
                  distance: str = "token",
                  model_name: str = "all-MiniLM-L6-v2") -> Dict[str, Any]:
    """
    Alpha over captions.

    ``rows`` is ``(annotator_id, unit_id, caption)``. The unit is whatever the
    caller decided two captions are *about* — an item for whole-image
    captioning, a matched region for region captioning.

    The distance actually used is reported, including when the requested one
    was unavailable: an alpha computed with a lexical fallback while the caller
    asked for embeddings is a different number, and silently substituting it is
    how a weak result gets quoted as a semantic one.
    """
    requested = distance
    delta: Callable[[Any, Any], float] = token_distance
    used = "token"
    note = ""

    if distance == "embedding":
        embedded = embedding_distance_fn(model_name)
        if embedded is not None:
            delta = embedded
            used = "embedding"
        else:
            note = (
                "sentence-transformers is not installed, so the token distance "
                "was used instead. It scores correct paraphrases as complete "
                "disagreement, so this alpha is a LOWER BOUND on semantic "
                "agreement, not a measure of it. `pip install "
                "sentence-transformers` for the real thing.")

    usable = [(str(a), str(u), str(c)) for a, u, c in rows
              if str(c or "").strip()]
    result: Dict[str, Any] = {
        "n_captions": len(usable),
        "n_units": len({u for _a, u, _c in usable}),
        "n_annotators": len({a for a, _u, _c in usable}),
        "distance_requested": requested,
        "distance_used": used,
    }
    if note:
        result["note"] = note

    if len(usable) < 2 or result["n_annotators"] < 2:
        result["alpha"] = None
        result["note"] = (result.get("note", "") + " "
                          if result.get("note") else "") + (
            "fewer than two annotators wrote a caption, so there is nothing to "
            "compare")
        return result

    value = krippendorff_alpha(usable, delta)
    result["alpha"] = None if (isinstance(value, float) and math.isnan(value)) \
        else value
    result["mean_pairwise_distance"] = _mean_pairwise(usable, delta)
    return result


def _mean_pairwise(rows, delta) -> float:
    """
    Raw mean distance between captions of the same unit.

    Reported beside alpha because alpha is chance-corrected and this is not:
    when a corpus's captions are all near-identical, alpha can be undefined or
    negative while the raw agreement is excellent, and only the pair explains
    what happened.
    """
    by_unit: Dict[str, List[str]] = {}
    for _annotator, unit, caption in rows:
        by_unit.setdefault(unit, []).append(caption)

    distances = []
    for captions in by_unit.values():
        for i in range(len(captions)):
            for j in range(i + 1, len(captions)):
                distances.append(delta(captions[i], captions[j]))
    return (sum(distances) / len(distances)) if distances else float("nan")


def region_caption_rows(items: Dict[str, Dict[str, Any]],
                        match_iou: float = DEFAULT_MATCH_IOU
                        ) -> Tuple[List[Tuple[str, str, str]], Dict[str, Any]]:
    """
    Turn per-annotator region captions into ``(annotator, unit, caption)`` rows.

    ``items`` is ``{item_id: {annotator_id: [{"region": <object>,
    "caption": str}, ...]}}``.

    Regions are matched between annotators by IoU before their captions are
    compared, because two annotators who each wrote three captions did not
    necessarily write them about the same three things. Comparing caption *k*
    of one with caption *k* of the other would measure the order they happened
    to draw in.

    Returns the rows and a summary of what matching cost — an unmatched region
    is a **detection** disagreement and is reported as one rather than being
    scored as a caption disagreement, which would blame the wrong thing.
    """
    from potato.grounding.metrics import region_similarity

    rows: List[Tuple[str, str, str]] = []
    matched = unmatched = 0

    for item_id, per_annotator in items.items():
        annotators = sorted(per_annotator)
        if len(annotators) < 2:
            continue

        # The first annotator's regions define the units; everyone else is
        # matched onto them. Arbitrary but stable, and stated: a different
        # anchor gives slightly different units when annotators disagree about
        # how many objects there are.
        anchor = annotators[0]
        anchor_entries = per_annotator[anchor] or []
        for index, entry in enumerate(anchor_entries):
            unit = f"{item_id}::{index}"
            caption = str(entry.get("caption") or "")
            if caption.strip():
                rows.append((anchor, unit, caption))

            for other in annotators[1:]:
                best, best_score = None, 0.0
                for candidate in (per_annotator[other] or []):
                    score = region_similarity(entry.get("region") or {},
                                              candidate.get("region") or {})
                    if score > best_score:
                        best, best_score = candidate, score
                if best is not None and best_score >= match_iou:
                    matched += 1
                    other_caption = str(best.get("caption") or "")
                    if other_caption.strip():
                        rows.append((other, unit, other_caption))
                else:
                    unmatched += 1

    return rows, {
        "n_matched_regions": matched,
        "n_unmatched_regions": unmatched,
        "match_iou": match_iou,
    }


def region_caption_report(items: Dict[str, Dict[str, Any]],
                          distance: str = "token",
                          match_iou: float = DEFAULT_MATCH_IOU,
                          model_name: str = "all-MiniLM-L6-v2"
                          ) -> Dict[str, Any]:
    """The full report: matching, then caption alpha over what matched."""
    rows, matching = region_caption_rows(items, match_iou=match_iou)
    report = caption_alpha(rows, distance=distance, model_name=model_name)
    report["matching"] = matching
    return report

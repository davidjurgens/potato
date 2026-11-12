"""
Agreement for interlinear glossed text (``annotation_type: interlinear_gloss``).

An answer is one JSON blob, ``{"words": [{"word", "morphemes", "gloss",
<tier>...}], "translation"}``, so there is no label name to compare: reduced to
one, every annotator "chose" the scheme and agreed perfectly. Each line of the
analysis is scored on its own instead, because the lines disagree for
different reasons and have different fixes:

* ``segmentation``: the morpheme line of each word, each (item, word) a unit.
* ``gloss``: the whole gloss of each word, each (item, word) a unit.
* ``morpheme_gloss``: the gloss of each morpheme, each (item, word, morpheme)
  a unit, counted only on words every annotator segmented the same way. On a
  word segmented two ways the morphemes do not correspond, and scoring them by
  position would charge a segmentation disagreement to the gloss.
* ``tier_<name>``: each configured extra tier, per word.

All are nominal: two cells agree when their text is identical after trimming.
An empty cell is an unanswered one, not the answer "", so two annotators who
both skipped a word do not count as agreeing on it. The free translation is not
scored; it is free text and has no unit to align.
"""

from __future__ import annotations

import itertools
import math
from typing import Any, Dict, List, Optional, Tuple

#: One layer's ratings, as (annotator, unit, value).
_Long = List[Tuple[str, str, str]]


def _decode(stored: Any) -> Optional[Dict[str, Any]]:
    from potato.igt import decode_answer
    return decode_answer(stored)


def _layer(long_rows: _Long) -> Dict[str, Any]:
    """Alpha and pairwise percent agreement over one layer's (annotator, unit, value)."""
    from potato.server_utils.iaa.alpha import krippendorff_alpha

    by_unit: Dict[str, Dict[str, str]] = {}
    for annotator, unit, value in long_rows:
        by_unit.setdefault(unit, {})[annotator] = value
    # A unit only one annotator answered carries no agreement information.
    by_unit = {u: v for u, v in by_unit.items() if len(v) >= 2}
    if not by_unit:
        return {"alpha": None, "percent_agreement": None, "n_units": 0,
                "note": "No unit was filled in by two or more annotators."}
    rows = [(a, u, v) for u, per in by_unit.items() for a, v in per.items()]
    alpha = krippendorff_alpha(rows, level="nominal")
    agree = total = 0
    for per in by_unit.values():
        for x, y in itertools.combinations(per.values(), 2):
            total += 1
            agree += x == y
    out = {"alpha": None if math.isnan(alpha) else alpha,
           "percent_agreement": agree / total,
           "n_units": len(by_unit)}
    if out["alpha"] is None:
        # Alpha is undefined when every value is the same (no expected
        # disagreement) or there is a single unit; the percentage still says
        # what happened.
        out["note"] = ("Alpha is undefined here: there are too few units, or "
                       "every annotator gave the same value everywhere.")
    return out


def gloss_report(rows: Dict[str, Dict[str, Any]], scheme: Dict[str, Any]) -> Dict[str, Any]:
    """Per-line agreement for one interlinear_gloss scheme.

    ``rows`` is ``{instance_id: {user_id: stored_value}}`` as
    ``dispatcher._gather_raw`` returns it.
    """
    from potato.igt import split_cell

    tiers = [str(t) for t in (scheme.get("tiers") or [])]
    layers: Dict[str, _Long] = {"segmentation": [], "gloss": [], "morpheme_gloss": []}
    for tier in tiers:
        layers["tier_" + tier] = []

    items = 0
    seen_annotators = set()
    for iid, per_user in rows.items():
        answers = {uid: a for uid, a in ((u, _decode(v)) for u, v in per_user.items()) if a}
        if len(answers) < 2:
            continue
        items += 1
        seen_annotators.update(answers)
        n_words = max(len(a["words"]) for a in answers.values())
        for i in range(n_words):
            cells = {uid: a["words"][i] for uid, a in answers.items() if i < len(a["words"])}
            # The word line comes from the item, so annotators normally share
            # it; if it differs they were shown different text at this
            # position and nothing there is comparable.
            if len({c.get("word", "") for c in cells.values()}) > 1:
                continue
            unit = f"{iid}#{i}"
            for line, layer in [("morphemes", "segmentation"), ("gloss", "gloss")] + \
                    [(t, "tier_" + t) for t in tiers]:
                for uid, cell in cells.items():
                    value = str(cell.get(line, "")).strip()
                    if value:
                        layers[layer].append((uid, unit, value))

            # Morpheme glosses, only where every annotator who segmented the
            # word split it into the same pieces.
            segmented = {uid: str(c.get("morphemes", "")).strip()
                         for uid, c in cells.items() if str(c.get("morphemes", "")).strip()}
            if len(segmented) < 2 or len(set(segmented.values())) != 1:
                continue
            pieces, bounds, _ = split_cell(next(iter(segmented.values())))
            for uid in segmented:
                g_pieces, g_bounds, _ = split_cell(cells[uid].get("gloss", ""))
                if g_bounds != bounds:
                    continue
                for k, g in enumerate(g_pieces):
                    if g.strip():
                        layers["morpheme_gloss"].append((uid, f"{unit}#{k}", g.strip()))

    if not items:
        return {"n_items": 0, "n_annotators": 0,
                "note": "No item has a gloss from two or more annotators yet."}
    report: Dict[str, Any] = {"n_items": items, "n_annotators": len(seen_annotators)}
    for name, long_rows in layers.items():
        report[name] = _layer(long_rows)
    return report

"""
LLM-judge bias & robustness diagnostics — the second axis beyond agreement (κ).

Potato's judge↔human dashboard reports *agreement* (κ, drift). But a judge can agree
with humans on average yet still be *biased* and *non-robust* — and 2026 research
finds style/length bias (0.76–0.92) dominates and is invisible to a single κ. This
module adds the missing axis and packages both into a portable **eval card**:

- **Verbosity / length bias** — does the judge favor longer outputs more than humans
  do? (correlation of output length with the judge's positive-rate minus the human's).
- **Confidence calibration** — does the judge's stated confidence track its actual
  correctness vs human gold? (expected calibration error + reliability buckets).
- **Position-swap consistency** — for option-order / pairwise judging, how often does
  the verdict *flip* when the order is reversed? (a runnable probe; needs the judge).

Pure stdlib for the data functions; the position probe takes a judge callable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class BiasRecord:
    text_len: int
    judge_label: str
    human_label: str


def verbosity_bias(records: List[BiasRecord], positive_label: Optional[str] = None
                   ) -> Dict[str, Any]:
    """Does the judge assign the 'positive' label to longer outputs *more than humans
    do*? Returns the judge's and human's mean length for the positive class and the
    **excess** (judge_gap − human_gap) where gap = mean_len(positive) − mean_len(rest).
    A large positive excess ⇒ the judge over-rewards length relative to humans.
    """
    if not records:
        return {"n": 0, "length_bias_excess": None, "interpretation": "no data"}
    labels = [r.judge_label for r in records] + [r.human_label for r in records]
    pos = positive_label or _most_common(labels)

    def gap(getter):
        pos_lens = [r.text_len for r in records if getter(r) == pos]
        neg_lens = [r.text_len for r in records if getter(r) != pos]
        if not pos_lens or not neg_lens:
            return None
        return (sum(pos_lens) / len(pos_lens)) - (sum(neg_lens) / len(neg_lens))

    jg = gap(lambda r: r.judge_label)
    hg = gap(lambda r: r.human_label)
    excess = (jg - hg) if (jg is not None and hg is not None) else None
    interp = "insufficient variation"
    if excess is not None:
        interp = ("judge over-rewards length" if excess > 20 else
                  "judge under-rewards length" if excess < -20 else "no notable length bias")
    return {"n": len(records), "positive_label": pos,
            "judge_length_gap": _r(jg), "human_length_gap": _r(hg),
            "length_bias_excess": _r(excess), "interpretation": interp}


def confidence_calibration(records: List[Tuple[float, bool]], n_buckets: int = 5
                           ) -> Dict[str, Any]:
    """Expected Calibration Error from ``(confidence, correct)`` pairs.

    Buckets confidence into ``n_buckets`` bins; ECE is the weighted gap between mean
    confidence and accuracy per bin. Lower is better-calibrated (0 = perfect).
    """
    pairs = [(min(1.0, max(0.0, float(c))), bool(ok)) for c, ok in records if c is not None]
    n = len(pairs)
    if n == 0:
        return {"n": 0, "ece": None, "buckets": []}
    buckets = []
    ece = 0.0
    for b in range(n_buckets):
        lo, hi = b / n_buckets, (b + 1) / n_buckets
        inb = [(c, ok) for c, ok in pairs if (c >= lo and (c < hi or (b == n_buckets - 1 and c <= hi)))]
        if not inb:
            continue
        conf = sum(c for c, _ in inb) / len(inb)
        acc = sum(1 for _c, ok in inb if ok) / len(inb)
        ece += (len(inb) / n) * abs(conf - acc)
        buckets.append({"range": [round(lo, 2), round(hi, 2)], "n": len(inb),
                        "mean_confidence": _r(conf), "accuracy": _r(acc)})
    return {"n": n, "ece": _r(ece), "buckets": buckets}


def position_swap_consistency(judge_two_orderings: Callable[[str], Tuple[str, str]],
                              item_ids: List[str]) -> Dict[str, Any]:
    """Position-bias probe. ``judge_two_orderings(item_id)`` must return the judge's
    verdict under the original option order and under the reversed order. Reports the
    **flip rate** (fraction where the two disagree) — high ⇒ the verdict depends on
    presentation order, not content.
    """
    flips = compared = 0
    examples: List[str] = []
    for iid in item_ids:
        try:
            a, b = judge_two_orderings(iid)
        except Exception:
            continue
        if a is None or b is None:
            continue
        compared += 1
        if str(a) != str(b):
            flips += 1
            if len(examples) < 10:
                examples.append(iid)
    rate = (flips / compared) if compared else None
    interp = "no data"
    if rate is not None:
        interp = ("severe position bias" if rate >= 0.3 else
                  "some position bias" if rate >= 0.1 else "robust to order")
    return {"compared": compared, "flips": flips, "flip_rate": _r(rate),
            "interpretation": interp, "flip_examples": examples}


def build_eval_card(schema: str, kappa: Optional[float], agreement_rate: Optional[float],
                    verbosity: Optional[Dict] = None, calibration: Optional[Dict] = None,
                    position: Optional[Dict] = None, prompt_version: str = "") -> Dict[str, Any]:
    """Assemble a portable **judge eval card**: agreement (κ) PLUS the robustness/bias
    axis, with an overall verdict. This is the certificate to ship with an eval."""
    concerns: List[str] = []
    if kappa is not None and kappa < 0.6:
        concerns.append(f"moderate/low agreement (κ={round(kappa,3)})")
    if verbosity and verbosity.get("length_bias_excess") is not None and abs(verbosity["length_bias_excess"]) > 20:
        concerns.append(verbosity["interpretation"])
    if calibration and calibration.get("ece") is not None and calibration["ece"] > 0.15:
        concerns.append(f"poorly calibrated (ECE={calibration['ece']})")
    if position and position.get("flip_rate") is not None and position["flip_rate"] >= 0.1:
        concerns.append(position["interpretation"])
    verdict = "trustworthy" if not concerns else ("use with caution" if len(concerns) == 1 else "needs review")
    return {"schema": schema, "prompt_version": prompt_version,
            "agreement": {"kappa": _r(kappa), "agreement_rate": _r(agreement_rate)},
            "verbosity_bias": verbosity, "calibration": calibration, "position": position,
            "concerns": concerns, "verdict": verdict}


def eval_cards_from_pairs(pairs_by_schema: Dict[str, List[tuple]],
                          per_schema_alignment: Dict[str, Dict],
                          text_len_getter: Callable[[str], int],
                          prompt_version: str = "") -> Dict[str, Dict]:
    """Build a judge eval card per schema from alignment pairs.

    ``pairs_by_schema``: {schema: [(instance_id, human_label, judge_label,
    confidence, reasoning), ...]} (the ``gather_pairs`` shape). ``per_schema_alignment``
    carries κ + agreement_rate (from ``compute_alignment_from_pairs``).
    ``text_len_getter(instance_id)`` returns the item's text length.
    """
    cards: Dict[str, Dict] = {}
    for schema, pairs in pairs_by_schema.items():
        recs, conf_recs = [], []
        for p in pairs:
            iid, human, judge = p[0], p[1], p[2]
            conf = p[3] if len(p) > 3 else None
            if human is None or judge is None:
                continue
            recs.append(BiasRecord(text_len=int(text_len_getter(iid) or 0),
                                   judge_label=str(judge), human_label=str(human)))
            if conf is not None:
                conf_recs.append((conf, str(judge) == str(human)))
        al = per_schema_alignment.get(schema, {})
        cards[schema] = build_eval_card(
            schema, kappa=al.get("kappa"), agreement_rate=al.get("agreement_rate"),
            verbosity=verbosity_bias(recs) if recs else None,
            calibration=confidence_calibration(conf_recs) if conf_recs else None,
            position=None, prompt_version=prompt_version)
    return cards


def _most_common(xs: List[str]) -> Optional[str]:
    from collections import Counter
    return Counter(xs).most_common(1)[0][0] if xs else None


def _r(x):
    return round(x, 4) if isinstance(x, (int, float)) else x

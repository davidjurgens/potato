"""
Is the judge judging, or just picking whatever came first?

Practitioners running LLM-as-judge pipelines describe the same two-step check:
swap the positions so the judge does not always pick the first option, then
hand-label a hundred items to see whether the judge is any good at all. The
second step is work only a human can do. The first is arithmetic, and no
annotation tool reports it.

The measure
-----------
Run every item twice -- once with the allowed labels in configured order, once
reversed -- and count how often the verdict changes. A judge that is reading
the item answers the same either way.

* **flip rate** -- the share of items whose verdict changed. This is the
  headline. Zero means order-invariant; anything approaching the rate you would
  get from guessing means the judge is answering a different question than you
  asked.
* **first-position rate** -- how often the verdict was whatever was listed
  first. Reported per run, because the direction of the pull is what tells you
  whether the flips are noise or a systematic preference: a judge that picks
  first 90% of the time in *both* runs is biased, one at roughly 50% in both is
  merely inconsistent, and the two need different fixes.
* **stable label rate** -- among unflipped items, whether the agreement is
  concentrated on one label. A judge that always answers "yes" is perfectly
  order-invariant and perfectly useless, and a flip rate alone cannot see that.

Cost
----
This doubles the judge calls for the items it covers, which is why it runs on
demand over a sample rather than on every judged item.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Below this many usable pairs the rates are too noisy to act on. Reported
#: anyway -- a small probe that says "5 items, 40% flips" is more useful than
#: silence -- but flagged so nobody quotes it as a finding.
MIN_PAIRS = 20


@dataclass
class ProbeResult:
    """One item judged under both label orders."""

    instance_id: str
    forward_label: Optional[str]
    reversed_label: Optional[str]
    forward_order: List[str] = field(default_factory=list)
    reversed_order: List[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Both runs produced a verdict. A failed call is not a flip."""
        return bool(self.forward_label) and bool(self.reversed_label)

    @property
    def flipped(self) -> Optional[bool]:
        if not self.usable:
            return None
        return self.forward_label != self.reversed_label

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "forward_label": self.forward_label,
            "reversed_label": self.reversed_label,
            "forward_order": list(self.forward_order),
            "reversed_order": list(self.reversed_order),
            "flipped": self.flipped,
        }


def probe_instance(judge_service, instance_id: str,
                   schema_info: Dict[str, Any], instance_text: str,
                   few_shot_examples: Optional[List[Dict[str, str]]] = None,
                   ) -> ProbeResult:
    """
    Judge one item under both label orders.

    The reversal is of the *allowed labels* list in the prompt, which is where
    a categorical judge's position bias lives. Nothing about the item itself
    changes, so any difference in the verdict is attributable to the order.
    """
    from potato.ai.judge import extract_labels

    labels = extract_labels(schema_info)
    forward = list(labels)
    backward = list(reversed(labels))

    def run(order: List[str]) -> Optional[str]:
        prediction = judge_service.judge_instance(
            instance_id, schema_info, instance_text,
            few_shot_examples=few_shot_examples, label_order=order)
        return prediction.predicted_label if prediction else None

    return ProbeResult(
        instance_id=instance_id,
        forward_label=run(forward),
        reversed_label=run(backward),
        forward_order=forward,
        reversed_order=backward,
    )


def probe_batch(judge_service, schema_info: Dict[str, Any],
                items: Sequence[Dict[str, str]],
                few_shot_examples: Optional[List[Dict[str, str]]] = None,
                on_progress: Optional[Callable[[int, int], None]] = None,
                ) -> List[ProbeResult]:
    """
    Probe a sample of items.

    Args:
        items: ``[{"instance_id": ..., "text": ...}, ...]``.
        on_progress: Called with ``(done, total)``. This makes twice as many
            model calls as a normal judging pass, so a caller driving it from
            a UI needs somewhere to say so.
    """
    results = []
    total = len(items)
    for index, item in enumerate(items, start=1):
        try:
            results.append(probe_instance(
                judge_service, str(item.get("instance_id", "")), schema_info,
                str(item.get("text", "")), few_shot_examples))
        except Exception:
            # One bad item must not lose the whole probe: the calls already
            # made are the expensive part.
            logger.exception("Position-bias probe failed for %s",
                             item.get("instance_id"))
        if on_progress:
            on_progress(index, total)
    return results


def summarize(results: Sequence[ProbeResult]) -> Dict[str, Any]:
    """
    Turn probe results into the numbers to report.

    The flip rate itself is delegated to
    :func:`potato.server_utils.judge_bias.position_swap_consistency`, which
    already defined the measure and its severity bands -- it just had no
    caller, because nothing supplied the pair of verdicts it needs. That is
    what this module is for. Recomputing the rate here would give the eval
    card and this report two definitions of the same number.

    On top of it this adds the two things a flip rate alone cannot see: which
    *direction* the pull goes (per-run first-position rate), and whether the
    judge is order-invariant only because it always answers the same label.

    ``reliable`` is False below :data:`MIN_PAIRS`; the numbers are still
    returned, because a small probe that says "5 items, 2 flips" beats an
    empty report.
    """
    from potato.server_utils.judge_bias import position_swap_consistency

    usable = [r for r in results if r.usable]
    n = len(usable)
    if not n:
        return {
            # Every key the populated return has. An empty report that omits
            # them raises a KeyError in the caller precisely when there is no
            # data -- the case a report most needs to survive.
            "n_probed": len(results), "n_usable": 0, "reliable": False,
            "flip_rate": None, "first_position_rate": None,
            "stable_label_rate": None, "stable_label": None,
            "swap": position_swap_consistency(lambda _i: (None, None), []),
            "verdict": ("No item produced a verdict under both orders, so "
                        "nothing can be said about position bias."),
        }

    by_id = {r.instance_id: (r.forward_label, r.reversed_label) for r in usable}
    swap = position_swap_consistency(lambda iid: by_id[iid], list(by_id))
    flip_rate = swap["flip_rate"] or 0.0

    def first_rate(get_label, get_order):
        picked_first = sum(1 for r in usable
                           if get_order(r) and get_label(r) == get_order(r)[0])
        return picked_first / n

    forward_first = first_rate(lambda r: r.forward_label, lambda r: r.forward_order)
    reversed_first = first_rate(lambda r: r.reversed_label, lambda r: r.reversed_order)

    agreed = [r for r in usable if not r.flipped]
    stable_counts = Counter(r.forward_label for r in agreed)
    stable_label_rate = (stable_counts.most_common(1)[0][1] / len(agreed)
                         if agreed else None)

    return {
        "n_probed": len(results),
        "n_usable": n,
        "reliable": n >= MIN_PAIRS,
        # The shape build_eval_card() reads, so the probe lights up the
        # "position" slot on the judge eval card that has always been None.
        "swap": swap,
        "flip_rate": flip_rate,
        "first_position_rate": {
            "configured_order": forward_first,
            "reversed_order": reversed_first,
        },
        "stable_label_rate": stable_label_rate,
        "stable_label": (stable_counts.most_common(1)[0][0]
                         if stable_counts else None),
        "verdict": _verdict(flip_rate, forward_first, reversed_first,
                            stable_label_rate, n),
    }


def _verdict(flip_rate: float, forward_first: float, reversed_first: float,
             stable_label_rate: Optional[float], n: int) -> str:
    """
    One sentence a researcher can put in a paper or act on.

    Deliberately does not reduce to pass/fail. The three numbers fail in
    different ways and have different fixes: a systematic first-position pull
    is fixed by randomising and recording order, inconsistency is not, and a
    judge that always answers the same label is not fixed by either.
    """
    caveat = "" if n >= MIN_PAIRS else (
        f" Based on only {n} item{'s' if n != 1 else ''}, so treat it as a "
        f"smoke test rather than a measurement.")

    both_prefer_first = forward_first >= 0.7 and reversed_first >= 0.7
    if both_prefer_first:
        return (
            f"The judge picked whichever label was listed first on "
            f"{forward_first:.0%} and {reversed_first:.0%} of items under the "
            f"two orders. That is a systematic position preference, not a "
            f"judgement of the items." + caveat)

    if flip_rate >= 0.2:
        return (
            f"{flip_rate:.0%} of verdicts changed when the label order was "
            f"reversed. The judge is not reading the item consistently; "
            f"treat its labels as noisy rather than as a reference." + caveat)

    if stable_label_rate is not None and stable_label_rate >= 0.95:
        return (
            f"Verdicts were order-invariant ({flip_rate:.0%} flips), but "
            f"{stable_label_rate:.0%} of them were the same label. A judge "
            f"that always answers the same thing is order-invariant and "
            f"uninformative; check the label distribution before trusting "
            f"the flip rate." + caveat)

    return (
        f"{flip_rate:.0%} of verdicts changed when the label order was "
        f"reversed, with no systematic first-position preference. The judge "
        f"appears order-invariant on this sample." + caveat)

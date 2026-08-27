"""
Reviewing model output: worst-first, and the items the model said nothing about.

The mature annotation pipeline practitioners describe is not "label everything
by hand" -- it is model pre-labels, then human QC. Potato had every part of
that and not the workflow: ``ai_prelabel`` writes predictions,
``active_learning_manager`` ranks by uncertainty, ``potato/curation`` slices
the data, and adjudication compares human to human. Nothing compared human to
*model*.

Two ideas from the same practitioner recipe, and the second is the one tools
get wrong:

**Sort by confidence and check the worst.** Cheap, and it finds the errors the
model already suspects. :class:`ReviewQueue` does this, and the
``model_review`` assignment strategy serves it.

**Sample the items the model predicted nothing on.** A wrong box is visible in
a review UI -- it is right there, wrong. A *missing* box is invisible: the
reviewer sees an empty image and moves on. So false negatives never surface
from confidence-ordered review at all, because an item with no prediction has
no confidence to be low. They only surface if you go looking for them, which
is what :func:`empty_prediction_ids` is for.

That asymmetry is also why recall is computable at all here. Precision comes
free from reviewing predictions; recall needs someone to have looked at the
items with none.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Verdicts a reviewer can give a prelabel. Stored distinctly from a fresh
#: annotation: "the model was right" and "a human independently chose this"
#: are different facts, and conflating them makes model precision
#: unmeasurable.
VERDICTS = ("accept", "correct", "reject")

#: Default share of the confidence-ordered queue to review. The recipe is
#: "check the worst 10-20%".
DEFAULT_WORST_FRACTION = 0.2

#: Keys a prediction payload has used for its confidence.
CONFIDENCE_KEYS = ("confidence", "score", "probability", "prob")


# ------------------------------------------------------------- reading them


@dataclass
class PredictionSummary:
    """What the model said about one item, across every prelabelled scheme."""

    instance_id: str
    n_predictions: int = 0
    #: Lowest confidence over this item's predictions, or None when the
    #: predictions carry no confidence at all.
    min_confidence: Optional[float] = None
    mean_confidence: Optional[float] = None
    schemes: List[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        """The model predicted nothing here. The false-negative pool."""
        return self.n_predictions == 0

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "n_predictions": self.n_predictions,
            "min_confidence": self.min_confidence,
            "mean_confidence": self.mean_confidence,
            "schemes": list(self.schemes),
            "empty": self.empty,
        }


def _confidences(payload: Any) -> List[float]:
    """Every confidence in one scheme's prediction payload."""
    found: List[float] = []

    def visit(node):
        if isinstance(node, dict):
            for key in CONFIDENCE_KEYS:
                value = node.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    found.append(float(value))
                    break
            for value in node.values():
                if isinstance(value, (list, dict)):
                    visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload)
    return found


def _count_predictions(payload: Any) -> int:
    """
    How many things the model asserted for one scheme.

    A list is a count of objects (boxes, spans). A bare label is one
    assertion. An empty list is a real, load-bearing answer -- "the model
    looked and found nothing" -- and is exactly what makes this item part of
    the false-negative pool, so it counts as zero rather than being skipped.
    """
    if payload is None or payload == "":
        return 0
    if isinstance(payload, str):
        # Blob schemas store their objects as a JSON string.
        stripped = payload.strip()
        if stripped.startswith(("[", "{")):
            try:
                return _count_predictions(json.loads(stripped))
            except ValueError:
                return 1
        return 1
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return len(payload) and 1 or 0
    return 1


def summarize_predictions(instance_id: str, item_data: Dict[str, Any],
                          field_name: str = "predictions",
                          schema_names: Optional[Iterable[str]] = None
                          ) -> PredictionSummary:
    """
    Read one item's prelabels into a :class:`PredictionSummary`.

    ``schema_names`` restricts the reading to schemes the project actually
    configured; without it a stray key under ``predictions`` would count as a
    prediction and quietly keep an item out of the false-negative pool.
    """
    summary = PredictionSummary(instance_id=instance_id)
    predictions = (item_data or {}).get(field_name)
    if not isinstance(predictions, dict):
        return summary

    wanted = set(schema_names) if schema_names is not None else None
    confidences: List[float] = []
    for scheme, payload in predictions.items():
        if wanted is not None and scheme not in wanted:
            continue
        count = _count_predictions(payload)
        summary.n_predictions += count
        if count:
            summary.schemes.append(str(scheme))
        confidences.extend(_confidences(payload))

    if confidences:
        summary.min_confidence = min(confidences)
        summary.mean_confidence = statistics.fmean(confidences)
    return summary


# ------------------------------------------------------------------- queues


def review_order(summaries: Sequence[PredictionSummary]) -> List[str]:
    """
    Prelabelled items, least confident first.

    Items whose predictions carry no confidence sort *after* the ones that do,
    rather than being treated as confidence 0 and jumping the queue. A model
    that does not report confidence is not a model that is unsure; assuming so
    would fill the worst-first queue with items nobody has a reason to doubt.

    Empty-prediction items are excluded entirely -- they have no confidence to
    rank and reviewing them is a different job, see
    :func:`empty_prediction_ids`.
    """
    ranked = [s for s in summaries if not s.empty]
    with_conf = [s for s in ranked if s.min_confidence is not None]
    without = [s for s in ranked if s.min_confidence is None]
    with_conf.sort(key=lambda s: (s.min_confidence, s.instance_id))
    without.sort(key=lambda s: s.instance_id)
    return [s.instance_id for s in with_conf] + [s.instance_id for s in without]


def worst_fraction(summaries: Sequence[PredictionSummary],
                   fraction: float = DEFAULT_WORST_FRACTION) -> List[str]:
    """The least-confident ``fraction`` of the queue, at least one item."""
    order = review_order(summaries)
    if not order:
        return []
    cutoff = max(1, int(round(len(order) * max(0.0, min(1.0, fraction)))))
    return order[:cutoff]


def empty_prediction_ids(summaries: Sequence[PredictionSummary]) -> List[str]:
    """
    Items the model predicted nothing on: the false-negative pool.

    Reviewing these is the only way recall is measurable. A confidence-ordered
    queue can never surface them, because an item with no prediction has no
    confidence to be low -- which is precisely why missing detections are the
    failure class that survives review.
    """
    return sorted(s.instance_id for s in summaries if s.empty)


# ----------------------------------------------------------------- verdicts


@dataclass
class ReviewVerdict:
    """One reviewer's judgement of one item's prelabels."""

    instance_id: str
    reviewer: str
    verdict: str
    schema_name: str = ""
    #: Set when the reviewer changed something, so a correction can be told
    #: apart from a rejection in the metrics.
    note: str = ""
    timestamp: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "reviewer": self.reviewer,
            "verdict": self.verdict,
            "schema_name": self.schema_name,
            "note": self.note,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewVerdict":
        return cls(
            instance_id=str(data.get("instance_id", "")),
            reviewer=str(data.get("reviewer", "")),
            verdict=str(data.get("verdict", "")),
            schema_name=str(data.get("schema_name", "")),
            note=str(data.get("note", "")),
            timestamp=data.get("timestamp"),
        )


def review_metrics(verdicts: Sequence[ReviewVerdict],
                   reviewed_empty_ids: Sequence[str] = (),
                   found_in_empty_ids: Sequence[str] = ()) -> Dict[str, Any]:
    """
    Model precision, recall and human agreement, from review verdicts.

    Args:
        verdicts: One per reviewed prelabelled item.
        reviewed_empty_ids: Items with NO prediction that a human actually
            opened. This is the recall denominator, and it has to be the
            reviewed set rather than every empty item -- an item nobody looked
            at tells you nothing about whether the model missed something in
            it.
        found_in_empty_ids: Of those, the ones where the human found something
            the model had not. Each is a confirmed false negative.

    Returns precision always, and recall only when the empty pool was
    sampled: ``recall: None`` with a stated reason beats a number computed
    from a denominator nobody checked.
    """
    latest: Dict[Tuple[str, str], ReviewVerdict] = {}
    for verdict in verdicts:
        # Last verdict per (item, scheme) wins: a reviewer who changes their
        # mind should not be counted twice.
        latest[(verdict.instance_id, verdict.schema_name)] = verdict

    counts = {name: 0 for name in VERDICTS}
    for verdict in latest.values():
        if verdict.verdict in counts:
            counts[verdict.verdict] += 1

    reviewed = sum(counts.values())
    # A corrected prelabel was partly wrong; counting it as a true positive
    # would let a model that is always nearly-right score a perfect
    # precision.
    true_positives = counts["accept"]
    precision = (true_positives / reviewed) if reviewed else None

    n_sampled = len(set(reviewed_empty_ids))
    n_missed = len(set(found_in_empty_ids) & set(reviewed_empty_ids))
    recall = None
    recall_note = ("The empty-prediction pool was not reviewed, so there is no "
                   "evidence about what the model missed and recall cannot be "
                   "computed. Sample it from the empty-prediction slice.")
    if n_sampled:
        # Estimated over the reviewed sample: of everything a human found,
        # what share had the model already found?
        denominator = true_positives + counts["correct"] + n_missed
        recall = (true_positives + counts["correct"]) / denominator if denominator else None
        recall_note = (f"Estimated over {n_sampled} sampled item(s) with no "
                       f"prediction, {n_missed} of which turned out to contain "
                       f"something.")

    return {
        "n_reviewed": reviewed,
        "counts": counts,
        "precision": precision,
        "recall": recall,
        "recall_note": recall_note,
        "n_empty_reviewed": n_sampled,
        "n_false_negatives": n_missed,
        "agreement_rate": (counts["accept"] / reviewed) if reviewed else None,
    }


# ------------------------------------------------------------- persistence


_VERDICT_MIGRATION = None


def _db(task_dir: str):
    from potato.persistence import Migration, get_db, register_migration

    global _VERDICT_MIGRATION
    if _VERDICT_MIGRATION is None:
        _VERDICT_MIGRATION = Migration(
            name="0001_model_review_verdicts",
            sql="""
            CREATE TABLE IF NOT EXISTS model_review_verdicts (
                project     TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                schema_name TEXT NOT NULL DEFAULT '',
                reviewer    TEXT NOT NULL,
                verdict     TEXT NOT NULL,
                note        TEXT NOT NULL DEFAULT '',
                updated_at  REAL NOT NULL,
                PRIMARY KEY (project, instance_id, schema_name, reviewer)
            );
            CREATE INDEX IF NOT EXISTS idx_review_project
                ON model_review_verdicts (project, updated_at DESC);
            """,
        )
    register_migration(_VERDICT_MIGRATION)
    return get_db(task_dir)


def record_verdict(config: Dict[str, Any], verdict: ReviewVerdict) -> None:
    """
    Store one review verdict, replacing this reviewer's earlier one.

    Kept in its own table rather than as an annotation. "The model was right"
    and "a human independently chose this label" are different facts, and
    storing the first as the second makes model precision unmeasurable --
    every accepted prelabel would look like human work.

    Raises:
        ValueError: On an unknown verdict. Silently storing a typo would make
            the precision denominator wrong in a way nothing surfaces.
    """
    import time

    if verdict.verdict not in VERDICTS:
        raise ValueError(
            f"Unknown verdict {verdict.verdict!r}; expected one of "
            f"{', '.join(VERDICTS)}")

    conn = _db(config.get("task_dir", "."))
    conn.execute(
        """INSERT INTO model_review_verdicts
               (project, instance_id, schema_name, reviewer, verdict, note,
                updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(project, instance_id, schema_name, reviewer)
           DO UPDATE SET verdict = excluded.verdict, note = excluded.note,
                         updated_at = excluded.updated_at""",
        (config.get("annotation_task_name", "default"), verdict.instance_id,
         verdict.schema_name, verdict.reviewer, verdict.verdict, verdict.note,
         verdict.timestamp or time.time()),
    )
    conn.commit()


def load_verdicts(config: Dict[str, Any]) -> List[ReviewVerdict]:
    """Every recorded verdict for this project, oldest first."""
    try:
        rows = _db(config.get("task_dir", ".")).execute(
            """SELECT instance_id, schema_name, reviewer, verdict, note,
                      updated_at
               FROM model_review_verdicts WHERE project = ?
               ORDER BY updated_at ASC""",
            (config.get("annotation_task_name", "default"),),
        ).fetchall()
    except Exception:
        logger.debug("Could not read model-review verdicts", exc_info=True)
        return []

    return [ReviewVerdict(
        instance_id=row["instance_id"], schema_name=row["schema_name"],
        reviewer=row["reviewer"], verdict=row["verdict"], note=row["note"],
        timestamp=row["updated_at"]) for row in rows]


def summarize_project(item_state_manager, config: Dict[str, Any]
                      ) -> Dict[str, Any]:
    """
    The whole review picture: queue, false-negative pool, and the metrics.

    One entry point so the admin page and the API cannot disagree about what
    counts as reviewed.
    """
    qc = config.get("pre_annotation", {}) or {}
    field_name = qc.get("field", "predictions")
    schema_names = [s.get("name") for s in
                    (config.get("annotation_schemes") or []) if s.get("name")]

    summaries = []
    for instance_id, item in item_state_manager.iter_items():
        data = item.get_data() if hasattr(item, "get_data") else {}
        summaries.append(summarize_predictions(instance_id, data, field_name,
                                               schema_names))

    verdicts = load_verdicts(config)
    empty_ids = empty_prediction_ids(summaries)
    reviewed_ids = {v.instance_id for v in verdicts}
    reviewed_empty = sorted(reviewed_ids & set(empty_ids))
    # A verdict on an item with NO prediction can only mean the reviewer found
    # something the model had not: there was no prelabel to accept.
    found_in_empty = sorted(v.instance_id for v in verdicts
                            if v.instance_id in set(empty_ids)
                            and v.verdict in ("correct", "reject"))

    prelabelled = [v for v in verdicts if v.instance_id not in set(empty_ids)]
    metrics = review_metrics(prelabelled, reviewed_empty, found_in_empty)

    return {
        "n_items": len(summaries),
        "n_prelabelled": sum(1 for s in summaries if not s.empty),
        "queue": review_order(summaries),
        "worst_first": worst_fraction(summaries),
        "empty_prediction_ids": empty_ids,
        "n_empty": len(empty_ids),
        "metrics": metrics,
    }

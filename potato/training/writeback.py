"""Getting a run's predictions in front of annotators.

A prediction becomes a *prelabel*: it lands in the item's data under the
``predictions`` field, and the existing ``pre_annotation`` machinery renders it
as a pre-filled answer, ``model_review`` queues it least-confident-first, and
a reviewer records accept, correct or reject.

Four rules, applied in order, and every skip is counted rather than dropped
quietly.

**The leak guard.** An item the model was fitted on is never prelabelled. A
model is confident and right about its own training data for reasons that say
nothing about new data, and if an annotator accepts that prediction the error
is laundered into the next round's training set.

**The confidence floor.** Below it, a prelabel is noise that costs an
annotator attention.

**The schema gate, empty by default.** Turning on training must not silently
change what annotators see. Prelabels anchor people -- they accept more than
they should -- so switching them on is a decision an administrator makes per
schema, once the held-out score justifies it.

**Human annotations are unreachable from here.** Predictions go into item
*data*; human labels live in ``UserState`` and on the ``Item``'s own ``labels``
/ ``span_annotations`` / ``metadata`` attributes. This module addresses none of
those, and uses a single narrow setter rather than ``update_item()``, which
replaces an item's whole payload.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from potato.training import store

logger = logging.getLogger(__name__)

__all__ = ["WritebackReport", "ingest_predictions", "rehydrate_predictions",
           "clear_published", "withdraw_rejected", "PREDICTION_FIELD"]

#: The item-data key prelabels live under. Matches what the importers write
#: and what `quality_control.extract_pre_annotations` reads.
PREDICTION_FIELD = "predictions"


@dataclass
class WritebackReport:
    """What happened, in enough detail to explain an empty result.

    The failure this guards against is a write-back that silently does
    nothing: every count here has a corresponding reason an administrator can
    act on.
    """

    run_id: str = ""
    n_read: int = 0
    n_written: int = 0
    n_skipped_train_split: int = 0
    n_skipped_low_confidence: int = 0
    n_skipped_schema_not_enabled: int = 0
    n_skipped_rejected: int = 0
    n_skipped_missing_item: int = 0
    n_skipped_empty: int = 0
    schemas_enabled: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id, "n_read": self.n_read,
            "n_written": self.n_written,
            "n_skipped_train_split": self.n_skipped_train_split,
            "n_skipped_low_confidence": self.n_skipped_low_confidence,
            "n_skipped_schema_not_enabled": self.n_skipped_schema_not_enabled,
            "n_skipped_rejected": self.n_skipped_rejected,
            "n_skipped_missing_item": self.n_skipped_missing_item,
            "n_skipped_empty": self.n_skipped_empty,
            "schemas_enabled": list(self.schemas_enabled),
            "warnings": list(self.warnings),
            # The sentence the docs' troubleshooting quotes; the status
            # endpoint had only the counts.
            "summary": self.summary,
        }

    @property
    def summary(self) -> str:
        if not self.schemas_enabled:
            return ("No predictions were published: write-back is not enabled "
                    "for any schema. Set model_training.writeback.schemas.")
        if self.n_written:
            return "Published %d prediction(s) as prelabels." % self.n_written
        return ("Read %d prediction(s) and published none. See the skip "
                "counts." % self.n_read)


def _is_empty(payload: Any) -> bool:
    if payload is None or payload == "" or payload == [] or payload == {}:
        return True
    if isinstance(payload, dict) and set(payload) <= {"segments", "objects"}:
        return not any(payload.values())
    return False


def _writeback_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return ((config.get("model_training", {}) or {}).get("writeback", {}) or {})


def _rejected_keys(config: Dict[str, Any]) -> set:
    """``(instance_id, schema)`` pairs a reviewer has already rejected.

    Re-showing a prelabel a human threw out wastes the review that threw it
    out, and makes the tool look like it is not listening.
    """
    try:
        from potato import model_review
        return {(v.instance_id, v.schema_name)
                for v in model_review.load_verdicts(config)
                if v.verdict == "reject"}
    except Exception:
        logger.debug("Could not read review verdicts", exc_info=True)
        return set()


def ingest_predictions(run, predictions_path: str,
                       config: Dict[str, Any],
                       item_manager=None) -> WritebackReport:
    """Store a run's predictions and publish the permitted ones.

    Storage and publication are separate on purpose. Every prediction is
    recorded in ``training_predictions`` regardless of the gates, so a run's
    output can be inspected, scored and retracted; only the ones that pass all
    four rules are put in front of annotators.
    """
    report = WritebackReport(run_id=getattr(run, "run_id", ""))

    if not os.path.isfile(predictions_path):
        report.warnings.append("No predictions file at %s" % predictions_path)
        return report

    settings = _writeback_config(config)
    enabled_schemas = set(settings.get("schemas") or [])
    report.schemas_enabled = sorted(enabled_schemas)
    min_confidence = float(settings.get("min_confidence", 0.0) or 0.0)
    field_name = settings.get("field", PREDICTION_FIELD)

    own_train_ids = store.training_split_ids(config, report.run_id)
    # Any run's training items, not only this run's: an item a later run
    # fitted on has a human label, and an older prelabel on it is stale.
    train_ids = own_train_ids | store.all_training_split_ids(config)
    rejected = _rejected_keys(config)

    to_store: List[tuple] = []
    to_publish: List[tuple] = []

    with open(predictions_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                report.warnings.append("Skipped an unparseable prediction line")
                continue

            report.n_read += 1
            instance_id = str(record.get("instance_id", ""))
            schema_name = str(record.get("schema_name", ""))
            payload = record.get("payload")
            confidence = record.get("confidence")

            if not instance_id or not schema_name:
                continue

            to_store.append((instance_id, schema_name, payload, confidence))

            if instance_id in train_ids:
                report.n_skipped_train_split += 1
                continue
            if schema_name not in enabled_schemas:
                report.n_skipped_schema_not_enabled += 1
                continue
            if (instance_id, schema_name) in rejected:
                report.n_skipped_rejected += 1
                continue
            if confidence is not None and float(confidence) < min_confidence:
                report.n_skipped_low_confidence += 1
                continue
            if _is_empty(payload):
                # No spans, no shapes, no segments: nothing to show, and
                # counting it as written overstated what annotators see.
                report.n_skipped_empty += 1
                continue

            to_publish.append((instance_id, schema_name, payload))

    # Persist first. This is the durable record, and it is what survives a
    # restart -- predictions written into item data alone do not.
    if to_store:
        try:
            store.record_predictions(config, report.run_id, to_store)
        except Exception:
            logger.exception("Could not record predictions for run %s",
                             report.run_id)
            report.warnings.append("Predictions could not be persisted")

    if item_manager is None and (to_publish or own_train_ids):
        from potato.item_state_management import get_item_state_manager
        item_manager = get_item_state_manager()

    # Take down prelabels an earlier run left on the items this run trained
    # on. They would otherwise stay on screen, and come back after a restart.
    if item_manager is not None:
        for instance_id in own_train_ids:
            for schema_name in enabled_schemas:
                item_manager.clear_prediction(instance_id, schema_name,
                                              field=field_name)

    if not to_publish:
        return report

    from potato.labeling_engine.integration.mirror import mirror
    for instance_id, schema_name, payload in to_publish:
        if item_manager.set_prediction(instance_id, schema_name, payload,
                                       field=field_name):
            report.n_written += 1
        else:
            report.n_skipped_missing_item += 1
        label = payload.get("label") if isinstance(payload, dict) else payload
        conf = payload.get("confidence") if isinstance(payload, dict) else None
        mirror("model_training", report.run_id, report.run_id, instance_id, schema_name,
               label, conf)

    logger.info("Write-back for run %s: %s", report.run_id, report.summary)
    return report


def rehydrate_predictions(config: Dict[str, Any], item_manager) -> int:
    """Replay stored predictions into item data at startup.

    Without this the loop resets on every restart. Predictions in item data
    come from the input file at load time and nothing re-persists them, so a
    prelabel written at runtime lives only in memory -- the review queue would
    empty itself every time the server bounced.

    Returns the number of predictions restored.
    """
    settings = _writeback_config(config)
    enabled = set(settings.get("schemas") or [])
    if not enabled:
        return 0

    field_name = settings.get("field", PREDICTION_FIELD)
    min_confidence = float(settings.get("min_confidence", 0.0) or 0.0)
    rejected = _rejected_keys(config)
    restored = 0

    try:
        stored = store.load_predictions(config)
    except Exception:
        logger.debug("Could not read stored predictions", exc_info=True)
        return 0

    # The same rules ingest_predictions applies. Every prediction is stored,
    # its run's training items included, so replaying them all brought back
    # at boot the prelabels the leak guard, the confidence floor and reviewer
    # rejections had kept off. The leak guard covers every run's training
    # items, so an older run's prelabel on an item a newer run fitted on
    # stays off too.
    train_ids = store.all_training_split_ids(config)
    for record in stored:
        if record["schema_name"] not in enabled:
            continue
        if record["instance_id"] in train_ids:
            continue
        if (record["instance_id"], record["schema_name"]) in rejected:
            continue
        if _is_empty(record.get("payload")):
            continue
        confidence = record.get("confidence")
        if confidence is not None and float(confidence) < min_confidence:
            continue
        if item_manager.set_prediction(record["instance_id"],
                                       record["schema_name"],
                                       record["payload"], field=field_name):
            restored += 1

    if restored:
        logger.info("Restored %d model prediction(s) from previous runs",
                    restored)
    return restored


def withdraw_rejected(config: Dict[str, Any], instance_id: str,
                      schema_name: str, item_manager=None) -> bool:
    """Take down a training prelabel the moment a reviewer rejects it.

    The rejected-pairs rule applied only when predictions were published, at
    the next run or restart, so a rejected prelabel stayed on the page until
    then. A prelabel training did not write (one imported with the data) is
    left alone.
    """
    if not (config.get("model_training") or {}).get("enabled"):
        return False
    if not store.has_prediction(config, instance_id, schema_name):
        return False
    return bool(clear_published(config, [{"instance_id": instance_id,
                                          "schema_name": schema_name}],
                                item_manager))


def clear_published(config: Dict[str, Any], records, item_manager=None) -> int:
    """Take retracted predictions out of item data. Returns how many."""
    field_name = _writeback_config(config).get("field", PREDICTION_FIELD)
    if item_manager is None:
        try:
            from potato.item_state_management import get_item_state_manager
            item_manager = get_item_state_manager()
        except Exception:
            return 0
    cleared = 0
    for record in records:
        if item_manager.clear_prediction(record["instance_id"],
                                         record["schema_name"],
                                         field=field_name):
            cleared += 1
    return cleared

"""Truth Serum state: prediction storage, surprisingly-popular verdicts, scores.

Persistence: ``{output_annotation_dir}/truth_serum/predictions.jsonl`` —
append-only; the latest record per (username, instance_id) wins, so annotators
can revise their label/prediction freely.

Math (simplified own-answer-prediction variant of Prelec et al. 2017):

- For an item with n >= min_annotators predictions, each label L that received
  votes has an *actual* popularity ``count(L) / n`` and a *predicted*
  popularity: the mean prediction of the annotators who chose L (each
  predicted what share of others would agree with them).
- ``surprise(L) = actual_pct(L) - predicted_pct(L)``. The surprisingly-popular
  label is the argmax of surprise. When it differs from the majority label,
  the item lands in the "crowd is likely wrong" review queue.
- Annotator calibration error: mean |prediction - actual agreement among the
  *other* annotators| over items with a verdict.
- Annotator SP-alignment: share of an annotator's labels that match the SP
  verdict, over items with a verdict.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from potato.truth_serum.config import TruthSerumConfig, parse_truth_serum_config

logger = logging.getLogger(__name__)


class TruthSerumManager:
    """Singleton owning prediction storage and surprisingly-popular scoring."""

    def __init__(self, app_config: Dict[str, Any]) -> None:
        self.app_config = app_config
        self.ts_config: TruthSerumConfig = parse_truth_serum_config(app_config)

        output_dir = app_config.get("output_annotation_dir", "annotation_output")
        self.storage_dir = os.path.join(output_dir, "truth_serum")
        self._lock = threading.Lock()

        # (username, instance_id) -> prediction record (latest wins)
        self._predictions: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------ io --
    def _path(self) -> str:
        return os.path.join(self.storage_dir, "predictions.jsonl")

    def _load(self) -> None:
        path = self._path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        key = (record["username"], str(record["instance_id"]))
                        self._predictions[key] = record
                    except (json.JSONDecodeError, KeyError, TypeError):
                        logger.warning("Skipping malformed line in %s", path)
        except OSError:
            logger.exception("Failed reading %s", path)

    # ------------------------------------------------------------ recording --
    def record_prediction(self, username: str, instance_id: str, label: str,
                          predicted_pct: float) -> Dict[str, Any]:
        """Record (or revise) an annotator's label + popularity prediction."""
        predicted_pct = float(predicted_pct)
        if not 0 <= predicted_pct <= 100:
            raise ValueError("predicted_pct must be between 0 and 100")
        record = {
            "username": username,
            "instance_id": str(instance_id),
            "schema": self.ts_config.schema,
            "label": label,
            "predicted_pct": predicted_pct,
            "timestamp": time.time(),
        }
        with self._lock:
            self._predictions[(username, str(instance_id))] = record
            os.makedirs(self.storage_dir, exist_ok=True)
            with open(self._path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def get_prediction(self, username: str, instance_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._predictions.get((username, str(instance_id)))

    # -------------------------------------------------------------- scoring --
    def _by_instance(self) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        with self._lock:
            for record in self._predictions.values():
                grouped.setdefault(record["instance_id"], []).append(record)
        return grouped

    def compute_item_results(self) -> List[Dict[str, Any]]:
        """Per-item verdicts for every instance meeting ``min_annotators``."""
        results = []
        for instance_id, records in sorted(self._by_instance().items()):
            n = len(records)
            if n < self.ts_config.min_annotators:
                continue
            votes: Dict[str, int] = {}
            predictions_by_label: Dict[str, List[float]] = {}
            for r in records:
                votes[r["label"]] = votes.get(r["label"], 0) + 1
                predictions_by_label.setdefault(r["label"], []).append(r["predicted_pct"])

            labels = []
            for label, count in votes.items():
                actual_pct = 100.0 * count / n
                predicted_pct = sum(predictions_by_label[label]) / len(predictions_by_label[label])
                labels.append({
                    "label": label,
                    "votes": count,
                    "actual_pct": round(actual_pct, 1),
                    "predicted_pct": round(predicted_pct, 1),
                    "surprise": round(actual_pct - predicted_pct, 1),
                })
            labels.sort(key=lambda x: -x["votes"])

            top_votes = labels[0]["votes"]
            majority_tied = sum(1 for l in labels if l["votes"] == top_votes) > 1
            majority_label = labels[0]["label"]
            sp_entry = max(labels, key=lambda x: x["surprise"])
            results.append({
                "instance_id": instance_id,
                "n": n,
                "labels": labels,
                "majority_label": majority_label,
                "majority_tied": majority_tied,
                "sp_label": sp_entry["label"],
                "sp_surprise": sp_entry["surprise"],
                "disagrees": sp_entry["label"] != majority_label,
            })
        return results

    def compute_annotator_scores(self) -> Dict[str, Dict[str, Any]]:
        """Calibration error and SP-alignment per annotator."""
        grouped = self._by_instance()
        verdicts = {r["instance_id"]: r for r in self.compute_item_results()}

        scores: Dict[str, Dict[str, Any]] = {}
        for instance_id, records in grouped.items():
            n = len(records)
            votes: Dict[str, int] = {}
            for r in records:
                votes[r["label"]] = votes.get(r["label"], 0) + 1
            verdict = verdicts.get(instance_id)
            for r in records:
                entry = scores.setdefault(r["username"], {
                    "predictions": 0,
                    "_calibration_errors": [],
                    "_sp_matches": 0,
                    "_sp_total": 0,
                })
                entry["predictions"] += 1
                if verdict is None or n < 2:
                    continue
                # Agreement among the *other* annotators with this label
                actual_others = 100.0 * (votes[r["label"]] - 1) / (n - 1)
                entry["_calibration_errors"].append(abs(r["predicted_pct"] - actual_others))
                entry["_sp_total"] += 1
                if r["label"] == verdict["sp_label"]:
                    entry["_sp_matches"] += 1

        for entry in scores.values():
            errors = entry.pop("_calibration_errors")
            matches = entry.pop("_sp_matches")
            total = entry.pop("_sp_total")
            entry["calibration_error"] = (
                round(sum(errors) / len(errors), 1) if errors else None
            )
            entry["sp_alignment"] = round(matches / total, 3) if total else None
            entry["scored_items"] = total
        return scores

    # ---------------------------------------------------------------- stats --
    def get_stats(self) -> Dict[str, Any]:
        items = self.compute_item_results()
        annotators = self.compute_annotator_scores()
        with self._lock:
            total_predictions = len(self._predictions)
        disagreements = [i for i in items if i["disagrees"]]
        return {
            "enabled": self.ts_config.enabled,
            "schema": self.ts_config.schema,
            "question": self.ts_config.question,
            "min_annotators": self.ts_config.min_annotators,
            "totals": {
                "predictions": total_predictions,
                "items_with_verdicts": len(items),
                "sp_disagrees_majority": len(disagreements),
                "annotators": len(annotators),
            },
            "items": items,
            "disagreements": disagreements,
            "annotators": annotators,
        }

    # --------------------------------------------------------------- export --
    def export_records(self) -> Dict[str, Any]:
        """Full export: item verdicts + raw predictions."""
        with self._lock:
            raw = sorted(self._predictions.values(),
                         key=lambda r: (r["instance_id"], r["username"]))
        return {
            "schema": self.ts_config.schema,
            "min_annotators": self.ts_config.min_annotators,
            "items": self.compute_item_results(),
            "predictions": raw,
        }


# ----------------------------------------------------------------- singleton --
_manager: Optional[TruthSerumManager] = None


def init_truth_serum_manager(app_config: Dict[str, Any]) -> Optional[TruthSerumManager]:
    """Initialize the singleton when ``truth_serum.enabled`` is on."""
    global _manager
    if not (app_config.get("truth_serum") or {}).get("enabled", False):
        _manager = None
        return None
    _manager = TruthSerumManager(app_config)
    logger.info("Truth Serum enabled (schema=%s, min_annotators=%d)",
                _manager.ts_config.schema, _manager.ts_config.min_annotators)
    return _manager


def get_truth_serum_manager() -> Optional[TruthSerumManager]:
    return _manager


def clear_truth_serum_manager() -> None:
    global _manager
    _manager = None

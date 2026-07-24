"""Boundary Lab state: probe cache, verdict recording, stats, contrast-set export.

Persistence layout (under ``{output_annotation_dir}/boundary/``):

- ``probes.jsonl``    — every generated probe (shared across annotators so
  invariance consistency is comparable between annotators)
- ``responses.jsonl`` — one line per annotator verdict (append-only)

Verdicts: ``holds`` (label survives the edit), ``flips`` (label changes;
carries ``new_label`` and optional ``rationale``), ``unsure``.

Every answered flip/holds probe is a labeled contrast pair:
``holds`` ⇒ counterfactual shares the original label;
``flips`` ⇒ counterfactual carries the annotator's ``new_label``.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from potato.boundary.config import BoundaryConfig, parse_boundary_config
from potato.boundary.generator import KIND_FLIP, KIND_INVARIANCE, Probe, ProbeGenerator

logger = logging.getLogger(__name__)

VALID_VERDICTS = ("holds", "flips", "unsure")


class BoundaryManager:
    """Singleton owning probe generation, verdict storage, and aggregation."""

    def __init__(self, app_config: Dict[str, Any]) -> None:
        self.app_config = app_config
        self.boundary_config: BoundaryConfig = parse_boundary_config(app_config)
        self.generator = ProbeGenerator(app_config, self.boundary_config)

        output_dir = app_config.get("output_annotation_dir", "annotation_output")
        self.storage_dir = os.path.join(output_dir, "boundary")
        self._lock = threading.Lock()

        # (instance_id, schema, label) -> list of probe dicts
        self._probes: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        # (username, probe_id) -> response dict (latest wins)
        self._responses: Dict[Tuple[str, str], Dict[str, Any]] = {}

        self._load()

    # ------------------------------------------------------------------ io --
    def _probes_path(self) -> str:
        return os.path.join(self.storage_dir, "probes.jsonl")

    def _responses_path(self) -> str:
        return os.path.join(self.storage_dir, "responses.jsonl")

    def _load(self) -> None:
        for path, handler in ((self._probes_path(), self._index_probe),
                              (self._responses_path(), self._index_response)):
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            handler(json.loads(line))
                        except (json.JSONDecodeError, KeyError, TypeError):
                            logger.warning("Skipping malformed line in %s", path)
            except OSError:
                logger.exception("Failed reading %s", path)

    def _append(self, path: str, record: Dict[str, Any]) -> None:
        os.makedirs(self.storage_dir, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _index_probe(self, record: Dict[str, Any]) -> None:
        key = (str(record["instance_id"]), record["schema"], record["original_label"])
        bucket = self._probes.setdefault(key, [])
        if not any(p["probe_id"] == record["probe_id"] for p in bucket):
            bucket.append(record)

    def _index_response(self, record: Dict[str, Any]) -> None:
        self._responses[(record["username"], record["probe_id"])] = record

    # -------------------------------------------------------------- probes --
    def get_or_generate_probes(self, instance_id: str, schema: str, label: str,
                               labels: List[str], text: str,
                               item_data: Optional[Dict[str, Any]] = None
                               ) -> List[Dict[str, Any]]:
        """Return cached probes for (instance, schema, label), generating on miss.

        Probes are shared across annotators by design.
        """
        key = (str(instance_id), schema, label)
        with self._lock:
            cached = self._probes.get(key)
        if cached:
            return cached

        probes: List[Probe] = self.generator.generate(
            str(instance_id), schema, label, labels, text, item_data=item_data
        )
        records = [p.to_dict() for p in probes]
        with self._lock:
            # Re-check under the lock; another request may have generated first.
            cached = self._probes.get(key)
            if cached:
                return cached
            self._probes[key] = records
            for record in records:
                self._append(self._probes_path(), record)
        return records

    def _find_probe(self, probe_id: str) -> Optional[Dict[str, Any]]:
        for bucket in self._probes.values():
            for probe in bucket:
                if probe["probe_id"] == probe_id:
                    return probe
        return None

    # ----------------------------------------------------------- responses --
    def record_response(self, username: str, probe_id: str, verdict: str,
                        new_label: Optional[str] = None,
                        rationale: Optional[str] = None) -> Dict[str, Any]:
        """Record (or overwrite) an annotator's verdict on a probe."""
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"Invalid verdict '{verdict}'; expected one of {VALID_VERDICTS}")
        probe = self._find_probe(probe_id)
        if probe is None:
            raise KeyError(f"Unknown probe_id '{probe_id}'")
        record = {
            "username": username,
            "probe_id": probe_id,
            "instance_id": probe["instance_id"],
            "schema": probe["schema"],
            "kind": probe["kind"],
            "original_label": probe["original_label"],
            "verdict": verdict,
            "new_label": new_label if verdict == "flips" else None,
            "rationale": (rationale or "").strip() or None,
            "timestamp": time.time(),
        }
        with self._lock:
            self._responses[(username, probe_id)] = record
            self._append(self._responses_path(), record)
        return record

    def get_user_responses(self, username: str, instance_id: str, schema: str,
                           label: str) -> Dict[str, Dict[str, Any]]:
        """probe_id -> response for one annotator on one (instance, label)."""
        key = (str(instance_id), schema, label)
        with self._lock:
            probe_ids = {p["probe_id"] for p in self._probes.get(key, [])}
            return {
                pid: resp
                for (user, pid), resp in self._responses.items()
                if user == username and pid in probe_ids
            }

    # ---------------------------------------------------------------- stats --
    def get_stats(self) -> Dict[str, Any]:
        """Aggregates for the Boundary Lab dashboard."""
        with self._lock:
            responses = list(self._responses.values())
            probe_by_id = {
                p["probe_id"]: p for bucket in self._probes.values() for p in bucket
            }

        answered = [r for r in responses if r["verdict"] in ("holds", "flips")]
        flips = [r for r in responses if r["verdict"] == "flips"]
        unsure = [r for r in responses if r["verdict"] == "unsure"]

        # Per-label boundary sensitivity: of the minimal edits intended to
        # flip this label, how many actually did?
        per_label: Dict[str, Dict[str, int]] = {}
        for r in answered:
            if r["kind"] != KIND_FLIP:
                continue
            entry = per_label.setdefault(r["original_label"], {"flips": 0, "holds": 0})
            entry["flips" if r["verdict"] == "flips" else "holds"] += 1
        label_sensitivity = {
            label: {
                **counts,
                "flip_rate": counts["flips"] / max(counts["flips"] + counts["holds"], 1),
            }
            for label, counts in per_label.items()
        }

        # Per-annotator invariance consistency: paraphrases should never flip.
        per_annotator: Dict[str, Dict[str, Any]] = {}
        for r in responses:
            entry = per_annotator.setdefault(r["username"], {
                "answered": 0, "flips": 0,
                "invariance_holds": 0, "invariance_flips": 0,
            })
            entry["answered"] += 1
            if r["verdict"] == "flips":
                entry["flips"] += 1
            if r["kind"] == KIND_INVARIANCE and r["verdict"] in ("holds", "flips"):
                entry["invariance_holds" if r["verdict"] == "holds" else "invariance_flips"] += 1
        for entry in per_annotator.values():
            total_inv = entry["invariance_holds"] + entry["invariance_flips"]
            entry["invariance_consistency"] = (
                entry["invariance_holds"] / total_inv if total_inv else None
            )

        # Recent flips with rationales, joined to probe text for the gallery.
        gallery = []
        for r in sorted(flips, key=lambda x: x.get("timestamp", 0), reverse=True)[:40]:
            probe = probe_by_id.get(r["probe_id"])
            if not probe:
                continue
            gallery.append({
                "instance_id": r["instance_id"],
                "original_text": probe["original_text"],
                "counterfactual_text": probe["text"],
                "original_label": r["original_label"],
                "new_label": r["new_label"],
                "rationale": r["rationale"],
                "edit_hint": probe.get("edit_hint", ""),
                "annotator": r["username"],
                "source": probe.get("source", ""),
            })

        return {
            "enabled": self.boundary_config.enabled,
            "schema": self.boundary_config.schema,
            "totals": {
                "instances_probed": len({r["instance_id"] for r in responses}),
                "probes_generated": len(probe_by_id),
                "probes_answered": len(answered) + len(unsure),
                "contrast_pairs": len(answered),
                "flips": len(flips),
                "holds": len(answered) - len(flips),
                "unsure": len(unsure),
                "rationales": sum(1 for r in flips if r["rationale"]),
                "annotators": len(per_annotator),
            },
            "label_sensitivity": label_sensitivity,
            "annotators": per_annotator,
            "gallery": gallery,
        }

    # --------------------------------------------------------------- export --
    def export_contrast_set(self) -> List[Dict[str, Any]]:
        """Contrast-set JSONL records: every answered probe becomes a labeled
        (original, counterfactual) pair. ``unsure`` verdicts are excluded."""
        with self._lock:
            responses = list(self._responses.values())
            probe_by_id = {
                p["probe_id"]: p for bucket in self._probes.values() for p in bucket
            }
        records = []
        for r in sorted(responses, key=lambda x: x.get("timestamp", 0)):
            if r["verdict"] not in ("holds", "flips"):
                continue
            probe = probe_by_id.get(r["probe_id"])
            if not probe:
                continue
            records.append({
                "instance_id": r["instance_id"],
                "schema": r["schema"],
                "original_text": probe["original_text"],
                "original_label": r["original_label"],
                "counterfactual_text": probe["text"],
                "counterfactual_label": (
                    r["new_label"] if r["verdict"] == "flips" else r["original_label"]
                ),
                "kind": r["kind"],
                "flipped": r["verdict"] == "flips",
                "rationale": r["rationale"],
                "edit_hint": probe.get("edit_hint", ""),
                "probe_source": probe.get("source", ""),
                "annotator": r["username"],
                "timestamp": r["timestamp"],
            })
        return records


# ----------------------------------------------------------------- singleton --
_manager: Optional[BoundaryManager] = None


def init_boundary_manager(app_config: Dict[str, Any]) -> Optional[BoundaryManager]:
    """Initialize the singleton when ``boundary_probing.enabled`` is on."""
    global _manager
    if not (app_config.get("boundary_probing") or {}).get("enabled", False):
        _manager = None
        return None
    _manager = BoundaryManager(app_config)
    logger.info(
        "Boundary Lab enabled (schema=%s, sources=%s)",
        _manager.boundary_config.schema,
        _manager.boundary_config.sources,
    )
    return _manager


def get_boundary_manager() -> Optional[BoundaryManager]:
    return _manager


def clear_boundary_manager() -> None:
    global _manager
    _manager = None

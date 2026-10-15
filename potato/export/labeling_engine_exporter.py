"""
The labeling engine's deliverable: every item's label, where it came from,
and the certificate that says what holds.

The per-annotator exporters (csv, jsonl, parquet) read people's user states,
so a study whose labels are mostly accepted machine labels would ship only
the minority people labeled. This exporter reads the engine's resolved
labels instead, one row per item and scheme:

- ``label`` and ``label_origin`` (auto, human, adjudicated);
- ``status`` (accepted, accepted_uncertified for threshold_legacy, pending,
  pending_recert); an item with no label yet has a ``pending`` row too;
- for machine labels: the source, model and source version, the confidence,
  and the contract version it was accepted under;
- for human labels: the requests they answered.

Files written: ``labels.jsonl``, ``labels.csv``, ``certificate.json``,
``certificate.md``, ``certificate.html``, ``README.md`` (a Hugging Face
dataset card) and ``model_calls.jsonl`` (the audit log, hashes only).
"""

from __future__ import annotations

import csv
import json
import os
from typing import List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult


class LabelingEngineExporter(BaseExporter):
    format_name = "labeling_engine"
    description = ("Labeling engine output: every item's label with its provenance, "
                   "plus the quality certificate and the model-call log")
    file_extensions = [".jsonl", ".csv", ".json", ".md", ".html"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not (context.config.get("labeling_engine") or {}).get("enabled"):
            return False, "labeling_engine is not enabled in this config"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.labeling_engine.certificate import (
            build_certificate, dataset_card, render_html, render_markdown)
        from potato.labeling_engine.service import Engine
        ok, why = self.can_export(context)
        if not ok:
            return ExportResult(success=False, format_name=self.format_name, errors=[why])
        os.makedirs(output_path, exist_ok=True)
        engine = Engine(context.config)
        written: List[str] = []
        rows = []
        all_ids = engine.store.all_item_ids()
        for scheme in engine.schemes():
            # Labels accepted under threshold_legacy carry no guarantee; say so
            # on each row, as the certificate does.
            legacy = {cv.id for c in engine.cfg.contracts
                      if c.kind == "threshold_legacy" and c.schema == scheme.name
                      for cv in engine.store.contract_versions(
                          c.id, engine.cascade_hash(scheme))}
            versions = {}
            for sid, vid in zip(engine.tiers(scheme), engine.tier_versions(scheme)):
                versions[vid] = (sid, engine.store.get_source_version(vid))
            preds = {vid: engine.store.current_predictions(scheme.name, vid)
                     for vid in versions}
            seen = set()
            for lab in engine.store.resolved(schema=scheme.name):
                seen.add(lab.item_id)
                sid, sv = versions.get(lab.source_version_id, (None, None))
                p = preds.get(lab.source_version_id, {}).get(lab.item_id)
                status = lab.status
                if status == "accepted" and lab.contract_version_id in legacy:
                    status = "accepted_uncertified"
                if lab.origin == "auto" and status.startswith("accepted") \
                        and lab.source_version_id not in versions:
                    # The config changed since this was accepted (a new
                    # prompt, model or source): until the next pass
                    # re-certifies, it is not accepted under this cascade.
                    status = "pending_recert"
                rows.append({
                    "id": lab.item_id, "schema": lab.schema, "label": lab.value,
                    "label_origin": lab.origin, "status": status,
                    "source": sid, "model": sv.model if sv else None,
                    "source_version": lab.source_version_id,
                    "confidence": p.raw_conf if p is not None and lab.origin == "auto" else None,
                    "contract_version": lab.contract_version_id,
                    "request_ids": lab.request_ids,
                })
            # Every item appears once per scheme, labeled or not, so the file
            # accounts for the whole corpus.
            for iid in all_ids:
                if iid not in seen:
                    rows.append({"id": iid, "schema": scheme.name, "label": None,
                                 "label_origin": None, "status": "pending", "source": None,
                                 "model": None, "source_version": None, "confidence": None,
                                 "contract_version": None, "request_ids": []})
        path = os.path.join(output_path, "labels.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
        written.append(path)
        path = os.path.join(output_path, "labels.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            cols = ["id", "schema", "label", "label_origin", "status", "source", "model",
                    "source_version", "confidence", "contract_version", "request_ids"]
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                            for k, v in r.items()})
        written.append(path)

        cert = build_certificate(engine)
        for name, text in (("certificate.json", json.dumps(cert, indent=2, default=str)),
                           ("certificate.md", render_markdown(cert)),
                           ("certificate.html", render_html(cert)),
                           ("README.md", dataset_card(cert))):
            path = os.path.join(output_path, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            written.append(path)

        path = os.path.join(output_path, "model_calls.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            offset = 0
            while True:
                batch = engine.store.calls(limit=5000, offset=offset)
                if not batch:
                    break
                for c in batch:
                    f.write(json.dumps(c.__dict__, default=str) + "\n")
                offset += len(batch)
        written.append(path)
        by_origin = {}
        for r in rows:
            key = r["label_origin"] or "pending"
            by_origin[key] = by_origin.get(key, 0) + 1
        return ExportResult(success=True, format_name=self.format_name,
                            files_written=written,
                            stats={"labels": len(rows), "by_origin": by_origin,
                                   "certificate_id": cert.get("certificate_id")})

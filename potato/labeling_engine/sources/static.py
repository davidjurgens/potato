"""
Labels that already exist: imported pre-annotations, a model run elsewhere,
or the outputs of an older Potato subsystem mirrored into the engine.

Options:
  field             item field holding predictions: {scheme: label} or
                    {scheme: {"label": ..., "confidence": ...}}. When the
                    source labels one scheme, a bare label (or
                    {"label", "confidence"}) is accepted too.
  predictions_file  JSON Lines of {"id", "schema", "label", "confidence"},
                    relative to task_dir
  default_confidence  used when a prediction carries none (0.5)

A static source makes no model calls; each prediction is logged as one
zero-cost call so the call log still says where every label came from. Its
version hashes the file's content, so replacing the file is a new labeler.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

from ..model.records import Prediction
from ..schemes import SchemeSpec, normalize_label
from .base import Source, SourceError


class StaticSource(Source):
    kind = "static"
    CODE_VERSION = "1"

    def _opt(self, key, default=None):
        return (self.cfg.options or {}).get(key, self.cfg.raw.get(key, default))

    def _file_path(self) -> Optional[str]:
        p = self._opt("predictions_file")
        if not p:
            return None
        return p if os.path.isabs(p) else os.path.join(
            self.app_config.get("task_dir", "."), p)

    def _file_rows(self) -> Dict[tuple, Dict[str, Any]]:
        path = self._file_path()
        if not path:
            return {}
        if not os.path.exists(path):
            raise SourceError(f"source {self.id!r}: {path} not found")
        out = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    out[(str(r.get("id")), r.get("schema"))] = r
        return out

    def supports(self, scheme: SchemeSpec) -> bool:
        return True

    def prompt_template(self, scheme: SchemeSpec) -> str:
        path = self._file_path()
        digest = ""
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()[:16]
        return f"static:{self._opt('field')}:{digest}"

    def _lookup(self, item, scheme, rows) -> Optional[Dict[str, Any]]:
        if rows:
            return rows.get((item.item_id, scheme.name))
        field = self._opt("field")
        if not field:
            return None
        blob = item.data.get(field)
        if blob is None:
            return None
        if isinstance(blob, str):
            try:
                blob = json.loads(blob)
            except ValueError:
                pass
        if isinstance(blob, dict) and scheme.name in blob:
            v = blob[scheme.name]
            return v if isinstance(v, dict) and "label" in v else {"label": v}
        if self._single_scheme():
            # One scheme, so a bare value can only mean its label.
            if isinstance(blob, dict):
                return blob if "label" in blob else None
            return {"label": blob}
        self._shape_misses.append(type(blob).__name__)
        return None

    def _single_scheme(self) -> bool:
        named = self.cfg.raw.get("schemas") or self.cfg.schemas or []
        if named:
            return len(named) == 1
        return len(self.app_config.get("annotation_schemes") or []) == 1

    def predict_batch(self, items, scheme, ctx, sv) -> List[Prediction]:
        rows = self._file_rows()
        self._shape_misses: List[str] = []
        if not rows and self._opt("field") and items:
            # Fail loudly on a field of the wrong shape: abstaining on every
            # item looks like a source that is merely unsure.
            for item in items:
                self._lookup(item, scheme, rows)
            if len(self._shape_misses) == len(items):
                raise SourceError(
                    f"source {self.id!r}: field {self._opt('field')!r} holds "
                    f"{self._shape_misses[0]}, expected {{scheme: label}} "
                    f"(e.g. {{{scheme.name!r}: ...}}); a bare label works only "
                    "when the source labels one scheme")
            self._shape_misses = []
        default = float(self._opt("default_confidence", 0.5))
        out = []
        for item in items:
            found = self._lookup(item, scheme, rows)
            res = ctx.call(sv, None, f"{item.item_id}:{scheme.name}",
                           schema_hash=scheme.schema_hash(), max_output_tokens=0,
                           invoke=lambda _p, found=found: (found, None), cacheable=False)
            if not found or found.get("label") is None:
                out.append(Prediction(item.item_id, scheme.name, sv.version_id, None,
                                      status="abstain", raw_conf=0.0,
                                      call_ids=[res.call_id]))
                continue
            value = found["label"]
            if scheme.labels and isinstance(value, str):
                value = normalize_label(value, scheme.labels) or value
            conf = found.get("confidence")
            out.append(Prediction(item.item_id, scheme.name, sv.version_id, value,
                                  raw_conf=float(conf) if conf is not None else default,
                                  call_ids=[res.call_id]))
        return out

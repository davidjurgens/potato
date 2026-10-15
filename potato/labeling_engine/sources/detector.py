"""
Object-detector source (YOLO and friends) for image_annotation schemes.

The prediction for an image is its set of boxes. The confidence for the image
as a whole has to cover two ways of being wrong: a box that should not be
there, and an object the detector saw but kept below the cut. So it is the
lowest of the kept boxes' confidences and one minus each dropped candidate's:
an image is only as certain as its least certain decision.

Options (under ``options``):
  keep_threshold        boxes at or above this are the prediction (0.35)
  candidate_threshold   boxes between this and keep_threshold count against
                        the image's confidence (0.05)
  label_map             detector class -> scheme label; classes not mapped to
                        a scheme label are ignored. Default: identity.
  image_field           item field holding the image path or URL (default:
                        the item's text_key value)
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from ..model.records import Prediction
from ..schemes import SchemeSpec
from .base import Source, SourceError, build_endpoint


class DetectorSource(Source):
    kind = "detector"
    CODE_VERSION = "1"

    def __init__(self, cfg, app_config=None, engine_cfg=None):
        super().__init__(cfg, app_config, engine_cfg)
        self._endpoint_obj = None
        self._lock = threading.Lock()

    def _opt(self, key, default):
        return (self.cfg.options or {}).get(key, default)

    def supports(self, scheme: SchemeSpec) -> bool:
        return scheme.annotation_type == "image_annotation" and bool(scheme.labels)

    def prompt_template(self, scheme: SchemeSpec) -> str:
        return repr(sorted({k: self._opt(k, None) for k in (
            "keep_threshold", "candidate_threshold", "label_map", "image_field")}.items()))

    def _endpoint(self):
        with self._lock:
            if self._endpoint_obj is None:
                cfg = self.cfg
                opts = dict(cfg.options or {})
                opts["confidence_threshold"] = float(self._opt("candidate_threshold", 0.05))
                from dataclasses import replace
                self._endpoint_obj = build_endpoint(replace(cfg, options={
                    k: v for k, v in opts.items()
                    if k not in ("keep_threshold", "candidate_threshold", "label_map",
                                 "image_field")}))
            return self._endpoint_obj

    def _map(self, label: str, scheme: SchemeSpec):
        mapping = self._opt("label_map", None)
        if mapping:
            return mapping.get(label)
        return label if label in scheme.labels else None

    def predict_batch(self, items, scheme, ctx, sv) -> List[Prediction]:
        if not self.supports(scheme):
            raise SourceError(self.unsupported_reason(scheme))
        keep = float(self._opt("keep_threshold", 0.35))
        cand = float(self._opt("candidate_threshold", 0.05))
        field = self._opt("image_field", None)

        def detect(ref):
            from .base import local_media_path
            ep = self._endpoint()
            dets = ep.detect(local_media_path(self.app_config, ref),
                             confidence_threshold=cand)
            out = []
            for d in dets or []:
                label = self._map(str(d.get("label")), scheme)
                if label is None:
                    continue
                b = d.get("bbox") or {}
                out.append({"label": label, "confidence": float(d.get("confidence", 0)),
                            "bbox": [float(b.get("x", 0)), float(b.get("y", 0)),
                                     float(b.get("width", 0)), float(b.get("height", 0))]})
            return out, None

        def one(item):
            ref = str(item.data.get(field) if field else item.text or "")
            if not ref:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="error", reasoning="no image reference")
            res = ctx.call(sv, None, ref, schema_hash=scheme.schema_hash(),
                           max_output_tokens=0, concurrency=self.concurrency or 1,
                           invoke=detect)
            if not res.ok:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="error", call_ids=[res.call_id],
                                  reasoning=res.error)
            dets = res.reply or []
            kept = [d for d in dets if d["confidence"] >= keep]
            dropped = [d for d in dets if d["confidence"] < keep]
            confs = [d["confidence"] for d in kept] + [1 - d["confidence"] for d in dropped]
            value = [{"type": "bbox", "label": d["label"], "bbox": d["bbox"]} for d in kept]
            return Prediction(item.item_id, scheme.name, sv.version_id, value,
                              raw_conf=min(confs) if confs else 1.0,
                              conf={"boxes": [d["confidence"] for d in kept]},
                              call_ids=[res.call_id])

        return ctx.parallel(list(items), one, self.concurrency or 1)

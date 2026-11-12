"""
Decision-model source: Laya in-process, or any /v1/systemone server (hosted
Jev, OpenJev through vLLM, Laya's bundled server).

A decision model returns a probability for every option in one forward pass
and generates no text, so its confidence is the probability of the chosen
option and there is nothing to parse.
"""

from __future__ import annotations

import threading
from typing import List

from ..model.records import Prediction
from ..schemes import SchemeSpec
from .base import Source, SourceError, build_endpoint

DECISION_TYPES = ("radio", "select", "likert", "slider")


class DecisionSource(Source):
    kind = "decision"
    #: 2: in-process Laya wraps the state as {"text": ...}, as systemone does.
    CODE_VERSION = "2"

    def __init__(self, cfg, app_config=None, engine_cfg=None):
        super().__init__(cfg, app_config, engine_cfg)
        self._endpoint_obj = None
        self._lock = threading.Lock()

    def supports(self, scheme: SchemeSpec) -> bool:
        from potato.ai.decision_endpoint import UnsupportedSchemeError, questions_for_scheme
        if scheme.annotation_type not in DECISION_TYPES:
            return False
        try:
            questions_for_scheme(scheme.raw, "")
        except UnsupportedSchemeError:
            return False
        return True

    def prompt_template(self, scheme: SchemeSpec) -> str:
        return self.cfg.prompt or scheme.description or ""

    def _endpoint(self):
        with self._lock:
            if self._endpoint_obj is None:
                ep = build_endpoint(self.cfg)
                if getattr(ep, "is_decision_model", False) is not True:
                    raise SourceError(f"source {self.id!r}: {self.cfg.endpoint_type!r} "
                                      "is not a decision model; use kind: llm")
                self._endpoint_obj = ep
            return self._endpoint_obj

    def predict_batch(self, items, scheme, ctx, sv) -> List[Prediction]:
        from potato.ai.decision_endpoint import questions_for_scheme
        if not self.supports(scheme):
            raise SourceError(self.unsupported_reason(scheme))
        questions = questions_for_scheme(scheme.raw, self.prompt_template(scheme))
        endpoint = self._endpoint()

        def decide(text):
            [ans] = endpoint.decide(text, questions)
            return ({"value": ans.value, "confidence": ans.confidence,
                     "probabilities": ans.probabilities}, None)

        def one(item):
            res = ctx.call(sv, endpoint, item.text, schema_hash=scheme.schema_hash(),
                           max_output_tokens=0, base_url=self.cfg.base_url,
                           concurrency=self.concurrency, invoke=decide)
            if not res.ok:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="error", call_ids=[res.call_id],
                                  reasoning=res.error)
            reply = res.reply or {}
            value = reply.get("value")
            if value is None:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="abstain", raw_conf=0.0, call_ids=[res.call_id])
            return Prediction(item.item_id, scheme.name, sv.version_id, str(value),
                              raw_conf=max(0.0, min(1.0, float(reply.get("confidence", 0)))),
                              conf={str(k): float(v) for k, v in
                                    (reply.get("probabilities") or {}).items()},
                              call_ids=[res.call_id])

        return ctx.parallel(list(items), one, self.concurrency or 1)

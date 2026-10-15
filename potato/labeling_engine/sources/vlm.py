"""
Vision-language source: an image plus the scheme's question, for one-of-N
schemes about the image. Verbalized confidence, as for the text LLM source.

``endpoint_type`` is a vision endpoint (openai_vision, anthropic_vision,
ollama_vision). For a self-hosted model behind an OpenAI-compatible server,
use openai_vision with ``base_url``.
"""

from __future__ import annotations

import threading
from typing import List

from ..model.records import Prediction
from ..schemes import SchemeSpec, normalize_label
from .base import Source, SourceError, build_endpoint
from .llm import DEFAULT_TEMPLATE, _parse_reply

VLM_TEMPLATE = """{instructions}

Labels:
{labels}

Look at the image. Answer with JSON: {{"label": one of the labels above, exactly \
as written, "confidence": 0-100 for how sure you are, "reasoning": one short sentence}}."""


class VLMSource(Source):
    kind = "vlm"
    CODE_VERSION = "1"

    def __init__(self, cfg, app_config=None, engine_cfg=None):
        super().__init__(cfg, app_config, engine_cfg)
        self._endpoint_obj = None
        self._lock = threading.Lock()

    def supports(self, scheme: SchemeSpec) -> bool:
        return scheme.is_one_of_n and len(scheme.labels) >= 2

    def prompt_template(self, scheme: SchemeSpec) -> str:
        return self.cfg.prompt or VLM_TEMPLATE

    def _prompt(self, scheme: SchemeSpec) -> str:
        labels = "\n".join(f"- {n}" + (f": {scheme.descriptions[n]}"
                                       if n in scheme.descriptions else "")
                           for n in scheme.labels)
        return self.prompt_template(scheme).format(
            instructions=(scheme.description or f"Choose the {scheme.name} label.").strip(),
            labels=labels, description=scheme.description, text="")

    def _endpoint(self):
        with self._lock:
            if self._endpoint_obj is None:
                self._endpoint_obj = build_endpoint(self.cfg)
            return self._endpoint_obj

    def predict_batch(self, items, scheme, ctx, sv) -> List[Prediction]:
        from potato.ai.ai_endpoint import normalize_confidence
        from potato.ai.visual_ai_endpoint import BaseVisualAIEndpoint as VisualAIEndpoint
        from pydantic import ConfigDict, create_model
        from typing import Literal
        if not self.supports(scheme):
            raise SourceError(self.unsupported_reason(scheme))
        prompt = self._prompt(scheme)
        fields = {"label": (Literal[tuple(scheme.labels)], scheme.labels[0]),
                  "confidence": (float, 50.0), "reasoning": (str, "")}
        fmt = create_model("EngineImageLabel", __config__=ConfigDict(
            json_schema_extra={"required": list(fields)}), **fields)
        field = (self.cfg.options or {}).get("image_field")

        def one(item):
            ref = str(item.data.get(field) if field else item.text or "")

            def ask(_p, ref=ref):
                ep = self._endpoint()
                from .base import local_media_path
                if ref.startswith(("http://", "https://")):
                    img = VisualAIEndpoint.create_url_image_data(ref)
                else:
                    img = VisualAIEndpoint.encode_image_to_base64(
                        local_media_path(self.app_config, ref))
                from potato.ai.ai_endpoint import _LAST_USAGE
                _LAST_USAGE.value = None
                reply = ep.query_with_image(prompt, img, fmt)
                return reply, getattr(_LAST_USAGE, "value", None)

            res = ctx.call(sv, None, f"{prompt}\n[image] {ref}",
                           schema_hash=scheme.schema_hash(),
                           max_output_tokens=self.cfg.max_tokens,
                           base_url=self.cfg.base_url, concurrency=self.concurrency,
                           invoke=ask)
            if not res.ok:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="error", call_ids=[res.call_id],
                                  reasoning=res.error)
            reply = _parse_reply(res.reply)
            label = normalize_label(reply.get("label"), scheme.labels)
            if label is None:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="abstain", raw_conf=0.0, call_ids=[res.call_id])
            return Prediction(item.item_id, scheme.name, sv.version_id, label,
                              raw_conf=normalize_confidence(reply.get("confidence")),
                              call_ids=[res.call_id],
                              reasoning=str(reply.get("reasoning") or "")[:500] or None)

        return ctx.parallel(list(items), one, self.concurrency)

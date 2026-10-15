"""
LLM-as-judge source: a rubric, the item's fields, one label with confidence.

The prompt is the one ``potato/ai/judge.py`` builds for judge alignment, so a
judge calibrated here and the same judge in the old judge-alignment report
see the same words. Options (under ``options``):

  rubric       what the judge applies (default: the scheme's description)
  fields       item fields shown to the judge, in order (default: the text)
  swap_order   ask twice with the label order reversed. A verdict that flips
               with the order is a judgement about the prompt, not the item,
               so it becomes an abstention and goes to a person; agreeing
               verdicts keep the lower of the two confidences. Judges favour
               whichever label is listed first (``ai/position_bias.py``).
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..model.records import Prediction
from ..schemes import SchemeSpec, normalize_label
from .llm import LLMSource, _parse_reply


class JudgeSource(LLMSource):
    kind = "judge"
    CODE_VERSION = "1"

    @property
    def method(self) -> str:
        return "verbalized"

    def supports(self, scheme: SchemeSpec) -> bool:
        from ..families import TRACE_TYPES
        if scheme.annotation_type in TRACE_TYPES:
            return True
        return super().supports(scheme)

    def _opt(self, key, default=None):
        return (self.cfg.options or {}).get(key, (self.cfg.raw.get("judge") or {}).get(
            key, default))

    def _service(self, scheme: SchemeSpec):
        from potato.ai.judge import JudgeService
        rubric = self._opt("rubric") or scheme.description
        return JudgeService({"judge_alignment": {"schemas": {scheme.name: {"rubric": rubric}}}})

    def _item_text(self, item) -> str:
        fields = self._opt("fields")
        if not fields:
            return item.text
        parts = []
        for f in fields:
            v = item.data.get(f)
            if v is None:
                continue
            if not isinstance(v, str):
                import json
                v = json.dumps(v, ensure_ascii=False)
            parts.append(f"{f}:\n{v}")
        return "\n\n".join(parts)

    def prompt_template(self, scheme: SchemeSpec) -> str:
        return self._service(scheme).build_prompt(scheme.raw, "{item}") + \
            f"|fields={self._opt('fields')}|swap={bool(self._opt('swap_order'))}"

    def build_prompt(self, scheme: SchemeSpec, text: str, reverse: bool = False) -> str:
        order = list(reversed(scheme.labels)) if reverse else None
        return self._service(scheme).build_prompt(scheme.raw, text, label_order=order)

    def _ask(self, item, scheme, ctx, sv, reverse: bool):
        from potato.ai.ai_endpoint import normalize_confidence
        prompt = self.build_prompt(scheme, self._item_text(item), reverse)
        res = ctx.call(sv, self._endpoint(), prompt, self._response_model(scheme),
                       schema_hash=scheme.schema_hash(), sample_idx=1 if reverse else 0,
                       max_output_tokens=self.cfg.max_tokens, base_url=self.cfg.base_url,
                       concurrency=self.concurrency)
        if not res.ok:
            return None, 0.0, res
        reply = _parse_reply(res.reply)
        return (normalize_label(reply.get("label"), scheme.labels),
                normalize_confidence(reply.get("confidence")), res)

    def _predict_steps(self, items, scheme, ctx, sv) -> List[Prediction]:
        """Per-step process rewards, through ``JudgeService.judge_steps``.

        The service makes the request, but inside ``ctx.call``, so the call
        is logged, cached and budgeted like any other.
        """
        from potato.ai.judge import JudgeService
        from .base import endpoint_config
        steps_key = scheme.raw.get("steps_key", "steps")
        rubric = self._opt("rubric") or scheme.description
        service = JudgeService({"judge_alignment": {
            "ai_support": endpoint_config(self.cfg)["ai_support"],
            "schemas": {scheme.name: {"rubric": rubric}}}})

        def one(item):
            steps = item.data.get(steps_key) or []
            if not steps:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="abstain", raw_conf=0.0,
                                  reasoning=f"item has no {steps_key!r} list")
            text = "\n".join(str(st) for st in steps)
            res = ctx.call(sv, None, f"steps:{scheme.name}:{rubric}\n{text}",
                           schema_hash=scheme.schema_hash(),
                           max_output_tokens=max(512, 24 * len(steps)),
                           base_url=self.cfg.base_url, concurrency=self.concurrency,
                           invoke=lambda _p: (service.judge_steps(
                               item.item_id, scheme.raw, steps, rubric=rubric), None))
            if not res.ok or not res.reply:
                # No verdicts is a failure to answer, not an answer: an error,
                # so the item is asked again (up to the retry cap), with a
                # reason. Recorded as an abstain it was final and silent.
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="error", call_ids=[res.call_id],
                                  reasoning=res.error or (
                                      "the judge returned no step verdicts (no endpoint, "
                                      "or a reply that could not be parsed)"))
            value = {str(r["index"]): r["reward"] for r in res.reply}
            confs = [r["confidence"] for r in res.reply if r.get("confidence") is not None]
            return Prediction(item.item_id, scheme.name, sv.version_id, value,
                              raw_conf=min(confs) if confs else 0.5,
                              call_ids=[res.call_id])

        return ctx.parallel(list(items), one, self.concurrency)

    def predict_batch(self, items, scheme, ctx, sv) -> List[Prediction]:
        from ..families import TRACE_TYPES
        if not self.supports(scheme):
            from .base import SourceError
            raise SourceError(self.unsupported_reason(scheme))
        if scheme.annotation_type in TRACE_TYPES:
            return self._predict_steps(items, scheme, ctx, sv)
        swap = bool(self._opt("swap_order", False))

        def one(item):
            label, conf, res = self._ask(item, scheme, ctx, sv, False)
            call_ids = [res.call_id]
            if not res.ok:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="error", call_ids=call_ids, reasoning=res.error)
            note = None
            if swap and label is not None:
                label2, conf2, res2 = self._ask(item, scheme, ctx, sv, True)
                call_ids.append(res2.call_id)
                if res2.ok and label2 != label:
                    return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                      status="abstain", raw_conf=0.0, call_ids=call_ids,
                                      reasoning=f"verdict flipped with label order "
                                                f"({label} vs {label2})")
                if res2.ok:
                    conf = min(conf, conf2)
                    note = "same verdict under both label orders"
            if label is None:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="abstain", raw_conf=0.0, call_ids=call_ids)
            return Prediction(item.item_id, scheme.name, sv.version_id, label,
                              raw_conf=conf, call_ids=call_ids, reasoning=note)

        return ctx.parallel(list(items), one, self.concurrency)

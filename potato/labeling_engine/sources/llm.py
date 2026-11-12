"""
Generative LLM source for one-of-N schemes.

Confidence comes from one of three methods, chosen by ``confidence.method``:

- ``verbalized`` (the default): the model reports 0-100 in the same reply.
  Cheapest, and the least reliable; the calibrator in the contracts layer is
  what makes it usable.
- ``k_sample``: ``samples`` replies at ``sample_temperature``; the label is
  the most common answer and the confidence is its share. Costs k calls.
- ``logprob``: the labels are lettered and the model answers with one letter;
  the probability of each label is read from the first token's log
  probabilities. One call, no generated text, and the best-calibrated of the
  three where the backend exposes logprobs (vLLM and OpenAI-compatible
  servers). Limited to 20 labels, the most top_logprobs those servers return.
"""

from __future__ import annotations

import json
import math
import re
import string
import threading
from typing import Any, Dict, List, Optional, Sequence

from ..model.records import Prediction
from ..schemes import SchemeSpec, normalize_label
from .base import Source, SourceError, build_endpoint

DEFAULT_TEMPLATE = """{instructions}

Labels:
{labels}

Item:
\"\"\"
{text}
\"\"\"

Answer with JSON: {{"label": one of the labels above, exactly as written, \
"confidence": 0-100 for how sure you are, "reasoning": one short sentence}}."""

LETTER_TEMPLATE = """{instructions}

Options:
{options}

Item:
\"\"\"
{text}
\"\"\"

Answer with the letter of the one option that fits best, and nothing else."""

LETTERS = string.ascii_uppercase
MAX_LOGPROB_LABELS = 20
LOGPROB_ENDPOINTS = ("vllm", "openai", "openrouter")


def _parse_reply(reply: Any) -> Dict[str, Any]:
    if isinstance(reply, dict):
        return reply
    if not isinstance(reply, str):
        return {}
    text = reply.strip()
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else {}
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            out = json.loads(m.group(0))
            return out if isinstance(out, dict) else {}
        except ValueError:
            return {}
    return {}


class LLMSource(Source):
    kind = "llm"
    CODE_VERSION = "1"

    def __init__(self, cfg, app_config=None, engine_cfg=None):
        super().__init__(cfg, app_config, engine_cfg)
        self._endpoints: Dict[Any, Any] = {}
        self._lock = threading.Lock()

    # --- configuration --------------------------------------------------------

    @property
    def method(self) -> str:
        m = (self.cfg.confidence or {}).get("method", "auto")
        return "verbalized" if m in ("auto", "native") else m

    @property
    def samples(self) -> int:
        return max(2, int((self.cfg.confidence or {}).get("samples", 5)))

    @property
    def sample_temperature(self) -> float:
        return float((self.cfg.confidence or {}).get("sample_temperature", 0.7))

    def supports(self, scheme: SchemeSpec) -> bool:
        if not scheme.is_one_of_n or len(scheme.labels) < 2:
            return False
        if self.method == "logprob":
            return (len(scheme.labels) <= MAX_LOGPROB_LABELS
                    and self.cfg.endpoint_type in LOGPROB_ENDPOINTS)
        return True

    def unsupported_reason(self, scheme):
        if self.method == "logprob" and scheme.is_one_of_n:
            return (f"source {self.id!r}: logprob confidence needs a vllm, openai or "
                    f"openrouter endpoint and at most {MAX_LOGPROB_LABELS} labels")
        return super().unsupported_reason(scheme)

    def _instructions(self, scheme: SchemeSpec) -> str:
        return (scheme.description or f"Choose the {scheme.name} label for the item.").strip()

    def _label_lines(self, scheme: SchemeSpec) -> str:
        return "\n".join(f"- {name}" + (f": {scheme.descriptions[name]}"
                                        if name in scheme.descriptions else "")
                         for name in scheme.labels)

    def prompt_template(self, scheme: SchemeSpec) -> str:
        if self.method == "logprob":
            return LETTER_TEMPLATE
        return self.cfg.prompt or DEFAULT_TEMPLATE

    def build_prompt(self, scheme: SchemeSpec, text: str) -> str:
        if self.method == "logprob":
            options = "\n".join(f"{LETTERS[i]}. {name}" + (
                f": {scheme.descriptions[name]}" if name in scheme.descriptions else "")
                for i, name in enumerate(scheme.labels))
            return LETTER_TEMPLATE.format(instructions=self._instructions(scheme),
                                          options=options, text=text)
        template = self.cfg.prompt or DEFAULT_TEMPLATE
        values = {"instructions": self._instructions(scheme),
                  "description": scheme.description,
                  "labels": self._label_lines(scheme), "text": text}
        try:
            prompt = template.format(**values)
        except (KeyError, IndexError, ValueError) as e:
            raise SourceError(f"source {self.id!r}: prompt template is not valid: {e}. "
                              "Use {text}, {labels}, {instructions} and {description}; "
                              "write literal braces as {{ and }}") from e
        if "{text}" not in template:
            prompt += f'\n\nItem:\n"""\n{text}\n"""'
        return prompt

    def _response_model(self, scheme: SchemeSpec):
        from typing import Literal
        from pydantic import ConfigDict, create_model
        fields = {"label": (Literal[tuple(scheme.labels)], scheme.labels[0]),
                  "confidence": (float, 50.0), "reasoning": (str, "")}
        return create_model("EngineLabel", __config__=ConfigDict(
            json_schema_extra={"required": list(fields)}), **fields)

    def _endpoint(self, temperature: Optional[float] = None):
        key = temperature
        with self._lock:
            if key not in self._endpoints:
                self._endpoints[key] = build_endpoint(self.cfg, temperature=temperature)
            return self._endpoints[key]

    # --- prediction -------------------------------------------------------

    def predict_batch(self, items, scheme, ctx, sv) -> List[Prediction]:
        if not self.supports(scheme):
            raise SourceError(self.unsupported_reason(scheme))
        fn = {"verbalized": self._verbalized, "k_sample": self._k_sample,
              "logprob": self._logprob}[self.method]
        return ctx.parallel(list(items), lambda it: fn(it, scheme, ctx, sv),
                            self.concurrency)

    def _verbalized(self, item, scheme, ctx, sv) -> Prediction:
        from potato.ai.ai_endpoint import normalize_confidence
        prompt = self.build_prompt(scheme, item.text)
        res = ctx.call(sv, self._endpoint(), prompt, self._response_model(scheme),
                       schema_hash=scheme.schema_hash(),
                       max_output_tokens=self.cfg.max_tokens, base_url=self.cfg.base_url,
                       concurrency=self.concurrency)
        if not res.ok:
            return Prediction(item.item_id, scheme.name, sv.version_id, None,
                              status="error", call_ids=[res.call_id], reasoning=res.error)
        reply = _parse_reply(res.reply)
        label = normalize_label(reply.get("label"), scheme.labels)
        if label is None:
            return Prediction(item.item_id, scheme.name, sv.version_id, None,
                              status="abstain", raw_conf=0.0, call_ids=[res.call_id],
                              reasoning=f"unmatched label {reply.get('label')!r}")
        return Prediction(item.item_id, scheme.name, sv.version_id, label,
                          raw_conf=normalize_confidence(reply.get("confidence")),
                          call_ids=[res.call_id],
                          reasoning=str(reply.get("reasoning") or "")[:500] or None)

    def _k_sample(self, item, scheme, ctx, sv) -> Prediction:
        prompt = self.build_prompt(scheme, item.text)
        endpoint = self._endpoint(self.sample_temperature)
        votes: Dict[str, int] = {}
        call_ids = []
        errors = 0
        for k in range(self.samples):
            res = ctx.call(sv, endpoint, prompt, self._response_model(scheme),
                           schema_hash=scheme.schema_hash(), sample_idx=k,
                           max_output_tokens=self.cfg.max_tokens,
                           base_url=self.cfg.base_url, concurrency=self.concurrency)
            call_ids.append(res.call_id)
            if not res.ok:
                errors += 1
                continue
            label = normalize_label(_parse_reply(res.reply).get("label"), scheme.labels)
            if label is not None:
                votes[label] = votes.get(label, 0) + 1
        if not votes:
            status = "error" if errors == self.samples else "abstain"
            return Prediction(item.item_id, scheme.name, sv.version_id, None,
                              status=status, raw_conf=0.0, call_ids=call_ids)
        # Ties go to the label listed first in the scheme, so the choice does
        # not depend on dict order.
        best = max(scheme.labels, key=lambda lab: (votes.get(lab, 0),
                                                   -scheme.labels.index(lab)))
        dist = {lab: votes.get(lab, 0) / self.samples for lab in scheme.labels}
        return Prediction(item.item_id, scheme.name, sv.version_id, best,
                          raw_conf=votes[best] / self.samples, conf=dist,
                          call_ids=call_ids)

    def _logprob(self, item, scheme, ctx, sv) -> Prediction:
        prompt = self.build_prompt(scheme, item.text)
        n = len(scheme.labels)
        res = ctx.call(sv, None, prompt, schema_hash=scheme.schema_hash(),
                       max_output_tokens=1, base_url=self.cfg.base_url,
                       concurrency=self.concurrency,
                       invoke=lambda p: self._letter_logprobs(p, n))
        if not res.ok:
            return Prediction(item.item_id, scheme.name, sv.version_id, None,
                              status="error", call_ids=[res.call_id], reasoning=res.error)
        letter_lp = res.reply or {}
        probs = {}
        for i, name in enumerate(scheme.labels):
            lp = letter_lp.get(LETTERS[i])
            probs[name] = math.exp(lp) if lp is not None else 0.0
        total = sum(probs.values())
        if total <= 0:
            return Prediction(item.item_id, scheme.name, sv.version_id, None,
                              status="abstain", raw_conf=0.0, call_ids=[res.call_id],
                              reasoning="no option letter among the top tokens")
        dist = {k: v / total for k, v in probs.items()}
        best = max(scheme.labels, key=lambda lab: (dist[lab], -scheme.labels.index(lab)))
        return Prediction(item.item_id, scheme.name, sv.version_id, best,
                          raw_conf=dist[best], conf=dist, call_ids=[res.call_id])

    def _letter_logprobs(self, prompt: str, n_options: int):
        """``({letter: logprob}, usage)`` from the first generated token."""
        import requests
        endpoint = self._endpoint()
        top = min(MAX_LOGPROB_LABELS, max(5, n_options + 2))
        payload = {"model": self.cfg.model,
                   "messages": [{"role": "user", "content": prompt}],
                   "max_tokens": 1, "temperature": 0, "logprobs": True,
                   "top_logprobs": top}
        if self.cfg.endpoint_type == "openai":
            resp = endpoint.client.chat.completions.create(**payload)
            content = resp.choices[0].logprobs.content or []
            entries = [(t.token, t.logprob) for t in (content[0].top_logprobs if content else [])]
            usage = getattr(resp, "usage", None)
            usage = ({"input_tokens": usage.prompt_tokens,
                      "output_tokens": usage.completion_tokens} if usage else None)
        else:
            base = getattr(endpoint, "base_url", None) or self.cfg.base_url or ""
            base = base.rstrip("/")
            url = (f"{base}/chat/completions" if base.endswith("/v1")
                   else f"{base}/v1/chat/completions")
            if self.cfg.endpoint_type == "openrouter":
                url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            key = self.cfg.api_key or getattr(endpoint, "api_key", "")
            if key:
                headers["Authorization"] = f"Bearer {key}"
            r = requests.post(url, json=payload, headers=headers,
                              timeout=self.cfg.timeout or 60)
            r.raise_for_status()
            data = r.json()
            content = ((data["choices"][0].get("logprobs") or {}).get("content") or [])
            entries = [(t.get("token"), t.get("logprob"))
                       for t in (content[0].get("top_logprobs") or [] if content else [])]
            u = data.get("usage") or {}
            usage = ({"input_tokens": u.get("prompt_tokens"),
                      "output_tokens": u.get("completion_tokens")} if u else None)
        out: Dict[str, float] = {}
        letters = set(LETTERS[:n_options])
        for token, lp in entries:
            tok = (token or "").strip().strip(".):").upper()
            if tok in letters and lp is not None:
                # Several tokenizations of one letter (" A", "A") add up.
                out[tok] = math.log(math.exp(out[tok]) + math.exp(lp)) if tok in out else lp
        return out, usage

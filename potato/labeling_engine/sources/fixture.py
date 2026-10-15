"""
A synthetic source with known error rates, for testing the statistics.

The contracts promise things like "at most 5% of accepted labels are wrong,
with 90% probability". The only way to check such a promise is to run it
many times against a labeler whose true error rate is known, and count how
often it was broken. This source is that labeler: it reads each item's true
label from ``field`` (default ``gold``), answers wrongly with probability
``error_rate`` (per class if given as a mapping), and reports a confidence
drawn so that correct answers tend to score higher, by ``separability``
(0 = confidence says nothing, 1 = it separates them perfectly).

Answers are a deterministic function of (seed, item id), so a run can be
replayed exactly. Each answer is still logged as a call, so the runner's
bookkeeping is exercised the same way as for a real model.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List, Sequence

from ..model.records import Prediction
from ..schemes import SchemeSpec
from .base import Source


def _rng(seed: Any, item_id: str) -> random.Random:
    digest = hashlib.blake2b(f"{seed}:{item_id}".encode(), digest_size=8).digest()
    return random.Random(int.from_bytes(digest, "big"))


class FixtureSource(Source):
    kind = "fixture"

    def supports(self, scheme: SchemeSpec) -> bool:
        return bool(scheme.labels)

    def _params(self) -> Dict[str, Any]:
        raw = self.cfg.raw
        opts = self.cfg.options or {}
        return {
            "field": raw.get("field") or opts.get("field") or "gold",
            "error_rate": raw.get("error_rate", opts.get("error_rate", 0.1)),
            "separability": float(opts.get("separability", 0.6)),
            "abstain_rate": float(opts.get("abstain_rate", 0.0)),
            "seed": raw.get("seed", opts.get("seed", 0)),
        }

    def prompt_template(self, scheme: SchemeSpec) -> str:
        return f"fixture:{sorted(self._params().items())}"

    def answer(self, item_id: str, truth: Any, labels: List[str]):
        """``(label or None, confidence)`` for one item."""
        p = self._params()
        rng = _rng(p["seed"], item_id)
        if rng.random() < p["abstain_rate"]:
            return None, 0.0
        err = p["error_rate"]
        if isinstance(err, dict):
            err = float(err.get(str(truth), err.get("default", 0.1)))
        wrong = rng.random() < float(err)
        if wrong and len(labels) > 1:
            label = rng.choice([x for x in labels if x != truth])
        else:
            label = truth if truth in labels else rng.choice(labels)
            wrong = label != truth
        # A mixture: with separability s, correct answers sit in [0.5, 1] and
        # wrong ones in [0, 0.5]; with 1 - s both are uniform on [0, 1].
        s = max(0.0, min(1.0, p["separability"]))
        u = rng.random()
        separated = 0.5 * u if wrong else 0.5 + 0.5 * u
        conf = s * separated + (1.0 - s) * u
        return label, max(0.0, min(1.0, conf))

    def predict_batch(self, items, scheme, ctx, sv) -> List[Prediction]:
        field = self._params()["field"]

        def one(item):
            truth = item.data.get(field)
            label, conf = self.answer(item.item_id, truth, scheme.labels)
            res = ctx.call(sv, None, item.item_id, schema_hash=scheme.schema_hash(),
                           max_output_tokens=0,
                           invoke=lambda _p, label=label, conf=conf: (
                               {"label": label, "confidence": conf}, None))
            if not res.ok:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="error", call_ids=[res.call_id])
            reply = res.reply or {}
            if reply.get("label") is None:
                return Prediction(item.item_id, scheme.name, sv.version_id, None,
                                  status="abstain", raw_conf=0.0, call_ids=[res.call_id])
            return Prediction(item.item_id, scheme.name, sv.version_id, reply["label"],
                              raw_conf=float(reply["confidence"]),
                              call_ids=[res.call_id])

        return ctx.parallel(list(items), one, self.concurrency or 1)

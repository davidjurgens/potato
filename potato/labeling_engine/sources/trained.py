"""
A model trained on this study's labels (``potato/training``), as a source.

Usually created by distillation (``labeling_engine/distill.py``) rather than
written into the config. Its version includes the training run, so each
retrain is a new labeler: the cascade hash changes, contracts go stale, and
the new tier is calibrated and certified on the same human labels as any
other.

Options: ``artifact_dir`` (the fitted model), ``trainer`` (default
sklearn-text), ``run_id``.
"""

from __future__ import annotations

import threading
from typing import List

from ..model.records import Prediction
from ..schemes import SchemeSpec
from .base import Source, SourceError


class TrainedSource(Source):
    kind = "trained"
    CODE_VERSION = "1"

    def __init__(self, cfg, app_config=None, engine_cfg=None):
        super().__init__(cfg, app_config, engine_cfg)
        self._lock = threading.Lock()

    def _opt(self, key, default=None):
        return (self.cfg.options or {}).get(key, default)

    def supports(self, scheme: SchemeSpec) -> bool:
        trained_for = self._opt("scheme")
        return (trained_for is None or trained_for == scheme.name) and scheme.is_one_of_n

    def prompt_template(self, scheme: SchemeSpec) -> str:
        return f"trained:{self._opt('trainer', 'sklearn-text')}:{self._opt('run_id')}"

    def predict_batch(self, items, scheme, ctx, sv) -> List[Prediction]:
        from potato.training.base import PredictItem, SchemaSpec as TSchema, TrainingSpec
        from potato.training.registry import get_trainer
        art = self._opt("artifact_dir")
        if not art:
            raise SourceError(f"source {self.id!r}: no artifact_dir")
        trainer = get_trainer(self._opt("trainer", "sklearn-text"))
        spec = TrainingSpec(run_id=str(self._opt("run_id", "distilled")),
                            trainer=trainer.name,
                            schemas=(TSchema(name=scheme.name,
                                             annotation_type=scheme.annotation_type,
                                             kind="nominal", labels=tuple(scheme.labels)),),
                            bundle_dir=art, workdir=art)

        class _Quiet:
            def status(self, *a, **k): pass
            def progress(self, *a, **k): pass
            def log(self, *a, **k): pass
            def metric(self, *a, **k): pass
            def should_stop(self): return False

        def run_all(_prompt):
            recs = trainer.predict(spec, art, [PredictItem(instance_id=i.item_id,
                                                           text=i.text) for i in items],
                                   _Quiet())
            return ({r.instance_id: [r.payload.get("label"), r.confidence] for r in recs},
                    None)

        # One logged call per batch: the model runs in-process and costs
        # nothing, but the call log still records that it was asked.
        res = ctx.call(sv, None, "\n".join(i.item_id for i in items),
                       schema_hash=scheme.schema_hash(), max_output_tokens=0,
                       invoke=run_all, cacheable=False)
        if not res.ok:
            return [Prediction(i.item_id, scheme.name, sv.version_id, None, status="error",
                               call_ids=[res.call_id], reasoning=res.error) for i in items]
        out = []
        for i in items:
            label, conf = (res.reply or {}).get(i.item_id, (None, None))
            if label is None or label not in scheme.labels:
                out.append(Prediction(i.item_id, scheme.name, sv.version_id, None,
                                      status="abstain", raw_conf=0.0, call_ids=[res.call_id]))
            else:
                out.append(Prediction(i.item_id, scheme.name, sv.version_id, label,
                                      raw_conf=float(conf if conf is not None else 0.5),
                                      call_ids=[res.call_id]))
        return out

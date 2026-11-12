"""
A jury: several sources vote, the most common answer wins.

Members are other sources in the config (``members``). Each labels the item
through its own version and call log; the jury's prediction is the plurality
label, its confidence the share of members who gave it (ties go to the label
listed first in the scheme). Members that abstain or fail do not vote; if none
votes, the jury abstains.

The jury's version hashes its members' versions, so changing any member is a
new jury.
"""

from __future__ import annotations

from typing import Dict, List

from ..model.records import Prediction, SourceVersion, content_hash
from ..schemes import SchemeSpec
from .base import Source, SourceError


class JurySource(Source):
    kind = "jury"
    CODE_VERSION = "1"

    def _members(self) -> List[Source]:
        cached = getattr(self, "_member_cache", None)
        if cached is not None:
            return cached
        from . import build_source
        if self.engine_cfg is None:
            raise SourceError(f"jury {self.id!r} needs the engine config to find its members")
        out = []
        for mid in self.cfg.members:
            mcfg = self.engine_cfg.source(mid)
            if mcfg is None:
                raise SourceError(f"jury {self.id!r}: unknown member {mid!r}")
            out.append(build_source(mcfg, self.app_config, self.engine_cfg))
        self._member_cache = out
        return out

    def supports(self, scheme: SchemeSpec) -> bool:
        try:
            members = self._members()
        except SourceError:
            return False
        return scheme.is_one_of_n and all(m.supports(scheme) for m in members)

    def version(self, scheme: SchemeSpec) -> SourceVersion:
        members = [m.version(scheme).version_id for m in self._members()]
        return SourceVersion(source_id=self.cfg.id, kind=self.kind, model="jury",
                             endpoint_type="jury", params={"members": members,
                                                           "aggregation": self.cfg.aggregation},
                             prompt_template_hash=content_hash(members)[:32],
                             code_version=f"jury/{self.CODE_VERSION}")

    def predict_batch(self, items, scheme, ctx, sv) -> List[Prediction]:
        members = self._members()
        votes: Dict[str, List[Prediction]] = {i.item_id: [] for i in items}
        for m in members:
            msv = m.version(scheme)
            ctx.store.register_source_version(msv)
            for p in m.predict_batch(items, scheme, ctx, msv):
                p.run_id = ctx.run_id
                votes[p.item_id].append(p)
            # Members' own predictions are kept: each is a labeler in its own
            # right, and the certificate can show how the jury was formed.
            ctx.store.add_predictions([p for ps in votes.values() for p in ps
                                       if p.source_version_id == msv.version_id])
        out = []
        for it in items:
            ps = votes[it.item_id]
            call_ids = [c for p in ps for c in p.call_ids]
            answered = [p for p in ps if p.status == "ok" and p.value is not None]
            if not answered:
                out.append(Prediction(it.item_id, scheme.name, sv.version_id, None,
                                      status="abstain", raw_conf=0.0, call_ids=call_ids))
                continue
            counts = {lab: sum(1 for p in answered if p.value == lab) for lab in scheme.labels}
            best = max(scheme.labels, key=lambda lab: (counts[lab], -scheme.labels.index(lab)))
            dist = {lab: counts[lab] / len(members) for lab in scheme.labels}
            out.append(Prediction(it.item_id, scheme.name, sv.version_id, best,
                                  raw_conf=counts[best] / len(members), conf=dist,
                                  call_ids=call_ids,
                                  reasoning=f"{counts[best]} of {len(members)} members"))
        return out

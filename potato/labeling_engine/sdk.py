"""
The labeling engine from Python.

    from potato.labeling_engine.sdk import Study

    study = Study("examples/labeling-engine/text-certified-sentiment/config.yaml")
    study.run()                         # label, sample, certify, resolve
    for req in study.requests(status="open")[:5]:
        study.label(req.item_id, req.schema, "positive", user="me")
    study.certify()
    print(study.certificate(fmt="md"))
    study.export("out/")

The same engine the server and ``potato label`` drive, over the same
``engine.sqlite``: a study can be started in a notebook and finished in the
browser, or the other way round. Like ``potato label run``, ``run`` takes the
study's writer lock and refuses if a server's planner holds it.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


class Study:

    def __init__(self, config_path: str):
        from .cli import load_study
        from .service import Engine
        self.config_path = config_path
        self.config, self.items = load_study(config_path)
        self.engine = Engine(self.config)

    # --- driving ------------------------------------------------------------

    def run(self, until: str = "predicted", max_ticks: int = 20) -> Dict[str, Any]:
        from .allocation.planner import Planner
        holder = self.engine.store.writer_name("sdk")
        if not self.engine.store.acquire_writer(holder):
            raise RuntimeError(f"{self.engine.store.writer_holder()} is driving this study; "
                               "stop it or let it do the work. If it has already "
                               "stopped, the lock frees itself within 2 minutes.")
        try:
            planner = Planner(self.engine, item_source=lambda e: self.items)
            report = None
            for _ in range(max(1, max_ticks)):
                with self.engine.store.holding_writer(holder):
                    report = planner.tick()
                if until == "predicted":
                    break
                contracts = [c for s in self.engine.status()["schemes"].values()
                             for c in s["contracts"].values()]
                if contracts and all(c.get("status") == "met" for c in contracts):
                    break
                if any((r.get("more") or {}).get("waiting_on")
                       for r in report["schemes"].values()):
                    break
            return report
        finally:
            self.engine.store.release_writer(holder)

    def label(self, item_id: str, scheme: str, value: Any, user: str,
              request_id: Optional[int] = None) -> int:
        """Record a person's label; closes the request it answers."""
        return self.engine.record_human_label(item_id, scheme, value, user, request_id)

    # --- reading ------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return self.engine.status()

    def requests(self, status: Optional[str] = None, purpose: Optional[str] = None,
                 scheme: Optional[str] = None) -> List[Any]:
        return self.engine.store.requests(status=[status] if status else None,
                                          purpose=[purpose] if purpose else None,
                                          schema=scheme)

    def certify(self, retest: bool = False) -> Dict[str, Any]:
        """Evaluate every contract. ``retest`` also tests when only dev labels
        changed the rule, which spends a look."""
        return {s.name: self.engine.certify(s, retest=retest)
                for s in self.engine.schemes()}

    def certificate(self, fmt: str = "json"):
        from .certificate import build_certificate, render_html, render_markdown
        cert = build_certificate(self.engine)
        return {"json": cert, "md": render_markdown(cert), "html": render_html(cert)}[fmt]

    def export(self, out_dir: str):
        from potato.export.base import ExportContext
        from potato.export.registry import export_registry
        ctx = ExportContext(config=self.config, annotations=[], items={},
                            schemas=self.config.get("annotation_schemes") or [],
                            output_dir=self.config.get("output_annotation_dir") or ".")
        return export_registry.export("labeling_engine", ctx, out_dir)

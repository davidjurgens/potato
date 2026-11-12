"""
Machine sources. ``build_source`` maps a ``SourceConfig.kind`` to its class;
the class's module is imported only then, so a study that never uses a
detector never imports the detector code.
"""

from __future__ import annotations

import importlib

from .base import Source, SourceError  # noqa: F401

#: kind -> (module, class)
REGISTRY = {
    "fixture": (".fixture", "FixtureSource"),
    "llm": (".llm", "LLMSource"),
    "decision": (".decision", "DecisionSource"),
    "detector": (".detector", "DetectorSource"),
    "vlm": (".vlm", "VLMSource"),
    "judge": (".judge", "JudgeSource"),
    "trained": (".trained", "TrainedSource"),
    "jury": (".jury", "JurySource"),
    "static": (".static", "StaticSource"),
}


def build_source(cfg, app_config=None, engine_cfg=None) -> Source:
    entry = REGISTRY.get(cfg.kind)
    if entry is None:
        raise SourceError(f"source {cfg.id!r}: kind {cfg.kind!r} is not available")
    module = importlib.import_module(entry[0], __name__)
    return getattr(module, entry[1])(cfg, app_config, engine_cfg)

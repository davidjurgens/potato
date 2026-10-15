"""
Live check of the systemone decision source against an OpenJev server.

Skipped unless POTATO_OPENJEV_URL is set, e.g. through a tunnel to burger:

    ssh -f -N -L 18009:127.0.0.1:8009 burger.si.umich.edu
    POTATO_OPENJEV_URL=http://127.0.0.1:18009 POTATO_OPENJEV_MODEL=wev-8b \\
        pytest tests/unit/labeling_engine/test_openjev_live.py
"""

import os

import pytest

from potato.labeling_engine.config import parse_engine_config
from potato.labeling_engine.items import ItemView
from potato.labeling_engine.runtime import Runner
from potato.labeling_engine.schemes import SchemeSpec
from potato.labeling_engine.sources import build_source
from potato.labeling_engine.store import EngineStore
from potato.persistence import clear_db_cache

URL = os.environ.get("POTATO_OPENJEV_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POTATO_OPENJEV_URL to run")

SCHEME = {"name": "sentiment", "annotation_type": "radio",
          "description": "What is the overall sentiment of this review?",
          "labels": ["positive", "negative", "neutral"]}
REVIEWS = [("I absolutely love it, best purchase all year.", "positive"),
           ("It broke on day two and support never answered.", "negative"),
           ("The box contains one cable and a manual.", "neutral"),
           ("Fantastic sound, comfortable, worth every penny.", "positive"),
           ("Total waste of money. Returning it.", "negative")]


def test_openjev_labels_with_probabilities(tmp_path):
    clear_db_cache()
    app = {"task_dir": str(tmp_path), "annotation_task_name": "oj",
           "annotation_schemes": [SCHEME]}
    eng = parse_engine_config({**app, "labeling_engine": {"enabled": True, "sources": [
        {"id": "openjev", "kind": "decision", "endpoint_type": "systemone",
         "model": os.environ.get("POTATO_OPENJEV_MODEL", "wev-8b"), "base_url": URL}]}})
    store = EngineStore(str(tmp_path))
    items = [ItemView(f"r{k}", text, data={"gold": g}) for k, (text, g) in enumerate(REVIEWS)]
    s = Runner(store, app, eng).predict(build_source(eng.source("openjev"), app, eng),
                                        SchemeSpec.from_scheme(SCHEME), items)
    assert s.status == "done" and s.n_ok == len(items), s
    preds = store.current_predictions("sentiment", s.source_version_id)
    right = sum(preds[i.item_id].value == i.data["gold"] for i in items)
    assert right >= 4
    for p in preds.values():
        assert abs(sum(p.conf.values()) - 1.0) < 1e-3
        assert p.raw_conf == pytest.approx(p.conf[p.value], abs=1e-6)
    clear_db_cache()

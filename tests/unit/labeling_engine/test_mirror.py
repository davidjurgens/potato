"""Older subsystems' machine labels reach the engine's store when it is on."""

import pytest

from potato.labeling_engine.integration import hooks
from potato.labeling_engine.integration.mirror import mirror
from potato.persistence import clear_db_cache


@pytest.fixture
def engine(tmp_path):
    clear_db_cache()
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "m",
           "annotation_schemes": [{"name": "s", "annotation_type": "radio",
                                   "labels": ["a", "b"]}],
           "labeling_engine": {"enabled": True,
                               "sources": [{"id": "fx", "kind": "fixture"}]}}
    eng = hooks.init_engine(cfg, start_planner=False)
    yield eng
    hooks.clear_engine()
    clear_db_cache()


def test_mirrored_prediction_has_provenance(engine):
    mirror("solo_mode", "gemma", 3, "i1", "s", "a", 0.8, "because")
    mirror("solo_mode", "gemma", 4, "i1", "s", "b", 0.6)
    rows = engine.store.conn.execute(
        "SELECT sv.source_id, sv.model, sv.params_json, p.value_json, p.raw_conf"
        " FROM prediction p JOIN source_version sv ON sv.version_id = p.source_version_id"
        " ORDER BY p.id").fetchall()
    assert [r[0] for r in rows] == ["mirror:solo_mode", "mirror:solo_mode"]
    assert '"version":"3"' in rows[0][2] and '"version":"4"' in rows[1][2]
    assert rows[0][4] == 0.8
    [c1, c2] = sorted(engine.store.calls(), key=lambda c: c.id)
    assert c1.endpoint_type == "mirror:solo_mode" and c1.cost_usd is None and c1.estimated


def test_nothing_happens_without_the_engine(tmp_path):
    hooks.clear_engine()
    mirror("solo_mode", "gemma", 1, "i1", "s", "a", 0.8)   # no error, no store


def test_solo_set_llm_prediction_mirrors(engine):
    from potato.solo_mode.manager import LLMPrediction, SoloModeManager
    pred = LLMPrediction(instance_id="i9", schema_name="s", predicted_label="b",
                         confidence_score=0.7, uncertainty_score=0.3, prompt_version=2,
                         model_name="m")
    # Exercise the real method on a minimal manager.
    mgr = SoloModeManager.__new__(SoloModeManager)
    import threading
    mgr._lock = threading.RLock()
    mgr.predictions, mgr.llm_labeled_ids, mgr.confidence_history = {}, set(), {}
    mgr.set_llm_prediction("i9", "s", pred)
    assert engine.store.prediction_history("i9", "s")[0].value == "b"

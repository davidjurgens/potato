"""
Unit tests for automated judge calibration (corrections -> few-shot -> new
prompt version). Hermetic: human labels, instance text, and the judge are
stubbed, so no LLM or server is needed.
"""

import pytest

from potato.ai.judge import JudgePrediction, compute_prompt_version
from potato.server_utils import judge_alignment as ja
from potato.server_utils import judge_autocalibrate as ac


SCHEMA = {"annotation_type": "radio", "name": "verdict",
          "labels": [{"name": "pass"}, {"name": "fail"}], "description": "verdict"}
GOLD = {"i1": "pass", "i2": "pass", "i3": "fail", "i4": "fail"}
USERS = ["u1"]


@pytest.fixture
def cfg(tmp_path):
    return {
        "task_dir": str(tmp_path), "output_annotation_dir": str(tmp_path),
        "annotation_schemes": [SCHEMA],
        "judge_alignment": {"schemas": {"verdict": {"rubric": "rubric"}}},
    }


class _FakeItem:
    def __init__(self, text): self._t = text
    def get_text(self): return self._t


class _FakeISM:
    def get_item(self, iid): return _FakeItem(f"text for {iid}")


class _FakeJudge:
    """Judge that 'learns' from corrections: with few-shot it returns the gold
    label; without, it returns a fixed (often wrong) 'pass'. Records the shot ids
    it was given per instance so the leakage guard can be asserted."""

    def __init__(self, gold):
        self.gold = gold
        self.shot_ids_seen = {}

    def get_rubric(self, schema): return "rubric"

    def judge_instance(self, iid, schema, text, few_shot_examples=None, prompt_version=None):
        self.shot_ids_seen[iid] = [s["id"] for s in (few_shot_examples or [])]
        label = self.gold[iid] if few_shot_examples else "pass"
        return JudgePrediction(iid, schema["name"], label, 0.9, "r", "fake", prompt_version)


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(ja, "majority_human_label",
                        lambda iid, schema, users: GOLD.get(iid))
    monkeypatch.setattr(ja, "annotated_instance_ids",
                        lambda users, name: list(GOLD.keys()))
    monkeypatch.setattr("potato.item_state_management.get_item_state_manager",
                        lambda: _FakeISM())


def _seed_baseline(cfg):
    # Baseline judge predicts "pass" for everything -> wrong on i3, i4.
    for iid in GOLD:
        ja.save_prediction(cfg, JudgePrediction(iid, "verdict", "pass", 0.9, "r", "m", "v_base"))


def test_collect_corrections_finds_judge_mistakes(cfg, stub):
    _seed_baseline(cfg)
    corr = ac.collect_corrections(cfg, USERS, "v_base")
    ids = {c["id"] for c in corr["verdict"]}
    assert ids == {"i3", "i4"}          # the two the judge got wrong
    assert all(c["label"] == "fail" for c in corr["verdict"])  # human gold
    assert all("text for" in c["text"] for c in corr["verdict"])


def test_fingerprint_is_stable_and_set_sensitive():
    a = [{"id": "i3", "label": "fail"}, {"id": "i4", "label": "fail"}]
    assert ac._fingerprint(a) == ac._fingerprint(list(reversed(a)))  # order-independent
    assert ac._fingerprint(a) != ac._fingerprint([{"id": "i3", "label": "fail"}])


def test_autocalibrate_improves_kappa(cfg, stub):
    _seed_baseline(cfg)
    fake = _FakeJudge(GOLD)
    report = ac.autocalibrate(cfg, USERS, service=fake)

    res = report["schemas"]["verdict"]
    assert res["status"] == "calibrated"
    assert res["n_corrections"] == 2
    assert res["base_kappa"] is not None
    assert res["new_kappa"] == 1.0          # judge now matches gold everywhere
    assert res["improved"] is True
    assert report["improved_count"] == 1
    # A distinct new prompt version was created and persisted.
    assert res["new_version"] != "v_base"
    assert res["new_version"] in ja.load_predictions(cfg)


def test_leakage_guard_excludes_own_correction(cfg, stub):
    _seed_baseline(cfg)
    fake = _FakeJudge(GOLD)
    ac.autocalibrate(cfg, USERS, service=fake)
    # When judging i3 (a corrected instance), its own correction must be absent.
    assert "i3" not in fake.shot_ids_seen["i3"]
    assert "i4" not in fake.shot_ids_seen["i4"]
    # Non-corrected instances still see the corrections.
    assert set(fake.shot_ids_seen["i1"]) == {"i3", "i4"}


def test_skips_schema_without_corrections(cfg, stub, monkeypatch):
    # Baseline judge is always correct -> no corrections -> skipped.
    for iid in GOLD:
        ja.save_prediction(cfg, JudgePrediction(iid, "verdict", GOLD[iid], 0.9, "r", "m", "v_base"))
    report = ac.autocalibrate(cfg, USERS, service=_FakeJudge(GOLD))
    assert report["schemas"]["verdict"]["status"] == "skipped"
    assert report["improved_count"] == 0

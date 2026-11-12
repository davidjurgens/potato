"""
Crowd recruitment for engine requests: dry run by default, live only within
budgets.human_usd; and the auto-scale slot count people still need.
"""

from unittest.mock import patch

import pytest

from potato.labeling_engine.allocation.crowd import plan_crowd
from potato.labeling_engine.model import HumanRequest
from potato.labeling_engine.service import Engine
from potato.persistence import clear_db_cache

SCHEME = {"name": "s", "annotation_type": "radio", "labels": ["a", "b"]}


@pytest.fixture(autouse=True)
def _db():
    clear_db_cache()
    yield
    clear_db_cache()


def _engine(tmp_path, features=None, budgets=None, crowd=None):
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "c",
           "annotation_schemes": [SCHEME],
           "labeling_engine": {
               "enabled": True, "sources": [{"id": "fx", "kind": "fixture"}],
               "humans": {"pools": ["crowd"]},
               "crowd": crowd or {"study_id": "S1", "reward_usd": 1.0,
                                  "per_worker_quota": 10},
               "features": {"crowd_recruit": True} if features is None else features,
               "budgets": budgets or {}}}
    eng = Engine(cfg)
    eng.store.add_requests([HumanRequest(f"i{k}", "s", "calibration", 0.1, pool="crowd")
                            for k in range(35)])
    return eng


class FakeProlific:
    def __init__(self, taken=2, available=5, total_cost_cents=None):
        self.study = {"places_taken": taken, "total_available_places": available}
        self.total_cost_cents = total_cost_cents
        self.increased = []

    def get_study(self, sid):
        return dict(self.study)

    def calculate_cost(self, reward, places):
        return {"total_cost": self.total_cost_cents if self.total_cost_cents is not None
                else int(reward * places * 1.333)}

    def increase_places(self, sid, target):
        self.increased.append((sid, target))
        self.study["total_available_places"] = target


def test_dry_run_by_default_spends_nothing(tmp_path):
    eng = _engine(tmp_path)
    fake = FakeProlific()
    plan = plan_crowd(eng, client_factory=lambda: fake)
    assert plan["action"] == "dry_run" and plan["new_places"] == 4
    assert plan["estimated_cost_usd"] > 0
    assert fake.increased == []
    assert (eng.store.get_budget("human_usd") or type("B", (), {"spent": 0})).spent == 0


def test_live_spend_adds_places_within_budget(tmp_path):
    eng = _engine(tmp_path, features={"crowd_recruit": True, "crowd_live_spend": True},
                  budgets={"human_usd": 20})
    fake = FakeProlific(taken=2, available=5)
    plan = plan_crowd(eng, client_factory=lambda: fake)
    # 35 open / 10 per worker = 4 more than the 2 taken; 5 exist: add 1.
    assert plan["action"] == "increased" and fake.increased == [("S1", 6)]
    assert eng.store.get_budget("human_usd").spent == pytest.approx(plan["quoted_cost_usd"])


def test_live_spend_refuses_past_the_budget(tmp_path):
    eng = _engine(tmp_path, features={"crowd_recruit": True, "crowd_live_spend": True},
                  budgets={"human_usd": 1})
    fake = FakeProlific(taken=0, available=0, total_cost_cents=600)
    plan = plan_crowd(eng, client_factory=lambda: fake)
    assert plan["action"] == "refused_budget" and fake.increased == []
    assert "budgets.human_usd" in plan["note"]


def test_off_without_the_feature(tmp_path):
    eng = _engine(tmp_path, features={})
    assert plan_crowd(eng)["action"] == "off"


class _ISM:
    max_annotations_per_item = 2

    def __init__(self, caps, annotators):
        self.caps, self.annotators = caps, annotators

    def get_instance_ids(self):
        return list(self.caps)

    def _get_annotator_cap_for_item(self, iid):
        return self.caps[iid]

    def get_annotators_for_item(self, iid):
        return self.annotators.get(iid, set())


class _State:
    def __init__(self, origin=None):
        if origin:
            self.origin = origin


class _USM:
    def __init__(self, states):
        self.states = states

    def get_user_ids(self):
        return list(self.states)

    def get_user_state(self, uid):
        return self.states[uid]


def test_remaining_slots_use_item_caps_and_count_only_people():
    from potato.crowdsourcing.admin_api import _remaining_annotation_slots
    from potato.labeling_engine.integration.hooks import clear_engine
    clear_engine()
    ism = _ISM({"a": 2, "b": 5}, {"a": {"alice", "tool"}, "b": {"alice"}})
    usm = _USM({"alice": _State(), "tool": _State({"kind": "tool", "id": "tool"})})
    with patch("potato.item_state_management.get_item_state_manager", return_value=ism), \
            patch("potato.user_state_management.get_user_state_manager", return_value=usm):
        # a: cap 2, one person (the tool does not count) -> 1; b: cap 5 -> 4.
        assert _remaining_annotation_slots() == 5

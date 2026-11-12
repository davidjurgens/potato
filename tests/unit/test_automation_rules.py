"""Unit tests for automation rules, deterministic sampling, and the manager."""

import pytest

from potato.automation.rules import AutomationRule, deterministic_sample
from potato.automation.manager import AutomationManager, clear_automation_manager


# ---- matching ----

def test_rule_matches_condition():
    r = AutomationRule.from_dict({"name": "errs", "when": {"field": "status", "in": ["error"]}})
    assert r.matches({"status": "error"})
    assert not r.matches({"status": "ok"})


def test_rule_empty_when_matches_everything():
    r = AutomationRule.from_dict({"name": "all", "when": []})
    assert r.matches({"anything": 1})


def test_rule_multiple_conditions_are_anded():
    r = AutomationRule.from_dict({"name": "both", "when": [
        {"field": "status", "equals": "error"},
        {"field": "score", "lt": 0.5},
    ]})
    assert r.matches({"status": "error", "score": 0.2})
    assert not r.matches({"status": "error", "score": 0.9})


# ---- deterministic sampling ----

def test_sampling_is_deterministic():
    a = deterministic_sample("item-1", "rule-x")
    b = deterministic_sample("item-1", "rule-x")
    assert a == b
    assert 0.0 <= a < 1.0


def test_sampling_varies_by_item_and_rule():
    assert deterministic_sample("item-1", "r") != deterministic_sample("item-2", "r")
    assert deterministic_sample("item-1", "r1") != deterministic_sample("item-1", "r2")


def test_sample_rate_bounds():
    r0 = AutomationRule.from_dict({"name": "never", "sample_rate": 0.0})
    r1 = AutomationRule.from_dict({"name": "always", "sample_rate": 1.0})
    assert not r0.sampled("x")
    assert r1.sampled("x")


def test_sample_rate_partial_is_stable_and_proportional():
    r = AutomationRule.from_dict({"name": "half", "sample_rate": 0.5})
    kept = [r.sampled(f"item-{i}") for i in range(1000)]
    # Same decision every call (determinism)
    assert all(r.sampled(f"item-{i}") == kept[i] for i in range(1000))
    # Roughly half (hash uniformity); generous bounds to avoid flakiness
    frac = sum(kept) / len(kept)
    assert 0.4 < frac < 0.6


# ---- manager processing ----

@pytest.fixture
def manager():
    clear_automation_manager()
    cfg = {"automation": {"enabled": True, "rules": [
        {"name": "queue-errors", "when": {"field": "status", "equals": "error"},
         "actions": [{"type": "add_to_queue", "priority": 90}]},
    ]}}
    mgr = AutomationManager(cfg)
    yield mgr
    mgr.shutdown()


def test_manager_fires_matching_rule(manager, monkeypatch):
    # add_to_queue needs an item state manager; stub get_item.
    calls = {}

    class FakeItem:
        def __init__(self):
            self.metadata = {}

    class FakeISM:
        def __init__(self):
            self.item = FakeItem()
        def get_item(self, iid):
            calls["iid"] = iid
            return self.item

    fake = FakeISM()
    monkeypatch.setattr("potato.item_state_management.get_item_state_manager", lambda: fake)

    fired = manager.process_item("t1", {"status": "error"})
    assert fired == 1
    assert fake.item.metadata["triage_priority"] == 90.0
    assert manager.store.counters["items_processed"] == 1
    assert manager.store.counters["rules_fired"] == 1


def test_manager_no_match_no_fire(manager):
    fired = manager.process_item("t2", {"status": "ok"})
    assert fired == 0


def test_manager_status_shape(manager):
    st = manager.get_status()
    assert st["enabled"] is True
    assert st["rules"][0]["name"] == "queue-errors"
    assert "counters" in st

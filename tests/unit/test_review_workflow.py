"""
Unit tests for D4 reviewer routing + kanban workflow.

Covers: enrollment idempotence, state moves + transition audit,
assignment, board/my-queue queries, routing rules (first-match,
explicit assignee, round-robin least-loaded), startup/automation
integration guards, and state validation.
"""

import pytest

from potato.persistence import clear_db_cache, clear_migrations, register_migration
from potato.review_workflow import (
    _REVIEW_MIGRATION,
    STATES,
    assign_instance,
    board,
    enroll_instance,
    enroll_with_routing,
    get_review_item,
    move_instance,
    my_queue,
    review_enabled,
    route_instance,
    transitions_for,
)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(_REVIEW_MIGRATION)
    yield
    clear_db_cache()
    clear_migrations()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


class TestStore:
    def test_enroll_idempotent(self, td):
        assert enroll_instance(td, project="P", instance_id="i1") is True
        assert enroll_instance(td, project="P", instance_id="i1") is False
        item = get_review_item(td, "P", "i1")
        assert item["state"] == "pending"

    def test_enroll_rejects_unknown_state(self, td):
        with pytest.raises(ValueError):
            enroll_instance(td, project="P", instance_id="i1", state="bogus")

    def test_move_and_audit_trail(self, td):
        enroll_instance(td, project="P", instance_id="i1")
        item = move_instance(td, project="P", instance_id="i1",
                             state="in_review", actor="alice")
        assert item["state"] == "in_review"
        move_instance(td, project="P", instance_id="i1",
                      state="adjudication", actor="alice", note="disputed")
        item = get_review_item(td, "P", "i1")
        assert item["note"] == "disputed"
        trail = transitions_for(td, "P", "i1")
        assert [(t["from_state"], t["to_state"]) for t in trail] == [
            (None, "pending"), ("pending", "in_review"),
            ("in_review", "adjudication")]
        assert trail[1]["actor"] == "alice"

    def test_move_unknown_instance_raises(self, td):
        with pytest.raises(KeyError):
            move_instance(td, project="P", instance_id="nope",
                          state="done", actor="x")

    def test_assign_and_priority(self, td):
        enroll_instance(td, project="P", instance_id="i1")
        item = assign_instance(td, project="P", instance_id="i1",
                               assignee="bob", priority=7)
        assert item["assignee"] == "bob" and item["priority"] == 7
        item = assign_instance(td, project="P", instance_id="i1",
                               assignee=None)
        assert item["assignee"] is None
        assert item["priority"] == 7  # unchanged when not passed

    def test_board_grouping_and_order(self, td):
        enroll_instance(td, project="P", instance_id="low", priority=0)
        enroll_instance(td, project="P", instance_id="high", priority=9)
        enroll_instance(td, project="P", instance_id="reviewing",
                        state="in_review")
        b = board(td, "P")
        assert set(b.keys()) == set(STATES)
        assert [i["instance_id"] for i in b["pending"]] == ["high", "low"]
        assert [i["instance_id"] for i in b["in_review"]] == ["reviewing"]

    def test_my_queue_excludes_pending_and_done(self, td):
        for iid, state in [("a", "in_review"), ("b", "needs_second"),
                           ("c", "pending"), ("d", "done")]:
            enroll_instance(td, project="P", instance_id=iid, state=state,
                            assignee="alice")
        ids = [i["instance_id"] for i in my_queue(td, "P", "alice")]
        assert set(ids) == {"a", "b"}


class TestRouting:
    def _config(self, td, routing, reviewers=None):
        return {"task_dir": td, "annotation_task_name": "P",
                "review_workflow": {"enabled": True, "routing": routing,
                                    "reviewers": reviewers or []}}

    def test_no_rules_defaults_pending(self, td):
        r = route_instance(self._config(td, []), "i1", {"x": 1})
        assert r == {"state": "pending", "assignee": None, "priority": 0}

    def test_first_match_wins(self, td):
        routing = [
            {"when": [{"field": "status", "equals": "error"}],
             "state": "in_review", "assign_to": "alice", "priority": 10},
            {"when": [], "state": "in_review", "assign_to": "bob"},
        ]
        r = route_instance(self._config(td, routing), "i1",
                           {"status": "error"})
        assert r["assignee"] == "alice" and r["priority"] == 10
        r = route_instance(self._config(td, routing), "i2",
                           {"status": "ok"})
        assert r["assignee"] == "bob"

    def test_dotted_field_condition(self, td):
        routing = [{"when": [{"field": "metadata.score", "lt": 0.5}],
                    "state": "needs_second"}]
        r = route_instance(self._config(td, routing), "i1",
                           {"metadata": {"score": 0.2}})
        assert r["state"] == "needs_second"
        r = route_instance(self._config(td, routing), "i2",
                           {"metadata": {"score": 0.9}})
        assert r["state"] == "pending"

    def test_round_robin_least_loaded(self, td):
        config = self._config(
            td, [{"when": [], "round_robin": True}], ["alice", "bob"])
        # alice already has two open items; bob has none
        enroll_instance(td, project="P", instance_id="x1",
                        state="in_review", assignee="alice")
        enroll_instance(td, project="P", instance_id="x2",
                        state="in_review", assignee="alice")
        r = route_instance(config, "new", {})
        assert r["assignee"] == "bob"

    def test_enroll_with_routing(self, td):
        config = self._config(
            td, [{"when": [{"field": "status", "equals": "error"}],
                  "state": "in_review", "assign_to": "alice",
                  "priority": 5}])
        assert enroll_with_routing(config, "i1", {"status": "error"})
        item = get_review_item(td, "P", "i1")
        assert (item["state"], item["assignee"], item["priority"]) == (
            "in_review", "alice", 5)

    def test_invalid_state_in_rule_falls_back(self, td):
        routing = [{"when": [], "state": "not-a-state"}]
        r = route_instance(self._config(td, routing), "i1", {})
        assert r["state"] == "in_review"


class TestIntegrationGuards:
    def test_enabled_flag(self):
        assert not review_enabled({})
        assert not review_enabled({"review_workflow": {}})
        assert review_enabled({"review_workflow": {"enabled": True}})

    def test_automation_action_registered_as_fast(self):
        from potato.automation.actions import FAST_ACTIONS, _EXECUTORS
        assert "enroll_review" in FAST_ACTIONS
        assert "enroll_review" in _EXECUTORS

    def test_automation_action_skips_when_disabled(self):
        from potato.automation.actions import execute_action
        from unittest.mock import patch
        with patch("potato.server_utils.config_module.config", {}):
            out = execute_action({"type": "enroll_review"},
                                 {"item_id": "x", "item_data": {}})
        assert out["status"] == "skipped"

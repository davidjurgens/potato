"""Between-subjects condition assignment (potato/server_utils/experiment_conditions.py)."""

import threading

import pytest

from potato.phase import UserPhase
from potato.server_utils.config_module import ConfigValidationError
from potato.server_utils.experiment_conditions import (
    ConditionAssigner,
    build_cells,
    validate_conditions_config,
)
from potato.user_state_management import InMemoryUserState


def _cfg(**spec):
    base = {"factors": {"feedback": ["none", "immediate"], "font": ["serif", "sans"]}}
    base.update(spec)
    return {"conditions": base}


def _users(n, prefix="p"):
    return [InMemoryUserState(f"{prefix}{i}", -1) for i in range(n)]


class TestCells:
    def test_full_factorial(self):
        cells = build_cells(_cfg()["conditions"])
        assert len(cells) == 4
        assert {(c["feedback"], c["font"]) for c in cells} == {
            ("none", "serif"), ("none", "sans"), ("immediate", "serif"), ("immediate", "sans")}

    def test_explicit_subset(self):
        cells = build_cells(_cfg(cells=[{"feedback": "none", "font": "serif"},
                                        {"feedback": "immediate", "font": "sans", "weight": 2}])
                            ["conditions"])
        assert [(c["feedback"], c["font"], c["weight"]) for c in cells] == [
            ("none", "serif", 1.0), ("immediate", "sans", 2.0)]


class TestBalanced:
    def test_sequential_balance(self):
        a = ConditionAssigner(_cfg())
        for us in _users(200):
            a.ensure(us)
        counts = a.counts()
        assert sum(counts) == 200
        assert max(counts) - min(counts) <= 1

    def test_threaded_balance(self):
        a = ConditionAssigner(_cfg())
        users = _users(50, "t")
        threads = [threading.Thread(target=a.ensure, args=(u,)) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        counts = a.counts()
        assert sum(counts) == 50
        assert max(counts) - min(counts) <= 1
        ordinals = sorted(u.flow_record["condition_ordinal"] for u in users)
        assert ordinals == list(range(50))

    def test_weights(self):
        a = ConditionAssigner(_cfg(cells=[{"feedback": "none", "font": "serif", "weight": 1},
                                          {"feedback": "immediate", "font": "serif", "weight": 3}]))
        for us in _users(40):
            a.ensure(us)
        assert a.counts() == [10, 30]

    def test_idempotent(self):
        a = ConditionAssigner(_cfg())
        us = InMemoryUserState("same", -1)
        first = dict(a.ensure(us))
        for _ in range(5):
            assert a.ensure(us) == first
        assert sum(a.counts()) == 1

    def test_max_per_cell_skips_full_cells(self):
        a = ConditionAssigner(_cfg(max_per_cell=2, cells=[
            {"feedback": "none", "font": "serif", "weight": 1},
            {"feedback": "immediate", "font": "serif", "weight": 100}]))
        for us in _users(4):
            a.ensure(us)
        assert a.counts() == [2, 2]


class TestOtherMethods:
    def test_random_is_deterministic_per_user(self):
        a1 = ConditionAssigner(_cfg(assignment="random"))
        a2 = ConditionAssigner(_cfg(assignment="random"))
        for u1, u2 in zip(_users(20), _users(20)):
            assert a1.ensure(u1) == a2.ensure(u2)

    def test_round_robin(self):
        a = ConditionAssigner(_cfg(assignment="round_robin"))
        users = _users(8)
        for us in users:
            a.ensure(us)
        assert [u.flow_record["condition_cell"] for u in users] == [0, 1, 2, 3, 0, 1, 2, 3]


class TestRestart:
    def test_rebuild_from_users_keeps_balancing(self):
        a = ConditionAssigner(_cfg())
        first = _users(6, "before")
        for us in first:
            a.ensure(us)
        restarted = ConditionAssigner(_cfg())
        restarted.rebuild_from_users(first)
        assert restarted.counts() == a.counts()
        later = _users(2, "after")
        for us in later:
            restarted.ensure(us)
        counts = restarted.counts()
        assert max(counts) - min(counts) == 0
        assert {u.flow_record["condition_ordinal"] for u in later} == {6, 7}


class TestBalanceOnCompleted:
    def test_dropouts_are_replaced(self):
        a = ConditionAssigner(_cfg(balance_on="completed", cells=[
            {"feedback": "none", "font": "serif"},
            {"feedback": "immediate", "font": "serif"}]))
        done = InMemoryUserState("finisher", -1)
        a.ensure(done, [])
        done.advance_to_phase(UserPhase.DONE, None)
        dropout = InMemoryUserState("dropout", -1)
        a.ensure(dropout, [done])
        # The dropout never finished, so the next arrival goes to its cell.
        nxt = InMemoryUserState("next", -1)
        a.ensure(nxt, [done, dropout])
        assert nxt.flow_record["condition_cell"] == dropout.flow_record["condition_cell"]
        assert done.flow_record["condition_cell"] != dropout.flow_record["condition_cell"]


class TestValidation:
    def test_valid(self):
        validate_conditions_config(_cfg(assignment="random", max_per_cell=10))

    @pytest.mark.parametrize("spec,match", [
        ({"factors": {}}, "factors"),
        ({"factors": {"f": ["only"]}}, "at least two"),
        ({"factors": {"f": ["a", "a"]}}, "distinct"),
        ({"factors": {"f": [True, False]}}, "true/false"),
        ({"factors": {"bad name": ["a", "b"]}}, "identifier"),
        ({"factors": {"f": ["a", "b"]}, "assignment": "latin"}, "assignment"),
        ({"factors": {"f": ["a", "b"]}, "balance_on": "finished"}, "balance_on"),
        ({"factors": {"f": ["a", "b"]}, "max_per_cell": 0}, "max_per_cell"),
        ({"factors": {"f": ["a", "b"]}, "cells": [{"f": "c"}]}, "not a declared level"),
        ({"factors": {"f": ["a", "b"]}, "cells": [{"f": "a"}, {"f": "a"}]}, "repeats"),
        ({"factors": {"f": ["a", "b"]}, "cells": [{"f": "a", "weight": -1}]}, "weight"),
        ({"factors": {"f": ["a", "b"]}, "seed": 3}, "unknown key"),
    ])
    def test_refused(self, spec, match):
        with pytest.raises(ConfigValidationError, match=match):
            validate_conditions_config({"conditions": spec})

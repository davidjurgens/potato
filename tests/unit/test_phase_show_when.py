"""Page-level show_when / exit_when and counterbalanced page order.

These drive UserStateManager.advance_phase / retreat_phase with a real
InMemoryUserState, so the skip, screen-out and ordering decisions are the
ones a participant would get.
"""

import json
import os

from potato.item_state_management import Label
from potato.phase import UserPhase
from potato.server_utils import phase_flow
from potato.user_state_management import InMemoryUserState, UserStateManager
from tests.helpers.test_utils import create_test_directory


def _usm(phases, pages, **extra):
    cfg = {
        "output_annotation_dir": create_test_directory("phase_show_when_states"),
        "annotation_task_name": "Flow Test",
        "annotation_schemes": [],
        "phases": phases,
    }
    cfg.update(extra)
    usm = UserStateManager(cfg)
    usm.phase_type_to_name_to_page = pages
    return usm


def _user(usm, user_id="u1", at=(UserPhase.PRESTUDY, "screener")):
    us = InMemoryUserState(user_id, -1)
    us.advance_to_phase(*at)
    usm.user_to_annotation_state[user_id] = us
    return us


def _answer(us, phase, page, schema, value):
    us.phase_to_page_to_label_to_value[phase][page][Label(schema, value)] = value


SMOKER_PHASES = {
    "order": ["screener", "smoking", "general", "annotation", "exit"],
    "screener": {"type": "prestudy", "file": "s.json"},
    "smoking": {
        "type": "prestudy", "file": "smoking.json",
        "show_when": [{"schema": "smoker", "operator": "equals", "value": "Yes"}],
    },
    "general": {"type": "prestudy", "file": "g.json"},
    "exit": {"type": "poststudy", "file": "e.json"},
}
SMOKER_PAGES = {
    UserPhase.PRESTUDY: {"screener": "a.html", "smoking": "b.html", "general": "c.html"},
    UserPhase.POSTSTUDY: {"exit": "e.html"},
}


class TestShowWhen:
    def test_page_shown_when_condition_holds(self):
        usm = _usm(SMOKER_PHASES, SMOKER_PAGES)
        us = _user(usm)
        _answer(us, UserPhase.PRESTUDY, "screener", "smoker", "Yes")
        usm.advance_phase("u1")
        assert us.get_current_phase_and_page() == (UserPhase.PRESTUDY, "smoking")
        assert not us.flow_record.get("skipped_pages")

    def test_page_skipped_when_condition_fails(self):
        usm = _usm(SMOKER_PHASES, SMOKER_PAGES)
        us = _user(usm)
        _answer(us, UserPhase.PRESTUDY, "screener", "smoker", "No")
        usm.advance_phase("u1")
        assert us.get_current_phase_and_page() == (UserPhase.PRESTUDY, "general")
        assert [s["page"] for s in us.flow_record["skipped_pages"]] == ["smoking"]

    def test_unanswered_condition_skips(self):
        usm = _usm(SMOKER_PHASES, SMOKER_PAGES)
        us = _user(usm)
        usm.advance_phase("u1")
        assert us.get_current_phase_and_page() == (UserPhase.PRESTUDY, "general")

    def test_skip_last_pre_annotation_page_reaches_annotation(self):
        phases = dict(SMOKER_PHASES)
        phases["order"] = ["screener", "smoking", "annotation", "exit"]
        phases.pop("general")
        pages = {UserPhase.PRESTUDY: {"screener": "a.html", "smoking": "b.html"},
                 UserPhase.POSTSTUDY: {"exit": "e.html"}}
        usm = _usm(phases, pages)
        us = _user(usm)
        _answer(us, UserPhase.PRESTUDY, "screener", "smoker", "No")
        usm.advance_phase("u1")
        assert us.get_current_phase_and_page() == (UserPhase.ANNOTATION, None)

    def test_skip_run_of_pages_across_phases(self):
        phases = {
            "order": ["screener", "a", "b", "annotation"],
            "screener": {"type": "prestudy", "file": "s.json"},
            "a": {"type": "prestudy", "file": "a.json",
                  "show_when": [{"schema": "x", "operator": "equals", "value": "go"}]},
            "b": {"type": "prestudy", "file": "b.json",
                  "show_when": [{"schema": "x", "operator": "equals", "value": "go"}]},
        }
        pages = {UserPhase.PRESTUDY: {"screener": "s.html", "a": "a.html", "b": "b.html"}}
        usm = _usm(phases, pages)
        us = _user(usm)
        usm.advance_phase("u1")
        assert us.get_current_phase_and_page() == (UserPhase.ANNOTATION, None)
        assert [s["page"] for s in us.flow_record["skipped_pages"]] == ["a", "b"]

    def test_back_navigation_passes_over_hidden_page(self):
        usm = _usm(SMOKER_PHASES, SMOKER_PAGES)
        us = _user(usm, at=(UserPhase.PRESTUDY, "general"))
        _answer(us, UserPhase.PRESTUDY, "screener", "smoker", "No")
        assert usm.get_prev_user_phase_page("u1") == (UserPhase.PRESTUDY, "screener")
        assert usm.retreat_phase("u1")
        assert us.get_current_phase_and_page() == (UserPhase.PRESTUDY, "screener")

    def test_back_navigation_returns_to_visible_page(self):
        usm = _usm(SMOKER_PHASES, SMOKER_PAGES)
        us = _user(usm, at=(UserPhase.PRESTUDY, "general"))
        _answer(us, UserPhase.PRESTUDY, "screener", "smoker", "Yes")
        assert usm.get_prev_user_phase_page("u1") == (UserPhase.PRESTUDY, "smoking")

    def test_condition_reference(self):
        phases = {
            "order": ["intro", "feedback_page", "annotation"],
            "intro": {"type": "instructions", "file": "i.json"},
            "feedback_page": {
                "type": "instructions", "file": "f.json",
                "show_when": [{"schema": "condition.feedback", "operator": "equals",
                               "value": "immediate"}],
            },
        }
        pages = {UserPhase.INSTRUCTIONS: {"intro": "i.html", "feedback_page": "f.html"}}
        usm = _usm(phases, pages)
        shown = _user(usm, "shown", at=(UserPhase.INSTRUCTIONS, "intro"))
        shown.flow_record["conditions"] = {"feedback": "immediate"}
        hidden = _user(usm, "hidden", at=(UserPhase.INSTRUCTIONS, "intro"))
        hidden.flow_record["conditions"] = {"feedback": "none"}
        usm.advance_phase("shown")
        usm.advance_phase("hidden")
        assert shown.get_current_phase_and_page() == (UserPhase.INSTRUCTIONS, "feedback_page")
        assert hidden.get_current_phase_and_page() == (UserPhase.ANNOTATION, None)

    def test_answer_from_earlier_phase(self):
        phases = {
            "order": ["screener", "annotation", "followup", "exit"],
            "screener": {"type": "prestudy", "file": "s.json"},
            "followup": {"type": "poststudy", "file": "f.json",
                         "show_when": [{"schema": "smoker", "operator": "equals",
                                        "value": "Yes"}]},
            "exit": {"type": "poststudy", "file": "e.json"},
        }
        pages = {UserPhase.PRESTUDY: {"screener": "s.html"},
                 UserPhase.POSTSTUDY: {"followup": "f.html", "exit": "e.html"}}
        usm = _usm(phases, pages)
        us = _user(usm, at=(UserPhase.ANNOTATION, None))
        _answer(us, UserPhase.PRESTUDY, "screener", "smoker", "No")
        usm.advance_phase("u1")
        assert us.get_current_phase_and_page() == (UserPhase.POSTSTUDY, "exit")

    def test_no_rules_matches_old_behaviour(self):
        phases = {k: {kk: vv for kk, vv in v.items() if kk != "show_when"}
                  if isinstance(v, dict) else v for k, v in SMOKER_PHASES.items()}
        usm = _usm(phases, SMOKER_PAGES)
        us = _user(usm)
        seen = []
        while us.get_current_phase_and_page()[0] != UserPhase.DONE:
            usm.advance_phase("u1")
            seen.append(us.get_current_phase_and_page())
        assert seen == [
            (UserPhase.PRESTUDY, "smoking"), (UserPhase.PRESTUDY, "general"),
            (UserPhase.ANNOTATION, None), (UserPhase.POSTSTUDY, "exit"),
            (UserPhase.DONE, None),
        ]


class TestExitWhen:
    PHASES = {
        "order": ["screener", "general", "annotation"],
        "screener": {
            "type": "prestudy", "file": "s.json",
            "exit_when": {
                "show_when": [{"schema": "age", "operator": "lt", "value": 18}],
                "message": "This study is for adults only.",
            },
        },
        "general": {"type": "prestudy", "file": "g.json"},
    }
    PAGES = {UserPhase.PRESTUDY: {"screener": "s.html", "general": "g.html"}}

    def test_screen_out_goes_to_done(self):
        usm = _usm(self.PHASES, self.PAGES)
        us = _user(usm)
        us.phase_to_page_to_label_to_value[UserPhase.PRESTUDY]["screener"][
            Label("age", "age")] = "16"
        usm.advance_phase("u1")
        assert us.get_current_phase_and_page() == (UserPhase.DONE, None)
        assert us.flow_record["screened_out"]["page"] == "screener"
        assert us.flow_record["screened_out"]["message"] == "This study is for adults only."
        assert us.get_prestudy_status() is False

    def test_screened_out_cannot_go_back(self):
        """Audit 94, E1: Previous from DONE walked a screened-out participant
        back into the study."""
        usm = _usm(self.PHASES, self.PAGES, allow_phase_back_navigation=True)
        us = _user(usm)
        us.phase_to_page_to_label_to_value[UserPhase.PRESTUDY]["screener"][
            Label("age", "age")] = "16"
        usm.advance_phase("u1")
        assert us.get_current_phase_and_page() == (UserPhase.DONE, None)
        assert usm.get_prev_user_phase_page("u1") == (UserPhase.DONE, None)
        assert not usm.retreat_phase("u1")
        assert not usm.can_user_go_back("u1")
        assert us.get_current_phase_and_page() == (UserPhase.DONE, None)

    def test_eligible_participant_continues(self):
        usm = _usm(self.PHASES, self.PAGES)
        us = _user(usm)
        us.phase_to_page_to_label_to_value[UserPhase.PRESTUDY]["screener"][
            Label("age", "age")] = "30"
        usm.advance_phase("u1")
        assert us.get_current_phase_and_page() == (UserPhase.PRESTUDY, "general")
        assert "screened_out" not in us.flow_record
        assert us.get_prestudy_status() is None


class TestCounterbalance:
    PAGES = {UserPhase.INSTRUCTIONS: {"intro": "i.html", "block_a": "a.html",
                                      "block_b": "b.html", "block_c": "c.html"}}

    def _phases(self, method):
        return {
            "order": ["intro", "block_a", "block_b", "block_c", "annotation"],
            "intro": {"type": "instructions", "file": "i.json"},
            "block_a": {"type": "instructions", "file": "a.json"},
            "block_b": {"type": "instructions", "file": "b.json"},
            "block_c": {"type": "instructions", "file": "c.json"},
            "counterbalance": [{"pages": ["block_a", "block_b", "block_c"],
                                "method": method}],
        }

    def _walk(self, usm, user_id):
        us = _user(usm, user_id, at=(UserPhase.INSTRUCTIONS, "intro"))
        seen = []
        while us.get_current_phase_and_page()[0] == UserPhase.INSTRUCTIONS:
            usm.advance_phase(user_id)
            if us.get_current_phase_and_page()[0] == UserPhase.INSTRUCTIONS:
                seen.append(us.get_current_phase_and_page()[1])
        return us, seen

    def test_random_orders_differ_across_users_and_are_stable(self):
        usm = _usm(self._phases("random"), self.PAGES)
        orders = set()
        for i in range(20):
            us, seen = self._walk(usm, f"user{i}")
            assert sorted(seen) == ["block_a", "block_b", "block_c"]
            assert us.flow_record["page_orders"]["group_0"] == seen
            orders.add(tuple(seen))
        assert len(orders) > 1
        # The same participant gets the same order again.
        again = _usm(self._phases("random"), self.PAGES)
        _, seen_again = self._walk(again, "user3")
        _, seen_first = self._walk(_usm(self._phases("random"), self.PAGES), "user3")
        assert seen_again == seen_first

    def test_recorded_order_survives_reload(self):
        usm = _usm(self._phases("random"), self.PAGES)
        us, seen = self._walk(usm, "reload_me")
        restored = InMemoryUserState("reload_me", -1)
        restored.flow_record = json.loads(json.dumps(us.flow_record))
        assert restored.flow_record["page_orders"]["group_0"] == seen

    def test_latin_square_follows_arrival_order(self):
        """Without conditions, participant k gets row k (audit 94, E3)."""
        usm = _usm(self._phases("latin_square"), self.PAGES)
        rows = phase_flow.williams_rows(3)
        pages = ["block_a", "block_b", "block_c"]
        for k in range(len(rows) * 2):
            us, seen = self._walk(usm, f"arrival{k}")
            assert us.flow_record["latin_ordinal"] == k
            assert seen == [pages[i] for i in rows[k % len(rows)]]

    def test_latin_counter_survives_restart(self):
        usm = _usm(self._phases("latin_square"), self.PAGES)
        for k in range(3):
            self._walk(usm, f"before{k}")
        restarted = _usm(self._phases("latin_square"), self.PAGES)
        restarted.user_to_annotation_state.update(usm.user_to_annotation_state)
        restarted.rebuild_latin_counter()
        us, _ = self._walk(restarted, "after")
        assert us.flow_record["latin_ordinal"] == 3

    def test_every_cell_walks_the_whole_square(self):
        """Audit 94, E2: with round-robin over two cells and a two-page
        square, indexing by the global arrival number gave each cell one row
        forever, confounding block order with condition."""
        phases = self._phases("latin_square")
        phases["counterbalance"] = [{"pages": ["block_a", "block_b"], "method": "latin_square"}]
        phases["order"] = ["intro", "block_a", "block_b", "annotation"]
        pages = {UserPhase.INSTRUCTIONS: {"intro": "i.html", "block_a": "a.html",
                                          "block_b": "b.html"}}
        usm = _usm(phases, pages, conditions={
            "factors": {"arm": ["x", "y"]}, "assignment": "round_robin"})
        orders_by_cell = {}
        for k in range(8):
            us = InMemoryUserState(f"rr{k}", -1)
            usm.user_to_annotation_state[us.user_id] = us
            usm.ensure_conditions(us)
            us.advance_to_phase(UserPhase.INSTRUCTIONS, "intro")
            seen = []
            while True:
                usm.advance_phase(us.user_id)
                if us.get_current_phase_and_page()[0] != UserPhase.INSTRUCTIONS:
                    break
                seen.append(us.get_current_phase_and_page()[1])
            orders_by_cell.setdefault(us.flow_record["conditions"]["arm"], set()).add(tuple(seen))
        assert orders_by_cell["x"] == {("block_a", "block_b"), ("block_b", "block_a")}
        assert orders_by_cell["y"] == {("block_a", "block_b"), ("block_b", "block_a")}


class TestWilliams:
    def test_even_square_is_carryover_balanced(self):
        for n in (2, 4, 6):
            rows = phase_flow.williams_rows(n)
            assert len(rows) == n
            for pos in range(n):
                assert sorted(r[pos] for r in rows) == list(range(n))
            pairs = [(r[i], r[i + 1]) for r in rows for i in range(n - 1)]
            assert len(pairs) == len(set(pairs)) == n * (n - 1)

    def test_odd_square_doubles_and_balances_positions(self):
        for n in (3, 5):
            rows = phase_flow.williams_rows(n)
            assert len(rows) == 2 * n
            for pos in range(n):
                counts = [r[pos] for r in rows]
                assert all(counts.count(k) == 2 for k in range(n))
            pairs = [(r[i], r[i + 1]) for r in rows for i in range(n - 1)]
            assert all(pairs.count(p) == 2 for p in set(pairs))
            assert len(set(pairs)) == n * (n - 1)


class TestFlowRecordPersistence:
    def test_round_trip(self):
        us = InMemoryUserState("persist", -1)
        us.flow_record = {"conditions": {"f": "a"}, "condition_ordinal": 3,
                          "skipped_pages": [{"phase": "prestudy", "page": "x", "at": 1.0}]}
        us.instance_id_to_trial = {"i1": {"outcome": "timeout"}}
        us.prestudy_passed = False
        d = us.to_json()
        user_dir = create_test_directory("flow_record_round_trip")
        with open(os.path.join(user_dir, "user_state.json"), "w") as f:
            json.dump(d, f)
        loaded = InMemoryUserState.load(user_dir)
        assert loaded.flow_record == us.flow_record
        assert loaded.instance_id_to_trial == us.instance_id_to_trial
        assert loaded.prestudy_passed is False

    def test_old_state_without_keys_loads(self):
        us = InMemoryUserState("old", -1)
        d = us.to_json()
        for key in ("flow_record", "instance_id_to_trial", "prestudy_passed"):
            d.pop(key)
        user_dir = create_test_directory("flow_record_old_state")
        with open(os.path.join(user_dir, "user_state.json"), "w") as f:
            json.dump(d, f)
        loaded = InMemoryUserState.load(user_dir)
        assert loaded.flow_record == {}
        assert loaded.instance_id_to_trial == {}
        assert loaded.prestudy_passed is None

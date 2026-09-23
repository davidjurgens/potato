"""Guards for ``potato/annotator_origin.py``.

The two rules worth pinning are the ones every other consumer will lean on:
an absent origin is a person, and a present-but-unreadable origin is a machine.
The first is what makes the field safe to add to a running study; the second is
what keeps a corrupted state out of human-human agreement.
"""

import json
import os

import pytest

from potato.annotator_origin import (
    HUMAN,
    LLM,
    PAIR_HUMAN_HUMAN,
    PAIR_HUMAN_MACHINE,
    PAIR_MACHINE_MACHINE,
    TOOL,
    MachineAnnotator,
    describe,
    has_machine_participants,
    is_human,
    is_machine,
    kind_of,
    origin_of,
    pair_kind,
    parse_machine_annotators,
    partition,
    stamp_user_state,
    summarize,
)


class _FakeState:
    """Stands in for a UserState. Only `origin` and `get_user_id` are read."""

    def __init__(self, user_id, origin=None):
        self.user_id = user_id
        if origin is not None:
            self.origin = origin

    def get_user_id(self):
        return self.user_id


PROKKA = {
    "id": "prokka",
    "kind": "tool",
    "tool": "prokka",
    "version": "1.14.6",
    "database_version": "2023-05",
    "run_date": "2024-11-03",
}


def _config(*annotators, enabled=True):
    return {"machine_annotators": {"enabled": enabled, "annotators": list(annotators)}}


class TestAbsentMeansHuman:
    """The migration contract. Break this and every existing study changes."""

    def test_state_with_no_origin_attribute_is_human(self):
        assert is_human(_FakeState("alice"))
        assert origin_of(_FakeState("alice")) == {"kind": HUMAN}

    def test_empty_origin_is_human(self):
        assert is_human(_FakeState("alice", {}))

    def test_none_is_human(self):
        assert is_human(None)

    def test_kind_of_reports_the_partition_not_the_subkind(self):
        assert kind_of(_FakeState("alice")) == HUMAN
        assert kind_of(_FakeState("p", {"kind": TOOL, "id": "prokka"})) == "machine"
        assert kind_of(_FakeState("g", {"kind": LLM, "id": "gpt"})) == "machine"


class TestUnreadableMeansMachine:
    """Conservative direction: withhold rows rather than corrupt a number."""

    def test_origin_without_a_kind_is_machine(self):
        assert is_machine(_FakeState("x", {"id": "something"}))

    def test_origin_with_a_blank_kind_is_machine(self):
        assert is_machine(_FakeState("x", {"kind": "   ", "id": "s"}))

    def test_non_mapping_origin_is_machine(self):
        assert is_machine(_FakeState("x", ["not", "a", "mapping"]))

    def test_malformed_is_flagged_so_a_reader_can_tell(self):
        assert origin_of(_FakeState("x", {"id": "s"})).get("malformed") is True

    def test_an_unknown_kind_is_still_a_machine(self):
        # Not human, so it must not land in the human partition.
        assert is_machine(_FakeState("x", {"kind": "robot", "id": "r"}))


class TestRoster:
    def test_parses_a_declaration(self):
        roster = parse_machine_annotators(_config(PROKKA))
        assert set(roster) == {"prokka"}
        assert roster["prokka"].version == "1.14.6"
        assert roster["prokka"].database_version == "2023-05"

    def test_disabled_block_yields_no_roster(self):
        assert parse_machine_annotators(_config(PROKKA, enabled=False)) == {}

    def test_absent_block_yields_no_roster(self):
        assert parse_machine_annotators({}) == {}
        assert parse_machine_annotators(None) == {}

    def test_entry_without_an_id_is_skipped(self):
        roster = parse_machine_annotators(_config({"kind": "tool"}, PROKKA))
        assert set(roster) == {"prokka"}

    def test_duplicate_id_keeps_the_first(self):
        second = dict(PROKKA, version="9.9.9")
        roster = parse_machine_annotators(_config(PROKKA, second))
        assert roster["prokka"].version == "1.14.6"

    def test_kind_defaults_to_tool(self):
        roster = parse_machine_annotators(_config({"id": "x"}))
        assert roster["x"].kind == TOOL

    def test_non_list_annotators_is_survivable(self):
        assert parse_machine_annotators(
            {"machine_annotators": {"enabled": True, "annotators": "prokka"}}
        ) == {}


class TestStamping:
    def test_stamps_a_declared_participant(self):
        roster = parse_machine_annotators(_config(PROKKA))
        state = _FakeState("prokka")
        assert stamp_user_state(state, roster) is True
        assert is_machine(state)
        assert state.origin["version"] == "1.14.6"
        assert state.origin["declared_in"] == "config"

    def test_leaves_an_undeclared_participant_alone(self):
        roster = parse_machine_annotators(_config(PROKKA))
        state = _FakeState("alice")
        assert stamp_user_state(state, roster) is False
        assert is_human(state)

    def test_empty_roster_stamps_nothing(self):
        state = _FakeState("prokka")
        assert stamp_user_state(state, {}) is False
        assert is_human(state)

    def test_restamping_is_idempotent(self):
        roster = parse_machine_annotators(_config(PROKKA))
        state = _FakeState("prokka")
        stamp_user_state(state, roster)
        first = dict(state.origin)
        assert stamp_user_state(state, roster) is False
        assert state.origin == first

    def test_a_changed_declaration_keeps_the_original_recorded_at(self):
        """recorded_at means when this was first seen, not when we restarted."""
        roster = parse_machine_annotators(_config(PROKKA))
        state = _FakeState("prokka")
        stamp_user_state(state, roster)
        original_time = state.origin["recorded_at"]

        newer = parse_machine_annotators(_config(dict(PROKKA, version="1.15.0")))
        assert stamp_user_state(state, newer) is True
        assert state.origin["version"] == "1.15.0"
        assert state.origin["recorded_at"] == original_time


class TestPartitioning:
    def _states(self):
        return {
            "alice": _FakeState("alice"),
            "bob": _FakeState("bob"),
            "prokka": _FakeState("prokka", {"kind": TOOL, "id": "prokka"}),
            "bakta": _FakeState("bakta", {"kind": TOOL, "id": "bakta"}),
        }

    def test_splits_by_kind(self):
        groups = partition(self._states())
        assert set(groups[HUMAN]) == {"alice", "bob"}
        assert set(groups["machine"]) == {"prokka", "bakta"}

    def test_sub_dicts_are_the_same_shape_as_the_input(self):
        # This is what lets the IAA dispatcher hand a partition to gatherers
        # that know nothing about origin.
        groups = partition(self._states())
        assert groups[HUMAN]["alice"].get_user_id() == "alice"

    def test_all_human_still_partitions(self):
        groups = partition({"a": _FakeState("a"), "b": _FakeState("b")})
        assert len(groups[HUMAN]) == 2
        assert groups["machine"] == {}

    def test_empty_input(self):
        groups = partition({})
        assert groups[HUMAN] == {} and groups["machine"] == {}

    def test_has_machine_participants(self):
        assert has_machine_participants(self._states()) is True
        assert has_machine_participants({"a": _FakeState("a")}) is False

    def test_summarize_counts_and_names(self):
        summary = summarize(self._states())
        assert summary["n_human"] == 2
        assert summary["n_machine"] == 2
        assert summary["machine"] == ["bakta", "prokka"]


class TestPairKind:
    def test_three_way_taxonomy(self):
        human = _FakeState("alice")
        machine = _FakeState("prokka", {"kind": TOOL, "id": "prokka"})
        other = _FakeState("bakta", {"kind": TOOL, "id": "bakta"})
        assert pair_kind(human, _FakeState("bob")) == PAIR_HUMAN_HUMAN
        assert pair_kind(machine, other) == PAIR_MACHINE_MACHINE
        assert pair_kind(human, machine) == PAIR_HUMAN_MACHINE
        assert pair_kind(machine, human) == PAIR_HUMAN_MACHINE


class TestDescribe:
    def test_human(self):
        assert describe(_FakeState("alice")) == "human"

    def test_machine_carries_version_and_database(self):
        label = describe(_FakeState("p", {
            "kind": TOOL, "id": "prokka", "version": "1.14.6",
            "database_version": "2023-05",
        }))
        assert "prokka" in label and "1.14.6" in label and "2023-05" in label


class TestConfigValidation:
    """The load-time guard.

    A declaration that never matches a participant is the failure that arrives
    silently: the study runs, the machine annotates, and its rows are counted
    as a person's because the id did not line up.
    """

    def _validate(self, block):
        from potato.server_utils.config_module import (
            validate_machine_annotators_config,
        )

        validate_machine_annotators_config({"machine_annotators": block})

    def test_absent_block_is_fine(self):
        from potato.server_utils.config_module import (
            validate_machine_annotators_config,
        )

        validate_machine_annotators_config({})

    def test_disabled_block_is_not_validated(self):
        # Nothing reads it, so its shape does not matter.
        self._validate({"enabled": False, "annotators": "nonsense"})

    def test_valid_block_passes(self):
        self._validate({"enabled": True, "annotators": [PROKKA]})

    def test_enabled_with_no_annotators_is_refused(self):
        from potato.server_utils.config_module import ConfigValidationError

        with pytest.raises(ConfigValidationError):
            self._validate({"enabled": True})

    def test_entry_without_an_id_is_refused(self):
        from potato.server_utils.config_module import ConfigValidationError

        with pytest.raises(ConfigValidationError):
            self._validate({"enabled": True, "annotators": [{"kind": "tool"}]})

    def test_duplicate_ids_are_refused(self):
        from potato.server_utils.config_module import ConfigValidationError

        with pytest.raises(ConfigValidationError):
            self._validate(
                {"enabled": True, "annotators": [{"id": "prokka"}, {"id": "prokka"}]}
            )

    def test_non_list_annotators_is_refused(self):
        from potato.server_utils.config_module import ConfigValidationError

        with pytest.raises(ConfigValidationError):
            self._validate({"enabled": True, "annotators": "prokka"})

    def test_unknown_kind_is_not_an_error(self):
        """Not being human is the only thing correctness depends on."""
        self._validate({"enabled": True, "annotators": [{"id": "x", "kind": "robot"}]})


class TestOriginSurvivesTheUserState:
    """The field has to round-trip both serializers, not just exist in memory."""

    def test_in_memory_state_starts_human_and_serializes_origin(self):
        from potato.user_state_management import InMemoryUserState

        state = InMemoryUserState("alice")
        assert state.origin == {}
        assert state.to_json()["origin"] == {}
        assert is_human(state)

    def test_round_trips_through_disk(self, tmp_path):
        from potato.user_state_management import InMemoryUserState

        state = InMemoryUserState("prokka")
        roster = parse_machine_annotators(_config(PROKKA))
        stamp_user_state(state, roster)

        user_dir = str(tmp_path / "prokka")
        os.makedirs(user_dir, exist_ok=True)
        state.save(user_dir)

        reloaded = InMemoryUserState.load(user_dir)
        assert is_machine(reloaded)
        assert origin_of(reloaded)["version"] == "1.14.6"

    def test_a_state_file_written_before_origin_existed_loads_as_human(self, tmp_path):
        """The migration case. No origin key at all, which is every study today."""
        from potato.user_state_management import InMemoryUserState

        state = InMemoryUserState("alice")
        user_dir = str(tmp_path / "alice")
        os.makedirs(user_dir, exist_ok=True)
        state.save(user_dir)

        # Strip the key the way a pre-change file would have it.
        state_path = None
        for candidate in os.listdir(user_dir):
            if candidate.endswith(".json"):
                state_path = os.path.join(user_dir, candidate)
                break
        assert state_path is not None, (
            f"no .json user state was written to {user_dir}, so this test "
            f"cannot reach the migration case. Skipping here would let it pass "
            f"while proving nothing. Directory holds: {os.listdir(user_dir)}"
        )

        with open(state_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        raw.pop("origin", None)
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump(raw, handle)

        reloaded = InMemoryUserState.load(user_dir)
        assert is_human(reloaded)

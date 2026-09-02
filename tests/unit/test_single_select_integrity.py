"""
Unit tests for the single-select annotation invariant (GH #167).

Background: a ``radio``/``likert``/``confidence`` schema renders one input per option,
each carrying its own ``label_name``. Annotations are stored as
``{Label(schema, label_name): value}``, so changing the answer writes a NEW dict key.
Before the fix, the old key was never removed for likert, and was never removed for ANY
type on phase pages, so every option the annotator clicked accumulated in
``user_state.json`` and the CSV export became ambiguous.

These tests pin down:
  * which annotation types are single-select (a misclassification would delete data),
  * that the invariant holds in every phase, not just the annotation phase,
  * that ``free_response`` survives the purge,
  * that the export and repair paths resolve legacy duplicates correctly.
"""

import json
import os
import tempfile

import pytest

from potato.item_state_management import Label
from potato.phase import UserPhase
from potato.server_utils.schemas.registry import schema_registry


# ---------------------------------------------------------------------------
# Registry classification
# ---------------------------------------------------------------------------

class TestRegistryClassification:
    """The single_select flag is the source of truth for what may be purged."""

    def test_exactly_three_types_are_single_select(self):
        """A new generator must be classified deliberately, not by default.

        If this fails because a type was added, decide whether it renders SEVERAL
        inputs with DIFFERENT label_names for ONE logical answer. If it does, set
        single_select=True and add it here. If it emits a single fixed label_name
        (like select -> "select-one"), leave it False.
        """
        assert schema_registry.get_single_select_types() == [
            "confidence", "likert", "radio"]

    def test_every_registered_type_has_the_flag(self):
        for schema in schema_registry.list_schemas():
            assert "single_select" in schema, (
                f"{schema['name']} is missing the single_select flag")
            assert isinstance(schema["single_select"], bool)

    @pytest.mark.parametrize("type_name", [
        # One fixed label_name per schema -> re-answering overwrites; purging is
        # unnecessary and would only add risk.
        "select", "slider", "number", "vas", "ranking", "triage", "card_sort",
        # Legitimately multi-label.
        "multiselect", "multirate", "semantic_differential", "constant_sum",
        "range_slider", "soft_label", "rubric_eval",
        # Hidden inputs gated on data-modified/data-server-set: the client does not
        # reliably re-send them, so clearing could drop real data.
        "pairwise", "bws",
        # Multi-label when `labels:` is configured.
        "text",
    ])
    def test_types_that_must_not_be_purged(self, type_name):
        definition = schema_registry.get(type_name)
        assert definition is not None, f"{type_name} is not registered"
        assert definition.single_select is False, (
            f"{type_name} must not be single_select — purging it would delete "
            f"legitimate annotations")


# ---------------------------------------------------------------------------
# Schema resolution, including SurveyFlow questions
# ---------------------------------------------------------------------------

class TestSchemaResolution:

    @pytest.fixture
    def loaded_config(self):
        from potato.server_utils.config_module import config
        # The cohort resolver is a process-wide singleton that other tests may have
        # initialised. all_single_select_schema_names() unions its schemes in, so leave
        # it cleared here or this test's result depends on execution order.
        try:
            from potato.server_utils.cohort_schemes import clear_cohort_scheme_resolver
            clear_cohort_scheme_resolver()
        except Exception:
            pass
        original = dict(config)
        config.clear()
        config.update({
            "annotation_schemes": [
                {"name": "veracity", "annotation_type": "radio"},
                {"name": "confidence", "annotation_type": "likert"},
                {"name": "notes", "annotation_type": "text"},
                {"name": "tags", "annotation_type": "multiselect"},
                {"name": "per_turn", "annotation_type": "radio", "turn_level": True},
            ],
            "_surveyflow_schemes": [
                {"name": "native_language", "annotation_type": "radio"},
                {"name": "nlp_familiarity", "annotation_type": "likert"},
            ],
        })
        yield config
        config.clear()
        config.update(original)

    def test_resolves_annotation_schemes(self, loaded_config):
        from potato.server_utils.schema_exclusivity import is_single_select
        assert is_single_select("veracity") is True
        assert is_single_select("confidence") is True
        assert is_single_select("notes") is False
        assert is_single_select("tags") is False

    def test_resolves_surveyflow_schemes(self, loaded_config):
        """The pre-fix code only looked at annotation_schemes, so survey questions
        resolved to None and could never be cleared."""
        from potato.server_utils.schema_exclusivity import is_single_select
        assert is_single_select("native_language") is True
        assert is_single_select("nlp_familiarity") is True

    def test_turn_level_schemes_are_never_single_select(self, loaded_config):
        """turn_level schemes never run their generator — they store one `_data` blob
        regardless of annotation_type, so the declared type says nothing useful."""
        from potato.server_utils.schema_exclusivity import is_single_select
        assert is_single_select("per_turn") is False

    def test_unknown_schema_is_not_purged(self, loaded_config):
        from potato.server_utils.schema_exclusivity import is_single_select
        assert is_single_select("does_not_exist") is False

    def test_all_names_spans_both_sources(self, loaded_config):
        from potato.server_utils.schema_exclusivity import all_single_select_schema_names
        assert all_single_select_schema_names(loaded_config) == {
            "veracity", "confidence", "native_language", "nlp_familiarity"}


# ---------------------------------------------------------------------------
# The write-time invariant, in every phase
# ---------------------------------------------------------------------------

def _state(single_select=("confidence", "veracity")):
    from potato.user_state_management import InMemoryUserState
    state = InMemoryUserState("test_user", -1)
    state._single_select_schemas = frozenset(single_select)
    return state


def _labels(state, instance_id="inst_1"):
    """The stored labels for whichever container the current phase uses."""
    if state.current_phase_and_page[0] == UserPhase.ANNOTATION:
        return state.instance_id_to_label_to_value[instance_id]
    phase, page = state.current_phase_and_page
    return state.phase_to_page_to_label_to_value[phase][page]


# Every phase a user passes through. The bug behaved differently in the annotation
# phase (likert only) than on phase pages (every type), so all of them are covered.
ALL_PHASES = [
    (UserPhase.ANNOTATION, None),
    (UserPhase.CONSENT, "consent"),
    (UserPhase.INSTRUCTIONS, "instructions"),
    (UserPhase.TRAINING, "training"),
    (UserPhase.PRESTUDY, "prestudy"),
    (UserPhase.POSTSTUDY, "poststudy"),
]


class TestWriteTimeInvariant:

    @pytest.mark.parametrize("phase,page", ALL_PHASES)
    def test_changed_likert_answer_replaces_the_old_one(self, phase, page):
        """The core #167 regression, exercised in every phase."""
        state = _state()
        state.set_current_phase_and_page((phase, page))

        state.add_label_annotation("inst_1", Label("confidence", "5"), "5")
        state.add_label_annotation("inst_1", Label("confidence", "4"), "4")

        stored = _labels(state)
        assert list(stored.items()) == [(Label("confidence", "4"), "4")], (
            f"phase {phase} kept {len(stored)} values for a single-select schema")

    @pytest.mark.parametrize("phase,page", ALL_PHASES)
    def test_changed_radio_answer_replaces_the_old_one(self, phase, page):
        state = _state()
        state.set_current_phase_and_page((phase, page))

        state.add_label_annotation("inst_1", Label("veracity", "True"), "True")
        state.add_label_annotation("inst_1", Label("veracity", "False"), "False")

        stored = _labels(state)
        assert list(stored.items()) == [(Label("veracity", "False"), "False")]

    def test_free_response_survives_the_purge(self):
        """radio's has_free_response stores a SECOND label on the same schema. It is a
        separate answer, not a competing option, and must not be deleted."""
        state = _state(single_select=("veracity",))

        state.add_label_annotation("inst_1", Label("veracity", "Other"), "Other")
        state.add_label_annotation("inst_1", Label("veracity", "free_response"), "see note")
        state.add_label_annotation("inst_1", Label("veracity", "True"), "True")

        stored = _labels(state)
        assert stored[Label("veracity", "free_response")] == "see note"
        assert stored[Label("veracity", "True")] == "True"
        assert Label("veracity", "Other") not in stored

    def test_writing_free_response_does_not_evict_the_choice(self):
        state = _state(single_select=("veracity",))
        state.add_label_annotation("inst_1", Label("veracity", "True"), "True")
        state.add_label_annotation("inst_1", Label("veracity", "free_response"), "note")

        stored = _labels(state)
        assert stored[Label("veracity", "True")] == "True"
        assert stored[Label("veracity", "free_response")] == "note"

    def test_bad_text_is_not_exempt(self):
        """likert's bad_text_label is a real member of the radio group — choosing it
        must replace the scale point, unlike free_response."""
        state = _state()
        state.add_label_annotation("inst_1", Label("confidence", "3"), "3")
        state.add_label_annotation("inst_1", Label("confidence", "bad_text"), "0")

        stored = _labels(state)
        assert list(stored.keys()) == [Label("confidence", "bad_text")]

    def test_falsy_value_does_not_evict_the_real_answer(self):
        """The legacy v1 template posts the WHOLE fieldset as {name: <bool>} pairs.
        An unselected option must never displace the selected one."""
        state = _state(single_select=("veracity",))
        state.add_label_annotation("inst_1", Label("veracity", "True"), True)
        state.add_label_annotation("inst_1", Label("veracity", "False"), False)

        stored = _labels(state)
        assert stored[Label("veracity", "True")] is True

    def test_multi_label_schemas_are_untouched(self):
        state = _state()  # 'tags' is not in the single-select set
        state.add_label_annotation("inst_1", Label("tags", "a"), "a")
        state.add_label_annotation("inst_1", Label("tags", "b"), "b")

        stored = _labels(state)
        assert len(stored) == 2

    def test_invariant_off_by_default(self):
        """A bare UserState (as built by many existing unit tests) must behave exactly
        as before rather than crash or silently delete."""
        from potato.user_state_management import InMemoryUserState
        state = InMemoryUserState("bare_user", -1)
        state.set_current_phase_and_page((UserPhase.ANNOTATION, None))
        state.add_label_annotation("inst_1", Label("confidence", "5"), "5")
        state.add_label_annotation("inst_1", Label("confidence", "4"), "4")
        assert len(state.instance_id_to_label_to_value["inst_1"]) == 2


class TestClearSchemaLabels:

    @pytest.mark.parametrize("phase,page", ALL_PHASES)
    def test_clears_the_right_container(self, phase, page):
        state = _state()
        state.set_current_phase_and_page((phase, page))
        state.add_label_annotation("inst_1", Label("tags", "a"), "a")
        state.add_label_annotation("inst_1", Label("tags", "b"), "b")

        assert state.clear_schema_labels("inst_1", "tags") == 2
        assert len(_labels(state)) == 0

    def test_preserves_free_response(self):
        state = _state()
        state.add_label_annotation("inst_1", Label("tags", "a"), "a")
        state.add_label_annotation("inst_1", Label("tags", "free_response"), "note")

        assert state.clear_schema_labels("inst_1", "tags") == 1
        assert _labels(state) == {Label("tags", "free_response"): "note"}

    def test_does_not_materialise_empty_instances(self):
        """Both stores are defaultdicts. Merely looking for stale labels must not
        create an entry, or an untouched instance looks annotated to the exporter."""
        state = _state()
        assert state.clear_schema_labels("never_seen", "confidence") == 0
        assert "never_seen" not in state.instance_id_to_label_to_value


# ---------------------------------------------------------------------------
# Resolving legacy duplicates
# ---------------------------------------------------------------------------

class TestResolveFinalLabel:

    def test_single_value_needs_no_resolution(self):
        from potato.export.single_select import resolve_final_label
        assert resolve_final_label("confidence", ["4"]) == ("4", "single")

    def test_falls_back_to_persisted_order(self):
        from potato.export.single_select import resolve_final_label
        assert resolve_final_label("confidence", ["5", "4"]) == ("4", "order")

    def test_behavioral_trail_wins(self):
        """The decisive case: 5 -> 4 -> 5 persists as [5, 4] because the dict keeps
        FIRST-write order. Only the timestamps know the answer is 5."""
        from potato.export.single_select import resolve_final_label
        changes = [
            {"timestamp": 100.0, "schema_name": "confidence",
             "label_name": "5", "action": "select"},
            {"timestamp": 200.0, "schema_name": "confidence",
             "label_name": "4", "action": "select"},
            {"timestamp": 300.0, "schema_name": "confidence",
             "label_name": "5", "action": "select"},
        ]
        assert resolve_final_label("confidence", ["5", "4"], changes) == ("5", "behavioral")

    def test_reporters_reported_sequence(self):
        """The exact case from the GH #167 follow-up comment.

        Click sequence 5, 4, 5, 4, 5 persists as ['5', '4'] — the dict lists values in
        first-touch order and updates in place, so its last entry is NOT the final
        answer. Only the timestamped trail can recover it.
        """
        from potato.export.single_select import resolve_final_label
        clicks = ["5", "4", "5", "4", "5"]
        changes = [
            {"timestamp": 100.0 + i, "schema_name": "confidence",
             "label_name": label, "action": "select"}
            for i, label in enumerate(clicks)
        ]
        # What the corrupted state file actually holds.
        stored = ["5", "4"]

        assert resolve_final_label("confidence", stored, changes) == ("5", "behavioral")
        # Without the trail, order alone gives the wrong answer — hence the warning.
        assert resolve_final_label("confidence", stored) == ("4", "order")

    def test_ignores_other_schemas_changes(self):
        from potato.export.single_select import resolve_final_label
        changes = [
            {"timestamp": 999.0, "schema_name": "other",
             "label_name": "5", "action": "select"},
        ]
        assert resolve_final_label("confidence", ["5", "4"], changes) == ("4", "order")

    def test_free_response_is_not_a_candidate(self):
        from potato.export.single_select import resolve_final_label
        assert resolve_final_label(
            "veracity", ["True", "free_response"]) == ("True", "single")


# ---------------------------------------------------------------------------
# Repair CLI
# ---------------------------------------------------------------------------

CORRUPT_STATE = {
    "user_id": "u1",
    "instance_id_to_label_to_value": {
        "inst_1": [
            [{"schema": "confidence", "name": "5"}, "5"],
            [{"schema": "confidence", "name": "4"}, "4"],
            [{"schema": "veracity", "name": "True"}, "True"],
        ]
    },
    "phase_to_page_to_label_to_value": {
        "prestudy": {
            "prestudy": [
                [{"schema": "native_language", "name": "Yes"}, "Yes"],
                [{"schema": "native_language", "name": "No"}, "No"],
            ]
        }
    },
    "instance_id_to_behavioral_data": {
        "inst_1": {
            "annotation_changes": [
                {"timestamp": 100.0, "schema_name": "confidence",
                 "label_name": "5", "action": "select"},
                {"timestamp": 200.0, "schema_name": "confidence",
                 "label_name": "4", "action": "select"},
                {"timestamp": 300.0, "schema_name": "confidence",
                 "label_name": "5", "action": "select"},
            ]
        }
    },
}


class TestRepair:

    def test_repairs_annotation_and_phase_data(self):
        from potato.repair_cli import repair_user_state
        state = json.loads(json.dumps(CORRUPT_STATE))

        state, reports = repair_user_state(
            state, {"confidence", "veracity", "native_language"})

        labels = state["instance_id_to_label_to_value"]["inst_1"]
        confidence = [e for e in labels if e[0]["schema"] == "confidence"]
        assert len(confidence) == 1
        # 5 -> 4 -> 5, so the answer is 5 even though 4 is last in stored order.
        assert confidence[0][0]["name"] == "5"

        prestudy = state["phase_to_page_to_label_to_value"]["prestudy"]["prestudy"]
        assert len(prestudy) == 1
        assert prestudy[0][0]["name"] == "No"

        methods = {(r["schema"], r["method"]) for r in reports}
        assert ("confidence", "behavioral") in methods
        assert ("native_language", "order") in methods

    def test_leaves_healthy_schemas_alone(self):
        from potato.repair_cli import repair_user_state
        state = json.loads(json.dumps(CORRUPT_STATE))
        state, _ = repair_user_state(state, {"confidence", "veracity", "native_language"})

        labels = state["instance_id_to_label_to_value"]["inst_1"]
        veracity = [e for e in labels if e[0]["schema"] == "veracity"]
        assert len(veracity) == 1 and veracity[0][1] == "True"

    def test_dry_run_writes_nothing(self):
        from potato.repair_cli import repair_output_dir
        with tempfile.TemporaryDirectory() as out:
            user_dir = os.path.join(out, "u1")
            os.makedirs(user_dir)
            path = os.path.join(user_dir, "user_state.json")
            with open(path, "w") as f:
                json.dump(CORRUPT_STATE, f)
            before = open(path).read()

            summary = repair_output_dir(out, {"confidence", "native_language"}, apply=False)

            assert summary["collapses"] == 2
            assert summary["applied"] is False
            assert open(path).read() == before
            assert not os.path.exists(path + ".bak")

    def test_apply_writes_and_backs_up(self):
        from potato.repair_cli import repair_output_dir
        with tempfile.TemporaryDirectory() as out:
            user_dir = os.path.join(out, "u1")
            os.makedirs(user_dir)
            path = os.path.join(user_dir, "user_state.json")
            with open(path, "w") as f:
                json.dump(CORRUPT_STATE, f)

            summary = repair_output_dir(out, {"confidence", "native_language"}, apply=True)

            assert summary["applied"] is True
            assert os.path.exists(path + ".bak")
            with open(path) as f:
                repaired = json.load(f)
            labels = repaired["instance_id_to_label_to_value"]["inst_1"]
            assert len([e for e in labels if e[0]["schema"] == "confidence"]) == 1
            # The backup still holds the original, so the repair is reversible.
            with open(path + ".bak") as f:
                assert len(json.load(f)["instance_id_to_label_to_value"]["inst_1"]) == 3

    def test_repair_is_idempotent(self):
        from potato.repair_cli import repair_user_state
        state = json.loads(json.dumps(CORRUPT_STATE))
        state, _ = repair_user_state(state, {"confidence", "native_language"})
        state, reports = repair_user_state(state, {"confidence", "native_language"})
        assert reports == []

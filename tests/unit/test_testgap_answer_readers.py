"""
Readers of stored answers, fed the shapes the server actually writes.

Every reader below had tests, and every test built its input by hand: a slider
as ``{"rating": 7}``, a multiselect as a list, an attention check as
``{"color": "Blue"}``. ``/updateinstance`` stores none of those. It writes one
``Label(schema, name)`` per posted key with the posted value -- a slider as
``{Label("rating", "slider"): "7"}``, each ticked box as
``{Label("tags", "sports"): "sports"}``, a radio's "Other" text as a second
label ``free_response`` -- and posts multiselect boxes one key at a time. These
tests build state through ``InMemoryUserState.add_label_annotation`` with those
values, and the QC payload through the route's own flattening.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from potato.item_state_management import Label, SpanAnnotation
from potato.phase import UserPhase
from potato.user_state_management import InMemoryUserState
from tests.helpers.test_utils import create_test_directory


def _state(user, answers):
    """answers: {instance_id: {(schema, label): posted value}}."""
    state = InMemoryUserState(user)
    state.advance_to_phase(UserPhase.ANNOTATION, None)
    for iid, entries in answers.items():
        for (schema, label), value in entries.items():
            state.add_label_annotation(iid, Label(schema, label), value)
    return state


# ---------------------------------------------------------------------------
# Adjudication routing
# ---------------------------------------------------------------------------

class TestAdjudicationComparesTheAnswer:
    SCHEMES = [
        {"name": "rating", "annotation_type": "slider", "min_value": 1, "max_value": 10},
        {"name": "lk", "annotation_type": "likert", "size": 5},
        {"name": "grid", "annotation_type": "multirate",
         "options": ["x", "y"], "labels": ["0", "1", "2"]},
    ]

    def _agreement(self, a, b):
        from potato.adjudication import AdjudicationManager
        manager = AdjudicationManager.__new__(AdjudicationManager)
        manager.config = {"annotation_schemes": self.SCHEMES}
        items = {u: manager._serialize_labels(s.get_label_annotations("i1"))
                 for u, s in (("u1", a), ("u2", b))}
        return manager._compute_agreement(items, [s["name"] for s in self.SCHEMES])

    def test_a_slider_at_1_and_one_at_10_disagree(self):
        a = _state("u1", {"i1": {("rating", "slider"): "1"}})
        b = _state("u2", {"i1": {("rating", "slider"): "10"}})
        assert self._agreement(a, b)["rating"] == 0.0

    def test_the_same_number_stored_as_int_and_string_agrees(self):
        a = _state("u1", {"i1": {("rating", "slider"): "7"}})
        b = _state("u2", {"i1": {("rating", "slider"): 7}})
        assert self._agreement(a, b)["rating"] == 1.0

    def test_a_likert_answer_of_0_is_an_answer(self):
        from potato.server_utils import annotation_values
        scheme = self.SCHEMES[1]
        answered = annotation_values.comparable_value(scheme, {"0": "0"})
        assert answered == frozenset({"0"})
        assert answered != annotation_values.comparable_value(scheme, {})

    def test_a_matrix_row_rated_0_is_not_a_skipped_row(self):
        a = _state("u1", {"i1": {("grid", "x"): "0", ("grid", "y"): "2"}})
        b = _state("u2", {"i1": {("grid", "y"): "2"}})
        assert self._agreement(a, b)["grid"] == 0.0


# ---------------------------------------------------------------------------
# Required follow-ups on annotation pages
# ---------------------------------------------------------------------------

class TestRequiredFollowUpsSeeTheValue:
    SCHEMES = [
        {"name": "rating", "annotation_type": "slider", "min_value": 0, "max_value": 10},
        {"name": "why", "annotation_type": "text",
         "display_logic": {"show_when": [
             {"schema": "rating", "operator": "gt", "value": 5}]}},
        {"name": "q", "annotation_type": "number"},
        {"name": "low", "annotation_type": "text",
         "display_logic": {"show_when": [
             {"schema": "q", "operator": "lt", "value": 3}]}},
    ]

    def _hidden(self, answers):
        import potato.flask_server as fs
        with patch.object(fs, "config", {"annotation_schemes": self.SCHEMES}):
            return fs._hidden_scheme_names(_state("u", {"i1": answers}), "i1")

    def test_the_slider_value_reaches_the_condition(self):
        assert "why" not in self._hidden({("rating", "slider"): "7"})
        assert "why" in self._hidden({("rating", "slider"): "3"})

    def test_a_slider_at_0_is_answered(self):
        import potato.flask_server as fs
        with patch.object(fs, "config", {"annotation_schemes": self.SCHEMES}):
            flat = fs._flat_annotations_for_instance(
                _state("u", {"i1": {("rating", "slider"): "0"}}), "i1")
        assert flat == {"rating": "0"}

    def test_an_unanswered_number_does_not_satisfy_lt(self):
        """Unanswered is not 0. The browser already read it that way."""
        assert "low" in self._hidden({("rating", "slider"): "7"})

    def test_a_yaml_number_equals_a_posted_string(self):
        from potato.server_utils.display_logic import DisplayLogicEvaluator
        assert DisplayLogicEvaluator._values_equal("3", 3, False)
        assert not DisplayLogicEvaluator._values_equal("3", 4, False)
        assert not DisplayLogicEvaluator._values_equal("", 0, False)


# ---------------------------------------------------------------------------
# Attention checks and gold standards
# ---------------------------------------------------------------------------

class TestMultiselectAttentionCheck:
    def _qc(self):
        from potato.quality_control import QualityControlManager
        task_dir = create_test_directory("testgap_qc_multiselect")
        path = os.path.join(task_dir, "checks.json")
        with open(path, "w") as fh:
            json.dump([{"id": "ac1", "text": "Tick only Blue",
                        "expected_answer": {"color": "Blue"}}], fh)
        return QualityControlManager({
            "annotation_schemes": [{"name": "color", "annotation_type": "multiselect",
                                    "labels": ["Red", "Green", "Blue"]}],
            "attention_checks": {"enabled": True, "items_file": path, "frequency": 3},
        }, task_dir)

    def _grade(self, payload):
        from potato.routes import _qc_answer_payload
        all_annotations, _ = _qc_answer_payload(payload)
        return self._qc().validate_attention_response("u", "ac1", all_annotations, None)

    @pytest.mark.parametrize("order", [
        ["Red", "Green", "Blue"], ["Blue", "Red", "Green"]])
    def test_ticking_every_box_fails_in_any_order(self, order):
        payload = {f"color:::{label}": label for label in order}
        assert self._grade(payload)["passed"] is False

    @pytest.mark.parametrize("value", ["Blue", "on", True])
    def test_ticking_only_the_expected_box_passes(self, value):
        assert self._grade({"color:::Blue": value})["passed"] is True


# ---------------------------------------------------------------------------
# Models that read labels
# ---------------------------------------------------------------------------

class _USM:
    def __init__(self, states):
        self.states = {s.user_id: s for s in states}

    def get_all_users(self):
        return list(self.states.values())

    def get_user_state(self, uid):
        return self.states.get(uid)

    def get_user_ids(self):
        return list(self.states)


class TestPsychometricsKeepsLabelZero:
    def test_a_radio_answer_of_0_is_observed(self):
        from potato.psychometrics.manager import PsychometricsManager
        states = [_state("u1", {"i1": {("s", "0"): "0"}, "i2": {("s", "1"): "1"}})]
        manager = PsychometricsManager({"psychometrics": {"enabled": True, "schema": "s"},
                                        "annotation_schemes": [
                                            {"name": "s", "annotation_type": "radio",
                                             "labels": ["0", "1"]}]})
        with patch("potato.user_state_management.get_user_state_manager",
                   return_value=_USM(states)):
            obs = sorted(manager.collect_observations())
        assert obs == [("i1", "u1", "0"), ("i2", "u1", "1")]


class TestActiveLearningCountsAnnotators:
    def _manager(self, schema_type):
        from potato.active_learning_manager import ActiveLearningConfig, ActiveLearningManager
        manager = ActiveLearningManager.__new__(ActiveLearningManager)
        manager.config = ActiveLearningConfig(
            schema_names=["s"], min_annotations_per_instance=2,
            schema_types={"s": schema_type})
        import logging
        manager.logger = logging.getLogger("test")
        return manager

    def _items(self):
        return SimpleNamespace(get_item=lambda iid: SimpleNamespace(
            get_text=lambda: "t", get_data=lambda: {"text": "t"}, get_id=lambda: iid))

    def test_free_response_text_is_not_a_class(self):
        manager = self._manager("radio")
        states = [_state(u, {"i1": {("s", "neg"): "neg", ("s", "free_response"): "why"}})
                  for u in ("a", "b")]
        data = manager._collect_training_data(self._items(), _USM(states), "s")
        assert data["labels"] == ["neg"]

    def test_one_annotator_with_two_ticks_is_one_vote(self):
        manager = self._manager("multiselect")
        states = [_state("a", {"i1": {("s", "x"): "x", ("s", "y"): "y"}})]
        data = manager._collect_training_data(self._items(), _USM(states), "s")
        assert data["labels"] == []

    def test_a_tie_has_no_majority(self):
        manager = self._manager("radio")
        assert manager._majority_vote([{"label": "a"}, {"label": "b"}]) is None


class TestEmbeddingMapColours:
    def test_free_response_does_not_colour_the_point(self):
        from potato.embedding_visualization import EmbeddingVisualizationManager
        manager = EmbeddingVisualizationManager.__new__(EmbeddingVisualizationManager)
        import logging
        manager.logger = logging.getLogger("test")
        manager.app_config = {"annotation_schemes": [
            {"name": "s", "annotation_type": "radio", "labels": ["pos", "neg"]}]}
        # free_response written first, so a first-seen tie-break picks it.
        states = [_state("a", {"i1": {("s", "free_response"): "x", ("s", "neg"): "neg"}})]
        manager._get_user_state_manager = lambda: _USM(states)
        with patch("potato.flask_server.get_users", return_value=["a"]):
            assert manager._get_majority_labels(["i1"]) == {"i1": "neg"}


# ---------------------------------------------------------------------------
# Admin analytics
# ---------------------------------------------------------------------------

class _Item:
    def __init__(self, iid):
        self.iid = iid

    def get_id(self):
        return self.iid


def _admin(schemes, states, items=("i1",)):
    from potato.admin import AdminDashboard
    dashboard = AdminDashboard()
    dashboard.check_admin_access = lambda: True
    usm = _USM(states)
    ism = SimpleNamespace(items=lambda: [_Item(i) for i in items])
    patches = [
        patch("potato.admin.get_item_state_manager", return_value=ism),
        patch("potato.admin.get_user_state_manager", return_value=usm),
        patch("potato.admin.get_users", return_value=list(usm.states)),
        patch("potato.admin.config", {"annotation_schemes": schemes}),
    ]
    return dashboard, patches


class TestAdminQuestionStats:
    SCHEMES = [
        {"name": "tags", "annotation_type": "multiselect",
         "labels": [{"name": "sports"}, {"name": "politics"}, {"name": "tech"}]},
        {"name": "rating", "annotation_type": "slider", "min": 0, "max": 10},
    ]

    def _questions(self):
        states = [
            _state("a", {"i1": {("tags", "sports"): "sports", ("tags", "tech"): "tech",
                                ("rating", "slider"): "2"}}),
            _state("b", {"i1": {("tags", "politics"): "politics",
                                ("rating", "slider"): "8"}}),
        ]
        dashboard, patches = _admin(self.SCHEMES, states)
        for p in patches:
            p.start()
        try:
            return {q["name"]: q["analysis"] for q in dashboard.get_questions_data()["questions"]}
        finally:
            for p in patches:
                p.stop()

    def test_multiselect_counts_every_tick(self):
        data = self._questions()["tags"]["data"]
        assert dict(zip(data["labels"], data["counts"])) == {
            "sports": 1, "politics": 1, "tech": 1}

    def test_co_occurrence_is_within_one_annotator(self):
        assert self._questions()["tags"]["data"]["co_occurrence"] == {"sports|tech": 1}

    def test_slider_values_are_numbers(self):
        stats = self._questions()["rating"]["data"]["statistics"]
        assert (stats["min"], stats["max"], stats["mean"]) == (2.0, 8.0, 5.0)


class TestCodeCooccurrence:
    SCHEMES = [
        {"name": "themes", "annotation_type": "multiselect",
         "labels": ["frustration", "delight"]},
        {"name": "rating", "annotation_type": "slider"},
        {"name": "ner", "annotation_type": "span", "labels": ["PER"]},
    ]

    def test_codes_are_label_names_and_spans_are_read(self):
        state = _state("a", {"i1": {("themes", "frustration"): "on",
                                    ("themes", "delight"): "on",
                                    ("rating", "slider"): "7"}})
        state.add_span_annotation("i1", SpanAnnotation("ner", "PER", "", 0, 5), "PER")
        dashboard, patches = _admin(self.SCHEMES, [state])
        for p in patches:
            p.start()
        try:
            result = dashboard.get_code_cooccurrence_matrix()
        finally:
            for p in patches:
                p.stop()
        assert result["codes"] == ["ner::PER", "themes::delight", "themes::frustration"]
        assert result["n_pairs"] == 3


# ---------------------------------------------------------------------------
# The MySQL backend groups by schema name
# ---------------------------------------------------------------------------

class _MysqlShapedState:
    """What MysqlUserState.get_all_annotations returns: string schema keys."""

    def __init__(self, user_id, annotations):
        self.user_id = user_id
        self._annotations = annotations

    def get_all_annotations(self):
        return self._annotations


class TestMysqlShapedAnnotations:
    def test_psychometrics_reads_them(self):
        from potato.psychometrics.manager import PsychometricsManager
        state = _MysqlShapedState("u1", {"i1": {"labels": {"s": {"0": "0"}}, "spans": {}}})
        manager = PsychometricsManager({"psychometrics": {"enabled": True, "schema": "s"},
                                        "annotation_schemes": [
                                            {"name": "s", "annotation_type": "radio",
                                             "labels": ["0", "1"]}]})
        usm = SimpleNamespace(get_all_users=lambda: [state])
        with patch("potato.user_state_management.get_user_state_manager",
                   return_value=usm):
            assert manager.collect_observations() == [("i1", "u1", "0")]

    def test_active_learning_reads_them(self):
        manager = TestActiveLearningCountsAnnotators()._manager("radio")
        states = [_MysqlShapedState(u, {"i1": {"labels": {"s": {"neg": "neg"}}}})
                  for u in ("a", "b")]
        usm = SimpleNamespace(get_all_users=lambda: states)
        data = manager._collect_training_data(
            TestActiveLearningCountsAnnotators()._items(), usm, "s")
        assert data["labels"] == ["neg"]

    def test_code_cooccurrence_reads_mysql_spans(self):
        state = _MysqlShapedState("a", {"i1": {
            "labels": {"themes": {"delight": "delight"}},
            "spans": {"ner": {"PER": {"title": "", "start": 0, "end": 3}}}}})
        dashboard, patches = _admin(TestCodeCooccurrence.SCHEMES, [state])
        for p in patches:
            p.start()
        try:
            result = dashboard.get_code_cooccurrence_matrix()
        finally:
            for p in patches:
                p.stop()
        assert result["codes"] == ["ner::PER", "themes::delight"]


class TestNumericQuestionStats:
    """Real numbers reach these statistics now, which exposed two faults."""

    def _analysis(self, values):
        states = [_state(f"u{n}", {"i1": {("rating", "slider"): str(v)}})
                  for n, v in enumerate(values)]
        dashboard, patches = _admin(
            [{"name": "rating", "annotation_type": "slider",
              "min_value": 0, "max_value": 10}], states)
        for p in patches:
            p.start()
        try:
            return dashboard.get_questions_data()["questions"][0]["analysis"]
        finally:
            for p in patches:
                p.stop()

    def test_one_answer_does_not_divide_by_zero(self):
        data = self._analysis([7])["data"]
        assert sum(data["bins"]["counts"]) == 1

    def test_median_of_an_even_count_is_the_midpoint(self):
        assert self._analysis([2, 4, 6, 8])["data"]["statistics"]["median"] == 5.0

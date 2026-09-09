"""The expertise router can record a disagreement, and can be looked at.

Measured by the audit on a live server: three annotators, twelve items, one
annotator answering No to every item of a category while both colleagues
answered Yes. The worker logged ``agreed=True`` thirty-six times and
``agreed=False`` zero times, every expertise score climbed to 0.969 in every
category, and probabilistic routing stayed uniform -- random assignment
reporting success.

The read took the stored VALUE, which for a radio is the marker ``"on"``, so
consensus was ``"on"``, every annotator's answer was ``"on"``, and agreement
was true by construction.

Two things kept it invisible and are fixed alongside, because they are why one
could not notice:

* the worker counted the pool it walked rather than the annotations it scored,
  so "36 expertise updates" was logged on every tick forever after 36 real
  updates happened once;
* scores lived in memory with no persistence and no route, so the only way to
  observe the router was ``-v`` and DEBUG lines.

Also here: ``category_assignment.category_key`` was documented with an example
and read by nothing, and the five real ``category_assignment.dynamic`` sub-keys
had no documentation at all.
"""

import json
import os
import tempfile

import pytest

from potato.expertise_manager import (
    AgreementMethod,
    CategoryExpertise,
    ExpertiseManager,
    clear_expertise_manager,
    init_expertise_manager,
)


class Label:
    """The stored key shape: a schema and a label name."""

    def __init__(self, schema, name):
        self.schema = schema
        self.name = name

    def get_schema(self):
        return self.schema

    def get_name(self):
        return self.name

    def __hash__(self):
        return hash((self.schema, self.name))

    def __eq__(self, other):
        return (self.schema, self.name) == (other.schema, other.name)


@pytest.fixture(autouse=True)
def fresh_manager():
    clear_expertise_manager()
    ExpertiseManager._instance = None
    yield
    clear_expertise_manager()
    ExpertiseManager._instance = None


def manager(tmp_path=None, **dynamic):
    config = {"category_assignment": {"dynamic": {"enabled": True, **dynamic}}}
    if tmp_path:
        config["output_annotation_dir"] = tmp_path
    ExpertiseManager._instance = None
    return init_expertise_manager(config)


def stored(schema, label_name, value="on"):
    return {"labels": {Label(schema, label_name): value}}


# ----------------------------------------------------------------------
# 1. A disagreement is recorded as one
# ----------------------------------------------------------------------

class TestTheReadFindsTheAnswer:
    """The answer is the label NAME. The value is a DOM default."""

    def test_two_opposite_radio_answers_are_different_answers(self):
        from potato.expertise_manager import _schema_answer

        yes = _schema_answer(stored("stance", "Yes"), "stance")
        no = _schema_answer(stored("stance", "No"), "stance")
        assert yes != no, (
            "both answers read as 'on', so consensus was 'on', every "
            "annotator matched it, and the router could not record a "
            "disagreement at all")
        assert {yes, no} == {"Yes", "No"}

    def test_the_annotation_page_shape_reads_the_same(self):
        """The desktop page repeats the label in the value; same answer."""
        from potato.expertise_manager import _schema_answer

        assert (_schema_answer(stored("stance", "Yes", "Yes"), "stance")
                == _schema_answer(stored("stance", "Yes", "on"), "stance")
                == "Yes")

    def test_a_free_text_answer_is_still_its_value(self):
        from potato.expertise_manager import _schema_answer

        assert _schema_answer(
            stored("comment", "text_box", "it was fine"), "comment"
        ) == "it was fine"

    def test_another_schema_is_not_read(self):
        from potato.expertise_manager import _schema_answer

        assert _schema_answer(stored("stance", "Yes"), "tone") is None


class TestDisagreementLowersTheScore:

    def test_agreeing_raises_and_disagreeing_lowers(self):
        mgr = manager()
        assert mgr.update_user_expertise("u", "i1", "food", "Yes", "Yes") is True
        raised = mgr.get_user_profile("u").get_expertise_score("food")
        assert mgr.update_user_expertise("u", "i2", "food", "No", "Yes") is False
        assert mgr.get_user_profile("u").get_expertise_score("food") < raised

    def test_the_dissenter_does_not_reach_the_majority_score(self):
        """The measured shape of the defect: same items, opposite answers,
        identical scores."""
        mgr = manager()
        for i in range(4):
            mgr.update_user_expertise("maj", f"i{i}", "food", "Yes", "Yes")
            mgr.update_user_expertise("odd", f"i{i}", "food", "No", "Yes")
        majority = mgr.get_user_profile("maj").get_expertise_score("food")
        dissenter = mgr.get_user_profile("odd").get_expertise_score("food")
        assert dissenter < majority, (
            f"the annotator who disagreed on every item scored {dissenter} "
            f"against the majority's {majority}")


# ----------------------------------------------------------------------
# 2. The counter counts work done
# ----------------------------------------------------------------------

class TestTheSkipIsNotCountedAsWork:

    def test_rescoring_the_same_instance_returns_none(self):
        mgr = manager()
        assert mgr.update_user_expertise("u", "i1", "food", "No", "Yes") is False
        assert mgr.update_user_expertise("u", "i1", "food", "No", "Yes") is None, (
            "the already-scored skip returned False, which is what a "
            "DISAGREEMENT returns; the caller could not tell them apart")

    def test_a_disagreement_is_not_a_skip(self):
        mgr = manager()
        result = mgr.update_user_expertise("u", "i1", "food", "No", "Yes")
        assert result is False and result is not None

    def test_the_score_does_not_move_on_a_skip(self):
        mgr = manager()
        mgr.update_user_expertise("u", "i1", "food", "No", "Yes")
        after_first = mgr.get_user_profile("u").get_expertise_score("food")
        mgr.update_user_expertise("u", "i1", "food", "No", "Yes")
        assert mgr.get_user_profile("u").get_expertise_score("food") == after_first


# ----------------------------------------------------------------------
# 3. Scores survive a restart and can be read
# ----------------------------------------------------------------------

class TestScoresArePersistedAndReadable:

    def test_scores_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = manager(d)
            for i in range(4):
                mgr.update_user_expertise("u", f"i{i}", "food", "Yes", "Yes")
            learned = mgr.get_user_profile("u").get_expertise_score("food")
            assert learned > 0.5
            mgr._save_scores()

            ExpertiseManager._instance = None
            restarted = manager(d)
            assert restarted.get_user_profile("u").get_expertise_score("food") == learned, (
                "a study restarted on day two relearned every score from the "
                "neutral 0.5, and nothing said so")

    def test_a_missing_store_says_so_rather_than_failing(self, caplog):
        import logging

        with tempfile.TemporaryDirectory() as d:
            with caplog.at_level(logging.INFO, logger="potato.expertise_manager"):
                mgr = manager(d)
            assert mgr.get_user_profile("u").get_expertise_score("food") == 0.5
            assert any("neutral 0.5" in r.getMessage() for r in caplog.records)

    def test_a_corrupt_store_does_not_stop_the_server(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "expertise_scores.json"), "w") as fh:
                fh.write("{not json")
            mgr = manager(d)
            assert mgr.get_user_profile("u").get_expertise_score("food") == 0.5

    def test_the_admin_route_reports_the_counts_behind_the_score(self):
        """A score of 1.0 from four agreements and a score of 1.0 nothing has
        ever disagreed with look identical and mean different things."""
        from potato.admin import AdminDashboard

        mgr = manager()
        mgr.update_user_expertise("u", "i1", "food", "Yes", "Yes")
        mgr.update_user_expertise("u", "i2", "food", "No", "Yes")

        dashboard = AdminDashboard.__new__(AdminDashboard)
        dashboard.check_admin_access = lambda: True
        import logging
        dashboard.logger = logging.getLogger("test")

        data = dashboard.get_expertise_data()
        assert data["enabled"] is True
        food = data["by_user"]["u"]["food"]
        assert food["agreements"] == 1
        assert food["disagreements"] == 1
        assert food["evaluated"] == 2

    def test_the_route_is_registered_on_the_live_app(self):
        """Views registered only with @app.route never reach `potato start`."""
        import potato.routes as routes

        source = open(routes.__file__, encoding="utf-8").read()
        assert '"/admin/api/expertise"' in source
        assert source.count('"/admin/api/expertise"') >= 2, (
            "the route is decorated but not added in configure_routes(), so "
            "the app `potato start` serves does not have it")


# ----------------------------------------------------------------------
# 4. The key named after the feature is read
# ----------------------------------------------------------------------

class TestCategoryKeyIsReadWhereItIsDocumented:

    def _manager_with(self, config_extra):
        from potato.item_state_management import ItemStateManager, clear_item_state_manager

        clear_item_state_manager()
        with tempfile.TemporaryDirectory() as d:
            config = {"output_annotation_dir": d, "task_dir": d,
                      "annotation_schemes": []}
            config.update(config_extra)
            try:
                return ItemStateManager(config).category_key
            finally:
                clear_item_state_manager()

    def test_the_documented_spelling_is_read(self):
        assert self._manager_with(
            {"category_assignment": {"enabled": True, "category_key": "topic"}}
        ) == "topic", (
            "category_assignment.category_key was documented with an example, "
            "accepted by validation and read by nothing, so a study using it "
            "ran with zero categories and looked healthy")

    def test_the_original_spelling_still_wins(self):
        assert self._manager_with({
            "item_properties": {"category_key": "subject"},
            "category_assignment": {"enabled": True, "category_key": "topic"},
        }) == "subject"

    def test_neither_spelling_means_no_categories(self):
        assert self._manager_with({}) is None


class TestTheDynamicSubKeysAreDocumented:

    @pytest.mark.parametrize("key,default", [
        ("min_annotations_for_consensus", 2),
        ("agreement_method", "majority_vote"),
        ("learning_rate", 0.1),
        ("update_interval_seconds", 60),
        ("base_probability", 0.1),
    ])
    def test_the_key_is_documented_with_the_default_the_code_uses(self, key, default):
        from potato.server_utils.config_key_docs import get_key_doc

        doc = get_key_doc(f"category_assignment.dynamic.{key}")
        assert doc is not None, (
            f"{key} is read and type-checked, and a config author has no way "
            "to learn it exists")
        assert doc.default == default, (
            f"the documented default for {key} is {doc.default!r}, the code "
            f"uses {default!r}")

    @pytest.mark.parametrize("key,default", [
        ("min_annotations_for_consensus", 2),
        ("agreement_method", AgreementMethod.MAJORITY_VOTE),
        ("learning_rate", 0.1),
        ("update_interval_seconds", 60),
        ("base_probability", 0.1),
    ])
    def test_the_code_really_uses_that_default(self, key, default):
        """The documentation is checked against the running object, not
        against another copy of the same claim."""
        mgr = manager()
        assert getattr(mgr, key) == default


# ----------------------------------------------------------------------
# 5. Active learning says whether its ordering is served
# ----------------------------------------------------------------------

class TestReorderingSaysWhetherItIsServed:

    def test_the_stub_strategy_is_disclosed_at_boot(self, caplog):
        import logging

        from potato.item_state_management import ItemStateManager, clear_item_state_manager

        clear_item_state_manager()
        with tempfile.TemporaryDirectory() as d:
            with caplog.at_level(logging.WARNING):
                ItemStateManager({"output_annotation_dir": d, "task_dir": d,
                                  "annotation_schemes": [],
                                  "assignment_strategy": "llm_confidence"})
            clear_item_state_manager()
        assert any("llm_confidence" in r.getMessage() and "random" in r.getMessage()
                   for r in caplog.records), (
            "a strategy that assigns at random sat in the same enum as the "
            "ones that work, disclosed only by a source comment")

    def test_a_working_strategy_is_not_warned_about(self, caplog):
        import logging

        from potato.item_state_management import ItemStateManager, clear_item_state_manager

        clear_item_state_manager()
        with tempfile.TemporaryDirectory() as d:
            with caplog.at_level(logging.WARNING):
                ItemStateManager({"output_annotation_dir": d, "task_dir": d,
                                  "annotation_schemes": [],
                                  "assignment_strategy": "random"})
            clear_item_state_manager()
        assert not [r for r in caplog.records
                    if "not implemented" in r.getMessage()]

    def test_the_confidence_scorer_has_no_unreachable_second_body(self):
        """The `_route_annotation` deletion took the wrong `def` with it and
        left a verbatim copy of the body after the return."""
        import ast

        from potato import active_learning_manager

        tree = ast.parse(open(active_learning_manager.__file__,
                              encoding="utf-8").read())
        names = [node.name for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)]
        assert names.count("_calculate_confidence_scores") == 1
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == "_calculate_confidence_scores"):
                returns = [i for i, stmt in enumerate(node.body)
                           if isinstance(stmt, ast.Return)]
                assert not returns or returns[-1] == len(node.body) - 1, (
                    "there are statements after the final return")


# ----------------------------------------------------------------------
# 6. The shared collapse understands the marker shape too
# ----------------------------------------------------------------------

class TestTheCollapseReadsTheMarkerShape:
    """`answer_collapse` says it is the single definition of "what did the
    participant answer for schema X", used by conditional display logic, the
    export and training grading. It recognised True / 1 / "true" / value ==
    label_name, and not the browser's own "on" -- so a radio answered by the
    simulator, an API caller, a room or a phone collapsed to the string "on"
    and the label was gone from all three.
    """

    def test_a_marker_collapses_to_the_label(self):
        from potato.server_utils.answer_collapse import collapse_entries

        value, winner, _method = collapse_entries(
            [("Sincere", "on")], schema="stance", annotation_type="radio")
        assert value == "Sincere" and winner == "Sincere"

    def test_the_annotation_page_shape_is_unchanged(self):
        from potato.server_utils.answer_collapse import collapse_entries

        assert collapse_entries([("Sincere", "Sincere")], schema="stance",
                                annotation_type="radio")[0] == "Sincere"

    def test_free_text_that_says_on_is_still_the_text(self):
        from potato.server_utils.answer_collapse import collapse_entries

        assert collapse_entries([("text_box", "on")], schema="comment",
                                annotation_type="text")[0] == "on", (
            "a free-text answer of 'on' must not be read as its label name")

    def test_an_unticked_option_is_not_selected(self):
        from potato.server_utils.answer_collapse import collapse_entries

        assert collapse_entries([("a", "on"), ("b", "off")], schema="tags",
                                annotation_type="multiselect")[0] == "a"

    def test_the_wire_payload_canonicalizes_the_same_way(self):
        """The wire shape and the stored shape must not disagree."""
        from potato.server_utils.annotation_keys import canonical_wire_answer

        for payload in ({"stance:Sincere": "on"},
                        {"stance:::Sincere": "on"},
                        {"stance": "on", "stance:Sincere": "Sincere"}):
            assert canonical_wire_answer(payload) == {"stance": "Sincere"}, payload

"""Config validation for page show_when / exit_when and phases.counterbalance."""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_phase_flow_config,
    validate_phase_flow_references,
)


def _cfg(phases, **extra):
    cfg = {"phases": phases}
    cfg.update(extra)
    return cfg


BASE = {
    "order": ["screener", "followup", "annotation"],
    "screener": {"type": "prestudy", "file": "s.json"},
    "followup": {"type": "prestudy", "file": "f.json"},
}


def _with(page, **keys):
    phases = {k: (dict(v) if isinstance(v, dict) else list(v)) for k, v in BASE.items()}
    phases[page].update(keys)
    return phases


class TestShowWhenShape:
    def test_valid_rule_passes(self):
        validate_phase_flow_config(_cfg(_with(
            "followup", show_when=[{"schema": "smoker", "operator": "equals", "value": "Yes"}])))

    @pytest.mark.parametrize("rule", [
        [],
        "smoker == Yes",
        [{"schema": "smoker"}],
        [{"schema": "smoker", "operator": "is", "value": "Yes"}],
        [{"schema": "age", "operator": "gt", "value": "eighteen"}],
    ])
    def test_malformed_rules_refused(self, rule):
        with pytest.raises(ConfigValidationError):
            validate_phase_flow_config(_cfg(_with("followup", show_when=rule)))

    def test_bad_logic_refused(self):
        with pytest.raises(ConfigValidationError, match="logic"):
            validate_phase_flow_config(_cfg(_with(
                "followup", logic="either",
                show_when=[{"schema": "s", "operator": "not_empty"}])))

    def test_annotation_page_cannot_be_skipped(self):
        phases = _with("followup")
        phases["coding"] = {"type": "annotation",
                            "show_when": [{"schema": "s", "operator": "not_empty"}]}
        with pytest.raises(ConfigValidationError, match="annotation phase"):
            validate_phase_flow_config(_cfg(phases))

    def test_condition_reference_requires_declared_factor(self):
        rule = [{"schema": "condition.feedback", "operator": "equals", "value": "none"}]
        with pytest.raises(ConfigValidationError, match="conditions.factors"):
            validate_phase_flow_config(_cfg(_with("followup", show_when=rule)))
        validate_phase_flow_config(_cfg(
            _with("followup", show_when=rule),
            conditions={"factors": {"feedback": ["none", "immediate"]}}))


class TestExitWhenShape:
    def test_valid(self):
        validate_phase_flow_config(_cfg(_with("screener", exit_when={
            "show_when": [{"schema": "age", "operator": "lt", "value": 18}],
            "message": "Adults only."})))

    @pytest.mark.parametrize("spec", [
        "age < 18",
        {"message": "x"},
        {"show_when": [{"schema": "age", "operator": "lt", "value": 18}], "message": 3},
        {"show_when": [{"schema": "age", "operator": "lt", "value": 18}], "redirect": "x"},
    ])
    def test_malformed_refused(self, spec):
        with pytest.raises(ConfigValidationError):
            validate_phase_flow_config(_cfg(_with("screener", exit_when=spec)))


class TestCounterbalanceShape:
    def _phases(self, groups, **types):
        phases = {
            "order": ["a", "b", "c", "annotation"],
            "a": {"type": types.get("a", "instructions"), "file": "a.json"},
            "b": {"type": types.get("b", "instructions"), "file": "b.json"},
            "c": {"type": types.get("c", "instructions"), "file": "c.json"},
            "counterbalance": groups,
        }
        return phases

    def test_valid(self):
        validate_phase_flow_config(_cfg(self._phases(
            [{"pages": ["a", "b", "c"], "method": "latin_square"}])))

    @pytest.mark.parametrize("groups,match", [
        ({"pages": ["a", "b"]}, "must be a list"),
        ([{"pages": ["a"]}], "at least two"),
        ([{"pages": ["a", "z"]}], "no phase defines"),
        ([{"pages": ["a", "b"], "method": "shuffle"}], "method"),
        ([{"pages": ["a", "b"]}, {"pages": ["b", "c"]}], "another group"),
        ([{"pages": ["a", "b"], "blocks": 2}], "unknown key"),
    ])
    def test_refused(self, groups, match):
        with pytest.raises(ConfigValidationError, match=match):
            validate_phase_flow_config(_cfg(self._phases(groups)))

    def test_mixed_types_refused(self):
        with pytest.raises(ConfigValidationError, match="mixes phase types"):
            validate_phase_flow_config(_cfg(self._phases(
                [{"pages": ["a", "b"]}], b="prestudy")))


class TestReferences:
    SCHEMES = {
        "screener": [{"name": "smoker", "annotation_type": "radio"}],
        "followup": [{"name": "packs", "annotation_type": "number"}],
    }

    def test_earlier_question_ok(self):
        validate_phase_flow_references(_cfg(_with(
            "followup", show_when=[{"schema": "smoker", "operator": "equals", "value": "Yes"}])),
            self.SCHEMES)

    def test_unknown_question_refused(self):
        with pytest.raises(ConfigValidationError, match="no phase page asks"):
            validate_phase_flow_references(_cfg(_with(
                "followup", show_when=[{"schema": "smokes", "operator": "equals", "value": "Yes"}])),
                self.SCHEMES)

    def test_question_on_same_page_refused_for_show_when(self):
        with pytest.raises(ConfigValidationError, match="on this page or later"):
            validate_phase_flow_references(_cfg(_with(
                "followup", show_when=[{"schema": "packs", "operator": "gt", "value": 1}])),
                self.SCHEMES)

    def test_question_on_same_page_allowed_for_exit_when(self):
        validate_phase_flow_references(_cfg(_with("screener", exit_when={
            "show_when": [{"schema": "smoker", "operator": "equals", "value": "No"}]})),
            self.SCHEMES)

    def test_later_question_refused_for_exit_when(self):
        with pytest.raises(ConfigValidationError, match="after this page"):
            validate_phase_flow_references(_cfg(_with("screener", exit_when={
                "show_when": [{"schema": "packs", "operator": "gt", "value": 1}]})),
                self.SCHEMES)

    def test_condition_references_skip_question_check(self):
        validate_phase_flow_references(_cfg(_with(
            "followup", show_when=[{"schema": "condition.f", "operator": "equals",
                                    "value": "x"}])), self.SCHEMES)


class TestValidateCatchesBootErrors:
    """Audit 94, E4/E5/J6: `potato validate` passed configs the server then
    refused to start. validate_yaml_structure now reads the phase files."""

    def _dir(self, name, questions):
        import json, os
        from tests.helpers.test_utils import create_test_directory
        d = create_test_directory(name)
        for fname, qs in questions.items():
            with open(os.path.join(d, fname), "w") as f:
                json.dump(qs, f)
        return d

    def _validate(self, phases, d, **extra):
        from potato.server_utils.config_module import validate_phase_flow_files
        cfg = {"phases": phases}
        cfg.update(extra)
        validate_phase_flow_files(cfg, d)

    def test_unknown_question_caught(self):
        d = self._dir("validate_flow_unknown", {
            "s.json": [{"name": "smoker", "annotation_type": "radio", "labels": ["Yes", "No"]}],
            "f.json": [{"name": "packs", "annotation_type": "number"}]})
        phases = {"order": ["s", "f"], "s": {"type": "prestudy", "file": "s.json"},
                  "f": {"type": "prestudy", "file": "f.json",
                        "show_when": [{"schema": "smokes", "operator": "equals", "value": "Yes"}]}}
        with pytest.raises(ConfigValidationError, match="no phase page asks"):
            self._validate(phases, d)

    def test_pin_not_on_page_caught(self):
        d = self._dir("validate_flow_pin", {
            "s.json": [{"name": "q1", "annotation_type": "text"}, {"name": "q2", "annotation_type": "text"}]})
        phases = {"order": ["s"], "s": {"type": "prestudy", "file": "s.json",
                                        "randomize_questions": {"pin_last": ["q9"]}}}
        with pytest.raises(ConfigValidationError, match="not a question on that page"):
            self._validate(phases, d)

    def test_expose_answers_checked(self):
        d = self._dir("validate_flow_expose", {
            "s.json": [{"name": "age", "annotation_type": "number"}],
            "p.json": [{"name": "later", "annotation_type": "text"}]})
        phases = {"order": ["s", "task", "annotation", "p"],
                  "s": {"type": "prestudy", "file": "s.json"},
                  "task": {"type": "prestudy", "_kind": "jspsych", "timeline": "t.js",
                           "expose_answers": ["later"]},
                  "p": {"type": "poststudy", "file": "p.json"}}
        with pytest.raises(ConfigValidationError, match="later page"):
            self._validate(phases, d)
        phases["task"]["expose_answers"] = ["nonexist"]
        with pytest.raises(ConfigValidationError, match="no phase page asks"):
            self._validate(phases, d)
        phases["task"]["expose_answers"] = ["age"]
        self._validate(phases, d)

    def test_condition_level_must_exist(self):
        rule = [{"schema": "condition.arm", "operator": "equals", "value": "c"}]
        with pytest.raises(ConfigValidationError, match="not a level"):
            validate_phase_flow_config(_cfg(_with("followup", show_when=rule),
                                            conditions={"factors": {"arm": ["a", "b"]}}))
        from potato.server_utils.experiment_conditions import validate_condition_references
        with pytest.raises(ConfigValidationError, match="not a level"):
            validate_condition_references(
                {"conditions": {"factors": {"arm": ["a", "b"]}}},
                [{"name": "q", "display_logic": {"show_when": rule}}])

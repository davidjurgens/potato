"""List experiments and randomized response: estimators, validation, gating."""

import math

import pytest

from potato.export.survey_experiment_exporter import (
    estimate_crosswise, estimate_forced, estimate_list)
from potato.server_utils.config_module import ConfigValidationError, _validate_survey_experiment
from potato.server_utils.phase_flow import apply_condition_markup


def test_list_difference_in_means_and_welch_se():
    treat, control = [2, 3, 3, 4], [2, 2, 3, 1]
    r = estimate_list(treat, control)
    assert r["estimate"] == pytest.approx(3.0 - 2.0)
    vt = sum((x - 3.0) ** 2 for x in treat) / 3
    vc = sum((x - 2.0) ** 2 for x in control) / 3
    assert r["se"] == pytest.approx(math.sqrt(vt / 4 + vc / 4))


def test_forced_response_recovers_prevalence():
    # True prevalence 0.3 with p_truth 2/3, p_yes 1/6: expected yes rate
    # = 2/3 * 0.3 + 1/6 = 0.3667. 1100 of 3000 is that rate.
    r = estimate_forced(1100, 3000, 2 / 3, 1 / 6)
    assert r["estimate"] == pytest.approx((1100 / 3000 - 1 / 6) / (2 / 3))
    assert r["estimate"] == pytest.approx(0.3, abs=0.01)


def test_crosswise_recovers_prevalence():
    # pi = 0.2, p = 0.25: P(same) = pi*p + (1-pi)*(1-p) = 0.05 + 0.6 = 0.65
    r = estimate_crosswise(650, 1000, 0.25)
    assert r["estimate"] == pytest.approx(0.2)
    assert r["se"] == pytest.approx(math.sqrt(0.65 * 0.35 / 1000) / 0.5)


@pytest.mark.parametrize("scheme,match", [
    ({"annotation_type": "list_experiment", "items": ["a"]}, "at least two"),
    ({"annotation_type": "list_experiment", "items": ["a", "b"]}, "sensitive_item"),
    ({"annotation_type": "list_experiment", "items": ["a", "b"], "sensitive_item": "s"}, "treatment"),
    ({"annotation_type": "randomized_response", "method": "crosswise",
      "nonsensitive_statement": "x", "nonsensitive_prevalence": 0.5}, "not close to 0.5"),
    ({"annotation_type": "randomized_response", "p_truth": 0.5, "p_yes": 0.3, "p_no": 0.3,
      "randomizer": "r"}, "must be 1"),
    ({"annotation_type": "randomized_response", "p_truth": 0.5, "p_yes": 0.25, "p_no": 0.25},
     "describe the randomizer"),
])
def test_validation(scheme, match):
    with pytest.raises(ConfigValidationError, match=match):
        _validate_survey_experiment(scheme, "annotation_schemes[0]")


def test_condition_only_elements_are_removed_for_other_levels():
    html = '<ul><li>a</li><li data-condition-only="g=t">secret</li></ul>'
    assert "secret" not in apply_condition_markup(html, {"g": "c"})
    assert "secret" not in apply_condition_markup(html, None)
    kept = apply_condition_markup(html, {"g": "t"})
    assert "secret" in kept and "data-condition-only" not in kept


def test_export_reads_survey_page_answers(monkeypatch):
    """List experiments usually run on a survey page, so the answers come from
    phase_responses, with the group from each participant's flow record."""
    import csv
    import os
    from potato.export import survey_experiment_exporter as sx
    from potato.export.base import ExportContext
    from tests.helpers.test_utils import create_test_directory
    scheme = {"annotation_type": "list_experiment", "name": "lists", "items": ["a", "b", "c"],
              "sensitive_item": "s", "treatment": {"factor": "g", "level": "t"}}
    groups = {"u1": "t", "u2": "t", "u3": "c", "u4": "c", "u5": "c"}
    counts = {"u1": "3", "u2": "2", "u3": "1", "u4": "2", "u5": "9"}     # u5 out of range
    monkeypatch.setattr(sx, "_conditions_by_user", lambda ctx: {u: {"g": g} for u, g in groups.items()})
    responses = [{"user_id": u, "schema": "lists", "label_name": "number", "value": v}
                 for u, v in counts.items()]
    out = create_test_directory("survey_experiments_phase")
    ctx = ExportContext(config={}, annotations=[], items={}, schemas=[scheme], output_dir=out,
                        phase_responses=responses)
    assert sx.SurveyExperimentExporter().export(ctx, out).success
    row = next(csv.DictReader(open(os.path.join(out, "survey_experiments.csv"))))
    assert float(row["estimate"]) == pytest.approx(2.5 - 1.5)
    assert row["excluded"] == "1" and row["n_control"] == "2"


def _example_context(out, phase_responses):
    import os
    import yaml
    from potato.export.base import ExportContext
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "examples", "advanced", "sensitive-questions", "config.yaml")
    with open(path) as f:
        config = yaml.safe_load(f)
    config["config_file"] = path
    return ExportContext(config=config, annotations=[], items={},
                         schemas=config["annotation_schemes"], output_dir=out,
                         phase_responses=phase_responses)


def test_export_finds_the_shipped_examples_survey_page_schemes(monkeypatch):
    """The example's designs are on a prestudy page, not in annotation_schemes."""
    import csv
    import os
    from potato.export import survey_experiment_exporter as sx
    from tests.helpers.test_utils import create_test_directory
    out = create_test_directory("survey_experiments_example")
    groups = {"u1": "treatment", "u2": "treatment", "u3": "control", "u4": "control"}
    monkeypatch.setattr(sx, "_conditions_by_user",
                        lambda ctx: {u: {"list_group": g} for u, g in groups.items()})
    responses = [{"user_id": u, "schema": "lists", "label_name": "number", "value": v}
                 for u, v in {"u1": "3", "u2": "2", "u3": "1", "u4": "2"}.items()]
    ctx = _example_context(out, responses)
    ok, why = sx.SurveyExperimentExporter().can_export(ctx)
    assert ok, why
    assert sx.SurveyExperimentExporter().export(ctx, out).success
    rows = {r["schema"]: r for r in csv.DictReader(open(os.path.join(out, "survey_experiments.csv")))}
    assert set(rows) == {"lists", "cheating_crosswise", "tax_forced"}
    assert float(rows["lists"]["estimate"]) == pytest.approx(2.5 - 1.5)


@pytest.mark.parametrize("bad", ["abc", "", "nan", "inf", "4", "-3", "1.5"])
def test_every_unusable_count_is_counted_as_excluded(monkeypatch, bad):
    """A control participant's count must be a whole number in 0..3."""
    import csv
    import os
    from potato.export import survey_experiment_exporter as sx
    from potato.export.base import ExportContext
    from tests.helpers.test_utils import create_test_directory
    scheme = {"annotation_type": "list_experiment", "name": "lists", "items": ["a", "b", "c"],
              "sensitive_item": "s", "treatment": {"factor": "g", "level": "t"}}
    groups = {"u1": "t", "u2": "t", "u3": "c", "u4": "c", "u5": "c"}
    monkeypatch.setattr(sx, "_conditions_by_user", lambda ctx: {u: {"g": g} for u, g in groups.items()})
    counts = {"u1": "3", "u2": "2", "u3": "1", "u4": "2"}
    responses = [{"user_id": u, "schema": "lists", "label_name": "number", "value": v}
                 for u, v in counts.items()]
    # u5 answers on an item page, which stores {label: value} under the scheme.
    anns = [{"user_id": "u5", "instance_id": "i1", "labels": {"lists": {"number": bad}}}]
    out = create_test_directory("survey_experiments_excluded")
    ctx = ExportContext(config={}, annotations=anns, items={}, schemas=[scheme], output_dir=out,
                        phase_responses=responses)
    assert sx.SurveyExperimentExporter().export(ctx, out).success
    row = next(csv.DictReader(open(os.path.join(out, "survey_experiments.csv"))))
    if bad == "":
        assert row["excluded"] == "0"                   # no answer is not an answer
    else:
        assert row["excluded"] == "1", bad
    assert row["n_control"] == "2"


def test_a_non_numeric_survey_page_count_is_counted_as_excluded(monkeypatch):
    import csv
    import os
    from potato.export import survey_experiment_exporter as sx
    from potato.export.base import ExportContext
    from tests.helpers.test_utils import create_test_directory
    scheme = {"annotation_type": "list_experiment", "name": "lists", "items": ["a", "b", "c"],
              "sensitive_item": "s", "treatment": {"factor": "g", "level": "t"}}
    monkeypatch.setattr(sx, "_conditions_by_user", lambda ctx: {"u1": {"g": "c"}, "u2": {"g": "c"}})
    responses = [{"user_id": "u1", "schema": "lists", "label_name": "number", "value": "abc"},
                 {"user_id": "u2", "schema": "lists", "label_name": "number", "value": "2"}]
    out = create_test_directory("survey_experiments_excluded_phase")
    ctx = ExportContext(config={}, annotations=[], items={}, schemas=[scheme], output_dir=out,
                        phase_responses=responses)
    assert sx.SurveyExperimentExporter().export(ctx, out).success
    row = next(csv.DictReader(open(os.path.join(out, "survey_experiments.csv"))))
    assert row["excluded"] == "1" and row["n_control"] == "1"

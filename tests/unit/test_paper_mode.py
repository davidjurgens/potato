"""Unit tests for Paper Mode (potato/paper/)."""

import json
import os

import pytest

from potato.paper.collect import collect_project
from potato.paper.latex import latex_escape, render_report
from potato.paper.metrics import cohen_kappa, compute_metrics, interpret_alpha
from tests.helpers.test_utils import create_test_directory


def build_project(test_dir, states, schemes=None, data_items=6):
    """Write a config.yaml + user_state.json files into test_dir."""
    import yaml
    schemes = schemes or [
        {"annotation_type": "radio", "name": "sentiment",
         "description": "d", "labels": ["Pos", "Neg"]},
        {"annotation_type": "span", "name": "spans",
         "description": "d", "labels": ["X"]},
    ]
    os.makedirs(os.path.join(test_dir, "data"), exist_ok=True)
    with open(os.path.join(test_dir, "data", "items.json"), "w") as f:
        for k in range(data_items):
            f.write(json.dumps({"id": f"i{k}", "text": f"item {k}"}) + "\n")
    config = {
        "annotation_task_name": "Unit & Test_Task",
        "output_annotation_dir": "out/",
        "data_files": ["data/items.json"],
        "annotation_schemes": schemes,
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    for user, labels in states.items():
        user_dir = os.path.join(test_dir, "out", user)
        os.makedirs(user_dir, exist_ok=True)
        state = {
            "user_id": user,
            "instance_id_to_label_to_value": {
                iid: [[{"schema": "sentiment", "name": v}, v]]
                for iid, v in labels.items()
            },
        }
        with open(os.path.join(user_dir, "user_state.json"), "w") as f:
            json.dump(state, f)
    return config_path


class TestCohenKappa:
    def test_perfect_agreement(self):
        assert cohen_kappa([("A", "A"), ("B", "B"), ("A", "A")]) == 1.0

    def test_hand_computed_case(self):
        # 2 coders, 10 items: observed agreement 0.7,
        # A: 6 A's / 4 B's ; B: 5 A's / 5 B's -> pe = 0.6*0.5 + 0.4*0.5 = 0.5
        # kappa = (0.7 - 0.5) / 0.5 = 0.4
        pairs = [("A", "A")] * 4 + [("B", "B")] * 3 + \
                [("A", "B")] * 2 + [("B", "A")] * 1
        assert cohen_kappa(pairs) == pytest.approx(0.4)

    def test_empty_returns_none(self):
        assert cohen_kappa([]) is None

    def test_single_category_degenerate(self):
        assert cohen_kappa([("A", "A"), ("A", "A")]) == 1.0


class TestInterpretAlpha:
    def test_thresholds(self):
        assert interpret_alpha(0.9) == "acceptable agreement"
        assert interpret_alpha(0.7) == "tentative agreement"
        assert interpret_alpha(0.3) == "low agreement"
        assert interpret_alpha(None) == "not computable"


class TestLatexEscape:
    def test_specials(self):
        assert latex_escape("A&B_C%D#E") == r"A\&B\_C\%D\#E"
        assert latex_escape("50%") == r"50\%"
        assert latex_escape("x^2 ~ y") == r"x\textasciicircum{}2 \textasciitilde{} y"


class TestCollect:
    def test_collects_records_and_skips_noncategorical(self):
        test_dir = create_test_directory("paper_collect")
        config_path = build_project(test_dir, {
            "u1": {"i0": "Pos", "i1": "Neg"},
            "u2": {"i0": "Pos"},
        })
        project = collect_project(config_path)
        assert sorted(project.annotators) == ["u1", "u2"]
        assert len(project.records) == 3
        assert [s["name"] for s in project.schemes] == ["sentiment"]
        assert [s["name"] for s in project.skipped_schemes] == ["spans"]
        assert project.total_items == 6
        assert project.instance_ids == ["i0", "i1"]

    def test_empty_output_dir(self):
        test_dir = create_test_directory("paper_collect_empty")
        config_path = build_project(test_dir, {})
        project = collect_project(config_path)
        assert project.records == []


class TestMetrics:
    def test_full_metrics(self):
        test_dir = create_test_directory("paper_metrics")
        config_path = build_project(test_dir, {
            "u1": {"i0": "Pos", "i1": "Pos", "i2": "Neg", "i3": "Neg"},
            "u2": {"i0": "Pos", "i1": "Pos", "i2": "Neg", "i3": "Pos"},
        })
        metrics = compute_metrics(collect_project(config_path))
        assert metrics["n_annotators"] == 2
        assert metrics["n_annotated_instances"] == 4
        assert metrics["n_label_records"] == 8

        scheme = metrics["schemes"][0]
        assert scheme["distribution"] == {"Pos": 5, "Neg": 3}
        assert scheme["multi_annotated_units"] == 4
        # observed agreement 3/4; hand-check kappa:
        # u1: 2 Pos/2 Neg; u2: 3 Pos/1 Neg -> pe = .5*.75+.5*.25 = .5 -> k = .5
        assert scheme["pairwise_kappa"]["mean"] == pytest.approx(0.5)
        assert scheme["alpha"] is not None
        assert -1.0 <= scheme["alpha"] <= 1.0

    def test_no_overlap_no_agreement(self):
        test_dir = create_test_directory("paper_metrics_solo")
        config_path = build_project(test_dir, {"u1": {"i0": "Pos", "i1": "Neg"}})
        metrics = compute_metrics(collect_project(config_path))
        scheme = metrics["schemes"][0]
        assert scheme["alpha"] is None
        assert scheme["pairwise_kappa"]["mean"] is None
        assert metrics["instances_single_annotated"] == 2


class TestRender:
    def test_report_files_and_content(self):
        test_dir = create_test_directory("paper_render")
        config_path = build_project(test_dir, {
            "u1": {"i0": "Pos", "i1": "Pos", "i2": "Neg"},
            "u2": {"i0": "Pos", "i1": "Neg", "i2": "Neg"},
        })
        metrics = compute_metrics(collect_project(config_path))
        out_dir = os.path.join(test_dir, "paper_export")
        paths = render_report(metrics, out_dir)

        tex = open(paths["tex"]).read()
        # Escaping of the task name with & and _
        assert r"Unit \& Test\_Task" in tex
        # Cut-paste block markers
        for block in ("paragraph-dataset-description", "paragraph-annotation-methods",
                      "table-distribution-sentiment", "table-annotators",
                      "table-agreement", "paragraph-limitations"):
            assert f"%% === BLOCK: {block} ===" in tex
        # booktabs + citations present
        assert r"\toprule" in tex
        assert r"\citep{pei2022potato}" in tex
        # Non-categorical scheme noted
        assert "spans" in tex

        bib = open(paths["bib"]).read()
        assert "pei2022potato" in bib and "krippendorff2004content" in bib

        assert os.path.exists(os.path.join(paths["tables_dir"],
                                           "distribution_sentiment.csv"))
        summary = json.load(open(paths["summary"]))
        assert summary["n_annotators"] == 2


class TestCLI:
    def test_end_to_end_anonymizes(self, capsys):
        from potato.paper.__main__ import main
        test_dir = create_test_directory("paper_cli")
        config_path = build_project(test_dir, {
            "real_name_1": {"i0": "Pos", "i1": "Neg"},
            "real_name_2": {"i0": "Pos", "i1": "Neg"},
        })
        out_dir = os.path.join(test_dir, "paper_export")
        assert main([config_path, "-o", out_dir]) == 0
        tex = open(os.path.join(out_dir, "paper.tex")).read()
        assert "real_name_1" not in tex
        assert "A1" in tex and "A2" in tex

    def test_no_annotations_exits_nonzero(self, capsys):
        from potato.paper.__main__ import main
        test_dir = create_test_directory("paper_cli_empty")
        config_path = build_project(test_dir, {})
        assert main([config_path, "-o", os.path.join(test_dir, "x")]) == 1

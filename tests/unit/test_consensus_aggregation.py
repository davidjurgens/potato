"""Consensus aggregation (export format ``consensus``).

The round trip imports tests/data/zooniverse/aggregation/ -- an invented
penguin-count project, five volunteers, image 1000 x 500 pixels -- with the
Zooniverse importer's annotators kept, writes the Potato project, builds the
export context the CLI builds, aggregates and checks every number against a
value worked out by hand (in the comments).

Fixture, subject 9001:
  T0 (single):   Yes, Yes, Yes, Yes, No
  T1 (multiple): vol1 Ice+Water, vol2 Ice, vol3 Ice+Rock, vol4 Ice, vol5 Water
  T2 (drawing), "Adult" points in pixels:
      vol1 (100,100) (800,400); vol2 (102,98) (805,402);
      vol3 (98,101) (500,250); vol4 (101,103) (797,398); vol5 draws nothing
  T2 "Nest" boxes [x, y, w, h]: vol1 [200,100,100,50], vol2 [205,105,100,50],
      vol3 [190,95,110,60], vol4 [600,300,50,50]
Subject 9002: T0 Yes, No, Yes, No; T1 Rock x4; vol1 one point (300,300).
Subject 9003: vol1 alone: T0 Yes, T1 Ice, one box [10,20,30,40].
Subject 9004: nobody.
"""

import csv
import json
from pathlib import Path

import pytest
import yaml

from potato.aggregation.boxes import box_consensus, group_boxes
from potato.aggregation.config import (ConsensusConfigError, ConsensusSettings,
                                       parse_consensus_config)
from potato.aggregation.engine import aggregate
from potato.aggregation.points import cluster_points, dbscan_labels
from potato.aggregation.questions import categorical_consensus
from potato.export.base import ExportContext
from potato.export.registry import export_registry
from tests.helpers.test_utils import create_test_directory

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "zooniverse" / "aggregation"


# ------------------------------------------------------------ round trip

@pytest.fixture(scope="module")
def project():
    from potato.importers.projects.writer import write_project
    from potato.importers.projects.zooniverse import ZooniverseImporter

    result = ZooniverseImporter().parse_path(FIXTURE)
    out = create_test_directory("consensus_zooniverse_roundtrip")
    write_project(result, out, str(FIXTURE), keep_annotators=True)
    return Path(out)


def _export(project_dir: Path, options=None, extra_config=None):
    from potato.export.cli import build_export_context

    config_path = project_dir / "config.yaml"
    if extra_config is not None:
        config = yaml.safe_load(config_path.read_text())
        config.update(extra_config)
        config_path = project_dir / "config_consensus.yaml"
        config_path.write_text(yaml.safe_dump(config))
    context = build_export_context(str(config_path))
    out = project_dir / ("consensus_" + "_".join(f"{k}{v}" for k, v in (options or {}).items()))
    result = export_registry.export("consensus", context, str(out), options or {})
    assert result.success, result.errors
    return out, result


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _find(rows, **match):
    hits = [r for r in rows if all(str(r[k]) == str(v) for k, v in match.items())]
    assert len(hits) == 1, (match, hits)
    return hits[0]


class TestZooniverseRoundTrip:
    @pytest.fixture(scope="class")
    def exported(self, project):
        return _export(project, {"eps": "10", "eps_unit": "pixels"})

    def test_imported_items_carry_the_image_size(self, project):
        rows = [json.loads(line) for line in
                (project / "data" / "aggregation.jsonl").read_text().splitlines()]
        sizes = {r["id"]: (r.get("image_width"), r.get("image_height")) for r in rows}
        assert sizes["9001"] == (1000, 500)
        # Nobody classified 9004, so no classification recorded its size.
        assert sizes["9004"] == (None, None)

    def test_single_answer_question(self, exported):
        out, _ = exported
        rows = _rows(out / "consensus_questions.csv")
        # 9001: Yes 4 of 5 = 0.8, which meets the default threshold 0.8.
        q = _find(rows, instance_id="9001", schema="T0")
        assert (q["n_classifiers"], q["top_answer"], q["top_count"]) == ("5", "Yes", "4")
        assert float(q["top_fraction"]) == pytest.approx(0.8)
        assert q["status"] == "retired"
        # 9002: Yes 2, No 2 -> a tie, needs review.
        q = _find(rows, instance_id="9002", schema="T0")
        assert q["status"] == "needs_review" and q["tied"] == "Yes;No"
        assert float(q["top_fraction"]) == pytest.approx(0.5)
        # 9003: one classifier, fewer than min_classifiers (2).
        q = _find(rows, instance_id="9003", schema="T0")
        assert q["n_classifiers"] == "1" and q["status"] == "needs_review"
        assert "min_classifiers" in q["reason"]
        assert not [r for r in rows if r["instance_id"] == "9004"]

    def test_vote_fractions(self, exported):
        out, _ = exported
        votes = _rows(out / "consensus_votes.csv")
        t0 = {r["answer"]: (int(r["count"]), float(r["fraction"]))
              for r in votes if r["instance_id"] == "9001" and r["schema"] == "T0"}
        # Every option is listed, in the workflow's order, including Unsure at 0.
        assert list(t0) == ["Yes", "No", "Unsure"]
        assert t0 == {"Yes": (4, 0.8), "No": (1, 0.2), "Unsure": (0, 0.0)}
        t1 = {r["answer"]: (int(r["count"]), float(r["fraction"]))
              for r in votes if r["instance_id"] == "9001" and r["schema"] == "T1"}
        # Share of the 5 classifiers who ticked each box.
        assert t1 == {"Ice": (4, 0.8), "Water": (2, 0.4), "Rock": (1, 0.2)}

    def test_multiselect_status(self, exported):
        out, _ = exported
        rows = _rows(out / "consensus_questions.csv")
        # 9001: Water ticked by 2 of 5 (0.4) -- neither 0.8 ticked nor 0.8 unticked.
        q = _find(rows, instance_id="9001", schema="T1")
        assert q["status"] == "needs_review" and "Water" in q["reason"]
        assert "Ice" not in q["reason"] and "Rock" not in q["reason"]
        # 9002: all four ticked Rock and nothing else: every option decided.
        q = _find(rows, instance_id="9002", schema="T1")
        assert q["status"] == "retired" and q["top_answer"] == "Rock"
        assert float(q["top_fraction"]) == 1.0

    def test_point_clusters_in_pixels(self, exported):
        out, _ = exported
        rows = [r for r in _rows(out / "consensus_points.csv")
                if r["instance_id"] == "9001" and r["label"] == "Adult"]
        assert len(rows) == 2
        a = _find(rows, cluster="0")
        # (100+102+98+101)/4 = 100.25, (100+98+101+103)/4 = 100.5
        assert float(a["x_px"]) == pytest.approx(100.25)
        assert float(a["y_px"]) == pytest.approx(100.5)
        assert float(a["x"]) == pytest.approx(0.10025)
        assert float(a["y"]) == pytest.approx(0.201)
        assert (a["size"], a["n_annotators"]) == ("4", "4")
        assert a["annotators"] == "vol1;vol2;vol3;vol4"
        b = _find(rows, cluster="1")
        # centre (2402/3, 400); squared distances 0.444, 22.778, 17.444
        assert float(b["x_px"]) == pytest.approx(800.6667, abs=1e-4)
        assert float(b["y_px"]) == pytest.approx(400.0)
        assert (b["size"], b["n_annotators"]) == ("3", "3")
        assert float(b["spread_px"]) == pytest.approx(3.6818, abs=1e-4)
        # sample variances: x 32.667/2, y 8/2; covariance 16/2
        assert float(b["var_x"]) == pytest.approx(16.3333, abs=1e-4)
        assert float(b["var_y"]) == pytest.approx(4.0)
        assert float(b["cov_xy"]) == pytest.approx(8.0)
        # vol3's (500, 250) is noise.
        assert a["label_noise"] == "1" and a["label_points"] == "8"
        assert a["n_classifiers"] == "4"

    def test_a_lone_point_is_noise(self, exported):
        out, _ = exported
        row = _find(_rows(out / "consensus_points.csv"), instance_id="9002", label="Adult")
        assert row["cluster"] == "" and row["label_noise"] == "1"
        assert row["note"].startswith("no cluster")

    def test_box_consensus(self, exported):
        out, _ = exported
        rows = [r for r in _rows(out / "consensus_boxes.csv") if r["instance_id"] == "9001"]
        assert len(rows) == 2
        g = _find(rows, group="0")
        # Median edges: left 200, top 100, right 300, bottom 155.
        assert [float(g[k]) for k in ("x_px", "y_px", "width_px", "height_px")] == \
            pytest.approx([200, 100, 100, 55])
        assert [float(g[k]) for k in ("x", "y", "width", "height")] == \
            pytest.approx([0.2, 0.2, 0.1, 0.11])
        # IoU to consensus: vol1 5000/5500, vol2 4750/5750, vol3 5500/6600.
        assert float(g["mean_iou"]) == pytest.approx(
            (5000 / 5500 + 4750 / 5750 + 5500 / 6600) / 3, abs=1e-6)
        assert float(g["min_iou"]) == pytest.approx(4750 / 5750, abs=1e-6)
        # 3 of the 4 volunteers who drew on 9001 (vol5 drew nothing).
        assert (g["support"], g["n_classifiers"]) == ("3", "4")
        assert float(g["support_fraction"]) == pytest.approx(0.75)
        assert g["annotators"] == "vol1;vol2;vol3"
        lone = _find(rows, group="1")
        assert (lone["support"], lone["annotators"], float(lone["mean_iou"])) == \
            ("1", "vol4", 1.0)

    def test_one_classifier_one_box(self, exported):
        out, _ = exported
        g = _find(_rows(out / "consensus_boxes.csv"), instance_id="9003")
        assert [float(g[k]) for k in ("x_px", "y_px", "width_px", "height_px")] == \
            pytest.approx([10, 20, 30, 40])
        assert (g["support"], g["n_classifiers"], float(g["support_fraction"])) == \
            ("1", "1", 1.0)

    def test_json_and_stats(self, exported):
        out, result = exported
        data = json.loads((out / "consensus.json").read_text())
        assert data["settings"]["points"] == {"eps": 10.0, "eps_unit": "pixels",
                                              "min_samples": 2}
        assert result.stats["retired"] == 2      # 9001 T0, 9002 T1
        assert result.stats["needs_review"] == 4
        assert result.stats["point_clusters"] == 2
        assert result.stats["box_groups"] == 3

    def test_fraction_eps_gives_the_same_clusters(self, project):
        # Default eps 0.02 of each axis: A's widest pair is 0.01005 apart,
        # B's 0.0113, and A to the noise point is far more.
        out, _ = _export(project)
        rows = [r for r in _rows(out / "consensus_points.csv")
                if r["instance_id"] == "9001"]
        assert sorted(r["size"] for r in rows) == ["3", "4"]

    def test_config_block_sets_the_parameters(self, project):
        out, _ = _export(project, extra_config={"consensus_aggregation": {
            "agreement_threshold": 0.5, "min_classifiers": 1,
            "boxes": {"iou_threshold": 0.95}}})
        rows = _rows(out / "consensus_questions.csv")
        assert _find(rows, instance_id="9003", schema="T0")["status"] == "retired"
        # With 0.5, Water (0.4 ticked, 0.6 unticked) is decided.
        assert _find(rows, instance_id="9001", schema="T1")["status"] == "retired"
        # No pair of nests overlaps by 0.95: every box is its own group.
        boxes = [r for r in _rows(out / "consensus_boxes.csv") if r["instance_id"] == "9001"]
        assert sorted(r["support"] for r in boxes) == ["1", "1", "1", "1"]


# ------------------------------------------------------------ pieces

def test_dbscan_matches_scikit_learn():
    """Same labels as sklearn.cluster.DBSCAN (what panoptes_aggregation calls),
    up to the numbering of clusters, on random data with dense clumps."""
    import numpy as np
    from sklearn.cluster import DBSCAN

    rng = np.random.default_rng(7)
    for trial in range(40):
        centres = rng.uniform(0, 100, size=(rng.integers(1, 5), 2))
        pts = np.vstack([c + rng.normal(0, 2, size=(rng.integers(1, 8), 2)) for c in centres]
                        + [rng.uniform(0, 100, size=(rng.integers(0, 5), 2))])
        eps, min_samples = float(rng.uniform(1, 6)), int(rng.integers(1, 5))
        ours = dbscan_labels(pts.tolist(), eps, min_samples)
        theirs = DBSCAN(eps=eps, min_samples=min_samples).fit(pts).labels_.tolist()
        assert [l == -1 for l in ours] == [l == -1 for l in theirs], trial
        pairs = {(a, b) for a, b in zip(ours, theirs) if a != -1}
        assert len({a for a, _ in pairs}) == len(pairs) == len({b for _, b in pairs}), trial


def test_min_samples_counts_the_point_itself():
    # Two points 1 apart: with min_samples 2 each has 2 neighbours (itself and
    # the other) and they cluster; with 3 they are noise.
    assert dbscan_labels([[0, 0], [1, 0]], eps=1.5, min_samples=2) == [0, 0]
    assert dbscan_labels([[0, 0], [1, 0]], eps=1.5, min_samples=3) == [-1, -1]
    assert dbscan_labels([[0, 0]], eps=1.0, min_samples=1) == [0]
    assert dbscan_labels([], eps=1.0, min_samples=2) == []


def test_border_point_joins_the_first_cluster():
    # Cores at 0 and 4 (with partners at -1 and 5); the point at 2 is within
    # eps=2 of both cores but has only 3 neighbours, fewer than min_samples 4.
    pts = [[-1, 0], [0, 0], [-0.5, 0], [2, 0], [4, 0], [5, 0], [4.5, 0]]
    labels = dbscan_labels(pts, eps=2.0, min_samples=4)
    assert labels[3] == labels[0] == 0 and labels[4] == 1


def test_pixel_eps_without_a_size_is_refused():
    with pytest.raises(ValueError):
        cluster_points([("a", 0.1, 0.1)], eps=5, eps_unit="pixels", min_samples=1, size=None)


def test_grouping_keeps_one_box_per_annotator():
    # Two overlapping boxes from one person never pair with each other.
    boxes = [("a", [0, 0, 10, 10]), ("a", [1, 1, 10, 10]), ("b", [0, 0, 10, 10])]
    groups = group_boxes(boxes, 0.5)
    assert sorted(map(sorted, groups)) == [[0, 2], [1]]


def test_grouping_does_not_chain():
    # b overlaps a and c at 0.6 each, but a and c barely overlap: one group is
    # {b and one of them}, not all three.
    a, b, c = [0, 0, 10, 10], [2.5, 0, 10, 10], [5, 0, 10, 10]
    groups = box_consensus([("u1", a), ("u2", b), ("u3", c)], iou_threshold=0.55,
                           n_classifiers=3)
    assert sorted(g["support"] for g in groups) == [1, 2]


def test_ties_and_threshold_edges():
    scheme = {"name": "q", "annotation_type": "radio", "labels": ["A", "B"]}
    tie = categorical_consensus(scheme, {"u1": "A", "u2": "B"}, 0.5, 1)
    assert tie["status"] == "needs_review" and tie["tied"] == ["A", "B"]
    agree = categorical_consensus(scheme, {"u1": "B", "u2": "B"}, 1.0, 2)
    assert (agree["status"], agree["top_answer"], agree["top_fraction"]) == \
        ("retired", "B", 1.0)
    multi = {"name": "m", "annotation_type": "multiselect", "labels": ["x", "y"]}
    # 1 of 5 ticked y: 0.8 unticked, exactly the threshold, so decided.
    answers = {f"u{i}": frozenset({"x"}) for i in range(4)}
    answers["u4"] = frozenset({"x", "y"})
    assert categorical_consensus(multi, answers, 0.8, 1)["status"] == "retired"


# ------------------------------------------------------------ degenerate projects

def _record(user, iid, labels=None, image=None):
    return {"instance_id": iid, "user_id": user, "labels": labels or {},
            "image_annotations": image or {}, "_changes": []}


RADIO = {"name": "q", "annotation_type": "radio", "labels": ["A", "B"]}
IMAGE = {"name": "img", "annotation_type": "image_annotation", "tools": ["landmark", "bbox"],
         "labels": ["P"]}


def test_one_annotator_one_item():
    rec = _record("solo", "1", {"q": {"A": "A"}}, {"img": [
        {"type": "landmark", "label": "P", "coordinates": {"x": 0.5, "y": 0.5}},
        {"type": "bbox", "label": "P",
         "coordinates": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}}]})
    out = aggregate({}, [rec], {}, [RADIO, IMAGE], ConsensusSettings())
    q = out["questions"][0]
    assert (q["n_classifiers"], q["top_answer"], q["status"]) == (1, "A", "needs_review")
    # One point with min_samples 2 is noise; one box is a group of one.
    assert out["points"][0]["clusters"] == [] and out["points"][0]["noise"] == 1
    assert out["boxes"][0]["groups"][0]["support_fraction"] == 1.0
    one = aggregate({}, [rec], {}, [RADIO, IMAGE],
                    ConsensusSettings(min_classifiers=1, min_samples=1))
    assert one["questions"][0]["status"] == "retired"
    assert one["points"][0]["clusters"][0]["size"] == 1
    assert one["points"][0]["clusters"][0]["var_x"] is None


def test_no_points_and_all_agree():
    recs = [_record(u, "1", {"q": {"B": "B"}}, {"img": []}) for u in ("a", "b", "c")]
    out = aggregate({}, recs, {}, [RADIO, IMAGE], ConsensusSettings())
    assert out["questions"][0]["status"] == "retired"
    assert out["questions"][0]["answers"] == [
        {"answer": "A", "count": 0, "fraction": 0.0},
        {"answer": "B", "count": 3, "fraction": 1.0}]
    assert out["points"] == [] and out["boxes"] == []


def test_exporter_on_a_project_with_no_marks():
    out_dir = create_test_directory("consensus_no_marks")
    ctx = ExportContext(config={}, annotations=[_record("a", "1", {}, {"img": []})],
                        items={}, schemas=[IMAGE], output_dir=out_dir)
    result = export_registry.export("consensus", ctx, str(Path(out_dir) / "x"))
    assert result.success
    assert _rows(Path(out_dir) / "x" / "consensus_points.csv") == []
    assert _rows(Path(out_dir) / "x" / "consensus_boxes.csv") == []


def test_exporter_refuses_with_a_reason():
    ctx = ExportContext(config={}, annotations=[], items={},
                        schemas=[{"name": "t", "annotation_type": "text"}], output_dir="")
    ok, reason = export_registry.get("consensus").can_export(ctx)
    assert not ok and "radio" in reason
    ctx.schemas = [RADIO]
    assert export_registry.get("consensus").can_export(ctx) == (False, "No annotations to export")


def test_pixel_eps_without_image_size_warns_and_keeps_going():
    recs = [_record(u, "1", image={"img": [
        {"type": "landmark", "label": "P", "coordinates": {"x": 0.5, "y": 0.5}}]})
        for u in ("a", "b")]
    out = aggregate({}, recs, {}, [IMAGE], ConsensusSettings(eps=5, eps_unit="pixels"))
    assert out["points"][0]["clusters"] == []
    assert "image size unknown" in out["points"][0]["skipped"]
    assert any("image size" in w for w in out["warnings"])


def test_shapes_other_than_points_and_boxes_are_counted():
    recs = [_record("a", "1", image={"img": [
        {"type": "polygon", "label": "P", "coordinates": [{"x": 0, "y": 0}, {"x": 1, "y": 0},
                                                           {"x": 1, "y": 1}]}]})]
    out = aggregate({}, recs, {}, [IMAGE], ConsensusSettings())
    assert out["not_aggregated"] == {"polygon": 1}
    assert any("1 polygon" in w for w in out["warnings"])


def test_pixel_shaped_marks_use_the_item_size():
    # Older flat pixel objects (no `coordinates`) need the item's size.
    recs = [_record(u, "1", image={"img": [{"type": "bbox", "label": "P", "x": 100,
                                            "y": 50, "width": 200, "height": 100}]})
            for u in ("a", "b")]
    out = aggregate({}, recs, {"1": {"image_width": 1000, "image_height": 500}}, [IMAGE],
                    ConsensusSettings())
    g = out["boxes"][0]["groups"][0]
    assert (g["x"], g["y"], g["width"], g["height"]) == pytest.approx((0.1, 0.1, 0.2, 0.2))
    assert g["support"] == 2


# ------------------------------------------------------------ config

@pytest.mark.parametrize("block, needle", [
    ({"agreement_threshold": 0}, "agreement_threshold"),
    ({"agreement_threshold": 1.5}, "agreement_threshold"),
    ({"agreement_threshold": "high"}, "agreement_threshold"),
    ({"min_classifiers": 0}, "min_classifiers"),
    ({"min_classifiers": 2.5}, "min_classifiers"),
    ({"points": {"eps": 0}}, "points.eps"),
    ({"points": {"eps": 5}}, "eps_unit"),
    ({"points": {"eps_unit": "metres"}}, "eps_unit"),
    ({"points": {"min_samples": 0}}, "min_samples"),
    ({"points": {"radius": 3}}, "radius"),
    ({"boxes": {"iou_threshold": 1.2}}, "iou_threshold"),
    ({"boxes": []}, "boxes"),
    ({"threshold": 0.7}, "threshold"),
    ({"schemes": []}, "schemes"),
])
def test_bad_config_values_name_the_key(block, needle):
    with pytest.raises(ConsensusConfigError) as info:
        parse_consensus_config({"consensus_aggregation": block})
    assert needle in str(info.value) and "consensus_aggregation" in str(info.value)


def test_options_override_the_block():
    s = parse_consensus_config({"consensus_aggregation": {"agreement_threshold": 0.6,
                                                          "points": {"eps": 0.05}}},
                               {"eps": "7", "eps_unit": "pixels", "schemes": "T0, T2"})
    assert (s.agreement_threshold, s.eps, s.eps_unit, s.schemes) == \
        (0.6, 7.0, "pixels", ("T0", "T2"))
    with pytest.raises(ConsensusConfigError, match="unknown consensus option"):
        parse_consensus_config({}, {"epsilon": "3"})


def test_config_load_rejects_a_bad_block_and_an_unknown_scheme():
    from potato.server_utils.config_module import (ConfigValidationError,
                                                   validate_yaml_structure)

    base = {"item_properties": {"id_key": "id", "text_key": "text"}, "task_dir": ".",
            "output_annotation_dir": "out", "annotation_task_name": "t",
            "data_files": ["d.json"],
            "annotation_schemes": [{"name": "q", "annotation_type": "radio",
                                    "description": "Q", "labels": ["A", "B"]}]}
    with pytest.raises(ConfigValidationError, match="consensus_aggregation.points.eps_unit"):
        validate_yaml_structure({**base, "consensus_aggregation": {
            "points": {"eps_unit": "metres"}}})
    with pytest.raises(ConfigValidationError, match="does not declare: nope"):
        validate_yaml_structure({**base, "consensus_aggregation": {"schemes": ["nope"]}})


def test_points_match_panoptes_aggregation_when_installed():
    """Parity with Zooniverse's own reducer, for anyone who has it installed
    (it is not a Potato dependency). Checked against panoptes_aggregation 5.3.1."""
    reducer = pytest.importorskip(
        "panoptes_aggregation.reducers.point_reducer_dbscan").point_reducer_dbscan
    data = {"vol1": [(100, 100), (800, 400)], "vol2": [(102, 98), (805, 402)],
            "vol3": [(98, 101), (500, 250)], "vol4": [(101, 103), (797, 398)]}
    extracts = [{"frame0": {"T2_tool0_x": [p[0] for p in pts],
                            "T2_tool0_y": [p[1] for p in pts]}} for pts in data.values()]
    for eps, min_samples in [(10, 2), (5, 2), (10, 3)]:
        frame = reducer(extracts, user_id=list(data), eps=eps,
                        min_samples=min_samples)["frame0"]
        theirs = sorted(zip(frame.get("T2_tool0_clusters_x", []),
                            frame.get("T2_tool0_clusters_y", []),
                            frame.get("T2_tool0_clusters_count", [])))
        ours = cluster_points([(u, x / 1000, y / 500) for u, pts in data.items()
                               for x, y in pts],
                              eps=eps, eps_unit="pixels", min_samples=min_samples,
                              size=(1000, 500))
        mine = sorted((c["x_px"], c["y_px"], c["size"]) for c in ours["clusters"])
        assert [t[2] for t in theirs] == [m[2] for m in mine]
        for t, m in zip(theirs, mine):
            assert m[:2] == pytest.approx(t[:2])


def test_slider_summary():
    slider = {"name": "s", "annotation_type": "slider", "min_value": 0, "max_value": 10}
    recs = [_record(u, "1", {"s": {"slider": v}}) for u, v in (("a", "7"), ("b", "6"), ("c", "2"))]
    recs.append(_record("d", "2", {"s": {"slider": "4"}}))
    out = aggregate({}, recs, {}, [slider], ConsensusSettings())
    first, second = out["numeric"]
    # 7, 6, 2: mean 5, median 6, sd sqrt((4 + 1 + 9) / 2) = sqrt(7)
    assert (first["n"], first["mean"], first["median"], first["min"], first["max"]) == \
        (3, 5.0, 6.0, 2.0, 7.0)
    assert first["sd"] == pytest.approx(7 ** 0.5)
    assert (second["instance_id"], second["n"], second["sd"]) == ("2", 1, None)

"""
Gold standards and attention checks over drawn answers.

``_compare_responses`` compared every answer by string/set equality. Two
annotators never produce byte-identical geometry, so an image gold standard was
unpassable no matter how well the annotator drew — the feature existed but could
only ever record failures. Grading now goes through the same overlap comparator
as training practice questions.

Every "passes" case is paired with a "fails" case, so a comparator that returned
a constant could not satisfy the file.
"""

from __future__ import annotations

import json

import pytest

from potato.quality_control import QualityControlConfig, QualityControlManager


def blob(*objects):
    return json.dumps(list(objects))


def box(x, y, w=0.2, h=0.2, label="cat"):
    return {"type": "bbox", "label": label,
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def polygon(points, label="road"):
    return {"type": "polygon", "label": label,
            "coordinates": [{"x": px, "y": py} for px, py in points]}


@pytest.fixture
def manager(tmp_path):
    return QualityControlManager({}, str(tmp_path))


class TestGeometryGrading:
    def test_identical_geometry_passes(self, manager):
        gold = {"objects": blob(box(0.1, 0.1))}
        assert manager._compare_responses(gold, dict(gold)) is True

    def test_slightly_different_boundary_passes(self, manager):
        """The whole point: a few pixels of difference is not a failure."""
        gold = {"objects": blob(box(0.100, 0.100))}
        drawn = {"objects": blob(box(0.105, 0.103))}
        assert gold["objects"] != drawn["objects"], "fixture must not be identical"
        assert manager._compare_responses(gold, drawn) is True

    def test_box_somewhere_else_fails(self, manager):
        gold = {"objects": blob(box(0.1, 0.1))}
        drawn = {"objects": blob(box(0.8, 0.8))}
        assert manager._compare_responses(gold, drawn) is False

    def test_right_place_wrong_label_fails(self, manager):
        """Calling a cat a dog is exactly what a gold standard should catch."""
        gold = {"objects": blob(box(0.1, 0.1, label="cat"))}
        drawn = {"objects": blob(box(0.1, 0.1, label="dog"))}
        assert manager._compare_responses(gold, drawn) is False

    def test_missing_an_object_fails(self, manager):
        gold = {"objects": blob(box(0.1, 0.1), box(0.6, 0.6))}
        drawn = {"objects": blob(box(0.1, 0.1))}
        assert manager._compare_responses(gold, drawn) is False

    def test_extra_object_fails(self, manager):
        gold = {"objects": blob(box(0.1, 0.1))}
        drawn = {"objects": blob(box(0.1, 0.1), box(0.6, 0.6))}
        assert manager._compare_responses(gold, drawn) is False

    def test_polygons_are_graded_too(self, manager):
        gold = {"regions": blob(polygon([(0.1, 0.1), (0.4, 0.1), (0.4, 0.4)]))}
        near = {"regions": blob(polygon([(0.105, 0.1), (0.4, 0.105), (0.4, 0.4)]))}
        far = {"regions": blob(polygon([(0.6, 0.6), (0.9, 0.6), (0.9, 0.9)]))}
        assert manager._compare_responses(gold, near) is True
        assert manager._compare_responses(gold, far) is False


class TestToleranceIsConfigurable:
    def test_default_is_the_coco_convention(self, manager):
        assert manager._geometry_tolerance() == 0.5

    def test_tolerance_read_from_gold_standards_block(self, tmp_path):
        config = {"gold_standards": {"enabled": True,
                                     "geometry_iou_tolerance": 0.9}}
        m = QualityControlManager(config, str(tmp_path))
        assert m._geometry_tolerance() == 0.9

    def test_tolerance_read_from_quality_control_block(self, tmp_path):
        config = {"quality_control": {"geometry_iou_tolerance": 0.25}}
        m = QualityControlManager(config, str(tmp_path))
        assert m._geometry_tolerance() == 0.25

    def test_non_numeric_tolerance_is_ignored_not_fatal(self, tmp_path):
        config = {"quality_control": {"geometry_iou_tolerance": "loose"}}
        m = QualityControlManager(config, str(tmp_path))
        assert m._geometry_tolerance() == 0.5

    def test_strict_tolerance_rejects_a_loose_match(self, tmp_path):
        """Same pair of shapes, opposite verdicts either side of the threshold."""
        gold = {"objects": blob(box(0.10, 0.10, 0.20, 0.20))}
        drawn = {"objects": blob(box(0.13, 0.13, 0.20, 0.20))}

        loose = QualityControlManager(
            {"quality_control": {"geometry_iou_tolerance": 0.5}}, str(tmp_path))
        strict = QualityControlManager(
            {"quality_control": {"geometry_iou_tolerance": 0.95}}, str(tmp_path))

        assert loose._compare_responses(gold, drawn) is True
        assert strict._compare_responses(gold, drawn) is False


class TestNonGeometryIsUnaffected:
    """The regression risk: geometry detection must not swallow normal answers."""

    def test_matching_string_answer_still_passes(self, manager):
        assert manager._compare_responses({"s": "yes"}, {"s": "yes"}) is True

    def test_differing_string_answer_still_fails(self, manager):
        assert manager._compare_responses({"s": "yes"}, {"s": "no"}) is False

    def test_multiselect_list_still_set_compares(self, manager):
        assert manager._compare_responses(
            {"tags": ["a", "b"]}, {"tags": ["b", "a"]}) is True
        assert manager._compare_responses(
            {"tags": ["a", "b"]}, {"tags": ["a"]}) is False

    def test_a_plain_list_of_dicts_without_type_is_not_geometry(self, manager):
        """`looks_like_geometry` keys on a "type" field; nothing else qualifies."""
        from potato.server_utils.training_grading import looks_like_geometry

        assert not looks_like_geometry(json.dumps([{"label": "cat"}]))
        assert looks_like_geometry(blob(box(0.1, 0.1)))


class TestEndToEndGoldStandard:
    def test_validate_gold_response_accepts_a_near_miss(self, tmp_path):
        """Through the public API, not just the comparator."""
        m = QualityControlManager(
            {"gold_standards": {"enabled": True}}, str(tmp_path))
        m.gold_labels["img_1"] = {"objects": blob(box(0.10, 0.10))}

        result = m.validate_gold_response(
            "annotator_1", "img_1", {"objects": blob(box(0.105, 0.102))})
        assert result is not None
        assert m.gold_results["annotator_1"][-1].correct is True

    def test_validate_gold_response_rejects_a_wrong_answer(self, tmp_path):
        m = QualityControlManager(
            {"gold_standards": {"enabled": True}}, str(tmp_path))
        m.gold_labels["img_1"] = {"objects": blob(box(0.10, 0.10))}

        m.validate_gold_response(
            "annotator_2", "img_1", {"objects": blob(box(0.80, 0.80))})
        assert m.gold_results["annotator_2"][-1].correct is False

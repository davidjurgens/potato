"""
Agreement for 3D objects, segment schemas and agent-trace steps.

These types were absent from the dispatcher's map, so ``/admin/iaa`` skipped
them as unsupported -- including temporal_grounding and tiered_annotation,
which store the same ``{"segments": [...]}`` blob audio and video do. Each
test pairs perfect agreement with total disagreement, so a report that
gathered nothing (and returned no number) cannot pass either.
"""

import json

import pytest

from potato.server_utils.iaa import dispatcher
from potato.server_utils.iaa.dispatcher import SchemaKind, classify_schema
from tests.unit.test_iaa_dispatcher_gathering import run_report


def _cuboid(cx, label="car"):
    return {"type": "cuboid_3d", "label": label,
            "coordinates": {"center": [cx, 0, 0], "size": [2, 2, 2]}}


def _spatial(*objs):
    return {("cloud", "_data"): json.dumps(list(objs))}


def _segments(scheme, *segs):
    return {(scheme, "_data"): json.dumps({"segments": [
        {"start_time": a, "end_time": b, "label": lab} for a, b, lab in segs]})}


def _steps(scheme, labels):
    return {(scheme, "_data"): json.dumps({"steps": [
        {"index": i, "reward": r} for i, r in enumerate(labels)]})}


@pytest.mark.parametrize("atype,kind", [
    ("spatial_annotation", SchemaKind.SPATIAL),
    ("temporal_grounding", SchemaKind.SEGMENTS),
    ("tiered_annotation", SchemaKind.SEGMENTS),
    ("process_reward", SchemaKind.TRACE),
    ("trajectory_eval", SchemaKind.TRACE),
    ("tool_call_review", SchemaKind.TRACE),
    ("failure_attribution", SchemaKind.TRACE),
    ("gui_trajectory", SchemaKind.TRACE),
])
def test_types_are_classified(atype, kind):
    assert classify_schema({"annotation_type": atype, "name": "x"}) == kind


class TestSpatial:
    SCHEME = {"annotation_type": "spatial_annotation", "name": "cloud"}

    def test_same_boxes_agree(self):
        m = run_report({"a": {"i1": _spatial(_cuboid(0)), "i2": _spatial(_cuboid(5))},
                        "b": {"i1": _spatial(_cuboid(0)), "i2": _spatial(_cuboid(5))}},
                       self.SCHEME)
        assert m["mean_agreement"] == pytest.approx(1.0)
        assert m["n_items"] == 2 and m["n_pairs"] == 2

    def test_disjoint_boxes_disagree(self):
        m = run_report({"a": {"i1": _spatial(_cuboid(0))},
                        "b": {"i1": _spatial(_cuboid(50))}}, self.SCHEME)
        assert m["mean_agreement"] == pytest.approx(0.0)

    def test_same_place_different_label_counts_half(self):
        m = run_report({"a": {"i1": _spatial(_cuboid(0, "car"))},
                        "b": {"i1": _spatial(_cuboid(0, "truck"))}}, self.SCHEME)
        assert m["mean_agreement"] == pytest.approx(0.5)


@pytest.mark.parametrize("atype", ["temporal_grounding", "tiered_annotation"])
class TestSegments:
    def test_same_segments_agree(self, atype):
        scheme = {"annotation_type": atype, "name": "seg"}
        same = _segments("seg", (0.0, 2.0, "x"), (5.0, 6.0, "y"))
        m = run_report({"a": {"i1": same}, "b": {"i1": same}}, scheme)
        assert m["mean_agreement"] == pytest.approx(1.0)

    def test_disjoint_segments_disagree(self, atype):
        scheme = {"annotation_type": atype, "name": "seg"}
        m = run_report({"a": {"i1": _segments("seg", (0.0, 1.0, "x"))},
                        "b": {"i1": _segments("seg", (10.0, 11.0, "x"))}}, scheme)
        assert m["mean_agreement"] == pytest.approx(0.0)


class TestTrace:
    SCHEME = {"annotation_type": "process_reward", "name": "pr"}

    def test_same_step_labels_agree(self):
        labels = [[1, -1, 1, 1], [-1, 1, 1, -1], [1, 1, -1, 1]]
        a = {f"i{k}": _steps("pr", lab) for k, lab in enumerate(labels)}
        m = run_report({"a": a, "b": dict(a)}, self.SCHEME)
        assert m["percent_agreement"] == pytest.approx(1.0)
        assert m["cohen_kappa"] == pytest.approx(1.0)
        assert m["alpha_nominal"] == pytest.approx(1.0)
        assert m["n_steps"] == 4

    def test_opposite_step_labels_disagree(self):
        labels = [[1, -1, 1, 1], [-1, 1, 1, -1], [1, 1, -1, 1]]
        a = {f"i{k}": _steps("pr", lab) for k, lab in enumerate(labels)}
        b = {f"i{k}": _steps("pr", [-x for x in lab]) for k, lab in enumerate(labels)}
        m = run_report({"a": a, "b": b}, self.SCHEME)
        assert m["percent_agreement"] == pytest.approx(0.0)
        assert m["alpha_nominal"] < 0


def test_metrics_are_declared_for_each_new_kind():
    for kind in (SchemaKind.SPATIAL, SchemaKind.SEGMENTS, SchemaKind.TRACE):
        assert dispatcher.metrics_for_schema({"annotation_type": "x"}, kind=kind.value)


def test_engine_scores_a_machine_as_the_report_scores_a_person():
    """The engine's families read values with the same parsers, so a machine
    that drew the second annotator's boxes has that annotator's agreement."""
    from potato.labeling_engine.families import family_for
    from potato.labeling_engine.schemes import SchemeSpec
    fam = family_for(SchemeSpec.from_scheme(
        {"annotation_type": "spatial_annotation", "name": "cloud"}))
    human = fam.human_value({"_data": json.dumps([_cuboid(0, "car")])})
    machine = fam.human_value({"_data": json.dumps([_cuboid(0, "truck")])})
    assert 1.0 - fam.loss(machine, human) == pytest.approx(0.5)

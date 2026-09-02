"""
The IAA dispatcher must actually gather annotations.

``UserState.instance_id_to_label_to_value[iid]`` is **flat**, keyed by ``Label``
objects: ``{Label(schema, name): value}``. ``_gather_labels`` used to look the
schema up by *name* in that mapping. A string never hashes to a ``Label``, so
``dict.get`` returned ``None`` without ever calling ``Label.__eq__`` — and every
metric in the module reported NaN over zero items, for every schema of every
kind, for as long as the overlap-IAA report has existed.

These tests pin the fix. Each agreement test ships with the opposite case
(perfect vs. total disagreement) so a gatherer that silently returns nothing
cannot pass: NaN is neither 1.0 nor 0.0.
"""

from __future__ import annotations

import json
import math
import pathlib

import pytest

from potato.item_state_management import Label
from potato.server_utils import annotation_values
from potato.server_utils.iaa import dispatcher


# ---------------------------------------------------------------------------
# Fakes that mirror the real storage shape
# ---------------------------------------------------------------------------

class FakeUserState:
    """Holds the flat ``{Label: value}`` container a real UserState holds."""

    def __init__(self, per_item):
        # per_item: {instance_id: {(schema, name): value}}
        self.store = {
            iid: {Label(schema, name): value
                  for (schema, name), value in entries.items()}
            for iid, entries in per_item.items()
        }

    def get_label_annotations(self, instance_id):
        return self.store.get(instance_id, {})

    def get_span_annotations(self, instance_id):
        return {}


class FakeUSM:
    def __init__(self, states):
        self.states = states

    def get_user_state(self, uid):
        return self.states.get(uid)


class FakeItem:
    def get_text(self):
        return "the quick brown fox jumps over the lazy dog"


class FakeISM:
    def __init__(self, iids, annotators):
        self._items = {i: FakeItem() for i in iids}
        self.instance_id_to_instance = self._items
        self.instance_annotators = {i: set(annotators) for i in iids}

    def _get_annotator_cap_for_item(self, iid):
        return 2

    # The accessor API the dispatcher uses. See potato/item_store.py: consumers
    # go through these so a paged backend is possible, and a fake that only
    # exposed the dict would be testing an interface nothing calls any more.
    def find_item(self, iid):
        return self._items.get(iid)

    def iter_items(self):
        return iter(self._items.items())

    def get_instance_ids(self):
        return list(self._items)


def run_report(per_user_items, scheme):
    """Build a two-annotator report for one schema."""
    iids = sorted({iid for items in per_user_items.values() for iid in items})
    states = {uid: FakeUserState(items) for uid, items in per_user_items.items()}
    ism = FakeISM(iids, list(per_user_items))
    report = dispatcher.compute_overlap_iaa(
        ism, FakeUSM(states), {"annotation_schemes": [scheme]}
    )
    return report["schemas"][scheme["name"]]["metrics"]


# ---------------------------------------------------------------------------
# The fake is faithful to real on-disk state
# ---------------------------------------------------------------------------

class TestStorageShapeIsReal:
    """Guard against a fake that tests a shape the product never produces."""

    def test_real_user_state_file_regroups(self):
        path = pathlib.Path(
            "demo/22-adjudication/annotation_output/ann_bob/user_state.json")
        if not path.exists():
            pytest.skip("demo annotation output not present")

        raw = json.loads(path.read_text())["instance_id_to_label_to_value"]
        iid, entries = next(iter(raw.items()))
        # On disk: [[{"schema":..., "name":...}, value], ...] -> Label-keyed dict
        restored = {Label(k["schema"], k["name"]): v for k, v in entries}

        grouped = annotation_values.group_by_schema(restored)
        assert grouped, f"nothing regrouped for {iid}"
        assert all(isinstance(v, dict) for v in grouped.values())

    def test_string_lookup_on_label_keyed_dict_misses(self):
        """The exact defect, stated as a fact about Python dicts."""
        stored = {Label("sentiment", "positive"): True}
        assert stored.get("sentiment") is None
        assert annotation_values.group_by_schema(stored) == {
            "sentiment": {"positive": True}
        }


# ---------------------------------------------------------------------------
# Categorical
# ---------------------------------------------------------------------------

RADIO = {"name": "sentiment", "annotation_type": "radio",
         "labels": ["positive", "negative"]}


class TestNominalGathering:
    def test_perfect_agreement_is_one(self):
        agree = {
            "i1": {("sentiment", "positive"): True},
            "i2": {("sentiment", "negative"): True},
            "i3": {("sentiment", "positive"): True},
        }
        metrics = run_report({"alice": agree, "bob": agree}, RADIO)
        assert metrics["n_items"] == 3
        assert metrics["n_annotators"] == 2
        assert metrics["alpha_nominal"] == pytest.approx(1.0)

    def test_total_disagreement_is_not_one(self):
        alice = {
            "i1": {("sentiment", "positive"): True},
            "i2": {("sentiment", "negative"): True},
            "i3": {("sentiment", "positive"): True},
        }
        bob = {
            "i1": {("sentiment", "negative"): True},
            "i2": {("sentiment", "positive"): True},
            "i3": {("sentiment", "negative"): True},
        }
        metrics = run_report({"alice": alice, "bob": bob}, RADIO)
        assert metrics["n_items"] == 3
        assert metrics["alpha_nominal"] < 0.0

    def test_likert_reads_the_number_from_the_label_name(self):
        """Likert stores {"2": "2"} — the answer is in the name, not the value."""
        scheme = {"name": "quality", "annotation_type": "likert", "size": 5}
        alice = {"i1": {("quality", "2"): "2"}, "i2": {("quality", "4"): "4"}}
        bob = {"i1": {("quality", "2"): "2"}, "i2": {("quality", "4"): "4"}}
        metrics = run_report({"alice": alice, "bob": bob}, scheme)
        assert metrics["n_items"] == 2
        assert metrics["alpha_ordinal"] == pytest.approx(1.0)

    def test_continuous_reads_the_number_from_the_value(self):
        """Sliders put the number in the value, not the label name."""
        scheme = {"name": "score", "annotation_type": "slider"}
        alice = {"i1": {("score", "slider"): "3.5"},
                 "i2": {("score", "slider"): "7.5"}}
        bob = {"i1": {("score", "slider"): "3.5"},
               "i2": {("score", "slider"): "7.5"}}
        metrics = run_report({"alice": alice, "bob": bob}, scheme)
        assert metrics["n_items"] == 2
        assert metrics["pearson_r"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

IMAGE = {"name": "objects", "annotation_type": "image_annotation",
         "labels": ["cat", "dog"]}


def blob(*objects):
    return json.dumps(list(objects))


def box(x, y, w, h, label="cat"):
    return {"type": "bbox", "label": label,
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


class TestGeometryGathering:
    def test_image_annotation_is_no_longer_unsupported(self):
        assert dispatcher.classify_schema(IMAGE) is dispatcher.SchemaKind.GEOMETRY
        assert dispatcher.metrics_for_schema(IMAGE)

    def test_identical_boxes_agree(self):
        same = {"i1": {("objects", "_data"): blob(box(0.1, 0.1, 0.2, 0.2))},
                "i2": {("objects", "_data"): blob(box(0.5, 0.5, 0.3, 0.3))}}
        metrics = run_report({"alice": same, "bob": same}, IMAGE)
        assert metrics["n_items"] == 2
        assert metrics["mean_agreement"] == pytest.approx(1.0)
        assert metrics["detection_f1"] == pytest.approx(1.0)
        assert metrics["mean_object_count_diff"] == pytest.approx(0.0)

    def test_disjoint_boxes_disagree(self):
        alice = {"i1": {("objects", "_data"): blob(box(0.0, 0.0, 0.2, 0.2))}}
        bob = {"i1": {("objects", "_data"): blob(box(0.7, 0.7, 0.2, 0.2))}}
        metrics = run_report({"alice": alice, "bob": bob}, IMAGE)
        assert metrics["n_items"] == 1
        assert metrics["mean_agreement"] == pytest.approx(0.0)
        assert metrics["detection_f1"] == pytest.approx(0.0)

    def test_missed_object_lowers_detection_but_not_matched_iou(self):
        """The distinction the four-number report exists to make."""
        alice = {"i1": {("objects", "_data"): blob(
            box(0.1, 0.1, 0.2, 0.2), box(0.6, 0.6, 0.2, 0.2))}}
        bob = {"i1": {("objects", "_data"): blob(box(0.1, 0.1, 0.2, 0.2))}}
        metrics = run_report({"alice": alice, "bob": bob}, IMAGE)
        # The box they both drew is perfect...
        assert metrics["mean_matched_iou"] == pytest.approx(1.0)
        # ...but one of three object-slots went unmatched.
        assert metrics["detection_f1"] == pytest.approx(2 / 3)
        assert metrics["mean_agreement"] < 1.0
        assert metrics["mean_object_count_diff"] == pytest.approx(1.0)

    def test_both_empty_is_agreement(self):
        empty = {"i1": {("objects", "_data"): "[]"}}
        metrics = run_report({"alice": empty, "bob": empty}, IMAGE)
        assert metrics["mean_agreement"] == pytest.approx(1.0)

    def test_one_empty_is_disagreement(self):
        alice = {"i1": {("objects", "_data"): blob(box(0.1, 0.1, 0.2, 0.2))}}
        bob = {"i1": {("objects", "_data"): "[]"}}
        metrics = run_report({"alice": alice, "bob": bob}, IMAGE)
        assert metrics["mean_agreement"] == pytest.approx(0.0)
        assert metrics["detection_f1"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Temporal (audio and video share one payload shape)
# ---------------------------------------------------------------------------

AUDIO = {"name": "events", "annotation_type": "audio_annotation",
         "labels": ["speech", "music"]}
VIDEO = {"name": "events", "annotation_type": "video_annotation",
         "labels": ["speech", "music"]}


def segments(*triples):
    return json.dumps({"segments": [
        {"start_time": s, "end_time": e, "label": lab} for s, e, lab in triples
    ]})


class TestTemporalGathering:
    @pytest.mark.parametrize("scheme", [AUDIO, VIDEO])
    def test_classified_as_temporal(self, scheme):
        assert dispatcher.classify_schema(scheme) is dispatcher.SchemaKind.TEMPORAL

    @pytest.mark.parametrize("scheme", [AUDIO, VIDEO])
    def test_identical_segments_agree(self, scheme):
        same = {"i1": {("events", "_data"): segments((0.0, 2.0, "speech"),
                                                     (5.0, 7.0, "music"))}}
        metrics = run_report({"alice": same, "bob": same}, scheme)
        assert metrics["mean_agreement"] == pytest.approx(1.0)
        assert metrics["detection_f1"] == pytest.approx(1.0)

    @pytest.mark.parametrize("scheme", [AUDIO, VIDEO])
    def test_disjoint_segments_disagree(self, scheme):
        alice = {"i1": {("events", "_data"): segments((0.0, 2.0, "speech"))}}
        bob = {"i1": {("events", "_data"): segments((10.0, 12.0, "speech"))}}
        metrics = run_report({"alice": alice, "bob": bob}, scheme)
        assert metrics["mean_agreement"] == pytest.approx(0.0)

    def test_partial_overlap_above_threshold_matches(self):
        alice = {"i1": {("events", "_data"): segments((0.0, 10.0, "speech"))}}
        bob = {"i1": {("events", "_data"): segments((2.0, 12.0, "speech"))}}
        metrics = run_report({"alice": alice, "bob": bob}, AUDIO)
        # intersection 8s, union 12s -> IoU 2/3, above the 0.5 match threshold
        assert metrics["mean_matched_iou"] == pytest.approx(2 / 3, abs=1e-6)
        assert metrics["detection_f1"] == pytest.approx(1.0)

    def test_weak_overlap_below_threshold_is_not_a_match(self):
        """A 1/3 overlap is a detection disagreement, not a sloppy match."""
        alice = {"i1": {("events", "_data"): segments((0.0, 10.0, "speech"))}}
        bob = {"i1": {("events", "_data"): segments((5.0, 15.0, "speech"))}}
        metrics = run_report({"alice": alice, "bob": bob}, AUDIO)
        assert metrics["detection_f1"] == pytest.approx(0.0)
        assert math.isnan(metrics["mean_matched_iou"])
        assert metrics["mean_agreement"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Free text stays absent rather than being scored
# ---------------------------------------------------------------------------

class TestIncomparableStaysAbsent:
    def test_textbox_is_not_reported(self):
        scheme = {"name": "why", "annotation_type": "textbox"}
        alice = {"i1": {("why", "text"): "because the cat is orange"}}
        bob = {"i1": {("why", "text"): "it looked like a cat to me"}}
        iids = ["i1"]
        states = {"alice": FakeUserState(alice), "bob": FakeUserState(bob)}
        report = dispatcher.compute_overlap_iaa(
            FakeISM(iids, ["alice", "bob"]), FakeUSM(states),
            {"annotation_schemes": [scheme]},
        )
        assert "why" not in report["schemas"]


# ---------------------------------------------------------------------------
# Control: the metrics themselves were never broken
# ---------------------------------------------------------------------------

class TestControl:
    def test_alpha_works_when_fed_directly(self):
        """If this failed, the tests above would prove nothing about gathering."""
        from potato.server_utils.iaa import alpha

        rows = [("alice", i, v) for i, v in
                [("i1", "pos"), ("i2", "neg"), ("i3", "pos")]]
        rows += [("bob", i, v) for i, v in
                 [("i1", "pos"), ("i2", "neg"), ("i3", "pos")]]
        assert alpha.krippendorff_alpha(rows, level="nominal") == pytest.approx(1.0)

    def test_nan_is_distinguishable_from_agreement(self):
        """The old behaviour returned NaN; assert NaN would fail these tests."""
        assert not (math.nan == pytest.approx(1.0))
        assert not (math.nan == pytest.approx(0.0))

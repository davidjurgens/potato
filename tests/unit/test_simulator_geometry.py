"""
Simulated annotators can draw.

Before this, ``simulator/annotation_strategies`` had no ``image_annotation``
branch, so an image project could not be piloted, load-tested, or used to check
that the agreement statistics behave. Every other modality could.

The closing tests are the reason this exists: feed simulated annotators of
*known* competence through the real IAA dispatcher and assert the reported
agreement tracks the competence that produced it. A statistic nobody has
validated against a known ground truth is a number, not a measurement.
"""

from __future__ import annotations

import json
import random

import pytest

from potato.simulator import geometry_strategy
from potato.simulator.annotation_strategies import RandomStrategy
from potato.server_utils.iaa import dispatcher

from tests.unit.test_iaa_dispatcher_gathering import (
    FakeISM, FakeUSM, FakeUserState,
)


IMAGE_SCHEMA = {
    "name": "objects",
    "annotation_type": "image_annotation",
    "labels": ["cat", "dog", "bird"],
    "tools": ["bbox"],
}


class FixedCompetence:
    def __init__(self, accuracy):
        self.accuracy = accuracy

    def get_accuracy(self):
        return self.accuracy

    def should_be_correct(self):
        return random.random() < self.accuracy

    def select_wrong_answer(self, correct, options):
        return correct


def gold_blob(n=3, seed=0):
    rng = random.Random(seed)
    return json.dumps(
        geometry_strategy.random_objects(["cat", "dog"], ["bbox"], rng,
                                         count_range=(n, n))
    )


# ---------------------------------------------------------------------------
# Shape generation obeys the client contract
# ---------------------------------------------------------------------------

class TestGeneratedShapes:
    def test_produces_the_data_key_the_client_posts(self):
        out = RandomStrategy().generate_annotation(
            {"text": "x"}, IMAGE_SCHEMA, FixedCompetence(1.0))
        assert list(out) == ["objects:::_data"], (
            "must use the ::: separator; a single colon parses as a label name")

    def test_value_is_a_json_list_of_contract_objects(self):
        out = RandomStrategy().generate_annotation(
            {"text": "x"}, IMAGE_SCHEMA, FixedCompetence(1.0))
        objects = json.loads(out["objects:::_data"])
        assert objects
        for obj in objects:
            assert obj["type"] in ("bbox", "polygon", "landmark")
            assert obj["label"] in IMAGE_SCHEMA["labels"]
            assert "coordinates" in obj

    def test_coordinates_are_normalized(self):
        rng = random.Random(7)
        for obj in geometry_strategy.random_objects(["cat"], ["bbox"], rng,
                                                    count_range=(20, 20)):
            c = obj["coordinates"]
            assert 0.0 <= c["x"] <= 1.0 and 0.0 <= c["y"] <= 1.0
            assert c["x"] + c["width"] <= 1.0001
            assert c["y"] + c["height"] <= 1.0001

    def test_every_tool_is_buildable(self):
        rng = random.Random(3)
        for tool in ("bbox", "polygon", "landmark"):
            objs = geometry_strategy.random_objects(["cat"], [tool], rng,
                                                    count_range=(2, 2))
            assert all(o["type"] == tool for o in objs)

    def test_generated_objects_survive_the_exporter_contract(self):
        """Shapes must normalize the same way the client's do."""
        from potato.export.cv_utils import normalize_annotation_object

        rng = random.Random(11)
        for obj in geometry_strategy.random_objects(["cat"], ["bbox"], rng,
                                                    count_range=(5, 5)):
            canonical = normalize_annotation_object(obj, 640, 480)
            assert canonical, f"exporter rejected simulator output: {obj}"
            assert canonical.get("bbox")


# ---------------------------------------------------------------------------
# The noise model
# ---------------------------------------------------------------------------

class TestNoiseModel:
    def test_perfect_accuracy_never_drops_or_mislabels(self):
        levels = geometry_strategy.noise_levels(1.0)
        assert levels["drop"] == 0.0
        assert levels["mislabel"] == 0.0
        assert levels["spurious"] == 0.0

    def test_perfect_accuracy_still_jitters(self):
        """A simulator that reproduced geometry exactly would validate nothing."""
        assert geometry_strategy.noise_levels(1.0)["jitter"] > 0.0

    def test_worse_accuracy_means_more_of_every_error(self):
        good = geometry_strategy.noise_levels(0.9)
        bad = geometry_strategy.noise_levels(0.3)
        for key in ("jitter", "drop", "mislabel", "spurious"):
            assert bad[key] > good[key], key

    def test_jitter_preserves_type_and_label(self):
        obj = {"type": "bbox", "label": "cat",
               "coordinates": {"x": 0.4, "y": 0.4, "width": 0.2, "height": 0.2}}
        moved = geometry_strategy.jitter_object(obj, 0.05, random.Random(1))
        assert moved["type"] == "bbox"
        assert moved["label"] == "cat"
        assert moved["coordinates"] != obj["coordinates"]

    def test_jitter_keeps_boxes_inside_the_image(self):
        rng = random.Random(5)
        edge = {"type": "bbox", "label": "cat",
                "coordinates": {"x": 0.95, "y": 0.0, "width": 0.05, "height": 0.05}}
        for _ in range(100):
            c = geometry_strategy.jitter_object(edge, 0.2, rng)["coordinates"]
            assert 0.0 <= c["x"] and c["x"] + c["width"] <= 1.0001
            assert 0.0 <= c["y"] and c["y"] + c["height"] <= 1.0001

    def test_a_bad_annotator_drops_objects(self):
        rng = random.Random(2)
        reference = geometry_strategy.random_objects(["cat"], ["bbox"], rng,
                                                     count_range=(10, 10))
        counts = [
            len(geometry_strategy.perturb_objects(reference, ["cat"], 0.2, rng))
            for _ in range(30)
        ]
        assert min(counts) < 10, "a low-competence annotator should miss objects"

    def test_a_perfect_annotator_keeps_every_object(self):
        rng = random.Random(2)
        reference = geometry_strategy.random_objects(["cat"], ["bbox"], rng,
                                                     count_range=(10, 10))
        for _ in range(30):
            assert len(
                geometry_strategy.perturb_objects(reference, ["cat"], 1.0, rng)
            ) == 10


# ---------------------------------------------------------------------------
# Round trip: simulated competence -> reported agreement
# ---------------------------------------------------------------------------

def simulate_report(accuracy, n_items=25, seed=0):
    """Two annotators of equal competence redraw the same reference sets."""
    random.seed(seed)
    strategy = RandomStrategy()
    per_user = {"alice": {}, "bob": {}}

    for i in range(n_items):
        iid = f"img_{i}"
        gold = {"objects": gold_blob(n=3, seed=seed * 1000 + i)}
        for user in per_user:
            out = strategy.generate_annotation(
                {"text": "x"}, IMAGE_SCHEMA, FixedCompetence(accuracy), gold)
            per_user[user][iid] = {("objects", "_data"): out["objects:::_data"]}

    iids = [f"img_{i}" for i in range(n_items)]
    states = {u: FakeUserState(items) for u, items in per_user.items()}
    report = dispatcher.compute_overlap_iaa(
        FakeISM(iids, list(per_user)), FakeUSM(states),
        {"annotation_schemes": [IMAGE_SCHEMA]},
    )
    return report["schemas"]["objects"]["metrics"]


class TestAgreementTracksCompetence:
    def test_expert_annotators_agree_strongly(self):
        metrics = simulate_report(1.0, seed=1)
        assert metrics["n_items"] == 25
        assert metrics["detection_f1"] == pytest.approx(1.0)
        assert metrics["mean_agreement"] > 0.8

    def test_careless_annotators_agree_much_less(self):
        metrics = simulate_report(0.2, seed=1)
        assert metrics["mean_agreement"] < 0.6

    def test_agreement_is_monotone_in_competence(self):
        """The property that makes the statistic trustworthy."""
        scores = [simulate_report(a, seed=4)["mean_agreement"]
                  for a in (0.1, 0.5, 0.9)]
        assert scores[0] < scores[1] < scores[2], scores

    def test_detection_f1_separates_missing_from_sloppy(self):
        """Careless annotators miss objects; expert ones only draw imprecisely."""
        expert = simulate_report(1.0, seed=2)
        careless = simulate_report(0.2, seed=2)
        assert expert["detection_f1"] > careless["detection_f1"]
        assert expert["mean_object_count_diff"] < careless["mean_object_count_diff"]

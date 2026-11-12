"""
Pairwise answers are compared and exported in data order.

With ``randomize_order`` a pairwise page stores the position the annotator
saw: "A" is whichever candidate was shown first. Two annotators who preferred
the same response store different letters when one of them saw the pair
swapped. The recorded order (``instance_id_to_presentation_order``, a list of
source indices) is what turns both back into the data's letter, and every
reader that compares or exports answers has to apply it.

Each test pairs a swapped annotator with an unswapped one who chose the SAME
data response, so a reader that skips the mapping sees a disagreement.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from potato.item_state_management import ItemStateManager, Label
from potato.phase import UserPhase
from potato.server_utils.iaa import dispatcher
from potato.server_utils.presentation_order import (
    source_oriented, source_pairwise_values)
from potato.user_state_management import InMemoryUserState
from tests.unit.test_iaa_dispatcher_gathering import FakeISM, FakeUSM

PREF = {"annotation_type": "pairwise", "name": "pref", "description": "Better?",
        "items_key": "responses", "randomize_order": True, "allow_tie": True}
SCALE = {"annotation_type": "pairwise", "name": "pref", "mode": "scale",
         "description": "How much better?", "items_key": "responses",
         "randomize_order": True, "scale": {"min": -3, "max": 3}}

SWAPPED, UNSWAPPED = [1, 0], [0, 1]


class TestSourcePairwiseValues:
    def test_swap_maps_each_letter(self):
        assert source_pairwise_values(PREF, {"selection": "A"}, SWAPPED) == {"selection": "B"}
        assert source_pairwise_values(PREF, {"selection": "B"}, SWAPPED) == {"selection": "A"}

    def test_data_order_is_unchanged(self):
        assert source_pairwise_values(PREF, {"selection": "A"}, UNSWAPPED) == {"selection": "A"}

    def test_tie_and_justification_are_unchanged(self):
        values = {"selection": "tie", "justification": '{"rationale": "A"}'}
        assert source_pairwise_values(PREF, values, SWAPPED) == values

    def test_dimensions_map_too(self):
        values = {"accuracy": "A", "fluency": "B", "style": "tie"}
        assert source_pairwise_values(PREF, values, SWAPPED) == {
            "accuracy": "B", "fluency": "A", "style": "tie"}

    def test_scale_mirrors_on_its_range(self):
        # -2 is "the first card shown is better"; swapped, that is the data's B.
        assert source_pairwise_values(SCALE, {"scale_value": "-2"}, SWAPPED) == {"scale_value": "2"}
        assert source_pairwise_values(SCALE, {"scale_value": 0}, SWAPPED) == {"scale_value": 0}

    def test_scale_not_centred_on_zero(self):
        scheme = dict(SCALE, scale={"min": 1, "max": 7})
        assert source_pairwise_values(scheme, {"scale_value": "2"}, SWAPPED) == {"scale_value": "6"}

    def test_only_pairwise_schemes_are_touched(self):
        radio = {"annotation_type": "radio", "name": "tone", "labels": ["A", "B"]}
        labels = {"tone": {"A": True}}
        assert source_oriented([radio], labels, {"tone": SWAPPED}) == labels


def _state(uid, iid, selection, order):
    state = InMemoryUserState(uid)
    state.current_phase_and_page = (UserPhase.ANNOTATION, "annotation")
    state.add_label_annotation(iid, Label("pref", "selection"), selection)
    state.record_presentation_order(iid, {"pref": order})
    return state


def _same_preference():
    # Both preferred the data's first response; b saw it second.
    return {"a": _state("a", "i1", "A", UNSWAPPED),
            "b": _state("b", "i1", "B", SWAPPED)}


class TestAgreementReadsDataOrder:
    def test_iaa_report(self):
        states = _same_preference()
        report = dispatcher.compute_overlap_iaa(
            FakeISM(["i1"], list(states)), FakeUSM(states),
            {"annotation_schemes": [PREF]})
        assert report["schemas"]["pref"]["metrics"]["percent_agreement"] == 1.0

    def test_adaptive_disagreement_score(self):
        states = _same_preference()
        ism = ItemStateManager({"random_seed": 7, "annotation_schemes": [PREF]})
        ism.add_item("i1", {"responses": ["x", "y"]})
        usm = MagicMock()
        usm.get_user_state.side_effect = states.get
        with patch("potato.user_state_management.get_user_state_manager",
                   return_value=usm):
            for uid in states:
                ism.register_annotator("i1", uid)
            assert ism._calculate_disagreement_score("i1") == 0.0
            # A real disagreement still scores: b now preferred the data's B.
            states["b"] = _state("b", "i1", "A", SWAPPED)
            assert ism._calculate_disagreement_score("i1") > 0.0


@pytest.fixture
def output_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


class TestExportsReadDataOrder:
    def _save(self, output_dir):
        for uid, state in _same_preference().items():
            user_dir = os.path.join(output_dir, uid)
            os.makedirs(user_dir)
            state.save(user_dir)

    def test_loader_orients_labels(self, output_dir):
        from potato.export.cli import load_annotations_from_output_dir

        self._save(output_dir)
        records = load_annotations_from_output_dir(output_dir, [PREF])
        assert {r["user_id"]: r["labels"]["pref"]["selection"] for r in records} == {
            "a": "A", "b": "A"}

    def test_preference_pairs_name_the_chosen_response(self, output_dir):
        from potato.export.base import ExportContext
        from potato.export.cli import load_annotations_from_output_dir
        from potato.export.coding_eval_exporter import CodingEvalExporter

        self._save(output_dir)
        context = ExportContext(
            config={}, annotations=load_annotations_from_output_dir(output_dir, [PREF]),
            items={"i1": {"text": "Which is better?", "responses": ["first", "second"]}},
            schemas=[PREF], output_dir=output_dir)
        out = os.path.join(output_dir, "export")
        os.makedirs(out)
        path, count = CodingEvalExporter()._export_preference(context, out)
        assert count == 2
        with open(path) as f:
            rows = [json.loads(line) for line in f]
        assert {(r["chosen"], r["rejected"]) for r in rows} == {("first", "second")}


class TestOtherReadersReadDataOrder:
    def test_adjudication_shows_data_order(self):
        from potato.adjudication import AdjudicationManager

        manager = AdjudicationManager.__new__(AdjudicationManager)
        manager.config = {"annotation_schemes": [PREF]}
        b = _same_preference()["b"]
        shown = manager._serialize_labels(b.get_label_annotations("i1"), b, "i1")
        assert shown["pref"]["selection"] == "A"

    def test_paper_mode_records(self, output_dir):
        from potato.paper.collect import _extract_records

        b = _same_preference()["b"]
        b.save(output_dir)
        with open(os.path.join(output_dir, "user_state.json")) as f:
            state = json.load(f)
        records = _extract_records("b", state, {"pref": "pairwise"}, {"pref": PREF})
        assert [r.value for r in records] == ["A"]

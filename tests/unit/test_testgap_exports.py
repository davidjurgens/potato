"""
Exports and published data, built from a project the server could have
written: user states saved by `InMemoryUserState.save` and read back by the
export CLI's own `build_export_context`.

The format tests that existed fed one annotator, one image per basename and
one hand-made text whose entities all ended at a space. Each failure below
needs one of the things they left out: a second annotator, two images with
the same name, a box over the edge, an abbreviation inside an entity, a
dialogue field, or a published scoring key checked against its source.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from potato.export.cli import build_export_context
from potato.item_state_management import Label, SpanAnnotation
from potato.phase import UserPhase
from potato.user_state_management import InMemoryUserState
from tests.helpers.test_utils import create_test_directory


@pytest.fixture
def tmp_path(request):
    """Export output inside tests/, never the system temp directory."""
    return Path(create_test_directory(f"tg_export_{request.node.name}"[:80]))


def _project(name, schemes, items, states, extra=None):
    """states: {user: callable(InMemoryUserState) that writes their answers}."""
    root = create_test_directory(name)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    with open(os.path.join(root, "data", "items.jsonl"), "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")
    config = {"annotation_task_name": name, "task_dir": ".",
              "output_annotation_dir": "annotation_output",
              "data_files": ["data/items.jsonl"],
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": schemes}
    config.update(extra or {})
    with open(os.path.join(root, "config.yaml"), "w") as f:
        yaml.safe_dump(config, f)
    for user, write in states.items():
        state = InMemoryUserState(user)
        state.advance_to_phase(UserPhase.ANNOTATION, None)
        write(state)
        state.save(os.path.join(root, "annotation_output", user))
    return root, build_export_context(os.path.join(root, "config.yaml"))


# ---------------------------------------------------------------------------
# Detection exports
# ---------------------------------------------------------------------------

IMAGE_SCHEME = [{"name": "objects", "annotation_type": "image_annotation",
                 "labels": [{"name": "cat"}], "tools": ["bbox"]}]


def _boxes(*boxes):
    """Normalised client boxes, as the canvas stores them."""
    def write(iid):
        def _w(state):
            state.add_label_annotation(iid, Label("objects", "_data"), json.dumps([
                {"type": "bbox", "label": "cat",
                 "coordinates": {"x": x, "y": y, "width": w, "height": h}}
                for x, y, w, h in boxes]))
        return _w
    return write


def _two_annotators_two_same_named_images(name):
    items = [{"id": "a", "text": "", "image": "set1/img.jpg", "width": 100, "height": 100},
             {"id": "b", "text": "", "image": "set2/img.jpg", "width": 100, "height": 100}]
    one = _boxes((0.1, 0.1, 0.2, 0.2))
    two = _boxes((0.5, 0.5, 0.2, 0.2))

    def u1(state):
        one("a")(state)
        two("b")(state)

    def u2(state):
        one("a")(state)
    return _project(name, IMAGE_SCHEME, items, {"ann1": u1, "ann2": u2},
                    {"item_properties": {"id_key": "id", "text_key": "text",
                                         "image_key": "image"}})


class TestYolo:
    def test_annotators_and_same_named_images_get_their_own_files(self, tmp_path):
        from potato.export.yolo_exporter import YOLOExporter
        _root, ctx = _two_annotators_two_same_named_images("tg_yolo")
        result = YOLOExporter().export(ctx, str(tmp_path))
        files = sorted(str(p.relative_to(tmp_path / "labels"))
                       for p in (tmp_path / "labels").rglob("*.txt"))
        assert files == ["ann1/set1/img.txt", "ann1/set2/img.txt", "ann2/set1/img.txt"]
        # Each file holds that annotator's one box, not a merge.
        for f in files:
            assert len((tmp_path / "labels" / f).read_text().splitlines()) == 1
        assert result.stats["num_images"] == 2

    def test_a_box_over_the_edge_is_clipped(self):
        from potato.export.cv_utils import normalize_bbox
        # x from -10 to 10 in a 100 px image keeps 0..10.
        assert normalize_bbox(-10, 0, 20, 10, 100, 100) == pytest.approx((0.05, 0.05, 0.1, 0.1))


class TestPascalVoc:
    def test_corners_are_one_based_and_files_do_not_overwrite(self, tmp_path):
        from potato.export.pascal_voc_exporter import PascalVOCExporter
        _root, ctx = _two_annotators_two_same_named_images("tg_voc")
        PascalVOCExporter().export(ctx, str(tmp_path))
        files = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.xml"))
        assert files == ["ann1/set1/img.xml", "ann1/set2/img.xml", "ann2/set1/img.xml"]
        box = ET.parse(tmp_path / "ann1/set1/img.xml").find("object/bndbox")
        # Pixels 10..29 of a 100 px image: VOC xmin=11, xmax=30.
        assert [box.find(k).text for k in ("xmin", "ymin", "xmax", "ymax")] == \
            ["11", "11", "30", "30"]

    def test_import_reads_one_based_inclusive_corners(self, tmp_path):
        from potato.importers.voc_importer import VOCImporter
        xml = ("<annotation><filename>x.jpg</filename><size><width>200</width>"
               "<height>100</height></size><object><name>cat</name><bndbox>"
               "<xmin>1</xmin><ymin>5</ymin><xmax>50</xmax><ymax>40</ymax>"
               "</bndbox></object></annotation>")
        coords = VOCImporter().parse(ET.fromstring(xml)).images[0].objects[0]["coordinates"]
        # xmin=1 is pixel 0; xmax=50 is the 50th pixel, so the width is 50.
        assert coords["x"] * 200 == pytest.approx(0)
        assert coords["width"] * 200 == pytest.approx(50)
        assert coords["y"] * 100 == pytest.approx(4)
        assert coords["height"] * 100 == pytest.approx(36)


# ---------------------------------------------------------------------------
# CoNLL
# ---------------------------------------------------------------------------

SPAN_SCHEME = [{"name": "ner", "annotation_type": "span",
                "labels": ["PER", "ORG", "LOC"]}]


def _spans(iid, *spans, field=None):
    def write(state):
        for label, start, end in spans:
            state.add_span_annotation(
                iid, SpanAnnotation("ner", label, label, start, end, target_field=field),
                label)
    return write


class TestConll:
    TEXT = "They met the U.S. Army in Paris. Bob left."

    def _export(self, tmp_path, states, items=None, extra=None, options=None):
        from potato.export.conll_2003_exporter import CoNLL2003Exporter
        _root, ctx = _project("tg_conll", SPAN_SCHEME,
                              items or [{"id": "d1", "text": self.TEXT}], states, extra)
        result = CoNLL2003Exporter().export(ctx, str(tmp_path), options or {})
        return result

    def test_an_entity_is_not_split_across_sentences(self, tmp_path):
        s = self.TEXT.index("U.S.")
        self._export(tmp_path, {"amy": _spans("d1", ("ORG", s, s + 9))})
        body = (tmp_path / "annotations.conll").read_text()
        assert "U.S.\t_\t_\tB-ORG\nArmy\t_\t_\tI-ORG" in body

    def test_each_annotator_gets_a_file(self, tmp_path):
        b, p = self.TEXT.index("Bob"), self.TEXT.index("Paris")
        result = self._export(tmp_path, {"zed": _spans("d1", ("LOC", p, p + 5)),
                                         "amy": _spans("d1", ("PER", b, b + 3))})
        assert (tmp_path / "annotations.amy.conll").read_text().count("B-PER") == 1
        assert "B-PER" not in (tmp_path / "annotations.zed.conll").read_text()
        assert any("2 annotators" in w for w in result.warnings)

    def test_a_dialogue_field_is_tokenised_as_rendered(self, tmp_path):
        items = [{"id": "d1", "text": "x", "conv": [
            {"speaker": "A", "text": "Hi Bob"}, {"speaker": "B", "text": "Hello"}]}]
        extra = {"instance_display": {"fields": [
            {"key": "conv", "type": "dialogue", "span_target": True}]}}
        from potato.server_utils.displays.base import reconstruct_dialogue_dom_text
        rendered = reconstruct_dialogue_dom_text(items[0]["conv"])
        b = rendered.index("Bob")
        self._export(tmp_path, {"amy": _spans("d1", ("PER", b, b + 3), field="conv")},
                     items=items, extra=extra)
        body = (tmp_path / "annotations.conll").read_text()
        assert "{'speaker'" not in body
        assert "Bob\t_\t_\tB-PER" in body

    def test_a_span_inside_a_token_is_tagged_and_reported(self, tmp_path):
        text = "an anti-Trump rally"
        result = self._export(tmp_path, {"amy": _spans("d1", ("PER", 8, 13))},
                              items=[{"id": "d1", "text": text}])
        assert "anti-Trump\t_\t_\tB-PER" in (tmp_path / "annotations.conll").read_text()
        assert any("does not align" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Filtering by a prior task's annotations
# ---------------------------------------------------------------------------

def _decisions(root, per_user):
    for user, by_item in per_user.items():
        state = InMemoryUserState(user)
        state.advance_to_phase(UserPhase.ANNOTATION, None)
        for iid, labels in by_item.items():
            for label in labels:
                state.add_label_annotation(iid, Label("q", label), label)
        state.save(os.path.join(root, user))


class TestFilterByPriorAnnotation:
    def _dir(self, per_user):
        root = create_test_directory("tg_filter")
        _decisions(root, per_user)
        return root

    def test_the_majority_decides_not_the_last_directory(self):
        from potato.filter_by_annotation import filter_loaded_items, load_annotations_from_dir
        root = self._dir({"alice": {"i1": ["accept"]}, "bob": {"i1": ["reject"]},
                          "carol": {"i1": ["reject"]}})
        loaded = load_annotations_from_dir(root)
        items = [{"id": "i1"}]
        assert filter_loaded_items(items, loaded, "q", {"accept"}) == []
        assert filter_loaded_items(items, loaded, "q", {"accept"}, rule="any") == items

    def test_any_ticked_box_counts(self):
        from potato.filter_by_annotation import filter_loaded_items, load_annotations_from_dir
        root = self._dir({"alice": {"i1": ["sports", "tech"]}})
        loaded = load_annotations_from_dir(root)
        assert filter_loaded_items([{"id": "i1"}], loaded, "q", {"sports"}) == [{"id": "i1"}]

    def test_the_summary_counts_every_answer(self):
        from potato.filter_by_annotation import get_annotation_summary
        root = self._dir({"a": {"i1": ["accept"], "i2": ["reject"]},
                          "b": {"i1": ["accept"], "i2": ["accept"]},
                          "c": {"i1": ["reject"]}})
        assert get_annotation_summary(root, "q") == {"accept": 3, "reject": 2}


# ---------------------------------------------------------------------------
# Survey scoring keys, against the published instruments
# ---------------------------------------------------------------------------

INSTRUMENTS = Path(__file__).resolve().parents[2] / "potato/survey_instruments/instruments"


def _scoring(name):
    with open(INSTRUMENTS / f"{name}.json") as f:
        data = json.load(f)
    return data["scoring"], data["questions"]


class TestPublishedKeys:
    @pytest.mark.parametrize("name, subscale, reverse", [
        # Gosling, Rentfrow & Swann (2003): 2, 4, 6, 8, 10 reversed.
        ("tipi", "emotional_stability", [4]),
        ("tipi", "extraversion", [6]),
        # Rammstedt & John (2007): 1, 3, 4, 5, 7 reversed.
        ("bfi-10", "extraversion", [1]),
        ("bfi-10", "agreeableness", [7]),
        ("bfi-10", "conscientiousness", [3]),
        ("bfi-10", "neuroticism", [4]),
        ("bfi-10", "openness", [5]),
        # Donnellan et al. (2006): 6-10 and 15-20 reversed.
        ("mini-ipip", "agreeableness", [7, 17]),
        ("mini-ipip", "openness", [10, 15, 20]),
        # Luhtanen & Crocker (1992): 2, 4, 5, 7, 10, 12, 13, 15 reversed.
        ("cses", "membership", [5, 13]),
        ("cses", "public", [7, 15]),
        # Zimbardo & Boyd (1999): 9, 24, 25, 41, 56 reversed.
        ("ztpi", "future", [9, 24, 56]),
        ("ztpi", "past_positive", [25, 41]),
        # Ho et al. (2015): the four con-trait items of each subscale.
        ("sdo-7", "dominance", [5, 6, 7, 8]),
        ("sdo-7", "anti_egalitarianism", [13, 14, 15, 16]),
    ])
    def test_reverse_keys(self, name, subscale, reverse):
        scoring, _ = _scoring(name)
        assert sorted(scoring["subscales"][subscale].get("reverse", [])) == reverse

    def test_mc_sds_keys(self):
        """Crowne & Marlowe (1960): 18 items keyed true, 15 false."""
        scoring, _ = _scoring("mc-sds")
        assert scoring["keyed_true"] == [1, 2, 4, 7, 8, 13, 16, 17, 18, 20, 21, 24,
                                         25, 26, 27, 29, 31, 33]

    def test_rwa_reverses_the_con_trait_items(self):
        scoring, questions = _scoring("rwa")
        reversed_text = [questions[i - 1]["description"] for i in scoring["reverse_items"]]
        assert any("free thinkers" in t for t in reversed_text)
        assert not any("strong, determined leader" in t for t in reversed_text)

    def test_mfq_has_every_scored_item(self):
        scoring, questions = _scoring("mfq")
        assert max(i for sub in scoring["subscales"].values() for i in sub["items"]) \
            <= len(questions)

    def test_mos_ss_scores_every_item(self):
        scoring, questions = _scoring("mos-ss")
        scored = sorted(i for sub in scoring["subscales"].values() for i in sub["items"])
        assert scored == list(range(1, len(questions) + 1))


@pytest.mark.parametrize("path", sorted(INSTRUMENTS.glob("*.json")), ids=lambda p: p.stem)
def test_every_scoring_key_refers_to_real_items(path):
    """A key naming an item the instrument does not have, a reverse item
    outside its subscale, or true/false keys that overlap or miss items."""
    data = json.loads(path.read_text())
    n = len(data.get("questions", []))
    scoring = data.get("scoring") or {}
    for name, sub in (scoring.get("subscales") or {}).items():
        items = sub.get("items", [])
        assert all(1 <= i <= n for i in items), name
        assert set(sub.get("reverse", [])) <= set(items), name
    for key in ("reverse_items", "keyed_true", "keyed_false"):
        assert all(1 <= i <= n for i in scoring.get(key, [])), key
    if "keyed_true" in scoring:
        true, false = set(scoring["keyed_true"]), set(scoring.get("keyed_false", []))
        assert not true & false
        assert true | false == set(range(1, n + 1))

"""
Families decide what counts as the machine being right; the detector and
vision sources produce image predictions in the shapes the families read.
"""

import json

import os

import pytest

from potato.labeling_engine.config import parse_engine_config
from potato.labeling_engine.families import (
    Geometry, MultiLabel, Nominal, Ordinal, Unsupported, family_for)
from potato.labeling_engine.items import ItemView
from potato.labeling_engine.runtime import Runner
from potato.labeling_engine.schemes import SchemeSpec
from potato.labeling_engine.sources import build_source
from potato.labeling_engine.store import EngineStore
from potato.persistence import clear_db_cache

BOXES = SchemeSpec.from_scheme({"name": "objects", "annotation_type": "image_annotation",
                                "labels": ["person", "vehicle"], "tools": ["bbox"]})


def _box(label, x, y, w, h):
    return {"type": "bbox", "label": label, "bbox": [x, y, w, h]}


def _stored(*objs):
    """What /updateinstance stores for an image scheme."""
    return {"_data": json.dumps([{"type": "bbox", "label": o["label"], "coordinates": {
        "x": o["bbox"][0], "y": o["bbox"][1], "width": o["bbox"][2],
        "height": o["bbox"][3]}} for o in objs])}


class TestFamilyFor:

    @pytest.mark.parametrize("atype,cls", [
        ("radio", Nominal), ("select", Nominal), ("likert", Ordinal),
        ("multiselect", MultiLabel), ("image_annotation", Geometry),
        ("text", Unsupported), ("pure_display", Unsupported)])
    def test_dispatch(self, atype, cls):
        scheme = SchemeSpec.from_scheme({"name": "s", "annotation_type": atype,
                                         "labels": ["a", "b"], "size": 5})
        assert type(family_for(scheme)) is cls


class TestGeometry:

    def test_human_value_reads_what_the_image_tool_saves(self):
        fam = family_for(BOXES)
        objs = fam.human_value(_stored(_box("person", 0.1, 0.1, 0.2, 0.3)))
        assert objs[0]["label"] == "person"
        assert objs[0]["bbox"] == pytest.approx([0.1, 0.1, 0.2, 0.3])

    def test_identical_sets_are_correct_and_a_missed_box_is_not(self):
        fam = family_for(BOXES, tolerance=0.3)
        human = fam.human_value(_stored(_box("person", 0.1, 0.1, 0.2, 0.3),
                                        _box("vehicle", 0.5, 0.5, 0.3, 0.2)))
        same = [_box("person", 0.1, 0.1, 0.2, 0.3), _box("vehicle", 0.5, 0.5, 0.3, 0.2)]
        assert fam.loss(same, human) == pytest.approx(0.0)
        assert fam.correct(same, human)
        missed = same[:1]
        assert fam.loss(missed, human) == pytest.approx(0.5)
        assert not fam.correct(missed, human)

    def test_both_empty_is_agreement(self):
        fam = family_for(BOXES)
        assert fam.correct([], fam.human_value(_stored()))

    def test_geometry_has_no_classes_for_per_class_contracts(self):
        fam = family_for(BOXES)
        assert not fam.per_class_ok and fam.classes() == ["*"]


class TestOrdinal:

    def test_off_by_one_within_tolerance(self):
        scheme = SchemeSpec.from_scheme({"name": "q", "annotation_type": "likert", "size": 5})
        fam = family_for(scheme, tolerance=0.25)
        assert fam.loss("3", "4") == pytest.approx(0.25) and fam.correct("3", "4")
        assert not fam.correct("2", "4")


class FakeYOLO:
    def __init__(self, dets):
        self.dets = dets
        self.calls = []

    def detect(self, ref, confidence_threshold=None):
        self.calls.append((ref, confidence_threshold))
        return self.dets.get(ref, [])


@pytest.fixture
def store(tmp_path):
    clear_db_cache()
    yield EngineStore(str(tmp_path))
    clear_db_cache()


def _engine_cfg(app, sources):
    return parse_engine_config({**app, "labeling_engine": {"enabled": True,
                                                           "sources": sources}})


def test_detector_maps_labels_and_scores_the_image(store, tmp_path, monkeypatch):
    app = {"task_dir": str(tmp_path), "annotation_task_name": "d",
           "annotation_schemes": [BOXES.raw]}
    eng = _engine_cfg(app, [{"id": "yolo", "kind": "detector", "model": "yolov8n.pt",
                             "options": {"keep_threshold": 0.4,
                                         "label_map": {"person": "person", "car": "vehicle"}}}])
    assert eng.source("yolo").endpoint_type == "yolo"
    src = build_source(eng.source("yolo"), app, eng)
    # The detector is handed the file the reference names, under task_dir.
    path = os.path.join(str(tmp_path), "img1.jpg")
    fake = FakeYOLO({path: [
        {"label": "person", "confidence": 0.9,
         "bbox": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.3}},
        {"label": "car", "confidence": 0.7,
         "bbox": {"x": 0.5, "y": 0.5, "width": 0.3, "height": 0.2}},
        {"label": "car", "confidence": 0.2,     # a doubt below the cut
         "bbox": {"x": 0.0, "y": 0.8, "width": 0.1, "height": 0.1}},
        {"label": "toaster", "confidence": 0.95,  # not in the scheme
         "bbox": {"x": 0.3, "y": 0.3, "width": 0.1, "height": 0.1}},
    ]})
    monkeypatch.setattr(src, "_endpoint", lambda: fake)
    s = Runner(store, app, eng).predict(src, BOXES, [ItemView("i1", "img1.jpg")])
    [p] = store.current_predictions("objects", s.source_version_id).values()
    assert [o["label"] for o in p.value] == ["person", "vehicle"]
    assert all(o["type"] == "bbox" for o in p.value)
    # min(kept 0.9, 0.7; 1 - dropped 0.2 = 0.8) = 0.7
    assert p.raw_conf == pytest.approx(0.7)
    assert fake.calls == [(path, 0.05)]
    # The prediction is directly comparable with what a person saves.
    fam = family_for(BOXES, tolerance=0.3)
    human = fam.human_value(_stored(_box("person", 0.1, 0.1, 0.2, 0.3),
                                    _box("vehicle", 0.5, 0.5, 0.3, 0.2)))
    assert fam.correct(p.value, human)


def test_detector_refuses_non_image_schemes(tmp_path):
    app = {"annotation_schemes": [BOXES.raw]}
    eng = _engine_cfg(app, [{"id": "yolo", "kind": "detector"}])
    src = build_source(eng.source("yolo"), app, eng)
    radio = SchemeSpec.from_scheme({"name": "r", "annotation_type": "radio",
                                    "labels": ["a", "b"]})
    assert not src.supports(radio) and src.supports(BOXES)


def test_vlm_label_and_confidence(store, tmp_path, monkeypatch):
    scheme = SchemeSpec.from_scheme({"name": "has_person", "annotation_type": "radio",
                                     "labels": ["yes", "no"]})
    app = {"task_dir": str(tmp_path), "annotation_task_name": "v",
           "annotation_schemes": [scheme.raw]}
    eng = _engine_cfg(app, [{"id": "v", "kind": "vlm", "endpoint_type": "openai_vision",
                             "model": "m", "base_url": "http://x/v1"}])
    src = build_source(eng.source("v"), app, eng)
    seen = []

    class FakeVision:
        def query_with_image(self, prompt, img, fmt):
            seen.append((img.source, img.data))
            return {"label": "Yes", "confidence": 88}
    monkeypatch.setattr(src, "_endpoint", lambda: FakeVision())
    s = Runner(store, app, eng).predict(src, scheme,
                                        [ItemView("i1", "http://images/1.jpg")])
    [p] = store.current_predictions("has_person", s.source_version_id).values()
    assert (p.value, p.raw_conf) == ("yes", 0.88)
    assert seen == [("url", "http://images/1.jpg")]


class TestTraceFamilyAndStepJudge:

    PRM = {"name": "prm", "annotation_type": "process_reward", "description": "Judge steps"}

    def test_trace_family_reads_the_saved_blob(self):
        fam = family_for(SchemeSpec.from_scheme(self.PRM))
        stored = {"prm": json.dumps({"steps": [{"reward": 1}, {"reward": -1}],
                                     "mode": "per_step"})}
        assert fam.human_value(stored) == {"0": 1, "1": -1}
        assert fam.loss({"0": 1, "1": 1}, {"0": 1, "1": -1}) == 0.5
        assert fam.loss({"5": 1}, {"0": 1}) == 1.0     # nothing in common

    def test_step_judge_goes_through_the_call_log(self, store, tmp_path, monkeypatch):
        scheme = SchemeSpec.from_scheme(self.PRM)
        app = {"task_dir": str(tmp_path), "annotation_task_name": "j",
               "annotation_schemes": [self.PRM]}
        eng = _engine_cfg(app, [{"id": "j", "kind": "judge", "endpoint_type": "openai",
                                 "model": "m"}])
        src = build_source(eng.source("j"), app, eng)
        assert src.supports(scheme)
        from potato.ai import judge as judge_mod
        monkeypatch.setattr(judge_mod.JudgeService, "judge_steps",
                            lambda self, iid, si, steps, rubric=None: [
                                {"index": 0, "reward": 1, "confidence": 0.9},
                                {"index": 1, "reward": -1, "confidence": 0.6}])
        item = ItemView("i1", "", data={"steps": ["think", "act"]})
        s = Runner(store, app, eng).predict(src, scheme, [item])
        [p] = store.current_predictions("prm", s.source_version_id).values()
        assert p.value == {"0": 1, "1": -1} and p.raw_conf == pytest.approx(0.6)
        assert len(store.calls()) == 1 and p.call_ids == [store.calls()[0].id]


def test_a_machine_box_prefills_as_the_canvas_client_shape():
    """Found by potato-skill (D2): the verify page got the server shape, drew
    no box, and Next stored [] as the human label."""
    from potato.labeling_engine.families import family_for
    from potato.labeling_engine.schemes import SchemeSpec
    from potato.server_utils.annotation_values import geometry_objects
    scheme = SchemeSpec.from_scheme({"name": "objects", "annotation_type": "image_annotation",
                                     "labels": ["animal"], "tools": ["bbox"]})
    fam = family_for(scheme)
    machine = [{"type": "bbox", "label": "animal", "bbox": [0.1, 0.2, 0.3, 0.4]}]
    page = fam.to_page(machine)
    [obj] = page
    assert (obj["type"], obj["label"]) == ("bbox", "animal")
    assert obj["coordinates"] == {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
    # Saved back unchanged by the page, it reads as the same box: loss 0.
    import json
    assert fam.loss(machine, fam.human_value(json.dumps(page))) == 0.0


def test_a_family_the_page_cannot_prefill_has_no_page_value():
    from potato.labeling_engine.families import family_for
    from potato.labeling_engine.schemes import SchemeSpec
    seg = SchemeSpec.from_scheme({"name": "events", "annotation_type": "temporal_grounding",
                                  "labels": ["x"]})
    assert family_for(seg).to_page([{"start": 1, "end": 2, "label": "x"}]) is None


@pytest.mark.parametrize("ref,expected", [
    ("/media/a.jpg", "TASK/media/a.jpg"),
    ("media/a.jpg", "TASK/media/a.jpg"),
    ("http://h/a.jpg", "http://h/a.jpg"),
    ("/abs/a.jpg", "/abs/a.jpg"),
])
def test_image_references_resolve_as_the_page_resolves_them(ref, expected):
    """Found by potato-skill (D10): /media/x.jpg was opened as a filesystem
    path, and every detector and vision call failed."""
    from potato.labeling_engine.sources.base import local_media_path
    assert local_media_path({"task_dir": "TASK"}, ref) == expected


def test_a_number_scheme_is_scored_on_its_own_range():
    """Found by potato-skill (D6)."""
    from potato.labeling_engine.families import family_for
    from potato.labeling_engine.schemes import SchemeSpec
    fam = family_for(SchemeSpec.from_scheme({"name": "n", "annotation_type": "number",
                                             "min": 0, "max": 1000}))
    assert fam.loss(500, 510) == pytest.approx(0.01)
    assert fam.correct(500, 510)


@pytest.mark.parametrize("atype,stored", [
    # What each widget writes to its hidden input (temporal_grounding.py's
    # IIFE, tiered-annotation.js serialize()).
    ("temporal_grounding", {"_data": '{"events": {"0": {"start": 1, "end": 4}, '
                                     '"1": {"start": 6, "end": 9}}}'}),
    ("tiered_annotation", {"_data": '{"annotations": {"speaker": [{"start_time": 0, '
                                    '"end_time": 1000, "value": "A"}, {"start_time": 1500, '
                                    '"end_time": 3000, "value": "B"}]}, "time_slots": [0, 1000]}'}),
])
def test_every_timeline_widgets_answer_is_read(atype, stored):
    """Found by potato-skill (D7): only {"segments": [...]} was read, so the
    agreement report saw no labels and the engine read every answer as empty."""
    from potato.labeling_engine.families import family_for
    from potato.labeling_engine.schemes import SchemeSpec
    from potato.server_utils.iaa.structured import segment_distance, segment_list
    segs = segment_list(stored)
    assert len(segs) == 2 and all(s["end"] > s["start"] for s in segs)
    assert segment_distance(segs, segs) == 0.0
    fam = family_for(SchemeSpec.from_scheme({"name": "t", "annotation_type": atype,
                                             "labels": ["x"]}))
    assert fam.human_value(stored) == segs


def test_two_identical_instants_agree():
    """Found by potato-skill (D11): identical zero-length segments scored 1.0
    apart."""
    from potato.server_utils.iaa.structured import segment_distance
    seg = [{"start": 3.0, "end": 3.0, "label": "onset"}]
    assert segment_distance(seg, seg) == 0.0
    assert segment_distance(seg, [{"start": 4.0, "end": 4.0, "label": "onset"}]) == 1.0

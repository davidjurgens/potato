"""Raven / Audacity / BirdNET import into spectrogram projects, and the
Raven / Audacity exports back out, on synthetic recordings."""

import json
import os
import wave

import pytest
import yaml

from potato.export.base import ExportContext
from potato.export.registry import export_registry
from potato.importers import projects
from potato.importers.projects.writer import write_project
from potato.server_utils import acoustic_tables as t
from tests.helpers.test_utils import create_test_directory


def _wav(path, seconds=2.0, rate=16000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


BOXES = [{"start_s": 0.2, "end_s": 0.6, "low_hz": 1000.0, "high_hz": 3000.0, "label": "chip"},
         {"start_s": 1.0, "end_s": 1.4, "low_hz": 500.0, "high_hz": 900.0, "label": "song"}]


@pytest.fixture
def folder():
    d = create_test_directory("bioacoustics_import")
    _wav(os.path.join(d, "rec1.wav"))
    _wav(os.path.join(d, "rec2.wav"))
    return d


def test_raven_folder_becomes_spectrogram_project(folder):
    with open(os.path.join(folder, "rec1.Table.1.selections.txt"), "w") as f:
        f.write(t.write_raven(BOXES, label_column="Species"))
    with open(os.path.join(folder, "rec2.Table.1.selections.txt"), "w") as f:
        f.write(t.write_raven([], label_column="Species"))
    assert projects.detect(folder) == "raven"
    result = projects.IMPORTERS["raven"].parse_path(folder, {})
    scheme = result.schemes[0]
    assert scheme["annotation_type"] == "spectrogram_annotation" and scheme["labels"] == ["chip", "song"]
    items = {i.instance_id: i for i in result.items}
    assert set(items) == {"rec1", "rec2"}
    got = items["rec1"].predictions["calls"]
    assert [{k: b[k] for k in t.BOX_KEYS} for b in got] == BOXES
    assert got[0]["source"] == "import" and got[0]["import_format"] == "raven"
    assert items["rec1"].fields["audio_url"] == "/media/rec1.wav"
    assert items["rec1"].fields["sample_rate"] == 16000
    assert items["rec2"].predictions["calls"] == []

    out = os.path.join(folder, "project")
    write_project(result, out, source=folder)
    config = yaml.safe_load(open(os.path.join(out, "config.yaml")))
    assert config["annotation_schemes"][0]["name"] == "calls"
    assert os.path.isfile(os.path.join(out, "media", "rec1.wav"))
    # The generated config passes Potato's own validation.
    from potato.server_utils.config_module import validate_single_annotation_scheme
    validate_single_annotation_scheme(config["annotation_schemes"][0], "annotation_schemes[0]")


def test_birdnet_threshold_and_provenance(folder):
    with open(os.path.join(folder, "rec1.BirdNET.results.csv"), "w") as f:
        f.write("Start (s),End (s),Scientific name,Common name,Confidence\n"
                "0.0,3.0,Turdus migratorius,American Robin,0.82\n"
                "3.0,6.0,Cardinalis cardinalis,Northern Cardinal,0.05\n")
    assert projects.detect(os.path.join(folder, "rec1.BirdNET.results.csv")) == "birdnet"
    result = projects.IMPORTERS["birdnet"].parse_path(folder, {})
    boxes = result.items[0].predictions["calls"]
    assert [b["label"] for b in boxes] == ["Turdus migratorius"]     # 0.05 < default 0.1
    assert boxes[0]["source"] == "ai" and boxes[0]["ai_model"] == "BirdNET"
    assert sum(result.skipped.values()) == 1
    loose = projects.IMPORTERS["birdnet"].parse_path(folder, {"min_confidence": 0.0})
    assert len(loose.items[0].predictions["calls"]) == 2


def test_audacity_import(folder):
    path = os.path.join(folder, "rec2.txt")
    with open(path, "w") as f:
        f.write(t.write_audacity(BOXES))
    assert projects.detect(path) == "audacity_labels"
    result = projects.IMPORTERS["audacity_labels"].parse_path(path, {})
    assert result.items[0].instance_id == "rec2"
    assert [{k: b[k] for k in t.BOX_KEYS} for b in result.items[0].predictions["calls"]] == BOXES


def _context(folder, answers, schemes=None):
    schemes = schemes or [{"annotation_type": "spectrogram_annotation", "name": "calls",
                           "description": "d", "labels": ["chip", "song"]}]
    annotations = [{"instance_id": iid, "user_id": user, "labels": {"calls": {"_data": json.dumps(b)}},
                    "spans": {}, "image_annotations": {}} for (iid, user), b in answers.items()]
    items = {iid: {"id": iid, "recording": f"{iid}.wav", "sample_rate": 16000} for iid, _ in answers}
    return ExportContext(config={}, annotations=annotations, items=items, schemas=schemes,
                         output_dir=folder)


@pytest.mark.parametrize("fmt,suffix", [("raven", ".selections.txt"), ("audacity_labels", ".labels.txt")])
def test_export_round_trips_through_the_importer(folder, fmt, suffix):
    edited = BOXES + [{"start_s": 1.6, "end_s": 1.8, "low_hz": None, "high_hz": None, "label": "chip"}]
    ctx = _context(folder, {("rec1", "ann"): edited})
    out = os.path.join(folder, "export_" + fmt)
    result = export_registry.export(fmt, ctx, out, {})
    assert result.success and result.files_written == [os.path.join(out, "rec1" + suffix)]
    _wav(os.path.join(out, "rec1.wav"))
    back = projects.IMPORTERS[fmt].parse_path(out, {}).items[0].predictions["calls"]
    got = [{k: b[k] for k in t.BOX_KEYS} for b in back]
    assert got[:2] == BOXES
    if fmt == "raven":   # a time-only box goes over the band: 0 Hz to Nyquist
        assert (got[2]["low_hz"], got[2]["high_hz"]) == (0.0, 8000.0)
    else:
        assert got[2]["low_hz"] is None


def test_export_names_files_by_annotator_when_there_are_several(folder):
    ctx = _context(folder, {("rec1", "a"): BOXES, ("rec1", "b"): BOXES[:1]})
    out = os.path.join(folder, "two")
    result = export_registry.export("raven", ctx, out, {})
    assert sorted(os.path.basename(p) for p in result.files_written) == [
        "rec1.a.selections.txt", "rec1.b.selections.txt"]
    only = export_registry.export("raven", ctx, os.path.join(folder, "one"), {"annotator": "b"})
    assert [os.path.basename(p) for p in only.files_written] == ["rec1.selections.txt"]


def test_an_unknown_annotator_is_named(folder):
    ctx = _context(folder, {("rec1", "a"): BOXES})
    res = export_registry.export("raven", ctx, os.path.join(folder, "nobody"), {"annotator": "zed"})
    assert res.files_written == []
    assert any("No answers from annotator 'zed'" in w for w in res.warnings)

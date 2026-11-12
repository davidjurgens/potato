"""MegaDetector and COCO Camera Traps import; MegaDetector, Camtrap DP and
Darwin Core export; on synthetic fixtures."""

import csv
import json
import os

import pytest

from potato.export.base import ExportContext
from potato.export.camera_trap_exporter import iso_timestamp
from potato.export.registry import export_registry
from potato.importers import projects
from potato.importers.projects.writer import write_project
from tests.helpers.test_utils import create_test_directory

MD = {
    "info": {"format_version": "1.4", "detector": "md_v5a.0.0.pt"},
    "detection_categories": {"1": "animal", "2": "person", "3": "vehicle"},
    "classification_categories": {"7": "Procyon lotor", "8": "Unused species"},
    "images": [
        {"file": "cam1/a.jpg", "datetime": "2024-05-14 05:42:10", "location": "cam1", "seq_id": "s1",
         "detections": [
             {"category": "1", "conf": 0.9, "bbox": [0.1, 0.2, 0.3, 0.4], "classifications": [["7", 0.8]]},
             {"category": "2", "conf": 0.5, "bbox": [0.6, 0.1, 0.1, 0.5]},
             {"category": "1", "conf": 0.1, "bbox": [0.0, 0.0, 0.1, 0.1]}]},
        {"file": "cam1/b.jpg", "datetime": "2024-05-14 05:42:11", "location": "cam1", "seq_id": "s1",
         "detections": [{"category": "1", "conf": 0.15, "bbox": [0.1, 0.1, 0.1, 0.1]}]},
        {"file": "cam1/c.jpg", "failure": "Failed to load image"},
    ],
}


@pytest.fixture
def md_file():
    d = create_test_directory("camera_trap_import")
    path = os.path.join(d, "md.json")
    with open(path, "w") as f:
        json.dump(MD, f)
    return path


def test_megadetector_detection_and_items(md_file):
    assert projects.detect(md_file) == "megadetector"
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})
    names = [s["name"] for s in result.schemes]
    assert names == ["triage", "detections", "species"]
    labels = [l["name"] for l in result.schemes[1]["labels"]]
    assert labels == ["Procyon lotor", "animal", "person", "vehicle"]   # unused species left out
    a, b = result.items
    assert a.instance_id == "cam1_a.jpg" and a.fields["file"] == "cam1/a.jpg"
    assert a.fields["image_url"] == "/media/cam1/a.jpg"
    boxes = a.predictions["detections"]
    assert [x["label"] for x in boxes] == ["Procyon lotor", "person"]   # 0.1 < 0.2 threshold
    assert boxes[0]["coordinates"] == {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
    assert boxes[0]["source"] == "ai" and boxes[0]["confidence"] == 0.9
    assert a.predictions["triage"] == "animal" and a.predictions["species"] == ["Procyon lotor"]
    assert b.predictions["triage"] == "empty" and b.predictions["detections"] == []
    assert result.skipped["images MegaDetector failed to read"] == 1

    looser = projects.IMPORTERS["megadetector"].parse_path(md_file, {"md_threshold": 0.05})
    assert len(looser.items[0].predictions["detections"]) == 3
    assert looser.items[1].predictions["triage"] == "animal"


def test_image_dir_sets_media_directory_and_project_validates(md_file):
    d = os.path.dirname(md_file)
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {"image_dir": d})
    assert result.extra_config == {"media_directory": os.path.abspath(d)}
    assert any("not under --image-dir" in w for w in result.warnings)
    out = os.path.join(d, "project")
    write_project(result, out, source=md_file, extra_config=result.extra_config)
    import yaml
    config = yaml.safe_load(open(os.path.join(out, "config.yaml")))
    assert config["media_directory"] == os.path.abspath(d)
    from potato.server_utils.config_module import validate_single_annotation_scheme
    for i, s in enumerate(config["annotation_schemes"]):
        validate_single_annotation_scheme(s, f"annotation_schemes[{i}]")


def test_sequences_become_gallery_items(md_file):
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {"sequences": True})
    assert [s["name"] for s in result.schemes] == ["triage", "species"]
    (item,) = result.items
    assert item.instance_id == "s1" and item.fields["files"] == ["cam1/a.jpg", "cam1/b.jpg"]
    assert [f["url"] for f in item.fields["frames"]] == ["/media/cam1/a.jpg", "/media/cam1/b.jpg"]
    assert item.predictions["triage"] == "animal"
    assert result.instance_display["fields"][0]["type"] == "gallery"
    assert len(item.fields["md_detections"]["cam1/a.jpg"]) == 2


def test_coco_camera_traps(md_file):
    cct = {"info": {}, "categories": [{"id": 0, "name": "empty"}, {"id": 5, "name": "Sus scrofa"}],
           "images": [{"id": "i1", "file_name": "loc/x.jpg", "width": 200, "height": 100,
                       "seq_id": "q", "frame_num": 0, "location": "loc", "datetime": "2019:06:01 12:00:00"},
                      {"id": "i2", "file_name": "loc/y.jpg", "width": 200, "height": 100,
                       "seq_id": "q", "frame_num": 1, "location": "loc"}],
           "annotations": [{"id": 1, "image_id": "i1", "category_id": 5, "bbox": [20, 10, 100, 50]},
                           {"id": 2, "image_id": "i2", "category_id": 0}]}
    path = os.path.join(os.path.dirname(md_file), "cct.json")
    with open(path, "w") as f:
        json.dump(cct, f)
    assert projects.detect(path) == "coco_camera_traps"
    result = projects.IMPORTERS["coco_camera_traps"].parse_path(path, {})
    x, y = result.items
    assert x.predictions["detections"][0]["coordinates"] == {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}
    assert x.predictions["triage"] == "animal" and x.predictions["species"] == ["Sus scrofa"]
    assert y.predictions["triage"] == "empty"


def _reviewed_context(result, edit):
    """Annotation records as the server would store them, from the imported
    pre-annotations with `edit` applied."""
    schemes = result.schemes
    annotations, items = [], {}
    for item in result.items:
        items[item.instance_id] = dict(item.fields, id=item.instance_id)
        pred = json.loads(json.dumps(item.predictions))
        edit(item.instance_id, pred)
        labels = {"triage": {pred["triage"]: pred["triage"]}}
        if "species" in pred:
            labels["species"] = {n: n for n in pred["species"]}
        annotations.append({"instance_id": item.instance_id, "user_id": "rev", "labels": labels,
                            "spans": {}, "image_annotations": {"detections": pred["detections"]}})
    return ExportContext(config={"annotation_task_name": "CT"}, annotations=annotations,
                         items=items, schemas=schemes, output_dir="")


def _edit(iid, pred):
    if iid == "cam1_a.jpg":
        person = pred["detections"][1]
        person["coordinates"]["x"] = 0.55
        person["edited"] = True
    else:   # the reviewer says b.jpg holds a raccoon the detector missed
        pred["triage"] = "animal"
        pred["detections"] = [{"type": "bbox", "label": "Procyon lotor", "source": "human",
                               "coordinates": {"x": 0.3, "y": 0.3, "width": 0.2, "height": 0.2}}]
        pred["species"] = ["Procyon lotor"]


def test_megadetector_export_round_trip(md_file):
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})
    ctx = _reviewed_context(result, _edit)
    out = os.path.join(os.path.dirname(md_file), "md_out")
    res = export_registry.export("megadetector", ctx, out, {})
    assert res.success
    data = json.load(open(res.files_written[0]))
    by_file = {i["file"]: i["detections"] for i in data["images"]}
    raccoon, person = by_file["cam1/a.jpg"]
    # conf is the detector's score, the classification the classifier's (0.8).
    assert raccoon == {"category": "1", "conf": 0.9, "bbox": [0.1, 0.2, 0.3, 0.4],
                       "classifications": [["1", 0.8]]}
    assert person["category"] == "2" and person["conf"] == 1.0 and person["bbox"][0] == 0.55
    assert by_file["cam1/b.jpg"][0]["conf"] == 1.0
    assert data["classification_categories"] == {"1": "Procyon lotor"}
    # The export reads back in as the same boxes.
    path = os.path.join(out, "again.json")
    os.rename(res.files_written[0], path)
    again = projects.IMPORTERS["megadetector"].parse_path(path, {})
    assert again.items[1].predictions["detections"][0]["coordinates"] == {
        "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.2}


def test_megadetector_export_keeps_boxes_triaged_empty_and_warns(md_file):
    """Triaged empty but still boxed is the reviewer's contradiction: the boxes
    stay (as in the Darwin and Web Annotation exports) and the item is named."""
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})

    def empty(iid, pred):
        pred["triage"] = "empty"
    ctx = _reviewed_context(result, empty)
    res = export_registry.export("megadetector", ctx, os.path.join(os.path.dirname(md_file), "e"), {})
    data = json.load(open(res.files_written[0]))
    by_file = {i["file"]: i["detections"] for i in data["images"]}
    assert len(by_file["cam1/a.jpg"]) == 2 and by_file["cam1/b.jpg"] == []
    (warning,) = [w for w in res.warnings if "triaged empty" in w]
    assert "cam1_a.jpg (rev)" in warning and "cam1_b.jpg" not in warning


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_camtrap_dp_package(md_file):
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})
    ctx = _reviewed_context(result, _edit)
    out = os.path.join(os.path.dirname(md_file), "camtrap")
    res = export_registry.export("camtrap_dp", ctx, out, {"timezone": "-05:00", "contributor": "A. Person",
                                                        "sampling_design": "opportunistic",
                                                        "capture_method": "activityDetection"})
    assert res.success
    obs = _rows(os.path.join(out, "observations.csv"))
    assert list(obs[0].keys())[:8] == ["observationID", "deploymentID", "mediaID", "eventID",
                                       "eventStart", "eventEnd", "observationLevel", "observationType"]
    raccoon = obs[0]
    assert (raccoon["observationType"], raccoon["scientificName"], raccoon["bboxX"]) == ("animal", "Procyon lotor", "0.1")
    # The species is the classifier's call, so its score (0.8), not the detector's 0.9.
    assert raccoon["classificationMethod"] == "machine" and raccoon["classificationProbability"] == "0.8"
    assert raccoon["eventStart"] == "2024-05-14T05:42:10-05:00" and raccoon["deploymentID"] == "cam1"
    person = obs[1]
    assert person["observationType"] == "human" and person["classificationMethod"] == "human"
    media = _rows(os.path.join(out, "media.csv"))
    assert [m["filePath"] for m in media] == ["cam1/a.jpg", "cam1/b.jpg"]
    assert media[0]["fileMediatype"] == "image/jpeg"
    dep = _rows(os.path.join(out, "deployments.csv"))[0]
    assert dep["deploymentStart"] == "2024-05-14T05:42:10-05:00" and dep["latitude"] == ""
    assert any("latitude" in w for w in res.warnings)
    package = json.load(open(os.path.join(out, "datapackage.json")))
    # 1.0's profile has a $defs reference frictionless 5.17+ cannot resolve.
    assert package["profile"].endswith("/1.0.2/camtrap-dp-profile.json")
    # Single images: GBIF's converter needs to be told the level.
    assert package["gbifIngestion"] == {"observationLevel": "media"}
    assert [r["name"] for r in package["resources"]] == ["deployments", "media", "observations"]
    assert package["taxonomic"] == [{"scientificName": "Procyon lotor"}]


def test_darwin_core_basis_of_record(md_file):
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})
    ctx = _reviewed_context(result, _edit)
    out = os.path.join(os.path.dirname(md_file), "dwc")
    res = export_registry.export("darwin_core", ctx, out, {})
    rows = _rows(res.files_written[0])
    assert [(r["scientificName"], r["basisOfRecord"]) for r in rows] == [
        ("Procyon lotor", "MachineObservation"), ("Procyon lotor", "HumanObservation")]
    assert rows[0]["eventDate"] == "2024-05-14T05:42:10" and rows[0]["occurrenceStatus"] == "present"
    forced = export_registry.export("darwin_core", ctx, out, {"basis_of_record": "HumanObservation"})
    assert {r["basisOfRecord"] for r in _rows(forced.files_written[0])} == {"HumanObservation"}


@pytest.mark.parametrize("raw,tz,expected", [
    ("2024-05-14 05:42:10", None, ("2024-05-14T05:42:10", False)),
    ("2024:05:14 05:42:10", "+02:00", ("2024-05-14T05:42:10+02:00", True)),
    ("2024-05-14T05:42:10+00:00", None, ("2024-05-14T05:42:10Z", True)),
    ("", None, ("", False)),
])
def test_iso_timestamp(raw, tz, expected):
    assert iso_timestamp(raw, tz) == expected


def test_sequence_review_carries_or_empties_detections(md_file):
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {"sequences": True})
    (item,) = result.items
    items = {item.instance_id: dict(item.fields, id=item.instance_id)}
    out = os.path.join(os.path.dirname(md_file), "seq")
    for triage, expected in (("animal", 2), ("empty", 0)):
        ctx = ExportContext(config={}, items=items, schemas=result.schemes, output_dir="",
                            annotations=[{"instance_id": "s1", "user_id": "rev", "spans": {},
                                          "labels": {"triage": {triage: triage}},
                                          "image_annotations": {}}])
        res = export_registry.export("megadetector", ctx, out, {})
        data = json.load(open(res.files_written[0]))
        by_file = {i["file"]: i["detections"] for i in data["images"]}
        assert set(by_file) == {"cam1/a.jpg", "cam1/b.jpg"}
        assert len(by_file["cam1/a.jpg"]) == expected
        if expected:
            assert by_file["cam1/a.jpg"][0]["conf"] == 0.9   # the detector's own entry
        obs = export_registry.export("camtrap_dp", ctx, os.path.join(out, "dp"), {})
        rows = _rows(os.path.join(out, "dp", "observations.csv"))
        assert {r["observationLevel"] for r in rows} == {"event"} and rows[0]["eventID"] == "s1"
        assert rows[0]["observationType"] == ("animal" if triage == "animal" else "blank")


def _two_reviewers(result):
    """The reviewed context with a second reviewer, bob, who agrees with rev."""
    ctx = _reviewed_context(result, _edit)
    ctx.annotations = ctx.annotations + [dict(r, user_id="bob") for r in ctx.annotations]
    return ctx


@pytest.mark.parametrize("fmt,path", [
    ("camtrap_dp", "observations.csv"),
    ("darwin_core", "occurrence.csv"),
])
def test_several_reviewers_are_not_written_as_several_animals(md_file, fmt, path):
    """Every reviewer's boxes were written as separate observations, so two
    reviewers of one raccoon published two raccoons, and annotator= was
    ignored. Now one reviewer per item, as in the MegaDetector export."""
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})
    base = os.path.dirname(md_file)
    one = export_registry.export(fmt, _reviewed_context(result, _edit), os.path.join(base, fmt + "_1"), {})
    two = export_registry.export(fmt, _two_reviewers(result), os.path.join(base, fmt + "_2"), {})
    rows_one = _rows(os.path.join(base, fmt + "_1", path))
    rows_two = _rows(os.path.join(base, fmt + "_2", path))
    assert len(rows_two) == len(rows_one)
    assert any("several annotators" in w for w in two.warnings)
    assert not any("several annotators" in w for w in one.warnings)
    # bob sorts first, so he is the default; annotator= picks rev instead.
    who = "classifiedBy" if fmt == "camtrap_dp" else "identifiedBy"
    humans = {r[who] for r in rows_two if r.get("classificationMethod", "human") == "human"
              and r[who] in ("bob", "rev")}
    assert humans == {"bob"}
    chosen = export_registry.export(fmt, _two_reviewers(result), os.path.join(base, fmt + "_3"),
                                    {"annotator": "rev"})
    rows_rev = _rows(os.path.join(base, fmt + "_3", path))
    assert len(rows_rev) == len(rows_one)
    assert {r[who] for r in rows_rev} & {"bob", "rev"} == {"rev"}
    assert not any("several annotators" in w for w in chosen.warnings)


def test_disagreeing_reviewers_and_an_unknown_annotator_are_named(md_file):
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})
    base = os.path.dirname(md_file)
    ctx = _two_reviewers(result)
    # bob calls b.jpg empty where rev saw a raccoon.
    for record in ctx.annotations:
        if record["user_id"] == "bob" and record["instance_id"] == "cam1_b.jpg":
            record["labels"] = {"triage": {"empty": "empty"}}
            record["image_annotations"] = {"detections": []}
    res = export_registry.export("darwin_core", ctx, os.path.join(base, "dis"), {})
    (warning,) = [w for w in res.warnings if "several annotators" in w]
    assert "On 1 of them the annotators disagree" in warning and "cam1_b.jpg" in warning
    none = export_registry.export("camtrap_dp", ctx, os.path.join(base, "nobody"),
                                  {"annotator": "nobody"})
    assert any("No answers from annotator 'nobody'" in w for w in none.warnings)


def test_megadetector_coordinates_reach_the_package(md_file):
    data = json.load(open(md_file))
    for image in data["images"]:
        image.update({"latitude": 4.61, "longitude": -74.08})
    json.dump(data, open(md_file, "w"))
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})
    assert result.items[0].fields["latitude"] == 4.61
    ctx = _reviewed_context(result, _edit)
    out = os.path.join(os.path.dirname(md_file), "camtrap_geo")
    res = export_registry.export("camtrap_dp", ctx, out, {})
    package = json.load(open(os.path.join(out, "datapackage.json")))
    assert package["spatial"]["bbox"] == [-74.08, 4.61, -74.08, 4.61]
    assert not any("latitude" in w for w in res.warnings)


def test_camtrap_licenses_need_a_media_license(md_file):
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})
    ctx = _reviewed_context(result, _edit)
    out = os.path.join(os.path.dirname(md_file), "camtrap_lic")
    res = export_registry.export("camtrap_dp", ctx, out, {"license": "CC0-1.0"})
    assert any("media_license" in w for w in res.warnings)
    both = export_registry.export("camtrap_dp", ctx, out, {"license": "CC0-1.0",
                                                          "media_license": "CC-BY-4.0"})
    package = json.load(open(os.path.join(out, "datapackage.json")))
    assert package["licenses"] == [{"name": "CC0-1.0", "scope": "data"},
                                   {"name": "CC-BY-4.0", "scope": "media"}]
    assert not any("media_license" in w for w in both.warnings)


def test_darwin_core_media_is_a_public_link_or_nothing(md_file):
    """associatedMedia held the Potato server's own /media/ path."""
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})
    ctx = _reviewed_context(result, _edit)
    out = os.path.join(os.path.dirname(md_file), "dwc_media")
    res = export_registry.export("darwin_core", ctx, out, {})
    assert {r["associatedMedia"] for r in _rows(res.files_written[0])} == {""}
    assert any("media_base_url" in w for w in res.warnings)
    based = export_registry.export("darwin_core", ctx, out,
                                   {"media_base_url": "https://example.org/photos/"})
    assert {r["associatedMedia"] for r in _rows(based.files_written[0])} == {
        "https://example.org/photos/cam1/a.jpg", "https://example.org/photos/cam1/b.jpg"}
    assert not any("media_base_url" in w for w in based.warnings)


def test_a_media_base_with_a_query_string_keeps_it_last():
    from potato.export.camera_trap_exporter import _public_media
    assert _public_media("/media/cam1/a.jpg", "cam1/a.jpg",
                         "https://example.org/photos?sig=1") == \
        "https://example.org/photos/cam1/a.jpg?sig=1"


def test_a_megadetector_file_given_as_a_url_is_served_from_it(md_file):
    data = json.load(open(md_file))
    data["images"][0]["file"] = "https://cdn.example.org/x/a.jpg?sig=abc"
    json.dump(data, open(md_file, "w"))
    result = projects.IMPORTERS["megadetector"].parse_path(md_file, {})
    assert result.items[0].fields["image_url"] == "https://cdn.example.org/x/a.jpg?sig=abc"
    ctx = _reviewed_context(result, _edit)
    res = export_registry.export("darwin_core", ctx,
                                 os.path.join(os.path.dirname(md_file), "dwc_url"), {})
    media = {r["associatedMedia"] for r in _rows(res.files_written[0])}
    assert "https://cdn.example.org/x/a.jpg?sig=abc" in media

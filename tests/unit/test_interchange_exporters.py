"""W3C Web Annotation, Frictionless Data Package and Psych-DS exports."""

import csv
import json
import os
import re

import pytest

from potato.export.base import ExportContext
from potato.export.data_package_exporter import DataPackageExporter, PsychDSExporter
from potato.export.web_annotation_exporter import WebAnnotationExporter
from tests.helpers.test_utils import create_test_directory

TEXT = "The cat sat on the mat while the dog slept nearby."


def _context(out):
    schemas = [
        {"name": "ner", "annotation_type": "span", "description": "Entities",
         "labels": ["ANIMAL"]},
        {"name": "sentiment", "annotation_type": "radio", "description": "Overall tone?",
         "labels": ["positive", "negative"]},
        {"name": "notes", "annotation_type": "text", "description": "Notes"},
        {"name": "boxes", "annotation_type": "image_annotation", "description": "Boxes",
         "labels": ["cat"], "source_field": "image"},
    ]
    annotations = [
        {"instance_id": "d1", "user_id": "alice",
         "labels": {"sentiment": {"positive": "positive"}, "notes": {"text_box": "calm"}},
         "spans": {"ner": [{"name": "ANIMAL", "start": 4, "end": 7},
                           {"name": "ANIMAL", "start": 33, "end": 36}]}},
        {"instance_id": "img1", "user_id": "bob", "labels": {},
         "image_annotations": {"boxes": [
             {"type": "bbox", "label": "cat",
              "coordinates": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}},
             {"type": "polygon", "label": "cat",
              "coordinates": [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.3, "y": 0.6}]}]}},
    ]
    items = {"d1": {"id": "d1", "text": TEXT},
             "img1": {"id": "img1", "text": "", "image": "https://example.org/cat.jpg",
                      "width": 200, "height": 100}}
    config = {"annotation_task_name": "Cats & dogs", "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": schemas, "output_annotation_dir": out}
    return ExportContext(config=config, annotations=annotations, items=items,
                         schemas=schemas, output_dir=out)


@pytest.fixture
def out():
    return create_test_directory("interchange_exporters")


def test_web_annotation_selectors(out):
    ctx = _context(out)
    res = WebAnnotationExporter().export(ctx, out)
    assert res.success, res.errors
    coll = json.load(open(os.path.join(out, "web_annotations.jsonld")))
    assert coll["type"] == "AnnotationCollection"
    items = coll["first"]["items"]
    assert coll["total"] == len(items)

    spans = [a for a in items if a["potato:schema"] == "ner"]
    sel = spans[0]["target"]["selector"]
    assert sel["type"] == "TextQuoteSelector" and sel["exact"] == "cat"
    assert sel["prefix"] == "The " and sel["suffix"].startswith(" sat")
    assert sel["refinedBy"] == {"type": "TextPositionSelector", "start": 4, "end": 7}
    assert spans[1]["target"]["selector"]["exact"] == "dog"

    choice = next(a for a in items if a["potato:schema"] == "sentiment")
    assert choice["motivation"] == "classifying" and choice["body"]["value"] == "positive"
    assert choice["target"] == "urn:potato:Cats-dogs:d1"
    note = next(a for a in items if a["potato:schema"] == "notes")
    assert note["body"] == {"type": "TextualBody", "purpose": "describing", "value": "calm"}

    regions = [a for a in items if a["potato:schema"] == "boxes"]
    frag = regions[0]["target"]
    assert frag["source"] == "https://example.org/cat.jpg"
    assert frag["selector"]["value"] == "xywh=pixel:20,20,60,40"
    svg = regions[1]["target"]["selector"]
    assert svg["type"] == "SvgSelector" and 'viewBox="0 0 200 100"' in svg["value"]
    assert "20,10 100,10 60,60" in svg["value"]
    assert regions[0]["creator"]["nickname"] == "bob"


def test_web_annotation_base_iri(out):
    res = WebAnnotationExporter().export(_context(out), out, {"base_iri": "https://ex.org/items/"})
    items = json.load(open(res.files_written[0]))["first"]["items"]
    assert any(a["target"] == "https://ex.org/items/d1" for a in items)


def test_data_package(out):
    res = DataPackageExporter().export(_context(out), out)
    assert res.success, res.errors
    pkg = json.load(open(os.path.join(out, "datapackage.json")))
    assert pkg["$schema"].startswith("https://datapackage.org/profiles/2.0/")
    assert re.fullmatch(r"[a-z0-9._-]+", pkg["name"])
    res0 = pkg["resources"][0]
    assert os.path.exists(os.path.join(out, res0["path"]))
    with open(os.path.join(out, res0["path"])) as f:
        header = next(csv.reader(f))
    assert [fld["name"] for fld in res0["schema"]["fields"]] == header
    by_name = {fld["name"]: fld for fld in res0["schema"]["fields"]}
    if "sentiment" in by_name:
        assert by_name["sentiment"]["description"] == "Overall tone?"


def test_psych_ds(out):
    res = PsychDSExporter().export(_context(out), out)
    assert res.success, res.errors
    desc = json.load(open(os.path.join(out, "dataset_description.json")))
    assert desc["@context"] == "https://schema.org/" and desc["@type"] == "Dataset"
    files = os.listdir(os.path.join(out, "data"))
    assert files and all(re.fullmatch(r"(?:[a-z]+-[A-Za-z0-9]+_)+data\.csv", f) for f in files), files
    names = {v if isinstance(v, str) else v["name"] for v in desc["variableMeasured"]}
    for f in files:
        with open(os.path.join(out, "data", f)) as fh:
            assert set(next(csv.reader(fh))) <= names
    assert not os.path.exists(os.path.join(out, ".psychds-staging"))


def test_table_schema_finds_the_question_of_a_label_column():
    """Audit 96 L5: wide CSV columns are schema.label; the description and
    enum must still come from the question."""
    import csv as _csv
    import os as _os
    from potato.export.data_package_exporter import table_schema, _variable
    from tests.helpers.test_utils import create_test_directory
    d = create_test_directory("table_schema_columns")
    path = _os.path.join(d, "a.csv")
    with open(path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["instance_id", "sentiment.positive", "sentiment.negative"])
        w.writerow(["i1", "positive", ""])
        w.writerow(["i2", "", "negative"])
    schemes = {"sentiment": {"name": "sentiment", "annotation_type": "radio",
                             "description": "Overall tone?", "labels": ["positive", "negative"]}}
    fields = {f["name"]: f for f in table_schema(path, schemes)["fields"]}
    assert fields["sentiment.positive"]["description"] == "Overall tone? (positive)"
    assert fields["sentiment.positive"]["constraints"] == {"enum": ["positive"]}
    assert "description" not in fields["instance_id"]
    assert _variable("sentiment.negative", schemes)["description"] == "Overall tone? (negative)"


def test_survey_only_study_exports_its_answers():
    """Audit 96 L4: with survey answers and no item annotations, csv,
    data_package and psych_ds must write the answers, and not list an
    annotations file that was never written."""
    import os as _os
    from potato.export.base import ExportContext
    from potato.export.data_package_exporter import DataPackageExporter, PsychDSExporter
    from potato.export.tabular_exporter import CSVExporter
    from tests.helpers.test_utils import create_test_directory
    responses = [{"user_id": u, "phase": "prestudy", "page": "survey", "sequence": i,
                  "schema": "age", "label_name": "age", "value": str(20 + i)}
                 for i, u in enumerate(("u1", "u2"))]
    for exporter in (CSVExporter(), DataPackageExporter(), PsychDSExporter()):
        d = create_test_directory(f"survey_only_{exporter.format_name}")
        ctx = ExportContext(config={"export_include_phase_data": True, "annotation_task_name": "S"},
                            annotations=[], items={}, schemas=[], output_dir=d,
                            phase_responses=responses)
        result = exporter.export(ctx, d)
        assert result.success
        assert all(_os.path.exists(f) for f in result.files_written), exporter.format_name
        names = " ".join(result.files_written)
        # csv/data_package: phase_responses.csv; psych_ds: ..._table-phaseresponses_data.csv
        assert "phaseresponses" in names.replace("_", "").lower(), (exporter.format_name, names)
        assert "annotations.csv" not in names


def test_web_annotation_created_is_the_answer_time():
    """Audit 96 L8: every annotation carried the export time."""
    import json as _json
    import os as _os
    from potato.export.base import ExportContext
    from potato.export.web_annotation_exporter import WebAnnotationExporter
    from tests.helpers.test_utils import create_test_directory
    d = create_test_directory("wa_created")
    ann = {"instance_id": "i1", "user_id": "u", "labels": {"tone": {"pos": "pos"}},
           "spans": {}, "_changes": [{"schema_name": "tone", "timestamp": 1760000000.0},
                                     {"schema_name": "tone", "timestamp": 1760000100.0}]}
    ctx = ExportContext(config={"annotation_task_name": "t"}, annotations=[ann],
                        items={"i1": {"id": "i1", "text": "hello"}},
                        schemas=[{"name": "tone", "annotation_type": "radio", "labels": ["pos"]}],
                        output_dir=d)
    result = WebAnnotationExporter().export(ctx, d)
    path = next(f for f in result.files_written if f.endswith((".json", ".jsonld")))
    data = _json.load(open(path))
    items = data.get("first", {}).get("items") or data.get("items") or []
    assert items and items[0]["created"] == "2025-10-09T08:55:00Z"


def test_web_annotation_span_created_comes_from_the_history():
    """Audit 96 L8 re-verify: spans have no annotation_changes, so they still
    carried the export time. The annotation history has an add_span for each."""
    import datetime as dt
    from potato.export.cli import load_annotations_from_output_dir
    d = create_test_directory("wa_span_created")
    user = os.path.join(d, "alice")
    os.makedirs(user, exist_ok=True)
    span = {"schema": "ner", "name": "ANIMAL", "title": "ANIMAL", "start": 4, "end": 7}
    with open(os.path.join(user, "user_state.json"), "w") as f:
        json.dump({"user_id": "alice", "instance_id_to_label_to_value": {},
                   "instance_id_to_span_to_value": {"d1": [[span, True]]}}, f)
    made = dt.datetime(2026, 3, 1, 9, 30, 0)
    with open(os.path.join(user, "annotation_history.jsonl"), "w") as f:
        for when, kind in ((made - dt.timedelta(minutes=5), "add_span"), (made, "update_span")):
            f.write(json.dumps({"action_type": kind, "instance_id": "d1", "schema_name": "ner",
                                "span_data": {"start": 4, "end": 7}, "timestamp": when.isoformat()})
                    + "\n")
        f.write("{torn\n")
    schemas = [{"name": "ner", "annotation_type": "span", "labels": ["ANIMAL"]}]
    annotations = load_annotations_from_output_dir(d, schemas, {})
    ctx = ExportContext(config={"annotation_task_name": "t"}, annotations=annotations,
                        items={"d1": {"id": "d1", "text": TEXT}}, schemas=schemas, output_dir=d)
    result = WebAnnotationExporter().export(ctx, os.path.join(d, "out"))
    items = json.load(open(result.files_written[0]))["first"]["items"]
    expected = dt.datetime.fromtimestamp(made.timestamp(), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert [i["created"] for i in items] == [expected]

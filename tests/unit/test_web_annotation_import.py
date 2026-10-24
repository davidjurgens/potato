"""W3C Web Annotation import: selectors become spans and regions, bodies
labels, creators annotators; and a Potato export comes back unchanged."""

import json
from pathlib import Path

import pytest

from potato.export.base import ExportContext
from potato.export.web_annotation_exporter import WebAnnotationExporter
from potato.importers import projects
from potato.importers.projects import _dh
from potato.importers.projects.web_annotation import WebAnnotationImporter
from potato.importers.projects.writer import write_project
from tests.helpers.test_utils import create_test_directory

TEXT = "The cat sat on the mat while the dog slept near the cat."


def _ctx(out):
    schemas = [
        {"name": "ner", "annotation_type": "span", "description": "Entities", "labels": ["ANIMAL"]},
        {"name": "tone", "annotation_type": "radio", "description": "Tone", "labels": ["calm", "tense"]},
        {"name": "boxes", "annotation_type": "image_annotation", "description": "Boxes",
         "labels": ["cat", "dog"], "source_field": "image"},
    ]
    annotations = [
        {"instance_id": "d1", "user_id": "alice", "labels": {"tone": {"calm": "calm"}},
         "spans": {"ner": [{"name": "ANIMAL", "start": 4, "end": 7},
                           {"name": "ANIMAL", "start": 52, "end": 55}]}},
        {"instance_id": "img1", "user_id": "bob", "labels": {},
         "image_annotations": {"boxes": [
             {"type": "bbox", "label": "cat",
              "coordinates": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}},
             {"type": "polygon", "label": "dog",
              "coordinates": [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.3, "y": 0.6}]},
             {"type": "polyline", "label": "dog", "closed": False,
              "coordinates": [{"x": 0.2, "y": 0.2}, {"x": 0.4, "y": 0.5}]}]}},
    ]
    items = {"d1": {"id": "d1", "text": TEXT},
             "img1": {"id": "img1", "text": "", "image": "https://example.org/cat.jpg",
                      "width": 200, "height": 100}}
    config = {"annotation_task_name": "Round trip", "annotation_schemes": schemas,
              "item_properties": {"id_key": "id", "text_key": "text"}}
    return ExportContext(config=config, annotations=annotations, items=items, schemas=schemas,
                         output_dir=out)


@pytest.fixture
def out():
    return Path(create_test_directory("web_annotation_import"))


def _write_texts(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _coords(obj):
    c = obj["coordinates"]
    if isinstance(c, dict):
        return {k: round(v, 6) for k, v in c.items()}
    return [(round(p["x"], 6), round(p["y"], 6)) for p in c]


class TestRoundTrip:
    def test_spans_boxes_polygons_survive_export_then_import(self, out):
        ctx = _ctx(str(out))
        assert WebAnnotationExporter().export(ctx, str(out)).success
        _write_texts(out / "texts.jsonl", list(ctx.items.values()))
        path = out / "web_annotations.jsonld"
        assert projects.detect(str(path)) == "web_annotation"
        result = WebAnnotationImporter().parse_path(path, {"texts": str(out / "texts.jsonl")})

        by_id = {i.instance_id: i for i in result.items}
        assert set(by_id) == {"d1", "img1"}       # potato:instance keeps the ids
        spans = by_id["d1"].predictions["ner"]
        assert [(s["start"], s["end"], s["label"]) for s in spans] == [(4, 7, "ANIMAL"), (52, 55, "ANIMAL")]
        assert by_id["d1"].predictions["tone"] == "calm"

        original = ctx.annotations[1]["image_annotations"]["boxes"]
        back = by_id["img1"].predictions["boxes"]
        assert [o["type"] for o in back] == ["bbox", "polygon", "polyline"]
        for a, b in zip(original, back):
            assert a["label"] == b["label"]
            if isinstance(a["coordinates"], dict):
                for k in a["coordinates"]:
                    assert b["coordinates"][k] == pytest.approx(a["coordinates"][k], abs=1e-3)
            else:
                for p, q in zip(a["coordinates"], b["coordinates"]):
                    assert (q["x"], q["y"]) == pytest.approx((p["x"], p["y"]), abs=1e-3)
        assert back[0]["source"] == "import" and back[0]["import_format"] == "web_annotation"
        assert result.annotator_ids == {"alice": "alice", "bob": "bob"}
        assert by_id["d1"].responses["alice"]["ner"] == spans

        schemes = {s["name"]: s for s in result.schemes}
        assert schemes["ner"]["annotation_type"] == "span"
        assert schemes["tone"]["annotation_type"] == "radio"
        assert schemes["boxes"]["annotation_type"] == "image_annotation"
        assert set(schemes["boxes"]["tools"]) == {"bbox", "polygon", "polyline"}

    def test_written_project_keeps_annotators(self, out):
        ctx = _ctx(str(out))
        WebAnnotationExporter().export(ctx, str(out))
        _write_texts(out / "texts.jsonl", list(ctx.items.values()))
        result = WebAnnotationImporter().parse_path(out / "web_annotations.jsonld",
                                                    {"texts": str(out / "texts.jsonl")})
        project = out / "project"
        write_project(result, str(project), source="web_annotations.jsonld", keep_annotators=True)
        state = json.loads((project / "annotation_output" / "alice" / "user_state.json").read_text())
        spans = state["instance_id_to_span_to_value"]["d1"]
        assert [(s[0]["start"], s[0]["end"], s[0]["name"]) for s in spans] == [
            (4, 7, "ANIMAL"), (52, 55, "ANIMAL")]
        rows = [json.loads(l) for l in (project / "data" / "web_annotations.jsonl").read_text().splitlines()]
        img = next(r for r in rows if r["id"] == "img1")
        assert len(img["predictions"]["boxes"]) == 3 and img["image_url"] == "https://example.org/cat.jpg"


def _anno(target, body="ANIMAL", creator=None, **extra):
    node = {"type": "Annotation", "motivation": "tagging", "target": target,
            "body": {"type": "TextualBody", "purpose": "tagging", "value": body}}
    if creator:
        node["creator"] = creator
    node.update(extra)
    return node


def _import(out, doc, **options):
    path = out / "in.jsonld"
    doc = {"@context": "http://www.w3.org/ns/anno.jsonld", "type": "AnnotationPage", "items": doc}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return WebAnnotationImporter().parse_path(path, options)


class TestTextSelectors:
    def test_missing_position_is_found_by_quote_with_prefix(self, out):
        (out / "texts").mkdir()
        (out / "texts" / "story.txt").write_text(TEXT, encoding="utf-8")
        # "cat" occurs twice; the prefix picks the second.
        result = _import(out, [_anno({"source": "https://example.org/docs/story.txt", "selector": {
            "type": "TextQuoteSelector", "exact": "cat", "prefix": "near the ", "suffix": "."}})],
            texts=str(out / "texts"))
        span = result.items[0].predictions["spans"][0]
        assert (span["start"], span["end"]) == (52, 55)
        assert result.items[0].fields["text"][52:55] == "cat"

    def test_wrong_position_is_corrected_by_quote(self, out):
        _write_texts(out / "t.jsonl", [{"source": "urn:x:doc", "text": TEXT}])
        result = _import(out, [_anno({"source": "urn:x:doc", "selector": [
            {"type": "TextPositionSelector", "start": 30, "end": 33},
            {"type": "TextQuoteSelector", "exact": "dog"}]})], texts=str(out / "t.jsonl"))
        span = result.items[0].predictions["spans"][0]
        assert TEXT[span["start"]:span["end"]] == "dog"

    def test_position_on_source_text_is_moved_into_rendered_text(self, out):
        raw = "A  doubled   space before the cat."
        _write_texts(out / "t.jsonl", [{"source": "urn:x:doc", "text": raw}])
        start = raw.index("cat")
        result = _import(out, [_anno({"source": "urn:x:doc", "selector": {
            "type": "TextPositionSelector", "start": start, "end": start + 3}})],
            texts=str(out / "t.jsonl"))
        item = result.items[0]
        span = item.predictions["spans"][0]
        assert item.fields["text"] == "A doubled space before the cat."
        assert item.fields["text"][span["start"]:span["end"]] == "cat"

    def test_guard_unmapped_offsets_would_land_late(self):
        """The rendered-text map is what keeps the span on 'cat'."""
        raw = "A  doubled   space before the cat."
        dom, remap = _dh.rendered_text(raw)
        start = raw.index("cat")
        assert dom[start:start + 3] != "cat"          # what an unmapped offset reads
        assert dom[remap(start):remap(start + 3)] == "cat"

    def test_text_annotations_without_their_document_are_reported(self, out):
        result = _import(out, [_anno({"source": "urn:x:missing", "selector": {
            "type": "TextQuoteSelector", "exact": "cat"}})])
        assert not result.items
        assert result.skipped["text annotations whose document was not found"] == 1

    def test_local_source_file_is_read(self, out):
        (out / "doc.txt").write_text(TEXT, encoding="utf-8")
        result = _import(out, [_anno({"source": "doc.txt", "selector": {
            "type": "TextQuoteSelector", "exact": "mat"}})])
        span = result.items[0].predictions["spans"][0]
        assert TEXT[span["start"]:span["end"]] == "mat"


class TestHypothesis:
    def test_search_api_rows(self, out):
        page = "https://example.org/article"
        _write_texts(out / "t.jsonl", [{"url": page, "text": TEXT}])
        rows = {"total": 1, "rows": [{
            "id": "h1", "uri": page, "user": "acct:carol@hypothes.is", "tags": ["pet"],
            "text": "a comment", "permissions": {},
            "target": [{"source": page, "selector": [
                {"type": "RangeSelector", "startContainer": "/p[1]"},
                {"type": "TextPositionSelector", "start": 33, "end": 36},
                {"type": "TextQuoteSelector", "exact": "dog", "prefix": "while the ", "suffix": " slept"}]}]}]}
        path = out / "hyp.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        assert WebAnnotationImporter().detect_path(path)
        result = WebAnnotationImporter().parse_path(path, {"texts": str(out / "t.jsonl")})
        item = result.items[0]
        assert item.predictions["spans"] == [{"start": 33, "end": 36, "label": "pet"}]
        assert "carol" in result.annotator_ids


class TestRegions:
    def test_percent_fragment_needs_no_image_size(self, out):
        result = _import(out, [_anno("https://example.org/a.jpg#xywh=percent:10,20,30,40", "cat")])
        obj = result.items[0].predictions["regions"][0]
        assert obj["coordinates"] == pytest.approx({"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4})

    def test_pixel_fragment_without_size_is_reported_not_guessed(self, out):
        result = _import(out, [_anno("https://example.org/a.jpg#xywh=pixel:10,20,30,40", "cat")])
        assert result.skipped["pixel regions on an image of unknown size"] == 1
        assert any("image size is unknown" in w for w in result.warnings)

    def test_svg_path_becomes_polygon(self, out):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
               '<path d="M10 10 L90 10 L90 40 Z"/></svg>')
        result = _import(out, [_anno({"source": "https://example.org/b.png",
                                      "selector": {"type": "SvgSelector", "value": svg}}, "stamp")])
        obj = result.items[0].predictions["regions"][0]
        assert obj["type"] == "polygon"
        assert [(p["x"], p["y"]) for p in obj["coordinates"]] == pytest.approx(
            [(0.1, 0.2), (0.9, 0.2), (0.9, 0.8)])
        assert result.items[0].fields["image_width"] == 100

    def test_local_image_is_copied_and_measured(self, out):
        from PIL import Image
        Image.new("RGB", (400, 200), "white").save(out / "scan.png")
        result = _import(out, [_anno("scan.png#xywh=40,20,100,50", "seal")])
        item = result.items[0]
        assert item.fields["image_url"] == "/media/scan.png"
        assert "media/scan.png" in result.media_files
        assert item.predictions["regions"][0]["coordinates"] == pytest.approx(
            {"x": 0.1, "y": 0.1, "width": 0.25, "height": 0.25})


class TestWholeItemBodies:
    def test_several_tags_from_one_person_make_a_multiselect(self, out):
        result = _import(out, [
            {"type": "Annotation", "motivation": "classifying", "target": "urn:x:i1",
             "creator": {"type": "Person", "nickname": "dana"},
             "body": [{"type": "TextualBody", "purpose": "classifying", "value": "letter"},
                      {"type": "TextualBody", "purpose": "classifying", "value": "legal"}]},
            {"type": "Annotation", "motivation": "commenting", "target": "urn:x:i1",
             "body": {"type": "TextualBody", "value": "Water damage on the left."}}])
        schemes = {s["name"]: s for s in result.schemes}
        assert schemes["classification"]["annotation_type"] == "multiselect"
        assert schemes["comment"]["annotation_type"] == "text"
        item = result.items[0]
        assert item.predictions["classification"] == ["letter", "legal"]
        assert item.predictions["comment"] == "Water damage on the left."

    def test_manifest_is_left_to_the_iiif_importer(self, out):
        path = out / "manifest.json"
        path.write_text(json.dumps({"@context": "http://iiif.io/api/presentation/3/context.json",
                                    "type": "Manifest", "items": [
                                        {"type": "AnnotationPage"}]}), encoding="utf-8")
        assert not WebAnnotationImporter().detect_path(path)
        assert projects.detect(str(path)) == "iiif"


def test_cli_texts_flag_reaches_the_importer(out):
    from potato.importers.cli import main
    ctx = _ctx(str(out))
    WebAnnotationExporter().export(ctx, str(out))
    _write_texts(out / "texts.jsonl", list(ctx.items.values()))
    assert main(["-i", str(out / "web_annotations.jsonld"), "-o", str(out / "cli"),
                 "--texts", str(out / "texts.jsonl")]) == 0
    rows = [json.loads(l) for l in (out / "cli" / "data" / "web_annotations.jsonl").read_text().splitlines()]
    d1 = next(r for r in rows if r["id"] == "d1")
    assert [(s["start"], s["end"]) for s in d1["predictions"]["ner"]] == [(4, 7), (52, 55)]


class TestAudit97Fragments:
    """Audit 97 V8: parts of a target the importer can't place are reported."""

    def test_time_fragment_is_reported_with_its_range(self, out):
        result = _import(out, [_anno("https://example.org/talk.mp3#t=12.345,67.89", body="laugh")])
        assert any("t=12.345,67.89" in w for w in result.warnings), result.warnings

    def test_time_fragment_selector_is_reported(self, out):
        target = {"source": "https://example.org/talk.mp3",
                  "selector": {"type": "FragmentSelector", "value": "t=npt:3,9"}}
        result = _import(out, [_anno(target, body="laugh")])
        assert any("t=3,9" in w for w in result.warnings), result.warnings

    def test_garbage_xywh_is_reported(self, out):
        target = {"source": "https://example.org/page.jpg",
                  "selector": {"type": "FragmentSelector", "value": "xywh=pixel:a,b,c,d"}}
        result = _import(out, [_anno(target, body="cat")])
        assert any("xywh=pixel:a,b,c,d" in w and "unreadable region" in w
                   for w in result.warnings), result.warnings

    def test_missing_pillow_is_named(self, out, monkeypatch):
        import sys
        (out / "page.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        target = {"source": "page.png",
                  "selector": {"type": "FragmentSelector", "value": "xywh=pixel:1,2,3,4"}}
        monkeypatch.setitem(sys.modules, "PIL", None)
        result = _import(out, [_anno(target, body="cat")])
        assert any("Pillow is not installed" in w for w in result.warnings), result.warnings


class TestAudit97MediaIri:
    """Audit 97 V8: a region's source was the server path "/media/...", not an IRI."""

    def _ctx(self, out):
        schemas = [{"name": "boxes", "annotation_type": "image_annotation", "description": "Boxes",
                    "labels": ["cat"], "source_field": "image_url"}]
        annotations = [{"instance_id": "p1", "user_id": "bob", "labels": {},
                        "image_annotations": {"boxes": [
                            {"type": "bbox", "label": "cat",
                             "coordinates": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}}]}}]
        items = {"p1": {"id": "p1", "text": "", "image_url": "/media/p1.png",
                        "image_width": 40, "image_height": 20}}
        config = {"annotation_task_name": "Media", "annotation_schemes": schemas,
                  "item_properties": {"id_key": "id", "text_key": "text"}}
        return ExportContext(config=config, annotations=annotations, items=items, schemas=schemas,
                             output_dir=str(out))

    @staticmethod
    def _sources(res):
        doc = json.loads(Path(res.files_written[0]).read_text())
        return [a["target"]["source"] for a in doc["first"]["items"]]

    def test_without_a_base_the_path_is_project_relative_and_warned(self, out):
        res = WebAnnotationExporter().export(self._ctx(out), str(out / "rel"))
        assert self._sources(res) == ["media/p1.png"]
        assert any("media_base_url" in w for w in res.warnings), res.warnings

    def test_media_base_url_makes_an_absolute_iri(self, out):
        res = WebAnnotationExporter().export(self._ctx(out), str(out / "abs"),
                                             {"media_base_url": "https://annotate.example.org/"})
        assert self._sources(res) == ["https://annotate.example.org/media/p1.png"]
        assert not any("media_base_url" in w for w in res.warnings)

    def test_relative_export_reimports_with_image_dir(self, out):
        from PIL import Image
        media = out / "media"
        media.mkdir()
        Image.new("RGB", (40, 20)).save(media / "p1.png")
        res = WebAnnotationExporter().export(self._ctx(out), str(out / "again"))
        result = WebAnnotationImporter().parse_path(Path(res.files_written[0]),
                                                    {"image_dir": str(media)})
        item = result.items[0]
        assert item.fields["image_url"] == "/media/p1.png"
        assert len(item.predictions["boxes"]) == 1

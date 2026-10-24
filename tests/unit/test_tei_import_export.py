"""TEI P5 in (blocks as items, inline names as spans) and out (inline
markup, standOff for spans that cannot nest), round-tripping both."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from potato.export.base import ExportContext
from potato.export.tei_exporter import TEIExporter, split_nesting
from potato.importers.text.registry import text_import_registry
from tests.helpers import dh_fixtures as fx
from tests.helpers.test_utils import create_test_directory

TEI = "{http://www.tei-c.org/ns/1.0}"


@pytest.fixture
def out():
    return Path(create_test_directory("tei_import_export"))


def _parse(path, unit="p"):
    return text_import_registry.parse_path("tei", path, {"tei_unit": unit})


class TestImport:
    def test_paragraphs_names_and_reading_text(self, out):
        path = fx.make_tei(out)
        assert text_import_registry.detect_path(path) == "tei"
        result = _parse(path)
        docs = {d.instance_id: d for d in result.documents}
        p1 = docs["p1"]                                   # xml:id becomes the id
        assert p1.text == ("The ship Margaret came into Leith on 9 March 1750, "
                           "sent by the Baltic Company.")    # note left out, spaces collapsed
        assert [(s.label, p1.text[s.start:s.end]) for s in p1.spans] == [
            ("ship", "Margaret"), ("placeName", "Leith"), ("date", "9 March 1750"),
            ("orgName", "the Baltic Company")]
        paid = next(d for d in result.documents if d.text.startswith("Paid"))
        assert paid.text == "Paid to John Smith for forty barrels."   # expan and corr chosen
        assert paid.extra["title"] == "Harbour letters (synthetic)"
        verse = next(d for d in result.documents if d.extra["tei_unit"] == "lg")
        assert verse.text == "The tide comes in at Dunbar,\nthe gulls go out to sea."
        assert not result.warnings
        assert {l["name"] for l in result.labels} == {"persName", "ship", "placeName", "date", "orgName"}

    def test_offsets_index_the_rendered_text(self, out):
        from potato.server_utils.span_text import instance_dom_text, normalize_display_text
        result = _parse(fx.make_tei(out), unit="div")
        for doc in result.documents:
            assert instance_dom_text(normalize_display_text(doc.text)) == doc.text
            for span in doc.spans:
                assert doc.text[span.start:span.end] == span.text

    def test_units(self, out):
        path = fx.make_tei(out)
        assert len(_parse(path, "div").documents) == 2
        assert [d.text for d in _parse(path, "l").documents] == [
            "The tide comes in at Dunbar,", "the gulls go out to sea."]
        with pytest.raises(ValueError):
            _parse(path, "chapter")


def _ctx(out, text, spans, items_extra=None):
    items = {"d1": {"id": "d1", "text": text, **(items_extra or {})}}
    schemas = [{"name": "spans", "annotation_type": "span", "description": "x", "labels": ["a"]}]
    annotations = [{"instance_id": "d1", "user_id": "u", "labels": {},
                    "spans": {"spans": [{"name": l, "start": s, "end": e} for s, e, l in spans]}}]
    config = {"annotation_task_name": "TEI test", "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": schemas}
    return ExportContext(config=config, annotations=annotations, items=items, schemas=schemas,
                         output_dir=str(out))


class TestExport:
    def test_inline_markup_with_tei_names_and_rs(self, out):
        text = "Anna met Ben in Oslo."
        ctx = _ctx(out, text, [(0, 4, "persName"), (9, 12, "PER"), (16, 20, "placeName")])
        res = TEIExporter().export(ctx, str(out / "x"))
        assert res.success
        raw = Path(res.files_written[0]).read_text(encoding="utf-8")
        root = ET.fromstring(raw.encode())             # well-formed
        p = root.find(f".//{TEI}p[@{{http://www.w3.org/XML/1998/namespace}}id='d1']")
        assert "".join(p.itertext()) == text
        assert [c.tag.replace(TEI, "") for c in p] == ["persName", "rs", "placeName"]
        assert p[1].get("type") == "PER"
        assert root.find(f".//{TEI}standOff") is None

    def test_overlapping_spans_go_to_standoff_and_come_back(self, out):
        text = "New York City Hall\nopened in 1812."
        spans = [(0, 13, "placeName"), (9, 18, "orgName"), (0, 8, "placeName"), (29, 33, "date")]
        inline, standoff = split_nesting([{"start": s, "end": e, "label": l} for s, e, l in spans])
        assert [(s["start"], s["end"]) for s in standoff] == [(9, 18)]
        ctx = _ctx(out, text, spans)
        res = TEIExporter().export(ctx, str(out / "x"))
        path = Path(res.files_written[0])
        root = ET.parse(path).getroot()
        ann = root.find(f".//{TEI}listAnnotation/{TEI}annotation")
        assert ann.get("target") == "#string-range(d1,9,9)"
        assert root.find(f".//{TEI}p/{TEI}lb") is not None
        result = text_import_registry.parse_path("tei", path, {})
        doc = result.documents[0]
        assert doc.instance_id == "d1" and doc.text == text
        assert sorted((s.start, s.end, s.label) for s in doc.spans) == sorted(spans)

    def test_guard_string_range_counts_lb_as_nothing(self, out):
        """After a newline the string-value offset is one less than the item offset."""
        text = "line one\nKing Street"
        ctx = _ctx(out, text, [(9, 20, "placeName"), (14, 20, "name"), (11, 16, "rs")])
        res = TEIExporter().export(ctx, str(out / "x"))
        root = ET.parse(res.files_written[0]).getroot()
        targets = [a.get("target") for a in root.iter(f"{TEI}annotation")]
        # "name" (14-20) crosses the inline "rs" (11-16): standOff at item
        # offset 14, which is string-value offset 13
        assert targets == ["#string-range(d1,13,6)"]
        back = text_import_registry.parse_path("tei", Path(res.files_written[0]), {}).documents[0]
        assert ("name", "Street") in {(s.label, back.text[s.start:s.end]) for s in back.spans}

    def test_round_trip_of_an_imported_file(self, out):
        result = _parse(fx.make_tei(out / "src"))
        items, annotations = {}, []
        for d in result.documents:
            items[d.instance_id] = {"id": d.instance_id, "text": d.text, **d.extra}
            annotations.append({"instance_id": d.instance_id, "user_id": "u", "labels": {},
                                "spans": {"spans": [{"name": s.label, "start": s.start, "end": s.end}
                                                    for s in d.spans]}})
        schemas = [{"name": "spans", "annotation_type": "span", "description": "x", "labels": []}]
        ctx = ExportContext(config={"item_properties": {"text_key": "text"}}, annotations=annotations,
                            items=items, schemas=schemas, output_dir=str(out))
        res = TEIExporter().export(ctx, str(out / "x"))
        assert [Path(f).name for f in res.files_written] == ["letters.xml"]
        again = text_import_registry.parse_path("tei", Path(res.files_written[0]), {})
        before = {(d.text, tuple((s.start, s.end, s.label) for s in d.spans)) for d in result.documents}
        after = {(d.text, tuple((s.start, s.end, s.label) for s in d.spans)) for d in again.documents}
        assert before == after
        root = ET.parse(res.files_written[0]).getroot()
        assert root.find(f".//{TEI}title").text == "Harbour letters (synthetic)"
        assert root.find(f".//{TEI}rs[@type='ship']") is not None


def test_cli_unit_flag_reaches_the_importer(out):
    from potato.importers.cli import main
    path = fx.make_tei(out / "src")
    assert main(["-i", str(path), "-o", str(out / "cli"), "--tei-unit", "l"]) == 0
    rows = [json.loads(l) for l in (out / "cli" / "data" / "letters.json").read_text().splitlines()]
    assert [r["text"] for r in rows] == ["The tide comes in at Dunbar,", "the gulls go out to sea."]


def test_export_keeps_source_order_not_annotation_order(out):
    """Audit 97 V2: paragraphs came out in the order they were annotated."""
    ids = [f"p{n:02d}" for n in range(1, 13)]
    items = {iid: {"id": iid, "text": f"Paragraph {iid} names Oslo."} for iid in ids}
    annotated = [ids[i] for i in (1, 10, 8, 4, 3, 6, 9, 2, 5, 11, 0, 7)]
    annotations = [{"instance_id": iid, "user_id": "u", "labels": {},
                    "spans": {"spans": [{"name": "placeName", "start": 20, "end": 24}]}}
                   for iid in annotated]
    schemas = [{"name": "spans", "annotation_type": "span", "description": "x", "labels": ["a"]}]
    config = {"annotation_task_name": "TEI test", "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": schemas}
    ctx = ExportContext(config=config, annotations=annotations, items=items, schemas=schemas,
                        output_dir=str(out))
    res = TEIExporter().export(ctx, str(out / "order"))
    assert res.success, res.errors
    root = ET.parse(res.files_written[0]).getroot()
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    assert [p.get(xml_id) for p in root.iter(f"{TEI}p") if p.get(xml_id)] == ids


def test_malformed_tei_names_the_parse_error(out):
    """Audit 97 V9: the XML error was collected and then dropped."""
    bad = out / "bad.xml"
    bad.write_text('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>open</body></text></TEI>',
                   encoding="utf-8")
    with pytest.raises(ValueError) as err:
        _parse(bad)
    message = str(err.value)
    assert "not well-formed XML" in message
    assert "mismatched tag" in message

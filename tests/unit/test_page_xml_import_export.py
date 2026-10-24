"""PAGE XML in (line transcription or layout correction) and back out, with
the corrections written into the original file and everything else kept."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from potato.export.page_xml_exporter import PageXMLExporter
from potato.importers import projects
from potato.importers.projects.page_xml import PageXMLImporter
from potato.importers.projects.writer import write_project
from tests.helpers import dh_fixtures as fx
from tests.helpers.test_utils import create_test_directory

NS = {"p": fx.PAGE_NS}


@pytest.fixture
def out():
    return Path(create_test_directory("page_xml_import_export"))


def _project(out, mode="lines", transkribus=True):
    src = out / "src"
    fx.make_page_xml(src, transkribus_layout=transkribus)
    result = PageXMLImporter().parse_path(src, {"page_xml_mode": mode})
    project = out / f"project-{mode}"
    write_project(result, str(project), source=str(src))
    return project, result


def _save(project, user, labels=None, images=None):
    labels = labels or {}
    state = {"user_id": user, "instance_id_ordering": list(labels) or list(images or {}),
             "current_instance_index": 0, "instance_id_to_span_to_value": {},
             "instance_id_to_label_to_value": {}}
    for iid, text in labels.items():
        blob = json.dumps({"edited_text": text, "original_text": "", "edit_distance_chars": 0,
                           "edit_distance_words": 0})
        state["instance_id_to_label_to_value"][iid] = [
            [{"schema": "transcription", "name": "transcription"}, blob]]
    for iid, objects in (images or {}).items():
        state["instance_id_to_label_to_value"][iid] = [
            [{"schema": "layout", "name": "_data"}, json.dumps(objects)]]
    d = project / "annotation_output" / user
    d.mkdir(parents=True, exist_ok=True)
    (d / "user_state.json").write_text(json.dumps(state))


def _export(project, out, **options):
    from potato.export.cli import build_export_context
    ctx = build_export_context(str(project / "config.yaml"))
    dest = out / "export"
    res = PageXMLExporter().export(ctx, str(dest), options)
    assert res.success, res.errors
    return dest, res


class TestLinesImport:
    def test_one_item_per_line_in_reading_order(self, out):
        src = out / "src"
        fx.make_page_xml(src, transkribus_layout=True)
        assert projects.detect(str(src)) == "page_xml"
        result = PageXMLImporter().parse_path(src)
        assert [i.fields["line_id"] for i in result.items] == ["r1l1", "r2l1", "r2l2", "r2l3", "r3l1"]
        first = result.items[0].fields
        assert first["htr_text"] == "Letter to the harbour rnaster"
        assert first["line_image"]["image"] == "/media/letter.png"
        assert (first["line_image"]["width"], first["line_image"]["height"]) == (1000, 700)
        assert first["line_image"]["region"] == [120, 60, 640, 56]
        assert first["htr_confidence"] == "0.87"
        assert result.media_files["media/letter.png"].endswith("src/letter.png")   # one folder up
        scheme = result.schemes[0]
        assert scheme["annotation_type"] == "text_edit" and scheme["source_field"] == "htr_text"
        assert result.instance_display["fields"][0]["type"] == "image_region"

    def test_2013_schema_with_point_children(self, out):
        old = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
        xml = (f'<PcGts xmlns="{old}"><Page imageFilename="x.png" imageWidth="100" imageHeight="50">'
               '<TextRegion id="r"><Coords><Point x="0" y="0"/><Point x="90" y="0"/>'
               '<Point x="90" y="40"/></Coords><TextLine id="l"><Coords><Point x="5" y="5"/>'
               '<Point x="80" y="5"/><Point x="80" y="30"/></Coords>'
               '<TextEquiv><Unicode>old text</Unicode></TextEquiv></TextLine></TextRegion></Page></PcGts>')
        (out / "old.xml").write_text(xml)
        from PIL import Image
        Image.new("RGB", (100, 50)).save(out / "x.png")
        result = PageXMLImporter().parse_path(out / "old.xml")
        item = result.items[0]
        assert item.fields["htr_text"] == "old text"
        assert item.fields["line_image"]["region"] == [5, 5, 75, 25]


class TestLinesExport:
    def test_corrected_text_is_written_and_the_rest_kept(self, out):
        project, result = _project(out)
        ids = {i.fields["line_id"]: i.instance_id for i in result.items}
        _save(project, "editor", {ids["r1l1"]: "Letter to the harbour master",
                                  ids["r2l1"]: "The ship Margaret arrived on the ninth"})
        dest, res = _export(project, out)
        path = dest / "page_xml" / "page" / "letter.xml"
        raw = path.read_text(encoding="utf-8")
        assert raw.startswith("<?xml") and "<PcGts xmlns=\"" + fx.PAGE_NS in raw     # default ns kept
        assert "ns0:" not in raw
        assert "<!-- kept by the exporter -->" in raw
        root = ET.fromstring(raw.encode())
        line = root.find(".//p:TextLine[@id='r1l1']", NS)
        assert line.find("p:TextEquiv/p:Unicode", NS).text == "Letter to the harbour master"
        assert "conf" not in line.find("p:TextEquiv", NS).attrib
        assert line.find("p:Word", NS) is None             # stale words dropped
        assert line.find("p:Baseline", NS) is not None
        untouched = root.find(".//p:TextLine[@id='r2l2']", NS)
        assert untouched.find("p:TextEquiv/p:Unicode", NS).text == "of March with forty barels of salt"
        assert untouched.find("p:TextEquiv", NS).get("conf") == "0.87"
        assert untouched.find("p:Word", NS) is not None
        region = root.find(".//p:TextRegion[@id='r2']", NS)
        assert region.find("p:TextEquiv/p:Unicode", NS).text.split("\n")[0] == \
            "The ship Margaret arrived on the ninth"
        assert root.find(".//p:ReadingOrder", NS) is not None
        assert root.find(".//p:ImageRegion", NS) is not None
        assert root.find(".//p:LastChange", NS).text != "2026-01-01T00:00:00"
        assert res.stats["lines_changed"] == 2

    def test_keep_words_option(self, out):
        project, result = _project(out)
        iid = result.items[0].instance_id
        _save(project, "editor", {iid: "Letter to the harbour master"})
        dest, _ = _export(project, out, keep_words="true")
        root = ET.parse(dest / "page_xml" / "page" / "letter.xml").getroot()
        assert root.find(".//p:TextLine[@id='r1l1']/p:Word", NS) is not None

    def test_each_annotator_gets_a_folder(self, out):
        project, result = _project(out)
        iid = result.items[0].instance_id
        _save(project, "a1", {iid: "first reading"})
        _save(project, "a2", {iid: "second reading"})
        dest, _ = _export(project, out)
        for user, text in (("a1", "first reading"), ("a2", "second reading")):
            root = ET.parse(dest / user / "page_xml" / "page" / "letter.xml").getroot()
            assert root.find(".//p:TextLine[@id='r1l1']/p:TextEquiv/p:Unicode", NS).text == text
        only, _ = _export(project, out, annotator="a2")
        assert (only / "page_xml" / "page" / "letter.xml").exists()


def _poly(x, y, w, h, label, pid=None):
    obj = {"type": "polygon", "label": label, "coordinates": [
        {"x": x / 1000, "y": y / 700}, {"x": (x + w) / 1000, "y": y / 700},
        {"x": (x + w) / 1000, "y": (y + h) / 700}, {"x": x / 1000, "y": (y + h) / 700}]}
    if pid:
        obj["attributes"] = {"page_xml_id": pid}
    return obj


class TestLayout:
    def test_regions_mode_imports_polygons_with_their_ids(self, out):
        _project_dir, result = _project(out, mode="regions")
        item = result.items[0]
        labels = [(o["label"], o["attributes"]["page_xml_id"]) for o in item.predictions["layout"]]
        assert ("heading", "r1") in labels and ("image", "img1") in labels and ("line", "r2l3") in labels
        assert set(result.schemes[0]["labels"]) == {"heading", "paragraph", "marginalia", "image", "line"}

    def test_moved_deleted_and_new_shapes(self, out):
        project, result = _project(out, mode="regions")
        item = result.items[0]
        kept = [o for o in item.predictions["layout"]
                if o["attributes"]["page_xml_id"] not in ("r3", "r3l1", "img1", "r2l1")]
        moved = _poly(100, 30, 720, 120, "caption", "r1")
        objects = [moved if o["attributes"]["page_xml_id"] == "r1" else o for o in kept]
        objects.append(_poly(130, 192, 700, 50, "line"))       # redrawn line inside r2
        objects.append(_poly(600, 600, 200, 60, "footnote"))   # a new region
        _save(project, "editor", images={item.instance_id: objects})
        dest, res = _export(project, out)
        root = ET.parse(dest / "page_xml" / "page" / "letter.xml").getroot()
        r1 = root.find(".//p:TextRegion[@id='r1']", NS)
        assert r1.find("p:Coords", NS).get("points") == "100,30 820,30 820,150 100,150"
        assert r1.get("type") == "caption"
        assert root.find(".//p:TextRegion[@id='r3']", NS) is None
        assert root.find(".//p:ImageRegion", NS) is None
        assert root.find(".//p:TextLine[@id='r2l1']", NS) is None
        refs = [r.get("regionRef") for r in root.iter(f"{{{fx.PAGE_NS}}}RegionRefIndexed")]
        assert refs == ["r1", "r2"]
        r2 = root.find(".//p:TextRegion[@id='r2']", NS)
        new_lines = [l for l in r2.findall("p:TextLine", NS) if l.get("id").startswith("l_potato")]
        assert len(new_lines) == 1
        # the new line sits before the region's TextEquiv
        tags = [c.tag.rsplit("}", 1)[-1] for c in r2]
        assert tags.index("TextEquiv") > tags.index("TextLine")
        footnote = [r for r in root.iter(f"{{{fx.PAGE_NS}}}TextRegion") if r.get("type") == "footnote"]
        assert len(footnote) == 1
        assert res.stats["shapes_removed"] == 3 and res.stats["shapes_added"] == 2

    def test_unannotated_page_is_unchanged(self, out):
        project, result = _project(out, mode="regions")
        _save(project, "editor", labels={})
        from potato.export.cli import build_export_context
        ctx = build_export_context(str(project / "config.yaml"))
        res = PageXMLExporter().export(ctx, str(out / "export"))
        assert not res.success          # nothing to write: no annotation on the page


def test_cli_mode_flag_reaches_the_importer(out):
    from potato.importers.cli import main
    src = out / "src"
    fx.make_page_xml(src)
    assert main(["-i", str(src), "-o", str(out / "cli"), "--page-xml-mode", "regions"]) == 0
    config = (out / "cli" / "config.yaml").read_text()
    assert "annotation_type: image_annotation" in config and "name: layout" in config
    assert (out / "cli" / "page_xml" / "letter.xml").exists()
    assert (out / "cli" / "media" / "letter.png").exists()


@pytest.mark.parametrize("mode", ["lines", "regions"])
def test_coords_outside_the_image_are_reported(out, mode):
    """Audit 97 V11: coordinates past imageWidth/imageHeight were kept silently."""
    src = out / f"outside-{mode}"
    xml = fx.make_page_xml(src)
    raw = xml.read_text(encoding="utf-8")
    xml.write_text(raw.replace(f'imageWidth="{fx.PAGE_WIDTH}"', 'imageWidth="600"'), encoding="utf-8")
    result = PageXMLImporter().parse_path(src, {"page_xml_mode": mode})
    warned = [w for w in result.warnings if "outside the 600x" in w]
    assert len(warned) == 1, result.warnings
    if mode == "lines":        # the five lines that run past x=600
        assert "5 region(s) or line(s)" in warned[0] and "r2l1" in warned[0]
    else:                      # three regions (one is an image) and those five lines
        assert "9 region(s) or line(s)" in warned[0] and "r1, r2, r3" in warned[0]


@pytest.mark.parametrize("mode", ["lines", "regions"])
def test_coords_inside_the_image_raise_no_warning(out, mode):
    src = out / f"inside-{mode}"
    fx.make_page_xml(src)
    result = PageXMLImporter().parse_path(src, {"page_xml_mode": mode})
    assert not [w for w in result.warnings if "outside the" in w], result.warnings

"""
QuPath GeoJSON and ASAP XML: import as pre-annotations, export, round trip.

Coordinates are slide pixels at level 0 in both files and fractions of the
slide in Potato, so every test checks numbers in pixel space against the file
it started from. Most use a small synthetic PNG (Pillow reads its size); one
uses the whole-slide example's synthetic Aperio slide through openslide.
"""

import json
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from potato.export.base import ExportContext
from potato.export.registry import export_registry
from potato.importers import projects
from potato.importers.projects.writer import write_project
from potato.media import pathology_regions as pr
from tests.helpers.test_utils import create_test_directory

W, H = 400, 300
EXAMPLE_SLIDE = Path("examples/image/whole-slide/media/synthetic_tissue.svs")
EXAMPLE_REGIONS = Path("examples/image/whole-slide/regions")

TRIANGLE = [[10.5, 20.25], [120, 40], [60.75, 150.5]]

QUPATH = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "id": "a1",
     "geometry": {"type": "Polygon", "coordinates": [TRIANGLE + [TRIANGLE[0]]]},
     "properties": {"objectType": "annotation", "name": "first",
                    "classification": {"name": "Tumor", "color": [200, 0, 0]}}},
    {"type": "Feature", "id": "a2",          # a QuPath rectangle: an upright 4-gon
     "geometry": {"type": "Polygon", "coordinates": [[[200, 50], [300, 50], [300, 120],
                                                       [200, 120], [200, 50]]]},
     "properties": {"objectType": "annotation",
                    "classification": {"name": "Stroma", "color": [0, 150, 0]}}},
    {"type": "Feature", "id": "a3",
     "geometry": {"type": "LineString", "coordinates": [[5, 5], [50, 60], [90, 20]]},
     "properties": {"objectType": "annotation",
                    "classification": {"name": "Tumor", "color": [200, 0, 0]}}},
    {"type": "Feature", "id": "a4",
     "geometry": {"type": "Point", "coordinates": [333.5, 222.25]},
     "properties": {"objectType": "annotation"}},                       # unclassified
]}


def write_png(path, size=(W, H)):
    from PIL import Image
    Image.new("RGB", size, (240, 200, 220)).save(path)


@pytest.fixture
def folder(request):
    d = create_test_directory(f"pathology_{request.node.name}"[:60])
    for child in Path(d).iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    write_png(os.path.join(d, "case1.png"))
    return Path(d)


def _px(obj, w=W, h=H):
    from potato.export.cv_utils import normalize_annotation_object
    return normalize_annotation_object(obj, w, h)


def _context(result, user="pat"):
    """Records as the server stores them once an annotator saves the
    pre-annotations unchanged."""
    items, annotations = {}, []
    for item in result.items:
        items[item.instance_id] = dict(item.fields, id=item.instance_id)
        annotations.append({"instance_id": item.instance_id, "user_id": user, "labels": {},
                            "spans": {}, "image_annotations": json.loads(
                                json.dumps(item.predictions))})
    return ExportContext(config={"annotation_task_name": "WSI"}, annotations=annotations,
                         items=items, schemas=result.schemes, output_dir="")


# -- QuPath import ---------------------------------------------------------------

class TestQuPathImport:
    def test_regions_land_where_the_file_put_them(self, folder):
        (folder / "case1.geojson").write_text(json.dumps(QUPATH))
        assert projects.detect(str(folder / "case1.geojson")) == "qupath_geojson"
        result = projects.IMPORTERS["qupath_geojson"].parse_path(folder / "case1.geojson", {})
        (item,) = result.items
        assert item.fields["image"] == "case1.png"
        assert (item.fields["image_width"], item.fields["image_height"]) == (W, H)
        objs = item.predictions["regions"]
        assert [o["type"] for o in objs] == ["polygon", "bbox", "polyline", "landmark"]
        assert _flat(_px(objs[0])["points"]) == pytest.approx(_flat(TRIANGLE))
        assert _px(objs[1])["bbox"] == pytest.approx([200, 50, 100, 70])
        assert _flat(_px(objs[2])["points"]) == pytest.approx(_flat([[5, 5], [50, 60], [90, 20]]))
        assert _flat(_px(objs[3])["points"]) == pytest.approx(_flat([[333.5, 222.25]]))
        assert [o["label"] for o in objs] == ["Tumor", "Stroma", "Tumor", "Unclassified"]
        assert all(o["source"] == "import" and o["import_format"] == "qupath_geojson"
                   for o in objs)
        assert objs[0]["attributes"] == {"qupath_id": "a1", "qupath_name": "first"}
        scheme = result.schemes[0]
        assert scheme["viewer"] == "deepzoom" and scheme["source_field"] == "image"
        assert {l["name"]: l["color"] for l in scheme["labels"]} == {
            "Tumor": "#c80000", "Stroma": "#009600", "Unclassified": pr.DEFAULT_COLOR}
        assert result.extra_config == {"media_directory": str(folder.resolve())}

    def test_qupath_02_lists_packed_colours_multipolygons_and_holes(self, folder):
        outer = [[0, 0], [100, 0], [100, 80], [0, 90], [0, 0]]
        hole = [[10, 10], [20, 10], [20, 20], [10, 10]]
        doc = [   # QuPath 0.2: a bare list of features and colorRGB
            {"type": "Feature", "id": "PathAnnotationObject",
             "geometry": {"type": "MultiPolygon", "coordinates": [
                 [outer, hole], [[[200, 200], [250, 210], [240, 260], [200, 200]]]]},
             "properties": {"isLocked": False, "measurements": [],
                            "classification": {"name": "Necrosis", "colorRGB": -3670016}}},
            {"type": "Feature", "geometry": {"type": "MultiPoint",
                                             "coordinates": [[1, 2], [3, 4]]},
             "properties": {"isLocked": False}}]
        (folder / "case1.json").write_text(json.dumps(doc))
        result = projects.IMPORTERS["qupath_geojson"].parse_path(folder / "case1.json", {})
        objs = result.items[0].predictions["regions"]
        assert [o["type"] for o in objs] == ["polygon", "polygon", "landmark", "landmark"]
        assert objs[0]["instance"] == objs[1]["instance"]      # two parts of one object
        assert _flat(_px(objs[0])["points"]) == pytest.approx(_flat(outer[:-1]))
        assert result.schemes[0]["labels"][0] == {"name": "Necrosis", "color": "#c80000"}
        assert any("holes" in w for w in result.warnings)
        assert result.skipped["polygon holes dropped"] == 1

    def test_map_geojson_is_not_mistaken_for_qupath(self, folder):
        geo = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-83.7, 42.3]},
             "properties": {"name": "Ann Arbor"}}]}
        (folder / "case1.geojson").write_text(json.dumps(geo))
        assert not projects.IMPORTERS["qupath_geojson"].detect_path(folder / "case1.geojson")
        assert projects.detect(str(folder / "case1.geojson")) != "qupath_geojson"

    def test_a_file_without_its_slide_is_left_out_and_said_so(self, folder):
        (folder / "case1.geojson").write_text(json.dumps(QUPATH))
        (folder / "case2.geojson").write_text(json.dumps(QUPATH))
        result = projects.IMPORTERS["qupath_geojson"].parse_path(folder, {})
        assert [i.instance_id for i in result.items] == ["case1"]
        assert any("case2.geojson: no slide named case2" in w for w in result.warnings)
        (folder / "case1.png").unlink()
        with pytest.raises(ValueError, match="could be paired"):
            projects.IMPORTERS["qupath_geojson"].parse_path(folder, {})

    def test_a_slide_linked_from_outside_the_input_is_refused(self, folder):
        outside = Path(create_test_directory("pathology_outside"))
        write_png(outside / "secret.png")
        (folder / "secret.png").symlink_to(outside / "secret.png")
        (folder / "secret.geojson").write_text(json.dumps(QUPATH))
        # secret.png is in the input folder by name but resolves outside it.
        with pytest.raises(ValueError, match="no slide named secret"):
            projects.IMPORTERS["qupath_geojson"].parse_path(folder / "secret.geojson", {})

    def test_regions_off_the_slide_are_kept_with_a_warning(self, folder):
        doc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [4000, 10]},
             "properties": {"objectType": "annotation"}}]}
        (folder / "case1.geojson").write_text(json.dumps(doc))
        result = projects.IMPORTERS["qupath_geojson"].parse_path(folder / "case1.geojson", {})
        assert len(result.items[0].predictions["regions"]) == 1
        assert any("outside the 400x300 slide" in w for w in result.warnings)

    def test_the_slide_name_may_keep_its_extension(self, folder):
        (folder / "case1.png.geojson").write_text(json.dumps(QUPATH))
        result = projects.IMPORTERS["qupath_geojson"].parse_path(folder / "case1.png.geojson", {})
        assert result.items[0].fields["image"] == "case1.png"

    def test_image_dir_is_searched_and_the_project_validates(self, folder):
        slides = Path(create_test_directory("pathology_slides"))
        write_png(slides / "elsewhere.png", (800, 600))
        regions = folder / "regions"
        regions.mkdir()
        (regions / "elsewhere.geojson").write_text(json.dumps(QUPATH))
        result = projects.IMPORTERS["qupath_geojson"].parse_path(
            regions / "elsewhere.geojson", {"image_dir": str(slides)})
        assert result.items[0].fields["image_width"] == 800
        assert result.extra_config["media_directory"] == str(slides.resolve())
        out = folder / "project"
        write_project(result, str(out), source=str(regions / "elsewhere.geojson"),
                      extra_config=result.extra_config)
        import yaml
        config = yaml.safe_load((out / "config.yaml").read_text())
        assert config["pre_annotation"]["enabled"] is True
        assert config["media_directory"] == str(slides.resolve())
        from potato.server_utils.config_module import validate_single_annotation_scheme
        validate_single_annotation_scheme(config["annotation_schemes"][0], "annotation_schemes[0]")
        row = json.loads((out / "data" / "elsewhere.jsonl").read_text().splitlines()[0])
        assert len(row["predictions"]["regions"]) == 4


# -- ASAP import -----------------------------------------------------------------

ASAP = """<?xml version="1.0"?>
<ASAP_Annotations>
  <Annotations>
    <Annotation Name="Annotation 0" Type="Polygon" PartOfGroup="tumor" Color="#F4FA58">
      <Coordinates>
        <Coordinate Order="2" X="60,75" Y="150,5" />
        <Coordinate Order="0" X="10.5" Y="20.25" />
        <Coordinate Order="1" X="120" Y="40" />
      </Coordinates>
    </Annotation>
    <Annotation Name="box" Type="Rectangle" PartOfGroup="Exclusion" Color="#000000">
      <Coordinates>
        <Coordinate Order="0" X="200" Y="50" /><Coordinate Order="1" X="300" Y="50" />
        <Coordinate Order="2" X="300" Y="120" /><Coordinate Order="3" X="200" Y="120" />
      </Coordinates>
    </Annotation>
    <Annotation Name="d" Type="Dot" PartOfGroup="None" Color="#123456">
      <Coordinates><Coordinate Order="0" X="333.5" Y="222.25" /></Coordinates>
    </Annotation>
    <Annotation Name="ruler" Type="Measurement" PartOfGroup="tumor" Color="#F4FA58">
      <Coordinates><Coordinate Order="0" X="5" Y="5" /><Coordinate Order="1" X="50" Y="60" /></Coordinates>
    </Annotation>
    <Annotation Name="s" Type="Spline" PartOfGroup="tumor" Color="#F4FA58">
      <Coordinates><Coordinate Order="0" X="1" Y="1" /><Coordinate Order="1" X="9" Y="1" />
        <Coordinate Order="2" X="5" Y="9" /></Coordinates>
    </Annotation>
  </Annotations>
  <AnnotationGroups>
    <Group Name="tumor" PartOfGroup="None" Color="#64FE2E"><Attributes /></Group>
    <Group Name="Exclusion" PartOfGroup="None" Color="#FF0000"><Attributes /></Group>
  </AnnotationGroups>
</ASAP_Annotations>
"""


class TestASAPImport:
    def test_types_groups_order_and_decimal_commas(self, folder):
        (folder / "case1.xml").write_text(ASAP)
        assert projects.detect(str(folder / "case1.xml")) == "asap_xml"
        result = projects.IMPORTERS["asap_xml"].parse_path(folder / "case1.xml", {})
        objs = result.items[0].predictions["regions"]
        assert [o["type"] for o in objs] == ["polygon", "bbox", "landmark", "polyline", "polygon"]
        assert _flat(_px(objs[0])["points"]) == pytest.approx(_flat(TRIANGLE))   # sorted by Order
        assert _px(objs[1])["bbox"] == pytest.approx([200, 50, 100, 70])
        assert _flat(_px(objs[2])["points"]) == pytest.approx(_flat([[333.5, 222.25]]))
        assert [o["label"] for o in objs] == ["tumor", "Exclusion", "Unclassified",
                                              "tumor", "tumor"]
        # The group's colour wins over the annotation's.
        assert {l["name"]: l["color"] for l in result.schemes[0]["labels"]}["tumor"] == "#64FE2E"
        assert any("Spline" in w for w in result.warnings)

    def test_page_xml_and_other_xml_are_not_asap(self, folder):
        (folder / "case1.xml").write_text('<?xml version="1.0"?><PcGts xmlns="http://schema.'
                                          'primaresearch.org/PAGE/gts/pagecontent/2019-07-15"/>')
        assert not projects.IMPORTERS["asap_xml"].detect_path(folder / "case1.xml")

    def test_malformed_xml_is_reported_not_raised(self, folder):
        (folder / "case1.xml").write_text("<ASAP_Annotations><Annotations>")
        with pytest.raises(ValueError, match="could be paired"):
            projects.IMPORTERS["asap_xml"].parse_path(folder / "case1.xml", {})


# -- export and round trips -----------------------------------------------------

def _flat(coords):
    """Nested coordinate lists as one flat list of numbers."""
    if isinstance(coords, (int, float)):
        return [coords]
    return [v for c in coords for v in _flat(c)]


def _qupath_geometry(doc):
    return [(f["geometry"]["type"], f["geometry"]["coordinates"],
             (f["properties"].get("classification") or {}).get("name")) for f in doc["features"]]


class TestRoundTrip:
    def test_qupath_import_then_export_gives_the_same_geometry(self, folder):
        (folder / "case1.geojson").write_text(json.dumps(QUPATH))
        result = projects.IMPORTERS["qupath_geojson"].parse_path(folder / "case1.geojson", {})
        out = folder / "out"
        exported = export_registry.export("qupath_geojson", _context(result), str(out))
        assert exported.success
        (path,) = exported.files_written
        assert path == str(out / "pat" / "case1.geojson")
        back = json.loads(Path(path).read_text())
        got, want = _qupath_geometry(back), _qupath_geometry(QUPATH)
        assert [(k, n) for k, _c, n in got] == [(k, n) for k, _c, n in want]
        for (_k, coords, _n), (_k0, c0, _n0) in zip(got, want):
            assert _flat(coords) == pytest.approx(_flat(c0))
        assert [f["id"] for f in back["features"]] == ["a1", "a2", "a3", "a4"]
        props = back["features"][0]["properties"]
        assert props["classification"] == {"name": "Tumor", "color": [200, 0, 0]}
        assert props["name"] == "first" and props["objectType"] == "annotation"
        assert "classification" not in back["features"][3]["properties"]   # unclassified

    def test_asap_import_then_export_gives_the_same_geometry(self, folder):
        (folder / "case1.xml").write_text(ASAP)
        result = projects.IMPORTERS["asap_xml"].parse_path(folder / "case1.xml", {})
        exported = export_registry.export("asap_xml", _context(result), str(folder / "out"))
        (path,) = exported.files_written
        root = ET.fromstring(Path(path).read_text())
        annotations = root.find("Annotations")
        got = [(a.get("Type"), a.get("PartOfGroup"), a.get("Name"),
                [[float(c.get("X")), float(c.get("Y"))] for c in a.find("Coordinates")])
               for a in annotations]
        assert [g[:3] for g in got] == [("Polygon", "tumor", "Annotation 0"),
                                        ("Rectangle", "Exclusion", "box"),
                                        ("Dot", "None", "d"),
                                        ("Measurement", "tumor", "ruler"),
                                        ("Polygon", "tumor", "s")]
        assert _flat(got[0][3]) == pytest.approx(_flat(TRIANGLE))
        assert _flat(got[1][3]) == pytest.approx(_flat([[200, 50], [300, 50], [300, 120], [200, 120]]))
        assert _flat(got[2][3]) == pytest.approx(_flat([[333.5, 222.25]]))
        groups = {g.get("Name"): g.get("Color") for g in root.find("AnnotationGroups")}
        assert groups == {"tumor": "#64FE2E", "Exclusion": "#FF0000"}
        # Read back by our own importer: same objects.
        again = pr.read_asap(Path(path).read_bytes(), W, H)
        first = result.items[0].predictions["regions"]
        assert [o["type"] for o in again.objects] == [o["type"] for o in first]
        for a, b in zip(again.objects, first):
            assert a["label"] == b["label"]
            assert _px(a)["bbox"] == pytest.approx(_px(b)["bbox"])
            if b["type"] != "bbox":
                assert _flat(_px(a)["points"]) == pytest.approx(_flat(_px(b)["points"]))

    def test_qupath_to_asap_and_back_keeps_geometry_and_classes(self, folder):
        (folder / "case1.geojson").write_text(json.dumps(QUPATH))
        result = projects.IMPORTERS["qupath_geojson"].parse_path(folder / "case1.geojson", {})
        out = folder / "asap"
        (path,) = export_registry.export("asap_xml", _context(result), str(out)).files_written
        # The three-point polyline has no ASAP type; the rest crosses over.
        reader = pr.read_asap(Path(path).read_bytes(), W, H)
        assert [o["type"] for o in reader.objects] == ["polygon", "bbox", "landmark"]
        assert [o["label"] for o in reader.objects] == ["Tumor", "Stroma", "Unclassified"]
        assert _flat(_px(reader.objects[0])["points"]) == pytest.approx(_flat(TRIANGLE))

    def test_masks_and_long_polylines_are_reported_not_dropped_silently(self, folder):
        (folder / "case1.geojson").write_text(json.dumps(QUPATH))
        result = projects.IMPORTERS["qupath_geojson"].parse_path(folder / "case1.geojson", {})
        result.items[0].predictions["regions"].append(
            {"type": "mask", "label": "Tumor", "rle": {"counts": [5, 5, 10], "size": [4, 5]}})
        exported = export_registry.export("asap_xml", _context(result), str(folder / "o"))
        assert any("brush masks are not written" in w for w in exported.warnings)
        assert any("polylines of 3 points were left out" in w for w in exported.warnings)

    def test_a_slide_of_unknown_size_is_not_written_against_zero(self, folder):
        (folder / "case1.geojson").write_text(json.dumps(QUPATH))
        result = projects.IMPORTERS["qupath_geojson"].parse_path(folder / "case1.geojson", {})
        context = _context(result)
        for item in context.items.values():
            del item["image_width"], item["image_height"]
            item["image"] = "missing.svs"
        exported = export_registry.export("qupath_geojson", context, str(folder / "o"))
        assert exported.files_written == []
        assert any("slide's size could not be read" in w for w in exported.warnings)

    def test_the_size_comes_from_the_slide_when_the_item_lacks_it(self):
        pytest.importorskip("openslide")
        out = Path(create_test_directory("pathology_example_export"))
        shutil.rmtree(out / "o", ignore_errors=True)
        result = projects.IMPORTERS["qupath_geojson"].parse_path(
            EXAMPLE_REGIONS / "synthetic_tissue.geojson",
            {"image_dir": str(EXAMPLE_SLIDE.parent)})
        context = _context(result)
        for item in context.items.values():          # as in the example's own data file
            del item["image_width"], item["image_height"]
        context.config = {"task_dir": str(EXAMPLE_SLIDE.parent.parent), "media_directory": "media"}
        (path,) = export_registry.export("qupath_geojson", context, str(out / "o")).files_written
        back = json.loads(Path(path).read_text())
        source = json.loads((EXAMPLE_REGIONS / "synthetic_tissue.geojson").read_text())
        assert len(back["features"]) == len(source["features"]) == 4
        for got, want in zip(back["features"], source["features"]):
            assert got["geometry"]["type"] == want["geometry"]["type"]
            assert _flat(got["geometry"]["coordinates"]) == pytest.approx(
                _flat(want["geometry"]["coordinates"]), abs=1e-3)


def test_the_example_asap_file_matches_the_example_qupath_file():
    """The two files under examples/image/whole-slide/regions describe the
    same regions; reading both must give the same pixels."""
    q = pr.load_qupath(EXAMPLE_REGIONS / "synthetic_tissue.geojson", 6144, 4096)
    a = pr.load_asap(EXAMPLE_REGIONS / "synthetic_tissue.xml", 6144, 4096)
    assert [o["type"] for o in q.objects] == [o["type"] for o in a.objects]
    for x, y in zip(q.objects, a.objects):
        assert x["label"] == y["label"]
        px, py = _px(x, 6144, 4096), _px(y, 6144, 4096)
        assert px["bbox"] == pytest.approx(py["bbox"], abs=1e-3)

"""IIIF manifests in (one item per canvas, existing annotations as
pre-annotations) and out (annotation pages in canvas coordinates, attached
to a copy of the manifest)."""

import json
from pathlib import Path

import pytest

from potato.export.base import ExportContext
from potato.export.iiif_exporter import IIIFAnnotationExporter
from potato.importers import projects
from potato.importers.projects import _dh
from potato.importers.projects.iiif import IIIFImporter
from potato.importers.projects.writer import write_project
from tests.helpers import dh_fixtures as fx
from tests.helpers.test_utils import create_test_directory


@pytest.fixture
def out():
    return Path(create_test_directory("iiif_import_export"))


@pytest.fixture
def no_network(monkeypatch):
    def refuse(url):
        raise AssertionError(f"network read of {url}")
    monkeypatch.setattr(_dh, "fetch_json", refuse)


def _import(out, version=3):
    manifest = fx.make_iiif(out / "src", version=version)
    return manifest, IIIFImporter().parse_path(manifest)


class TestImport:
    def test_one_item_per_canvas_with_its_image_and_metadata(self, out, no_network):
        manifest, result = _import(out)
        assert projects.detect(str(manifest)) == "iiif"
        assert [i.fields["label"] for i in result.items] == ["Folio 1r", "Folio 1v"]
        first = result.items[0].fields
        assert first["image_url"] == "/media/f1r.png"
        assert result.media_files["media/f1r.png"].endswith("images/f1r.png")
        assert first["canvas_id"] == "https://example.org/iiif/book1/canvas/f1r"
        assert (first["canvas_width"], first["canvas_height"]) == fx.CANVAS_SIZE
        assert (first["image_width"], first["image_height"]) == fx.IMAGE_SIZE
        assert first["metadata"] == {"Date": "1750", "Shelfmark": "MS Synthetic 1", "Folio": "f1r"}
        assert "Account book (synthetic)" in first["text"] and "Folio 1r" in first["text"]
        assert first["iiif_manifest"] == "iiif/manifest.json"

    def test_canvas_annotations_are_placed_in_canvas_coordinates(self, out, no_network):
        _m, result = _import(out)
        objs = result.items[0].predictions["regions"]
        # canvas box 120,120,200,200 on a 1200x1600 canvas
        box = next(o for o in objs if o["type"] == "bbox")
        assert box["label"] == "initial"
        assert box["coordinates"] == pytest.approx({"x": 0.1, "y": 0.075, "width": 1 / 6, "height": 0.125})
        poly = next(o for o in objs if o["type"] == "polygon")
        assert poly["label"] == "text block"
        assert (poly["coordinates"][0]["x"], poly["coordinates"][0]["y"]) == pytest.approx((140 / 1200, 380 / 1600))
        scheme = result.schemes[0]
        assert scheme["annotation_type"] == "image_annotation" and scheme["source_field"] == "image_url"
        assert set(scheme["labels"]) == {"initial", "text block"}

    def test_guard_image_size_would_misplace_canvas_coordinates(self, out, no_network):
        """Dividing by the image's 600x800 instead of the canvas would double the box."""
        from potato.importers.projects.web_annotation import Anno, region_object
        anno = Anno(id="a", source="c", fragment="xywh=120,120,200,200")
        wrong, _ = region_object(anno, *fx.IMAGE_SIZE, "x")
        assert wrong["coordinates"]["x"] == pytest.approx(0.2)     # what the bug produced
        _m, result = _import(out)
        box = next(o for o in result.items[0].predictions["regions"] if o["type"] == "bbox")
        assert box["coordinates"]["x"] == pytest.approx(0.1)

    def test_presentation_2_with_a_local_annotation_list(self, out, no_network):
        _m, result = _import(out, version=2)
        assert [i.fields["label"] for i in result.items] == ["Folio 1r", "Folio 1v"]
        box = result.items[0].predictions["regions"][0]
        assert box["label"] == "initial"          # <p>initial</p> comment, tag-less
        assert result.items[0].fields["iiif_version"] == 2
        # the second list is referenced but not beside the manifest
        assert result.skipped["referenced annotation pages not read"] == 1

    def test_image_service_url_when_a_size_is_asked_for(self, out, no_network):
        path = out / "remote.json"
        path.write_text(json.dumps(fx.iiif_manifest(local_images=False, with_annotations=False)))
        result = IIIFImporter().parse_path(path, {"iiif_size": "!1000,1000"})
        assert result.items[0].fields["image_url"] == \
            "https://images.example.org/iiif/f1r/full/!1000,1000/0/default.jpg"
        plain = IIIFImporter().parse_path(path)
        assert plain.items[0].fields["image_url"].endswith("/f1r/full/max/0/default.jpg")
        assert plain.schemes[0]["labels"] == ["region"]       # nothing to learn labels from

    def test_url_input_is_fetched_and_kept(self, out, monkeypatch):
        fetched = []
        doc = fx.iiif_manifest(local_images=False, with_annotations=False)

        def fake(url):
            fetched.append(url)
            return doc
        monkeypatch.setattr(_dh, "fetch_json", fake)
        url = "https://example.org/iiif/book1/manifest.json"
        assert IIIFImporter().detect_path(Path(url))          # Path() eats one slash
        result = IIIFImporter().parse_path(Path(url), {"source": url})
        assert fetched == [url]
        assert len(result.items) == 2
        kept = Path(result.media_files["iiif/manifest.json"])
        assert json.loads(kept.read_text())["id"] == doc["id"]

    def test_fetch_refuses_anything_but_http(self):
        with pytest.raises(ValueError):
            _dh.fetch_json("file:///etc/passwd")


def _context(project):
    from potato.export.cli import build_export_context
    return build_export_context(str(project / "config.yaml"))


def _annotate(project, user, iid, objects):
    """Save image annotations as `user` the way a browser save stores them."""
    state = {"user_id": user, "instance_id_ordering": [iid], "current_instance_index": 0,
             "instance_id_to_label_to_value": {iid: [[{"schema": "regions", "name": "_data"},
                                                      json.dumps(objects)]]},
             "instance_id_to_span_to_value": {}}
    d = project / "annotation_output" / user
    d.mkdir(parents=True, exist_ok=True)
    (d / "user_state.json").write_text(json.dumps(state))


class TestExport:
    def _project(self, out):
        manifest, result = _import(out)
        project = out / "project"
        write_project(result, str(project), source=str(manifest))
        return project, result

    def test_pages_target_canvas_coordinates_and_manifest_references_them(self, out, no_network):
        project, result = self._project(out)
        iid = result.items[0].instance_id
        _annotate(project, "ann1", iid, [
            {"type": "bbox", "label": "initial", "coordinates": {"x": 0.1, "y": 0.075,
                                                                 "width": 1 / 6, "height": 0.125}},
            {"type": "polygon", "label": "text block", "coordinates": [
                {"x": 0.25, "y": 0.25}, {"x": 0.75, "y": 0.25}, {"x": 0.5, "y": 0.75}]}])
        ctx = _context(project)
        exporter = IIIFAnnotationExporter()
        assert exporter.can_export(ctx)[0]
        dest = out / "export"
        res = exporter.export(ctx, str(dest), {"base_url": "https://example.org/potato/"})
        assert res.success, res.errors
        page = json.loads((dest / "annotations" / "f1r.json").read_text())
        assert page["type"] == "AnnotationPage"
        assert page["id"] == "https://example.org/potato/annotations/f1r.json"
        cid = "https://example.org/iiif/book1/canvas/f1r"
        box, poly = page["items"]
        assert box["target"] == f"{cid}#xywh=120,120,200,200"      # canvas, not image, pixels
        assert box["body"]["value"] == "initial"
        assert poly["target"]["source"]["id"] == cid
        assert 'viewBox="0 0 1200 1600"' in poly["target"]["selector"]["value"]
        assert "300,400 900,400 600,1200" in poly["target"]["selector"]["value"]

        manifest = json.loads((dest / "manifest.json").read_text())
        canvas = manifest["items"][0]
        refs = [a["id"] for a in canvas["annotations"]]
        assert refs[0].endswith("/annotations/existing")              # the original page kept
        assert refs[-1] == page["id"]
        assert "annotations" not in manifest["items"][1]               # nothing drawn on 1v

    def test_round_trip_through_an_embedded_manifest(self, out, no_network):
        project, result = self._project(out)
        iid = result.items[0].instance_id
        objects = [{"type": "bbox", "label": "initial",
                    "coordinates": {"x": 0.2, "y": 0.1, "width": 0.3, "height": 0.2}},
                   {"type": "polygon", "label": "text block", "coordinates": [
                       {"x": 0.25, "y": 0.25}, {"x": 0.75, "y": 0.25}, {"x": 0.5, "y": 0.75}]}]
        _annotate(project, "ann1", iid, objects)
        dest = out / "export"
        IIIFAnnotationExporter().export(_context(project), str(dest), {"embed": "true"})
        # The original embedded page would come back too; drop it to compare.
        manifest = json.loads((dest / "manifest.json").read_text())
        manifest["items"][0]["annotations"] = manifest["items"][0]["annotations"][-1:]
        (dest / "manifest.json").write_text(json.dumps(manifest))
        (dest / "images").mkdir()
        for slug, _l, _c in fx.FOLIOS:
            (dest / "images" / f"{slug}.png").write_bytes((out / "src" / "images" / f"{slug}.png").read_bytes())
        again = IIIFImporter().parse_path(dest / "manifest.json")
        back = again.items[0].predictions["regions"]
        assert [o["type"] for o in back] == ["bbox", "polygon"]
        assert back[0]["coordinates"] == pytest.approx(objects[0]["coordinates"], abs=1e-3)
        for p, q in zip(objects[1]["coordinates"], back[1]["coordinates"]):
            assert (q["x"], q["y"]) == pytest.approx((p["x"], p["y"]), abs=1e-3)

    def test_presentation_2_manifest_gets_annotation_lists(self, out, no_network):
        manifest, result = _import(out, version=2)
        project = out / "project2"
        write_project(result, str(project), source=str(manifest))
        _annotate(project, "ann1", result.items[1].instance_id, [
            {"type": "bbox", "label": "initial", "coordinates": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1}}])
        dest = out / "export2"
        IIIFAnnotationExporter().export(_context(project), str(dest))
        lst = json.loads((dest / "annotations" / "f1v.json").read_text())
        assert lst["@type"] == "sc:AnnotationList"
        assert lst["resources"][0]["on"].endswith("canvas/f1v#xywh=120,160,120,160")
        assert lst["resources"][0]["resource"]["chars"] == "initial"
        v2 = json.loads((dest / "manifest.json").read_text())
        other = v2["sequences"][0]["canvases"][1]["otherContent"]
        assert other[-1] == {"@id": "annotations/f1v.json", "@type": "sc:AnnotationList"}

    def test_refuses_projects_without_canvases(self, out):
        ctx = ExportContext(config={}, annotations=[{"instance_id": "a"}], items={"a": {"id": "a"}},
                            schemas=[], output_dir=str(out))
        ok, reason = IIIFAnnotationExporter().can_export(ctx)
        assert not ok and "canvas_id" in reason

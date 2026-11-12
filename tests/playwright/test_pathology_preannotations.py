"""
QuPath regions imported as pre-annotations, through the deep-zoom viewer,
saved by an annotator, and exported back to QuPath GeoJSON.

Unit tests cover the file formats from client-shaped objects. This covers
the part only a browser can: the deep-zoom viewer re-serializes every shape
it restores (fabric draws in slide pixels and OpenSeadragon drives the
transform), so a coordinate error anywhere on that path shows up as exported
geometry that no longer matches the file it was imported from. Everything is
read from what the server wrote to disk.
"""

import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("playwright.sync_api")
pytest.importorskip("PIL")

from tests.playwright.test_base import BasePlaywrightTest  # noqa: E402

SCHEMA = "regions"
W, H = 1600, 1200

TRIANGLE = [[160.5, 120.25], [900, 300], [500.75, 1000.5]]
FEATURES = [
    {"type": "Feature", "id": "t1",
     "geometry": {"type": "Polygon", "coordinates": [TRIANGLE + [TRIANGLE[0]]]},
     "properties": {"objectType": "annotation",
                    "classification": {"name": "Tumor", "color": [200, 0, 0]}}},
    {"type": "Feature", "id": "s1",
     "geometry": {"type": "Polygon", "coordinates": [[[1000, 200], [1400, 200], [1400, 500],
                                                       [1000, 500], [1000, 200]]]},
     "properties": {"objectType": "annotation",
                    "classification": {"name": "Stroma", "color": [0, 150, 0]}}},
    {"type": "Feature", "id": "p1",
     "geometry": {"type": "Point", "coordinates": [1300, 1000]},
     "properties": {"objectType": "annotation",
                    "classification": {"name": "Tumor", "color": [200, 0, 0]}}},
]


def _flat(coords):
    if isinstance(coords, (int, float)):
        return [coords]
    return [v for c in coords for v in _flat(c)]


@pytest.fixture(scope="module")
def project():
    from PIL import Image, ImageDraw

    from potato.importers import projects
    from potato.importers.projects.writer import write_project
    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.port_manager import find_free_port
    from tests.helpers.test_utils import create_test_directory

    root = Path(create_test_directory("playwright_pathology"))
    for child in root.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    source = root / "source"
    source.mkdir()
    for name, fill in (("case1", "#e8aac8"), ("case2", "#c8aae8")):
        image = Image.new("RGB", (W, H), "white")
        ImageDraw.Draw(image).ellipse([100, 100, W - 100, H - 100], fill=fill)
        image.save(source / f"{name}.png")
        (source / f"{name}.geojson").write_text(json.dumps(
            {"type": "FeatureCollection", "features": FEATURES}))

    result = projects.IMPORTERS["qupath_geojson"].parse_path(source, {})
    out = root / "project"
    write_project(result, str(out), source=str(source), extra_config=result.extra_config)
    config_path = out / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    # The generated project is relative to its own folder; the test server
    # runs from the repository root.
    config["task_dir"] = str(out)
    config["output_annotation_dir"] = str(out / "annotation_output")
    config["data_files"] = [str(out / f) for f in config["data_files"]]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))

    server = FlaskTestServer(port=find_free_port(), debug=False, config_file=str(config_path))
    if not server.start():
        pytest.fail("Failed to start the pathology server")
    yield server, config_path
    server.stop()


@pytest.mark.playwright
class TestImportedRegions(BasePlaywrightTest):

    def _ready(self, page, n, timeout=30_000):
        page.wait_for_function(
            """([schema, n]) => {
                const c = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`);
                const m = c && c.annotationManager;
                return !!(m && m.deepZoom && m.deepZoom.contentSize && m.image
                          && m.getAnnotationCount() >= n);
            }""", arg=[SCHEMA, n], timeout=timeout)
        page.wait_for_timeout(800)

    def test_regions_show_save_and_export_back_to_the_same_geometry(self, page, project):
        server, config_path = project
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        user = self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self._ready(page, 3)
        assert self.count_annotations(page, SCHEMA) == 3

        # The restored shapes sit on the slide where the file put them: the
        # triangle's first vertex, read back through OpenSeadragon's own
        # image-to-screen mapping, lands on fabric's rendering of that vertex.
        placed = page.evaluate(
            """(schema) => {
                const m = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`).annotationManager;
                const item = m.deepZoom.viewer.world.getItemAt(0);
                const p = item.imageToViewerElementCoordinates(new OpenSeadragon.Point(160.5, 120.25));
                const v = m.canvas.viewportTransform;
                return {osd: [p.x, p.y], fabric: [160.5 * v[0] + v[4], 120.25 * v[3] + v[5]]};
            }""", arg=SCHEMA)
        assert placed["fabric"][0] == pytest.approx(placed["osd"][0], abs=1.0)
        assert placed["fabric"][1] == pytest.approx(placed["osd"][1], abs=1.0)

        # Navigate away and back: the regions come back from the server, not
        # from the pre-annotation.
        self.click_next(page)
        self._ready(page, 3)
        self.click_prev(page)
        self._ready(page, 3)
        assert self.count_annotations(page, SCHEMA) == 3

        from potato.export.cli import build_export_context
        from potato.export.registry import export_registry
        context = build_export_context(str(config_path))
        mine = [a for a in context.annotations if a.get("user_id") == user]
        assert {a["instance_id"] for a in mine} >= {"case1"}
        out = Path(config_path).parent / "export"
        shutil.rmtree(out, ignore_errors=True)
        result = export_registry.export("qupath_geojson", context, str(out))
        assert result.success
        path = out / user / "case1.geojson"
        assert str(path) in result.files_written
        back = json.loads(path.read_text())["features"]
        assert [f["geometry"]["type"] for f in back] == ["Polygon", "Polygon", "Point"]
        assert [f["properties"]["classification"]["name"] for f in back] == [
            "Tumor", "Stroma", "Tumor"]
        for got, want in zip(back, FEATURES):
            # Within half a pixel of the source, at level 0.
            assert _flat(got["geometry"]["coordinates"]) == pytest.approx(
                _flat(want["geometry"]["coordinates"]), abs=0.5), want["id"]
        assert not [e for e in errors if "favicon" not in e], errors

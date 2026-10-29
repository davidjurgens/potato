"""
volume_annotation in a real browser: three views over a DICOM series and a
NIfTI file, painted with the mouse, saved and restored across navigation.

The masks a test checks are read back from the server (/get_annotations)
as well as from the page, so a value that only lived in the browser fails.
"""

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("pydicom")
pytest.importorskip("nibabel")

from tests.playwright.test_base import BasePlaywrightTest  # noqa: E402

GENERATOR = Path("examples/image/ct-volume/generate_volume.py")
MANAGER = "document.querySelector('.volume-annotation-container').annotationManager"


@pytest.fixture(scope="module")
def volume_server():
    import yaml
    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.port_manager import find_free_port
    from tests.helpers.test_utils import create_test_directory

    test_dir = Path(create_test_directory("playwright_volume"))
    spec = importlib.util.spec_from_file_location("generate_volume", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.HERE = test_dir
    gen.main()
    items = [{"id": "dicom", "volume": "phantom_dicom", "rtstruct": "phantom_rtstruct.dcm",
              "text": "DICOM series"},
             {"id": "nifti", "volume": "phantom.nii.gz", "text": "NIfTI"}]
    (test_dir / "items.json").write_text(json.dumps(items))
    config = {
        "port": 0, "annotation_task_name": "Volumes", "task_dir": str(test_dir),
        "media_directory": str(test_dir / "media"),
        "output_annotation_dir": str(test_dir / "out"),
        "data_files": [str(test_dir / "items.json")],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True},
        "annotation_schemes": [{
            "annotation_type": "volume_annotation", "name": "ct", "description": "Segment",
            "labels": [{"name": "Lesion", "key_value": "1"}, {"name": "Bone", "key_value": "2"}],
            "source_field": "volume", "prefill_rtstruct_field": "rtstruct",
            "display_tags": ["Modality", "PatientName"],
        }],
    }
    path = test_dir / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    srv = FlaskTestServer(port=find_free_port(), debug=False, config_file=str(path))
    if not srv.start():
        raise RuntimeError("volume server did not start")
    yield srv
    srv.stop()


def _ready(page):
    page.wait_for_function(f"(() => {{ const m = {MANAGER}; return m && m.info; }})()",
                           timeout=30_000)
    page.wait_for_timeout(500)


def _stroke(page, axis, y=0.5):
    box = page.locator(f".vol-view[data-axis='{axis}'] .vol-overlay").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.4, box["y"] + box["height"] * y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + box["height"] * y, steps=10)
    page.mouse.up()


def _slices(page, label):
    return page.evaluate(
        f"(() => {{ const m = {MANAGER}.masks['{label}']; "
        f"return m ? [...m.keys()].sort((a, b) => a - b) : []; }})()")


@pytest.mark.playwright
class TestVolumeAnnotation(BasePlaywrightTest):

    def test_the_rtstruct_starts_the_mask_without_answering_the_item(self, page, volume_server):
        self.register_and_login(page, volume_server)
        _ready(page)
        assert _slices(page, "Lesion") == list(range(21, 28))
        # Only the allowed tags reach the page; PatientName is in the header.
        tags = page.locator(".vol-tags").inner_text()
        assert "CT" in tags and "Phantom" not in tags
        # Past the autosave delay: an announced prefill would have been saved.
        self.wait_for_debounce(page, 2500)
        stored = page.evaluate(
            "fetch('/get_annotations?instance_id=dicom').then(r => r.json())")
        assert "ct" not in (stored.get("label_annotations") or {}), \
            "opening the item saved an answer"

    def test_painting_saves_and_survives_navigation(self, page, volume_server):
        self.register_and_login(page, volume_server)
        _ready(page)
        self.click_next(page)
        _ready(page)
        page.locator(".vol-label-btn[data-label='Bone']").click()
        page.locator("[data-tool='brush']").click()
        _stroke(page, "axial")
        start = page.evaluate(f"{MANAGER}.cursor.k")
        page.locator(".vol-view[data-axis='axial'] .vol-stage").focus()
        for _ in range(4):
            page.keyboard.press("ArrowUp")
        _stroke(page, "axial")
        assert _slices(page, "Bone") == [start, start + 4]

        page.locator("[data-action='interpolate']").click()
        page.wait_for_function(f"{MANAGER}.masks.Bone.size === 5", timeout=10_000)
        self.wait_for_debounce(page)
        stored = page.evaluate("fetch('/get_annotations?instance_id=nifti').then(r => r.json())")
        saved = json.loads(stored["label_values"]["ct"]["_data"])
        assert sorted(int(k) for k in saved["masks"]["Bone"]) == list(range(start, start + 5))

        self.click_prev(page)
        _ready(page)
        self.click_next(page)
        _ready(page)
        assert _slices(page, "Bone") == list(range(start, start + 5))

    def test_the_window_preset_changes_the_picture(self, page, volume_server):
        self.register_and_login(page, volume_server)
        _ready(page)
        before = page.evaluate(f"{MANAGER}.views.axial.img.src")
        select = page.locator(".vol-window-select")
        options = select.locator("option").all_inner_texts()
        lung = next(n for n, text in enumerate(options) if text.startswith("Lung"))
        select.select_option(str(lung))
        page.wait_for_function(
            f"{MANAGER}.views.axial.img.src !== {json.dumps(before)}", timeout=10_000)
        assert "wc=-600.0" in page.evaluate(f"{MANAGER}.views.axial.img.src")


@pytest.mark.playwright
class TestVolumePolygonFillsTheMask(BasePlaywrightTest):
    """A closed polygon was saved as a shape only, so it reached neither the
    NIfTI nor the DICOM SEG mask nor Dice."""

    def test_a_closed_polygon_paints_its_slice(self, page, volume_server):
        self.register_and_login(page, volume_server)
        _ready(page)
        self.click_next(page)
        _ready(page)
        page.locator(".vol-label-btn[data-label='Bone']").click()
        page.locator("[data-tool='polygon']").click()
        box = page.locator(".vol-view[data-axis='axial'] .vol-overlay").bounding_box()
        for fx, fy in ((0.3, 0.3), (0.6, 0.3), (0.6, 0.6), (0.3, 0.6)):
            page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
        page.keyboard.press("Enter")
        k = page.evaluate(f"{MANAGER}.cursor.k")
        assert _slices(page, "Bone") == [k]
        filled = page.evaluate(
            f"(() => {{ const p = {MANAGER}.masks.Bone.get({k}); "
            f"return p.reduce((n, v) => n + v, 0); }})()")
        assert filled > 0
        assert page.evaluate(f"{MANAGER}.shapes.filter(s => s.type === 'polygon').length") == 0
        self.wait_for_debounce(page)
        stored = page.evaluate("fetch('/get_annotations?instance_id=nifti').then(r => r.json())")
        saved = json.loads(stored["label_values"]["ct"]["_data"])
        assert [int(key) for key in saved["masks"]["Bone"]] == [k]

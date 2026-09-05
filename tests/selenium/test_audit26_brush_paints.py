"""
Does the brush tool actually paint?

The auditor could not answer this and said so rather than filing it. Two
hypotheses fit their evidence equally well: the Brush button renders selected
but never puts the canvas into a state where strokes land, or fabric ignores
the synthetic events their harness dispatches. Selenium's ActionChains produce
trusted events, which separates the two.

What the source says, for orientation: `brush` does NOT use fabric's
`isDrawingMode` -- that belongs to the `freeform` tool. Brush shows a separate
`.mask-canvas` and sets its `pointerEvents` to `auto`, so a stroke lands there
and never reaches `upper-canvas` at all. `elementFromPoint` returning
`upper-canvas` while brush is selected is therefore itself a signal.

Nothing in the suite asserted this before. `tests/selenium/test_mask_zoom_sync.py`
carries both a `_do_brush_stroke` helper and a `_has_mask_data` helper and calls
neither, so every mask test there checks position and none checks paint.

The image is a local data URI so the test does not depend on the network. That
matters more than usual here: `_resizeMaskCanvas` returns early when
`this.image` is unset, which leaves the mask canvas at zero size -- so a slow or
blocked image fetch produces exactly the symptom under investigation.
"""

import base64
import io
import json
import os
import time
import unittest

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)


def _write_solid_png(directory, name="canvas.png",
                     width=400, height=300, color=(30, 90, 160)):
    """A real file under the study's media directory.

    A `data:` URI does not work here: image-URL discovery does not recognize
    one, and the page logs "No image URL found!" -- which leaves the mask
    canvas at its 300x150 default and reproduces the very symptom under
    investigation for an unrelated reason.
    """
    from PIL import Image
    media = os.path.join(directory, "media")
    os.makedirs(media, exist_ok=True)
    Image.new("RGB", (width, height), color).save(os.path.join(media, name))
    return "/media/" + name


class TestBrushPaints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        schemes = [{
            "annotation_type": "image_annotation",
            "name": "lesion",
            "description": "Paint the affected region",
            "source_field": "image",
            "tools": ["brush", "eraser"],
            "labels": [{"name": "affected", "color": "#FF6B6B", "key_value": "1"}],
            "brush_size": 20,
        }]
        port = find_free_port(preferred_port=9884)
        cls.test_dir = create_test_directory("audit26_brush_paints")
        image_ref = _write_solid_png(cls.test_dir)
        # Four items, not one. Painting saves the item, and a saved single
        # item completes the study -- so the second test in the class navigates
        # to a "Thank You" page and waits out its timeout looking for a canvas.
        # Each test passed alone and two of three failed together, which is the
        # signature of a fixture the earlier test consumed.
        cls.data_file = create_test_data_file(
            cls.test_dir,
            [{"id": f"img_{n}", "image": image_ref} for n in range(1, 5)])
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[cls.data_file], port=port,
            item_properties={"id_key": "id", "text_key": "image"},
            user_config={"allow_all_users": True, "users": []},
            additional_config={"media_directory": "media"},
        )
        cls.server = FlaskTestServer(port=port, debug=False,
                                     config_file=cls.config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        options = ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1400,1100")
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)

        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("brushprobe")
        try:
            cls.driver.find_element(By.NAME, "pass").send_keys("pw")
        except Exception:
            pass
        cls.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            cls.driver.quit()
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def _open_and_select_brush(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".mask-canvas")))
        # The manager loads the image asynchronously, and a mask canvas sized
        # before the image arrives is zero by zero.
        WebDriverWait(self.driver, 15).until(lambda d: d.execute_script(
            "const c = document.querySelector('.image-annotation-container');"
            "return !!(c && c.annotationManager && c.annotationManager.image);"))
        self.driver.find_element(
            By.CSS_SELECTOR, '[data-tool="brush"]').click()
        self.driver.find_element(By.CSS_SELECTOR, ".label-btn").click()
        time.sleep(0.3)

    def _mask_count(self):
        return self.driver.execute_script(
            "const c = document.querySelector('.image-annotation-container');"
            "if (!c || !c.annotationManager) return -1;"
            "return Object.keys(c.annotationManager.masks || {}).length;")

    def _painted_pixels(self):
        """Non-transparent pixels on the mask canvas.

        The mask count is bookkeeping; this is whether anything was drawn.
        """
        return self.driver.execute_script("""
            const c = document.querySelector('.mask-canvas');
            if (!c || !c.width || !c.height) return -1;
            const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            let n = 0;
            for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
            return n;
        """)

    def test_the_mask_canvas_is_on_top_and_interactive_under_brush(self):
        """Where a stroke is supposed to land.

        Brush does not use fabric's drawing mode: it routes the stroke to the
        mask canvas by making that canvas the topmost interactive element. If
        `elementFromPoint` returns the fabric upper-canvas here, the stroke
        cannot reach the code that paints, whatever else is true.
        """
        self._open_and_select_brush()
        mask = self.driver.find_element(By.CSS_SELECTOR, ".mask-canvas")
        assert mask.is_displayed(), "the mask canvas is hidden under brush"
        rect = self.driver.execute_script(
            "const r = arguments[0].getBoundingClientRect();"
            "return [r.width, r.height];", mask)
        assert rect[0] > 0 and rect[1] > 0, f"mask canvas has a zero rect: {rect}"
        assert self.driver.execute_script(
            "return getComputedStyle(arguments[0]).pointerEvents;", mask) == "auto"

        topmost = self.driver.execute_script("""
            const r = arguments[0].getBoundingClientRect();
            const el = document.elementFromPoint(r.left + r.width / 2,
                                                 r.top + r.height / 2);
            return el ? el.className : null;
        """, mask)
        assert "mask-canvas" in (topmost or ""), (
            f"the topmost element mid-canvas is {topmost!r}, so a stroke never "
            "reaches the mask canvas")

    def test_a_trusted_drag_paints(self):
        """The question the auditor could not settle.

        ActionChains produces trusted events. If this paints, their synthetic
        stream was the problem; if it does not, the brush is broken and no
        harness could have driven it.
        """
        self._open_and_select_brush()
        assert self._painted_pixels() == 0, "the canvas was not blank to start"

        mask = self.driver.find_element(By.CSS_SELECTOR, ".mask-canvas")
        actions = ActionChains(self.driver)
        actions.move_to_element_with_offset(mask, 60, 60)
        actions.click_and_hold()
        for _ in range(6):
            actions.move_by_offset(20, 10)
        actions.release()
        actions.perform()
        time.sleep(0.5)

        painted = self._painted_pixels()
        assert painted > 0, (
            "a trusted click-drag across the mask canvas painted nothing "
            f"(painted pixels: {painted}, masks: {self._mask_count()})")

    def test_the_stroke_is_recorded_as_a_mask(self):
        """Painted pixels are not a stored annotation.

        The canvas can show a stroke that no export would ever carry, which is
        the half the auditor cared about: they have never seen a mask stored.
        """
        self._open_and_select_brush()
        mask = self.driver.find_element(By.CSS_SELECTOR, ".mask-canvas")
        actions = ActionChains(self.driver)
        actions.move_to_element_with_offset(mask, 60, 60)
        actions.click_and_hold()
        for _ in range(6):
            actions.move_by_offset(20, 10)
        actions.release()
        actions.perform()
        time.sleep(0.5)

        assert self._mask_count() > 0, (
            f"the stroke painted but no mask was recorded "
            f"(painted pixels: {self._painted_pixels()})")

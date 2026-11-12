"""
The annotation canvas was taller than the box that shows it.

Audit 27. `_initCanvas` reads the canvas width from its container and then
hardcodes `const height = 600`, while `.canvas-wrapper` is `height: 500px`
with `overflow: hidden`. So the canvas is about 104px taller than the visible
box on EVERY image_annotation study, whatever the image, and the bottom of it
is clipped with no scrollbar -- the wrapper hides overflow rather than
scrolling it. The auditor lost two of four polygon clicks in that band.

`Fit`, the one control whose job is to reconcile image size with visible size,
could not help. `zoomFit` computed its scale against the fabric canvas's own
dimensions, and `_fitImageToCanvas` has already scaled the image to fit that
canvas -- so one of the two ratios is exactly 1 and the `Math.min(..., 1)`
clamp pins the result at 1. It was arithmetically guaranteed to return 1 for
every image at every zoom level, which made it an exact duplicate of `100%`.
No picture would have made it work.

Nothing in the suite could see either one. Every image test runs at whatever
size the driver picks and asserts on DOM state; none of them ever compares the
canvas against the box it is displayed in. The viewport is a fixture dimension
like any other.
"""

import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
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


class TestCanvasFitsItsViewport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        schemes = [{
            "annotation_type": "image_annotation",
            "name": "vis",
            "description": "Annotate the image",
            "source_field": "image",
            "tools": ["bbox", "polygon", "brush"],
            "labels": [{"name": "thing", "color": "#FF6B6B", "key_value": "1"}],
        }]
        port = find_free_port(preferred_port=9889)
        cls.test_dir = create_test_directory("audit27_canvas_viewport")
        media = os.path.join(cls.test_dir, "media")
        os.makedirs(media, exist_ok=True)
        from PIL import Image
        # 4:3 at a size an author would actually use. Nothing exotic: the
        # clipping is a property of the wrapper, not of this image.
        Image.new("RGB", (800, 600), (40, 70, 110)).save(
            os.path.join(media, "big.png"))
        cls.data_file = create_test_data_file(
            cls.test_dir,
            [{"id": f"i{n}", "image": "/media/big.png"} for n in (1, 2, 3)])
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
        options.add_argument("--window-size=1400,900")
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)
        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("viewportprobe")
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

    def _open(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 15).until(lambda d: d.execute_script(
            "const c = document.querySelector('.image-annotation-container');"
            "return !!(c && c.annotationManager && c.annotationManager.image);"))
        time.sleep(0.6)

    def _measure(self):
        return self.driver.execute_script("""
            const c = document.querySelector('.image-annotation-container');
            const m = c.annotationManager;
            const w = document.querySelector('.canvas-wrapper');
            return {
                zoom: m.canvas.getZoom(),
                canvasH: m.canvas.getHeight(),
                canvasW: m.canvas.getWidth(),
                wrapperH: w.clientHeight,
                wrapperW: w.clientWidth,
                // The ON-SCREEN bottom edge. The object's own coordinates
                // ignore the viewport transform, so reading them would report
                // the same number before and after a zoom -- a measurement
                // that cannot see the thing under test.
                imageBottom: m.canvas.getZoom()
                    * (m.image.top + m.image.height * m.image.scaleY)
                    + m.canvas.viewportTransform[5],
            };
        """)

    def test_the_canvas_is_not_taller_than_the_box_that_shows_it(self):
        """The clipping, measured directly.

        `overflow: hidden` on the wrapper means the excess is not scrollable
        either, so anything below the fold is unreachable and unmarked.
        """
        self._open()
        state = self._measure()
        assert state["canvasH"] <= state["wrapperH"] + 1, (
            f"the canvas is {state['canvasH']}px tall inside a "
            f"{state['wrapperH']}px box that hides its overflow: "
            f"{state['canvasH'] - state['wrapperH']}px of every image is "
            f"clipped. {state}")

    def test_the_whole_image_is_inside_the_visible_box_on_arrival(self):
        """What the annotator can actually see before touching anything."""
        self._open()
        state = self._measure()
        assert state["imageBottom"] <= state["wrapperH"] + 1, (
            f"the image runs to {state['imageBottom']}px inside a "
            f"{state['wrapperH']}px box: {state}")

    def test_fit_differs_from_100_percent_when_there_is_something_to_fit(self):
        """The auditor's finding.

        Zoom in first, so both controls have somewhere to return from, then
        compare them against each other rather than against a constant: what
        makes `Fit` wrong is that it cannot differ from `100%`, whatever the
        right answer happens to be.
        """
        self._open()
        for _ in range(2):
            self.driver.find_element(
                By.CSS_SELECTOR, '[data-action="zoom-in"]').click()
            time.sleep(0.2)
        zoomed = self._measure()["zoom"]
        assert zoomed > 1.2, zoomed

        self.driver.find_element(
            By.CSS_SELECTOR, '[data-action="zoom-fit"]').click()
        time.sleep(0.3)
        fitted = self._measure()

        assert fitted["zoom"] < zoomed, (
            f"Fit did not change the zoom at all: {fitted}")
        assert fitted["imageBottom"] <= fitted["wrapperH"] + 1, (
            f"after Fit the image still runs past the visible box: {fitted}")

    def test_fit_uses_the_visible_box_not_the_canvas(self):
        """The reason `Fit` could never work, pinned directly.

        CSS can constrain the wrapper below the canvas at any time --
        `max-height: calc(100vh - 200px)` does exactly that on a short window
        -- so fitting to the canvas is wrong even once the canvas is sized
        correctly. Shrinking the wrapper by hand is the cheapest way to
        create that state.
        """
        self._open()
        # Above the wrapper's own `min-height: 400px`, which would otherwise
        # win and leave the box larger than the value set here.
        self.driver.execute_script(
            "const w = document.querySelector('.canvas-wrapper');"
            "w.style.height = '420px'; w.style.minHeight = '420px';")
        time.sleep(0.3)
        self.driver.find_element(
            By.CSS_SELECTOR, '[data-action="zoom-fit"]').click()
        time.sleep(0.3)
        state = self._measure()
        assert state["imageBottom"] <= state["wrapperH"] + 1, (
            f"Fit ignored the visible box and left the image running to "
            f"{state['imageBottom']}px inside {state['wrapperH']}px: {state}")

"""
Regression test for F-040: drawn document bounding boxes must persist.

document-bbox.js now writes boxes to a hidden input.annotation-data-input
(rendered by document_display.py) so the standard save pipeline collects them
as "{field}:::_data", the server stores them, and render_page_with_annotations
restores them. This test draws a box, navigates away and back, and asserts the
box survives (both the widget's box count and the server-side annotation).
"""

import os
import time
import unittest

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
BBOX_CONFIG = os.path.join(_REPO, "examples/image/document-bbox/config.yaml")


class TestDocumentBboxPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = find_free_port()
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=BBOX_CONFIG)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)
        cls.opts = ChromeOptions()
        for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-gpu", "--window-size=1920,1080"):
            cls.opts.add_argument(a)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.opts)
        self.user = f"bbox_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        d = self.driver
        d.get(f"{self.server.base_url}/")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.ID, "login-email")))
        d.find_element(By.ID, "login-email").send_keys(self.user)
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))

    def _draw_box(self):
        return self.driver.execute_script("""
            var c = document.querySelector('.document-display.document-bbox-mode');
            var canvas = document.querySelector('.document-bbox-canvas');
            if (!c || !canvas || !window.DocumentBoundingBox) return -1;
            window.DocumentBoundingBox.setMode(c, 'draw');
            var r = canvas.getBoundingClientRect();
            function ev(t, x, y) {
                canvas.dispatchEvent(new MouseEvent(t, {
                    bubbles: true, clientX: r.left + x, clientY: r.top + y}));
            }
            ev('mousedown', 20, 20);
            ev('mousemove', 90, 60);
            ev('mousemove', 150, 110);
            ev('mouseup', 150, 110);
            return window.DocumentBoundingBox.getAllBoxes(c).length;
        """)

    def _box_count(self):
        return self.driver.execute_script("""
            var c = document.querySelector('.document-display.document-bbox-mode');
            if (!c || !window.DocumentBoundingBox) return -1;
            try { return window.DocumentBoundingBox.getAllBoxes(c).length; }
            catch (e) { return -2; }
        """)

    def _hidden_input_value(self):
        return self.driver.execute_script(
            "var i=document.querySelector('.document-bbox-mode .annotation-data-input');"
            "return i ? i.value : null;")

    def test_drawn_box_persists_across_navigation(self):
        d = self.driver
        self._login()
        WebDriverWait(d, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".document-bbox-canvas")))
        instance_id = d.execute_script(
            "return window.currentInstance ? window.currentInstance.id : null;")
        time.sleep(1.0)

        drawn = self._draw_box()
        self.assertGreaterEqual(drawn, 1, f"failed to draw a box (count={drawn})")

        # The hidden input must now carry the box JSON (the persistence channel).
        val = self._hidden_input_value()
        self.assertTrue(val and "bbox" in val,
                        f"hidden annotation-data-input should hold the box, got {val!r}")

        # Navigate away (saves) and back (restores).
        time.sleep(1.5)
        d.execute_script("document.getElementById('next-btn').click();")
        time.sleep(1.0)
        d.execute_script("document.getElementById('prev-btn').click();")
        WebDriverWait(d, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".document-bbox-canvas")))
        time.sleep(1.5)

        self.assertGreaterEqual(
            self._box_count(), 1,
            "drawn bounding box must survive Next->Previous (F-040)")

        # And it must be stored server-side.
        if instance_id:
            cookies = {c["name"]: c["value"] for c in d.get_cookies()}
            ga = requests.get(
                f"{self.server.base_url}/get_annotations?instance_id={instance_id}",
                cookies=cookies).json()
            self.assertIn("document_content", ga.get("label_annotations", {}),
                          f"box must be stored server-side, got {ga}")


if __name__ == "__main__":
    unittest.main()

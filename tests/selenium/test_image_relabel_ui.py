"""
Relabeling an image box from the label buttons, in a browser.

A label button used to set only the label of the next box drawn, so a
detector's box with the wrong class could not be corrected without deleting it
and drawing it again. With a box selected, the button now relabels it. A box
that was just drawn is active too, but the annotator did not select it, and
picking the label for the next box must not relabel it.

Trusted mouse events throughout; persistence is checked by Next and Previous
and against /get_annotations.
"""

import json
import os
import shutil
import time
import unittest

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)

IMAGE = os.path.join(os.path.dirname(__file__), "..", "data", "test_image_400x300.png")
AI_BOX = {"type": "bbox", "label": "car", "color": "#2563eb", "source": "ai",
          "ai_model": "detector", "confidence": 0.9,
          "coordinates": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.3}}


class TestImageRelabelUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("image_relabel_ui")
        media = os.path.join(cls.test_dir, "media")
        os.makedirs(media, exist_ok=True)
        shutil.copy(IMAGE, os.path.join(media, "street.png"))
        schemes = [{
            "annotation_type": "image_annotation",
            "name": "objects",
            "description": "Box each vehicle",
            "source_field": "image",
            "tools": ["bbox"],
            "labels": [{"name": "car", "color": "#2563eb"},
                       {"name": "truck", "color": "#dc2626"}],
        }]
        port = find_free_port(preferred_port=9898)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": "img_1", "image": "/media/street.png",
             "predictions": {"objects": [AI_BOX]}},
            {"id": "img_2", "image": "/media/street.png"},
            {"id": "img_3", "image": "/media/street.png"},
        ])
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[data_file], port=port,
            item_properties={"id_key": "id", "text_key": "image"},
            user_config={"allow_all_users": True, "users": []},
            additional_config={
                "media_directory": "media",
                "pre_annotation": {"enabled": True, "field": "predictions",
                                   "allow_modification": True},
            },
        )
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        options = ChromeOptions()
        for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                     "--disable-gpu", "--window-size=1400,1400"):
            options.add_argument(flag)
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)
        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("relabeler")
        try:
            cls.driver.find_element(By.NAME, "pass").send_keys("pw")
        except Exception:
            pass
        cls.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            cls.driver.quit()
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    # ------------------------------------------------------------------ helpers
    def _wait_ready(self):
        WebDriverWait(self.driver, 15).until(lambda d: d.execute_script(
            "const c = document.querySelector('.image-annotation-container');"
            "return !!(c && c.annotationManager && c.annotationManager.image);"))
        time.sleep(0.5)

    def _instance(self):
        return self.driver.execute_script("return document.getElementById('instance_id').value")

    def _goto(self, instance_id):
        for _ in range(4):
            if self._instance() == instance_id:
                return
            self.driver.find_element(By.ID, "next-btn").click()
            time.sleep(1.5)
            self._wait_ready()
        self.assertEqual(self._instance(), instance_id)

    def _offset(self, fx, fy):
        """Offset from the upper canvas's centre of a point given as a
        fraction of the image."""
        return self.driver.execute_script("""
            const m = document.querySelector('.image-annotation-container').annotationManager;
            const img = m.image, vt = m.canvas.viewportTransform;
            const el = m.canvas.upperCanvasEl.getBoundingClientRect();
            const x = img.left + img.width * img.scaleX * arguments[0];
            const y = img.top + img.height * img.scaleY * arguments[1];
            const p = fabric.util.transformPoint({x: x, y: y}, vt);
            return [p.x - el.width / 2, p.y - el.height / 2];
        """, fx, fy)

    def _upper(self):
        return self.driver.find_element(By.CSS_SELECTOR, ".upper-canvas")

    def _click_at(self, fx, fy):
        x, y = self._offset(fx, fy)
        ActionChains(self.driver).move_to_element_with_offset(
            self._upper(), int(x), int(y)).click().perform()
        time.sleep(0.4)

    def _click_shape(self, index):
        """Click the middle of shape N, wherever the canvas put it."""
        x, y = self.driver.execute_script("""
            const m = document.querySelector('.image-annotation-container').annotationManager;
            const o = m.canvas.getObjects().filter(o => o.annotationData)[arguments[0]];
            const c = o.getCenterPoint();
            const p = fabric.util.transformPoint(c, m.canvas.viewportTransform);
            const el = m.canvas.upperCanvasEl.getBoundingClientRect();
            return [p.x - el.width / 2, p.y - el.height / 2];""", index)
        ActionChains(self.driver).move_to_element_with_offset(
            self._upper(), int(x), int(y)).click().perform()
        time.sleep(0.4)

    def _draw(self, fx, fy):
        x, y = self._offset(fx, fy)
        (ActionChains(self.driver)
            .move_to_element_with_offset(self._upper(), int(x), int(y))
            .click_and_hold().move_by_offset(30, 20).move_by_offset(40, 30)
            .release().perform())
        time.sleep(0.5)

    def _label_button(self, name):
        self.driver.find_element(
            By.CSS_SELECTOR, f".image-annotation-container .label-btn[data-label='{name}']").click()
        time.sleep(0.4)

    def _shapes(self):
        return self.driver.execute_script("""
            const m = document.querySelector('.image-annotation-container').annotationManager;
            return m.canvas.getObjects().filter(o => o.annotationData).map(o => ({
                label: o.annotationData.label, stroke: o.stroke,
                source: o.annotationData.source || 'human',
                edited: !!o.annotationData.edited}));""")

    def _stored(self, instance_id):
        stored = self.driver.execute_async_script("""
            const done = arguments[arguments.length - 1];
            fetch('/get_annotations?instance_id=' + encodeURIComponent(arguments[0]))
                .then(r => r.json()).then(done, e => done(String(e)));""", instance_id)
        raw = ((stored.get("label_values") or {}).get("objects") or {}).get("_data")
        return json.loads(raw) if raw else []

    # -------------------------------------------------------------------- tests
    def test_1_a_selected_model_box_takes_the_clicked_label(self):
        self._wait_ready()
        self._goto("img_1")
        self.assertEqual([s["label"] for s in self._shapes()], ["car"])
        self._click_at(0.25, 0.25)           # inside the detector's box
        self._label_button("truck")
        [shape] = self._shapes()
        self.assertEqual((shape["label"], shape["stroke"].lower()), ("truck", "#dc2626"))
        self.assertTrue(shape["edited"], "a relabeled model box must be marked edited")
        time.sleep(1.5)                      # autosave debounce
        self.driver.find_element(By.ID, "next-btn").click()
        time.sleep(1.5)
        self.driver.find_element(By.ID, "prev-btn").click()
        time.sleep(1.5)
        self._wait_ready()
        self.assertEqual(self._instance(), "img_1")
        [shape] = self._shapes()
        self.assertEqual((shape["label"], shape["stroke"].lower()), ("truck", "#dc2626"))
        [box] = self._stored("img_1")
        self.assertEqual((box["label"], box["source"], box["edited"]), ("truck", "ai", True))

    def test_2_choosing_the_next_label_leaves_the_box_just_drawn(self):
        self._wait_ready()
        self._goto("img_2")
        self._label_button("car")
        self._draw(0.6, 0.6)
        self.assertEqual([s["label"] for s in self._shapes()], ["car"])
        self._label_button("truck")          # for the next box, not this one
        self.assertEqual([s["label"] for s in self._shapes()], ["car"])
        # Selecting it on purpose does relabel it.
        self._click_shape(0)
        self._label_button("truck")
        self.assertEqual([s["label"] for s in self._shapes()], ["truck"])
        self.assertFalse(self._shapes()[0]["edited"], "a person's own box is not 'edited'")


    def test_3_escape_deselects_so_a_label_is_for_the_next_box(self):
        from selenium.webdriver.common.keys import Keys
        self._wait_ready()
        self._goto("img_3")
        self._label_button("car")
        self._draw(0.3, 0.3)
        self._click_shape(0)
        ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.3)
        self._label_button("truck")
        self.assertEqual([s["label"] for s in self._shapes()], ["car"])


if __name__ == "__main__":
    unittest.main()

"""
Per-object attributes, end to end in a browser.

Draws a box with trusted mouse events, sets its attributes in the panel under
the canvas with a real select and checkbox, navigates Next and Previous, and
checks both what the panel shows for the restored box and what the server
stored. Also checks that a blank required attribute stops Next with the reason
in the banner.
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
from selenium.webdriver.support.ui import Select, WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)

IMAGE = os.path.join(os.path.dirname(__file__), "..", "data", "test_image_400x300.png")


class TestObjectAttributesUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("object_attributes_ui")
        media = os.path.join(cls.test_dir, "media")
        os.makedirs(media, exist_ok=True)
        shutil.copy(IMAGE, os.path.join(media, "street.png"))
        schemes = [{
            "annotation_type": "image_annotation",
            "name": "objects",
            "description": "Box each object and set its attributes",
            "source_field": "image",
            "tools": ["bbox"],
            "labels": [{"name": "car", "color": "#2563eb"}],
            "attributes": [
                {"name": "occlusion", "type": "select",
                 "options": ["none", "partial", "heavy"], "required": True,
                 "default": "none"},
                {"name": "parked", "type": "bool"},
            ],
        }]
        port = find_free_port(preferred_port=9897)
        data_file = create_test_data_file(
            cls.test_dir,
            [{"id": f"img_{n}", "image": "/media/street.png"} for n in range(1, 5)])
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[data_file], port=port,
            item_properties={"id_key": "id", "text_key": "image"},
            user_config={"allow_all_users": True, "users": []},
            additional_config={"media_directory": "media"},
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
        cls.driver.find_element(By.NAME, "email").send_keys("attrui")
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

    def _instance(self):
        return self.driver.execute_script("return document.getElementById('instance_id').value")

    def _image_centre_offset(self, dx=0, dy=0):
        """Offset of a point on the image from the upper canvas's centre."""
        return self.driver.execute_script("""
            const m = document.querySelector('.image-annotation-container').annotationManager;
            const img = m.image, vt = m.canvas.viewportTransform;
            const el = m.canvas.upperCanvasEl.getBoundingClientRect();
            const cx = img.left + img.width * img.scaleX / 2 + arguments[0];
            const cy = img.top + img.height * img.scaleY / 2 + arguments[1];
            const p = fabric.util.transformPoint({x: cx, y: cy}, vt);
            return [p.x - el.width / 2, p.y - el.height / 2];
        """, dx, dy)

    def _draw_box(self):
        upper = self.driver.find_element(By.CSS_SELECTOR, ".upper-canvas")
        x0, y0 = self._image_centre_offset(-40, -30)
        (ActionChains(self.driver)
            .move_to_element_with_offset(upper, int(x0), int(y0))
            .click_and_hold().move_by_offset(30, 20).move_by_offset(40, 30)
            .release().perform())
        time.sleep(0.5)
        state = self.driver.execute_script("""
            const m = document.querySelector('.image-annotation-container').annotationManager;
            const a = m.canvas.getActiveObject();
            return {shapes: m.canvas.getObjects().filter(o => o.annotationData).length,
                    active: !!(a && a.annotationData), tool: m.currentTool,
                    fields: document.querySelectorAll('.attribute-field').length};""")
        self.assertEqual(state["shapes"], 1, state)

    def _select_box(self):
        upper = self.driver.find_element(By.CSS_SELECTOR, ".upper-canvas")
        x, y = self._image_centre_offset(-5, -5)
        ActionChains(self.driver).move_to_element_with_offset(upper, int(x), int(y)).click().perform()
        time.sleep(0.3)

    def _panel_select(self):
        return self.driver.find_element(By.CSS_SELECTOR, ".object-attribute-panel select")

    def _stored(self, instance_id):
        raw = self.driver.execute_async_script(
            "const done = arguments[arguments.length - 1];"
            "fetch('/get_annotations?instance_id=' + encodeURIComponent(arguments[0]))"
            ".then(r => r.json()).then(done).catch(e => done({error: String(e)}));", instance_id)
        blob = json.dumps(raw)
        start = blob.find('[{\\"type\\"')
        return json.loads(json.loads('"' + blob[start:blob.find(']"', start) + 1] + '"')) if start >= 0 else []

    def _click_next(self):
        button = self.driver.find_element(By.ID, "next-btn")
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", button)
        ActionChains(self.driver).move_to_element(button).click().perform()
        time.sleep(1)

    # -------------------------------------------------------------------- tests
    def test_1_attributes_survive_navigating_away_and_back(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait_ready()
        first = self._instance()
        self._draw_box()

        # The panel follows the new box, with the default already applied.
        select = Select(self._panel_select())
        self.assertEqual(select.first_selected_option.get_attribute("value"), "none")
        select.select_by_value("heavy")
        parked = self.driver.find_element(By.CSS_SELECTOR, ".object-attribute-panel input[type=checkbox]")
        ActionChains(self.driver).move_to_element(parked).click().perform()
        time.sleep(2)  # autosave debounce

        self._click_next()
        WebDriverWait(self.driver, 10).until(lambda d: self._instance() != first)
        self.driver.find_element(By.ID, "prev-btn").click()
        WebDriverWait(self.driver, 10).until(lambda d: self._instance() == first)
        self._wait_ready()

        # Visual state: select the restored box; the panel shows what was set.
        self._select_box()
        self.assertEqual(Select(self._panel_select()).first_selected_option.get_attribute("value"),
                         "heavy")
        self.assertTrue(self.driver.find_element(
            By.CSS_SELECTOR, ".object-attribute-panel input[type=checkbox]").is_selected())

        # Server state.
        [stored] = self._stored(first)
        self.assertEqual(stored["attributes"], {"occlusion": "heavy", "parked": True})

    def test_2_a_blank_required_attribute_stops_next_with_the_reason(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait_ready()
        # test_1 left the annotator on img_1, which already has its box; move
        # to an untouched item so this test draws the only shape.
        if self._instance() == "img_1":
            self._click_next()
            WebDriverWait(self.driver, 10).until(lambda d: self._instance() != "img_1")
            self._wait_ready()
        start = self._instance()
        self._draw_box()
        Select(self._panel_select()).select_by_value("")
        time.sleep(0.5)

        self._click_next()
        self.assertEqual(self._instance(), start)
        banner = self.driver.find_element(By.ID, "required-fields-error").text
        self.assertIn("1 object still needs required attributes", banner)

        Select(self._panel_select()).select_by_value("partial")
        time.sleep(0.5)
        self._click_next()
        WebDriverWait(self.driver, 10).until(lambda d: self._instance() != start)

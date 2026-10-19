"""
Video object tracks survive navigation, with their attributes.

Tracks drawn in tracking mode were never saved: TrackingUIManager kept them to
itself, the generator overrode a save() nothing called, and loading read a
getAnnotationData() that does not exist. This draws a track with a real drag,
sets an attribute in the panel, goes Next and Previous, and checks the track
and the attribute on the page and on the server.
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

VIDEO = os.path.join(os.path.dirname(__file__), "..", "data", "test_video_6s.webm")


class TestVideoTrackPersistence(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("video_track_persistence")
        os.makedirs(os.path.join(cls.test_dir, "media"), exist_ok=True)
        shutil.copy(VIDEO, os.path.join(cls.test_dir, "media", "clip.webm"))
        data_file = create_test_data_file(cls.test_dir, [
            {"id": "v1", "text": "/media/clip.webm"},
            {"id": "v2", "text": "/media/clip.webm"},
        ])
        port = find_free_port(preferred_port=9897)
        config_file = create_test_config(
            cls.test_dir,
            [{"annotation_type": "video_annotation", "name": "objects",
              "description": "Track the objects", "mode": "tracking",
              "labels": [{"name": "car", "color": "#FF6B6B"}],
              "attributes": [{"name": "occluded", "type": "select",
                              "options": ["none", "partial", "heavy"], "default": "none"}]}],
            data_files=[data_file], port=port, require_password=False,
            item_properties={"id_key": "id", "text_key": "text"})
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        options = ChromeOptions()
        for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                     "--disable-gpu", "--window-size=1400,1200", "--autoplay-policy=no-user-gesture-required"):
            options.add_argument(flag)
        cls.driver = webdriver.Chrome(options=options)
        cls.wait = WebDriverWait(cls.driver, 20)
        cls.driver.get(f"{cls.server.base_url}/")
        cls.wait.until(EC.presence_of_element_located((By.ID, "login-email")))
        cls.driver.find_element(By.ID, "login-email").send_keys("trackuser")
        cls.driver.find_element(By.CSS_SELECTOR, "#login-content form").submit()
        cls.wait.until(EC.presence_of_element_located((By.ID, "instance_id")))

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.server.stop_server()
        os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        cleanup_test_directory(cls.test_dir)

    def _stored_tracks(self, instance_id):
        cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
        import requests
        data = requests.get(f"{self.server.base_url}/get_annotations",
                            params={"instance_id": instance_id}, cookies=cookies).json()
        blob = (data.get("label_values", {}).get("objects") or {}).get("_data")
        return json.loads(blob).get("tracks", {}) if blob else {}

    def _center(self, element):
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.3)
        return element

    def _nav(self, button_id):
        old = self.driver.find_element(By.ID, "instance_id")
        self._center(self.driver.find_element(By.ID, button_id)).click()
        self.wait.until(EC.staleness_of(old))
        self.wait.until(EC.presence_of_element_located((By.ID, "instance_id")))

    def test_a_track_and_its_attribute_survive_next_and_previous(self):
        driver = self.driver
        start = driver.find_element(By.ID, "instance_id").get_attribute("value")
        self.wait.until(lambda d: d.execute_script(
            "var v=document.querySelector('.video-annotation-container video');"
            "return v && v.videoWidth > 0;"))
        self._center(driver.find_element(By.CSS_SELECTOR, '[data-action="create-track"]')).click()
        canvas = self._center(driver.find_element(By.CSS_SELECTOR, ".tracking-overlay"))
        ActionChains(driver).move_to_element_with_offset(canvas, -40, -40).click_and_hold() \
            .move_by_offset(80, 60).release().perform()
        self.wait.until(lambda d: len(self._stored_tracks(start)) == 1)

        select = self._center(self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".object-attribute-panel select"))))
        self.assertEqual(select.get_attribute("value"), "none")   # the default
        Select(select).select_by_value("partial")
        self.wait.until(lambda d: list(self._stored_tracks(start).values())[0]
                        .get("attributes") == {"occluded": "partial"})

        self._nav("next-btn")
        self.assertNotEqual(driver.find_element(By.ID, "instance_id").get_attribute("value"), start)
        self._nav("prev-btn")
        self.assertEqual(driver.find_element(By.ID, "instance_id").get_attribute("value"), start)

        item = self._center(self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".tracking-track-item"))))
        self.assertIn("car", item.text)
        item.click()
        restored = self.wait.until(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, ".object-attribute-panel select")))
        self.assertEqual(restored.get_attribute("value"), "partial")
        [track] = self._stored_tracks(start).values()
        keyframe = next(iter(track["keyframes"].values()))
        self.assertTrue(0 <= keyframe["bboxNorm"]["x"] <= 1, keyframe)


if __name__ == "__main__":
    unittest.main()

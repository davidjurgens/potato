"""
Drawing on a spectrogram covered by a detector's boxes, in a browser.

BirdNET boxes are full-band 3 s windows, and on a dense recording they cover
the whole spectrogram. A press on a box always started a move, so a drag meant
to draw a missed call moved a BirdNET detection instead. A detector's box that
is not selected is now drawn over; a click still selects it, and a selected
box moves as before.
"""

import os
import time
import unittest
import wave

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

#: A BirdNET-style box over every frequency and two thirds of the recording.
AI_BOX = {"start_s": 0.0, "end_s": 2.0, "low_hz": None, "high_hz": None,
          "label": "Turdus migratorius", "source": "ai", "ai_model": "BirdNET",
          "confidence": 0.9}


class TestSpectrogramDrawOverAI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("spectrogram_draw_over_ai")
        media = os.path.join(cls.test_dir, "media")
        os.makedirs(media, exist_ok=True)
        with wave.open(os.path.join(media, "dawn.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000 * 3)
        schemes = [{
            "annotation_type": "spectrogram_annotation", "name": "calls",
            "description": "Check the boxes", "source_field": "audio_url",
            "labels": [{"name": "Turdus migratorius", "color": "#2563eb"},
                       {"name": "missed call", "color": "#dc2626"}],
        }]
        port = find_free_port(preferred_port=9896)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": "rec_1", "recording": "dawn.wav", "audio_url": "/media/dawn.wav",
             "predictions": {"calls": [AI_BOX]}}])
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[data_file], port=port,
            item_properties={"id_key": "id", "text_key": "recording"},
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
                     "--disable-gpu", "--window-size=1400,1200",
                     "--autoplay-policy=no-user-gesture-required"):
            options.add_argument(flag)
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)
        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("reviewer")
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

    def _boxes(self):
        return self.driver.execute_script("""
            return [...document.querySelectorAll('.sg-box')].map(b => ({
                left: b.style.left, width: b.style.width,
                selected: b.classList.contains('sg-selected'),
                machine: b.classList.contains('sg-machine')}));""")

    def _drag(self, fx0, fy0, fx1, fy1):
        wrap = self.driver.find_element(By.CSS_SELECTOR, ".sg-wrap")
        w, h = wrap.size["width"], wrap.size["height"]
        (ActionChains(self.driver)
            .move_to_element_with_offset(wrap, int((fx0 - 0.5) * w), int((fy0 - 0.5) * h))
            .click_and_hold()
            .move_by_offset(int((fx1 - fx0) * w / 2), int((fy1 - fy0) * h / 2))
            .move_by_offset(int((fx1 - fx0) * w / 2), int((fy1 - fy0) * h / 2))
            .release().perform())
        time.sleep(0.5)

    def _click(self, fx, fy):
        wrap = self.driver.find_element(By.CSS_SELECTOR, ".sg-wrap")
        w, h = wrap.size["width"], wrap.size["height"]
        ActionChains(self.driver).move_to_element_with_offset(
            wrap, int((fx - 0.5) * w), int((fy - 0.5) * h)).click().perform()
        time.sleep(0.5)

    def test_a_drag_over_a_detection_draws_and_a_selected_one_moves(self):
        WebDriverWait(self.driver, 20).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".sg-box")) == 1)
        [ai] = self._boxes()
        self.assertTrue(ai["machine"])

        self._drag(0.2, 0.3, 0.4, 0.6)          # inside the detection
        boxes = self._boxes()
        self.assertEqual(len(boxes), 2, "the drag should have drawn a new box")
        self.assertEqual((boxes[0]["left"], boxes[0]["width"]),
                         (ai["left"], ai["width"]), "the detection moved")

        self._click(0.55, 0.8)                   # on the detection only
        self.assertTrue(self._boxes()[0]["selected"], "a click should select it")
        self._drag(0.55, 0.8, 0.65, 0.8)
        self.assertNotEqual(self._boxes()[0]["left"], ai["left"],
                            "a selected detection should move")


if __name__ == "__main__":
    unittest.main()

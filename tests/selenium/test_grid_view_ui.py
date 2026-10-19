"""
The grid page in a browser: select tiles, label them from the keyboard, save,
and find the labels on the normal annotation page.

Trusted events throughout (ActionChains), and the check after saving is the
radio button's visual state on /annotate, not a hidden value.
"""

import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)


class TestGridViewUI(unittest.TestCase):
    SCHEMES = [{"annotation_type": "radio", "name": "sentiment",
                "description": "Sentiment?", "labels": ["positive", "negative"]}]
    GRID_SCHEME = "sentiment"

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory(f"grid_view_ui_{cls.__name__}")
        items = [{"id": f"t{n}", "text": f"Headline number {n}"} for n in range(1, 9)]
        data_file = create_test_data_file(cls.test_dir, items)
        port = find_free_port(preferred_port=9896)
        cls.config_file = create_test_config(
            cls.test_dir, cls.SCHEMES, data_files=[data_file], port=port,
            additional_config={"grid_view": {"enabled": True, "scheme": cls.GRID_SCHEME,
                                             "page_size": 6}})
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        options = ChromeOptions()
        for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                     "--disable-gpu", "--window-size=1400,1000"):
            options.add_argument(flag)
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)
        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("gridui")
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
            # The in-process server may have chdir'd into the test directory;
            # deleting it from under the process breaks os.getcwd() for
            # whatever test runs next.
            os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            cleanup_test_directory(cls.test_dir)

    def _tiles(self):
        return self.driver.find_elements(By.CSS_SELECTOR, ".grid-tile")

    def _chips(self, tile):
        return [c.text for c in tile.find_elements(By.CSS_SELECTOR, ".grid-chip")]

    def test_label_from_the_keyboard_save_and_see_it_on_the_normal_page(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        self.driver.get(f"{self.server.base_url}/annotate/grid")
        WebDriverWait(self.driver, 10).until(lambda d: len(self._tiles()) == 6)
        tiles = self._tiles()
        first_id = tiles[0].get_attribute("data-instance-id")

        # Click the first, Shift-click the third: a range of three.
        actions = ActionChains(self.driver)
        actions.click(tiles[0]).key_down(Keys.SHIFT).click(tiles[2]).key_up(Keys.SHIFT).perform()
        self.assertEqual(
            [t.get_attribute("aria-selected") for t in self._tiles()][:4],
            ["true", "true", "true", "false"])
        ActionChains(self.driver).send_keys("1").perform()
        self.assertEqual([self._chips(t) for t in self._tiles()[:3]], [["positive"]] * 3)

        # Arrow to the fourth, Space to select only it after a plain click, 2.
        ActionChains(self.driver).click(self._tiles()[3]).send_keys("2").perform()
        self.assertEqual(self._chips(self._tiles()[3]), ["negative"])

        self.driver.find_element(By.ID, "grid-save").click()
        # The page reloads with the next batch: the four saved items are gone.
        # Tiles read mid-reload go stale; keep polling rather than failing.
        WebDriverWait(self.driver, 10, ignored_exceptions=(StaleElementReferenceException,)).until(
            lambda d: first_id not in [t.get_attribute("data-instance-id") for t in self._tiles()])
        self.assertIn("4 annotated", self.driver.find_element(By.CSS_SELECTOR, ".grid-progress").text)

        # The normal page shows the grid's answer as its own.
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance_id")))
        self.assertEqual(self.driver.find_element(By.ID, "instance_id").get_attribute("value"),
                         first_id)
        checked = [r.get_attribute("value") for r in
                   self.driver.find_elements(By.CSS_SELECTOR, "input[name='sentiment']")
                   if r.is_selected()]
        self.assertEqual(checked, ["positive"])


class TestTriageGridUI(TestGridViewUI):
    """A triage scheme in the grid: its own labels and keys, and the normal
    triage page shows a grid decision as selected."""
    SCHEMES = [{"annotation_type": "triage", "name": "keep", "description": "Keep it?"}]
    GRID_SCHEME = "keep"
    test_label_from_the_keyboard_save_and_see_it_on_the_normal_page = None

    def test_triage_decisions_from_the_grid_show_on_the_normal_page(self):
        self.driver.get(f"{self.server.base_url}/annotate/grid")
        WebDriverWait(self.driver, 10).until(lambda d: len(self._tiles()) == 6)
        tiles = self._tiles()
        first_id = tiles[0].get_attribute("data-instance-id")
        ActionChains(self.driver).click(tiles[0]).send_keys("1").perform()   # Keep
        ActionChains(self.driver).click(self._tiles()[1]).send_keys("2").perform()  # Discard
        self.assertEqual([self._chips(t) for t in self._tiles()[:2]], [["Keep"], ["Discard"]])

        self.driver.find_element(By.ID, "grid-save").click()
        WebDriverWait(self.driver, 10, ignored_exceptions=(StaleElementReferenceException,)).until(
            lambda d: first_id not in [t.get_attribute("data-instance-id") for t in self._tiles()])

        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "instance_id")))
        self.assertEqual(self.driver.find_element(By.ID, "instance_id").get_attribute("value"),
                         first_id)
        keep = self.driver.find_element(By.CSS_SELECTOR, ".triage-btn.triage-accept")
        WebDriverWait(self.driver, 10).until(lambda d: "selected" in keep.get_attribute("class"))
        self.assertNotIn("selected", self.driver.find_element(
            By.CSS_SELECTOR, ".triage-btn.triage-reject").get_attribute("class"))

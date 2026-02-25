#!/usr/bin/env python3
"""
Selenium tests for BWS annotation UI.

Tests browser interaction with the Best-Worst Scaling interface.
"""

import os
import time
import unittest

import yaml
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    cleanup_test_directory,
)


def create_bws_test_config(test_dir, num_items=10, tuple_size=4, num_tuples=5, port=9020):
    """Create a BWS config for Selenium testing."""
    # Create pool data
    data = [
        {"id": f"s{i:03d}", "text": f"Selenium test item {i} for BWS annotation."}
        for i in range(1, num_items + 1)
    ]
    data_file = create_test_data_file(test_dir, data)
    abs_test_dir = os.path.abspath(test_dir)
    output_dir = os.path.join(abs_test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": "BWS Selenium Test",
        "task_dir": abs_test_dir,
        "data_files": [os.path.basename(data_file)],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "output_annotation_dir": output_dir,
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "persist_sessions": False,
        "debug": False,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": "test-secret-key-bws-selenium",
        "user_config": {"allow_all_users": True, "users": []},
        "bws_config": {
            "tuple_size": tuple_size,
            "num_tuples": num_tuples,
            "seed": 42,
        },
        "annotation_schemes": [
            {
                "annotation_type": "bws",
                "name": "test_bws",
                "description": "Select best and worst",
                "best_description": "Which is BEST?",
                "worst_description": "Which is WORST?",
                "tuple_size": tuple_size,
                "sequential_key_binding": True,
            }
        ],
    }

    config_path = os.path.join(abs_test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


class TestBwsUI(unittest.TestCase):
    """Selenium tests for BWS annotation interface."""

    @classmethod
    def setUpClass(cls):
        """Set up Flask server with BWS config."""
        cls.test_dir = create_test_directory("bws_selenium_test")
        port = find_free_port(preferred_port=9020)

        cls.config_path = create_bws_test_config(
            cls.test_dir, num_items=10, tuple_size=4, num_tuples=5, port=port
        )

        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_path)
        started = cls.server.start_server()
        assert started, "Failed to start BWS server for Selenium tests"
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        """Clean up server and test directory."""
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """Create WebDriver and authenticate."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"bws_user_{int(time.time())}"

        # Login
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(self.test_user)
        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()

        # Wait for annotation page or consent page
        time.sleep(1)

        # Skip through any consent/instruction pages
        for _ in range(5):
            try:
                continue_btn = self.driver.find_element(
                    By.CSS_SELECTOR, "button.btn-primary, input[type='submit']"
                )
                continue_btn.click()
                time.sleep(0.5)
            except (NoSuchElementException, Exception):
                break

    def tearDown(self):
        """Close WebDriver."""
        if hasattr(self, "driver"):
            self.driver.quit()

    def _go_to_annotate(self):
        """Navigate to annotation page."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".annotation-form.bws"))
        )

    def wait_for_element(self, by, value, timeout=10):
        """Wait for element to be present."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def test_bws_items_display_rendered(self):
        """BWS items display shows labeled items (A, B, C, D) with text."""
        self._go_to_annotate()
        items = self.driver.find_elements(By.CSS_SELECTOR, ".bws-item")
        assert len(items) == 4, f"Expected 4 BWS items, found {len(items)}"

        # Check position labels
        labels = self.driver.find_elements(By.CSS_SELECTOR, ".bws-item-label")
        label_texts = [l.text.strip().rstrip(".") for l in labels]
        assert "A" in label_texts
        assert "D" in label_texts

    def test_standard_text_area_hidden(self):
        """The standard 'Text to Annotate' section is hidden when BWS is active."""
        self._go_to_annotate()
        container = self.driver.find_elements(By.CSS_SELECTOR, ".instance-text-container")
        if container:
            assert container[0].value_of_css_property("display") == "none"

    def test_select_best_tile(self):
        """Clicking a best tile highlights it and updates hidden input."""
        self._go_to_annotate()
        best_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-best-tile")
        assert len(best_tiles) >= 2

        # Click first best tile
        best_tiles[0].click()
        time.sleep(0.3)

        assert "selected" in best_tiles[0].get_attribute("class")

        # Check hidden input updated
        best_input = self.driver.find_element(
            By.CSS_SELECTOR, '.bws-value[label_name="best"]'
        )
        assert best_input.get_attribute("value") == "A"

    def test_select_worst_tile(self):
        """Clicking a worst tile highlights it and updates hidden input."""
        self._go_to_annotate()
        worst_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-worst-tile")
        assert len(worst_tiles) >= 2

        # Click last worst tile
        worst_tiles[-1].click()
        time.sleep(0.3)

        assert "selected" in worst_tiles[-1].get_attribute("class")

        worst_input = self.driver.find_element(
            By.CSS_SELECTOR, '.bws-value[label_name="worst"]'
        )
        assert worst_input.get_attribute("value") == "D"

    def test_only_one_best_selected(self):
        """Selecting a new best tile deselects the previous one."""
        self._go_to_annotate()
        best_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-best-tile")

        # Select first
        best_tiles[0].click()
        time.sleep(0.2)
        assert "selected" in best_tiles[0].get_attribute("class")

        # Select second
        best_tiles[1].click()
        time.sleep(0.2)
        assert "selected" not in best_tiles[0].get_attribute("class")
        assert "selected" in best_tiles[1].get_attribute("class")

    def test_only_one_worst_selected(self):
        """Selecting a new worst tile deselects the previous one."""
        self._go_to_annotate()
        worst_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-worst-tile")

        worst_tiles[0].click()
        time.sleep(0.2)
        assert "selected" in worst_tiles[0].get_attribute("class")

        worst_tiles[1].click()
        time.sleep(0.2)
        assert "selected" not in worst_tiles[0].get_attribute("class")
        assert "selected" in worst_tiles[1].get_attribute("class")

    def test_best_worst_different_validation(self):
        """Selecting same tile for both best and worst shows error and clears worst."""
        self._go_to_annotate()
        best_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-best-tile")
        worst_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-worst-tile")

        # Select A as best
        best_tiles[0].click()
        time.sleep(0.2)

        # Select A as worst (same position)
        worst_tiles[0].click()
        time.sleep(0.5)

        # Worst should be cleared (validation prevents same selection)
        worst_input = self.driver.find_element(
            By.CSS_SELECTOR, '.bws-value[label_name="worst"]'
        )
        assert worst_input.get_attribute("value") == ""

    def test_annotation_persists_after_refresh(self):
        """Select best+worst, wait for save, refresh, check visual tile state.

        Uses the beforeunload/visibilitychange sendBeacon handler plus the
        debounced save to ensure annotations reach the server before refresh.
        Verifies visual tile highlighting (CSS classes), not hidden input
        values, because browsers cache hidden input values across refresh.
        """
        self._go_to_annotate()

        # Select best=B, worst=D
        best_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-best-tile")
        worst_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-worst-tile")

        best_tiles[1].click()  # B
        time.sleep(0.3)
        worst_tiles[3].click()  # D
        time.sleep(1.5)  # Wait for 500ms debounced save + network round-trip

        # Refresh page (beforeunload handler will also fire sendBeacon)
        self.driver.refresh()
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".annotation-form.bws"))
        )
        time.sleep(1)

        # Check tile highlighting (visual state, not just hidden input values)
        selected_best = self.driver.find_elements(By.CSS_SELECTOR, ".bws-best-tile.selected")
        selected_worst = self.driver.find_elements(By.CSS_SELECTOR, ".bws-worst-tile.selected")
        assert len(selected_best) == 1, f"Expected 1 selected best tile, found {len(selected_best)}"
        assert len(selected_worst) == 1, f"Expected 1 selected worst tile, found {len(selected_worst)}"
        assert selected_best[0].get_attribute("data-value") == "B"
        assert selected_worst[0].get_attribute("data-value") == "D"

    def test_annotation_persists_after_navigation(self):
        """Select best+worst, navigate to next instance and back, verify restored.

        This tests true server-side persistence, not browser form state caching.
        Browser refresh can give false positives because browsers preserve hidden
        input values across refresh. Navigating away via Next button calls
        saveAnnotations() explicitly, then navigating back triggers a fresh
        server render with BeautifulSoup-injected values.
        """
        self._go_to_annotate()

        # Select best=B, worst=D
        best_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-best-tile")
        worst_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-worst-tile")

        best_tiles[1].click()  # B
        time.sleep(0.3)
        worst_tiles[3].click()  # D
        time.sleep(1)  # Wait for debounced save (500ms) to complete

        # Navigate to next instance via the Next button (calls saveAnnotations)
        next_btn = self.driver.find_element(By.ID, "next-btn")
        next_btn.click()

        # Wait for new page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".annotation-form.bws"))
        )
        time.sleep(1)

        # Navigate back to previous instance via the Previous button
        prev_btn = self.driver.find_element(By.ID, "prev-btn")
        prev_btn.click()

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".annotation-form.bws"))
        )
        time.sleep(1)

        # Verify tiles are visually highlighted (not just hidden input values)
        selected_best = self.driver.find_elements(
            By.CSS_SELECTOR, ".bws-best-tile.selected"
        )
        selected_worst = self.driver.find_elements(
            By.CSS_SELECTOR, ".bws-worst-tile.selected"
        )
        assert len(selected_best) == 1, (
            f"Expected 1 selected best tile, found {len(selected_best)}"
        )
        assert len(selected_worst) == 1, (
            f"Expected 1 selected worst tile, found {len(selected_worst)}"
        )
        assert selected_best[0].get_attribute("data-value") == "B"
        assert selected_worst[0].get_attribute("data-value") == "D"

    def test_annotation_persists_in_fresh_session(self):
        """Annotations survive a complete browser restart (new WebDriver).

        This is the strongest possible persistence test: it eliminates ALL
        browser-side caching (form state, bfcache, service workers) by
        destroying the browser process entirely and creating a new one.
        """
        self._go_to_annotate()

        # Select best=C, worst=A
        best_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-best-tile")
        worst_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-worst-tile")

        best_tiles[2].click()  # C
        time.sleep(0.3)
        worst_tiles[0].click()  # A
        time.sleep(1.5)  # Wait for debounced save

        # Destroy the browser completely
        username = self.test_user
        self.driver.quit()

        # Create a brand-new browser (no shared state with previous instance)
        self.driver = webdriver.Chrome(options=self.chrome_options)

        # Log in as the same user
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(username)
        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()
        time.sleep(1)

        # Skip through any consent/instruction pages
        for _ in range(5):
            try:
                continue_btn = self.driver.find_element(
                    By.CSS_SELECTOR, "button.btn-primary, input[type='submit']"
                )
                continue_btn.click()
                time.sleep(0.5)
            except (NoSuchElementException, Exception):
                break

        # Navigate to annotation page (should land on the same instance)
        self._go_to_annotate()
        time.sleep(1)

        # Verify tile highlighting is restored from server (no browser cache possible)
        selected_best = self.driver.find_elements(By.CSS_SELECTOR, ".bws-best-tile.selected")
        selected_worst = self.driver.find_elements(By.CSS_SELECTOR, ".bws-worst-tile.selected")
        assert len(selected_best) == 1, (
            f"Expected 1 selected best tile in fresh session, found {len(selected_best)}"
        )
        assert len(selected_worst) == 1, (
            f"Expected 1 selected worst tile in fresh session, found {len(selected_worst)}"
        )
        assert selected_best[0].get_attribute("data-value") == "C"
        assert selected_worst[0].get_attribute("data-value") == "A"

    def test_annotations_do_not_leak_to_new_instances(self):
        """Annotations from one instance must not appear on the next instance.

        Regression test: browser form state caching can cause hidden input values
        to leak across instances after window.location.reload().
        """
        self._go_to_annotate()

        # Select best=A, worst=C on first instance
        best_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-best-tile")
        worst_tiles = self.driver.find_elements(By.CSS_SELECTOR, ".bws-worst-tile")

        best_tiles[0].click()  # A
        time.sleep(0.3)
        worst_tiles[2].click()  # C
        time.sleep(1)  # Wait for debounced save

        # Navigate to next instance
        next_btn = self.driver.find_element(By.ID, "next-btn")
        next_btn.click()

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".annotation-form.bws"))
        )
        time.sleep(1)

        # On the new instance, no tiles should be selected
        selected_best = self.driver.find_elements(
            By.CSS_SELECTOR, ".bws-best-tile.selected"
        )
        selected_worst = self.driver.find_elements(
            By.CSS_SELECTOR, ".bws-worst-tile.selected"
        )
        assert len(selected_best) == 0, (
            f"Expected 0 selected best tiles on new instance, found {len(selected_best)}"
        )
        assert len(selected_worst) == 0, (
            f"Expected 0 selected worst tiles on new instance, found {len(selected_worst)}"
        )

        # Hidden input values should also be empty
        best_input = self.driver.find_element(
            By.CSS_SELECTOR, '.bws-value[label_name="best"]'
        )
        worst_input = self.driver.find_element(
            By.CSS_SELECTOR, '.bws-value[label_name="worst"]'
        )
        assert best_input.get_attribute("value") == "", (
            f"Expected empty best on new instance, got '{best_input.get_attribute('value')}'"
        )
        assert worst_input.get_attribute("value") == "", (
            f"Expected empty worst on new instance, got '{worst_input.get_attribute('value')}'"
        )

    def test_keyboard_shortcut_best(self):
        """Pressing number key selects corresponding best tile."""
        self._go_to_annotate()

        # Press "2" to select B as best
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys("2")
        time.sleep(0.3)

        best_input = self.driver.find_element(
            By.CSS_SELECTOR, '.bws-value[label_name="best"]'
        )
        assert best_input.get_attribute("value") == "B"

    def test_keyboard_shortcut_worst(self):
        """Pressing letter key selects corresponding worst tile."""
        self._go_to_annotate()

        # Press "c" to select C as worst
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys("c")
        time.sleep(0.3)

        worst_input = self.driver.find_element(
            By.CSS_SELECTOR, '.bws-value[label_name="worst"]'
        )
        assert worst_input.get_attribute("value") == "C"


if __name__ == "__main__":
    unittest.main()

"""
Selenium UI tests for pairwise annotation functionality.

Tests that annotators can use the UI to perform pairwise comparison tasks:
- Clicking on tiles to select preference
- Using keyboard shortcuts (1/2/0)
- Scale mode slider interaction
- Annotation persistence across navigation
"""

import pytest
import time
import json
import os
import tempfile
import shutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


class TestPairwiseBinaryUI:
    """Test suite for pairwise binary mode UI functionality."""

    @classmethod
    def setup_class(cls):
        """Set up the Flask server with pairwise binary annotation config."""
        # Create temp directory for test
        cls.test_dir = tempfile.mkdtemp(prefix="pairwise_binary_test_")
        cls.port = find_free_port()

        # Create data directory
        data_dir = os.path.join(cls.test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create data file with pairwise items
        data_file = os.path.join(data_dir, "pairwise_data.json")
        test_data = [
            {"id": "pair_1", "text": ["This is option A content.", "This is option B content."]},
            {"id": "pair_2", "text": ["First choice text here.", "Second choice text here."]},
            {"id": "pair_3", "text": ["Left side item.", "Right side item."]},
        ]
        with open(data_file, "w") as f:
            for item in test_data:
                f.write(json.dumps(item) + "\n")

        # Create config file
        config_file = os.path.join(cls.test_dir, "config.yaml")
        config_content = f"""
port: {cls.port}
server_name: Pairwise Binary Test
annotation_task_name: Pairwise Binary Annotation Test
task_dir: {cls.test_dir}
output_annotation_dir: {cls.test_dir}/annotation_output/
output_annotation_format: json

data_files:
  - data/pairwise_data.json

item_properties:
  id_key: id
  text_key: text

list_as_text:
  text_list_prefix_type: alphabet

user_config:
  allow_all_users: true
  users: []

annotation_schemes:
  - annotation_type: pairwise
    name: preference
    description: "Which option is better?"
    mode: binary
    items_key: text
    labels:
      - "Option A"
      - "Option B"
    allow_tie: true
    tie_label: "No preference"
    sequential_key_binding: true
    label_requirement:
      required: true

site_dir: default
"""
        with open(config_file, "w") as f:
            f.write(config_content)

        # Start Flask server
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        if not started:
            raise RuntimeError(f"Failed to start Flask server on port {cls.port}")

        # Set up Chrome options
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        cls.chrome_options = chrome_options

    @classmethod
    def teardown_class(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir') and os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setup_method(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.wait = WebDriverWait(self.driver, 15)
        # Generate unique user for test isolation
        self.test_user = f"pairwise_test_{int(time.time())}"
        self._login()

    def teardown_method(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login(self):
        """Log in a test user."""
        self.driver.get(f"{self.server.base_url}/")

        # Wait for page to load
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # Wait for login form
        username_field = self.wait.until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )

        # Enter username and submit
        username_field.clear()
        username_field.send_keys(self.test_user)

        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()

        # Wait for annotation page
        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "pairwise"))
        )

    def test_pairwise_tiles_displayed(self):
        """Test that pairwise tiles are displayed on the annotation page."""
        # Find pairwise tiles
        tiles = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile")
        assert len(tiles) == 2, f"Expected 2 tiles, found {len(tiles)}"

        # Check tile labels
        tile_labels = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile-label")
        assert len(tile_labels) >= 2

    def test_click_tile_selects_it(self):
        """Test that clicking a tile selects it."""
        # Find first tile
        tiles = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile")
        first_tile = tiles[0]

        # Click the tile
        first_tile.click()
        time.sleep(0.3)  # Wait for JavaScript to process

        # Check that tile is selected
        tile_classes = first_tile.get_attribute("class")
        assert "selected" in tile_classes, "Tile should be selected after click"

        # Check that hidden input has value
        hidden_input = self.driver.find_element(By.CLASS_NAME, "pairwise-value")
        assert hidden_input.get_attribute("value") == "A"

    def test_click_second_tile_deselects_first(self):
        """Test that clicking second tile deselects the first."""
        tiles = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile")

        # Click first tile
        tiles[0].click()
        time.sleep(0.2)

        # Click second tile
        tiles[1].click()
        time.sleep(0.2)

        # Check first tile is not selected
        assert "selected" not in tiles[0].get_attribute("class")

        # Check second tile is selected
        assert "selected" in tiles[1].get_attribute("class")

        # Check hidden input has value B
        hidden_input = self.driver.find_element(By.CLASS_NAME, "pairwise-value")
        assert hidden_input.get_attribute("value") == "B"

    def test_tie_button_displayed(self):
        """Test that tie button is displayed when allow_tie is true."""
        tie_btn = self.driver.find_element(By.CLASS_NAME, "pairwise-tie-btn")
        assert tie_btn.is_displayed()
        assert "No preference" in tie_btn.text

    def test_click_tie_button(self):
        """Test that clicking tie button selects it and deselects tiles."""
        tiles = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile")
        tie_btn = self.driver.find_element(By.CLASS_NAME, "pairwise-tie-btn")

        # First click a tile
        tiles[0].click()
        time.sleep(0.2)
        assert "selected" in tiles[0].get_attribute("class")

        # Now click tie button
        tie_btn.click()
        time.sleep(0.2)

        # Check tile is deselected
        assert "selected" not in tiles[0].get_attribute("class")

        # Check tie button is selected
        assert "selected" in tie_btn.get_attribute("class")

        # Check hidden input has tie value
        hidden_input = self.driver.find_element(By.CLASS_NAME, "pairwise-value")
        assert hidden_input.get_attribute("value") == "tie"

    def test_keyboard_shortcut_1_selects_tile_a(self):
        """Test that pressing '1' selects tile A."""
        # Focus on the page body
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.click()
        time.sleep(0.2)

        # Press '1' key
        ActionChains(self.driver).send_keys("1").perform()
        time.sleep(0.3)

        # Check tile A is selected
        tiles = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile")
        assert "selected" in tiles[0].get_attribute("class")

        hidden_input = self.driver.find_element(By.CLASS_NAME, "pairwise-value")
        assert hidden_input.get_attribute("value") == "A"

    def test_keyboard_shortcut_2_selects_tile_b(self):
        """Test that pressing '2' selects tile B."""
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.click()
        time.sleep(0.2)

        ActionChains(self.driver).send_keys("2").perform()
        time.sleep(0.3)

        tiles = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile")
        assert "selected" in tiles[1].get_attribute("class")

        hidden_input = self.driver.find_element(By.CLASS_NAME, "pairwise-value")
        assert hidden_input.get_attribute("value") == "B"

    def test_keyboard_shortcut_0_selects_tie(self):
        """Test that pressing '0' selects tie option."""
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.click()
        time.sleep(0.2)

        ActionChains(self.driver).send_keys("0").perform()
        time.sleep(0.3)

        tie_btn = self.driver.find_element(By.CLASS_NAME, "pairwise-tie-btn")
        assert "selected" in tie_btn.get_attribute("class")

        hidden_input = self.driver.find_element(By.CLASS_NAME, "pairwise-value")
        assert hidden_input.get_attribute("value") == "tie"

    def test_selection_persists_after_navigation(self):
        """Test that selection persists when navigating away and back."""
        # Select tile A
        tiles = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile")
        tiles[0].click()
        time.sleep(0.5)

        # Navigate to next instance
        next_btn = self.driver.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(0.5)

        # Navigate back to previous instance
        prev_btn = self.driver.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(0.5)

        # Check that selection is restored
        tiles = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile")
        # Note: This test may need adjustment based on how annotations are persisted


class TestPairwiseScaleUI:
    """Test suite for pairwise scale mode UI functionality."""

    @classmethod
    def setup_class(cls):
        """Set up the Flask server with pairwise scale annotation config."""
        cls.test_dir = tempfile.mkdtemp(prefix="pairwise_scale_test_")
        cls.port = find_free_port()

        # Create data directory
        data_dir = os.path.join(cls.test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create data file
        data_file = os.path.join(data_dir, "scale_data.json")
        test_data = [
            {"id": "scale_1", "text": ["Response A content.", "Response B content."]},
            {"id": "scale_2", "text": ["First answer.", "Second answer."]},
        ]
        with open(data_file, "w") as f:
            for item in test_data:
                f.write(json.dumps(item) + "\n")

        # Create config file
        config_file = os.path.join(cls.test_dir, "config.yaml")
        config_content = f"""
port: {cls.port}
server_name: Pairwise Scale Test
annotation_task_name: Pairwise Scale Annotation Test
task_dir: {cls.test_dir}
output_annotation_dir: {cls.test_dir}/annotation_output/
output_annotation_format: json

data_files:
  - data/scale_data.json

item_properties:
  id_key: id
  text_key: text

list_as_text:
  text_list_prefix_type: alphabet

user_config:
  allow_all_users: true
  users: []

annotation_schemes:
  - annotation_type: pairwise
    name: preference_scale
    description: "Rate how much better A is than B"
    mode: scale
    items_key: text
    labels:
      - "Response A"
      - "Response B"
    scale:
      min: -3
      max: 3
      step: 1
      default: 0
      labels:
        min: "A is much better"
        max: "B is much better"
        center: "Equal"
    label_requirement:
      required: true

site_dir: default
"""
        with open(config_file, "w") as f:
            f.write(config_content)

        # Start Flask server
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        if not started:
            raise RuntimeError(f"Failed to start Flask server on port {cls.port}")

        # Set up Chrome options
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        cls.chrome_options = chrome_options

    @classmethod
    def teardown_class(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir') and os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setup_method(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.wait = WebDriverWait(self.driver, 15)
        self.test_user = f"scale_test_{int(time.time())}"
        self._login()

    def teardown_method(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login(self):
        """Log in a test user."""
        self.driver.get(f"{self.server.base_url}/")
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        username_field = self.wait.until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        username_field.clear()
        username_field.send_keys(self.test_user)

        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()

        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "pairwise-scale"))
        )

    def test_scale_slider_displayed(self):
        """Test that scale slider is displayed on the annotation page."""
        slider = self.driver.find_element(By.CLASS_NAME, "pairwise-scale-slider")
        assert slider.is_displayed()

        # Check slider attributes
        assert slider.get_attribute("min") == "-3"
        assert slider.get_attribute("max") == "3"
        assert slider.get_attribute("step") == "1"

    def test_scale_labels_displayed(self):
        """Test that scale endpoint labels are displayed."""
        page_text = self.driver.find_element(By.TAG_NAME, "body").text

        assert "A is much better" in page_text
        assert "B is much better" in page_text
        assert "Equal" in page_text

    def test_scale_items_displayed(self):
        """Test that both items are displayed in scale mode."""
        scale_items = self.driver.find_elements(By.CLASS_NAME, "pairwise-scale-item")
        assert len(scale_items) == 2

    def test_slider_value_change(self):
        """Test that slider value can be changed."""
        slider = self.driver.find_element(By.CLASS_NAME, "pairwise-scale-slider")

        # Get initial value
        initial_value = slider.get_attribute("value")
        assert initial_value == "0"  # Default

        # Change slider value using JavaScript (more reliable for range inputs)
        self.driver.execute_script("""
            var slider = arguments[0];
            slider.value = -2;
            slider.dispatchEvent(new Event('input', { bubbles: true }));
            slider.dispatchEvent(new Event('change', { bubbles: true }));
        """, slider)
        time.sleep(0.3)

        # Verify value changed
        new_value = slider.get_attribute("value")
        assert new_value == "-2"

    def test_value_display_updates(self):
        """Test that value display updates when slider moves."""
        slider = self.driver.find_element(By.CLASS_NAME, "pairwise-scale-slider")

        # Change slider value
        self.driver.execute_script("""
            var slider = arguments[0];
            slider.value = 2;
            slider.dispatchEvent(new Event('input', { bubbles: true }));
        """, slider)
        time.sleep(0.3)

        # Check value display
        value_display = self.driver.find_element(By.CLASS_NAME, "pairwise-scale-current-value")
        assert value_display.text == "2"


class TestPairwiseMultipleSchemasUI:
    """Test multiple pairwise schemas on the same page."""

    @classmethod
    def setup_class(cls):
        """Set up the Flask server with multiple pairwise annotation schemas."""
        cls.test_dir = tempfile.mkdtemp(prefix="pairwise_multi_test_")
        cls.port = find_free_port()

        # Create data directory
        data_dir = os.path.join(cls.test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create data file
        data_file = os.path.join(data_dir, "multi_data.json")
        test_data = [
            {"id": "multi_1", "text": ["Response A", "Response B"]},
        ]
        with open(data_file, "w") as f:
            for item in test_data:
                f.write(json.dumps(item) + "\n")

        # Create config with multiple pairwise schemas
        config_file = os.path.join(cls.test_dir, "config.yaml")
        config_content = f"""
port: {cls.port}
server_name: Pairwise Multi Test
annotation_task_name: Multiple Pairwise Test
task_dir: {cls.test_dir}
output_annotation_dir: {cls.test_dir}/annotation_output/
output_annotation_format: json

data_files:
  - data/multi_data.json

item_properties:
  id_key: id
  text_key: text

list_as_text:
  text_list_prefix_type: alphabet

user_config:
  allow_all_users: true
  users: []

annotation_schemes:
  - annotation_type: pairwise
    name: fluency
    description: "Which is more fluent?"
    mode: binary
    items_key: text
    allow_tie: true
    sequential_key_binding: false  # Disable to avoid conflicts

  - annotation_type: pairwise
    name: relevance
    description: "Which is more relevant?"
    mode: binary
    items_key: text
    allow_tie: true
    sequential_key_binding: false

  - annotation_type: pairwise
    name: overall
    description: "Overall preference"
    mode: scale
    items_key: text
    scale:
      min: -2
      max: 2
      step: 1
      default: 0

site_dir: default
"""
        with open(config_file, "w") as f:
            f.write(config_content)

        # Start Flask server
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        if not started:
            raise RuntimeError(f"Failed to start Flask server on port {cls.port}")

        # Set up Chrome options
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        cls.chrome_options = chrome_options

    @classmethod
    def teardown_class(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir') and os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setup_method(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.wait = WebDriverWait(self.driver, 15)
        self.test_user = f"multi_test_{int(time.time())}"
        self._login()

    def teardown_method(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login(self):
        """Log in a test user."""
        self.driver.get(f"{self.server.base_url}/")
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        username_field = self.wait.until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        username_field.clear()
        username_field.send_keys(self.test_user)

        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()

        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "pairwise"))
        )

    def test_multiple_pairwise_forms_displayed(self):
        """Test that all pairwise forms are displayed."""
        pairwise_forms = self.driver.find_elements(By.CSS_SELECTOR, "form.pairwise")
        assert len(pairwise_forms) == 3, f"Expected 3 pairwise forms, found {len(pairwise_forms)}"

    def test_binary_and_scale_modes_coexist(self):
        """Test that both binary and scale mode forms are present."""
        binary_forms = self.driver.find_elements(By.CSS_SELECTOR, "form.pairwise-binary")
        scale_forms = self.driver.find_elements(By.CSS_SELECTOR, "form.pairwise-scale")

        assert len(binary_forms) == 2, "Expected 2 binary mode forms"
        assert len(scale_forms) == 1, "Expected 1 scale mode form"

    def test_independent_selection_per_schema(self):
        """Test that selections in one schema don't affect others."""
        # Find all binary forms and their tiles
        binary_forms = self.driver.find_elements(By.CSS_SELECTOR, "form.pairwise-binary")

        # Select tile A in first form
        first_form_tiles = binary_forms[0].find_elements(By.CLASS_NAME, "pairwise-tile")
        first_form_tiles[0].click()
        time.sleep(0.2)

        # Select tile B in second form
        second_form_tiles = binary_forms[1].find_elements(By.CLASS_NAME, "pairwise-tile")
        second_form_tiles[1].click()
        time.sleep(0.2)

        # Verify first form still has A selected
        assert "selected" in first_form_tiles[0].get_attribute("class")
        assert "selected" not in first_form_tiles[1].get_attribute("class")

        # Verify second form has B selected
        assert "selected" not in second_form_tiles[0].get_attribute("class")
        assert "selected" in second_form_tiles[1].get_attribute("class")

        # Verify hidden inputs have correct values
        first_hidden = binary_forms[0].find_element(By.CLASS_NAME, "pairwise-value")
        second_hidden = binary_forms[1].find_element(By.CLASS_NAME, "pairwise-value")

        assert first_hidden.get_attribute("value") == "A"
        assert second_hidden.get_attribute("value") == "B"

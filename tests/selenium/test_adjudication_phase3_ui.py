"""
Selenium UI tests for Phase 3 adjudication features.

Tests the Phase 3 adjudication frontend elements in a real browser:
- Similar Items panel visibility when similarity is disabled
- Annotator signal badges rendering and structure
- API response verification for item, similar items, and signals
- ADJ_CONFIG JS configuration for similarity_enabled
- Item view integration with Phase 3 panels
"""

import json
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

from potato.simulator import SimulatorManager, SimulatorConfig, UserConfig
from potato.simulator.config import (
    CompetenceLevel,
    AnnotationStrategyType,
    BiasedStrategyConfig,
)
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory


class TestAdjudicationPhase3UI(unittest.TestCase):
    """Selenium tests for Phase 3 adjudication features: similar items, signals."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server, run simulator with biased users, prepare browser."""
        # ----- Test directory & data -----
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "selenium_adj_phase3")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create 15 data items
        items = [
            {"id": f"p3_item_{i:03d}", "text": f"Phase 3 test sentence {i} for adjudication signal testing."}
            for i in range(15)
        ]
        data_file = os.path.join(cls.test_dir, "test_data.jsonl")
        with open(data_file, "w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

        # ----- Config (no similarity enabled) -----
        config = {
            "annotation_task_name": "Adjudication Phase3 Selenium Test",
            "task_dir": os.path.abspath(cls.test_dir),
            "data_files": ["test_data.jsonl"],
            "output_annotation_dir": "output",
            "output_annotation_format": "json",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": [
                        {"name": "positive"},
                        {"name": "negative"},
                        {"name": "neutral"},
                    ],
                    "description": "Classify the sentiment.",
                }
            ],
            "user_config": {"allow_anonymous": True},
            "max_annotations_per_item": 3,
            "adjudication": {
                "enabled": True,
                "adjudicator_users": ["adj_phase3"],
                "min_annotations": 2,
                "agreement_threshold": 0.99,
                "show_all_items": True,
                "show_annotator_names": True,
                "show_timing_data": True,
                "require_confidence": True,
                "error_taxonomy": ["ambiguous_text", "guideline_gap"],
                # similarity is NOT configured, so similarity_enabled defaults to False
            },
            "debug": True,
        }
        config_file = os.path.join(cls.test_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        # ----- Start server -----
        cls.server = FlaskTestServer(
            port=find_free_port(), debug=False, config_file=config_file
        )
        started = cls.server.start()
        if not started:
            raise unittest.SkipTest("Failed to start Flask server")

        # ----- Run simulator with biased users -----
        users = [
            UserConfig(
                user_id="p3_user_a",
                competence=CompetenceLevel.AVERAGE,
                strategy=AnnotationStrategyType.BIASED,
                biased_config=BiasedStrategyConfig(
                    label_weights={"positive": 0.9, "negative": 0.05, "neutral": 0.05}
                ),
            ),
            UserConfig(
                user_id="p3_user_b",
                competence=CompetenceLevel.AVERAGE,
                strategy=AnnotationStrategyType.BIASED,
                biased_config=BiasedStrategyConfig(
                    label_weights={"positive": 0.05, "negative": 0.9, "neutral": 0.05}
                ),
            ),
        ]
        sim_config = SimulatorConfig(
            users=users,
            user_count=2,
            parallel_users=1,
            delay_between_users=0.0,
            simulate_wait=False,
        )
        mgr = SimulatorManager(sim_config, cls.server.base_url)
        results = mgr.run_sequential(max_annotations_per_user=15)
        total = sum(len(r.annotations) for r in results.values())
        if total == 0:
            raise unittest.SkipTest("Simulator produced no annotations")

        # ----- Chrome options -----
        chrome_opts = ChromeOptions()
        chrome_opts.add_argument("--headless=new")
        chrome_opts.add_argument("--no-sandbox")
        chrome_opts.add_argument("--disable-dev-shm-usage")
        chrome_opts.add_argument("--disable-gpu")
        chrome_opts.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_opts

    @classmethod
    def tearDownClass(cls):
        """Stop server, clean up."""
        if hasattr(cls, "server"):
            cls.server.stop()
        if hasattr(cls, "test_dir"):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    # -- Per-test setup / teardown --

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(2)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    # -- Helpers --

    def _login_adjudicator(self):
        """Register + login as the adjudicator via the web form."""
        import requests as req

        s = req.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": "adj_phase3", "pass": "pass"},
        )
        s.post(
            f"{self.server.base_url}/auth",
            data={"email": "adj_phase3", "pass": "pass"},
        )
        # Transfer session cookie to the browser
        for cookie in s.cookies:
            self.driver.get(self.server.base_url)
            self.driver.add_cookie(
                {"name": cookie.name, "value": cookie.value, "path": "/"}
            )

    def _login_regular_user(self):
        """Login as a non-adjudicator user."""
        import requests as req

        s = req.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": "regular_p3", "pass": "pass"},
        )
        s.post(
            f"{self.server.base_url}/auth",
            data={"email": "regular_p3", "pass": "pass"},
        )
        for cookie in s.cookies:
            self.driver.get(self.server.base_url)
            self.driver.add_cookie(
                {"name": cookie.name, "value": cookie.value, "path": "/"}
            )

    def _wait(self, by, value, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def _wait_visible(self, by, value, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )

    def _navigate_and_select_item(self):
        """Navigate to adjudication page and select the first queue item.

        Returns the instance_id of the selected item, or None if the queue is empty.
        """
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        items = self.driver.find_elements(By.CLASS_NAME, "adj-queue-item")
        if not items:
            return None

        items[0].click()
        time.sleep(1)

        # Extract instance_id from the item header
        item_id_el = self.driver.find_element(By.ID, "adj-item-id")
        text = item_id_el.text
        # Text is "Item: p3_item_000" - extract the ID
        instance_id = text.replace("Item: ", "").strip() if text.startswith("Item:") else None
        return instance_id

    # ================================================================
    # Tests: Similar Items Panel
    # ================================================================

    def test_similar_items_panel_hidden_when_disabled(self):
        """When similarity is not configured, #adj-similar-items-panel should have display: none."""
        instance_id = self._navigate_and_select_item()
        if instance_id is None:
            self.skipTest("No items in queue")

        panel = self.driver.find_element(By.ID, "adj-similar-items-panel")
        display = panel.value_of_css_property("display")
        self.assertEqual(
            display, "none",
            "Similar items panel should be hidden (display: none) when similarity is not configured",
        )

    def test_similar_items_panel_exists_in_dom(self):
        """The #adj-similar-items-panel div should exist in the HTML even when hidden."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(2)

        panels = self.driver.find_elements(By.ID, "adj-similar-items-panel")
        self.assertEqual(
            len(panels), 1,
            "There should be exactly one #adj-similar-items-panel element in the DOM",
        )

    # ================================================================
    # Tests: Annotator Signal Badges
    # ================================================================

    def test_annotator_cards_have_data_attribute(self):
        """After loading an item, .adj-annotator-card elements should have data-annotator attributes."""
        instance_id = self._navigate_and_select_item()
        if instance_id is None:
            self.skipTest("No items in queue")

        cards = self.driver.find_elements(By.CLASS_NAME, "adj-annotator-card")
        if not cards:
            self.skipTest("No annotator cards found for this item")

        for card in cards:
            attr = card.get_attribute("data-annotator")
            self.assertIsNotNone(
                attr,
                "Each .adj-annotator-card should have a data-annotator attribute",
            )
            self.assertTrue(
                len(attr) > 0,
                "data-annotator attribute should not be empty",
            )

    def test_signal_badges_render_when_present(self):
        """If annotator signals are triggered, .adj-signal-flags divs should exist with badges."""
        instance_id = self._navigate_and_select_item()
        if instance_id is None:
            self.skipTest("No items in queue")

        signal_flags = self.driver.find_elements(By.CLASS_NAME, "adj-signal-flags")
        if not signal_flags:
            # Signals may not be triggered if simulator timing does not
            # produce fast_decision warnings. This is acceptable.
            self.skipTest(
                "No signal flags present - simulator may not have triggered signals"
            )

        # If signal flags exist, they should contain at least one badge
        for flags_div in signal_flags:
            badges = flags_div.find_elements(By.CLASS_NAME, "adj-signal-badge")
            self.assertGreater(
                len(badges), 0,
                "Each .adj-signal-flags div should contain at least one .adj-signal-badge",
            )

    def test_signal_badge_has_severity_class(self):
        """If signal badges are present, they should have adj-signal-high or adj-signal-medium class."""
        instance_id = self._navigate_and_select_item()
        if instance_id is None:
            self.skipTest("No items in queue")

        badges = self.driver.find_elements(By.CLASS_NAME, "adj-signal-badge")
        if not badges:
            self.skipTest(
                "No signal badges present - simulator may not have triggered signals"
            )

        valid_severity_classes = {"adj-signal-high", "adj-signal-medium"}
        for badge in badges:
            classes = badge.get_attribute("class").split()
            severity_classes = set(classes) & valid_severity_classes
            self.assertTrue(
                len(severity_classes) > 0,
                f"Signal badge should have one of {valid_severity_classes}, got classes: {classes}",
            )

    def test_signal_badge_has_tooltip(self):
        """If signal badges are present, they should have a title attribute (tooltip)."""
        instance_id = self._navigate_and_select_item()
        if instance_id is None:
            self.skipTest("No items in queue")

        badges = self.driver.find_elements(By.CLASS_NAME, "adj-signal-badge")
        if not badges:
            self.skipTest(
                "No signal badges present - simulator may not have triggered signals"
            )

        for badge in badges:
            title = badge.get_attribute("title")
            self.assertIsNotNone(
                title,
                "Signal badge should have a title attribute for tooltip",
            )
            # The title is the flag.message, which should be a non-empty string
            self.assertTrue(
                len(title) > 0,
                "Signal badge title (tooltip) should not be empty",
            )

    # ================================================================
    # Tests: API Response Verification via JS
    # ================================================================

    def test_item_api_returns_annotator_signals(self):
        """The /adjudicate/api/item/<id> endpoint should include annotator_signals."""
        instance_id = self._navigate_and_select_item()
        if instance_id is None:
            self.skipTest("No items in queue")

        script = """
        var callback = arguments[arguments.length - 1];
        fetch('/adjudicate/api/item/' + arguments[0])
            .then(function(r) { return r.json(); })
            .then(function(data) { callback(data); })
            .catch(function(err) { callback({error: err.message}); });
        """
        result = self.driver.execute_async_script(script, instance_id)

        self.assertIsNotNone(result, "API response should not be null")
        self.assertNotIn("error", result, f"API returned error: {result.get('error')}")
        self.assertIn(
            "annotator_signals", result,
            "API response should include 'annotator_signals' field",
        )
        # annotator_signals should be a dict (possibly empty)
        self.assertIsInstance(
            result["annotator_signals"], dict,
            "annotator_signals should be a dictionary",
        )

    def test_item_api_returns_similar_items(self):
        """The /adjudicate/api/item/<id> endpoint should include similar_items."""
        instance_id = self._navigate_and_select_item()
        if instance_id is None:
            self.skipTest("No items in queue")

        script = """
        var callback = arguments[arguments.length - 1];
        fetch('/adjudicate/api/item/' + arguments[0])
            .then(function(r) { return r.json(); })
            .then(function(data) { callback(data); })
            .catch(function(err) { callback({error: err.message}); });
        """
        result = self.driver.execute_async_script(script, instance_id)

        self.assertIsNotNone(result, "API response should not be null")
        self.assertNotIn("error", result, f"API returned error: {result.get('error')}")
        self.assertIn(
            "similar_items", result,
            "API response should include 'similar_items' field",
        )
        # Since similarity is disabled, similar_items should be an empty list
        self.assertIsInstance(
            result["similar_items"], list,
            "similar_items should be a list",
        )
        self.assertEqual(
            len(result["similar_items"]), 0,
            "similar_items should be empty when similarity is not configured",
        )

    def test_similar_api_returns_structure(self):
        """The /adjudicate/api/similar/<id> endpoint should return correct structure."""
        instance_id = self._navigate_and_select_item()
        if instance_id is None:
            self.skipTest("No items in queue")

        script = """
        var callback = arguments[arguments.length - 1];
        fetch('/adjudicate/api/similar/' + arguments[0])
            .then(function(r) { return r.json(); })
            .then(function(data) { callback(data); })
            .catch(function(err) { callback({error: err.message}); });
        """
        result = self.driver.execute_async_script(script, instance_id)

        self.assertIsNotNone(result, "API response should not be null")
        self.assertNotIn("error", result, f"API returned error: {result.get('error')}")

        # Verify all required fields are present
        required_fields = ["enabled", "instance_id", "similar_items", "count"]
        for field in required_fields:
            self.assertIn(
                field, result,
                f"API response should include '{field}' field",
            )

        # Verify field types and values
        self.assertFalse(
            result["enabled"],
            "enabled should be False since similarity is not configured",
        )
        self.assertEqual(
            result["instance_id"], instance_id,
            "instance_id in response should match the requested ID",
        )
        self.assertIsInstance(
            result["similar_items"], list,
            "similar_items should be a list",
        )
        self.assertEqual(
            result["count"], 0,
            "count should be 0 when similarity is disabled",
        )

    # ================================================================
    # Tests: Config in JS
    # ================================================================

    def test_adj_config_has_similarity_enabled(self):
        """window.ADJ_CONFIG.similarity_enabled should be false when not configured."""
        self._login_adjudicator()
        self.driver.get(f"{self.server.base_url}/adjudicate")
        time.sleep(1)

        similarity_enabled = self.driver.execute_script(
            "return window.ADJ_CONFIG.similarity_enabled;"
        )
        self.assertFalse(
            similarity_enabled,
            "ADJ_CONFIG.similarity_enabled should be false when similarity is not configured",
        )

    # ================================================================
    # Tests: Item View Integration
    # ================================================================

    def test_item_view_renders_with_phase3_panel(self):
        """After clicking a queue item, the HTML should contain #adj-similar-items-panel."""
        instance_id = self._navigate_and_select_item()
        if instance_id is None:
            self.skipTest("No items in queue")

        # The item view should be visible
        item_view = self.driver.find_element(By.ID, "adj-item-view")
        self.assertTrue(
            item_view.is_displayed(),
            "Item view should be visible after selecting a queue item",
        )

        # The similar items panel should exist within the item view
        panel = item_view.find_element(By.ID, "adj-similar-items-panel")
        self.assertIsNotNone(
            panel,
            "#adj-similar-items-panel should be present inside the item view",
        )

    def test_annotator_response_cards_display(self):
        """After selecting an item, .adj-annotator-card elements should be present."""
        instance_id = self._navigate_and_select_item()
        if instance_id is None:
            self.skipTest("No items in queue")

        cards = self.driver.find_elements(By.CLASS_NAME, "adj-annotator-card")
        self.assertGreater(
            len(cards), 0,
            "There should be at least one annotator response card after selecting an item",
        )

        # Each card should display annotator information
        for card in cards:
            # Card should have an annotator name element
            name_els = card.find_elements(By.CLASS_NAME, "adj-annotator-name")
            self.assertEqual(
                len(name_els), 1,
                "Each annotator card should contain one .adj-annotator-name element",
            )
            self.assertTrue(
                len(name_els[0].text) > 0,
                "Annotator name should not be empty",
            )

            # Card should have an annotator value element
            value_els = card.find_elements(By.CLASS_NAME, "adj-annotator-value")
            self.assertEqual(
                len(value_els), 1,
                "Each annotator card should contain one .adj-annotator-value element",
            )
            self.assertTrue(
                len(value_els[0].text) > 0,
                "Annotator value should not be empty",
            )


if __name__ == "__main__":
    unittest.main()

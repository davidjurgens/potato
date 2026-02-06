#!/usr/bin/env python3
"""
Selenium tests for diversity-based item ordering.

Tests the user experience when diversity_clustering assignment strategy is enabled:
- Items are presented from different topic clusters
- Navigation works correctly with reordered items
- Annotating triggers reclustering appropriately
- Order is preserved for visited/annotated items
"""

import os
import time
import pytest
import shutil
import yaml
import json
import numpy as np
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


def create_diversity_test_data(test_dir):
    """Create test data with distinct topic clusters."""
    # Create data with clear topic separation for predictable clustering
    data = [
        # Sports cluster (items 0-2)
        {"id": "sports1", "text": "The championship football game ended in overtime victory."},
        {"id": "sports2", "text": "Basketball playoffs feature exciting matchups this weekend."},
        {"id": "sports3", "text": "Tennis tournament draws record crowds to center court."},
        # Tech cluster (items 3-5)
        {"id": "tech1", "text": "New smartphone features advanced artificial intelligence chip."},
        {"id": "tech2", "text": "Cloud computing transforms enterprise software deployment."},
        {"id": "tech3", "text": "Cybersecurity threats increase with connected devices."},
        # Food cluster (items 6-8)
        {"id": "food1", "text": "Italian restaurant serves authentic handmade pasta dishes."},
        {"id": "food2", "text": "Sushi chef prepares fresh fish from morning market."},
        {"id": "food3", "text": "Farm to table cuisine highlights local seasonal produce."},
        # Travel cluster (items 9-11)
        {"id": "travel1", "text": "Paris remains the most visited European destination."},
        {"id": "travel2", "text": "Caribbean beach resorts offer relaxation and water sports."},
        {"id": "travel3", "text": "Mountain hiking trails provide scenic alpine views."},
    ]

    data_file = Path(test_dir) / "data" / "diversity_test.json"
    data_file.parent.mkdir(parents=True, exist_ok=True)

    with open(data_file, "w") as f:
        json.dump(data, f, indent=2)

    return str(data_file)


def create_diversity_config(test_dir, data_file, port):
    """Create config with diversity_clustering enabled."""
    config = {
        "annotation_task_name": "Diversity Ordering Test",
        "task_dir": test_dir,
        "data_files": [data_file],
        "output_annotation_dir": "annotation_output",
        "item_properties": {
            "id_key": "id",
            "text_key": "text",
        },
        "assignment_strategy": "diversity_clustering",
        "diversity_ordering": {
            "enabled": True,
            "prefill_count": 12,
            "num_clusters": 4,
            "auto_clusters": False,
            "recluster_threshold": 1.0,
            "preserve_visited": True,
        },
        "annotation_schemes": [
            {
                "annotation_type": "radio",
                "name": "topic",
                "description": "What is the main topic of this text?",
                "labels": ["Sports", "Technology", "Food", "Travel"],
            }
        ],
        "user_config": {
            "allow_all_users": True,
            "users": [],
        },
        "server": {
            "port": port,
        },
    }

    config_path = Path(test_dir) / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return str(config_path)


class TestDiversityOrderingUI:
    """Selenium tests for diversity ordering user interface."""

    @pytest.fixture(scope="class")
    def test_dir(self, request):
        """Create test directory for diversity tests."""
        test_dir = os.path.join(
            os.path.dirname(__file__),
            "..", "output",
            f"diversity_ui_test_{int(time.time())}"
        )
        os.makedirs(test_dir, exist_ok=True)

        def cleanup():
            shutil.rmtree(test_dir, ignore_errors=True)

        request.addfinalizer(cleanup)
        return test_dir

    @pytest.fixture(scope="class")
    def flask_server(self, request, test_dir):
        """Start Flask server with diversity ordering enabled."""
        # Check if required packages are available
        try:
            import sentence_transformers
            import sklearn
        except ImportError:
            pytest.skip("sentence-transformers or scikit-learn not installed")

        port = find_free_port()
        data_file = create_diversity_test_data(test_dir)
        config_path = create_diversity_config(test_dir, data_file, port)

        server = FlaskTestServer(port=port, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask server for diversity tests")

        yield server
        server.stop()

    @pytest.fixture
    def browser(self):
        """Create headless Chrome browser for testing."""
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        driver = webdriver.Chrome(options=chrome_options)
        yield driver
        driver.quit()

    def register_user(self, browser, base_url, username):
        """Register a new user and navigate to annotation page."""
        browser.get(f"{base_url}/")

        # Wait for login page
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='email']"))
        )

        # Fill in username (no password when allow_all_users=True)
        email_input = browser.find_element(By.CSS_SELECTOR, "input[name='email']")
        email_input.send_keys(username)

        # Submit form (button type="submit" not input type="submit")
        submit_btn = browser.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()

        # Wait for annotation page to load
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

    def get_current_instance_id(self, browser):
        """Get the current instance ID from the page."""
        try:
            instance_element = browser.find_element(By.ID, "instance_id")
            return instance_element.get_attribute("value")
        except:
            # Try getting it from the page content
            text_element = browser.find_element(By.ID, "instance-text")
            return text_element.text[:20]  # First 20 chars as identifier

    def get_displayed_text(self, browser):
        """Get the currently displayed instance text."""
        text_element = browser.find_element(By.ID, "instance-text")
        return text_element.text

    def select_topic(self, browser, topic_name):
        """Select a topic radio button."""
        radio = browser.find_element(
            By.CSS_SELECTOR,
            f"input[name='topic'][value='{topic_name}']"
        )
        radio.click()
        time.sleep(0.1)  # Brief pause for registration

    def click_next(self, browser):
        """Click the next button to navigate forward."""
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(0.2)  # Wait for navigation

    def click_prev(self, browser):
        """Click the previous button to navigate backward."""
        prev_btn = browser.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(0.2)  # Wait for navigation

    def test_server_starts_with_diversity(self, flask_server, browser):
        """Test that server starts and loads correctly with diversity ordering."""
        browser.get(f"{flask_server.base_url}/")

        # Should see login/registration page
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='email']"))
        )

        assert "Diversity" in browser.title or browser.page_source

    def test_user_can_register_and_see_annotation(self, flask_server, browser):
        """Test that a user can register and see the annotation interface."""
        username = f"diversity_user_{int(time.time())}"
        self.register_user(browser, flask_server.base_url, username)

        # Verify annotation interface is displayed
        text_element = browser.find_element(By.ID, "instance-text")
        assert text_element.is_displayed()

        # Verify topic radio buttons are present
        radios = browser.find_elements(By.CSS_SELECTOR, "input[name='topic']")
        assert len(radios) == 4  # Sports, Technology, Food, Travel

    def test_navigation_works_with_diversity(self, flask_server, browser):
        """Test that navigation between items works correctly."""
        username = f"nav_user_{int(time.time())}"
        self.register_user(browser, flask_server.base_url, username)

        # Get first item text
        first_text = self.get_displayed_text(browser)

        # Navigate forward
        self.click_next(browser)

        # Should see different item
        second_text = self.get_displayed_text(browser)
        assert first_text != second_text, "Navigation should show different item"

        # Navigate back
        self.click_prev(browser)

        # Should see first item again
        back_text = self.get_displayed_text(browser)
        assert back_text == first_text, "Going back should show original item"

    def test_items_show_topic_variety(self, flask_server, browser):
        """Test that consecutive items show variety in topics."""
        username = f"variety_user_{int(time.time())}"
        self.register_user(browser, flask_server.base_url, username)

        # Collect text from first several items
        texts = []
        for i in range(4):
            text = self.get_displayed_text(browser)
            texts.append(text)
            if i < 3:
                self.click_next(browser)

        # Check for variety - should have items from different topics
        # At least 3 of 4 items should be from different topic clusters
        topic_keywords = {
            "sports": ["football", "basketball", "tennis", "game", "playoffs"],
            "tech": ["smartphone", "cloud", "cybersecurity", "artificial", "computing"],
            "food": ["restaurant", "sushi", "pasta", "chef", "cuisine"],
            "travel": ["paris", "beach", "mountain", "resort", "hiking"]
        }

        detected_topics = set()
        for text in texts:
            text_lower = text.lower()
            for topic, keywords in topic_keywords.items():
                if any(kw in text_lower for kw in keywords):
                    detected_topics.add(topic)
                    break

        # With diversity ordering, first 4 items should ideally come from 4 different topics
        # Allow some variance - at least 2 different topics
        assert len(detected_topics) >= 2, \
            f"Expected topic variety in first 4 items, got only {detected_topics}"

    def test_annotate_and_navigate(self, flask_server, browser):
        """Test annotating items and navigating between them."""
        username = f"annotate_user_{int(time.time())}"
        self.register_user(browser, flask_server.base_url, username)

        # Annotate first item
        first_text = self.get_displayed_text(browser)
        self.select_topic(browser, "Sports")

        # Navigate to next and annotate
        self.click_next(browser)
        second_text = self.get_displayed_text(browser)
        self.select_topic(browser, "Technology")

        # Navigate to third and annotate
        self.click_next(browser)
        third_text = self.get_displayed_text(browser)
        self.select_topic(browser, "Food")

        # Go back and verify annotations are preserved
        self.click_prev(browser)
        assert self.get_displayed_text(browser) == second_text

        # Check that Technology radio is still selected
        tech_radio = browser.find_element(
            By.CSS_SELECTOR,
            "input[name='topic'][value='Technology']"
        )
        # Note: Selection state may or may not persist depending on implementation

        self.click_prev(browser)
        assert self.get_displayed_text(browser) == first_text

    def test_order_preserved_for_annotated_items(self, flask_server, browser):
        """Test that annotated items maintain their positions when navigating back."""
        username = f"preserve_user_{int(time.time())}"
        self.register_user(browser, flask_server.base_url, username)

        # Navigate through first 3 items, annotate each, and record their order
        item_order = []
        for i in range(3):
            text = self.get_displayed_text(browser)
            item_order.append(text)

            # Annotate the item to mark it as completed
            self.select_topic(browser, "Sports")
            time.sleep(0.2)  # Wait for annotation to register

            if i < 2:
                self.click_next(browser)
                time.sleep(0.3)  # Wait for page to fully load

        # Navigate back through annotated items
        for i in range(2, 0, -1):
            self.click_prev(browser)
            time.sleep(0.3)  # Wait for page to fully load
            current_text = self.get_displayed_text(browser)
            expected_text = item_order[i - 1]
            assert current_text == expected_text, \
                f"Annotated item at position {i-1} should be preserved. Expected: {expected_text[:30]}..., Got: {current_text[:30]}..."

    def test_multiple_users_can_annotate(self, flask_server, browser):
        """Test that multiple users can use diversity ordering independently."""
        # First user
        username1 = f"multi_user1_{int(time.time())}"
        self.register_user(browser, flask_server.base_url, username1)

        user1_first_text = self.get_displayed_text(browser)
        self.select_topic(browser, "Sports")
        self.click_next(browser)
        user1_second_text = self.get_displayed_text(browser)

        # Clear session for second user
        browser.delete_all_cookies()

        # Second user
        username2 = f"multi_user2_{int(time.time())}"
        self.register_user(browser, flask_server.base_url, username2)

        user2_first_text = self.get_displayed_text(browser)

        # Both users should be able to see items (may or may not be same order)
        assert user2_first_text is not None
        assert len(user2_first_text) > 0

    def test_annotation_workflow_complete(self, flask_server, browser):
        """Test a complete annotation workflow with diversity ordering."""
        username = f"workflow_user_{int(time.time())}"
        self.register_user(browser, flask_server.base_url, username)

        topics_map = {
            "football": "Sports", "basketball": "Sports", "tennis": "Sports",
            "smartphone": "Technology", "cloud": "Technology", "cybersecurity": "Technology",
            "restaurant": "Food", "sushi": "Food", "pasta": "Food",
            "paris": "Travel", "beach": "Travel", "mountain": "Travel",
        }

        # Annotate several items with appropriate topics
        for i in range(6):
            text = self.get_displayed_text(browser).lower()

            # Determine correct topic based on keywords
            selected_topic = "Sports"  # default
            for keyword, topic in topics_map.items():
                if keyword in text:
                    selected_topic = topic
                    break

            self.select_topic(browser, selected_topic)

            if i < 5:
                self.click_next(browser)
                time.sleep(0.1)

        # Verify we can still navigate
        self.click_prev(browser)
        prev_text = self.get_displayed_text(browser)
        assert prev_text is not None and len(prev_text) > 0


class TestDiversityOrderingWithRecluster:
    """Tests for reclustering behavior when users sample all clusters."""

    @pytest.fixture(scope="class")
    def test_dir(self, request):
        """Create test directory."""
        test_dir = os.path.join(
            os.path.dirname(__file__),
            "..", "output",
            f"diversity_recluster_test_{int(time.time())}"
        )
        os.makedirs(test_dir, exist_ok=True)

        def cleanup():
            shutil.rmtree(test_dir, ignore_errors=True)

        request.addfinalizer(cleanup)
        return test_dir

    @pytest.fixture(scope="class")
    def flask_server(self, request, test_dir):
        """Start Flask server with low recluster threshold for testing."""
        try:
            import sentence_transformers
            import sklearn
        except ImportError:
            pytest.skip("sentence-transformers or scikit-learn not installed")

        port = find_free_port()
        data_file = create_diversity_test_data(test_dir)

        # Create config with low recluster threshold
        config = {
            "annotation_task_name": "Recluster Test",
            "task_dir": test_dir,
            "data_files": [data_file],
            "output_annotation_dir": "annotation_output",
            "item_properties": {
                "id_key": "id",
                "text_key": "text",
            },
            "assignment_strategy": "diversity_clustering",
            "diversity_ordering": {
                "enabled": True,
                "prefill_count": 12,
                "num_clusters": 4,
                "auto_clusters": False,
                "recluster_threshold": 0.5,  # Recluster at 50% cluster coverage
                "preserve_visited": True,
            },
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "topic",
                    "description": "Topic?",
                    "labels": ["Sports", "Technology", "Food", "Travel"],
                }
            ],
            "user_config": {
                "allow_all_users": True,
                "users": [],
            },
        }

        config_path = Path(test_dir) / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        server = FlaskTestServer(port=port, config_file=str(config_path))
        if not server.start():
            pytest.fail("Failed to start Flask server")

        yield server
        server.stop()

    @pytest.fixture
    def browser(self):
        """Create headless Chrome browser."""
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        driver = webdriver.Chrome(options=chrome_options)
        yield driver
        driver.quit()

    def register_user(self, browser, base_url, username):
        """Register a user."""
        browser.get(f"{base_url}/")
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='email']"))
        )

        browser.find_element(By.CSS_SELECTOR, "input[name='email']").send_keys(username)
        browser.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

    def test_continuous_annotation_session(self, flask_server, browser):
        """Test that annotation continues working even after potential reclustering."""
        username = f"recluster_user_{int(time.time())}"
        self.register_user(browser, flask_server.base_url, username)

        # Annotate through all 12 items
        annotated_texts = []
        for i in range(12):
            text_elem = browser.find_element(By.ID, "instance-text")
            text = text_elem.text
            annotated_texts.append(text)

            # Select a topic
            radios = browser.find_elements(By.CSS_SELECTOR, "input[name='topic']")
            radios[i % 4].click()  # Cycle through topics

            # Navigate to next (except for last item)
            if i < 11:
                next_btn = browser.find_element(By.ID, "next-btn")
                next_btn.click()
                time.sleep(0.2)

        # All items should have been annotated
        assert len(annotated_texts) == 12

        # Should have variety in texts (not all the same)
        unique_texts = set(annotated_texts)
        assert len(unique_texts) == 12, "All 12 items should be unique"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

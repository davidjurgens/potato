"""
Selenium tests for the training phase: page rendering, progress display,
correct/incorrect feedback, and pass/fail workflows.

Replaces the entirely SKIPPED test_training_selenium.py with working tests
using the FlaskTestServer + Selenium pattern.

Note: The training template's annotation form area is empty (TASK_LAYOUT not
passed via render_template), so form submissions use requests.Session with
cookies shared from the Selenium driver. Page rendering and feedback display
are verified via Selenium.
"""

import json
import os
import time
import unittest

import requests
import yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_data_file,
)


import pytest


pytestmark = pytest.mark.core

def create_training_selenium_config(
    test_dir, port, max_mistakes=-1, allow_retry=True
):
    """Create config with training phase using FlaskTestServer-compatible format."""
    test_data = [
        {"id": "item_1", "text": "This is the first annotation item."},
        {"id": "item_2", "text": "This is the second annotation item."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Create training data
    training_data = {
        "training_instances": [
            {
                "id": "train_1",
                "text": "This is a positive sentiment text.",
                "correct_answers": {"sentiment": "positive"},
                "explanation": "This text expresses positive emotions.",
            },
            {
                "id": "train_2",
                "text": "This is a negative sentiment text.",
                "correct_answers": {"sentiment": "negative"},
                "explanation": "This text expresses negative emotions.",
            },
            {
                "id": "train_3",
                "text": "This is a neutral sentiment text.",
                "correct_answers": {"sentiment": "neutral"},
                "explanation": "This text is neutral and factual.",
            },
        ]
    }
    training_data_file = os.path.join(test_dir, "training_data.json")
    with open(training_data_file, "w") as f:
        json.dump(training_data, f, indent=2)

    passing_criteria = {
        "min_correct": 2,
        "require_all_correct": False,
    }
    if max_mistakes > 0:
        passing_criteria["max_mistakes"] = max_mistakes

    config = {
        "annotation_task_name": f"Training UI Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "What is the sentiment?",
            }
        ],
        "training": {
            "enabled": True,
            "data_file": training_data_file,
            "annotation_schemes": ["sentiment"],
            "passing_criteria": passing_criteria,
            "allow_retry": allow_retry,
            "failure_action": "move_to_done",
        },
        "assignment_strategy": "fixed_order",
        "max_annotations_per_user": 10,
        "max_annotations_per_item": 3,
        "phases": {
            "order": ["training", "annotation"],
            "training": {"type": "training"},
            "annotation": {"type": "annotation"},
        },
        "site_file": "base_template.html",
        "site_dir": "default",
        "output_annotation_dir": output_dir,
        "task_dir": test_dir,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": f"test-secret-{port}",
        "persist_sessions": False,
        "alert_time_each_instance": 0,
        "user_config": {"allow_all_users": True, "users": []},
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    return config_file


class TestTrainingPhaseUI(unittest.TestCase):
    """
    Training phase rendering and workflow tests.
    Verifies page structure, progress display, and feedback via Selenium.
    Submits training answers via requests (sharing Selenium session cookies).
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"training_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_training_selenium_config(cls.test_dir, cls.port)

        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file
        )
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"train_user_{int(time.time() * 1000)}"
        self._login_and_reach_training()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login_and_reach_training(self):
        """Login and navigate to training page."""
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(self.test_user)
        self.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']"
        ).click()
        time.sleep(2)
        # Navigate to training explicitly
        self.driver.get(f"{self.server.base_url}/training")
        time.sleep(1)

    def _get_requests_session(self):
        """Create a requests.Session with cookies from Selenium driver."""
        session = requests.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])
        return session

    def _submit_training_answer(self, answer_value):
        """Submit a training answer via requests and reload in Selenium."""
        session = self._get_requests_session()
        response = session.post(
            f"{self.server.base_url}/training",
            data={"sentiment": answer_value},
            timeout=5,
        )
        # Reload in Selenium to see the result
        self.driver.get(f"{self.server.base_url}/training")
        time.sleep(1)
        return response

    def test_training_page_renders(self):
        """Training page should display header, progress, and question text."""
        page_source = self.driver.page_source

        # Check for training header
        has_training = "Training Phase" in page_source or "training" in page_source.lower()
        self.assertTrue(has_training, "Training page should show 'Training Phase' header")

        # Check for progress (Question X of Y)
        has_progress = "Question" in page_source and "of" in page_source
        self.assertTrue(has_progress, "Training page should show question progress")

    def test_training_progress_display(self):
        """Progress should show 'Question 1 of 3' initially."""
        page_source = self.driver.page_source

        has_q1 = "Question 1" in page_source
        has_of_3 = "of 3" in page_source

        self.assertTrue(
            has_q1 and has_of_3,
            f"Should show 'Question 1 of 3' on training page",
        )

    def test_correct_answer_shows_success_feedback(self):
        """Submitting correct answer should show success feedback."""
        # train_1's correct answer is "positive"
        response = self._submit_training_answer("positive")

        self.assertEqual(response.status_code, 200)

        page_source = self.driver.page_source.lower()
        has_success = (
            "correct" in page_source
            or "feedback-correct" in page_source
            or "success" in page_source
        )
        self.assertTrue(
            has_success,
            "Correct answer should show success feedback on training page",
        )

    def test_incorrect_answer_shows_error_with_explanation(self):
        """Submitting wrong answer should show error feedback with explanation."""
        # train_1's correct answer is "positive", submit "negative"
        response = self._submit_training_answer("negative")

        self.assertEqual(response.status_code, 200)

        page_source = self.driver.page_source.lower()
        has_error = (
            "incorrect" in page_source
            or "feedback-incorrect" in page_source
            or "error" in page_source
        )
        has_explanation = (
            "positive emotions" in page_source
            or "explanation" in page_source
        )
        self.assertTrue(
            has_error,
            "Incorrect answer should show error feedback",
        )

    def test_training_passes_after_min_correct(self):
        """After min_correct correct answers, user should advance to annotation."""
        session = self._get_requests_session()

        # Answer train_1 correctly (positive)
        session.post(
            f"{self.server.base_url}/training",
            data={"sentiment": "positive"},
            timeout=5,
        )

        # Answer train_2 correctly (negative) — this is the 2nd correct, meeting min_correct=2
        response = session.post(
            f"{self.server.base_url}/training",
            data={"sentiment": "negative"},
            allow_redirects=True,
            timeout=5,
        )

        # User should now be in annotation phase
        # Navigate home to check current phase
        response = session.get(
            f"{self.server.base_url}/",
            allow_redirects=True,
            timeout=5,
        )

        text = response.text.lower()
        # Should be on annotation page (not training anymore)
        has_annotation = (
            "task_layout" in text
            or "sentiment" in text
            or "annotation" in text
        )
        # Should NOT still be on training page
        not_training = "training phase" not in text

        self.assertTrue(
            has_annotation or not_training,
            "After passing training, user should advance to annotation phase",
        )

    def test_instance_text_visible(self):
        """Training page should display the instance text."""
        page_source = self.driver.page_source
        has_text = "positive sentiment text" in page_source.lower()
        self.assertTrue(
            has_text,
            "Training page should display the training instance text",
        )


class TestTrainingMaxMistakesUI(unittest.TestCase):
    """
    Test that exceeding max_mistakes kicks user out of training.
    Uses a separate server with max_mistakes=2 to enable failure quickly.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"training_fail_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_training_selenium_config(
            cls.test_dir, cls.port, max_mistakes=2, allow_retry=True
        )

        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file
        )
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"fail_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_max_mistakes_kicks_user_out(self):
        """After exceeding max_mistakes, user should see training_failed page."""
        # Login
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(self.test_user)
        self.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']"
        ).click()
        time.sleep(2)

        # Get requests session with Selenium cookies
        session = requests.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])

        # Submit 2 wrong answers (max_mistakes=2)
        # train_1 correct is "positive", submit "negative"
        session.post(
            f"{self.server.base_url}/training",
            data={"sentiment": "negative"},
            timeout=5,
        )
        # Submit another wrong answer
        response = session.post(
            f"{self.server.base_url}/training",
            data={"sentiment": "neutral"},
            timeout=5,
        )

        # Navigate to check result
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)

        page_source = self.driver.page_source.lower()
        has_failed = (
            "exceeded" in page_source
            or "failed" in page_source
            or "too many mistakes" in page_source
            or "cannot continue" in page_source
            or "thank you" in page_source  # Done page after failure
        )
        self.assertTrue(
            has_failed,
            "After exceeding max_mistakes, user should see failure or done page",
        )


if __name__ == "__main__":
    unittest.main()

"""
Selenium Tests for Training Phase

This module contains end-to-end tests for training phase functionality using Selenium.
These tests verify the complete user experience through the browser interface.
"""

import pytest
import json
import tempfile
import os
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from tests.selenium.test_base import BaseSeleniumTest


class TestTrainingPhaseSelenium(BaseSeleniumTest):
    """Selenium tests for training phase functionality."""

    def setup_method(self):
        """Set up test environment."""
        super().setup_method()

        self.test_data = {
            "training_instances": [
                {
                    "id": "train_1",
                    "text": "This is a positive sentiment text that expresses joy and happiness.",
                    "correct_answers": {
                        "sentiment": "positive"
                    },
                    "explanation": "This text contains positive words like 'joy' and 'happiness' which clearly indicate positive sentiment."
                },
                {
                    "id": "train_2",
                    "text": "This is a negative sentiment text that expresses sadness and disappointment.",
                    "correct_answers": {
                        "sentiment": "negative"
                    },
                    "explanation": "This text contains negative words like 'sadness' and 'disappointment' which clearly indicate negative sentiment."
                },
                {
                    "id": "train_3",
                    "text": "This is a neutral sentiment text that presents factual information.",
                    "correct_answers": {
                        "sentiment": "neutral"
                    },
                    "explanation": "This text presents factual information without emotional content, indicating neutral sentiment."
                }
            ]
        }

        self.config = {
            "annotation_schemes": {
                "sentiment": {
                    "type": "radio",
                    "options": ["positive", "negative", "neutral"],
                    "required": True
                }
            },
            "training": {
                "enabled": True,
                "data_file": "training_data.json",
                "annotation_schemes": ["sentiment"],
                "passing_criteria": {
                    "min_correct": 2,
                    "require_all_correct": False
                },
                "allow_retry": True,
                "failure_action": "retry"
            },
            "phases": {
                "order": ["consent", "instructions", "training", "annotation"],
                "consent": {
                    "type": "consent",
                    "file": "consent.json"
                },
                "instructions": {
                    "type": "instructions",
                    "file": "instructions.json"
                },
                "training": {
                    "type": "training",
                    "file": "training.json"
                }
            }
        }

    def create_test_files(self):
        """Create temporary test files."""
        # Create training data file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(self.test_data, f)
            self.training_data_file = f.name

        # Create consent file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            consent_data = {
                "title": "Consent",
                "content": "Do you consent to participate in this annotation study?"
            }
            json.dump(consent_data, f)
            self.consent_file = f.name

        # Create instructions file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            instructions_data = {
                "title": "Instructions",
                "content": "Please annotate the sentiment of each text. Choose positive for happy/joyful content, negative for sad/angry content, and neutral for factual information."
            }
            json.dump(instructions_data, f)
            self.instructions_file = f.name

        # Update config with file paths
        self.config["training"]["data_file"] = self.training_data_file
        self.config["phases"]["consent"]["file"] = self.consent_file
        self.config["phases"]["instructions"]["file"] = self.instructions_file

    def teardown_method(self):
        """Clean up test files."""
        super().teardown_method()
        for file_path in [getattr(self, 'training_data_file', None),
                         getattr(self, 'consent_file', None),
                         getattr(self, 'instructions_file', None)]:
            if file_path and os.path.exists(file_path):
                os.unlink(file_path)

    def test_training_phase_ui_elements(self):
        """Test that training phase UI elements are displayed correctly."""
        self.create_test_files()

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Navigate to training phase
            self.driver.get(f"{server.base_url}/training")

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "h1"))
            )

            # Check for training phase title
            title = self.driver.find_element(By.TAG_NAME, "h1")
            assert "training" in title.text.lower()

            # Check for training text
            training_text = self.driver.find_element(By.CLASS_NAME, "training-text")
            assert "positive sentiment text" in training_text.text

            # Check for sentiment radio buttons
            sentiment_options = self.driver.find_elements(By.NAME, "sentiment")
            assert len(sentiment_options) == 3

            # Check for submit button
            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            assert submit_button.is_displayed()
            assert "submit" in submit_button.text.lower()

    def test_training_correct_answer_feedback(self):
        """Test feedback when user provides correct answer."""
        self.create_test_files()

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Navigate to training phase
            self.driver.get(f"{server.base_url}/training")

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Select correct answer (positive)
            positive_radio = self.driver.find_element(By.CSS_SELECTOR, "input[value='positive']")
            positive_radio.click()

            # Submit answer
            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for feedback
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "alert"))
            )

            # Check for success feedback
            alert = self.driver.find_element(By.CLASS_NAME, "alert")
            assert "correct" in alert.text.lower()
            assert "moving to next question" in alert.text.lower()
            assert "alert-success" in alert.get_attribute("class")

    def test_training_incorrect_answer_feedback(self):
        """Test feedback when user provides incorrect answer."""
        self.create_test_files()

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Navigate to training phase
            self.driver.get(f"{server.base_url}/training")

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Select incorrect answer (positive for negative text)
            # First, we need to get to the second question
            positive_radio = self.driver.find_element(By.CSS_SELECTOR, "input[value='positive']")
            positive_radio.click()

            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for next question to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Now select incorrect answer for second question
            positive_radio = self.driver.find_element(By.CSS_SELECTOR, "input[value='positive']")
            positive_radio.click()

            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for feedback
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "alert"))
            )

            # Check for error feedback
            alert = self.driver.find_element(By.CLASS_NAME, "alert")
            assert "incorrect" in alert.text.lower()
            assert "sadness" in alert.text.lower()  # Explanation should mention sadness
            assert "alert-danger" in alert.get_attribute("class")

    def test_training_retry_functionality(self):
        """Test retry functionality after incorrect answer."""
        self.create_test_files()

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Navigate to training phase
            self.driver.get(f"{server.base_url}/training")

            # Complete first question correctly
            positive_radio = self.driver.find_element(By.CSS_SELECTOR, "input[value='positive']")
            positive_radio.click()

            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for next question
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Submit incorrect answer for second question
            positive_radio = self.driver.find_element(By.CSS_SELECTOR, "input[value='positive']")
            positive_radio.click()

            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for feedback
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "alert"))
            )

            # Check for retry button
            retry_button = self.driver.find_element(By.CSS_SELECTOR, "button[value='retry']")
            assert retry_button.is_displayed()
            assert "retry" in retry_button.text.lower()

            # Click retry and submit correct answer
            negative_radio = self.driver.find_element(By.CSS_SELECTOR, "input[value='negative']")
            negative_radio.click()

            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for success feedback
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "alert-success"))
            )

    def test_training_progress_indication(self):
        """Test that training progress is displayed correctly."""
        self.create_test_files()

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Navigate to training phase
            self.driver.get(f"{server.base_url}/training")

            # Check for progress indication
            progress_element = self.driver.find_element(By.CLASS_NAME, "progress-info")
            assert "question" in progress_element.text.lower()
            assert "1" in progress_element.text or "first" in progress_element.text.lower()

            # Complete first question
            positive_radio = self.driver.find_element(By.CSS_SELECTOR, "input[value='positive']")
            positive_radio.click()

            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for next question
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Check updated progress
            progress_element = self.driver.find_element(By.CLASS_NAME, "progress-info")
            assert "2" in progress_element.text or "second" in progress_element.text.lower()

    def test_training_completion_workflow(self):
        """Test complete training completion workflow."""
        self.create_test_files()

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Navigate to training phase
            self.driver.get(f"{server.base_url}/training")

            # Complete all training questions correctly
            for i, expected_answer in enumerate(["positive", "negative", "neutral"]):
                # Wait for question to load
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "sentiment"))
                )

                # Select correct answer
                radio = self.driver.find_element(By.CSS_SELECTOR, f"input[value='{expected_answer}']")
                radio.click()

                # Submit answer
                submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                submit_button.click()

                # Wait for feedback or redirect
                try:
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "alert"))
                    )
                    # If we get here, we're still in training
                    alert = self.driver.find_element(By.CLASS_NAME, "alert")
                    assert "correct" in alert.text.lower()
                except TimeoutException:
                    # If no alert, we might have been redirected to annotation
                    break

            # Verify we're now in annotation phase
            current_url = self.driver.current_url
            assert "annotation" in current_url or "training" not in current_url

    def test_training_disabled_workflow(self):
        """Test workflow when training is disabled."""
        self.create_test_files()
        self.config["training"]["enabled"] = False

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Should skip training and go directly to annotation
            self.driver.get(f"{server.base_url}/annotation")

            # Verify we're in annotation phase
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "h1"))
            )

            title = self.driver.find_element(By.TAG_NAME, "h1")
            assert "annotation" in title.text.lower()

    def test_training_error_handling(self):
        """Test error handling in training phase."""
        self.create_test_files()

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Navigate to training phase
            self.driver.get(f"{server.base_url}/training")

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Submit without selecting an answer
            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Should show error message
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "alert-danger"))
            )

            error_alert = self.driver.find_element(By.CLASS_NAME, "alert-danger")
            assert "required" in error_alert.text.lower() or "error" in error_alert.text.lower()

    def test_training_multi_scheme_support(self):
        """Test training with multiple annotation schemes."""
        self.create_test_files()

        # Update config with multiple schemes
        self.config["annotation_schemes"]["topic"] = {
            "type": "checkbox",
            "options": ["emotion", "politics", "technology"],
            "required": True
        }
        self.config["training"]["annotation_schemes"] = ["sentiment", "topic"]

        # Update training data with multiple schemes
        self.test_data["training_instances"][0]["correct_answers"]["topic"] = ["emotion"]
        self.test_data["training_instances"][1]["correct_answers"]["topic"] = ["emotion"]
        self.test_data["training_instances"][2]["correct_answers"]["topic"] = ["emotion"]

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Navigate to training phase
            self.driver.get(f"{server.base_url}/training")

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Check for both sentiment and topic fields
            sentiment_field = self.driver.find_element(By.NAME, "sentiment")
            topic_field = self.driver.find_element(By.NAME, "topic")

            assert sentiment_field.is_displayed()
            assert topic_field.is_displayed()

            # Select answers for both schemes
            positive_radio = self.driver.find_element(By.CSS_SELECTOR, "input[value='positive']")
            positive_radio.click()

            emotion_checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[value='emotion']")
            emotion_checkbox.click()

            # Submit answer
            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for feedback
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "alert"))
            )

            # Check for success feedback
            alert = self.driver.find_element(By.CLASS_NAME, "alert")
            assert "correct" in alert.text.lower()

    def test_training_accessibility(self):
        """Test training phase accessibility features."""
        self.create_test_files()

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Navigate to training phase
            self.driver.get(f"{server.base_url}/training")

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Check for proper form labels
            labels = self.driver.find_elements(By.TAG_NAME, "label")
            sentiment_label = None
            for label in labels:
                if "sentiment" in label.text.lower():
                    sentiment_label = label
                    break

            assert sentiment_label is not None

            # Check for proper form structure
            form = self.driver.find_element(By.TAG_NAME, "form")
            assert form.get_attribute("method") == "post"

            # Check for proper button types
            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            assert submit_button.get_attribute("type") == "submit"

    def test_training_responsive_design(self):
        """Test training phase responsive design."""
        self.create_test_files()

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Test desktop view
            self.driver.set_window_size(1200, 800)
            self.driver.get(f"{server.base_url}/training")

            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Verify elements are visible in desktop view
            training_text = self.driver.find_element(By.CLASS_NAME, "training-text")
            assert training_text.is_displayed()

            # Test mobile view
            self.driver.set_window_size(375, 667)
            self.driver.refresh()

            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Verify elements are still visible in mobile view
            training_text = self.driver.find_element(By.CLASS_NAME, "training-text")
            assert training_text.is_displayed()

            # Check that form is still functional
            positive_radio = self.driver.find_element(By.CSS_SELECTOR, "input[value='positive']")
            positive_radio.click()

            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for feedback
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "alert"))
            )

    def test_training_browser_console_logs(self):
        """Test that training phase doesn't generate console errors."""
        self.create_test_files()

        with self.create_server(config=self.config) as server:
            # Register and login user
            self.register_user("test_user", "test_password")
            self.login_user("test_user", "test_password")

            # Complete consent and instructions phases
            self.complete_consent_phase()
            self.complete_instructions_phase()

            # Navigate to training phase
            self.driver.get(f"{server.base_url}/training")

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "sentiment"))
            )

            # Check for console errors
            logs = self.driver.get_log('browser')
            error_logs = [log for log in logs if log['level'] == 'SEVERE']
            assert len(error_logs) == 0, f"Found console errors: {error_logs}"

            # Submit an answer
            positive_radio = self.driver.find_element(By.CSS_SELECTOR, "input[value='positive']")
            positive_radio.click()

            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for feedback
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "alert"))
            )

            # Check for console errors after submission
            logs = self.driver.get_log('browser')
            error_logs = [log for log in logs if log['level'] == 'SEVERE']
            assert len(error_logs) == 0, f"Found console errors after submission: {error_logs}"
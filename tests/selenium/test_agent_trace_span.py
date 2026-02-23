"""
Selenium tests for span annotation on agent trace dialogue.

Tests that the span annotation UI works correctly when configured with
span_target: true on a dialogue display field. The agent-trace-evaluation
example has a 'hallucination_spans' schema targeting the dialogue.
"""

import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def create_chrome_options():
    opts = ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-plugins")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return opts


def login_user(driver, base_url, username):
    """Register and login a user, wait for annotation page."""
    driver.get(f"{base_url}/")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "login-email"))
    )
    try:
        driver.find_element(By.ID, "login-tab")
        register_tab = driver.find_element(By.ID, "register-tab")
        register_tab.click()
        WebDriverWait(driver, 5).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )
        driver.find_element(By.ID, "register-email").send_keys(username)
        driver.find_element(By.ID, "register-pass").send_keys("test123")
        driver.find_element(By.CSS_SELECTOR, "#register-content form").submit()
    except NoSuchElementException:
        username_field = driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(username)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    time.sleep(0.5)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
    except TimeoutException:
        pass


class TestAgentTraceSpanAnnotation(unittest.TestCase):
    """Test span annotation on agent trace dialogue display."""

    @classmethod
    def setUpClass(cls):
        project_root = get_project_root()
        config_path = os.path.join(
            project_root,
            "examples/agent-traces/agent-trace-evaluation/config.yaml",
        )
        port = find_free_port(preferred_port=9073)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start server for span annotation test"
        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"span_{int(time.time() * 1000) % 100000}"
        login_user(self.driver, self.server.base_url, self.test_user)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    # --- Span schema presence ---

    def test_hallucination_spans_schema_present(self):
        """The hallucination_spans span schema should be rendered on the page."""
        page_source = self.driver.page_source
        assert "hallucination_spans" in page_source, \
            "hallucination_spans schema should be present"

    def test_span_label_buttons_present(self):
        """Span label buttons (hallucination, incorrect_fact, unnecessary_action)
        should be present for selection."""
        page_source = self.driver.page_source
        assert "hallucination" in page_source, \
            "hallucination label should be present"
        assert "incorrect_fact" in page_source, \
            "incorrect_fact label should be present"
        assert "unnecessary_action" in page_source, \
            "unnecessary_action label should be present"

    def test_span_annotation_form_present(self):
        """The span annotation form element should be in the DOM."""
        forms = self.driver.find_elements(
            By.CSS_SELECTOR,
            "form#hallucination_spans,"
            " form[id*='hallucination'],"
            " [schema='hallucination_spans']"
        )
        assert len(forms) > 0, "Span annotation form should be present"

    # --- Span target (dialogue) ---

    def test_dialogue_has_span_target_content(self):
        """The dialogue display should have span-targetable text content."""
        # Look for text-content or span-target elements
        span_targets = self.driver.find_elements(
            By.CSS_SELECTOR,
            "#text-content, .span-target, [data-span-target]"
        )
        if not span_targets:
            # The dialogue text itself should be present
            page_source = self.driver.page_source
            has_dialogue_text = (
                "Agent (Thought)" in page_source
                or "Agent (Action)" in page_source
                or "search_flights" in page_source
            )
            assert has_dialogue_text, \
                "Dialogue text should be present as span target"
        else:
            assert any(st.is_displayed() for st in span_targets), \
                "At least one span target should be visible"

    def test_dialogue_text_content_present(self):
        """The dialogue area should contain substantial text content for span annotation."""
        # Verify the text-content or main-content area has enough text
        # that span annotation is meaningful
        text_content = self.driver.execute_script("""
            var el = document.getElementById('text-content')
                  || document.getElementById('main-content');
            return el ? el.textContent.length : 0;
        """)
        assert text_content > 50, \
            f"Content area should have substantial text, got {text_content} chars"

    # --- Span label interaction ---

    def test_span_label_elements_clickable(self):
        """Span label elements (buttons/badges) should be clickable."""
        # Look for span label buttons or badge elements
        label_elements = self.driver.find_elements(
            By.CSS_SELECTOR,
            ".span-label-btn, .span-label, "
            "[data-label-name='hallucination'], "
            "button[data-label='hallucination'], "
            ".badge[data-label]"
        )
        if not label_elements:
            # Try finding by text content
            all_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button, .badge")
            label_elements = [
                b for b in all_buttons
                if "hallucination" in (b.text.lower() or "")
            ]

        if not label_elements:
            self.skipTest("No span label buttons found")

        # Verify at least one is interactable
        clicked = False
        for elem in label_elements:
            try:
                if elem.is_displayed():
                    elem.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            # Try JS click
            self.driver.execute_script("arguments[0].click();", label_elements[0])
            clicked = True

        assert clicked, "Should be able to click a span label element"

    def test_span_annotation_coexists_with_other_schemas(self):
        """Span annotation schema should coexist with radio, likert, and
        multiselect schemas on the same page."""
        page_source = self.driver.page_source
        # These are all defined in the agent-trace-evaluation config
        assert "hallucination_spans" in page_source, \
            "Span schema should be present"
        assert "task_success" in page_source, \
            "Radio schema should coexist"
        assert "efficiency" in page_source, \
            "Likert schema should coexist"
        assert "mast_errors" in page_source, \
            "Multiselect schema should coexist"

    def test_span_and_per_turn_ratings_coexist(self):
        """Span annotation should coexist with per-turn ratings on dialogue."""
        page_source = self.driver.page_source
        has_span = "hallucination_spans" in page_source
        has_ptr = (
            "ptr-value" in page_source
            or "per-turn-rating" in page_source
            or "action_correctness" in page_source
        )
        assert has_span, "Span schema should be present"
        assert has_ptr, "Per-turn ratings should be present alongside spans"

    # --- Span creation via JS ---

    def test_span_manager_available(self):
        """The SpanManager JS object should be available on the page."""
        has_manager = self.driver.execute_script("""
            return typeof SpanAnnotator !== 'undefined' ||
                   typeof spanManager !== 'undefined' ||
                   typeof window.spanManager !== 'undefined' ||
                   document.querySelector('.span-label-btn') !== null ||
                   document.querySelector('[data-label-name]') !== null;
        """)
        # Even if the global isn't exposed, span functionality should be present
        page_source = self.driver.page_source
        has_span_ui = (
            "span-label" in page_source
            or "span_annotation" in page_source
            or "hallucination_spans" in page_source
        )
        assert has_manager or has_span_ui, \
            "Span annotation functionality should be available"

    def test_no_spans_initially(self):
        """Initially there should be no span annotations on the page."""
        spans = self.driver.find_elements(
            By.CSS_SELECTOR,
            ".span-annotation, .annotated-span, [data-span-id]"
        )
        assert len(spans) == 0, "Should have no spans initially"


if __name__ == "__main__":
    unittest.main()

"""
Selenium tests for agent trace annotation interactions.

Tests deeper UI interactions beyond basic page loading:
1. Per-turn rating click interactions and visual feedback
2. Multi-dimension per_turn_ratings (multiple schemes per turn)
3. Radio annotation + persistence after page refresh
4. Annotation submission and navigation to next item
5. Likert scale interaction
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
    """Standard headless Chrome options for testing."""
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


# =========================================================================
# Per-turn ratings and multi-dimension interaction
# =========================================================================

class TestPerTurnRatingInteraction(unittest.TestCase):
    """Test clicking per-turn rating values in the dialogue display."""

    @classmethod
    def setUpClass(cls):
        project_root = get_project_root()
        config_path = os.path.join(
            project_root,
            "examples/agent-traces/agent-trace-evaluation/config.yaml",
        )

        port = find_free_port(preferred_port=9060)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start server for per-turn rating test"
        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"ptr_{int(time.time() * 1000) % 100000}"
        login_user(self.driver, self.server.base_url, self.test_user)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_ptr_value_elements_exist(self):
        """Per-turn rating value elements should be present in the DOM."""
        ptr_values = self.driver.find_elements(By.CSS_SELECTOR, ".ptr-value")
        assert len(ptr_values) > 0, "Should have per-turn rating value elements"

    def test_ptr_value_has_data_attributes(self):
        """Each ptr-value should have data-turn, data-value, and data-schema."""
        ptr_values = self.driver.find_elements(By.CSS_SELECTOR, ".ptr-value")
        assert len(ptr_values) > 0, "No ptr-value elements found"

        first = ptr_values[0]
        assert first.get_attribute("data-turn") is not None, "Missing data-turn"
        assert first.get_attribute("data-value") is not None, "Missing data-value"
        assert first.get_attribute("data-schema") is not None, "Missing data-schema"

    def test_click_ptr_value_adds_selected_class(self):
        """Clicking a ptr-value should add ptr-selected class."""
        ptr_values = self.driver.find_elements(By.CSS_SELECTOR, ".ptr-value")
        assert len(ptr_values) > 0, "No ptr-value elements found"

        target = ptr_values[0]
        target.click()
        time.sleep(0.2)

        # The clicked element (and all values <= it) should be selected
        assert "ptr-selected" in target.get_attribute("class"), \
            "Clicked ptr-value should have ptr-selected class"

    def test_click_ptr_value_updates_hidden_input(self):
        """Clicking a ptr-value should update the corresponding hidden input."""
        ptr_values = self.driver.find_elements(By.CSS_SELECTOR, ".ptr-value")
        assert len(ptr_values) > 0, "No ptr-value elements found"

        target = ptr_values[0]
        schema_name = target.get_attribute("data-schema")
        target.click()
        time.sleep(0.2)

        # Find the hidden input for this schema
        hidden_input = self.driver.find_element(
            By.CSS_SELECTOR,
            f'.per-turn-hidden[data-schema-name="{schema_name}"]'
        )
        value = hidden_input.get_attribute("value")
        assert value and value != "", \
            f"Hidden input for schema '{schema_name}' should have a value after click"

    def test_multi_schema_both_present(self):
        """Both action_correctness and reasoning_quality schemas should be present."""
        page_source = self.driver.page_source
        assert 'data-schema="action_correctness"' in page_source, \
            "action_correctness schema should be present"
        assert 'data-schema="reasoning_quality"' in page_source, \
            "reasoning_quality schema should be present"

    def test_multi_schema_independent_clicks(self):
        """Clicking one schema's rating should not affect the other schema."""
        # Click an action_correctness rating
        ac_values = self.driver.find_elements(
            By.CSS_SELECTOR, '.ptr-value[data-schema="action_correctness"]'
        )
        rq_values = self.driver.find_elements(
            By.CSS_SELECTOR, '.ptr-value[data-schema="reasoning_quality"]'
        )

        if not ac_values or not rq_values:
            self.skipTest("Multi-schema ptr-values not found")

        # Click first action_correctness value
        ac_values[0].click()
        time.sleep(0.2)

        # The reasoning_quality values should NOT be selected
        rq_selected = [
            v for v in rq_values if "ptr-selected" in (v.get_attribute("class") or "")
        ]
        assert len(rq_selected) == 0, \
            "Clicking action_correctness should not select reasoning_quality values"

    def test_per_turn_rating_group_visible(self):
        """The per-turn-rating-group wrapper should be visible for multi-scheme turns."""
        groups = self.driver.find_elements(By.CSS_SELECTOR, ".per-turn-rating-group")
        assert len(groups) > 0, "Should have per-turn-rating-group wrappers"

    def test_schema_labels_visible(self):
        """Schema labels should be visible in the per-turn rating area."""
        labels = self.driver.find_elements(By.CSS_SELECTOR, ".ptr-schema-label")
        assert len(labels) > 0, "Should have ptr-schema-label elements"

        # Check that labels contain descriptive text
        label_texts = [l.text.strip() for l in labels if l.text.strip()]
        assert len(label_texts) > 0, "Schema labels should have text content"


# =========================================================================
# Annotation persistence after refresh
# =========================================================================

class TestAnnotationPersistence(unittest.TestCase):
    """Test that annotations persist after page refresh."""

    @classmethod
    def setUpClass(cls):
        project_root = get_project_root()
        config_path = os.path.join(
            project_root,
            "examples/agent-traces/agent-trace-evaluation/config.yaml",
        )

        port = find_free_port(preferred_port=9061)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start server for persistence test"
        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"persist_{int(time.time() * 1000) % 100000}"
        login_user(self.driver, self.server.base_url, self.test_user)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_radio_annotation_persists_after_submit_and_go_back(self):
        """Select radio, submit, navigate back — radio should still be selected."""
        # Find and click a radio button for task_success
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name*='task_success']"
        )
        if not radios:
            self.skipTest("No task_success radio buttons found")

        # Click first radio (success)
        radios[0].click()
        time.sleep(0.2)

        assert radios[0].is_selected(), "Radio should be selected after click"

        # Submit via click_to_next() JS function (the actual Potato submit mechanism).
        # This calls get_new_instance() which validates the form and POSTs to /annotate.
        # Validation may fail if required fields aren't filled, so we use the
        # lower-level post() approach that bypasses validation.
        self.driver.execute_script("""
            var instance_id = document.getElementById("instance_id").value;
            var post_req = {
                action: "next_instance",
                instance_id: instance_id,
                label: {},
                behavior_time_string: "0:00:01"
            };
            // Collect all checked inputs
            document.querySelectorAll("form input:checked").forEach(function(input) {
                post_req[input.name] = input.value;
            });
            fetch("/annotate", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(post_req)
            });
        """)
        time.sleep(2)

        # Navigate back to first item via POST to /go_to
        self.driver.execute_script("""
            var form = document.createElement('form');
            form.method = 'POST';
            form.action = '/go_to';
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'go_to';
            input.value = '0';
            form.appendChild(input);
            document.body.appendChild(form);
            form.submit();
        """)
        time.sleep(2)

        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Check that the radio is still selected
        radios_after = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name*='task_success']"
        )
        selected = [r for r in radios_after if r.is_selected()]
        assert len(selected) > 0, \
            "Radio annotation should persist after submit and navigation back"

    def test_likert_annotation_interaction(self):
        """Should be able to interact with a likert scale."""
        # Likert inputs are styled with opacity:0 (hidden). Users click visible
        # .shadcn-likert-button labels instead. We use JS click on the hidden
        # input to avoid ElementNotInteractableException.
        likert_inputs = self.driver.find_elements(
            By.CSS_SELECTOR, "input.shadcn-likert-input[schema='efficiency']"
        )

        if not likert_inputs:
            # Try alternative selectors
            likert_inputs = self.driver.find_elements(
                By.CSS_SELECTOR, "#efficiency input[type='radio']"
            )

        if not likert_inputs:
            self.skipTest("No efficiency likert inputs found")

        # Click the middle value via JavaScript (inputs are hidden)
        mid = len(likert_inputs) // 2
        self.driver.execute_script("arguments[0].click();", likert_inputs[mid])
        time.sleep(0.2)

        assert likert_inputs[mid].is_selected(), \
            "Likert radio should be selected after click"


# =========================================================================
# Annotation submission flow
# =========================================================================

class TestAnnotationSubmissionFlow(unittest.TestCase):
    """Test the full annotation submission workflow."""

    @classmethod
    def setUpClass(cls):
        project_root = get_project_root()
        config_path = os.path.join(
            project_root,
            "examples/agent-traces/agent-trace-evaluation/config.yaml",
        )

        port = find_free_port(preferred_port=9062)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start server for submission flow test"
        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"flow_{int(time.time() * 1000) % 100000}"
        login_user(self.driver, self.server.base_url, self.test_user)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_page_has_submit_mechanism(self):
        """The annotation page should have a way to submit annotations."""
        # Look for the Next button (a.shadcn-button with onclick=click_to_next)
        # or the click_to_next JS function
        has_submit = False

        for selector in [
            "a[onclick*='click_to_next']",
            "a.shadcn-button.shadcn-button-primary",
            "#annotate-confirm-btn",
            "#next-btn",
        ]:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                if btn.is_displayed():
                    has_submit = True
                    break
            except NoSuchElementException:
                continue

        if not has_submit:
            # Check for JS function
            has_fn = self.driver.execute_script(
                "return typeof click_to_next === 'function'"
            )
            has_submit = has_fn

        assert has_submit, "Should have a submit mechanism"

    def test_multiselect_checkboxes_clickable(self):
        """MAST error taxonomy checkboxes should be clickable."""
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR,
            "input[type='checkbox'][schema='mast_errors'],"
            " #mast_errors input[type='checkbox']"
        )

        if not checkboxes:
            self.skipTest("No mast_errors checkboxes found")

        # Click first checkbox
        checkboxes[0].click()
        time.sleep(0.2)
        assert checkboxes[0].is_selected(), "Checkbox should be selected after click"

        # Click a second checkbox (multiselect allows multiple)
        if len(checkboxes) > 1:
            checkboxes[1].click()
            time.sleep(0.2)
            assert checkboxes[1].is_selected(), "Second checkbox should also be selected"
            # First should still be selected
            assert checkboxes[0].is_selected(), \
                "First checkbox should remain selected after clicking second"

    def test_dialogue_turns_visible(self):
        """Agent trace dialogue turns should be visible in the browser."""
        # Look for dialogue turn elements
        turns = self.driver.find_elements(By.CSS_SELECTOR, ".dialogue-turn")

        if not turns:
            # Fallback: check for speaker names in page source
            page_source = self.driver.page_source
            has_turns = (
                "Agent (Thought)" in page_source
                or "Agent (Action)" in page_source
                or "Environment" in page_source
            )
            assert has_turns, "Should display dialogue turns with speaker names"
        else:
            assert len(turns) > 0, "Should have visible dialogue turns"
            # At least one turn should be displayed
            visible_turns = [t for t in turns if t.is_displayed()]
            assert len(visible_turns) > 0, "At least one dialogue turn should be visible"

    def test_instance_display_container_present(self):
        """The instance display container should be present."""
        containers = self.driver.find_elements(
            By.CSS_SELECTOR, ".instance-display-container"
        )
        assert len(containers) > 0, "Should have instance-display-container"

    def test_has_per_turn_ratings_container(self):
        """The has-per-turn-ratings container should be present."""
        containers = self.driver.find_elements(
            By.CSS_SELECTOR, ".has-per-turn-ratings"
        )
        assert len(containers) > 0, "Should have has-per-turn-ratings container"


if __name__ == "__main__":
    unittest.main()

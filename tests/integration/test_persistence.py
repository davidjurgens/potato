"""
Persistence tests for Potato Annotation Platform.

These tests verify that annotation state is correctly preserved across
various scenarios:
1. Navigation between instances
2. Browser refresh
3. Go-to navigation
4. Session timeout and recovery
5. Annotation modifications

These tests are critical for ensuring annotators don't lose their work.
"""

import pytest
import time
import sys
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.integration.base import IntegrationTestServer


# ==================== Helper Functions ====================

def register_user(browser, server, test_user):
    """Register user and wait for annotation page."""
    browser.get(server.base_url)
    time.sleep(1)

    register_tab = WebDriverWait(browser, 10).until(
        EC.element_to_be_clickable((By.ID, "register-tab"))
    )
    register_tab.click()
    time.sleep(0.5)

    WebDriverWait(browser, 5).until(
        EC.visibility_of_element_located((By.ID, "register-content"))
    )

    username_field = browser.find_element(By.ID, "register-email")
    password_field = browser.find_element(By.ID, "register-pass")

    username_field.clear()
    username_field.send_keys(test_user["username"])
    password_field.clear()
    password_field.send_keys(test_user["password"])

    register_form = browser.find_element(By.CSS_SELECTOR, "#register-content form")
    register_form.submit()

    WebDriverWait(browser, 15).until(
        lambda d: "main-content" in d.page_source
    )
    time.sleep(1)


def get_checkbox_states(browser):
    """Get current state of all checkboxes."""
    checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
    states = {}
    for cb in checkboxes:
        label = cb.get_attribute("label_name") or cb.get_attribute("value") or cb.get_attribute("id")
        if label:
            states[label] = cb.is_selected()
    return states


def get_radio_selection(browser):
    """Get currently selected radio button."""
    radios = browser.find_elements(By.CSS_SELECTOR, "input[type='radio']")
    for radio in radios:
        if radio.is_selected():
            return radio.get_attribute("label_name") or radio.get_attribute("value")
    return None


# ==================== Navigation Persistence Tests ====================

@pytest.mark.persistence
class TestNavigationPersistence:
    """Test that annotations persist across navigation."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_annotation_survives_next_prev_navigation(self, server, browser, test_user):
        """Test that annotation persists when navigating next and then back."""
        register_user(browser, server, test_user)

        # Make an annotation on instance 1
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if not checkboxes:
            pytest.skip("No checkboxes found")

        checkbox = checkboxes[0]
        checkbox_label = checkbox.get_attribute("label_name") or checkbox.get_attribute("value")

        browser.execute_script("arguments[0].click();", checkbox)
        time.sleep(0.5)

        # Verify it's selected
        assert checkbox.is_selected(), "Checkbox should be selected"

        # Navigate to next instance
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
        time.sleep(2)

        # Navigate back to previous instance
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_LEFT)
        time.sleep(2)

        # Find the same checkbox and verify it's still selected
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        checkbox = None
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            if label == checkbox_label:
                checkbox = cb
                break

        assert checkbox is not None, f"Could not find checkbox with label {checkbox_label}"
        assert checkbox.is_selected(), "Annotation should persist after navigation"

    def test_multiple_annotations_persist(self, server, browser, test_user):
        """Test that multiple checkbox selections persist."""
        register_user(browser, server, test_user)

        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if len(checkboxes) < 2:
            pytest.skip("Need at least 2 checkboxes")

        # Select multiple checkboxes
        selected_labels = []
        for cb in checkboxes[:2]:
            browser.execute_script("arguments[0].click();", cb)
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            selected_labels.append(label)
            time.sleep(0.3)

        # Navigate away and back
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
        time.sleep(2)
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_LEFT)
        time.sleep(2)

        # Verify all selections persist
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            if label in selected_labels:
                assert cb.is_selected(), f"Checkbox {label} should still be selected"


# ==================== Browser Refresh Persistence Tests ====================

@pytest.mark.persistence
class TestBrowserRefreshPersistence:
    """Test that annotations persist across browser refresh."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_session_survives_refresh(self, server, browser, test_user):
        """Test that user session survives browser refresh."""
        register_user(browser, server, test_user)

        # Verify on annotation page
        assert "main-content" in browser.page_source

        # Refresh browser
        browser.refresh()
        time.sleep(2)

        # Should still be on annotation page (session preserved)
        assert "main-content" in browser.page_source, \
            "Session should be preserved after browser refresh"

    def test_annotation_survives_refresh(self, server, browser, test_user):
        """Test that annotation survives browser refresh."""
        register_user(browser, server, test_user)

        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if not checkboxes:
            pytest.skip("No checkboxes found")

        # Make annotation
        checkbox = checkboxes[0]
        checkbox_label = checkbox.get_attribute("label_name") or checkbox.get_attribute("value")
        browser.execute_script("arguments[0].click();", checkbox)
        time.sleep(0.5)

        # Refresh browser
        browser.refresh()
        time.sleep(2)

        # Find checkbox and verify still selected
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            if label == checkbox_label:
                assert cb.is_selected(), "Annotation should survive browser refresh"
                return

        pytest.fail(f"Could not find checkbox {checkbox_label} after refresh")


# ==================== Go-To Navigation Persistence Tests ====================

@pytest.mark.persistence
class TestGoToNavigationPersistence:
    """Test that annotations persist when using go-to navigation."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    @pytest.mark.xfail(reason="Known persistence issue")
    def test_annotation_survives_go_to_navigation(self, server, browser, test_user):
        """Test that annotation persists when using go-to input."""
        register_user(browser, server, test_user)

        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if not checkboxes:
            pytest.skip("No checkboxes found")

        # Make annotation
        checkbox = checkboxes[0]
        checkbox_label = checkbox.get_attribute("label_name") or checkbox.get_attribute("value")
        browser.execute_script("arguments[0].click();", checkbox)
        time.sleep(0.5)

        # Try to find go-to input
        go_to_inputs = browser.find_elements(By.ID, "go_to")
        if not go_to_inputs:
            pytest.skip("No go-to input found")

        go_to = go_to_inputs[0]

        # Navigate to instance 3
        go_to.clear()
        go_to.send_keys("3")
        go_to.send_keys(Keys.RETURN)
        time.sleep(2)

        # Navigate back to instance 1
        go_to = browser.find_element(By.ID, "go_to")
        go_to.clear()
        go_to.send_keys("1")
        go_to.send_keys(Keys.RETURN)
        time.sleep(2)

        # Verify annotation persists
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            if label == checkbox_label:
                assert cb.is_selected(), "Annotation should survive go-to navigation"
                return

        pytest.fail(f"Could not find checkbox {checkbox_label}")


# ==================== Annotation Modification Tests ====================

@pytest.mark.persistence
class TestAnnotationModification:
    """Test that annotation modifications are handled correctly."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with checkbox config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-check-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_checkbox_can_be_toggled_off(self, server, browser, test_user):
        """Test that checkboxes can be toggled off after being checked."""
        register_user(browser, server, test_user)

        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if not checkboxes:
            pytest.skip("No checkboxes found")

        checkbox = checkboxes[0]

        # Toggle on
        browser.execute_script("arguments[0].click();", checkbox)
        time.sleep(0.3)
        assert checkbox.is_selected(), "Checkbox should be selected"

        # Toggle off
        browser.execute_script("arguments[0].click();", checkbox)
        time.sleep(0.3)
        assert not checkbox.is_selected(), "Checkbox should be deselected"

    @pytest.mark.xfail(reason="Known persistence issue")
    def test_modified_annotation_overwrites_previous(self, server, browser, test_user):
        """Test that modifying an annotation overwrites the previous value."""
        register_user(browser, server, test_user)

        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if len(checkboxes) < 2:
            pytest.skip("Need at least 2 checkboxes")

        # Select first checkbox
        first_label = checkboxes[0].get_attribute("label_name") or checkboxes[0].get_attribute("value")
        browser.execute_script("arguments[0].click();", checkboxes[0])
        time.sleep(0.3)

        # Navigate away and back
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
        time.sleep(2)
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_LEFT)
        time.sleep(2)

        # Deselect first checkbox, select second
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            if label == first_label:
                browser.execute_script("arguments[0].click();", cb)  # Deselect
                break

        second_label = checkboxes[1].get_attribute("label_name") or checkboxes[1].get_attribute("value")
        browser.execute_script("arguments[0].click();", checkboxes[1])
        time.sleep(0.3)

        # Navigate away and back again
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
        time.sleep(2)
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_LEFT)
        time.sleep(2)

        # Verify only second checkbox is selected
        checkboxes = browser.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            if label == first_label:
                assert not cb.is_selected(), "First checkbox should be deselected"
            elif label == second_label:
                assert cb.is_selected(), "Second checkbox should be selected"


# ==================== Radio Button Persistence Tests ====================

@pytest.mark.persistence
class TestRadioButtonPersistence:
    """Test that radio button selections persist correctly."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with single choice config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-single-choice-selection.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    def test_radio_selection_persists(self, server, browser, test_user):
        """Test that radio button selection persists after navigation."""
        register_user(browser, server, test_user)

        radios = browser.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        if not radios:
            pytest.skip("No radio buttons found")

        # Select a radio button
        radio = radios[0]
        radio_label = radio.get_attribute("label_name") or radio.get_attribute("value")
        browser.execute_script("arguments[0].click();", radio)
        time.sleep(0.5)

        # Navigate away and back
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
        time.sleep(2)
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_LEFT)
        time.sleep(2)

        # Find the radio and verify it's still selected
        radios = browser.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        for r in radios:
            label = r.get_attribute("label_name") or r.get_attribute("value")
            if label == radio_label:
                assert r.is_selected(), "Radio selection should persist"
                return

        pytest.fail(f"Could not find radio button {radio_label}")


# ==================== Text Input Persistence Tests ====================

@pytest.mark.persistence
class TestTextInputPersistence:
    """Test that text input annotations persist correctly."""

    @pytest.fixture
    def server(self, base_port):
        """Start server with text box config."""
        config_path = PROJECT_ROOT / "project-hub" / "simple_examples" / "configs" / "simple-text-box.yaml"
        server = IntegrationTestServer(str(config_path), port=base_port)
        success, error = server.start()
        if not success:
            pytest.skip(f"Server failed to start: {error}")
        yield server
        server.stop()

    @pytest.mark.xfail(reason="Known persistence issue")
    def test_text_input_persists(self, server, browser, test_user):
        """Test that text input content persists after navigation."""
        register_user(browser, server, test_user)

        text_inputs = browser.find_elements(By.CSS_SELECTOR, "input[type='text'], textarea")
        visible_input = None
        for inp in text_inputs:
            if inp.is_displayed():
                visible_input = inp
                break

        if not visible_input:
            pytest.skip("No visible text input found")

        # Type some text
        test_text = "Test persistence text"
        visible_input.clear()
        visible_input.send_keys(test_text)
        time.sleep(0.5)

        # Navigate away and back
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_RIGHT)
        time.sleep(2)
        browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_LEFT)
        time.sleep(2)

        # Find the text input and verify content
        text_inputs = browser.find_elements(By.CSS_SELECTOR, "input[type='text'], textarea")
        for inp in text_inputs:
            if inp.is_displayed():
                assert inp.get_attribute("value") == test_text, \
                    "Text input content should persist"
                return

        pytest.fail("Could not find visible text input after navigation")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])

"""
Tests for blocked user UI behavior (Issue #152).

When a user is blocked due to attention check failures, the error state
should show a "Finish" link instead of a "Retry" button to prevent the
confusing loop where retrying just re-triggers the block.
"""

import os
import pytest


class TestBlockedUserErrorState:
    """Verify the error state template supports permanent block behavior."""

    @pytest.fixture(autouse=True)
    def load_template(self):
        """Load the base template HTML for inspection."""
        template_path = os.path.join(
            os.path.dirname(__file__), "../../potato/templates/base_template_v2.html"
        )
        with open(template_path, "r") as f:
            self.template_html = f.read()

    def test_error_state_has_retry_button_with_id(self):
        """The retry button should have an id so JS can hide it for permanent blocks."""
        assert 'id="error-retry-btn"' in self.template_html

    def test_error_state_has_done_link(self):
        """There should be a hidden 'Finish' link for permanent blocks."""
        assert 'id="error-done-link"' in self.template_html

    def test_done_link_points_to_done_page(self):
        """The done link should navigate to the /done endpoint."""
        assert 'href="/done"' in self.template_html

    def test_done_link_initially_hidden(self):
        """The done link should be hidden by default (only shown for permanent blocks)."""
        # Find the done link line and check it has display: none
        lines = self.template_html.split("\n")
        for line in lines:
            if 'id="error-done-link"' in line:
                assert 'display: none' in line or "display:none" in line
                break
        else:
            pytest.fail("error-done-link element not found in template")


class TestBlockedUserJavaScript:
    """Verify the annotation.js handles permanent blocks correctly."""

    @pytest.fixture(autouse=True)
    def load_js(self):
        """Load annotation.js for inspection."""
        js_path = os.path.join(
            os.path.dirname(__file__), "../../potato/static/annotation.js"
        )
        with open(js_path, "r") as f:
            self.js_code = f.read()

    def test_show_error_accepts_options_parameter(self):
        """showError() should accept an options parameter for permanent blocks."""
        assert "function showError(show, message" in self.js_code
        assert "options" in self.js_code.split("function showError")[1].split("{")[0]

    def test_show_error_handles_permanent_flag(self):
        """showError() should check options.permanent to toggle retry vs done."""
        # Find the showError function body
        start = self.js_code.index("function showError")
        # Look for permanent handling within the function
        func_body = self.js_code[start:start + 1000]
        assert "permanent" in func_body
        assert "error-retry-btn" in func_body
        assert "error-done-link" in func_body

    def test_handle_quality_control_passes_permanent_for_block(self):
        """handleQualityControlResponse() should pass permanent:true when blocked."""
        start = self.js_code.index("function handleQualityControlResponse")
        func_body = self.js_code[start:start + 800]
        assert "permanent" in func_body
        assert "true" in func_body

    def test_annotation_forms_have_submit_prevention(self):
        """annotation.js should prevent default form submission on annotation forms."""
        assert "annotation-form" in self.js_code
        assert "preventDefault" in self.js_code

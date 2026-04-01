"""Unit tests for the trajectory_eval schema generator."""

import pytest
from potato.server_utils.schemas.trajectory_eval import generate_trajectory_eval_layout
from potato.server_utils.schemas.registry import schema_registry


class TestTrajectoryEvalSchema:
    """Test trajectory_eval HTML generation."""

    def _make_scheme(self, **overrides):
        base = {
            "annotation_type": "trajectory_eval",
            "name": "step_eval",
            "description": "Evaluate steps",
            "steps_key": "steps",
            "step_text_key": "action",
            "error_types": [
                {"name": "reasoning", "subtypes": ["logical_error", "factual_error"]},
                {"name": "execution"},
            ],
            "severities": [
                {"name": "minor", "weight": -1},
                {"name": "major", "weight": -5},
            ],
        }
        base.update(overrides)
        return base

    def test_generates_html_and_empty_keybindings(self):
        html, keybindings = generate_trajectory_eval_layout(self._make_scheme())
        assert isinstance(html, str)
        assert isinstance(keybindings, list)
        assert len(keybindings) == 0  # no keyboard shortcuts

    def test_html_contains_form_and_hidden_input(self):
        html, _ = generate_trajectory_eval_layout(self._make_scheme())
        assert 'class="annotation-form trajectory-eval-container"' in html
        assert 'class="annotation-input trajectory-eval-data-input"' in html

    def test_html_contains_data_attributes(self):
        html, _ = generate_trajectory_eval_layout(self._make_scheme())
        assert 'data-annotation-type="trajectory_eval"' in html
        assert 'data-schema-name="step_eval"' in html
        assert 'data-steps-key="steps"' in html

    def test_html_contains_error_type_options(self):
        html, _ = generate_trajectory_eval_layout(self._make_scheme())
        assert "logical_error" in html
        assert "factual_error" in html
        assert "execution" in html

    def test_html_contains_severity_radios(self):
        html, _ = generate_trajectory_eval_layout(self._make_scheme())
        assert "minor" in html
        assert "major" in html
        assert "-1" in html
        assert "-5" in html

    def test_html_contains_correctness_buttons(self):
        html, _ = generate_trajectory_eval_layout(self._make_scheme())
        assert "Correct" in html
        assert "Incorrect" in html
        assert "Partially Correct" in html

    def test_custom_correctness_options(self):
        html, _ = generate_trajectory_eval_layout(
            self._make_scheme(correctness_options=["good", "bad"])
        )
        assert "Good" in html
        assert "Bad" in html

    def test_score_display_shown_by_default(self):
        html, _ = generate_trajectory_eval_layout(self._make_scheme())
        assert "step_eval-score" in html

    def test_score_display_hidden_when_disabled(self):
        html, _ = generate_trajectory_eval_layout(self._make_scheme(show_score=False))
        assert "step_eval-score" not in html

    def test_iife_script_present(self):
        html, _ = generate_trajectory_eval_layout(self._make_scheme())
        assert "<script>" in html
        assert "window._trajState" in html
        assert "restoreFromHiddenInput" in html

    def test_description_escaped(self):
        html, _ = generate_trajectory_eval_layout(
            self._make_scheme(description="Test <script>alert(1)</script>")
        )
        assert "<script>alert(1)</script>" not in html.split("<script>")[0]


class TestTrajectoryEvalRegistration:
    """Test trajectory_eval is properly registered."""

    def test_in_registry(self):
        assert schema_registry.is_registered("trajectory_eval")

    def test_generate_via_registry(self):
        scheme = {
            "annotation_type": "trajectory_eval",
            "name": "test_traj",
            "description": "Test",
        }
        html, keybindings = schema_registry.generate(scheme)
        assert "trajectory-eval-container" in html

    def test_in_supported_types(self):
        assert "trajectory_eval" in schema_registry.get_supported_types()

    def test_in_config_valid_types(self):
        from potato.server_utils.config_module import validate_single_annotation_scheme
        # Should not raise for trajectory_eval type
        scheme = {
            "annotation_type": "trajectory_eval",
            "name": "test",
            "description": "Test",
        }
        # Just verify it doesn't raise on the type check
        # (may raise on other missing fields, which is fine)
        try:
            validate_single_annotation_scheme(scheme, "test")
        except Exception as e:
            # Should not be "unsupported annotation type"
            assert "annotation_type must be one of" not in str(e)

"""Unit tests for the process_reward annotation schema."""

import pytest
from potato.server_utils.schemas.process_reward import generate_process_reward_layout


class TestProcessRewardSchema:
    """Tests for generate_process_reward_layout()."""

    def _make_scheme(self, **kwargs):
        base = {
            "name": "test_prm",
            "description": "Test PRM schema",
            "annotation_type": "process_reward",
            "steps_key": "structured_turns",
            "mode": "first_error",
        }
        base.update(kwargs)
        return base

    def test_generates_html(self):
        html, kb = generate_process_reward_layout(self._make_scheme())
        assert isinstance(html, str)
        assert len(html) > 0
        assert isinstance(kb, list)

    def test_contains_container(self):
        html, _ = generate_process_reward_layout(self._make_scheme())
        assert "process-reward-container" in html
        assert "test_prm" in html

    def test_contains_hidden_input(self):
        html, _ = generate_process_reward_layout(self._make_scheme())
        assert "process-reward-data-input" in html
        assert 'type="hidden"' in html

    def test_first_error_mode_label(self):
        html, _ = generate_process_reward_layout(self._make_scheme(mode="first_error"))
        assert "First Error" in html
        assert "click the first incorrect step" in html

    def test_per_step_mode_label(self):
        html, _ = generate_process_reward_layout(self._make_scheme(mode="per_step"))
        assert "Per Step" in html
        assert "rate each step independently" in html

    def test_contains_reset_button(self):
        html, _ = generate_process_reward_layout(self._make_scheme())
        assert "Reset All" in html
        assert "prm-reset-btn" in html

    def test_contains_steps_container(self):
        html, _ = generate_process_reward_layout(self._make_scheme())
        assert "prm-steps-container" in html

    def test_iife_script(self):
        html, _ = generate_process_reward_layout(self._make_scheme())
        assert "<script>" in html
        assert "buildCards" in html
        assert "saveState" in html
        assert "data-modified" in html

    def test_css_styles(self):
        html, _ = generate_process_reward_layout(self._make_scheme())
        assert "<style>" in html
        assert ".prm-step-card" in html
        assert ".prm-btn-correct" in html
        assert ".prm-btn-incorrect" in html

    def test_custom_schema_name(self):
        html, _ = generate_process_reward_layout(self._make_scheme(name="my_rewards"))
        assert "my_rewards" in html

    def test_custom_steps_key(self):
        html, _ = generate_process_reward_layout(self._make_scheme(steps_key="steps"))
        assert '"steps_key": "steps"' in html

    def test_no_keybindings(self):
        _, kb = generate_process_reward_layout(self._make_scheme())
        assert kb == []


class TestProcessRewardNeutral:
    """Three-way (correct/neutral/incorrect) PRM800K-style labeling."""

    def _make_scheme(self, **kwargs):
        base = {
            "name": "test_prm",
            "description": "Test PRM schema",
            "annotation_type": "process_reward",
            "steps_key": "steps",
            "mode": "per_step",
            "allow_neutral": True,
        }
        base.update(kwargs)
        return base

    def test_neutral_disabled_by_default(self):
        # The runtime gate is CONFIG.allow_neutral (the class name string is
        # always present in the JS source, so we assert on the flag).
        scheme = self._make_scheme()
        del scheme["allow_neutral"]
        html, _ = generate_process_reward_layout(scheme)
        assert '"allow_neutral": false' in html

    def test_neutral_enabled_in_per_step(self):
        html, _ = generate_process_reward_layout(self._make_scheme())
        assert '"allow_neutral": true' in html
        # The unmarked sentinel must be null so neutral(0) is distinguishable.
        assert "var UNMARKED = NEUTRAL ? null : 0;" in html

    def test_neutral_forced_off_in_first_error_mode(self):
        # Neutral makes no sense for the first-error cascade and must be ignored.
        html, _ = generate_process_reward_layout(
            self._make_scheme(mode="first_error"))
        assert '"allow_neutral": false' in html

    def test_neutral_styling_present(self):
        html, _ = generate_process_reward_layout(self._make_scheme())
        assert "prm-neutral" in html
        assert "prm-status-neutral" in html
        assert "prm-count-neutral" in html

    def test_mode_label_mentions_neutral(self):
        html, _ = generate_process_reward_layout(self._make_scheme())
        assert "neutral" in html.lower()


class TestProcessRewardRegistration:
    """Test schema registry integration."""

    def test_registered(self):
        from potato.server_utils.schemas.registry import schema_registry
        assert "process_reward" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        from potato.server_utils.schemas.registry import schema_registry
        html, kb = schema_registry.generate({
            "annotation_type": "process_reward",
            "name": "reg_test",
            "description": "Registry test",
        })
        assert "process-reward-container" in html

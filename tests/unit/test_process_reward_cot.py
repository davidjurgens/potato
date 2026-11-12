"""Unit tests for the process_reward AI pre-label / verification extension.

The base process_reward behavior is covered by test_process_reward_schema.py;
this file focuses on the ai_prelabel / reward_labels / verification additions.
"""

import pytest

from potato.server_utils.schemas.process_reward import generate_process_reward_layout


def _gen(**overrides):
    scheme = {
        "name": "step_rewards",
        "description": "Rate each step",
        "annotation_type": "process_reward",
        "steps_key": "cot_steps",
        "mode": "per_step",
    }
    scheme.update(overrides)
    html, kb = generate_process_reward_layout(scheme)
    return html


class TestAiPrelabelHtml:
    def test_ai_bar_present_when_enabled(self):
        html = _gen(ai_prelabel=True)
        assert 'id="step_rewards-ai-prelabel"' in html
        assert 'id="step_rewards-ai-accept"' in html
        assert "/api/prm/prelabel" in html

    def test_ai_bar_absent_by_default(self):
        html = _gen()
        assert "step_rewards-ai-prelabel" not in html

    def test_verification_helpers_present(self):
        html = _gen(ai_prelabel=True)
        for fn in ("makeStep", "isAiPending", "applyHumanMark",
                   "bindAiControls", "applyAiSuggestions", "acceptAllAi"):
            assert fn in html

    def test_reward_labels_override(self):
        html = _gen(allow_neutral=True, reward_labels={"correct": "Valid", "incorrect": "Flawed"})
        assert "Valid" in html
        assert "Flawed" in html

    def test_cot_trace_scope_added(self):
        html = _gen(ai_prelabel=True, inline_with_trace=True)
        assert "cot-trace-display" in html

    def test_require_verification_flag_in_config(self):
        html = _gen(ai_prelabel=True, require_verification=True)
        assert '"require_verification": true' in html

    def test_ai_badge_markup(self):
        html = _gen(ai_prelabel=True)
        assert "prm-ai-badge" in html
        assert "prm-ai-pending" in html


class TestBackwardCompatibility:
    def test_legacy_config_still_generates(self):
        # No new keys at all — must still produce a working widget.
        html = _gen(mode="first_error")
        assert "process-reward-container" in html
        assert "step_rewards-ai-prelabel" not in html

    def test_makeStep_handles_old_blob_shape(self):
        # The restore path must treat an old {index,reward} entry as a verified
        # human label (documented invariant). We assert the guard code exists.
        html = _gen(ai_prelabel=True)
        assert "saved.verified !== undefined" in html
        assert "'human'" in html

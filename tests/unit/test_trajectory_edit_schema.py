"""
Unit tests for the trajectory_edit annotation schema (HTML generation).
"""

import re

import pytest

from potato.server_utils.schemas.trajectory_edit import generate_trajectory_edit_layout
from potato.server_utils.schemas.registry import schema_registry


BASE = {
    "annotation_type": "trajectory_edit",
    "name": "fix",
    "description": "Correct the trace",
}


def gen(**overrides):
    scheme = dict(BASE)
    scheme.update(overrides)
    html, kb = generate_trajectory_edit_layout(scheme)
    return html, kb


def strip_script(html: str) -> str:
    """Remove the <script> block so markup assertions don't match JS source."""
    return re.sub(r"<script>.*?</script>", "", html, flags=re.DOTALL)


class TestRegistration:
    def test_registered(self):
        assert "trajectory_edit" in schema_registry.get_supported_types()

    def test_generates_via_registry(self):
        html, _ = schema_registry.generate(dict(BASE))
        assert "trajectory-edit-container" in html


class TestStructure:
    def test_core_markup_present(self):
        html, kb = gen()
        assert kb == []
        for needle in [
            "trajectory-edit-container",
            "trajedit-steps-container",
            "trajectory-edit-data-input",
            'data-annotation-type="trajectory_edit"',
            'data-steps-key="steps"',
            'data-step-text-key="action"',
        ]:
            assert needle in html, f"missing {needle}"

    def test_config_serialized_for_js(self):
        html, _ = gen(steps_key="trace", step_text_key="text",
                      editable_fields=["text", "thought"])
        assert '"steps_key": "trace"' in html
        assert '"editable_fields": ["text", "thought"]' in html

    def test_iife_overwrite_guard_present(self):
        # The restore-before-build guard and data-server-set check must exist.
        html, _ = gen()
        assert "restoreFromHiddenInput" in html
        assert "data-server-set" in html
        # restore is invoked before building editors
        assert "var hadServerData = restoreFromHiddenInput();" in html

    def test_summary_counters_present(self):
        html, _ = gen()
        assert "fix-n-edited" in html
        assert "fix-total-dist" in html


class TestOptions:
    def test_final_answer_editor_toggle(self):
        on, _ = gen(edit_final_answer=True)
        off, _ = gen(edit_final_answer=False)
        assert '"edit_final_answer": true' in on
        assert '"edit_final_answer": false' in off

    def test_diff_and_distance_flags(self):
        html, _ = gen(show_diff=False, show_edit_distance=False)
        assert '"show_diff": false' in html
        assert '"show_edit_distance": false' in html

    def test_reason_flag(self):
        html, _ = gen(require_reason_on_edit=True)
        assert '"require_reason_on_edit": true' in html

    def test_editable_fields_defaults_to_step_text_key(self):
        html, _ = gen(step_text_key="cmd")
        assert '"editable_fields": ["cmd"]' in html

    def test_non_list_editable_fields_coerced(self):
        html, _ = gen(editable_fields="oops", step_text_key="action")
        assert '"editable_fields": ["action"]' in html


class TestEscaping:
    def test_description_escaped(self):
        html, _ = gen(description="<script>alert('x')</script>")
        body = strip_script(html)
        assert "<script>alert" not in body
        assert "&lt;script&gt;" in body

    def test_name_escaped_in_attributes(self):
        # A malicious schema name must not break out of attributes.
        html, _ = gen(name='x"><img src=y>')
        assert "<img src=y>" not in html

    def test_steps_key_escaped(self):
        html, _ = gen(steps_key='s"><b>')
        body = strip_script(html)
        assert "<b>" not in body


class TestValidation:
    def test_missing_required_returns_error_layout(self):
        # safe_generate_layout wraps errors; missing description should not crash.
        html, kb = generate_trajectory_edit_layout(
            {"annotation_type": "trajectory_edit", "name": "x"}
        )
        assert isinstance(html, str)

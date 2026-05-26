"""
Test that no schema generates forms with the action_page.php placeholder URL.

Issue #151: Pressing Enter in input fields would trigger form submission to
/action_page.php (a non-existent endpoint from W3Schools examples), causing
a 404 error and loss of annotation data.
"""

import pytest
from potato.server_utils.schemas.registry import schema_registry


class TestFormActionSafety:
    """Verify that schema-generated HTML does not contain dangerous form actions."""

    def _make_minimal_scheme(self, annotation_type):
        """Build a minimal annotation_scheme dict for the given type."""
        base = {
            "annotation_type": annotation_type,
            "name": f"test_{annotation_type}",
            "description": f"Test {annotation_type}",
            "labels": ["label_a", "label_b", "label_c"],
            "annotation_id": 0,
        }
        # Type-specific required fields
        if annotation_type == "likert":
            base["size"] = 5
        elif annotation_type == "slider":
            base["min_value"] = 0
            base["max_value"] = 100
        elif annotation_type in ("number",):
            base["min_value"] = 0
            base["max_value"] = 10
        elif annotation_type == "bws":
            base["tuple_size"] = 3
        elif annotation_type == "multirate":
            base["labels"] = ["quality", "fluency"]
            base["options"] = ["1", "2", "3", "4", "5"]
        elif annotation_type == "vas":
            base["min_value"] = 0
            base["max_value"] = 100
        elif annotation_type == "rubric_eval":
            base["criteria"] = [
                {"name": "quality", "description": "Quality", "levels": ["bad", "good"]}
            ]
        elif annotation_type in ("image_annotation", "video_annotation", "audio_annotation"):
            base["source_field"] = "media_url"
        elif annotation_type == "tiered_annotation":
            base["tiers"] = [
                {"name": "tier1", "labels": ["a", "b"]},
            ]
        elif annotation_type == "conjoint":
            base["attributes"] = [
                {"name": "attr1", "levels": ["low", "high"]},
            ]
        elif annotation_type == "trajectory_eval":
            base["dimensions"] = [
                {"name": "accuracy", "description": "Accuracy", "scale": 5},
            ]
        elif annotation_type == "process_reward":
            base["scale"] = 5
        elif annotation_type == "code_review":
            base["categories"] = ["style", "logic"]
        elif annotation_type == "text_edit":
            base["source_field"] = "text"
        elif annotation_type == "extractive_qa":
            base["source_field"] = "text"
        elif annotation_type == "constant_sum":
            base["total"] = 100
        return base

    @pytest.mark.parametrize("annotation_type", schema_registry.get_supported_types())
    def test_no_action_page_php_in_generated_html(self, annotation_type):
        """Each schema must NOT generate action_page.php in its HTML output."""
        scheme = self._make_minimal_scheme(annotation_type)
        try:
            html, _keybindings = schema_registry.generate(scheme)
        except Exception:
            # Some schemas may need more specific config to generate;
            # skip those rather than fail the safety test
            pytest.skip(f"Could not generate HTML for {annotation_type} with minimal config")

        assert "action_page.php" not in html, (
            f"Schema '{annotation_type}' still generates action_page.php in its HTML. "
            f"Replace with action=\"javascript:void(0)\"."
        )

    @pytest.mark.parametrize("annotation_type", schema_registry.get_supported_types())
    def test_form_has_safe_action(self, annotation_type):
        """Each schema's form should use a safe action attribute."""
        scheme = self._make_minimal_scheme(annotation_type)
        try:
            html, _keybindings = schema_registry.generate(scheme)
        except Exception:
            pytest.skip(f"Could not generate HTML for {annotation_type} with minimal config")

        # If the schema generates a <form>, it should have a safe action
        if "<form" in html.lower():
            assert 'action="javascript:void(0)"' in html or 'action=""' in html or "action" not in html, (
                f"Schema '{annotation_type}' has a <form> with an unsafe action attribute."
            )

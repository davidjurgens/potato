"""
Unit tests for Text Edit annotation schema.

Tests the text edit schema generator functionality including:
- HTML generation
- Show diff display elements
- Show edit distance display elements
- Allow reset button toggle
- Source field data attribute
- Hidden input for data storage
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.text_edit import generate_text_edit_layout


class TestTextEditSchema:
    """Tests for text edit schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        html, keybindings = generate_text_edit_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_edit" in html
        assert 'data-annotation-type="text_edit"' in html

    def test_source_field_attribute(self):
        """Test that source_field data attribute is set."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
            "source_field": "original_text",
        }

        html, _ = generate_text_edit_layout(scheme)

        assert 'data-source-field="original_text"' in html

    def test_show_diff_default_true(self):
        """Test that diff display is shown by default."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "text-edit-diff-display" in html
        assert "text-edit-diff-content" in html

    def test_show_diff_false(self):
        """Test that diff display is hidden when disabled."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
            "show_diff": False,
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "text-edit-diff-display" not in html

    def test_show_edit_distance_default_true(self):
        """Test that edit distance display is shown by default."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "text-edit-stats" in html
        assert "Words changed" in html
        assert "Chars changed" in html

    def test_show_edit_distance_false(self):
        """Test that edit distance display is hidden when disabled."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
            "show_edit_distance": False,
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "text-edit-stats" not in html

    def test_allow_reset_default_true(self):
        """Test that reset button is shown by default."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "Reset to Original" in html
        assert "text-edit-reset-btn" in html

    def test_allow_reset_false(self):
        """Test that reset button is hidden when disabled."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
            "allow_reset": False,
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "text-edit-reset-btn" not in html

    def test_hidden_input_for_data(self):
        """Test that a hidden input is present for data storage."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        html, _ = generate_text_edit_layout(scheme)

        assert 'type="hidden"' in html
        assert "text-edit-data-input" in html

    def test_textarea_present(self):
        """Test that a textarea element is present for editing."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "text-edit-textarea" in html
        assert "<textarea" in html

    def test_annotation_input_class(self):
        """Test that inputs carry annotation-input class."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "annotation-input" in html

    def test_no_keybindings(self):
        """Test that text edit returns no keybindings."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        _, keybindings = generate_text_edit_layout(scheme)

        assert keybindings == []

    def test_source_display_block(self):
        """Test that original text display block is present."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "text-edit-source-block" in html
        assert "Original:" in html

    def test_editor_label(self):
        """Test that editor label is present."""
        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "Edit below:" in html

    def test_description_in_legend(self):
        """Test that description appears in the HTML."""
        scheme = {
            "name": "test_edit",
            "description": "Edit the translation",
            "annotation_type": "text_edit",
        }

        html, _ = generate_text_edit_layout(scheme)

        assert "Edit the translation" in html


class TestTextEditSchemaValidation:
    """Tests for text edit schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "text_edit",
        }

        html, keybindings = generate_text_edit_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "text_edit",
        }

        html, keybindings = generate_text_edit_layout(scheme)
        assert "annotation-error" in html


class TestTextEditSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that text_edit is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("text_edit")

    def test_in_supported_types(self):
        """Test that text_edit is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "text_edit" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_edit",
            "description": "Test Edit",
            "annotation_type": "text_edit",
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestTextEditConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that text_edit is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "text_edit",
            "name": "test",
            "description": "Test",
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_type_rejected(self):
        """Test that invalid types are still rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "nonexistent_type",
            "name": "test",
            "description": "Test",
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestSingleAnnotationInput:
    """The editor and the hidden JSON blob used to be two writers on one key.

    Both carried `annotation-input` and the SAME schema/label_name, so both wrote
    Label(schema, label). Which one survived depended on DOM sync order and on whether
    `data-modified` had been set — an annotator who accepted the pre-filled source text
    without typing never fired `oninput`, so the plain string was stored where every
    other record held the JSON blob, and any consumer doing json.loads broke on it.

    The textarea also owned the `name` the server-side restore matches, which is why
    the raw JSON blob was injected into the visible editor on reload.
    """

    @staticmethod
    def _layout():
        from potato.server_utils.schemas.text_edit import generate_text_edit_layout
        html, _ = generate_text_edit_layout({
            "name": "post_edit",
            "description": "Post-edit the MT output",
            "annotation_type": "text_edit",
            "source_field": "mt_output",
        })
        return html

    @staticmethod
    def _elements(html):
        import re
        return re.findall(r'<(?:textarea|input)[^>]*>', html)

    def test_exactly_one_annotation_input(self):
        inputs = [e for e in self._elements(self._layout()) if "annotation-input" in e]
        assert len(inputs) == 1, (
            f"expected one annotation input, found {len(inputs)} — two elements "
            f"writing one Label(schema, label) key is the collision this guards")

    def test_the_annotation_input_is_the_hidden_data_blob(self):
        inputs = [e for e in self._elements(self._layout()) if "annotation-input" in e]
        assert "text-edit-data-input" in inputs[0]
        assert 'type="hidden"' in inputs[0]

    def test_the_textarea_is_not_an_annotation_input(self):
        textarea = next(e for e in self._elements(self._layout())
                        if e.startswith("<textarea"))
        assert "annotation-input" not in textarea
        assert "label_name=" not in textarea, (
            "a label_name on the editor makes it a second writer again")

    def test_restore_targets_the_hidden_input_not_the_editor(self):
        """flask_server's restore looks up name="schema:::label". If the textarea owns
        that name, the JSON blob becomes the editor's visible content."""
        import re
        html = self._layout()
        hidden = next(e for e in self._elements(html) if "text-edit-data-input" in e)
        textarea = next(e for e in self._elements(html) if e.startswith("<textarea"))

        assert re.search(r'\bname="post_edit:::post_edit"', hidden)
        assert not re.search(r'\bname=', textarea), (
            "the editor must not carry the name the server restore matches")

    def test_fieldset_uses_the_standard_schema_attribute(self):
        import re
        fieldset = re.search(r'<fieldset[^>]*>', self._layout()).group(0)
        assert 'schema="post_edit"' in fieldset
        assert "schema_name=" not in fieldset, (
            "every other schema emits `schema`; `schema_name` was a one-off typo")

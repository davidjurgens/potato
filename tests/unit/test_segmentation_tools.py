"""
Tests for segmentation tools (fill/eraser) in image annotation.
"""

import pytest


class TestSegmentationToolsRegistration:
    """Verify fill and eraser tools are registered in image_annotation."""

    def test_fill_in_valid_tools(self):
        from potato.server_utils.schemas.image_annotation import VALID_TOOLS
        assert "fill" in VALID_TOOLS

    def test_eraser_in_valid_tools(self):
        from potato.server_utils.schemas.image_annotation import VALID_TOOLS
        assert "eraser" in VALID_TOOLS

    def test_original_tools_still_present(self):
        from potato.server_utils.schemas.image_annotation import VALID_TOOLS
        for tool in ["bbox", "polygon", "freeform", "landmark"]:
            assert tool in VALID_TOOLS


class TestSegmentationToolButtons:
    """Verify tool buttons are generated correctly."""

    def test_fill_button_generated(self):
        from potato.server_utils.schemas.image_annotation import _generate_tool_buttons
        html = _generate_tool_buttons(["fill"])
        assert 'data-tool="fill"' in html
        assert "Fill" in html

    def test_eraser_button_generated(self):
        from potato.server_utils.schemas.image_annotation import _generate_tool_buttons
        html = _generate_tool_buttons(["eraser"])
        assert 'data-tool="eraser"' in html
        assert "Eraser" in html

    def test_all_tools_generate(self):
        from potato.server_utils.schemas.image_annotation import _generate_tool_buttons, VALID_TOOLS
        html = _generate_tool_buttons(VALID_TOOLS)
        for tool in VALID_TOOLS:
            assert f'data-tool="{tool}"' in html


class TestSegmentationKeybindings:
    """Verify keybinding generation includes new tools."""

    def test_fill_keybinding(self):
        from potato.server_utils.schemas.image_annotation import _generate_keybindings
        bindings = _generate_keybindings([], ["fill"])
        keys = [b[0] for b in bindings]
        assert "g" in keys

    def test_eraser_keybinding(self):
        from potato.server_utils.schemas.image_annotation import _generate_keybindings
        bindings = _generate_keybindings([], ["eraser"])
        keys = [b[0] for b in bindings]
        assert "e" in keys

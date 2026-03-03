"""
Regression tests for Batch 5 fixes (items 34, 36, 37).

Tests for dead code removal, duplicate data, and gallery counter fixes.
"""

import pytest

from potato.trace_converter.base import CanonicalTrace
from potato.trace_converter.converters.webarena_converter import WebArenaConverter
from potato.server_utils.displays.gallery_display import GalleryDisplay


class TestItem34CanonicalStepRemoved:
    """
    Issue: CanonicalStep class in base.py was dead code (never imported or used).

    Fix: Removed the class entirely.
    """

    def test_canonical_step_not_importable(self):
        """CanonicalStep should no longer exist in the module."""
        from potato.trace_converter import base
        assert not hasattr(base, "CanonicalStep"), \
            "CanonicalStep was dead code and should have been removed"

    def test_canonical_trace_still_works(self):
        """CanonicalTrace should still function normally after cleanup."""
        trace = CanonicalTrace(
            id="test",
            task_description="Test",
            conversation=[{"speaker": "A", "text": "hello"}],
        )
        d = trace.to_dict()
        assert d["id"] == "test"
        assert d["conversation"][0]["text"] == "hello"


class TestItem36WebArenaDuplicateScreenshots:
    """
    Bug: WebArena converter adds screenshots to both CanonicalTrace.screenshots
    AND extra_fields["screenshots"], causing duplicate data in output.

    Fix: Only pass screenshots via CanonicalTrace.screenshots parameter;
    extra_fields only has screenshot_url (first screenshot for image display).
    """

    def get_data_with_screenshots(self):
        return [{
            "task_id": "wa_001",
            "intent": "Find headphones",
            "actions": [
                {
                    "action_type": "click",
                    "element": {"text": "Search"},
                    "screenshot": "step_0.png"
                },
                {
                    "action_type": "type",
                    "element": {"text": "Input"},
                    "value": "test",
                    "screenshot": "step_1.png"
                }
            ]
        }]

    def test_screenshots_not_duplicated_in_output(self):
        """screenshots should appear only once in to_dict() output."""
        converter = WebArenaConverter()
        traces = converter.convert(self.get_data_with_screenshots())
        d = traces[0].to_dict()

        # screenshots should be in the core field
        assert "screenshots" in d
        assert d["screenshots"] == ["step_0.png", "step_1.png"]

        # screenshot_url should be the first screenshot (for image display)
        assert d.get("screenshot_url") == "step_0.png"

    def test_screenshots_count_in_output(self):
        """Output dict should not have duplicate screenshots key."""
        converter = WebArenaConverter()
        traces = converter.convert(self.get_data_with_screenshots())
        d = traces[0].to_dict()

        # Count how many times "step_0.png" appears as a value (should be in screenshots list only)
        screenshots_values = []
        for key, val in d.items():
            if isinstance(val, list) and "step_0.png" in val:
                screenshots_values.append(key)
        assert len(screenshots_values) == 1, \
            f"Screenshots list appears under multiple keys: {screenshots_values}"


class TestItem37GalleryCounterJS:
    """
    Bug: Gallery counter shows static "1 / N" text that never updates
    when the user scrolls through images.

    Fix: Added JavaScript scroll event listener that updates the counter
    based on which gallery item is closest to the viewport center.
    """

    def test_counter_has_data_total_attribute(self):
        """Gallery counter should have data-total attribute for JS access."""
        display = GalleryDisplay()
        data = ["img1.png", "img2.png", "img3.png"]
        field_config = {"key": "test", "display_options": {"layout": "horizontal"}}
        html = display.render(field_config, data)
        assert 'data-total="3"' in html

    def test_counter_has_scroll_js(self):
        """Horizontal gallery with multiple items should include scroll JS."""
        display = GalleryDisplay()
        data = ["img1.png", "img2.png"]
        field_config = {"key": "test", "display_options": {"layout": "horizontal"}}
        html = display.render(field_config, data)
        assert "addEventListener" in html
        assert "scroll" in html

    def test_no_counter_js_for_single_item(self):
        """Single-item gallery should not include counter or JS."""
        display = GalleryDisplay()
        data = ["img1.png"]
        field_config = {"key": "test", "display_options": {"layout": "horizontal"}}
        html = display.render(field_config, data)
        # No counter element needed for single item (CSS class may still be in stylesheet)
        assert "data-total" not in html
        assert "addEventListener" not in html

    def test_no_counter_js_for_vertical_layout(self):
        """Vertical layout should not include horizontal scroll counter."""
        display = GalleryDisplay()
        data = ["img1.png", "img2.png"]
        field_config = {"key": "test", "display_options": {"layout": "vertical"}}
        html = display.render(field_config, data)
        assert "data-total" not in html
        assert "addEventListener" not in html

    def test_gallery_still_renders_correctly(self):
        """Gallery should render all images and layout correctly."""
        display = GalleryDisplay()
        data = ["img1.png", "img2.png", "img3.png"]
        field_config = {"key": "test", "display_options": {"layout": "horizontal"}}
        html = display.render(field_config, data)
        assert "img1.png" in html
        assert "img2.png" in html
        assert "img3.png" in html
        assert "gallery-horizontal" in html
        assert html.count('class="gallery-item"') == 3

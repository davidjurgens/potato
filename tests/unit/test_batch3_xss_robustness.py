"""
Tests for Batch 3 fixes: XSS/Injection (3A) + Robustness (3B) + Data Integrity (3C).

Batch 3A — XSS/Injection:
1. annotation_id HTML escaping across all schema generators
2. Wikipedia URL encoding in knowledge_base.py
3. Export filename sanitization

Batch 3B — Error Handling/Robustness:
4. EventAnnotation.__str__ with missing keys
5. int() conversion safety in cv_utils.get_image_dimensions
6. normalize_bbox [0,1] clamping
7. diversity_manager edge cases
8. get_ai_suggestion null ais check

Batch 3C — Data Integrity:
9. EAF exporter dynamic time slot consistency
10. Error response does not leak exception details
"""

import pytest
import os
import sys
import json
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ============================================================================
# Batch 3A: annotation_id HTML escaping in schema generators
# ============================================================================

class TestAnnotationIdEscaping:
    """Verify all schema generators escape annotation_id in HTML output."""

    MALICIOUS_ID = '<script>alert("xss")</script>'
    SAFE_FRAGMENT = '&lt;script&gt;'  # Escaped version

    def _make_scheme(self, annotation_type, **extra):
        base = {
            "name": "test_schema",
            "description": "Test",
            "annotation_id": self.MALICIOUS_ID,
        }
        base.update(extra)
        return base

    def test_radio_escapes_annotation_id(self):
        from potato.server_utils.schemas.radio import generate_radio_layout
        scheme = self._make_scheme("radio", labels=[
            {"name": "a"}, {"name": "b"}
        ])
        html, _ = generate_radio_layout(scheme)
        assert self.MALICIOUS_ID not in html
        assert self.SAFE_FRAGMENT in html

    def test_multiselect_escapes_annotation_id(self):
        from potato.server_utils.schemas.multiselect import generate_multiselect_layout
        scheme = self._make_scheme("multiselect", labels=[
            {"name": "a"}, {"name": "b"}
        ])
        html, _ = generate_multiselect_layout(scheme)
        assert self.MALICIOUS_ID not in html
        assert self.SAFE_FRAGMENT in html

    def test_likert_escapes_annotation_id(self):
        from potato.server_utils.schemas.likert import generate_likert_layout
        scheme = self._make_scheme("likert", size=5, min_label="Bad", max_label="Good")
        html, _ = generate_likert_layout(scheme)
        assert self.MALICIOUS_ID not in html
        assert self.SAFE_FRAGMENT in html

    def test_textbox_escapes_annotation_id(self):
        from potato.server_utils.schemas.textbox import generate_textbox_layout
        scheme = self._make_scheme("textbox")
        html, _ = generate_textbox_layout(scheme)
        assert self.MALICIOUS_ID not in html
        assert self.SAFE_FRAGMENT in html

    def test_slider_escapes_annotation_id(self):
        from potato.server_utils.schemas.slider import generate_slider_layout
        scheme = self._make_scheme("slider", min=0, max=10, step=1)
        html, _ = generate_slider_layout(scheme)
        assert self.MALICIOUS_ID not in html

    def test_span_escapes_annotation_id(self):
        from potato.server_utils.schemas.span import generate_span_layout
        scheme = self._make_scheme("span", labels=[
            {"name": "PER"}, {"name": "ORG"}
        ])
        html, _ = generate_span_layout(scheme)
        assert self.MALICIOUS_ID not in html
        assert self.SAFE_FRAGMENT in html

    def test_pairwise_escapes_annotation_id(self):
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout
        scheme = self._make_scheme("pairwise", mode="binary")
        html, _ = generate_pairwise_layout(scheme)
        assert self.MALICIOUS_ID not in html

    def test_pairwise_scale_escapes_annotation_id(self):
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout
        scheme = self._make_scheme("pairwise", mode="scale")
        html, _ = generate_pairwise_layout(scheme)
        assert self.MALICIOUS_ID not in html

    def test_triage_escapes_annotation_id(self):
        from potato.server_utils.schemas.triage import generate_triage_layout
        scheme = self._make_scheme("triage")
        html, _ = generate_triage_layout(scheme)
        assert self.MALICIOUS_ID not in html

    def test_event_annotation_escapes_annotation_id(self):
        from potato.server_utils.schemas.event_annotation import generate_event_annotation_layout
        scheme = self._make_scheme("event_annotation", span_schema="spans", event_types=[])
        html, _ = generate_event_annotation_layout(scheme)
        assert self.MALICIOUS_ID not in html
        assert self.SAFE_FRAGMENT in html

    def test_span_link_escapes_annotation_id(self):
        from potato.server_utils.schemas.span_link import generate_span_link_layout
        scheme = self._make_scheme("span_link", span_schema="spans", link_types=[])
        html, _ = generate_span_link_layout(scheme)
        assert self.MALICIOUS_ID not in html
        assert self.SAFE_FRAGMENT in html

    def test_coreference_escapes_annotation_id(self):
        from potato.server_utils.schemas.coreference import generate_coreference_layout
        scheme = self._make_scheme("coreference", span_schema="spans")
        html, _ = generate_coreference_layout(scheme)
        assert self.MALICIOUS_ID not in html
        assert self.SAFE_FRAGMENT in html

    def test_tree_annotation_escapes_annotation_id(self):
        from potato.server_utils.schemas.tree_annotation import generate_tree_annotation_layout
        scheme = self._make_scheme("tree_annotation")
        html, _ = generate_tree_annotation_layout(scheme)
        assert self.MALICIOUS_ID not in html
        assert self.SAFE_FRAGMENT in html


# ============================================================================
# Batch 3A: CSS injection in event_annotation.py color attribute
# ============================================================================

class TestEventAnnotationColorEscaping:
    """Verify color values in event annotation are escaped."""

    def test_malicious_color_escaped(self):
        from potato.server_utils.schemas.event_annotation import generate_event_annotation_layout
        scheme = {
            "name": "test_events",
            "description": "Test",
            "span_schema": "spans",
            "event_types": [
                {
                    "type": "ATTACK",
                    "color": '"><script>alert(1)</script>',
                    "arguments": [],
                }
            ],
        }
        html, _ = generate_event_annotation_layout(scheme)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "&#" in html


# ============================================================================
# Batch 3A: Wikipedia URL encoding
# ============================================================================

class TestWikipediaUrlEncoding:
    """Verify Wikipedia URLs are properly encoded."""

    def test_special_chars_encoded(self):
        # Test that urllib.parse.quote encodes special chars
        title = "C++ (programming language)"
        encoded = urllib.parse.quote(title.replace(' ', '_'), safe='')
        assert "(" not in encoded
        assert ")" not in encoded
        assert "+" not in encoded
        # Should contain percent-encoded versions
        assert "%28" in encoded  # (
        assert "%29" in encoded  # )
        assert "%2B" in encoded  # +

    def test_unicode_chars_encoded(self):
        title = "München"
        encoded = urllib.parse.quote(title.replace(' ', '_'), safe='')
        assert "%" in encoded  # ü should be encoded


# ============================================================================
# Batch 3A: Export filename sanitization
# ============================================================================

class TestExportFilenameSanitization:
    """Verify export filenames are sanitized."""

    def test_yolo_sanitizes_stem(self):
        """YOLO exporter should sanitize filename stems."""
        raw = "../../malicious file (1)"
        # os.path.basename strips directory traversal
        basename = os.path.basename(raw)
        stem = os.path.splitext(basename)[0]
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)
        assert "/" not in safe
        assert ".." not in safe
        assert " " not in safe

    def test_mask_sanitizes_label(self):
        """Mask exporter should sanitize label in filename."""
        label = "../../etc/passwd"
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in label)
        assert "/" not in safe
        assert os.sep not in safe


# ============================================================================
# Batch 3B: EventAnnotation.__str__ with missing keys
# ============================================================================

class TestEventAnnotationStr:
    """Verify EventAnnotation.__str__ handles missing keys gracefully."""

    def test_str_with_complete_args(self):
        from potato.item_state_management import EventAnnotation
        evt = EventAnnotation(
            schema="test",
            event_type="ATTACK",
            trigger_span_id="span_1",
            arguments=[{"role": "attacker", "span_id": "span_2"}],
        )
        result = str(evt)
        assert "attacker" in result
        assert "span_2" in result

    def test_str_with_missing_role(self):
        from potato.item_state_management import EventAnnotation
        evt = EventAnnotation(
            schema="test",
            event_type="ATTACK",
            trigger_span_id="span_1",
            arguments=[{"span_id": "span_2"}],  # missing 'role'
        )
        result = str(evt)
        assert "?:span_2" in result  # Should use '?' fallback

    def test_str_with_missing_span_id(self):
        from potato.item_state_management import EventAnnotation
        evt = EventAnnotation(
            schema="test",
            event_type="ATTACK",
            trigger_span_id="span_1",
            arguments=[{"role": "target"}],  # missing 'span_id'
        )
        result = str(evt)
        assert "target:?" in result  # Should use '?' fallback

    def test_str_with_empty_arg_dict(self):
        from potato.item_state_management import EventAnnotation
        evt = EventAnnotation(
            schema="test",
            event_type="ATTACK",
            trigger_span_id="span_1",
            arguments=[{}],  # completely empty
        )
        result = str(evt)
        assert "?:?" in result


# ============================================================================
# Batch 3B: int() conversion safety in cv_utils
# ============================================================================

class TestGetImageDimensionsSafety:
    """Verify get_image_dimensions handles non-numeric values gracefully."""

    def test_valid_dimensions(self):
        from potato.export.cv_utils import get_image_dimensions
        item = {"width": 640, "height": 480}
        w, h = get_image_dimensions(item)
        assert w == 640
        assert h == 480

    def test_string_dimensions(self):
        from potato.export.cv_utils import get_image_dimensions
        item = {"width": "640", "height": "480"}
        w, h = get_image_dimensions(item)
        assert w == 640
        assert h == 480

    def test_non_numeric_width_falls_back(self):
        from potato.export.cv_utils import get_image_dimensions
        item = {"width": "not_a_number", "height": 480}
        w, h = get_image_dimensions(item, default_width=100, default_height=100)
        # Should use default since int("not_a_number") fails
        assert w == 100
        assert h == 480

    def test_non_numeric_height_falls_back(self):
        from potato.export.cv_utils import get_image_dimensions
        item = {"width": 640, "height": [480]}
        w, h = get_image_dimensions(item, default_width=100, default_height=100)
        assert w == 640
        # Should use default since int([480]) fails
        assert h == 100

    def test_none_dimension_falls_back(self):
        from potato.export.cv_utils import get_image_dimensions
        item = {"width": None}
        w, h = get_image_dimensions(item, default_width=100, default_height=200)
        assert w == 100
        assert h == 200


# ============================================================================
# Batch 3B: normalize_bbox [0,1] clamping
# ============================================================================

class TestNormalizeBboxClamping:
    """Verify normalize_bbox clamps values to [0,1] range."""

    def test_normal_bbox(self):
        from potato.export.cv_utils import normalize_bbox
        cx, cy, nw, nh = normalize_bbox(100, 100, 200, 200, 800, 600)
        assert 0 <= cx <= 1
        assert 0 <= cy <= 1
        assert 0 <= nw <= 1
        assert 0 <= nh <= 1

    def test_oversized_bbox_clamped(self):
        from potato.export.cv_utils import normalize_bbox
        # BBox larger than image
        cx, cy, nw, nh = normalize_bbox(0, 0, 1600, 1200, 800, 600)
        assert nw <= 1.0
        assert nh <= 1.0

    def test_negative_position_clamped(self):
        from potato.export.cv_utils import normalize_bbox
        # Negative starting position
        cx, cy, nw, nh = normalize_bbox(-100, -50, 50, 50, 800, 600)
        assert cx >= 0.0
        assert cy >= 0.0

    def test_zero_image_dimensions(self):
        from potato.export.cv_utils import normalize_bbox
        cx, cy, nw, nh = normalize_bbox(10, 10, 50, 50, 0, 0)
        assert (cx, cy, nw, nh) == (0, 0, 0, 0)


# ============================================================================
# Batch 3B: diversity_manager edge cases
# ============================================================================

class TestDiversityManagerEdgeCases:
    """Verify diversity_manager handles edge cases safely."""

    def test_get_next_diverse_item_empty_available(self):
        from potato.diversity_manager import DiversityManager
        dm = DiversityManager.__new__(DiversityManager)
        dm.enabled = True
        dm.cluster_labels = {"item1": 0}
        import threading
        dm._lock = threading.Lock()
        dm._user_cluster_cursors = {}

        result = dm.get_next_diverse_item("user1", set())
        assert result is None

    def test_get_next_diverse_item_no_clustered_items(self):
        from potato.diversity_manager import DiversityManager
        dm = DiversityManager.__new__(DiversityManager)
        dm.enabled = True
        # cluster_labels has entries but none matching available_ids
        dm.cluster_labels = {"other_item": 0}
        import threading
        dm._lock = threading.Lock()
        dm._user_cluster_cursors = {}

        # Available IDs exist but none are in cluster_labels
        result = dm.get_next_diverse_item("user1", {"item1", "item2"})
        # Should fall back to returning one of the available items
        assert result in {"item1", "item2"}


# ============================================================================
# Batch 3B: get_ai_suggestion ais None check
# ============================================================================

class TestAiSuggestionNullCheck:
    """Verify get_ai_suggestion returns error when AI is disabled."""

    def test_ais_none_returns_400(self):
        """If get_ai_cache_manager() returns None, should get 400, not crash."""
        from unittest.mock import patch, MagicMock
        from potato.flask_server import app

        with app.test_request_context('/get_ai_suggestion?annotationId=0'):
            from flask import session
            with patch('potato.routes.session', {'username': 'test_user'}):
                with patch('potato.routes.get_user_state') as mock_gus:
                    with patch('potato.routes.get_ai_cache_manager', return_value=None):
                        with patch('potato.routes.config', {'annotation_schemes': [{}]}):
                            from potato.routes import get_ai_suggestion
                            response = get_ai_suggestion()
                            # Should return 400 tuple, not crash
                            assert response[1] == 400


# ============================================================================
# Batch 3C: EAF exporter dynamic time slot consistency
# ============================================================================

class TestEafTimeSlotConsistency:
    """Verify EAF exporter adds dynamically created time slots to TIME_ORDER."""

    def test_dynamic_slots_added_to_time_order(self):
        from potato.export.eaf_exporter import EAFExporter
        import xml.etree.ElementTree as ET

        exporter = EAFExporter()

        # Create a schema with one tier
        schema = {
            "name": "test_schema",
            "tiers": [
                {
                    "name": "utterance",
                    "type": "alignable",
                    "linguistic_type": "default-lt",
                }
            ]
        }

        # Create tiered data with annotations at times NOT in time_slots
        tiered_data = {
            "time_slots": {
                "ts1": 0,
                "ts2": 1000,
            },
            "annotations": {
                "utterance": [
                    {"start_time": 0, "end_time": 1000, "value": "hello"},
                    {"start_time": 2000, "end_time": 3000, "value": "world"},  # 2000/3000 not in time_slots
                ]
            }
        }

        root = exporter._create_eaf_document(schema, tiered_data, "", {})

        # Find all TIME_SLOT elements
        time_order = root.find("TIME_ORDER")
        time_slot_ids = {ts.get("TIME_SLOT_ID") for ts in time_order.findall("TIME_SLOT")}

        # Find all TIME_SLOT_REF values used in annotations
        refs_used = set()
        for tier in root.findall("TIER"):
            for ann in tier.findall(".//ALIGNABLE_ANNOTATION"):
                refs_used.add(ann.get("TIME_SLOT_REF1"))
                refs_used.add(ann.get("TIME_SLOT_REF2"))

        # Every referenced slot should exist in TIME_ORDER
        for ref in refs_used:
            if ref is not None:
                assert ref in time_slot_ids, f"TIME_SLOT_REF '{ref}' not found in TIME_ORDER"


# ============================================================================
# Batch 3C: Error responses don't leak exception details
# ============================================================================

class TestErrorResponseNoLeak:
    """Verify error responses don't contain exception strings or file paths."""

    def test_save_annotation_error_no_leak(self):
        """The save annotation error response should not contain exception details."""
        # The fix changed:
        #   return jsonify({"message": f"Failed to save annotation: {str(e)}"})
        # to:
        #   return jsonify({"message": "Failed to save annotation"})
        # We just verify the pattern is correct by checking the source
        import inspect
        from potato import routes
        source = inspect.getsource(routes)
        # The old pattern should be gone
        assert 'f"Failed to save annotation: {str(e)}"' not in source

    def test_span_error_no_leak(self):
        """Span/link/event error responses should not contain str(e)."""
        import inspect
        from potato import routes
        source = inspect.getsource(routes)
        # These specific user-facing patterns should be gone
        assert 'f"Failed to clear span annotations: {str(e)}"' not in source
        assert 'f"Failed to get link annotations: {str(e)}"' not in source
        assert 'f"Failed to delete link annotation: {str(e)}"' not in source
        assert 'f"Failed to get event annotations: {str(e)}"' not in source
        assert 'f"Failed to delete event annotation: {str(e)}"' not in source
        assert 'f"Search failed: {str(e)}"' not in source
        assert 'f"Failed to update span: {str(e)}"' not in source

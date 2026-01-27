"""
Common test helpers for span annotation tests.

This module provides shared utilities for span tests across unit, server, and selenium tests:
- MockSpanAnnotation for testing without full backend
- Span creation and validation helpers
- Common assertions
- Test data generators
- Configuration builders
"""

import json
import os
import tempfile
import yaml
from typing import Dict, List, Optional, Any, Tuple
from unittest.mock import Mock


class MockSpanAnnotation:
    """Mock SpanAnnotation for unit tests without requiring full backend."""

    def __init__(self, schema: str, name: str, start: int, end: int,
                 title: Optional[str] = None, span_id: Optional[str] = None):
        self._schema = schema
        self._name = name
        self._title = title or name.title()
        self._start = start
        self._end = end
        self._id = span_id or f"span_{start}_{end}_{name}"

    def get_schema(self) -> str:
        return self._schema

    def get_name(self) -> str:
        return self._name

    def get_title(self) -> str:
        return self._title

    def get_start(self) -> int:
        return self._start

    def get_end(self) -> int:
        return self._end

    def get_id(self) -> str:
        return self._id

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format used by API."""
        return {
            'id': self._id,
            'schema': self._schema,
            'name': self._name,
            'label': self._name,  # API uses 'label'
            'title': self._title,
            'start': self._start,
            'end': self._end
        }

    def __eq__(self, other):
        if not isinstance(other, (MockSpanAnnotation, )):
            return False
        return (self._schema == other.get_schema() and
                self._name == other.get_name() and
                self._start == other.get_start() and
                self._end == other.get_end())


class SpanTestData:
    """Standard test data for span tests."""

    # Simple test texts
    SIMPLE_TEXT = "The quick brown fox jumps over the lazy dog."
    MEDIUM_TEXT = "I am very happy today. This is a test sentence for span annotations."
    LONG_TEXT = (
        "This is a longer text that can be used for testing multiple span annotations. "
        "It contains several sentences and various words that can be highlighted. "
        "The text is designed to test different span positions and lengths."
    )

    # Test instances for multi-instance tests
    TEST_INSTANCES = [
        {"id": "instance_1", "text": "I am very happy today."},
        {"id": "instance_2", "text": "This is a different instance."},
        {"id": "instance_3", "text": "Another test sentence for annotations."}
    ]

    # Standard span schemas
    EMOTION_SCHEMA = {
        "annotation_type": "span",
        "name": "emotion",
        "description": "Mark emotion spans in the text.",
        "labels": [
            {"name": "happy", "title": "Happy"},
            {"name": "sad", "title": "Sad"},
            {"name": "angry", "title": "Angry"}
        ]
    }

    ENTITY_SCHEMA = {
        "annotation_type": "span",
        "name": "entity",
        "description": "Mark named entities in the text.",
        "labels": [
            {"name": "person", "title": "Person"},
            {"name": "organization", "title": "Organization"},
            {"name": "location", "title": "Location"}
        ]
    }

    # Schema with custom colors
    EMOTION_SCHEMA_WITH_COLORS = {
        **EMOTION_SCHEMA,
        "colors": {
            "happy": "#90EE90",
            "sad": "#87CEEB",
            "angry": "#FFB6C1"
        }
    }


def create_span_test_config(
    test_dir: str,
    schemas: Optional[List[Dict]] = None,
    instances: Optional[List[Dict]] = None,
    port: int = 9000,
    **extra_config
) -> Tuple[str, str]:
    """
    Create a complete test configuration for span testing.

    Args:
        test_dir: Directory to create config files in
        schemas: List of annotation schemas (defaults to emotion schema)
        instances: List of test instances (defaults to SpanTestData.TEST_INSTANCES)
        port: Port number for server
        **extra_config: Additional config options

    Returns:
        Tuple of (config_file_path, data_file_path)
    """
    os.makedirs(test_dir, exist_ok=True)

    # Use defaults if not provided
    if schemas is None:
        schemas = [SpanTestData.EMOTION_SCHEMA]
    if instances is None:
        instances = SpanTestData.TEST_INSTANCES[:2]

    # Create data file
    data_file = os.path.join(test_dir, "test_data.jsonl")
    with open(data_file, 'w') as f:
        for instance in instances:
            f.write(json.dumps(instance) + "\n")

    # Create config
    config = {
        "port": port,
        "debug": False,
        "server_name": "span_test_server",
        "annotation_task_name": "Span Test",
        "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "output_annotation_format": "jsonl",
        "data_files": [data_file],
        "item_properties": {
            "id_key": "id",
            "text_key": "text"
        },
        "user_config": {
            "allow_all_users": True,
            "users": []
        },
        "require_password": False,
        "annotation_schemes": schemas,
        "site_dir": "default",
        **extra_config
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file, data_file


def assert_span_valid(span: Dict[str, Any], expected_schema: Optional[str] = None):
    """
    Assert that a span has all required fields and valid values.

    Args:
        span: Span dictionary from API
        expected_schema: Expected schema name (optional)
    """
    # Required fields
    required_fields = ['id', 'start', 'end']
    for field in required_fields:
        assert field in span, f"Span missing required field: {field}"

    # Validate types
    assert isinstance(span['start'], int), f"start must be int, got {type(span['start'])}"
    assert isinstance(span['end'], int), f"end must be int, got {type(span['end'])}"
    assert span['start'] >= 0, f"start must be non-negative, got {span['start']}"
    assert span['end'] > span['start'], f"end ({span['end']}) must be > start ({span['start']})"

    # Label/name field (API may use either)
    assert 'label' in span or 'name' in span, "Span must have label or name"

    # Schema validation
    if expected_schema:
        schema_val = span.get('schema') or span.get('schema_name')
        assert schema_val == expected_schema, f"Expected schema {expected_schema}, got {schema_val}"


def assert_spans_equal(span1: Dict, span2: Dict, ignore_id: bool = True):
    """
    Assert two spans are equivalent.

    Args:
        span1: First span
        span2: Second span
        ignore_id: If True, don't compare IDs
    """
    compare_fields = ['start', 'end']
    for field in compare_fields:
        assert span1.get(field) == span2.get(field), \
            f"Span {field} mismatch: {span1.get(field)} != {span2.get(field)}"

    # Compare label (may be 'label' or 'name')
    label1 = span1.get('label') or span1.get('name')
    label2 = span2.get('label') or span2.get('name')
    assert label1 == label2, f"Span label mismatch: {label1} != {label2}"

    if not ignore_id:
        assert span1.get('id') == span2.get('id'), \
            f"Span ID mismatch: {span1.get('id')} != {span2.get('id')}"


def assert_no_html_in_span(span: Dict):
    """Assert span data contains no HTML markup."""
    span_str = json.dumps(span)
    assert '<' not in span_str, f"Span contains '<': {span_str}"
    assert '>' not in span_str, f"Span contains '>': {span_str}"
    assert 'class=' not in span_str.lower(), f"Span contains 'class=': {span_str}"
    assert 'style=' not in span_str.lower(), f"Span contains 'style=': {span_str}"


def spans_overlap(span1_start: int, span1_end: int, span2_start: int, span2_end: int) -> bool:
    """
    Check if two spans overlap.

    Two spans overlap if one starts before the other ends AND the other starts before the first ends.
    Adjacent spans (touching at edges) do NOT overlap.
    """
    return span1_start < span2_end and span2_start < span1_end


def calculate_overlap_depth(spans: List[Dict]) -> int:
    """
    Calculate maximum overlap depth for a list of spans.

    Returns the maximum number of spans that overlap at any position.
    """
    if not spans:
        return 0

    # Create events: +1 for start, -1 for end
    events = []
    for span in spans:
        events.append((span['start'], 1))
        events.append((span['end'], -1))

    # Sort by position, then by type (ends before starts at same position)
    events.sort(key=lambda x: (x[0], -x[1]))

    max_depth = 0
    current_depth = 0
    for _, delta in events:
        current_depth += delta
        max_depth = max(max_depth, current_depth)

    return max_depth


class SpanSeleniumHelpers:
    """Helper methods for Selenium span tests."""

    @staticmethod
    def wait_for_span_manager(driver, timeout: int = 10) -> bool:
        """Wait for SpanManager to be initialized."""
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script(
                    "return window.spanManager && window.spanManager.isInitialized"
                )
            )
            return True
        except:
            return False

    @staticmethod
    def create_span_via_api(session, base_url: str, instance_id: str,
                           schema: str, label: str, start: int, end: int,
                           text: str) -> Dict:
        """Create a span annotation via the API."""
        span_data = {
            'schema': schema,
            'label': label,
            'start': start,
            'end': end,
            'text': text,
            'id': f"span_{start}_{end}_{label}"
        }

        response = session.post(
            f"{base_url}/updateinstance",
            data={
                'value': json.dumps({f'span_label:::{schema}': [span_data]}),
                'instance_id': instance_id,
                'action': 'save'
            }
        )
        return response.json() if response.status_code == 200 else None

    @staticmethod
    def get_spans_from_api(session, base_url: str, instance_id: str) -> List[Dict]:
        """Get spans for an instance from the API."""
        response = session.get(f"{base_url}/api/spans/{instance_id}")
        if response.status_code == 200:
            return response.json().get('spans', [])
        return []

    @staticmethod
    def verify_span_highlight_present(driver, label: str = None) -> bool:
        """Verify span highlight element is present in DOM."""
        from selenium.webdriver.common.by import By

        highlights = driver.find_elements(By.CLASS_NAME, "span-highlight")
        if not highlights:
            return False

        if label:
            for h in highlights:
                if h.get_attribute("data-label") == label:
                    return True
            return False

        return len(highlights) > 0

    @staticmethod
    def get_span_color(driver, label: str) -> Optional[str]:
        """Get the background color of a span with given label."""
        from selenium.webdriver.common.by import By

        highlights = driver.find_elements(By.CLASS_NAME, "span-highlight")
        for h in highlights:
            if h.get_attribute("data-label") == label:
                return h.value_of_css_property("background-color")
        return None


# Pytest fixtures for common setup
def pytest_span_config_fixture():
    """
    Pytest fixture factory for span test configuration.

    Usage:
        @pytest.fixture
        def span_config(tmp_path):
            return pytest_span_config_fixture()(tmp_path)
    """
    def _create_config(tmp_path, schemas=None, instances=None):
        test_dir = str(tmp_path / "span_test")
        return create_span_test_config(test_dir, schemas, instances)
    return _create_config

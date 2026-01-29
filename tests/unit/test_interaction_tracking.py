"""
Unit tests for the interaction_tracking module.

Tests the dataclasses for behavioral tracking including InteractionEvent,
AIUsageEvent, AnnotationChange, and BehavioralData.
"""

import pytest
import time
import json

from potato.interaction_tracking import (
    InteractionEvent,
    AIUsageEvent,
    AnnotationChange,
    BehavioralData,
    create_behavioral_data,
    get_or_create_behavioral_data,
)


class TestInteractionEvent:
    """Tests for the InteractionEvent dataclass."""

    def test_create_basic_event(self):
        """Test creating a basic interaction event."""
        event = InteractionEvent(
            event_type="click",
            timestamp=1706500000.0,
            target="label:positive",
            instance_id="instance_1",
        )
        assert event.event_type == "click"
        assert event.timestamp == 1706500000.0
        assert event.target == "label:positive"
        assert event.instance_id == "instance_1"
        assert event.client_timestamp is None
        assert event.metadata == {}

    def test_create_event_with_metadata(self):
        """Test creating an event with metadata."""
        event = InteractionEvent(
            event_type="click",
            timestamp=1706500000.0,
            target="label:positive",
            instance_id="instance_1",
            client_timestamp=1706500000000,
            metadata={"x": 150, "y": 320}
        )
        assert event.client_timestamp == 1706500000000
        assert event.metadata == {"x": 150, "y": 320}

    def test_to_dict(self):
        """Test serialization to dictionary."""
        event = InteractionEvent(
            event_type="focus_in",
            timestamp=1706500010.0,
            target="textbox:explanation",
            instance_id="instance_1",
            client_timestamp=1706500010000,
            metadata={"duration_ms": 5000}
        )
        d = event.to_dict()
        assert d == {
            'event_type': 'focus_in',
            'timestamp': 1706500010.0,
            'target': 'textbox:explanation',
            'instance_id': 'instance_1',
            'client_timestamp': 1706500010000,
            'metadata': {'duration_ms': 5000},
        }

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            'event_type': 'navigation',
            'timestamp': 1706500000.0,
            'target': 'nav:next',
            'instance_id': 'instance_2',
            'client_timestamp': 1706500000000,
            'metadata': {'from_instance': 'instance_1'},
        }
        event = InteractionEvent.from_dict(data)
        assert event.event_type == 'navigation'
        assert event.timestamp == 1706500000.0
        assert event.target == 'nav:next'
        assert event.instance_id == 'instance_2'
        assert event.client_timestamp == 1706500000000
        assert event.metadata == {'from_instance': 'instance_1'}

    def test_from_dict_missing_fields(self):
        """Test deserialization with missing optional fields."""
        data = {
            'event_type': 'click',
            'timestamp': 1706500000.0,
            'target': 'label:negative',
            'instance_id': 'instance_1',
        }
        event = InteractionEvent.from_dict(data)
        assert event.client_timestamp is None
        assert event.metadata == {}

    def test_roundtrip_serialization(self):
        """Test that to_dict/from_dict roundtrip preserves data."""
        original = InteractionEvent(
            event_type="keypress",
            timestamp=1706500005.5,
            target="key:1",
            instance_id="instance_3",
            client_timestamp=1706500005500,
            metadata={"key_code": 49}
        )
        restored = InteractionEvent.from_dict(original.to_dict())
        assert restored.event_type == original.event_type
        assert restored.timestamp == original.timestamp
        assert restored.target == original.target
        assert restored.instance_id == original.instance_id
        assert restored.client_timestamp == original.client_timestamp
        assert restored.metadata == original.metadata


class TestAIUsageEvent:
    """Tests for the AIUsageEvent dataclass."""

    def test_create_basic_event(self):
        """Test creating a basic AI usage event."""
        event = AIUsageEvent(
            request_timestamp=1706500010.0,
            schema_name="sentiment",
        )
        assert event.request_timestamp == 1706500010.0
        assert event.schema_name == "sentiment"
        assert event.suggestions_shown == []
        assert event.response_timestamp is None
        assert event.suggestion_accepted is None
        assert event.time_to_decision_ms is None

    def test_create_complete_event(self):
        """Test creating a complete AI usage event with all fields."""
        event = AIUsageEvent(
            request_timestamp=1706500010.0,
            schema_name="sentiment",
            suggestions_shown=["positive", "neutral"],
            response_timestamp=1706500012.5,
            suggestion_accepted="positive",
            final_annotation="positive",
            time_to_decision_ms=3500,
        )
        assert event.suggestions_shown == ["positive", "neutral"]
        assert event.response_timestamp == 1706500012.5
        assert event.suggestion_accepted == "positive"
        assert event.final_annotation == "positive"
        assert event.time_to_decision_ms == 3500

    def test_to_dict(self):
        """Test serialization to dictionary."""
        event = AIUsageEvent(
            request_timestamp=1706500010.0,
            schema_name="sentiment",
            suggestions_shown=["negative"],
            response_timestamp=1706500012.0,
            suggestion_accepted="negative",
            time_to_decision_ms=7500,
        )
        d = event.to_dict()
        assert d['request_timestamp'] == 1706500010.0
        assert d['schema_name'] == 'sentiment'
        assert d['suggestions_shown'] == ['negative']
        assert d['response_timestamp'] == 1706500012.0
        assert d['suggestion_accepted'] == 'negative'
        assert d['time_to_decision_ms'] == 7500

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            'request_timestamp': 1706500010.0,
            'schema_name': 'sentiment',
            'suggestions_shown': ['positive'],
            'response_timestamp': 1706500012.0,
            'suggestion_accepted': None,  # User rejected
            'time_to_decision_ms': 18000,
        }
        event = AIUsageEvent.from_dict(data)
        assert event.schema_name == 'sentiment'
        assert event.suggestion_accepted is None
        assert event.time_to_decision_ms == 18000

    def test_roundtrip_serialization(self):
        """Test roundtrip serialization preserves data."""
        original = AIUsageEvent(
            request_timestamp=1706500010.0,
            schema_name="topic",
            suggestions_shown=["sports", "politics"],
            response_timestamp=1706500012.5,
            suggestion_accepted="sports",
            final_annotation="sports",
            time_to_decision_ms=5000,
        )
        restored = AIUsageEvent.from_dict(original.to_dict())
        assert restored.request_timestamp == original.request_timestamp
        assert restored.schema_name == original.schema_name
        assert restored.suggestions_shown == original.suggestions_shown
        assert restored.suggestion_accepted == original.suggestion_accepted


class TestAnnotationChange:
    """Tests for the AnnotationChange dataclass."""

    def test_create_basic_change(self):
        """Test creating a basic annotation change."""
        change = AnnotationChange(
            timestamp=1706500005.0,
            schema_name="sentiment",
            action="select",
        )
        assert change.timestamp == 1706500005.0
        assert change.schema_name == "sentiment"
        assert change.action == "select"
        assert change.source == "user"

    def test_create_complete_change(self):
        """Test creating a change with all fields."""
        change = AnnotationChange(
            timestamp=1706500005.0,
            schema_name="sentiment",
            action="select",
            label_name="positive",
            old_value=None,
            new_value=True,
            source="ai_accept",
        )
        assert change.label_name == "positive"
        assert change.old_value is None
        assert change.new_value is True
        assert change.source == "ai_accept"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        change = AnnotationChange(
            timestamp=1706500010.0,
            schema_name="sentiment",
            action="deselect",
            label_name="neutral",
            old_value=True,
            new_value=None,
            source="user",
        )
        d = change.to_dict()
        assert d['action'] == 'deselect'
        assert d['old_value'] is True
        assert d['new_value'] is None

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            'timestamp': 1706500015.0,
            'schema_name': 'sentiment',
            'action': 'select',
            'label_name': 'negative',
            'old_value': None,
            'new_value': True,
            'source': 'keyboard',
        }
        change = AnnotationChange.from_dict(data)
        assert change.label_name == 'negative'
        assert change.source == 'keyboard'

    def test_different_sources(self):
        """Test annotation changes from different sources."""
        sources = ["user", "ai_accept", "keyboard", "prefill"]
        for source in sources:
            change = AnnotationChange(
                timestamp=time.time(),
                schema_name="test",
                action="select",
                source=source,
            )
            assert change.source == source


class TestBehavioralData:
    """Tests for the BehavioralData dataclass."""

    def test_create_basic_data(self):
        """Test creating basic behavioral data."""
        bd = BehavioralData(instance_id="instance_1")
        assert bd.instance_id == "instance_1"
        assert bd.session_start > 0
        assert bd.session_end is None
        assert bd.total_time_ms == 0
        assert bd.interactions == []
        assert bd.ai_usage == []
        assert bd.annotation_changes == []
        assert bd.navigation_history == []
        assert bd.focus_time_by_element == {}
        assert bd.scroll_depth_max == 0.0
        assert bd.keyword_highlights_shown == []

    def test_add_interaction(self):
        """Test adding an interaction event."""
        bd = BehavioralData(instance_id="instance_1")
        bd.add_interaction(
            event_type="click",
            target="label:positive",
            client_timestamp=1706500005500,
            metadata={"x": 150, "y": 320}
        )
        assert len(bd.interactions) == 1
        event = bd.interactions[0]
        assert event.event_type == "click"
        assert event.target == "label:positive"
        assert event.instance_id == "instance_1"
        assert event.client_timestamp == 1706500005500
        assert event.metadata == {"x": 150, "y": 320}

    def test_add_ai_request(self):
        """Test adding an AI assistance request."""
        bd = BehavioralData(instance_id="instance_1")
        event = bd.add_ai_request("sentiment")
        assert len(bd.ai_usage) == 1
        assert event.schema_name == "sentiment"
        assert event.request_timestamp > 0
        # Verify we can update the event later
        event.suggestions_shown = ["positive", "neutral"]
        event.response_timestamp = time.time()
        assert bd.ai_usage[0].suggestions_shown == ["positive", "neutral"]

    def test_add_annotation_change(self):
        """Test adding an annotation change."""
        bd = BehavioralData(instance_id="instance_1")
        bd.add_annotation_change(
            schema_name="sentiment",
            action="select",
            label_name="positive",
            old_value=None,
            new_value=True,
            source="user"
        )
        assert len(bd.annotation_changes) == 1
        change = bd.annotation_changes[0]
        assert change.schema_name == "sentiment"
        assert change.label_name == "positive"
        assert change.action == "select"
        assert change.source == "user"

    def test_add_navigation(self):
        """Test adding a navigation event."""
        bd = BehavioralData(instance_id="instance_2")
        bd.add_navigation(
            action="next",
            from_instance="instance_1",
            to_instance="instance_2"
        )
        assert len(bd.navigation_history) == 1
        nav = bd.navigation_history[0]
        assert nav['action'] == "next"
        assert nav['from_instance'] == "instance_1"
        assert nav['to_instance'] == "instance_2"
        assert nav['timestamp'] > 0

    def test_update_focus_time(self):
        """Test updating focus time for elements."""
        bd = BehavioralData(instance_id="instance_1")
        bd.update_focus_time("label:positive", 1000)
        bd.update_focus_time("textbox:explanation", 5000)
        bd.update_focus_time("label:positive", 500)  # Should accumulate

        assert bd.focus_time_by_element == {
            "label:positive": 1500,
            "textbox:explanation": 5000,
        }

    def test_update_scroll_depth(self):
        """Test updating scroll depth (max only)."""
        bd = BehavioralData(instance_id="instance_1")
        bd.update_scroll_depth(25.0)
        assert bd.scroll_depth_max == 25.0

        bd.update_scroll_depth(75.0)
        assert bd.scroll_depth_max == 75.0

        bd.update_scroll_depth(50.0)  # Should not decrease
        assert bd.scroll_depth_max == 75.0

    def test_finalize_session(self):
        """Test finalizing a session."""
        bd = BehavioralData(instance_id="instance_1")
        start_time = bd.session_start
        time.sleep(0.01)  # Small delay to ensure time difference
        bd.finalize_session()

        assert bd.session_end is not None
        assert bd.session_end > start_time
        assert bd.total_time_ms >= 10  # At least 10ms

    def test_to_dict_basic(self):
        """Test serialization to dictionary."""
        bd = BehavioralData(instance_id="instance_1")
        bd.session_start = 1706500000.0
        bd.session_end = 1706500035.0
        bd.total_time_ms = 35000
        bd.scroll_depth_max = 50.0

        d = bd.to_dict()
        assert d['instance_id'] == 'instance_1'
        assert d['session_start'] == 1706500000.0
        assert d['session_end'] == 1706500035.0
        assert d['total_time_ms'] == 35000
        assert d['scroll_depth_max'] == 50.0

    def test_to_dict_with_events(self):
        """Test serialization with nested events."""
        bd = BehavioralData(instance_id="instance_1")
        bd.add_interaction("click", "label:positive")
        bd.add_annotation_change("sentiment", "select", "positive")

        d = bd.to_dict()
        assert len(d['interactions']) == 1
        assert len(d['annotation_changes']) == 1
        assert isinstance(d['interactions'][0], dict)
        assert isinstance(d['annotation_changes'][0], dict)

    def test_from_dict_basic(self):
        """Test deserialization from dictionary."""
        data = {
            'instance_id': 'instance_1',
            'session_start': 1706500000.0,
            'session_end': 1706500035.0,
            'total_time_ms': 35000,
            'interactions': [],
            'ai_usage': [],
            'annotation_changes': [],
            'navigation_history': [],
            'focus_time_by_element': {'label:positive': 500},
            'scroll_depth_max': 25.0,
            'keyword_highlights_shown': [],
        }
        bd = BehavioralData.from_dict(data)
        assert bd.instance_id == 'instance_1'
        assert bd.session_start == 1706500000.0
        assert bd.total_time_ms == 35000
        assert bd.focus_time_by_element == {'label:positive': 500}
        assert bd.scroll_depth_max == 25.0

    def test_from_dict_with_events(self):
        """Test deserialization with nested events."""
        data = {
            'instance_id': 'instance_1',
            'session_start': 1706500000.0,
            'interactions': [
                {'event_type': 'click', 'timestamp': 1706500005.0, 'target': 'label:positive', 'instance_id': 'instance_1', 'metadata': {}},
            ],
            'ai_usage': [
                {'request_timestamp': 1706500010.0, 'schema_name': 'sentiment', 'suggestions_shown': ['positive']},
            ],
            'annotation_changes': [
                {'timestamp': 1706500005.0, 'schema_name': 'sentiment', 'action': 'select', 'label_name': 'positive'},
            ],
        }
        bd = BehavioralData.from_dict(data)

        assert len(bd.interactions) == 1
        assert isinstance(bd.interactions[0], InteractionEvent)
        assert bd.interactions[0].event_type == 'click'

        assert len(bd.ai_usage) == 1
        assert isinstance(bd.ai_usage[0], AIUsageEvent)
        assert bd.ai_usage[0].schema_name == 'sentiment'

        assert len(bd.annotation_changes) == 1
        assert isinstance(bd.annotation_changes[0], AnnotationChange)
        assert bd.annotation_changes[0].label_name == 'positive'

    def test_roundtrip_serialization(self):
        """Test complete roundtrip serialization."""
        original = BehavioralData(instance_id="instance_1")
        original.session_start = 1706500000.0
        original.session_end = 1706500035.0
        original.total_time_ms = 35000
        original.add_interaction("click", "label:positive", 1706500005500, {"x": 150})
        original.add_annotation_change("sentiment", "select", "positive", None, True, "user")
        original.update_focus_time("label:positive", 500)
        original.update_scroll_depth(50.0)
        original.keyword_highlights_shown = [{"text": "excellent", "label": "positive"}]

        # Roundtrip through JSON
        json_str = json.dumps(original.to_dict())
        restored = BehavioralData.from_dict(json.loads(json_str))

        assert restored.instance_id == original.instance_id
        assert restored.total_time_ms == original.total_time_ms
        assert len(restored.interactions) == 1
        assert restored.interactions[0].target == "label:positive"
        assert len(restored.annotation_changes) == 1
        assert restored.focus_time_by_element == original.focus_time_by_element
        assert restored.scroll_depth_max == original.scroll_depth_max
        assert restored.keyword_highlights_shown == original.keyword_highlights_shown


class TestFactoryFunctions:
    """Tests for factory and helper functions."""

    def test_create_behavioral_data(self):
        """Test the create_behavioral_data factory function."""
        bd = create_behavioral_data("test_instance")
        assert bd.instance_id == "test_instance"
        assert bd.session_start > 0
        assert bd.interactions == []

    def test_get_or_create_behavioral_data_new(self):
        """Test get_or_create when instance doesn't exist."""
        data_dict = {}
        bd = get_or_create_behavioral_data(data_dict, "instance_1")

        assert "instance_1" in data_dict
        assert bd.instance_id == "instance_1"
        assert isinstance(bd, BehavioralData)

    def test_get_or_create_behavioral_data_existing(self):
        """Test get_or_create when instance already exists."""
        data_dict = {}
        bd1 = get_or_create_behavioral_data(data_dict, "instance_1")
        bd1.add_interaction("click", "label:positive")

        bd2 = get_or_create_behavioral_data(data_dict, "instance_1")
        assert bd2 is bd1
        assert len(bd2.interactions) == 1

    def test_get_or_create_behavioral_data_from_dict(self):
        """Test get_or_create when dict contains raw dictionary instead of object."""
        data_dict = {
            "instance_1": {
                "instance_id": "instance_1",
                "session_start": 1706500000.0,
                "total_time_ms": 35000,
                "interactions": [
                    {"event_type": "click", "timestamp": 1706500005.0, "target": "label:positive", "instance_id": "instance_1"}
                ],
                "ai_usage": [],
                "annotation_changes": [],
            }
        }
        bd = get_or_create_behavioral_data(data_dict, "instance_1")

        assert isinstance(bd, BehavioralData)
        assert bd.total_time_ms == 35000
        assert len(bd.interactions) == 1
        assert isinstance(bd.interactions[0], InteractionEvent)
        # Verify the dict was replaced with the object
        assert isinstance(data_dict["instance_1"], BehavioralData)


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_dict_deserialization(self):
        """Test deserializing from an empty dictionary."""
        bd = BehavioralData.from_dict({})
        assert bd.instance_id == ''
        assert bd.session_start == 0
        assert bd.interactions == []

    def test_interaction_event_empty_dict(self):
        """Test deserializing InteractionEvent from empty dict."""
        event = InteractionEvent.from_dict({})
        assert event.event_type == ''
        assert event.timestamp == 0
        assert event.target == ''

    def test_ai_usage_empty_dict(self):
        """Test deserializing AIUsageEvent from empty dict."""
        event = AIUsageEvent.from_dict({})
        assert event.request_timestamp == 0
        assert event.schema_name == ''
        assert event.suggestions_shown == []

    def test_annotation_change_empty_dict(self):
        """Test deserializing AnnotationChange from empty dict."""
        change = AnnotationChange.from_dict({})
        assert change.timestamp == 0
        assert change.schema_name == ''
        assert change.action == ''
        assert change.source == 'user'  # Default value

    def test_multiple_interactions_ordering(self):
        """Test that multiple interactions maintain order."""
        bd = BehavioralData(instance_id="instance_1")
        for i in range(10):
            bd.add_interaction(f"event_{i}", f"target_{i}")

        assert len(bd.interactions) == 10
        for i, event in enumerate(bd.interactions):
            assert event.event_type == f"event_{i}"
            assert event.target == f"target_{i}"

    def test_complex_metadata(self):
        """Test handling complex metadata structures."""
        bd = BehavioralData(instance_id="instance_1")
        complex_metadata = {
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "mixed": {"items": [{"a": 1}, {"b": 2}]}
        }
        bd.add_interaction("click", "target", metadata=complex_metadata)

        d = bd.to_dict()
        restored = BehavioralData.from_dict(d)
        assert restored.interactions[0].metadata == complex_metadata

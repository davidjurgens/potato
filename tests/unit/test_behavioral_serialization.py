"""
Unit tests for behavioral data serialization in user state management.

Tests that behavioral data is properly serialized and deserialized
when user state is saved and loaded.
"""

import pytest
import json
import tempfile
import os

from potato.interaction_tracking import (
    InteractionEvent,
    AIUsageEvent,
    AnnotationChange,
    BehavioralData,
)


class TestBehavioralDataInUserState:
    """Tests for behavioral data serialization within user state."""

    def test_serialize_empty_behavioral_data(self):
        """Test serializing user state with empty behavioral data."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")

        d = user_state.to_json()
        assert 'instance_id_to_behavioral_data' in d
        assert d['instance_id_to_behavioral_data'] == {}

    def test_serialize_behavioral_data_dict(self):
        """Test serializing user state with dictionary behavioral data."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")
        user_state.instance_id_to_behavioral_data["instance_1"] = {
            "instance_id": "instance_1",
            "session_start": 1706500000.0,
            "total_time_ms": 35000,
        }

        d = user_state.to_json()
        assert 'instance_id_to_behavioral_data' in d
        assert 'instance_1' in d['instance_id_to_behavioral_data']
        bd = d['instance_id_to_behavioral_data']['instance_1']
        assert bd['instance_id'] == 'instance_1'
        assert bd['total_time_ms'] == 35000

    def test_serialize_behavioral_data_object(self):
        """Test serializing user state with BehavioralData objects."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")

        bd = BehavioralData(instance_id="instance_1")
        bd.session_start = 1706500000.0
        bd.session_end = 1706500035.0
        bd.total_time_ms = 35000
        bd.add_interaction("click", "label:positive", 1706500005500)
        bd.add_annotation_change("sentiment", "select", "positive")

        user_state.instance_id_to_behavioral_data["instance_1"] = bd

        d = user_state.to_json()
        assert 'instance_1' in d['instance_id_to_behavioral_data']

        serialized = d['instance_id_to_behavioral_data']['instance_1']
        assert serialized['instance_id'] == 'instance_1'
        assert serialized['total_time_ms'] == 35000
        assert len(serialized['interactions']) == 1
        assert len(serialized['annotation_changes']) == 1

    def test_deserialize_behavioral_data_from_file(self):
        """Test deserializing user state with behavioral data from file."""
        from potato.user_state_management import InMemoryUserState

        # Create initial state with behavioral data
        user_state = InMemoryUserState("test_user")
        bd = BehavioralData(instance_id="instance_1")
        bd.session_start = 1706500000.0
        bd.total_time_ms = 35000
        bd.add_interaction("click", "label:positive")
        user_state.instance_id_to_behavioral_data["instance_1"] = bd

        # Serialize to JSON and write to temp file
        json_data = user_state.to_json()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, 'user_state.json')
            with open(state_file, 'w') as f:
                json.dump(json_data, f)

            # Load from file
            new_state = InMemoryUserState.load(tmpdir)

            assert "instance_1" in new_state.instance_id_to_behavioral_data
            restored_bd = new_state.instance_id_to_behavioral_data["instance_1"]
            assert isinstance(restored_bd, BehavioralData)
            assert restored_bd.instance_id == "instance_1"
            assert restored_bd.total_time_ms == 35000
            assert len(restored_bd.interactions) == 1

    def test_roundtrip_serialization_complex(self):
        """Test complete roundtrip with complex behavioral data."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")

        # Create complex behavioral data
        bd1 = BehavioralData(instance_id="instance_1")
        bd1.session_start = 1706500000.0
        bd1.session_end = 1706500035.0
        bd1.total_time_ms = 35000
        bd1.add_interaction("click", "label:positive", 1706500005500, {"x": 150})
        bd1.add_interaction("focus_in", "textbox:explanation", 1706500010000)
        bd1.add_interaction("focus_out", "textbox:explanation", 1706500025000, {"duration_ms": 15000})
        bd1.add_annotation_change("sentiment", "select", "positive", None, True, "user")
        bd1.update_focus_time("label:positive", 500)
        bd1.update_focus_time("textbox:explanation", 15000)
        bd1.update_scroll_depth(25.0)
        bd1.keyword_highlights_shown = [{"text": "excellent", "label": "positive"}]

        bd2 = BehavioralData(instance_id="instance_2")
        bd2.session_start = 1706500040.0
        bd2.total_time_ms = 45000
        ai_event = bd2.add_ai_request("sentiment")
        ai_event.suggestions_shown = ["negative"]
        ai_event.response_timestamp = 1706500047.5
        ai_event.suggestion_accepted = "negative"
        ai_event.time_to_decision_ms = 7500
        bd2.add_annotation_change("sentiment", "select", "negative", None, True, "ai_accept")

        user_state.instance_id_to_behavioral_data["instance_1"] = bd1
        user_state.instance_id_to_behavioral_data["instance_2"] = bd2

        # Roundtrip through file
        json_data = user_state.to_json()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, 'user_state.json')
            with open(state_file, 'w') as f:
                json.dump(json_data, f)

            restored_state = InMemoryUserState.load(tmpdir)

            # Verify instance_1
            r_bd1 = restored_state.instance_id_to_behavioral_data["instance_1"]
            assert r_bd1.total_time_ms == 35000
            assert len(r_bd1.interactions) == 3
            assert r_bd1.interactions[0].event_type == "click"
            assert r_bd1.interactions[0].metadata == {"x": 150}
            assert len(r_bd1.annotation_changes) == 1
            assert r_bd1.annotation_changes[0].label_name == "positive"
            assert r_bd1.focus_time_by_element == {"label:positive": 500, "textbox:explanation": 15000}
            assert r_bd1.scroll_depth_max == 25.0
            assert r_bd1.keyword_highlights_shown == [{"text": "excellent", "label": "positive"}]

            # Verify instance_2
            r_bd2 = restored_state.instance_id_to_behavioral_data["instance_2"]
            assert r_bd2.total_time_ms == 45000
            assert len(r_bd2.ai_usage) == 1
            assert r_bd2.ai_usage[0].suggestion_accepted == "negative"
            assert r_bd2.ai_usage[0].time_to_decision_ms == 7500

    def test_backward_compatibility_with_old_format(self):
        """Test that old behavioral data format (simple dict) still works."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")

        # Old format - simple dictionary with time_string
        user_state.instance_id_to_behavioral_data["instance_1"] = {
            "time_string": "00:00:35",
            "old_field": "some_value"
        }

        d = user_state.to_json()
        assert d['instance_id_to_behavioral_data']['instance_1'] == {
            "time_string": "00:00:35",
            "old_field": "some_value"
        }

    def test_deserialize_mixed_formats(self):
        """Test deserializing with mixed old and new behavioral data formats."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")

        # Mix of old and new formats
        user_state.instance_id_to_behavioral_data["old_instance"] = {
            "time_string": "00:00:35"
        }
        user_state.instance_id_to_behavioral_data["new_instance"] = BehavioralData(
            instance_id="new_instance"
        )
        user_state.instance_id_to_behavioral_data["new_instance"].total_time_ms = 35000

        json_data = user_state.to_json()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, 'user_state.json')
            with open(state_file, 'w') as f:
                json.dump(json_data, f)

            restored = InMemoryUserState.load(tmpdir)

            # Old format should be converted to BehavioralData
            old_bd = restored.instance_id_to_behavioral_data["old_instance"]
            assert isinstance(old_bd, BehavioralData)

            # New format should be properly restored
            new_bd = restored.instance_id_to_behavioral_data["new_instance"]
            assert isinstance(new_bd, BehavioralData)
            assert new_bd.total_time_ms == 35000


class TestMultipleUserStateSerialization:
    """Tests for serializing multiple user states."""

    def test_multiple_users_with_behavioral_data(self):
        """Test that multiple user states can have independent behavioral data."""
        from potato.user_state_management import InMemoryUserState

        user1 = InMemoryUserState("user1")
        user2 = InMemoryUserState("user2")

        bd1 = BehavioralData(instance_id="instance_1")
        bd1.total_time_ms = 30000

        bd2 = BehavioralData(instance_id="instance_1")
        bd2.total_time_ms = 60000  # Different time

        user1.instance_id_to_behavioral_data["instance_1"] = bd1
        user2.instance_id_to_behavioral_data["instance_1"] = bd2

        json1 = user1.to_json()
        json2 = user2.to_json()

        # Verify they're independent
        assert json1['instance_id_to_behavioral_data']['instance_1']['total_time_ms'] == 30000
        assert json2['instance_id_to_behavioral_data']['instance_1']['total_time_ms'] == 60000


class TestEdgeCases:
    """Tests for edge cases in behavioral data serialization."""

    def test_empty_interactions_list(self):
        """Test serialization with empty interactions list."""
        bd = BehavioralData(instance_id="test")
        d = bd.to_dict()
        assert d['interactions'] == []

        restored = BehavioralData.from_dict(d)
        assert restored.interactions == []

    def test_none_values_in_ai_usage(self):
        """Test serialization with None values in AI usage."""
        bd = BehavioralData(instance_id="test")
        ai_event = bd.add_ai_request("sentiment")
        # Don't set response - leave as None

        d = bd.to_dict()
        assert d['ai_usage'][0]['response_timestamp'] is None
        assert d['ai_usage'][0]['suggestion_accepted'] is None

        restored = BehavioralData.from_dict(d)
        assert restored.ai_usage[0].response_timestamp is None

    def test_special_characters_in_target(self):
        """Test serialization with special characters in target names."""
        bd = BehavioralData(instance_id="test")
        bd.add_interaction("click", "label:sentiment:positive/negative")
        bd.add_interaction("focus_in", "textbox:explanation (optional)")

        d = bd.to_dict()
        json_str = json.dumps(d)
        restored = BehavioralData.from_dict(json.loads(json_str))

        assert restored.interactions[0].target == "label:sentiment:positive/negative"
        assert restored.interactions[1].target == "textbox:explanation (optional)"

    def test_unicode_in_metadata(self):
        """Test serialization with unicode characters in metadata."""
        bd = BehavioralData(instance_id="test")
        bd.add_interaction("click", "label:positive", metadata={"note": "用户点击"})

        d = bd.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        restored = BehavioralData.from_dict(json.loads(json_str))

        assert restored.interactions[0].metadata["note"] == "用户点击"

    def test_large_number_of_interactions(self):
        """Test serialization with large number of interactions."""
        bd = BehavioralData(instance_id="test")
        for i in range(1000):
            bd.add_interaction(f"event_{i}", f"target_{i}")

        d = bd.to_dict()
        assert len(d['interactions']) == 1000

        restored = BehavioralData.from_dict(d)
        assert len(restored.interactions) == 1000
        assert restored.interactions[999].event_type == "event_999"

    def test_deeply_nested_metadata(self):
        """Test serialization with deeply nested metadata."""
        bd = BehavioralData(instance_id="test")
        nested_metadata = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": "deep"
                    }
                }
            }
        }
        bd.add_interaction("click", "target", metadata=nested_metadata)

        d = bd.to_dict()
        json_str = json.dumps(d)
        restored = BehavioralData.from_dict(json.loads(json_str))

        assert restored.interactions[0].metadata["level1"]["level2"]["level3"]["value"] == "deep"


class TestTotalWorkingTime:
    """Tests for total_working_time calculation with behavioral data."""

    def test_total_working_time_with_old_format(self):
        """Test total_working_time calculation with old format (time_string)."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")

        # Old format with time_string in the expected format: "Time spent: 0d 0h 0m 35s "
        user_state.instance_id_to_behavioral_data["instance_1"] = {
            "time_string": "Time spent: 0d 0h 0m 35s "  # 35 seconds
        }
        user_state.instance_id_to_behavioral_data["instance_2"] = {
            "time_string": "Time spent: 0d 0h 1m 30s "  # 90 seconds
        }

        # Note: The current implementation returns a tuple (seconds, formatted_string)
        total_time, formatted = user_state.total_working_time()
        assert total_time == 125  # 35 + 90 seconds

    def test_total_working_time_with_no_time_string(self):
        """Test total_working_time when time_string is not present."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")

        # Data without time_string
        user_state.instance_id_to_behavioral_data["instance_1"] = {
            "other_field": "some_value"
        }

        total_time, formatted = user_state.total_working_time()
        assert total_time == 0

    def test_total_working_time_with_behavioral_data_objects(self):
        """Test total_working_time with BehavioralData objects (new format)."""
        from potato.user_state_management import InMemoryUserState
        from potato.interaction_tracking import BehavioralData

        user_state = InMemoryUserState("test_user")

        # New format with BehavioralData objects
        bd1 = BehavioralData(instance_id="instance_1")
        bd1.total_time_ms = 35000  # 35 seconds

        bd2 = BehavioralData(instance_id="instance_2")
        bd2.total_time_ms = 90000  # 90 seconds

        user_state.instance_id_to_behavioral_data["instance_1"] = bd1
        user_state.instance_id_to_behavioral_data["instance_2"] = bd2

        total_time, formatted = user_state.total_working_time()
        assert total_time == 125  # 35 + 90 seconds

    def test_total_working_time_mixed_formats(self):
        """Test total_working_time with both old dict format and new BehavioralData."""
        from potato.user_state_management import InMemoryUserState
        from potato.interaction_tracking import BehavioralData

        user_state = InMemoryUserState("test_user")

        # Old format with time_string
        user_state.instance_id_to_behavioral_data["instance_1"] = {
            "time_string": "Time spent: 0d 0h 0m 35s "  # 35 seconds
        }

        # New format with BehavioralData
        bd = BehavioralData(instance_id="instance_2")
        bd.total_time_ms = 90000  # 90 seconds
        user_state.instance_id_to_behavioral_data["instance_2"] = bd

        total_time, formatted = user_state.total_working_time()
        assert total_time == 125  # 35 + 90 seconds

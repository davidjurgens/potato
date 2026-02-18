"""
Unit tests for the event annotation feature.

Tests cover:
- EventAnnotation class functionality
- Schema generation
- Registry integration
"""

import pytest
from unittest.mock import MagicMock, patch


class TestEventAnnotationClass:
    """Test the EventAnnotation class in item_state_management.py"""

    def test_event_annotation_creation(self):
        """Test basic EventAnnotation creation"""
        from potato.item_state_management import EventAnnotation

        event = EventAnnotation(
            schema="events",
            event_type="ATTACK",
            trigger_span_id="span_123",
            arguments=[
                {"role": "attacker", "span_id": "span_456"},
                {"role": "target", "span_id": "span_789"}
            ]
        )

        assert event.get_schema() == "events"
        assert event.get_event_type() == "ATTACK"
        assert event.get_trigger_span_id() == "span_123"
        assert len(event.get_arguments()) == 2
        assert event.get_id().startswith("event_")

    def test_event_annotation_with_custom_id(self):
        """Test EventAnnotation with custom ID"""
        from potato.item_state_management import EventAnnotation

        event = EventAnnotation(
            schema="events",
            event_type="HIRE",
            trigger_span_id="span_abc",
            arguments=[],
            id="custom_event_id"
        )

        assert event.get_id() == "custom_event_id"

    def test_event_annotation_with_properties(self):
        """Test EventAnnotation with additional properties"""
        from potato.item_state_management import EventAnnotation

        event = EventAnnotation(
            schema="events",
            event_type="TRAVEL",
            trigger_span_id="span_xyz",
            arguments=[],
            properties={"color": "#dc2626", "custom_field": "value"}
        )

        props = event.get_properties()
        assert props["color"] == "#dc2626"
        assert props["custom_field"] == "value"

    def test_get_argument_by_role(self):
        """Test getting argument by role name"""
        from potato.item_state_management import EventAnnotation

        event = EventAnnotation(
            schema="events",
            event_type="ATTACK",
            trigger_span_id="span_123",
            arguments=[
                {"role": "attacker", "span_id": "span_456"},
                {"role": "target", "span_id": "span_789"}
            ]
        )

        attacker = event.get_argument_by_role("attacker")
        assert attacker is not None
        assert attacker["span_id"] == "span_456"

        target = event.get_argument_by_role("target")
        assert target is not None
        assert target["span_id"] == "span_789"

        # Non-existent role
        weapon = event.get_argument_by_role("weapon")
        assert weapon is None

    def test_get_all_span_ids(self):
        """Test getting all span IDs involved in event"""
        from potato.item_state_management import EventAnnotation

        event = EventAnnotation(
            schema="events",
            event_type="ATTACK",
            trigger_span_id="span_trigger",
            arguments=[
                {"role": "attacker", "span_id": "span_attacker"},
                {"role": "target", "span_id": "span_target"}
            ]
        )

        span_ids = event.get_all_span_ids()
        assert "span_trigger" in span_ids
        assert "span_attacker" in span_ids
        assert "span_target" in span_ids
        assert len(span_ids) == 3

    def test_to_dict(self):
        """Test serialization to dictionary"""
        from potato.item_state_management import EventAnnotation

        event = EventAnnotation(
            schema="events",
            event_type="ATTACK",
            trigger_span_id="span_123",
            arguments=[{"role": "attacker", "span_id": "span_456"}],
            id="event_test",
            properties={"color": "#dc2626"}
        )

        d = event.to_dict()
        assert d["id"] == "event_test"
        assert d["schema"] == "events"
        assert d["event_type"] == "ATTACK"
        assert d["trigger_span_id"] == "span_123"
        assert d["arguments"] == [{"role": "attacker", "span_id": "span_456"}]
        assert d["properties"]["color"] == "#dc2626"

    def test_from_dict(self):
        """Test deserialization from dictionary"""
        from potato.item_state_management import EventAnnotation

        data = {
            "id": "event_abc",
            "schema": "events",
            "event_type": "HIRE",
            "trigger_span_id": "span_xyz",
            "arguments": [
                {"role": "employer", "span_id": "span_1"},
                {"role": "employee", "span_id": "span_2"}
            ],
            "properties": {"color": "#2563eb"}
        }

        event = EventAnnotation.from_dict(data)
        assert event.get_id() == "event_abc"
        assert event.get_schema() == "events"
        assert event.get_event_type() == "HIRE"
        assert event.get_trigger_span_id() == "span_xyz"
        assert len(event.get_arguments()) == 2

    def test_equality(self):
        """Test EventAnnotation equality comparison"""
        from potato.item_state_management import EventAnnotation

        event1 = EventAnnotation(
            schema="events",
            event_type="ATTACK",
            trigger_span_id="span_123",
            arguments=[{"role": "attacker", "span_id": "span_456"}]
        )

        event2 = EventAnnotation(
            schema="events",
            event_type="ATTACK",
            trigger_span_id="span_123",
            arguments=[{"role": "attacker", "span_id": "span_456"}]
        )

        event3 = EventAnnotation(
            schema="events",
            event_type="HIRE",
            trigger_span_id="span_123",
            arguments=[{"role": "attacker", "span_id": "span_456"}]
        )

        assert event1 == event2
        assert event1 != event3

    def test_hash(self):
        """Test EventAnnotation hashing"""
        from potato.item_state_management import EventAnnotation

        event1 = EventAnnotation(
            schema="events",
            event_type="ATTACK",
            trigger_span_id="span_123",
            arguments=[{"role": "attacker", "span_id": "span_456"}]
        )

        event2 = EventAnnotation(
            schema="events",
            event_type="ATTACK",
            trigger_span_id="span_123",
            arguments=[{"role": "attacker", "span_id": "span_456"}]
        )

        # Equal events should have same hash
        assert hash(event1) == hash(event2)

        # Can be used in sets
        event_set = {event1, event2}
        assert len(event_set) == 1

    def test_str_representation(self):
        """Test string representation"""
        from potato.item_state_management import EventAnnotation

        event = EventAnnotation(
            schema="events",
            event_type="ATTACK",
            trigger_span_id="span_123",
            arguments=[{"role": "attacker", "span_id": "span_456"}],
            id="event_test"
        )

        str_repr = str(event)
        assert "EventAnnotation" in str_repr
        assert "ATTACK" in str_repr
        assert "span_123" in str_repr
        assert "attacker" in str_repr


class TestEventAnnotationSchemaGeneration:
    """Test the event_annotation schema generator"""

    def test_generate_event_annotation_layout(self):
        """Test basic schema generation"""
        from potato.server_utils.schemas.event_annotation import generate_event_annotation_layout

        scheme = {
            "name": "events",
            "description": "Test event annotation",
            "span_schema": "entities",
            "event_types": [
                {
                    "type": "ATTACK",
                    "color": "#dc2626",
                    "arguments": [
                        {"role": "attacker", "required": True},
                        {"role": "target", "required": True}
                    ]
                }
            ]
        }

        html, keybindings = generate_event_annotation_layout(scheme)

        assert "events" in html
        assert "event-annotation-container" in html
        assert "ATTACK" in html
        assert "data-event-type" in html

    def test_generate_with_trigger_labels(self):
        """Test schema generation with trigger label constraints"""
        from potato.server_utils.schemas.event_annotation import generate_event_annotation_layout

        scheme = {
            "name": "events",
            "description": "Test",
            "span_schema": "entities",
            "event_types": [
                {
                    "type": "ATTACK",
                    "trigger_labels": ["EVENT_TRIGGER", "VERB"],
                    "arguments": []
                }
            ]
        }

        html, keybindings = generate_event_annotation_layout(scheme)

        assert "data-trigger-labels" in html
        assert "EVENT_TRIGGER" in html

    def test_generate_with_entity_type_constraints(self):
        """Test schema generation with entity type constraints"""
        from potato.server_utils.schemas.event_annotation import generate_event_annotation_layout

        scheme = {
            "name": "events",
            "description": "Test",
            "span_schema": "entities",
            "event_types": [
                {
                    "type": "ATTACK",
                    "arguments": [
                        {"role": "attacker", "entity_types": ["PERSON", "ORG"], "required": True}
                    ]
                }
            ]
        }

        html, keybindings = generate_event_annotation_layout(scheme)

        # Check arguments data is included
        assert "data-arguments" in html

    def test_generate_with_visual_display(self):
        """Test schema generation with visual display settings"""
        from potato.server_utils.schemas.event_annotation import generate_event_annotation_layout

        scheme = {
            "name": "events",
            "description": "Test",
            "span_schema": "entities",
            "event_types": [],
            "visual_display": {
                "enabled": False,
                "arc_position": "below"
            }
        }

        html, keybindings = generate_event_annotation_layout(scheme)

        assert 'data-show-arcs="false"' in html


class TestEventAnnotationRegistryIntegration:
    """Test event_annotation integration with schema registry"""

    def test_event_annotation_in_registry(self):
        """Test that event_annotation is registered"""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("event_annotation")

    def test_event_annotation_schema_definition(self):
        """Test event_annotation schema definition"""
        from potato.server_utils.schemas.registry import schema_registry

        schema = schema_registry.get("event_annotation")
        assert schema is not None
        assert schema.name == "event_annotation"
        assert "event_types" in schema.required_fields
        assert "span_schema" in schema.required_fields
        assert schema.supports_keybindings is False

    def test_event_annotation_in_supported_types(self):
        """Test that event_annotation appears in supported types"""
        from potato.server_utils.schemas.registry import schema_registry

        supported = schema_registry.get_supported_types()
        assert "event_annotation" in supported

    def test_event_annotation_generator_callable(self):
        """Test that the generator is callable through registry"""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "event_annotation",
            "name": "events",
            "description": "Test",
            "span_schema": "entities",
            "event_types": []
        }

        html, keybindings = schema_registry.generate(scheme)
        assert html is not None
        assert "event-annotation-container" in html


class TestEventAnnotationConfigValidation:
    """Test event_annotation in config validation"""

    def test_event_annotation_is_valid_type(self):
        """Test that event_annotation is in valid_types"""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        # This should not raise for valid event_annotation type
        scheme = {
            "annotation_type": "event_annotation",
            "name": "events",
            "description": "Test",
            "span_schema": "entities",
            "event_types": []
        }

        # Validation should pass without raising an error
        # (validates that event_annotation is in valid_types list)
        validate_single_annotation_scheme(scheme, "annotation_schemes[0]")

"""
Tests for span linking functionality.

These tests verify:
1. SpanLink class in item_state_management.py
2. Link storage methods in user_state_management.py
3. span_link schema generation
4. Schema registry includes span_link type
"""

import pytest
from collections import defaultdict


class TestSpanLinkClass:
    """Test the SpanLink class in item_state_management."""

    def test_span_link_creation(self):
        """SpanLink should be created with required parameters."""
        from potato.item_state_management import SpanLink

        link = SpanLink(
            schema="relations",
            link_type="WORKS_FOR",
            span_ids=["span_1", "span_2"]
        )

        assert link.get_schema() == "relations"
        assert link.get_link_type() == "WORKS_FOR"
        assert link.get_span_ids() == ["span_1", "span_2"]
        assert link.get_direction() == "undirected"
        assert link.get_id().startswith("link_")

    def test_span_link_with_direction(self):
        """SpanLink should support directed links."""
        from potato.item_state_management import SpanLink

        link = SpanLink(
            schema="relations",
            link_type="SUPERVISES",
            span_ids=["span_a", "span_b"],
            direction="directed"
        )

        assert link.get_direction() == "directed"
        assert link.is_directed() is True

    def test_span_link_with_custom_id(self):
        """SpanLink should accept custom ID."""
        from potato.item_state_management import SpanLink

        link = SpanLink(
            schema="relations",
            link_type="KNOWS",
            span_ids=["span_1", "span_2"],
            id="custom_link_id"
        )

        assert link.get_id() == "custom_link_id"

    def test_span_link_with_properties(self):
        """SpanLink should support arbitrary properties."""
        from potato.item_state_management import SpanLink

        link = SpanLink(
            schema="relations",
            link_type="WORKS_FOR",
            span_ids=["span_1", "span_2"],
            properties={"confidence": 0.95, "notes": "verified"}
        )

        assert link.get_properties() == {"confidence": 0.95, "notes": "verified"}

    def test_span_link_to_dict(self):
        """SpanLink should serialize to dictionary."""
        from potato.item_state_management import SpanLink

        link = SpanLink(
            schema="relations",
            link_type="WORKS_FOR",
            span_ids=["span_1", "span_2"],
            direction="directed",
            id="link_123"
        )

        d = link.to_dict()

        assert d["schema"] == "relations"
        assert d["link_type"] == "WORKS_FOR"
        assert d["span_ids"] == ["span_1", "span_2"]
        assert d["direction"] == "directed"
        assert d["id"] == "link_123"

    def test_span_link_from_dict(self):
        """SpanLink should deserialize from dictionary."""
        from potato.item_state_management import SpanLink

        d = {
            "schema": "relations",
            "link_type": "COLLABORATES_WITH",
            "span_ids": ["span_a", "span_b", "span_c"],
            "direction": "undirected",
            "id": "link_456",
            "properties": {"source": "manual"}
        }

        link = SpanLink.from_dict(d)

        assert link.get_schema() == "relations"
        assert link.get_link_type() == "COLLABORATES_WITH"
        assert link.get_span_ids() == ["span_a", "span_b", "span_c"]
        assert link.get_direction() == "undirected"
        assert link.get_id() == "link_456"
        assert link.get_properties() == {"source": "manual"}

    def test_span_link_equality(self):
        """SpanLinks with same ID should be equal."""
        from potato.item_state_management import SpanLink

        link1 = SpanLink(
            schema="relations",
            link_type="WORKS_FOR",
            span_ids=["span_1", "span_2"],
            id="same_id"
        )

        link2 = SpanLink(
            schema="relations",
            link_type="WORKS_FOR",
            span_ids=["span_1", "span_2"],
            id="same_id"
        )

        assert link1 == link2
        assert hash(link1) == hash(link2)

    def test_span_link_str(self):
        """SpanLink should have string representation."""
        from potato.item_state_management import SpanLink

        link = SpanLink(
            schema="relations",
            link_type="WORKS_FOR",
            span_ids=["span_1", "span_2"]
        )

        s = str(link)
        assert "WORKS_FOR" in s
        assert "span_1" in s or "span_2" in s


class TestUserStateLinkStorage:
    """Test link storage methods in user_state_management."""

    @pytest.fixture
    def user_state(self):
        """Create a fresh InMemoryUserState for testing."""
        from potato.user_state_management import InMemoryUserState
        return InMemoryUserState(user_id="test_user")

    @pytest.fixture
    def sample_link(self):
        """Create a sample SpanLink for testing."""
        from potato.item_state_management import SpanLink
        return SpanLink(
            schema="relations",
            link_type="WORKS_FOR",
            span_ids=["span_1", "span_2"],
            direction="directed",
            id="test_link_1"
        )

    def test_add_link_annotation(self, user_state, sample_link):
        """Should be able to add link annotations."""
        user_state.add_link_annotation("instance_1", sample_link)

        links = user_state.get_link_annotations("instance_1")
        assert "test_link_1" in links
        assert links["test_link_1"].get_link_type() == "WORKS_FOR"

    def test_get_link_annotation(self, user_state, sample_link):
        """Should be able to get a specific link by ID."""
        user_state.add_link_annotation("instance_1", sample_link)

        link = user_state.get_link_annotation("instance_1", "test_link_1")
        assert link is not None
        assert link.get_id() == "test_link_1"

    def test_get_link_annotation_not_found(self, user_state):
        """Should return None for non-existent link."""
        link = user_state.get_link_annotation("instance_1", "nonexistent")
        assert link is None

    def test_remove_link_annotation(self, user_state, sample_link):
        """Should be able to remove link annotations."""
        user_state.add_link_annotation("instance_1", sample_link)

        result = user_state.remove_link_annotation("instance_1", "test_link_1")
        assert result is True

        links = user_state.get_link_annotations("instance_1")
        assert "test_link_1" not in links

    def test_remove_link_annotation_not_found(self, user_state):
        """Should return False when removing non-existent link."""
        result = user_state.remove_link_annotation("instance_1", "nonexistent")
        assert result is False

    def test_get_links_for_span(self, user_state):
        """Should be able to get all links containing a specific span."""
        from potato.item_state_management import SpanLink

        link1 = SpanLink(
            schema="relations",
            link_type="WORKS_FOR",
            span_ids=["span_1", "span_2"],
            id="link_1"
        )
        link2 = SpanLink(
            schema="relations",
            link_type="KNOWS",
            span_ids=["span_1", "span_3"],
            id="link_2"
        )
        link3 = SpanLink(
            schema="relations",
            link_type="LOCATED_IN",
            span_ids=["span_2", "span_4"],
            id="link_3"
        )

        user_state.add_link_annotation("instance_1", link1)
        user_state.add_link_annotation("instance_1", link2)
        user_state.add_link_annotation("instance_1", link3)

        # span_1 should be in link_1 and link_2
        span_1_links = user_state.get_links_for_span("instance_1", "span_1")
        assert len(span_1_links) == 2
        link_ids = [l.get_id() for l in span_1_links]
        assert "link_1" in link_ids
        assert "link_2" in link_ids

    def test_clear_link_annotations(self, user_state, sample_link):
        """Should be able to clear all link annotations for an instance."""
        from potato.item_state_management import SpanLink

        link2 = SpanLink(
            schema="relations",
            link_type="KNOWS",
            span_ids=["span_3", "span_4"],
            id="test_link_2"
        )

        user_state.add_link_annotation("instance_1", sample_link)
        user_state.add_link_annotation("instance_1", link2)

        user_state.clear_link_annotations("instance_1")

        links = user_state.get_link_annotations("instance_1")
        assert len(links) == 0

    def test_link_annotations_empty_by_default(self, user_state):
        """Get link annotations should return empty dict for new instance."""
        links = user_state.get_link_annotations("new_instance")
        assert links == {}


class TestSpanLinkSchemaGeneration:
    """Test span_link schema HTML generation."""

    def test_span_link_generates_html(self):
        """span_link annotation type should generate valid HTML."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "span_link",
            "name": "relations",
            "description": "Annotate relationships between entities",
            "span_schema": "entities",
            "link_types": [
                {
                    "name": "WORKS_FOR",
                    "directed": True,
                    "color": "#dc2626"
                },
                {
                    "name": "KNOWS",
                    "directed": False,
                    "color": "#22c55e"
                }
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0
        assert "span-link" in html or "relations" in html

    def test_span_link_with_constraints(self):
        """span_link should handle label constraints in link types."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "span_link",
            "name": "relations",
            "description": "Test relations",
            "span_schema": "entities",
            "link_types": [
                {
                    "name": "WORKS_FOR",
                    "directed": True,
                    "allowed_source_labels": ["PERSON"],
                    "allowed_target_labels": ["ORGANIZATION"],
                    "color": "#dc2626"
                }
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0

    def test_span_link_with_visual_display(self):
        """span_link should handle visual display options."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "span_link",
            "name": "relations",
            "description": "Test relations",
            "span_schema": "entities",
            "link_types": [
                {"name": "LINK_TYPE", "color": "#000000"}
            ],
            "visual_display": {
                "enabled": True,
                "arc_position": "above",
                "show_labels": True
            }
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestSchemaRegistryIncludesSpanLink:
    """Test that span_link is properly registered in schema registry."""

    def test_span_link_in_registry(self):
        """span_link should be in schema registry supported types."""
        from potato.server_utils.schemas.registry import schema_registry

        supported_types = schema_registry.get_supported_types()
        assert "span_link" in supported_types

    def test_span_link_in_config_valid_types(self):
        """span_link should be accepted as a valid annotation type."""
        # We verify span_link is valid by checking the config_module source
        # which defines valid_types = [..., 'span_link', ...]
        import inspect
        from potato.server_utils import config_module

        # Get the source code of config_module and check span_link is in valid_types
        source = inspect.getsource(config_module)
        assert "'span_link'" in source, "span_link should be in config_module valid_types"

    def test_span_link_schema_definition_exists(self):
        """span_link should have a SchemaDefinition in registry."""
        from potato.server_utils.schemas.registry import schema_registry

        schema_def = schema_registry.get("span_link")
        assert schema_def is not None
        assert schema_def.name == "span_link"

    def test_span_link_required_fields(self):
        """span_link schema definition should have correct required fields."""
        from potato.server_utils.schemas.registry import schema_registry

        schema_def = schema_registry.get("span_link")
        assert "name" in schema_def.required_fields
        assert "description" in schema_def.required_fields
        assert "link_types" in schema_def.required_fields
        assert "span_schema" in schema_def.required_fields


class TestSpanLinkSerialization:
    """Test serialization/deserialization of link annotations."""

    @pytest.fixture
    def user_state_with_links(self):
        """Create a user state with some link annotations."""
        from potato.user_state_management import InMemoryUserState
        from potato.item_state_management import SpanLink

        state = InMemoryUserState(user_id="test_user")

        link1 = SpanLink(
            schema="relations",
            link_type="WORKS_FOR",
            span_ids=["span_1", "span_2"],
            direction="directed",
            id="link_1"
        )
        link2 = SpanLink(
            schema="relations",
            link_type="KNOWS",
            span_ids=["span_3", "span_4"],
            direction="undirected",
            id="link_2"
        )

        state.add_link_annotation("instance_1", link1)
        state.add_link_annotation("instance_1", link2)

        return state

    def test_to_json_includes_links(self, user_state_with_links):
        """to_json should include link annotations."""
        json_data = user_state_with_links.to_json()

        assert "instance_id_to_link_to_value" in json_data
        assert "instance_1" in json_data["instance_id_to_link_to_value"]

        links = json_data["instance_id_to_link_to_value"]["instance_1"]
        assert "link_1" in links
        assert "link_2" in links

    def test_load_restores_links(self, user_state_with_links, tmp_path):
        """load should restore link annotations from disk."""
        import json
        import os
        from potato.user_state_management import InMemoryUserState

        # Save state to JSON file
        json_data = user_state_with_links.to_json()
        user_dir = tmp_path / "test_user"
        user_dir.mkdir()
        state_file = user_dir / "user_state.json"
        with open(state_file, 'w') as f:
            json.dump(json_data, f)

        # Load state from disk
        new_state = InMemoryUserState.load(str(user_dir))

        links = new_state.get_link_annotations("instance_1")
        assert "link_1" in links
        assert "link_2" in links
        assert links["link_1"].get_link_type() == "WORKS_FOR"
        assert links["link_2"].get_link_type() == "KNOWS"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

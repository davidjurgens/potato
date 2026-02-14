"""
Tests for coreference chain annotation schema.
"""

import pytest


class TestCoreferenceSchemaRegistration:
    """Test that the coreference schema is properly registered."""

    def test_registered_in_schema_registry(self):
        from potato.server_utils.schemas.registry import schema_registry
        assert schema_registry.is_registered("coreference")

    def test_in_config_valid_types(self):
        """Coreference should be in config_module valid_types."""
        from potato.server_utils.schemas.registry import schema_registry
        assert "coreference" in schema_registry.get_supported_types()

    def test_schema_metadata(self):
        from potato.server_utils.schemas.registry import schema_registry
        schema = schema_registry.get("coreference")
        assert schema is not None
        assert "name" in schema.required_fields
        assert "description" in schema.required_fields
        assert "span_schema" in schema.required_fields
        assert schema.supports_keybindings is False


class TestCoreferenceLayoutGeneration:
    """Test HTML generation for the coreference schema."""

    def test_basic_generation(self):
        from potato.server_utils.schemas.coreference import generate_coreference_layout
        scheme = {
            "annotation_type": "coreference",
            "name": "coref_chains",
            "description": "Create coreference chains",
            "span_schema": "mentions",
        }
        html, keybindings = generate_coreference_layout(scheme)
        assert "coref-container" in html
        assert "coref_chains" in html
        assert keybindings == []

    def test_with_entity_types(self):
        from potato.server_utils.schemas.coreference import generate_coreference_layout
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Coreference annotation",
            "span_schema": "ner",
            "entity_types": ["PERSON", "ORG", "LOC"],
        }
        html, _ = generate_coreference_layout(scheme)
        assert "PERSON" in html
        assert "ORG" in html
        assert "LOC" in html
        assert "coref-entity-type-selector" in html

    def test_without_entity_types(self):
        from potato.server_utils.schemas.coreference import generate_coreference_layout
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Coreference",
            "span_schema": "ner",
        }
        html, _ = generate_coreference_layout(scheme)
        assert "coref-entity-type-selector" not in html

    def test_hidden_input_uses_span_link_convention(self):
        from potato.server_utils.schemas.coreference import generate_coreference_layout
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Coreference",
            "span_schema": "ner",
        }
        html, _ = generate_coreference_layout(scheme)
        assert 'name="span_link:::coref"' in html

    def test_visual_display_config(self):
        from potato.server_utils.schemas.coreference import generate_coreference_layout
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Coreference",
            "span_schema": "ner",
            "visual_display": {"highlight_mode": "bracket"},
        }
        html, _ = generate_coreference_layout(scheme)
        assert 'data-highlight-mode="bracket"' in html

    def test_allow_singletons_default(self):
        from potato.server_utils.schemas.coreference import generate_coreference_layout
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Coreference",
            "span_schema": "ner",
        }
        html, _ = generate_coreference_layout(scheme)
        assert 'data-allow-singletons="true"' in html

    def test_allow_singletons_false(self):
        from potato.server_utils.schemas.coreference import generate_coreference_layout
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Coreference",
            "span_schema": "ner",
            "allow_singletons": False,
        }
        html, _ = generate_coreference_layout(scheme)
        assert 'data-allow-singletons="false"' in html

    def test_chain_data_json_config(self):
        from potato.server_utils.schemas.coreference import generate_coreference_layout
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Coreference",
            "span_schema": "mentions",
            "entity_types": ["PER"],
        }
        html, _ = generate_coreference_layout(scheme)
        assert 'data-coref-config' in html
        assert '"spanSchema": "mentions"' in html or 'spanSchema' in html

    def test_generate_via_registry(self):
        """Test generating through the centralized schema registry."""
        from potato.server_utils.schemas.registry import schema_registry
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Test coreference",
            "span_schema": "ner",
        }
        html, keybindings = schema_registry.generate(scheme)
        assert "coref-container" in html

    def test_entity_types_as_dicts(self):
        from potato.server_utils.schemas.coreference import generate_coreference_layout
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Coreference",
            "span_schema": "ner",
            "entity_types": [
                {"name": "PERSON", "color": "#FF0000"},
                {"name": "ORG", "color": "#00FF00"},
            ],
        }
        html, _ = generate_coreference_layout(scheme)
        assert "PERSON" in html
        assert "#FF0000" in html

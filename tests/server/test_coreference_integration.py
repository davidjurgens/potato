"""
Server integration tests for coreference chain annotation.

Tests the complete server-side functionality:
- Schema registration and generation
- Configuration loading with coreference type
- HTML output contains expected elements
- Server startup with coreference annotation scheme
"""

import pytest
import json
import os
import sys
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.registry import schema_registry
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


class TestCoreferenceSchemaRegistration:
    """Test coreference schema is properly registered."""

    def test_coreference_registered(self):
        assert schema_registry.is_registered("coreference")

    def test_coreference_in_supported_types(self):
        types = schema_registry.get_supported_types()
        assert "coreference" in types

    def test_coreference_schema_metadata(self):
        schema = schema_registry.get("coreference")
        assert schema is not None
        assert schema.name == "coreference"
        assert "name" in schema.required_fields
        assert "description" in schema.required_fields


class TestCoreferenceSchemaGeneration:
    """Test coreference schema generates valid HTML."""

    def test_generate_basic_layout(self):
        scheme = {
            "annotation_type": "coreference",
            "name": "coref_chains",
            "description": "Group mentions into chains",
            "span_schema": "mentions",
        }
        html, keybindings = schema_registry.generate(scheme)

        assert "coref_chains" in html
        assert "coref" in html.lower()
        # Should have a hidden input for data storage
        assert 'type="hidden"' in html or "hidden" in html

    def test_generate_with_entity_types(self):
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Coreference annotation",
            "span_schema": "ner_spans",
            "entity_types": ["PERSON", "ORG", "LOC"],
        }
        html, keybindings = schema_registry.generate(scheme)

        assert "PERSON" in html
        assert "ORG" in html
        assert "LOC" in html

    def test_generate_with_visual_display(self):
        scheme = {
            "annotation_type": "coreference",
            "name": "coref",
            "description": "Test",
            "span_schema": "spans",
            "visual_display": {"highlight_mode": "bracket"},
        }
        html, keybindings = schema_registry.generate(scheme)
        assert len(html) > 0

    def test_html_contains_config_data(self):
        """Generated HTML should embed the config as JSON for the JS manager."""
        scheme = {
            "annotation_type": "coreference",
            "name": "my_coref",
            "description": "Test coreference",
            "span_schema": "spans",
            "entity_types": ["PER", "ORG"],
            "allow_singletons": True,
        }
        html, _ = schema_registry.generate(scheme)
        # Config should be serialized in data attribute
        assert "data-coref-config" in html or "my_coref" in html


class TestCoreferenceServerStartup:
    """Test that a server with coreference annotation starts correctly."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("coref_server_test")
        test_data = [
            {"id": "1", "text": "John Smith went to the store. He bought apples. Smith left early."},
            {"id": "2", "text": "The company released a product. It was popular. The firm grew."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "span",
                    "name": "mentions",
                    "description": "Mark entity mentions",
                    "labels": ["PERSON", "ORG", "LOC"],
                },
                {
                    "annotation_type": "coreference",
                    "name": "coref_chains",
                    "description": "Group mentions into coreference chains",
                    "span_schema": "mentions",
                    "entity_types": ["PERSON", "ORG", "LOC"],
                    "allow_singletons": True,
                },
            ],
            data_files=[data_file],
            admin_api_key="test_admin_key",
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_server_starts(self, flask_server):
        response = requests.get(f"{flask_server.base_url}/", timeout=5)
        assert response.status_code == 200

    def test_annotation_page_loads(self, flask_server):
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "coref_user", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "coref_user", "pass": "pass"},
            timeout=5,
        )
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200
        # Page should contain coreference-related content
        assert "coref" in response.text.lower() or "coreference" in response.text.lower()

    def test_annotation_page_has_span_schema(self, flask_server):
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "coref_user2", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "coref_user2", "pass": "pass"},
            timeout=5,
        )
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        # Should include both the span annotation and coreference annotation
        assert "mentions" in response.text
        assert "coref_chains" in response.text

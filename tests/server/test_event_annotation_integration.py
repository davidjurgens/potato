"""
Server integration tests for N-ary event annotation.

Tests the complete server-side functionality:
- Schema registration and generation
- Configuration loading with event_annotation type
- HTML output contains expected elements
- API endpoints for event CRUD operations
- Server startup with event annotation scheme
- Event persistence and retrieval
"""

import pytest
import json
import os
import sys
import requests
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.registry import schema_registry
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


class TestEventAnnotationSchemaRegistration:
    """Test event_annotation schema is properly registered."""

    def test_event_annotation_registered(self):
        """event_annotation should be registered in the schema registry."""
        assert schema_registry.is_registered("event_annotation")

    def test_event_annotation_in_supported_types(self):
        """event_annotation should appear in the list of supported types."""
        types = schema_registry.get_supported_types()
        assert "event_annotation" in types

    def test_event_annotation_schema_metadata(self):
        """event_annotation schema should have correct metadata."""
        schema = schema_registry.get("event_annotation")
        assert schema is not None
        assert schema.name == "event_annotation"
        assert "name" in schema.required_fields
        assert "description" in schema.required_fields
        assert "event_types" in schema.required_fields
        assert "span_schema" in schema.required_fields
        assert schema.supports_keybindings is False

    def test_event_annotation_has_generator(self):
        """event_annotation should have a generator function."""
        schema = schema_registry.get("event_annotation")
        assert schema.generator is not None
        assert callable(schema.generator)


class TestEventAnnotationSchemaGeneration:
    """Test event_annotation schema generates valid HTML."""

    def test_generate_basic_layout(self):
        """Basic event_annotation scheme should generate valid HTML."""
        scheme = {
            "annotation_type": "event_annotation",
            "name": "events",
            "description": "Annotate events",
            "span_schema": "entities",
            "event_types": [
                {
                    "type": "ATTACK",
                    "arguments": [
                        {"role": "attacker", "required": True},
                        {"role": "target", "required": True}
                    ]
                }
            ]
        }
        html, keybindings = schema_registry.generate(scheme)

        assert "events" in html
        assert "event-annotation-container" in html
        assert "ATTACK" in html

    def test_generate_with_multiple_event_types(self):
        """Multiple event types should all appear in generated HTML."""
        scheme = {
            "annotation_type": "event_annotation",
            "name": "events",
            "description": "Events",
            "span_schema": "entities",
            "event_types": [
                {"type": "ATTACK", "arguments": []},
                {"type": "HIRE", "arguments": []},
                {"type": "TRAVEL", "arguments": []}
            ]
        }
        html, keybindings = schema_registry.generate(scheme)

        assert "ATTACK" in html
        assert "HIRE" in html
        assert "TRAVEL" in html

    def test_generate_with_trigger_labels(self):
        """Trigger label constraints should be embedded in HTML."""
        scheme = {
            "annotation_type": "event_annotation",
            "name": "events",
            "description": "Events",
            "span_schema": "entities",
            "event_types": [
                {
                    "type": "ATTACK",
                    "trigger_labels": ["VERB", "EVENT_TRIGGER"],
                    "arguments": []
                }
            ]
        }
        html, keybindings = schema_registry.generate(scheme)

        assert "data-trigger-labels" in html
        # The labels should be in the data attribute
        assert "VERB" in html or "EVENT_TRIGGER" in html

    def test_generate_with_entity_type_constraints(self):
        """Entity type constraints on arguments should be embedded."""
        scheme = {
            "annotation_type": "event_annotation",
            "name": "events",
            "description": "Events",
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
        html, keybindings = schema_registry.generate(scheme)

        # Arguments should be serialized as JSON in data attribute
        assert "data-arguments" in html

    def test_generate_with_visual_display_disabled(self):
        """Visual display settings should be respected."""
        scheme = {
            "annotation_type": "event_annotation",
            "name": "events",
            "description": "Events",
            "span_schema": "entities",
            "event_types": [],
            "visual_display": {
                "enabled": False
            }
        }
        html, keybindings = schema_registry.generate(scheme)

        assert 'data-show-arcs="false"' in html

    def test_generate_with_colors(self):
        """Custom colors for event types should be included."""
        scheme = {
            "annotation_type": "event_annotation",
            "name": "events",
            "description": "Events",
            "span_schema": "entities",
            "event_types": [
                {"type": "ATTACK", "color": "#ff0000", "arguments": []},
                {"type": "HIRE", "color": "#00ff00", "arguments": []}
            ]
        }
        html, keybindings = schema_registry.generate(scheme)

        assert "#ff0000" in html
        assert "#00ff00" in html

    def test_html_contains_form_elements(self):
        """Generated HTML should contain necessary form elements."""
        scheme = {
            "annotation_type": "event_annotation",
            "name": "my_events",
            "description": "Events",
            "span_schema": "entities",
            "event_types": [{"type": "TEST", "arguments": []}]
        }
        html, keybindings = schema_registry.generate(scheme)

        # Should have hidden input for event data
        assert 'type="hidden"' in html
        assert "event_data" in html or "my_events" in html

        # Should have create and cancel buttons
        assert "create" in html.lower()
        assert "cancel" in html.lower()


class TestEventAnnotationServerStartup:
    """Test that a server with event_annotation starts correctly."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server with event annotation config."""
        test_dir = create_test_directory("event_server_test")
        test_data = [
            {"id": "1", "text": "John attacked the building with a rifle."},
            {"id": "2", "text": "Microsoft hired Sarah as CTO last month."},
            {"id": "3", "text": "The CEO traveled from NYC to London."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "span",
                    "name": "entities",
                    "description": "Mark entities",
                    "labels": [
                        {"name": "PERSON"},
                        {"name": "ORG"},
                        {"name": "LOC"},
                        {"name": "WEAPON"},
                        {"name": "EVENT_TRIGGER"}
                    ],
                },
                {
                    "annotation_type": "event_annotation",
                    "name": "events",
                    "description": "Annotate events",
                    "span_schema": "entities",
                    "event_types": [
                        {
                            "type": "ATTACK",
                            "color": "#dc2626",
                            "trigger_labels": ["EVENT_TRIGGER"],
                            "arguments": [
                                {"role": "attacker", "entity_types": ["PERSON", "ORG"], "required": True},
                                {"role": "target", "entity_types": ["PERSON", "ORG", "LOC"], "required": True},
                                {"role": "weapon", "entity_types": ["WEAPON"], "required": False}
                            ]
                        },
                        {
                            "type": "HIRE",
                            "color": "#2563eb",
                            "arguments": [
                                {"role": "employer", "entity_types": ["ORG"], "required": True},
                                {"role": "employee", "entity_types": ["PERSON"], "required": True}
                            ]
                        }
                    ]
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
        """Server should start successfully with event annotation config."""
        response = requests.get(f"{flask_server.base_url}/", timeout=5)
        assert response.status_code == 200

    def test_annotation_page_loads(self, flask_server):
        """Annotation page should load and contain event annotation elements."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "event_user1", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "event_user1", "pass": "pass"},
            timeout=5,
        )
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200
        assert "event" in response.text.lower()

    def test_annotation_page_has_event_types(self, flask_server):
        """Annotation page should display event types."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "event_user2", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "event_user2", "pass": "pass"},
            timeout=5,
        )
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert "ATTACK" in response.text
        assert "HIRE" in response.text

    def test_annotation_page_has_span_schema(self, flask_server):
        """Annotation page should include both span and event schemas."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "event_user3", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "event_user3", "pass": "pass"},
            timeout=5,
        )
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert "entities" in response.text
        assert "events" in response.text


class TestEventAnnotationAPI:
    """Test the event annotation API endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server for API tests."""
        test_dir = create_test_directory("event_api_test")
        test_data = [
            {"id": "api_test_1", "text": "John attacked the building."},
            {"id": "api_test_2", "text": "Microsoft hired Sarah."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "span",
                    "name": "entities",
                    "description": "Mark entities",
                    "labels": [{"name": "PERSON"}, {"name": "ORG"}, {"name": "EVENT_TRIGGER"}],
                },
                {
                    "annotation_type": "event_annotation",
                    "name": "events",
                    "description": "Events",
                    "span_schema": "entities",
                    "event_types": [
                        {
                            "type": "ATTACK",
                            "arguments": [
                                {"role": "attacker", "required": True},
                                {"role": "target", "required": True}
                            ]
                        }
                    ]
                },
            ],
            data_files=[data_file],
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def _get_authenticated_session(self, flask_server, username="api_user"):
        """Helper to create authenticated session."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": username, "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": username, "pass": "pass"},
            timeout=5,
        )
        # Navigate to annotation page to initialize state
        session.get(f"{flask_server.base_url}/annotate", timeout=5)
        return session

    def test_get_events_empty(self, flask_server):
        """GET /api/events/<instance_id> should return empty list initially."""
        session = self._get_authenticated_session(flask_server, "api_user_1")
        response = session.get(f"{flask_server.base_url}/api/events/api_test_1", timeout=5)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["events"] == []

    def test_create_event_via_updateinstance(self, flask_server):
        """POST /updateinstance should create event annotations."""
        session = self._get_authenticated_session(flask_server, "api_user_2")

        # Create an event
        event_data = {
            "instance_id": "api_test_1",
            "event_annotations": [
                {
                    "schema": "events",
                    "event_type": "ATTACK",
                    "trigger_span_id": "span_trigger_1",
                    "arguments": [
                        {"role": "attacker", "span_id": "span_attacker_1"},
                        {"role": "target", "span_id": "span_target_1"}
                    ],
                    "id": "event_test_1"
                }
            ]
        }
        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=event_data,
            timeout=5,
        )
        assert response.status_code == 200

        # Verify event was created
        response = session.get(f"{flask_server.base_url}/api/events/api_test_1", timeout=5)
        assert response.status_code == 200
        data = response.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["event_type"] == "ATTACK"

    def test_delete_event(self, flask_server):
        """DELETE /api/events/<instance_id>/<event_id> should delete event."""
        session = self._get_authenticated_session(flask_server, "api_user_3")

        # First create an event
        event_data = {
            "instance_id": "api_test_1",
            "event_annotations": [
                {
                    "schema": "events",
                    "event_type": "ATTACK",
                    "trigger_span_id": "span_trigger_2",
                    "arguments": [],
                    "id": "event_to_delete"
                }
            ]
        }
        session.post(
            f"{flask_server.base_url}/updateinstance",
            json=event_data,
            timeout=5,
        )

        # Delete the event
        response = session.delete(
            f"{flask_server.base_url}/api/events/api_test_1/event_to_delete",
            timeout=5,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Verify it's deleted
        response = session.get(f"{flask_server.base_url}/api/events/api_test_1", timeout=5)
        data = response.json()
        event_ids = [e["id"] for e in data["events"]]
        assert "event_to_delete" not in event_ids

    def test_delete_nonexistent_event(self, flask_server):
        """DELETE should return 404 for nonexistent event."""
        session = self._get_authenticated_session(flask_server, "api_user_4")

        response = session.delete(
            f"{flask_server.base_url}/api/events/api_test_1/nonexistent_event_id",
            timeout=5,
        )
        assert response.status_code == 404

    def test_get_events_unauthenticated(self, flask_server):
        """GET /api/events should return 401 without authentication."""
        response = requests.get(
            f"{flask_server.base_url}/api/events/api_test_1",
            timeout=5,
        )
        assert response.status_code == 401


class TestEventAnnotationPersistence:
    """Test event annotation persistence across sessions."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server for persistence tests."""
        test_dir = create_test_directory("event_persist_test")
        test_data = [
            {"id": "persist_1", "text": "Test text for persistence."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "span",
                    "name": "entities",
                    "description": "Entities",
                    "labels": [{"name": "ENTITY"}],
                },
                {
                    "annotation_type": "event_annotation",
                    "name": "events",
                    "description": "Events",
                    "span_schema": "entities",
                    "event_types": [
                        {"type": "TEST_EVENT", "arguments": []}
                    ]
                },
            ],
            data_files=[data_file],
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_events_persist_across_page_reload(self, flask_server):
        """Events should persist when user navigates away and returns."""
        # Create authenticated session
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "persist_user", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "persist_user", "pass": "pass"},
            timeout=5,
        )
        session.get(f"{flask_server.base_url}/annotate", timeout=5)

        # Create an event
        event_data = {
            "instance_id": "persist_1",
            "event_annotations": [
                {
                    "schema": "events",
                    "event_type": "TEST_EVENT",
                    "trigger_span_id": "persist_trigger",
                    "arguments": [],
                    "id": "persist_event_1"
                }
            ]
        }
        session.post(
            f"{flask_server.base_url}/updateinstance",
            json=event_data,
            timeout=5,
        )

        # Simulate page reload by requesting annotation page again
        session.get(f"{flask_server.base_url}/annotate", timeout=5)

        # Verify event persists
        response = session.get(f"{flask_server.base_url}/api/events/persist_1", timeout=5)
        data = response.json()
        assert len(data["events"]) >= 1
        event_ids = [e["id"] for e in data["events"]]
        assert "persist_event_1" in event_ids

    def test_multiple_events_persist(self, flask_server):
        """Multiple events on same instance should all persist."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "multi_persist_user", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "multi_persist_user", "pass": "pass"},
            timeout=5,
        )
        session.get(f"{flask_server.base_url}/annotate", timeout=5)

        # Create multiple events
        for i in range(3):
            event_data = {
                "instance_id": "persist_1",
                "event_annotations": [
                    {
                        "schema": "events",
                        "event_type": "TEST_EVENT",
                        "trigger_span_id": f"multi_trigger_{i}",
                        "arguments": [],
                        "id": f"multi_event_{i}"
                    }
                ]
            }
            session.post(
                f"{flask_server.base_url}/updateinstance",
                json=event_data,
                timeout=5,
            )

        # Verify all events persist
        response = session.get(f"{flask_server.base_url}/api/events/persist_1", timeout=5)
        data = response.json()
        event_ids = [e["id"] for e in data["events"]]
        for i in range(3):
            assert f"multi_event_{i}" in event_ids

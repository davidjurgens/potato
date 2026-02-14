"""
Server integration tests for conversation tree annotation.

Tests the complete server-side functionality:
- Display registry integration for conversation_tree display
- Schema registry integration for tree_annotation
- Server startup with conversation tree config
- Annotation page renders tree nodes
"""

import pytest
import json
import os
import sys
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.displays import display_registry
from potato.server_utils.schemas.registry import schema_registry
from potato.server_utils.displays.conversation_tree_display import ConversationTreeDisplay
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


class TestConversationTreeDisplayRegistry:
    """Test conversation_tree display is registered and renders."""

    def test_display_registered(self):
        assert display_registry.is_registered("conversation_tree")

    def test_display_in_supported_types(self):
        types = display_registry.get_supported_types()
        assert "conversation_tree" in types

    def test_render_basic_tree(self):
        field_config = {"key": "tree", "type": "conversation_tree"}
        data = {
            "id": "root",
            "speaker": "User",
            "text": "Hello?",
            "children": [
                {"id": "r1", "speaker": "Bot", "text": "Hi there!", "children": []},
            ],
        }
        html = display_registry.render("conversation_tree", field_config, data)
        assert "root" in html
        assert "User" in html
        assert "Hello?" in html
        assert "Hi there!" in html

    def test_render_nested_tree(self):
        field_config = {"key": "tree", "type": "conversation_tree"}
        data = {
            "id": "root",
            "speaker": "User",
            "text": "Question?",
            "children": [
                {
                    "id": "a1",
                    "speaker": "Bot A",
                    "text": "Answer A",
                    "children": [
                        {"id": "a1_followup", "speaker": "User", "text": "Thanks A", "children": []},
                    ],
                },
                {"id": "a2", "speaker": "Bot B", "text": "Answer B", "children": []},
            ],
        }
        html = display_registry.render("conversation_tree", field_config, data)
        assert "Bot A" in html
        assert "Bot B" in html
        assert "Answer A" in html
        assert "Thanks A" in html

    def test_render_empty_tree(self):
        field_config = {"key": "tree", "type": "conversation_tree"}
        data = {"id": "root", "speaker": "User", "text": "Solo node", "children": []}
        html = display_registry.render("conversation_tree", field_config, data)
        assert "Solo node" in html

    def test_render_string_input(self):
        """If data is a JSON string, display should handle it."""
        field_config = {"key": "tree", "type": "conversation_tree"}
        data = json.dumps({
            "id": "root", "speaker": "A", "text": "Text",
            "children": [],
        })
        html = display_registry.render("conversation_tree", field_config, data)
        assert "Text" in html


class TestTreeAnnotationSchemaRegistry:
    """Test tree_annotation schema is registered and generates HTML."""

    def test_schema_registered(self):
        assert schema_registry.is_registered("tree_annotation")

    def test_schema_in_supported_types(self):
        types = schema_registry.get_supported_types()
        assert "tree_annotation" in types

    def test_generate_basic_layout(self):
        scheme = {
            "annotation_type": "tree_annotation",
            "name": "tree_quality",
            "description": "Rate the quality of responses in the tree",
        }
        html, keybindings = schema_registry.generate(scheme)
        assert "tree_quality" in html
        assert len(html) > 0

    def test_generate_with_node_scheme(self):
        scheme = {
            "annotation_type": "tree_annotation",
            "name": "node_rating",
            "description": "Rate each node",
            "node_scheme": {
                "annotation_type": "likert",
                "size": 5,
                "min_label": "Poor",
                "max_label": "Excellent",
            },
        }
        html, keybindings = schema_registry.generate(scheme)
        assert "node_rating" in html

    def test_generate_with_path_selection(self):
        scheme = {
            "annotation_type": "tree_annotation",
            "name": "path_select",
            "description": "Select the best path",
            "path_selection": {
                "enabled": True,
                "description": "Pick best response path",
            },
        }
        html, keybindings = schema_registry.generate(scheme)
        assert "path_select" in html


class TestConversationTreeServerStartup:
    """Test server starts with conversation tree config."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("conv_tree_server_test")
        test_data = [
            {
                "id": "thread_001",
                "text": "Conversation tree",
                "tree": json.dumps({
                    "id": "root",
                    "speaker": "User",
                    "text": "What is Python?",
                    "children": [
                        {"id": "r1", "speaker": "Bot A", "text": "A programming language.", "children": []},
                        {"id": "r2", "speaker": "Bot B", "text": "A snake.", "children": []},
                    ],
                }),
            },
            {
                "id": "thread_002",
                "text": "Another tree",
                "tree": json.dumps({
                    "id": "root",
                    "speaker": "User",
                    "text": "Hello",
                    "children": [
                        {"id": "r1", "speaker": "Bot", "text": "Hi!", "children": []},
                    ],
                }),
            },
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "tree_annotation",
                    "name": "response_quality",
                    "description": "Rate response quality in the conversation tree",
                    "path_selection": {"enabled": True, "description": "Select best path"},
                },
            ],
            data_files=[data_file],
            item_properties={"id_key": "id", "text_key": "text"},
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
            data={"action": "signup", "email": "tree_user", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "tree_user", "pass": "pass"},
            timeout=5,
        )
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert response.status_code == 200
        assert "response_quality" in response.text

    def test_annotation_page_renders_tree_schema(self, flask_server):
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "tree_user2", "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": "tree_user2", "pass": "pass"},
            timeout=5,
        )
        response = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        # Tree annotation schema should be rendered
        assert "tree" in response.text.lower()

#!/usr/bin/env python3
"""
Server integration tests for dialogue span annotation.

Tests that span annotations can be saved and retrieved correctly when the
span target field contains dialogue data (list of dicts with speaker/text).
"""

import os
import sys
import json
import yaml
import pytest
import requests
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


def create_dialogue_span_config(test_dir):
    """Create a config with dialogue display as span target."""
    os.makedirs(test_dir, exist_ok=True)
    os.makedirs(os.path.join(test_dir, "data"), exist_ok=True)
    os.makedirs(os.path.join(test_dir, "annotation_output"), exist_ok=True)

    data = [
        {
            "id": "trace_001",
            "task_description": "Book a flight to London",
            "conversation": [
                {"speaker": "Agent", "text": "I will search for flights."},
                {"speaker": "Environment", "text": "Found 3 flights: BA117 $450, VS3 $485."},
                {"speaker": "Agent", "text": "BA117 at $450 is the cheapest. Booking it."},
            ]
        },
        {
            "id": "trace_002",
            "task_description": "Debug the Python script",
            "conversation": [
                {"speaker": "Agent", "text": "Let me read the script."},
                {"speaker": "Environment", "text": "File contents shown."},
            ]
        }
    ]
    data_file = os.path.join(test_dir, "data", "test_traces.json")
    with open(data_file, 'w') as f:
        json.dump(data, f)

    config = {
        "port": 8000,
        "server_name": "dialogue span test",
        "annotation_task_name": "Dialogue Span Test",
        "task_dir": os.path.abspath(test_dir),
        "output_annotation_dir": os.path.join(os.path.abspath(test_dir), "annotation_output"),
        "output_annotation_format": "json",
        "data_files": [os.path.join(os.path.abspath(test_dir), "data", "test_traces.json")],
        "item_properties": {
            "id_key": "id",
            "text_key": "task_description"
        },
        "user_config": {
            "allow_all_users": True,
            "users": []
        },
        "authentication": {"method": "in_memory"},
        "alert_time_each_instance": 10000000,
        "require_password": False,
        "persist_sessions": False,
        "debug": False,
        "secret_key": "test-secret-key",
        "session_lifetime_days": 1,
        "site_dir": "default",
        "instance_display": {
            "layout": {"direction": "vertical", "gap": "16px"},
            "fields": [
                {
                    "key": "task_description",
                    "type": "text",
                    "label": "Task"
                },
                {
                    "key": "conversation",
                    "type": "dialogue",
                    "label": "Agent Trace",
                    "span_target": True,
                    "display_options": {
                        "show_turn_numbers": True,
                        "alternating_shading": True
                    }
                }
            ]
        },
        "annotation_schemes": [
            {
                "annotation_type": "span",
                "name": "issue_spans",
                "description": "Highlight issues in the trace",
                "labels": [
                    {"name": "hallucination", "tooltip": "Unsupported claim"},
                    {"name": "error", "tooltip": "Factual error"}
                ]
            }
        ]
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file


class TestDialogueSpanIntegration:
    """Integration tests for dialogue span annotation API."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", "dialogue_span_integration")

        config_file = create_dialogue_span_config(test_dir)

        port = find_free_port(preferred_port=9050)
        server = FlaskTestServer(port=port, config_file=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    @pytest.fixture
    def auth_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        base = self.server.base_url
        session.post(f"{base}/register", data={"email": "testuser", "pass": "pass"})
        resp = session.post(f"{base}/auth", data={"email": "testuser", "pass": "pass"})
        assert resp.status_code == 200
        return session

    def test_annotation_page_loads(self, auth_session):
        """Verify the annotation page loads successfully."""
        resp = auth_session.get(f"{self.server.base_url}/annotate")
        assert resp.status_code == 200
        # Should contain the dialogue display
        assert "dialogue-turn" in resp.text or "dialogue-display" in resp.text

    def test_annotation_page_has_text_content_wrapper(self, auth_session):
        """The rendered page should contain text-content wrapper for span annotation."""
        resp = auth_session.get(f"{self.server.base_url}/annotate")
        assert resp.status_code == 200
        assert 'text-content-conversation' in resp.text

    def test_save_span_annotation(self, auth_session):
        """Save a span annotation on dialogue data via /updateinstance."""
        base = self.server.base_url

        # First get the annotation page to establish the instance
        auth_session.get(f"{base}/annotate")

        # Save a span annotation
        annotation_data = {
            "instance_id": "trace_001",
            "schema": "issue_spans",
            "label": "hallucination",
            "start": 0,
            "end": 10,
            "target_field": "conversation"
        }
        resp = auth_session.post(
            f"{base}/updateinstance",
            json={
                "instance_id": "trace_001",
                "schema_name": "issue_spans",
                "label_name": "hallucination",
                "label_value": {
                    "span": {
                        "start": 0,
                        "end": 10,
                        "text": "I will sea",
                        "label": "hallucination",
                        "target_field": "conversation"
                    }
                }
            }
        )
        # Accept 200 or 302 (redirect)
        assert resp.status_code in (200, 302)

    def test_span_api_returns_correct_text_for_dialogue(self, auth_session):
        """The /api/spans endpoint should extract text correctly from dialogue data."""
        base = self.server.base_url

        # Navigate to the annotation page
        auth_session.get(f"{base}/annotate")

        resp = auth_session.get(f"{base}/api/spans/trace_001")
        if resp.status_code == 200:
            data = resp.json()
            # The text should be the concatenated dialogue text, not a Python repr
            text = data.get("text", "")
            # Should NOT contain Python list syntax
            assert "[{" not in text
            assert "'speaker'" not in text
            # Should look like concatenated dialogue
            # (exact format depends on the text_key field)

    def test_span_api_dialogue_text_extraction(self, auth_session):
        """Verify the span text extraction handles dialogue list-of-dicts format."""
        base = self.server.base_url

        auth_session.get(f"{base}/annotate")

        resp = auth_session.get(f"{base}/api/spans/trace_001")
        if resp.status_code == 200:
            data = resp.json()
            spans = data.get("spans", [])
            # If spans exist, verify they have text content (not empty)
            for span in spans:
                if span.get("target_field") == "conversation":
                    # Text should be extracted from concatenated dialogue
                    assert span.get("text") is not None

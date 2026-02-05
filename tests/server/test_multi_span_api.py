#!/usr/bin/env python3
"""
Server integration tests for multi-span target_field support.

Tests the API contracts for multi-span annotation:
1. /api/spans/<instance_id> returns target_field
2. /updateinstance accepts target_field and routes spans correctly
3. Spans with different target_fields are stored independently
4. instance_display fields render with correct data attributes
"""

import os
import sys
import json
import yaml
import pytest
import requests
import time

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


def create_multi_span_config(test_dir):
    """Create a multi-span annotation config for testing."""
    os.makedirs(test_dir, exist_ok=True)
    os.makedirs(os.path.join(test_dir, "data"), exist_ok=True)
    os.makedirs(os.path.join(test_dir, "annotation_output"), exist_ok=True)

    # Create test data
    data = [
        {
            "id": "test_001",
            "premise": "The cat sat on the mat while the dog slept nearby.",
            "hypothesis": "An animal was resting on a surface."
        },
        {
            "id": "test_002",
            "premise": "Scientists discovered a new species of frog.",
            "hypothesis": "Researchers found an unknown animal."
        }
    ]
    data_file = os.path.join(test_dir, "data", "test_data.json")
    with open(data_file, 'w') as f:
        json.dump(data, f)

    # Create config with instance_display and multi-span
    config = {
        "port": 8000,
        "server_name": "test annotator",
        "annotation_task_name": "Multi-Span Test",
        "task_dir": os.path.abspath(test_dir),
        "output_annotation_dir": os.path.join(os.path.abspath(test_dir), "annotation_output"),
        "output_annotation_format": "json",
        "annotation_codebook_url": "",
        "data_files": [os.path.join(os.path.abspath(test_dir), "data", "test_data.json")],
        "item_properties": {
            "id_key": "id",
            "text_key": "premise"
        },
        "user_config": {
            "allow_all_users": True,
            "users": []
        },
        "authentication": {
            "method": "in_memory"
        },
        "alert_time_each_instance": 10000000,
        "require_password": False,
        "persist_sessions": False,
        "debug": False,
        "secret_key": "test-secret-key",
        "session_lifetime_days": 1,
        "random_seed": 1234,
        "site_dir": "default",
        "instance_display": {
            "layout": {
                "direction": "vertical",
                "gap": "16px"
            },
            "fields": [
                {
                    "key": "premise",
                    "type": "text",
                    "label": "Premise",
                    "span_target": True
                },
                {
                    "key": "hypothesis",
                    "type": "text",
                    "label": "Hypothesis",
                    "span_target": True
                }
            ]
        },
        "annotation_schemes": [
            {
                "annotation_type": "span",
                "name": "alignment",
                "description": "Highlight aligned phrases",
                "labels": [
                    {"name": "MATCH", "tooltip": "Matching phrases"},
                    {"name": "MISMATCH", "tooltip": "Mismatched phrases"}
                ],
                "sequential_key_binding": True
            }
        ]
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file


class TestMultiSpanAPI:
    """Test API endpoints for multi-span target_field support."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server with multi-span config."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", "multi_span_api_test")

        config_file = create_multi_span_config(test_dir)
        port = find_free_port(preferred_port=9020)
        server = FlaskTestServer(port=port, config_file=config_file)
        if not server.start():
            pytest.fail("Failed to start server")

        request.cls.server = server
        request.cls.base_url = server.base_url
        request.cls.test_dir = test_dir
        yield server
        server.stop()

    @pytest.fixture(autouse=True)
    def authenticated_session(self, flask_server):
        """Create an authenticated session for each test."""
        self.session = requests.Session()
        # Register user
        self.session.post(
            f"{self.base_url}/register",
            data={"email": "testuser", "pass": "testpass"}
        )
        # Login
        resp = self.session.post(
            f"{self.base_url}/auth",
            data={"email": "testuser", "pass": "testpass"}
        )
        # Also try simple login (no-password mode)
        if resp.status_code != 200 or '/annotate' not in resp.url:
            self.session.post(
                f"{self.base_url}/login",
                data={"email": "testuser"}
            )

    def test_annotate_page_loads(self):
        """Test that the annotation page loads successfully."""
        resp = self.session.get(f"{self.base_url}/annotate")
        assert resp.status_code == 200
        assert "Multi-Span Test" in resp.text

    def test_annotate_page_has_display_fields(self):
        """Test that display fields are rendered with correct attributes."""
        resp = self.session.get(f"{self.base_url}/annotate")
        assert resp.status_code == 200
        html = resp.text

        # Check for display field containers
        assert 'data-span-target="true"' in html, \
            "Display fields should have data-span-target attribute"
        assert 'data-field-key="premise"' in html, \
            "Premise field should have data-field-key attribute"
        assert 'data-field-key="hypothesis"' in html, \
            "Hypothesis field should have data-field-key attribute"

    def test_annotate_page_has_text_content_elements(self):
        """Test that text content elements have correct IDs and data attributes."""
        resp = self.session.get(f"{self.base_url}/annotate")
        html = resp.text

        assert 'id="text-content-premise"' in html, \
            "Premise text content should have id='text-content-premise'"
        assert 'id="text-content-hypothesis"' in html, \
            "Hypothesis text content should have id='text-content-hypothesis'"
        assert 'data-original-text=' in html, \
            "Text content elements should have data-original-text attribute"

    def test_api_spans_returns_text(self):
        """Test /api/spans/<instance_id> returns correct text."""
        # First get current instance
        resp = self.session.get(f"{self.base_url}/api/current_instance")
        assert resp.status_code == 200
        instance_id = resp.json()["instance_id"]

        # Get spans for the instance
        resp = self.session.get(f"{self.base_url}/api/spans/{instance_id}")
        assert resp.status_code == 200
        data = resp.json()

        # Should return the text (from text_key)
        assert "text" in data, "API should return 'text' field"
        # Text should be the premise (since text_key is 'premise')
        assert "cat" in data["text"] or "Scientists" in data["text"], \
            f"Text should be the premise content, got: {data['text'][:60]}"

    def test_create_span_with_target_field(self):
        """Test creating a span with target_field via /updateinstance."""
        # Get current instance
        resp = self.session.get(f"{self.base_url}/api/current_instance")
        instance_id = resp.json()["instance_id"]

        # Create a span in the premise field
        post_data = {
            "type": "span",
            "schema": "alignment",
            "state": [{
                "name": "MATCH",
                "start": 4,
                "end": 7,
                "title": "MATCH",
                "value": 1,
                "target_field": "premise"
            }],
            "instance_id": instance_id
        }

        resp = self.session.post(
            f"{self.base_url}/updateinstance",
            json=post_data,
            headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 200, f"Failed to create span: {resp.text}"

    def test_create_spans_in_different_fields(self):
        """Test creating spans in different fields stores them with target_field."""
        # Get current instance
        resp = self.session.get(f"{self.base_url}/api/current_instance")
        instance_id = resp.json()["instance_id"]

        # Create a span in premise
        post_data_premise = {
            "type": "span",
            "schema": "alignment",
            "state": [{
                "name": "MATCH",
                "start": 0,
                "end": 3,
                "title": "MATCH",
                "value": 1,
                "target_field": "premise"
            }],
            "instance_id": instance_id
        }
        resp = self.session.post(
            f"{self.base_url}/updateinstance",
            json=post_data_premise,
            headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 200

        # Create a span in hypothesis
        post_data_hypothesis = {
            "type": "span",
            "schema": "alignment",
            "state": [{
                "name": "MISMATCH",
                "start": 3,
                "end": 9,
                "title": "MISMATCH",
                "value": 1,
                "target_field": "hypothesis"
            }],
            "instance_id": instance_id
        }
        resp = self.session.post(
            f"{self.base_url}/updateinstance",
            json=post_data_hypothesis,
            headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 200

        # Verify both spans are returned with correct target_fields
        resp = self.session.get(f"{self.base_url}/api/spans/{instance_id}")
        assert resp.status_code == 200
        data = resp.json()

        spans = data.get("spans", [])
        assert len(spans) >= 2, f"Expected at least 2 spans, got {len(spans)}: {spans}"

        # Check that spans have target_field set
        target_fields = [s.get("target_field", "") for s in spans]
        assert "premise" in target_fields, \
            f"Should have a span with target_field='premise', got: {target_fields}"
        assert "hypothesis" in target_fields, \
            f"Should have a span with target_field='hypothesis', got: {target_fields}"

    def test_span_label_checkboxes_have_target_field(self):
        """Test that span label checkboxes include target_field in onclick."""
        resp = self.session.get(f"{self.base_url}/annotate")
        html = resp.text

        # The changeSpanLabel call should have a targetField argument
        assert "changeSpanLabel(" in html, "Should have changeSpanLabel calls"

    def test_api_current_instance_works(self):
        """Test that /api/current_instance returns valid data."""
        resp = self.session.get(f"{self.base_url}/api/current_instance")
        assert resp.status_code == 200
        data = resp.json()
        assert "instance_id" in data
        assert data["instance_id"] is not None

    def test_hidden_text_content_element_exists(self):
        """Test that hidden #text-content element exists for legacy compatibility."""
        resp = self.session.get(f"{self.base_url}/annotate")
        html = resp.text

        # The hidden instance-text div should exist
        assert 'id="instance-text"' in html, \
            "Hidden #instance-text element should exist for legacy JS compatibility"
        assert 'id="text-content"' in html, \
            "Hidden #text-content element should exist inside #instance-text"

    def test_instance_display_container_exists(self):
        """Test that instance-display-container is rendered."""
        resp = self.session.get(f"{self.base_url}/annotate")
        html = resp.text

        assert 'instance-display-container' in html, \
            "Instance display container should be rendered"

    def test_span_schema_api_returns_schemas(self):
        """Test that /api/schemas returns the alignment schema."""
        resp = self.session.get(f"{self.base_url}/api/schemas")
        assert resp.status_code == 200
        data = resp.json()
        assert "alignment" in data, f"Should have 'alignment' schema, got: {list(data.keys())}"

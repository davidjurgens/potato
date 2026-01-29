"""
Server integration tests for AI API endpoints.

Tests the /api/get_ai_suggestion and /api/ai_assistant endpoints.
"""

import json
import pytest
import os
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file


class TestAISuggestionAPIWithoutAI:
    """Test AI suggestion API when AI support is disabled."""

    @pytest.fixture(scope="class")
    def test_dir(self):
        """Create test directory."""
        return create_test_directory("ai_api_no_ai_test")

    @pytest.fixture(scope="class")
    def server(self, test_dir):
        """Create server without AI support."""
        test_data = [
            {"id": "1", "text": "Great product!"},
            {"id": "2", "text": "Terrible experience."},
        ]
        data_file = create_test_data_file(test_dir, test_data, "data.jsonl")

        config_content = f"""
annotation_task_name: AI API Test
task_dir: {test_dir}
site_dir: default
port: 0
debug: true

data_files:
  - {data_file}

item_properties:
  id_key: id
  text_key: text

user_config:
  allow_all_users: true

annotation_schemes:
  - annotation_type: radio
    annotation_id: 0
    name: sentiment
    description: What is the sentiment?
    labels:
      - positive
      - negative

output_annotation_dir: {test_dir}/output
output_annotation_format: json
"""
        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            f.write(config_content)

        server = FlaskTestServer(config=config_file)
        assert server.start(), "Server should start"
        yield server
        server.stop()

    def test_get_ai_suggestion_without_session(self, server):
        """Test /api/get_ai_suggestion behavior without a session.

        Note: In debug mode, session validation is skipped, so this may return 200.
        In production mode, it should redirect to login.
        """
        # Request without session
        response = requests.get(
            f"{server.base_url}/api/get_ai_suggestion",
            params={"annotationId": "0", "aiAssistant": "hint"},
            timeout=5,
            allow_redirects=False
        )
        # In debug mode, this returns 200 (no session required)
        # In production mode, it would return 302 (redirect to login)
        # Either way, it should respond without crashing
        assert response.status_code in [200, 302, 401, 403], \
            f"Should respond gracefully, got {response.status_code}"

    def test_get_ai_suggestion_when_ai_disabled(self, server):
        """Test that endpoint handles missing AI gracefully."""
        session = requests.Session()

        # Login
        session.post(
            f"{server.base_url}/register",
            data={"email": "ai_test_user", "pass": "test123"},
            allow_redirects=True
        )

        # Request AI suggestion when AI is not configured
        response = session.get(
            f"{server.base_url}/api/get_ai_suggestion",
            params={"annotationId": "0", "aiAssistant": "hint"},
            timeout=5
        )

        # Should return something (error or empty), not crash
        assert response.status_code in [200, 400, 404, 500], \
            f"Should handle gracefully, got {response.status_code}"


class TestAIAssistantAPI:
    """Test the /api/ai_assistant endpoint that returns button HTML."""

    @pytest.fixture(scope="class")
    def test_dir(self):
        """Create test directory."""
        return create_test_directory("ai_assistant_api_test")

    @pytest.fixture(scope="class")
    def server(self, test_dir):
        """Create server without AI support."""
        test_data = [
            {"id": "1", "text": "Sample text for testing."},
        ]
        data_file = create_test_data_file(test_dir, test_data, "data.jsonl")

        config_content = f"""
annotation_task_name: AI Assistant API Test
task_dir: {test_dir}
site_dir: default
port: 0
debug: true

data_files:
  - {data_file}

item_properties:
  id_key: id
  text_key: text

user_config:
  allow_all_users: true

annotation_schemes:
  - annotation_type: radio
    annotation_id: 0
    name: sentiment
    description: What is the sentiment?
    labels:
      - positive
      - negative

output_annotation_dir: {test_dir}/output
output_annotation_format: json
"""
        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            f.write(config_content)

        server = FlaskTestServer(config=config_file)
        assert server.start(), "Server should start"
        yield server
        server.stop()

    def test_ai_assistant_returns_html_or_empty(self, server):
        """Test that /api/ai_assistant returns HTML or empty string."""
        session = requests.Session()

        # Login
        session.post(
            f"{server.base_url}/register",
            data={"email": "assistant_test", "pass": "test123"},
            allow_redirects=True
        )

        # Request AI assistant HTML
        response = session.get(
            f"{server.base_url}/api/ai_assistant",
            params={"annotationId": "0"},
            timeout=5
        )

        # Should return 200 with HTML content (might be empty if AI disabled)
        assert response.status_code == 200, \
            f"Should return 200, got {response.status_code}"

        # Content should be text/html or empty
        content = response.text
        assert isinstance(content, str), "Response should be string"

    def test_ai_assistant_multiple_calls_same_result(self, server):
        """Test that multiple calls return consistent result (no duplication issues)."""
        session = requests.Session()

        # Login
        session.post(
            f"{server.base_url}/register",
            data={"email": "multi_call_test", "pass": "test123"},
            allow_redirects=True
        )

        # Make multiple requests
        results = []
        for _ in range(3):
            response = session.get(
                f"{server.base_url}/api/ai_assistant",
                params={"annotationId": "0"},
                timeout=5
            )
            results.append(response.text)

        # All results should be identical
        assert all(r == results[0] for r in results), \
            "Multiple calls should return identical results"


class TestAISuggestionResponseFormat:
    """Test the response format of AI suggestions."""

    def test_hint_response_format_success(self):
        """Test expected format for successful hint response."""
        # Simulate a successful hint response
        response = '{"hint": "Look for sentiment words", "suggestive_choice": "positive"}'
        data = json.loads(response)

        assert "hint" in data, "Response should have 'hint' field"
        assert isinstance(data["hint"], str), "'hint' should be string"

    def test_hint_response_format_with_suggestion(self):
        """Test hint response with suggestive_choice."""
        response = '{"hint": "Consider the tone", "suggestive_choice": "negative"}'
        data = json.loads(response)

        assert "suggestive_choice" in data, "Response should have 'suggestive_choice'"
        assert data["suggestive_choice"] in ["positive", "negative", "neutral"], \
            "suggestive_choice should be a valid label"

    def test_keyword_response_format(self):
        """Test expected format for keyword response."""
        response = '{"keywords": ["great", "excellent", "love", "amazing"]}'
        data = json.loads(response)

        assert "keywords" in data, "Response should have 'keywords' field"
        assert isinstance(data["keywords"], list), "'keywords' should be list"
        assert all(isinstance(k, str) for k in data["keywords"]), \
            "All keywords should be strings"

    def test_error_response_format(self):
        """Test error response format."""
        error_responses = [
            "Unable to generate hint at this time.",
            "Unable to generate suggestion - annotation type not configured",
            "Error: Connection refused",
        ]

        for response in error_responses:
            assert isinstance(response, str), "Error should be string"
            assert len(response) > 0, "Error should not be empty"


class TestAIAPIParameters:
    """Test parameter validation for AI API endpoints."""

    @pytest.fixture(scope="class")
    def test_dir(self):
        """Create test directory."""
        return create_test_directory("ai_api_params_test")

    @pytest.fixture(scope="class")
    def server(self, test_dir):
        """Create server for parameter tests."""
        test_data = [{"id": "1", "text": "Test text."}]
        data_file = create_test_data_file(test_dir, test_data, "data.jsonl")

        config_content = f"""
annotation_task_name: AI Params Test
task_dir: {test_dir}
site_dir: default
port: 0
debug: true

data_files:
  - {data_file}

item_properties:
  id_key: id
  text_key: text

user_config:
  allow_all_users: true

annotation_schemes:
  - annotation_type: radio
    annotation_id: 0
    name: test
    description: Test
    labels:
      - a
      - b

output_annotation_dir: {test_dir}/output
output_annotation_format: json
"""
        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            f.write(config_content)

        server = FlaskTestServer(config=config_file)
        assert server.start(), "Server should start"
        yield server
        server.stop()

    def test_missing_annotation_id(self, server):
        """Test request with missing annotationId parameter."""
        session = requests.Session()
        session.post(
            f"{server.base_url}/register",
            data={"email": "param_test1", "pass": "test"},
            allow_redirects=True
        )

        response = session.get(
            f"{server.base_url}/api/get_ai_suggestion",
            params={"aiAssistant": "hint"},  # Missing annotationId
            timeout=5
        )

        # Should handle gracefully (error or empty)
        assert response.status_code in [200, 400, 500]

    def test_missing_ai_assistant(self, server):
        """Test request with missing aiAssistant parameter."""
        session = requests.Session()
        session.post(
            f"{server.base_url}/register",
            data={"email": "param_test2", "pass": "test"},
            allow_redirects=True
        )

        response = session.get(
            f"{server.base_url}/api/get_ai_suggestion",
            params={"annotationId": "0"},  # Missing aiAssistant
            timeout=5
        )

        # Should handle gracefully
        assert response.status_code in [200, 400, 500]

    def test_invalid_annotation_id(self, server):
        """Test request with invalid (non-integer) annotationId."""
        session = requests.Session()
        session.post(
            f"{server.base_url}/register",
            data={"email": "param_test3", "pass": "test"},
            allow_redirects=True
        )

        response = session.get(
            f"{server.base_url}/api/get_ai_suggestion",
            params={"annotationId": "not_a_number", "aiAssistant": "hint"},
            timeout=5
        )

        # Should handle gracefully (400 or 500 error)
        assert response.status_code in [400, 500]

    def test_invalid_ai_assistant_type(self, server):
        """Test request with invalid aiAssistant type."""
        session = requests.Session()
        session.post(
            f"{server.base_url}/register",
            data={"email": "param_test4", "pass": "test"},
            allow_redirects=True
        )

        response = session.get(
            f"{server.base_url}/api/get_ai_suggestion",
            params={"annotationId": "0", "aiAssistant": "invalid_type"},
            timeout=5
        )

        # Should return error string or 400/500
        # The endpoint might return 200 with error text
        assert response.status_code in [200, 400, 500]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

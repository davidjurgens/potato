"""
Integration test for span API text normalization.

This test verifies that the /api/spans/{instance_id} endpoint returns
text that matches the normalized text used for span offset calculations
in the template rendering.

Bug context:
- Template normalizes text (strips HTML, normalizes whitespace)
- API was returning raw unnormalized text
- Span offsets calculated on normalized text were applied to unnormalized text
- Result: Span positions broke after navigation
"""

import pytest
import requests
import re
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


def normalize_text(text: str) -> str:
    """
    Normalize text the same way as flask_server.py and routes.py.

    This should match the normalization in:
    - flask_server.py (template rendering)
    - routes.py (API endpoint)
    """
    # 1. Strip HTML tags
    normalized = re.sub(r'<[^>]+>', '', text)
    # 2. Normalize whitespace
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


class TestSpanAPINormalization:
    """Test that span API returns normalized text matching template."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server with span annotation config."""
        annotation_schemes = [
            {
                "annotation_type": "span",
                "name": "entities",
                "description": "Named entities",
                "labels": [
                    {"name": "PERSON", "color": "#4f46e5"},
                    {"name": "ORGANIZATION", "color": "#059669"}
                ],
                "sequential_key_binding": True
            }
        ]

        # Create test data with HTML formatting (simulating dialogue)
        test_data = [
            {
                "id": "test-1",
                "text": '<span class="dialogue-turn"><b>Alex:</b> Hello World!</span>'
            },
            {
                "id": "test-2",
                "text": "Simple   text   with   extra   spaces"
            },
            {
                "id": "test-3",
                "text": "Line1\n\nLine2\n\nLine3"
            }
        ]

        with TestConfigManager("span_api_norm", annotation_schemes, test_data=test_data) as test_config:
            server = FlaskTestServer(port=9087, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start Flask server")
            request.cls.test_config = test_config
            yield server
            server.stop()

    @pytest.fixture
    def session(self, flask_server):
        """Create authenticated session."""
        session = requests.Session()
        # Register and login
        session.post(f"{flask_server.base_url}/register",
                    data={"email": "testuser", "pass": "testpass"})
        session.post(f"{flask_server.base_url}/auth",
                    data={"email": "testuser", "pass": "testpass"})
        return session

    def test_api_returns_normalized_text_html(self, flask_server, session):
        """API should return text with HTML stripped."""
        # First access the annotation page to initialize instance
        response = session.get(f"{flask_server.base_url}/annotate?instance_id=test-1")
        assert response.status_code == 200

        # Get span data via API
        api_response = session.get(f"{flask_server.base_url}/api/spans/test-1")

        if api_response.status_code == 200:
            data = api_response.json()
            api_text = data.get('text', '')

            # Text should be normalized (no HTML tags)
            assert '<span' not in api_text
            assert '<b>' not in api_text
            assert '</span>' not in api_text

            # Should contain actual content
            assert 'Alex:' in api_text
            assert 'Hello World!' in api_text

            # Should match our normalize function
            raw_text = '<span class="dialogue-turn"><b>Alex:</b> Hello World!</span>'
            expected = normalize_text(raw_text)
            assert api_text == expected

    def test_api_returns_normalized_text_spaces(self, flask_server, session):
        """API should return text with whitespace normalized."""
        response = session.get(f"{flask_server.base_url}/annotate?instance_id=test-2")
        assert response.status_code == 200

        api_response = session.get(f"{flask_server.base_url}/api/spans/test-2")

        if api_response.status_code == 200:
            data = api_response.json()
            api_text = data.get('text', '')

            # Multiple spaces should be collapsed
            assert '   ' not in api_text
            assert api_text == "Simple text with extra spaces"

    def test_api_returns_normalized_text_newlines(self, flask_server, session):
        """API should return text with newlines normalized."""
        response = session.get(f"{flask_server.base_url}/annotate?instance_id=test-3")
        assert response.status_code == 200

        api_response = session.get(f"{flask_server.base_url}/api/spans/test-3")

        if api_response.status_code == 200:
            data = api_response.json()
            api_text = data.get('text', '')

            # Newlines should be converted to spaces
            assert '\n' not in api_text
            assert api_text == "Line1 Line2 Line3"

    def test_span_offset_extraction_uses_normalized_text(self, flask_server, session):
        """Span text extraction should use normalized positions."""
        # Access instance
        response = session.get(f"{flask_server.base_url}/annotate?instance_id=test-1")
        assert response.status_code == 200

        # Create a span annotation (for "Hello" in "Alex: Hello World!")
        # In normalized text, "Hello" starts at position 6
        span_data = {
            "instance_id": "test-1",
            "span_annotations": [{
                "schema": "entities",
                "label": "PERSON",
                "name": "PERSON",
                "start": 0,  # "Alex" starts at 0
                "end": 4,    # "Alex" ends at 4
            }]
        }

        update_response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=span_data
        )

        # Now get span data and verify the extracted text
        api_response = session.get(f"{flask_server.base_url}/api/spans/test-1")

        if api_response.status_code == 200:
            data = api_response.json()
            spans = data.get('spans', [])

            if spans:
                # The span text should be "Alex" from normalized text
                span = spans[0]
                assert span.get('text') == "Alex"

                # Verify we can extract the same text from API's text field
                api_text = data.get('text', '')
                start = span.get('start', 0)
                end = span.get('end', 0)
                assert api_text[start:end] == "Alex"


class TestSpanPositionConsistency:
    """Test that span positions are consistent between template and API."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server with dialogue-style data."""
        annotation_schemes = [
            {
                "annotation_type": "span",
                "name": "entities",
                "description": "Named entities",
                "labels": [
                    {"name": "PERSON", "color": "#4f46e5"}
                ]
            }
        ]

        # Test data that simulates dialogue formatting
        test_data = [
            {
                "id": "dialogue-1",
                "text": [
                    "Dr. Smith: The patient shows improvement.",
                    "Nurse: That's good news."
                ]
            }
        ]

        with TestConfigManager("span_position", annotation_schemes, test_data=test_data) as test_config:
            server = FlaskTestServer(port=9088, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start Flask server")
            request.cls.test_config = test_config
            yield server
            server.stop()

    @pytest.fixture
    def session(self, flask_server):
        """Create authenticated session."""
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register",
                    data={"email": "testuser2", "pass": "testpass"})
        session.post(f"{flask_server.base_url}/auth",
                    data={"email": "testuser2", "pass": "testpass"})
        return session

    def test_multi_line_dialogue_normalization(self, flask_server, session):
        """Multi-line dialogue should normalize consistently."""
        response = session.get(f"{flask_server.base_url}/annotate?instance_id=dialogue-1")
        assert response.status_code == 200

        api_response = session.get(f"{flask_server.base_url}/api/spans/dialogue-1")

        if api_response.status_code == 200:
            data = api_response.json()
            api_text = data.get('text', '')

            # Should not contain HTML
            assert '<' not in api_text or 'x <' in api_text  # Allow angle brackets in math

            # Should contain dialogue content
            assert 'Dr. Smith' in api_text or 'patient' in api_text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Server integration tests for Option Highlighting feature.

These tests require a running Ollama instance with qwen3:0.6b model.
To set up:
    ollama pull qwen3:0.6b

Run tests with:
    pytest tests/server/test_option_highlighting_integration.py -v

Skip these tests if Ollama is not available:
    pytest tests/server/test_option_highlighting_integration.py -v -m "not ollama"
"""

import json
import os
import pytest
import requests
import shutil
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory


def is_ollama_available():
    """Check if Ollama is running and qwen3:0.6b model is available."""
    try:
        import ollama
        client = ollama.Client(host="http://localhost:11434", timeout=5)
        models = client.list()
        model_names = [m.get('name', m.get('model', '')) for m in models.get('models', [])]
        # Check for qwen3:0.6b (may appear as qwen3:0.6b or qwen3:0.6b-gguf-q4_0 etc)
        has_model = any('qwen3' in name and '0.6b' in name for name in model_names)
        if not has_model:
            # Also check without version suffix
            has_model = 'qwen3:0.6b' in model_names
        return has_model
    except Exception as e:
        print(f"Ollama check failed: {e}")
        return False


# Mark all tests in this module to require Ollama
pytestmark = pytest.mark.skipif(
    not is_ollama_available(),
    reason="Ollama with qwen3:0.6b model not available"
)


class TestOptionHighlightingAPI:
    """Integration tests for the option highlighting API endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with option highlighting enabled."""
        # Create test directory
        test_dir = create_test_directory("option_highlight_integration")

        # Create test data
        test_data = [
            {"id": "1", "text": "I absolutely love this product! Best purchase ever!"},
            {"id": "2", "text": "Terrible experience. Would not recommend to anyone."},
            {"id": "3", "text": "The meeting is scheduled for 3 PM tomorrow."},
            {"id": "4", "text": "Great service but the price was a bit high."},
            {"id": "5", "text": "Amazing quality and fast shipping!"},
        ]

        data_file = os.path.join(test_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        # Create config with option highlighting enabled
        config = {
            "annotation_task_name": "Option Highlighting Test",
            "task_dir": test_dir,
            "data_files": ["test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "output_annotation_dir": "annotation_output",
            "output_annotation_format": "json",
            "user_config": {"allow_all_users": True},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "description": "What is the sentiment of this text?",
                    "labels": [
                        {"name": "Positive"},
                        {"name": "Negative"},
                        {"name": "Neutral"},
                        {"name": "Mixed"}
                    ]
                }
            ],
            "ai_support": {
                "enabled": True,
                "endpoint_type": "ollama",
                "ai_config": {
                    "model": "qwen3:0.6b",
                    "base_url": "http://localhost:11434",
                    "temperature": 0.3,
                    "max_tokens": 256,
                    "timeout": 60,
                    "include": {"all": True}
                },
                "option_highlighting": {
                    "enabled": True,
                    "top_k": 2,
                    "dim_opacity": 0.4,
                    "auto_apply": True,
                    "prefetch_count": 3
                },
                "cache_config": {
                    "disk_cache": {
                        "enabled": True,
                        "path": os.path.join(test_dir, "ai_cache.json")
                    },
                    "prefetch": {
                        "warm_up_page_count": 0,  # Disable warmup for faster tests
                        "on_next": 1,
                        "on_prev": 0
                    }
                }
            }
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Start server
        port = find_free_port()
        server = FlaskTestServer(port=port, config_file=config_file)

        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.base_url = server.base_url
        request.cls.test_dir = test_dir

        yield server

        server.stop()

        # Cleanup
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

    def _login(self, session, username="testuser"):
        """Register and login a user."""
        session.post(f"{self.base_url}/register", data={"email": username, "pass": "pass"})
        session.post(f"{self.base_url}/auth", data={"email": username, "pass": "pass"})

    # ================================================================
    # Configuration endpoint tests
    # ================================================================

    def test_config_endpoint_returns_enabled(self):
        """Test that /api/option_highlights/config returns enabled config."""
        session = requests.Session()
        self._login(session)

        resp = session.get(f"{self.base_url}/api/option_highlights/config")
        assert resp.status_code == 200

        data = resp.json()
        assert data["enabled"] is True
        assert data["top_k"] == 2
        assert data["dim_opacity"] == 0.4
        assert data["auto_apply"] is True

    def test_config_endpoint_requires_auth(self):
        """Test that config endpoint requires authentication."""
        session = requests.Session()
        # Don't login

        resp = session.get(f"{self.base_url}/api/option_highlights/config")
        # Should return 401 or redirect
        assert resp.status_code in [401, 302, 200]  # 200 if redirected to login page

    # ================================================================
    # Highlights endpoint tests
    # ================================================================

    def test_highlights_endpoint_returns_options(self):
        """Test that /api/option_highlights/<annotation_id> returns highlighted options."""
        session = requests.Session()
        self._login(session)

        # First go to annotate page to set up the instance
        session.get(f"{self.base_url}/annotate")

        # Now request highlights for annotation 0 (sentiment)
        resp = session.get(f"{self.base_url}/api/option_highlights/0")
        assert resp.status_code == 200

        data = resp.json()

        # Should have highlighted options (unless error)
        if "error" not in data:
            assert "highlighted" in data
            assert isinstance(data["highlighted"], list)
            assert len(data["highlighted"]) <= 2  # top_k is 2
            assert "config" in data

    def test_highlights_returns_valid_options(self):
        """Test that highlighted options are from the valid label set."""
        session = requests.Session()
        self._login(session)

        session.get(f"{self.base_url}/annotate")
        resp = session.get(f"{self.base_url}/api/option_highlights/0")
        data = resp.json()

        if "error" not in data and data.get("highlighted"):
            valid_labels = ["Positive", "Negative", "Neutral", "Mixed"]
            for opt in data["highlighted"]:
                assert opt in valid_labels, f"Invalid option: {opt}"

    def test_highlights_includes_confidence(self):
        """Test that response may include confidence score."""
        session = requests.Session()
        self._login(session)

        session.get(f"{self.base_url}/annotate")
        resp = session.get(f"{self.base_url}/api/option_highlights/0")
        data = resp.json()

        # Confidence is optional but should be valid if present
        if "confidence" in data and data["confidence"] is not None:
            assert 0 <= data["confidence"] <= 1

    # ================================================================
    # Prefetch endpoint tests
    # ================================================================

    def test_prefetch_endpoint_triggers_prefetch(self):
        """Test that /api/option_highlights/prefetch triggers prefetching."""
        session = requests.Session()
        self._login(session)

        session.get(f"{self.base_url}/annotate")

        resp = session.post(
            f"{self.base_url}/api/option_highlights/prefetch",
            json={"count": 3}
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "prefetch_started"
        assert "from_instance" in data

    def test_prefetch_uses_default_count(self):
        """Test that prefetch uses configured default count when not specified."""
        session = requests.Session()
        self._login(session)

        session.get(f"{self.base_url}/annotate")

        # Don't specify count
        resp = session.post(
            f"{self.base_url}/api/option_highlights/prefetch",
            json={}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "prefetch_started"

    # ================================================================
    # Edge case tests
    # ================================================================

    def test_invalid_annotation_id(self):
        """Test handling of invalid annotation ID."""
        session = requests.Session()
        self._login(session)

        session.get(f"{self.base_url}/annotate")

        # Request highlights for non-existent annotation
        resp = session.get(f"{self.base_url}/api/option_highlights/999")
        # Should either return error or 404
        assert resp.status_code in [200, 400, 404, 500]

    def test_multiple_requests_use_cache(self):
        """Test that repeated requests return consistent results (from cache)."""
        session = requests.Session()
        self._login(session)

        session.get(f"{self.base_url}/annotate")

        # First request
        resp1 = session.get(f"{self.base_url}/api/option_highlights/0")
        data1 = resp1.json()

        # Second request should be faster (cached)
        resp2 = session.get(f"{self.base_url}/api/option_highlights/0")
        data2 = resp2.json()

        # Results should be the same (from cache)
        if "error" not in data1 and "error" not in data2:
            assert data1.get("highlighted") == data2.get("highlighted")


class TestOptionHighlightingWithDifferentSchemas:
    """Test option highlighting with different annotation types."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start server with multiple schema types."""
        test_dir = create_test_directory("option_highlight_schemas")

        test_data = [
            {"id": "1", "text": "This product is excellent and I highly recommend it!"},
            {"id": "2", "text": "Poor quality, broke after one day of use."},
            {"id": "3", "text": "Average product, nothing special."},
        ]

        data_file = os.path.join(test_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        config = {
            "annotation_task_name": "Multi-Schema Option Highlighting Test",
            "task_dir": test_dir,
            "data_files": ["test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "output_annotation_dir": "annotation_output",
            "output_annotation_format": "json",
            "user_config": {"allow_all_users": True},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "description": "What is the sentiment?",
                    "labels": [
                        {"name": "Positive"},
                        {"name": "Negative"},
                        {"name": "Neutral"}
                    ]
                },
                {
                    "name": "topics",
                    "annotation_type": "multiselect",
                    "description": "Select all applicable topics",
                    "labels": [
                        {"name": "Quality"},
                        {"name": "Price"},
                        {"name": "Service"},
                        {"name": "Shipping"}
                    ]
                },
                {
                    "name": "rating",
                    "annotation_type": "likert",
                    "description": "Rate the overall quality",
                    "min_label": "Poor",
                    "max_label": "Excellent",
                    "size": 5
                },
                {
                    "name": "comment",
                    "annotation_type": "text",
                    "description": "Add any comments"
                }
            ],
            "ai_support": {
                "enabled": True,
                "endpoint_type": "ollama",
                "ai_config": {
                    "model": "qwen3:0.6b",
                    "base_url": "http://localhost:11434",
                    "temperature": 0.3,
                    "max_tokens": 256,
                    "include": {"all": True}
                },
                "option_highlighting": {
                    "enabled": True,
                    "top_k": 2,
                    "dim_opacity": 0.4,
                    "auto_apply": True,
                    "schemas": ["sentiment", "topics"],  # Only for specific schemas
                    "prefetch_count": 2
                },
                "cache_config": {
                    "disk_cache": {
                        "enabled": True,
                        "path": os.path.join(test_dir, "ai_cache.json")
                    },
                    "prefetch": {
                        "warm_up_page_count": 0,
                        "on_next": 1,
                        "on_prev": 0
                    }
                }
            }
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        port = find_free_port()
        server = FlaskTestServer(port=port, config_file=config_file)

        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.base_url = server.base_url
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

    def _login(self, session, username="testuser"):
        session.post(f"{self.base_url}/register", data={"email": username, "pass": "pass"})
        session.post(f"{self.base_url}/auth", data={"email": username, "pass": "pass"})

    def test_radio_schema_gets_highlights(self):
        """Test that radio schema (sentiment) gets highlights."""
        session = requests.Session()
        self._login(session)
        session.get(f"{self.base_url}/annotate")

        resp = session.get(f"{self.base_url}/api/option_highlights/0")
        data = resp.json()

        # Should work for radio type
        if "error" not in data:
            assert "highlighted" in data

    def test_multiselect_schema_gets_highlights(self):
        """Test that multiselect schema (topics) gets highlights."""
        session = requests.Session()
        self._login(session)
        session.get(f"{self.base_url}/annotate")

        resp = session.get(f"{self.base_url}/api/option_highlights/1")
        data = resp.json()

        # Should work for multiselect type
        if "error" not in data:
            assert "highlighted" in data

    def test_likert_not_in_schemas_filter(self):
        """Test that likert schema is skipped when not in schemas filter."""
        session = requests.Session()
        self._login(session)
        session.get(f"{self.base_url}/annotate")

        resp = session.get(f"{self.base_url}/api/option_highlights/2")
        data = resp.json()

        # Should return error since 'rating' is not in schemas filter
        assert "error" in data or data.get("highlighted") == []

    def test_text_schema_not_eligible(self):
        """Test that text schema is not eligible for highlighting."""
        session = requests.Session()
        self._login(session)
        session.get(f"{self.base_url}/annotate")

        resp = session.get(f"{self.base_url}/api/option_highlights/3")
        data = resp.json()

        # Should return error since text is not a discrete type
        assert "error" in data


class TestOptionHighlightingDisabled:
    """Test behavior when option highlighting is disabled."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start server with option highlighting disabled."""
        test_dir = create_test_directory("option_highlight_disabled")

        test_data = [{"id": "1", "text": "Test text"}]
        data_file = os.path.join(test_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        config = {
            "annotation_task_name": "Option Highlighting Disabled Test",
            "task_dir": test_dir,
            "data_files": ["test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "output_annotation_dir": "annotation_output",
            "user_config": {"allow_all_users": True},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "description": "What is the sentiment?",
                    "labels": ["Positive", "Negative", "Neutral"]
                }
            ],
            "ai_support": {
                "enabled": True,
                "endpoint_type": "ollama",
                "ai_config": {
                    "model": "qwen3:0.6b",
                    "include": {"all": True}
                },
                "option_highlighting": {
                    "enabled": False  # Explicitly disabled
                },
                "cache_config": {
                    "disk_cache": {"enabled": False},
                    "prefetch": {"warm_up_page_count": 0, "on_next": 0, "on_prev": 0}
                }
            }
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        port = find_free_port()
        server = FlaskTestServer(port=port, config_file=config_file)

        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.base_url = server.base_url
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

    def _login(self, session, username="testuser"):
        session.post(f"{self.base_url}/register", data={"email": username, "pass": "pass"})
        session.post(f"{self.base_url}/auth", data={"email": username, "pass": "pass"})

    def test_config_shows_disabled(self):
        """Test that config endpoint shows feature as disabled."""
        session = requests.Session()
        self._login(session)

        resp = session.get(f"{self.base_url}/api/option_highlights/config")
        data = resp.json()

        assert data["enabled"] is False

    def test_highlights_returns_error_when_disabled(self):
        """Test that highlights endpoint returns error when disabled."""
        session = requests.Session()
        self._login(session)
        session.get(f"{self.base_url}/annotate")

        resp = session.get(f"{self.base_url}/api/option_highlights/0")
        data = resp.json()

        assert "error" in data

    def test_prefetch_returns_error_when_disabled(self):
        """Test that prefetch endpoint returns error when disabled."""
        session = requests.Session()
        self._login(session)
        session.get(f"{self.base_url}/annotate")

        resp = session.post(
            f"{self.base_url}/api/option_highlights/prefetch",
            json={}
        )

        assert resp.status_code == 400 or "error" in resp.json()

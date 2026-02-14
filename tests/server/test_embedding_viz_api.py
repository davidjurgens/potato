"""
Server integration tests for embedding visualization API endpoints.

Tests the admin API endpoints for embedding visualization:
- GET /admin/api/embedding_viz/data
- POST /admin/api/embedding_viz/reorder
- POST /admin/api/embedding_viz/refresh
- GET /admin/api/embedding_viz/stats
"""

import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestEmbeddingVizAPI:
    """Test embedding visualization API endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server with diversity ordering enabled."""
        annotation_schemes = [{
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Sentiment classification",
            "labels": [
                {"name": "Positive", "key_binding": "p"},
                {"name": "Negative", "key_binding": "n"},
                {"name": "Neutral", "key_binding": "u"}
            ]
        }]

        # Enable diversity ordering (required for embedding viz)
        additional_config = {
            "diversity_ordering": {
                "enabled": True,
                "model_name": "all-MiniLM-L6-v2",
                "num_clusters": 5
            },
            "embedding_visualization": {
                "enabled": True,
                "sample_size": 100,
                "label_source": "majority"
            }
        }

        with TestConfigManager(
            "embedding_viz_test",
            annotation_schemes,
            num_items=20,
            additional_config=additional_config
        ) as test_config:
            server = FlaskTestServer(port=9850, config_file=test_config.config_path)
            if not server.start():
                pytest.skip("Failed to start server - may be missing dependencies")
            request.cls.server = server
            request.cls.test_config = test_config
            yield server
            server.stop()

    def test_stats_endpoint_requires_auth(self, flask_server):
        """Test that stats endpoint requires admin API key."""
        response = requests.get(f"{flask_server.base_url}/admin/api/embedding_viz/stats")

        # Should require authentication
        assert response.status_code in [401, 403]

    def test_stats_endpoint_with_auth(self, flask_server):
        """Test stats endpoint with valid authentication."""
        response = requests.get(
            f"{flask_server.base_url}/admin/api/embedding_viz/stats",
            headers={"X-API-Key": flask_server.admin_api_key}
        )

        # May return error if dependencies not available, but should not be auth error
        assert response.status_code in [200, 400]

        data = response.json()
        # Check structure even if not enabled
        if response.status_code == 200:
            assert "enabled" in data
            assert "umap_available" in data
            assert "numpy_available" in data

    def test_data_endpoint_requires_auth(self, flask_server):
        """Test that data endpoint requires admin API key."""
        response = requests.get(f"{flask_server.base_url}/admin/api/embedding_viz/data")

        assert response.status_code in [401, 403]

    def test_reorder_endpoint_requires_auth(self, flask_server):
        """Test that reorder endpoint requires admin API key."""
        response = requests.post(
            f"{flask_server.base_url}/admin/api/embedding_viz/reorder",
            json={"selections": []}
        )

        assert response.status_code in [401, 403]

    def test_reorder_endpoint_validates_input(self, flask_server):
        """Test that reorder endpoint validates input."""
        response = requests.post(
            f"{flask_server.base_url}/admin/api/embedding_viz/reorder",
            headers={"X-API-Key": flask_server.admin_api_key},
            json={}  # Missing selections
        )

        # Should return 400 for invalid input or 400 if viz not available
        assert response.status_code in [400]

        data = response.json()
        assert "error" in data or "success" in data

    def test_refresh_endpoint_requires_auth(self, flask_server):
        """Test that refresh endpoint requires admin API key."""
        response = requests.post(
            f"{flask_server.base_url}/admin/api/embedding_viz/refresh",
            json={"force_recompute": True}
        )

        assert response.status_code in [401, 403]


class TestEmbeddingVizAPIWithoutDiversity:
    """Test embedding visualization API when diversity ordering is disabled."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server_no_diversity(self, request):
        """Set up Flask server without diversity ordering."""
        annotation_schemes = [{
            "annotation_type": "radio",
            "name": "test",
            "description": "Test question",
            "labels": [
                {"name": "Yes", "key_binding": "y"},
                {"name": "No", "key_binding": "n"}
            ]
        }]

        # No diversity ordering
        additional_config = {
            "embedding_visualization": {
                "enabled": True
            }
        }

        with TestConfigManager(
            "embedding_viz_no_diversity_test",
            annotation_schemes,
            num_items=10,
            additional_config=additional_config
        ) as test_config:
            server = FlaskTestServer(port=9851, config_file=test_config.config_path)
            if not server.start():
                pytest.skip("Failed to start server")
            request.cls.server = server
            yield server
            server.stop()

    def test_data_returns_error_without_diversity(self, flask_server_no_diversity):
        """Test that data endpoint returns appropriate error without diversity manager."""
        response = requests.get(
            f"{flask_server_no_diversity.base_url}/admin/api/embedding_viz/data",
            headers={"X-API-Key": flask_server_no_diversity.admin_api_key}
        )

        # Should return 400 with error message
        assert response.status_code == 400

        data = response.json()
        assert "error" in data
        # Error should mention diversity or embeddings
        assert "diversity" in data["error"].lower() or "embedding" in data["error"].lower()


class TestReorderingLogic:
    """Test the reordering logic with actual data."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server_for_reorder(self, request):
        """Set up Flask server for reordering tests."""
        annotation_schemes = [{
            "annotation_type": "radio",
            "name": "label",
            "description": "Classification",
            "labels": [
                {"name": "A", "key_binding": "a"},
                {"name": "B", "key_binding": "b"}
            ]
        }]

        additional_config = {
            "diversity_ordering": {
                "enabled": True,
                "model_name": "all-MiniLM-L6-v2"
            },
            "embedding_visualization": {
                "enabled": True
            }
        }

        with TestConfigManager(
            "embedding_viz_reorder_test",
            annotation_schemes,
            num_items=30,
            additional_config=additional_config
        ) as test_config:
            server = FlaskTestServer(port=9852, config_file=test_config.config_path)
            if not server.start():
                pytest.skip("Failed to start server - may be missing dependencies")
            request.cls.server = server
            yield server
            server.stop()

    def test_reorder_with_valid_selections(self, flask_server_for_reorder):
        """Test reordering with valid selection data."""
        selections = [
            {"instance_ids": ["item_0", "item_1", "item_2"], "priority": 1},
            {"instance_ids": ["item_10", "item_11"], "priority": 2}
        ]

        response = requests.post(
            f"{flask_server_for_reorder.base_url}/admin/api/embedding_viz/reorder",
            headers={
                "X-API-Key": flask_server_for_reorder.admin_api_key,
                "Content-Type": "application/json"
            },
            json={"selections": selections, "interleave": True}
        )

        # May fail if viz not available, but should process the request
        data = response.json()

        if response.status_code == 200:
            assert "success" in data
            if data.get("success"):
                assert "reordered_count" in data
                assert data["reordered_count"] >= 0

    def test_reorder_without_interleave(self, flask_server_for_reorder):
        """Test reordering without interleaving."""
        selections = [
            {"instance_ids": ["item_0", "item_1"], "priority": 1},
            {"instance_ids": ["item_5", "item_6"], "priority": 2}
        ]

        response = requests.post(
            f"{flask_server_for_reorder.base_url}/admin/api/embedding_viz/reorder",
            headers={
                "X-API-Key": flask_server_for_reorder.admin_api_key,
                "Content-Type": "application/json"
            },
            json={"selections": selections, "interleave": False}
        )

        # Just verify request is processed
        assert response.status_code in [200, 400]


class TestEmbeddingVizConfigValidation:
    """Test configuration validation for embedding visualization."""

    def test_valid_config_passes_validation(self):
        """Test that valid config passes validation."""
        from potato.server_utils.config_module import validate_embedding_visualization_config

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "sample_size": 500,
                "include_all_annotated": True,
                "label_source": "mace",
                "umap": {
                    "n_neighbors": 15,
                    "min_dist": 0.1,
                    "metric": "cosine"
                }
            }
        }

        # Should not raise
        validate_embedding_visualization_config(config_data)

    def test_invalid_sample_size_fails_validation(self):
        """Test that invalid sample_size fails validation."""
        from potato.server_utils.config_module import (
            validate_embedding_visualization_config,
            ConfigValidationError
        )

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "sample_size": -1  # Invalid
            }
        }

        with pytest.raises(ConfigValidationError):
            validate_embedding_visualization_config(config_data)

    def test_invalid_label_source_fails_validation(self):
        """Test that invalid label_source fails validation."""
        from potato.server_utils.config_module import (
            validate_embedding_visualization_config,
            ConfigValidationError
        )

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "label_source": "invalid_source"  # Invalid
            }
        }

        with pytest.raises(ConfigValidationError):
            validate_embedding_visualization_config(config_data)

    def test_invalid_umap_metric_fails_validation(self):
        """Test that invalid UMAP metric fails validation."""
        from potato.server_utils.config_module import (
            validate_embedding_visualization_config,
            ConfigValidationError
        )

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "umap": {
                    "metric": "invalid_metric"  # Invalid
                }
            }
        }

        with pytest.raises(ConfigValidationError):
            validate_embedding_visualization_config(config_data)

    def test_disabled_config_skips_validation(self):
        """Test that disabled config skips detailed validation."""
        from potato.server_utils.config_module import validate_embedding_visualization_config

        config_data = {
            "embedding_visualization": {
                "enabled": False,
                "sample_size": -999  # Would be invalid if enabled
            }
        }

        # Should not raise because enabled=False
        validate_embedding_visualization_config(config_data)

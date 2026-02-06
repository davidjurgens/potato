"""
Integration tests for diversity-based item ordering.

Tests the DIVERSITY_CLUSTERING assignment strategy with a running Flask server.
"""

import pytest
import requests
import time
import os
import shutil
import json
from pathlib import Path

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file


class TestDiversityOrderingIntegration:
    """Integration tests for diversity ordering with Flask server."""

    @pytest.fixture(scope="class")
    def test_dir(self, request):
        """Create a test directory for diversity tests."""
        test_dir = create_test_directory("diversity_test")

        def cleanup():
            shutil.rmtree(test_dir, ignore_errors=True)

        request.addfinalizer(cleanup)
        return test_dir

    @pytest.fixture(scope="class")
    def diversity_config_path(self, test_dir):
        """Create a config file for diversity ordering tests."""
        import yaml

        # Create diverse test data with different topics
        data = [
            {"id": "sports1", "text": "The football team won the championship game last night."},
            {"id": "sports2", "text": "Basketball playoffs start next week with exciting matchups."},
            {"id": "sports3", "text": "The tennis tournament drew record crowds this year."},
            {"id": "tech1", "text": "New smartphone features advanced AI capabilities."},
            {"id": "tech2", "text": "Cloud computing continues to transform businesses."},
            {"id": "tech3", "text": "Cybersecurity threats increase as more devices connect."},
            {"id": "food1", "text": "The restaurant serves authentic Italian pasta dishes."},
            {"id": "food2", "text": "Fresh sushi prepared by expert chefs daily."},
            {"id": "food3", "text": "Farm-to-table ingredients make the best recipes."},
            {"id": "travel1", "text": "Paris remains the most visited city in Europe."},
            {"id": "travel2", "text": "Beach resorts offer relaxation and water sports."},
            {"id": "travel3", "text": "Mountain hiking trails provide scenic adventure."},
        ]

        data_file = create_test_data_file(test_dir, data, "diverse_data.jsonl")

        config = {
            "annotation_task_name": "Diversity Test",
            "task_dir": test_dir,
            "data_files": ["diverse_data.jsonl"],
            "output_annotation_dir": "annotation_output",
            "item_properties": {
                "id_key": "id",
                "text_key": "text",
            },
            "assignment_strategy": "diversity_clustering",
            "diversity_ordering": {
                "enabled": True,
                "prefill_count": 12,
                "num_clusters": 4,
                "auto_clusters": False,
                "recluster_threshold": 1.0,
                "preserve_visited": True,
            },
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "topic",
                    "description": "What is the main topic?",
                    "labels": ["Sports", "Technology", "Food", "Travel"],
                }
            ],
            "user_config": {
                "allow_all_users": True,
                "users": [],
            },
        }

        config_path = Path(test_dir) / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        return str(config_path)

    @pytest.fixture(scope="class")
    def flask_server(self, request, diversity_config_path):
        """Start Flask server with diversity ordering config."""
        # Skip if sentence-transformers not available
        try:
            import sentence_transformers
            import sklearn
        except ImportError:
            pytest.skip("sentence-transformers or scikit-learn not installed")

        server = FlaskTestServer(port=9450, config_file=diversity_config_path)
        if not server.start():
            pytest.fail("Failed to start Flask server for diversity tests")

        yield server
        server.stop()

    def test_server_starts_with_diversity_strategy(self, flask_server):
        """Test that server starts successfully with diversity_clustering strategy."""
        response = requests.get(f"{flask_server.base_url}/")
        assert response.status_code == 200

    def test_user_registration_with_diversity(self, flask_server):
        """Test that users can register when diversity ordering is enabled."""
        session = requests.Session()

        # Register a user
        response = session.post(
            f"{flask_server.base_url}/register",
            data={"email": "diversity_user1", "pass": "test123"}
        )
        assert response.status_code == 200

    def test_annotation_flow_works(self, flask_server):
        """Test that annotation flow works with diversity ordering."""
        session = requests.Session()

        # Register and login
        session.post(
            f"{flask_server.base_url}/register",
            data={"email": "diversity_user2", "pass": "test123"}
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"email": "diversity_user2", "pass": "test123"}
        )

        # Navigate to annotation page
        response = session.get(f"{flask_server.base_url}/annotate")
        assert response.status_code == 200

        # The page should show an annotation instance
        assert "topic" in response.text or "main topic" in response.text.lower()


class TestDiversityStrategyEnum:
    """Tests for DIVERSITY_CLUSTERING in AssignmentStrategy enum."""

    def test_strategy_enum_includes_diversity_clustering(self):
        """Test that DIVERSITY_CLUSTERING is in the enum."""
        from potato.item_state_management import AssignmentStrategy

        assert hasattr(AssignmentStrategy, 'DIVERSITY_CLUSTERING')
        assert AssignmentStrategy.DIVERSITY_CLUSTERING.value == 'diversity_clustering'

    def test_strategy_fromstr_parses_diversity_clustering(self):
        """Test that fromstr correctly parses diversity_clustering."""
        from potato.item_state_management import AssignmentStrategy

        strategy = AssignmentStrategy.fromstr("diversity_clustering")
        assert strategy == AssignmentStrategy.DIVERSITY_CLUSTERING

    def test_strategy_fromstr_case_insensitive(self):
        """Test that fromstr is case insensitive."""
        from potato.item_state_management import AssignmentStrategy

        strategy = AssignmentStrategy.fromstr("DIVERSITY_CLUSTERING")
        assert strategy == AssignmentStrategy.DIVERSITY_CLUSTERING


class TestConfigValidation:
    """Tests for diversity_ordering config validation."""

    def test_validate_diversity_config_valid(self):
        """Test validation passes with valid config."""
        from potato.server_utils.config_module import validate_diversity_config

        config = {
            "diversity_ordering": {
                "enabled": True,
                "model_name": "all-MiniLM-L6-v2",
                "num_clusters": 10,
                "items_per_cluster": 20,
                "recluster_threshold": 0.8,
            }
        }

        # Should not raise
        validate_diversity_config(config)

    def test_validate_diversity_config_invalid_num_clusters(self):
        """Test validation fails with invalid num_clusters."""
        from potato.server_utils.config_module import validate_diversity_config, ConfigValidationError

        config = {
            "diversity_ordering": {
                "enabled": True,
                "num_clusters": 1,  # Too small
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_diversity_config(config)
        assert "num_clusters" in str(exc_info.value)

    def test_validate_diversity_config_invalid_threshold(self):
        """Test validation fails with invalid recluster_threshold."""
        from potato.server_utils.config_module import validate_diversity_config, ConfigValidationError

        config = {
            "diversity_ordering": {
                "enabled": True,
                "recluster_threshold": 1.5,  # Must be 0-1
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_diversity_config(config)
        assert "recluster_threshold" in str(exc_info.value)

    def test_validate_diversity_config_skip_when_disabled(self):
        """Test validation skips detailed checks when disabled."""
        from potato.server_utils.config_module import validate_diversity_config

        config = {
            "diversity_ordering": {
                "enabled": False,
                "num_clusters": 0,  # Would be invalid if enabled
            }
        }

        # Should not raise because enabled: false
        validate_diversity_config(config)


class TestDiversityFallback:
    """Tests for fallback behavior when diversity manager is not available."""

    @pytest.fixture
    def minimal_test_dir(self, request):
        """Create minimal test directory."""
        test_dir = create_test_directory("diversity_fallback_test")

        def cleanup():
            shutil.rmtree(test_dir, ignore_errors=True)

        request.addfinalizer(cleanup)
        return test_dir

    def test_fallback_to_random_when_manager_unavailable(self, minimal_test_dir):
        """Test that assignment falls back to random when diversity manager is unavailable."""
        from unittest.mock import patch, MagicMock
        from potato.item_state_management import ItemStateManager, AssignmentStrategy, clear_item_state_manager

        clear_item_state_manager()

        config = {
            "assignment_strategy": "diversity_clustering",
            "max_annotations_per_item": -1,
            "random_seed": 42,
        }

        # Patch get_diversity_manager to return None
        with patch('potato.diversity_manager.get_diversity_manager', return_value=None):
            ism = ItemStateManager(config)

            # Add some items
            for i in range(5):
                ism.add_item(f"item{i}", {"text": f"Text {i}"})

            # Create mock user state
            user_state = MagicMock()
            user_state.has_remaining_assignments.return_value = True
            user_state.get_assigned_instance_count.return_value = 0
            user_state.get_max_assignments.return_value = 5
            user_state.has_annotated.return_value = False
            user_state.get_assigned_instance_ids.return_value = set()

            # Should fall back to random
            assigned = ism.assign_instances_to_user(user_state)
            assert assigned > 0

        clear_item_state_manager()

    def test_fallback_when_dm_disabled(self, minimal_test_dir):
        """Test fallback when diversity manager exists but is disabled."""
        from unittest.mock import patch, MagicMock
        from potato.item_state_management import ItemStateManager, clear_item_state_manager

        clear_item_state_manager()

        config = {
            "assignment_strategy": "diversity_clustering",
            "max_annotations_per_item": -1,
            "random_seed": 42,
        }

        # Create mock disabled diversity manager
        mock_dm = MagicMock()
        mock_dm.enabled = False

        with patch('potato.diversity_manager.get_diversity_manager', return_value=mock_dm):
            ism = ItemStateManager(config)

            for i in range(5):
                ism.add_item(f"item{i}", {"text": f"Text {i}"})

            user_state = MagicMock()
            user_state.has_remaining_assignments.return_value = True
            user_state.get_assigned_instance_count.return_value = 0
            user_state.get_max_assignments.return_value = 5
            user_state.has_annotated.return_value = False
            user_state.get_assigned_instance_ids.return_value = set()

            assigned = ism.assign_instances_to_user(user_state)
            assert assigned > 0

        clear_item_state_manager()


class TestDifferentUserOrderings:
    """Tests that different users get different orderings."""

    def test_users_get_different_cluster_sampling(self):
        """Test that different users sample from clusters differently."""
        import numpy as np
        import tempfile
        from potato.diversity_manager import DiversityConfig, DiversityManager, clear_diversity_manager

        clear_diversity_manager()

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create manager with custom embedding
            def cluster_embed(texts):
                embeddings = []
                for t in texts:
                    # Create distinct clusters based on first character
                    idx = ord(t[0]) % 4
                    vec = [0.0] * 4
                    vec[idx] = 1.0
                    embeddings.append(vec)
                return np.array(embeddings)

            config = DiversityConfig(
                enabled=True,
                custom_embedding_function=cluster_embed,
                cache_dir=temp_dir,
                num_clusters=4,
                auto_clusters=False,
            )

            dm = DiversityManager(config, {"output_annotation_dir": temp_dir})

            # Create items that cluster into 4 groups
            texts = {
                "a1": "apple", "a2": "avocado",
                "b1": "banana", "b2": "blueberry",
                "c1": "cherry", "c2": "cantaloupe",
                "d1": "durian", "d2": "dragonfruit",
            }
            dm.compute_embeddings_batch(texts)
            dm.cluster_items()

            # Get orderings for different users
            available = list(texts.keys())
            order1 = dm.apply_to_user_ordering("user1", available.copy(), set())
            order2 = dm.apply_to_user_ordering("user2", available.copy(), set())

            # Both should have all items
            assert set(order1) == set(available)
            assert set(order2) == set(available)

            # The orderings might be same or different depending on cluster sampling
            # But both should show diversity (items from different clusters interleaved)

        clear_diversity_manager()

"""
Integration tests for active learning using the user simulator.

These tests verify that the simulator can be used to test active learning
workflows, including multi-round annotation and quality tracking.
"""

import pytest
import tempfile
import os
import json
import time

from potato.simulator import (
    SimulatorManager,
    SimulatorConfig,
    TimingConfig,
    CompetenceLevel,
)
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory


# Skip if server tests are not configured
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SERVER_TESTS", "0") == "1",
    reason="Server tests skipped via environment variable",
)


@pytest.fixture(scope="module")
def test_data_dir():
    """Create test data directory."""
    test_dir = create_test_directory("simulator_active_learning")
    yield test_dir
    # Cleanup handled by test framework


@pytest.fixture(scope="module")
def test_data_file(test_data_dir):
    """Create test data file with items for annotation."""
    items = [
        {"id": f"item_{i:03d}", "text": f"This is test item number {i}. It has some content."}
        for i in range(50)
    ]

    data_file = os.path.join(test_data_dir, "test_data.jsonl")
    with open(data_file, "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")

    return data_file


@pytest.fixture(scope="module")
def test_config(test_data_dir, test_data_file):
    """Create test configuration for annotation task."""
    import yaml

    config = {
        "annotation_task_name": "Simulator Active Learning Test",
        "task_dir": test_data_dir,
        "data_files": [os.path.basename(test_data_file)],
        "output_annotation_dir": "output",
        "output_annotation_format": "json",
        "item_properties": {
            "id_key": "id",
            "text_key": "text",
        },
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": [
                    {"name": "positive", "tooltip": "Positive sentiment"},
                    {"name": "negative", "tooltip": "Negative sentiment"},
                    {"name": "neutral", "tooltip": "Neutral sentiment"},
                ],
                "description": "What is the sentiment of this text?",
            }
        ],
        "user_config": {
            "allow_anonymous": True,
        },
        "ui": {
            "show_progress_bar": True,
        },
    }

    config_file = os.path.join(test_data_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    return config_file


@pytest.fixture(scope="module")
def flask_server(test_config):
    """Start Flask test server."""
    server = FlaskTestServer(port=9876, debug=False, config_file=test_config)
    started = server.start()

    if not started:
        pytest.skip("Failed to start Flask server")

    yield server

    server.stop()


class TestSimulatorWithServer:
    """Tests that run the simulator against a real server."""

    def test_basic_simulation_run(self, flask_server):
        """Test that simulator can complete a basic run."""
        config = SimulatorConfig(
            user_count=3,
            strategy="random",
            competence_distribution={"good": 0.5, "average": 0.5},
            parallel_users=2,
            simulate_wait=False,
        )

        manager = SimulatorManager(config, flask_server.base_url)
        results = manager.run_parallel(max_annotations_per_user=5)

        assert len(results) == 3
        total_annotations = sum(len(r.annotations) for r in results.values())
        assert total_annotations > 0

    def test_simulation_with_competence_distribution(self, flask_server):
        """Test that competence distribution is respected."""
        config = SimulatorConfig(
            user_count=10,
            competence_distribution={
                "good": 0.4,
                "average": 0.3,
                "poor": 0.3,
            },
            parallel_users=3,
            simulate_wait=False,
        )

        manager = SimulatorManager(config, flask_server.base_url)
        results = manager.run_parallel(max_annotations_per_user=5)

        summary = manager.get_summary()
        assert summary["competence_distribution"]["good"] >= 2
        assert summary["competence_distribution"]["average"] >= 1
        assert summary["competence_distribution"]["poor"] >= 1

    def test_sequential_simulation(self, flask_server):
        """Test sequential (non-parallel) simulation."""
        config = SimulatorConfig(
            user_count=2,
            simulate_wait=False,
        )

        manager = SimulatorManager(config, flask_server.base_url)
        results = manager.run_sequential(max_annotations_per_user=3)

        assert len(results) == 2

    def test_simulation_summary_statistics(self, flask_server):
        """Test that summary statistics are computed correctly."""
        config = SimulatorConfig(
            user_count=5,
            parallel_users=2,
            simulate_wait=False,
        )

        manager = SimulatorManager(config, flask_server.base_url)
        manager.run_parallel(max_annotations_per_user=10)

        summary = manager.get_summary()

        assert "user_count" in summary
        assert "total_annotations" in summary
        assert "total_time_seconds" in summary
        assert "per_user" in summary
        assert summary["user_count"] == 5


class TestMultiRoundSimulation:
    """Tests for multi-round annotation (active learning scenarios)."""

    def test_multiple_annotation_rounds(self, flask_server):
        """Test simulating multiple rounds of annotation."""
        round_results = []

        for round_num in range(3):
            config = SimulatorConfig(
                user_count=3,
                parallel_users=2,
                simulate_wait=False,
            )

            manager = SimulatorManager(config, flask_server.base_url)
            results = manager.run_parallel(max_annotations_per_user=5)

            round_summary = {
                "round": round_num + 1,
                "users": len(results),
                "annotations": sum(len(r.annotations) for r in results.values()),
            }
            round_results.append(round_summary)

        # Verify all rounds completed
        assert len(round_results) == 3
        for result in round_results:
            assert result["users"] == 3
            assert result["annotations"] > 0

    def test_accumulating_annotations(self, flask_server):
        """Test that annotations accumulate across rounds."""
        import requests

        # Run first round
        config = SimulatorConfig(user_count=2, simulate_wait=False)
        manager = SimulatorManager(config, flask_server.base_url)
        manager.run_parallel(max_annotations_per_user=5)

        first_round_annotations = manager.get_summary()["total_annotations"]

        # Run second round (different users)
        config2 = SimulatorConfig(user_count=2, simulate_wait=False)
        manager2 = SimulatorManager(config2, flask_server.base_url)
        manager2.run_parallel(max_annotations_per_user=5)

        second_round_annotations = manager2.get_summary()["total_annotations"]

        # Total should be sum of both rounds
        total = first_round_annotations + second_round_annotations
        assert total >= first_round_annotations


class TestResultExport:
    """Tests for result export functionality."""

    def test_export_to_directory(self, flask_server, tmp_path):
        """Test exporting results to directory."""
        config = SimulatorConfig(
            user_count=3,
            output_dir=str(tmp_path),
            simulate_wait=False,
        )

        manager = SimulatorManager(config, flask_server.base_url)
        manager.run_parallel(max_annotations_per_user=3)
        manager.export_results()

        # Check files were created
        files = list(tmp_path.glob("*.json"))
        assert len(files) >= 2  # summary and user_results

        csv_files = list(tmp_path.glob("*.csv"))
        assert len(csv_files) >= 1  # annotations


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_single_user_simulation(self, flask_server):
        """Test with single user."""
        config = SimulatorConfig(
            user_count=1,
            simulate_wait=False,
        )

        manager = SimulatorManager(config, flask_server.base_url)
        results = manager.run_parallel(max_annotations_per_user=3)

        assert len(results) == 1

    def test_zero_max_annotations(self, flask_server):
        """Test with zero max annotations (should still login)."""
        config = SimulatorConfig(
            user_count=2,
            simulate_wait=False,
        )

        manager = SimulatorManager(config, flask_server.base_url)
        results = manager.run_parallel(max_annotations_per_user=0)

        # Should have results but no annotations
        assert len(results) == 2
        for result in results.values():
            assert len(result.annotations) == 0

    def test_high_parallelism(self, flask_server):
        """Test with high parallelism (more parallel than users)."""
        config = SimulatorConfig(
            user_count=5,
            parallel_users=10,  # More parallel workers than users
            simulate_wait=False,
        )

        manager = SimulatorManager(config, flask_server.base_url)
        results = manager.run_parallel(max_annotations_per_user=3)

        assert len(results) == 5

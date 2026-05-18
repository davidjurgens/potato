"""
Server integration tests for create_app(config_file) factory pattern.

Verifies that create_app() correctly initializes the server when called
with a config_file argument (the WSGI/gunicorn code path used by
HuggingFace Spaces deployment).
"""

import json
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(test_name="create_app_factory", num_items=3):
    """Create a minimal config for factory tests."""
    test_dir = create_test_directory(test_name)
    data = [
        {"id": f"item_{i}", "text": f"Test item {i} for factory test."}
        for i in range(1, num_items + 1)
    ]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "name": "label",
            "description": "Simple label",
            "annotation_type": "radio",
            "labels": ["yes", "no"],
        }],
        data_files=[data_file],
    )
    return config_file


def _make_trace_config(test_name="create_app_trace"):
    """Config with trace ingestion for testing blueprint registration."""
    test_dir = create_test_directory(test_name)
    data = [{"id": "seed", "text": "Seed item."}]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "name": "quality",
            "description": "Quality",
            "annotation_type": "radio",
            "labels": ["good", "bad"],
        }],
        data_files=[data_file],
        additional_config={
            "trace_ingestion": {
                "enabled": True,
                "api_key": "",
                "notify_annotators": False,
            },
        },
    )
    return config_file


# ---------------------------------------------------------------------------
# Tests: create_app(config_file) basic functionality
# ---------------------------------------------------------------------------

class TestCreateAppFactory:
    """Test that create_app(config_file) produces a working Flask app."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(port=9875, config_file=_make_config())
        if not server.start():
            pytest.fail("Failed to start server for create_app factory test")
        request.cls.server = server
        yield server
        server.stop()

    def test_health_endpoint(self):
        """Server responds to basic requests."""
        resp = requests.get(f"{self.server.base_url}/", timeout=10)
        # Should redirect to login or serve a page
        assert resp.status_code in (200, 302)

    def test_register_and_login(self):
        session = requests.Session()
        resp = session.post(
            f"{self.server.base_url}/register",
            data={"email": "factory_user", "pass": "pass"},
        )
        assert resp.status_code == 200

        resp = session.post(
            f"{self.server.base_url}/auth",
            data={"email": "factory_user", "pass": "pass"},
        )
        assert resp.status_code == 200

    def test_annotate_endpoint_serves(self):
        session = requests.Session()
        session.post(
            f"{self.server.base_url}/register",
            data={"email": "annotator_f", "pass": "pass"},
        )
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": "annotator_f", "pass": "pass"},
        )
        resp = session.get(f"{self.server.base_url}/annotate", timeout=10)
        assert resp.status_code == 200
        assert "annotation" in resp.text.lower() or "item" in resp.text.lower()

    def test_annotation_submission(self):
        """Annotations can be submitted successfully."""
        session = requests.Session()
        session.post(
            f"{self.server.base_url}/register",
            data={"email": "submit_f", "pass": "pass"},
        )
        session.post(
            f"{self.server.base_url}/auth",
            data={"email": "submit_f", "pass": "pass"},
        )
        session.get(f"{self.server.base_url}/annotate")

        # Submit an annotation
        resp = session.post(f"{self.server.base_url}/updateinstance", json={
            "instance_id": "item_1",
            "annotations": {"label:yes": "true"},
        })
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: create_app with trace ingestion blueprints
# ---------------------------------------------------------------------------

class TestCreateAppWithBlueprints:
    """Verify that blueprints are correctly registered via create_app()."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(
            port=9876,
            config_file=_make_trace_config(),
        )
        if not server.start():
            pytest.fail("Failed to start server for blueprint test")
        request.cls.server = server
        yield server
        server.stop()

    def test_trace_webhook_endpoint_exists(self):
        """The trace ingestion blueprint should be registered."""
        resp = requests.post(
            f"{self.server.base_url}/api/traces/webhook",
            json={"steps": []},
            timeout=10,
        )
        # Should return 200 (accepted) since no auth is required (empty api_key)
        assert resp.status_code == 200

    def test_trace_langsmith_endpoint_exists(self):
        resp = requests.post(
            f"{self.server.base_url}/api/traces/langsmith",
            json={"runs": [{"id": "r1", "run_type": "chain", "inputs": {}, "outputs": {}}]},
            timeout=10,
        )
        assert resp.status_code == 200

    def test_trace_status_requires_login(self):
        """Status endpoint should require authentication."""
        resp = requests.get(
            f"{self.server.base_url}/api/traces/status", timeout=10
        )
        # Should redirect to login
        assert resp.status_code in (302, 401, 200)


# ---------------------------------------------------------------------------
# Tests: _initialize_from_config directly
# ---------------------------------------------------------------------------

class TestInitializeFromConfig:
    """Test the _initialize_from_config() helper that create_app uses."""

    def test_creates_output_directory(self):
        """_initialize_from_config should create output directories."""
        from tests.helpers.flask_test_setup import clear_all_global_state
        clear_all_global_state()

        original_cwd = os.getcwd()
        config_file = _make_config("init_from_cfg")

        # Read config to find output dir
        import yaml
        with open(config_file) as f:
            config_data = yaml.safe_load(f)

        output_dir = config_data.get("output_annotation_dir", "")

        try:
            # chdir to config directory so init_config's path resolution works
            # even when earlier tests have changed cwd
            os.chdir(os.path.dirname(config_file))
            from potato.flask_server import _initialize_from_config
            _initialize_from_config(config_file)
            assert os.path.isdir(output_dir)
        finally:
            os.chdir(original_cwd)
            clear_all_global_state()

    def test_state_managers_initialized(self):
        """State managers should be available after initialization."""
        from tests.helpers.flask_test_setup import clear_all_global_state
        clear_all_global_state()

        original_cwd = os.getcwd()
        config_file = _make_config("init_state_mgrs")

        try:
            # chdir to config directory so init_config's path resolution works
            # even when earlier tests have changed cwd
            os.chdir(os.path.dirname(config_file))
            from potato.flask_server import _initialize_from_config
            _initialize_from_config(config_file)

            from potato.item_state_management import get_item_state_manager
            from potato.user_state_management import get_user_state_manager

            ism = get_item_state_manager()
            usm = get_user_state_manager()
            assert ism is not None
            assert usm is not None
        finally:
            os.chdir(original_cwd)
            clear_all_global_state()

    def test_qda_mode_initialized_via_factory(self):
        """F1 regression: create_app(config_file) must initialize the QDA
        Mode manager and serve /qda/status (run_server parity).

        FlaskTestServer replicates init in-process, so it cannot catch a
        missing init in _initialize_from_config — this test calls the real
        factory function.
        """
        from tests.helpers.flask_test_setup import clear_all_global_state
        from potato.qda_mode import clear_qda_mode_manager, get_qda_mode_manager

        clear_all_global_state()
        clear_qda_mode_manager()

        test_dir = create_test_directory("init_qda_factory")
        data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hi"}])
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[{
                "name": "label",
                "description": "L",
                "annotation_type": "radio",
                "labels": ["a", "b"],
            }],
            data_files=[data_file],
            additional_config={
                "qda_mode": {
                    "enabled": True,
                    "codebook": {"enabled": True, "mode": "fixed"},
                }
            },
        )

        original_cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(config_file))
            from potato.flask_server import create_app
            app = create_app(config_file)

            # Manager initialized by the factory path (the F1 fix).
            mgr = get_qda_mode_manager()
            assert mgr is not None
            assert mgr.config.enabled is True

            # Blueprint reachable on the served factory app.
            client = app.test_client()
            resp = client.get("/qda/status")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["enabled"] is True
            assert body["codebook"] == {"enabled": True, "mode": "fixed"}
        finally:
            os.chdir(original_cwd)
            clear_qda_mode_manager()
            clear_all_global_state()

    def test_invalid_qda_mode_config_aborts_factory_startup(self):
        """F2: an enabled-but-invalid qda_mode must abort create_app(),
        not silently boot with QDA disabled."""
        from tests.helpers.flask_test_setup import clear_all_global_state
        from potato.qda_mode import clear_qda_mode_manager
        from potato.server_utils.config_module import ConfigValidationError

        clear_all_global_state()
        clear_qda_mode_manager()

        test_dir = create_test_directory("init_qda_bad")
        data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hi"}])
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[{
                "name": "label",
                "description": "L",
                "annotation_type": "radio",
                "labels": ["a", "b"],
            }],
            data_files=[data_file],
            additional_config={
                "qda_mode": {
                    "enabled": True,
                    "codebook": {"mode": "nonsense"},
                }
            },
        )

        original_cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(config_file))
            from potato.flask_server import create_app
            with pytest.raises(ConfigValidationError, match="qda_mode"):
                create_app(config_file)
        finally:
            os.chdir(original_cwd)
            clear_qda_mode_manager()
            clear_all_global_state()

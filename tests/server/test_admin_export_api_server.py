"""
Server integration tests for admin export API endpoints.

Tests POST /admin/api/export and GET /admin/api/export/formats against
a real running Potato server.
"""

import pytest
import requests
import os
import sys

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

ADMIN_KEY = "test-export-api-key"


def _make_config(test_name="export_api", num_items=5):
    """Create a config with a simple radio scheme."""
    test_dir = create_test_directory(test_name)
    data = [
        {"id": f"item_{i}", "text": f"Sample text {i}"} for i in range(1, num_items + 1)
    ]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "name": "sentiment",
            "description": "Classify sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "negative", "neutral"],
        }],
        data_files=[data_file],
        admin_api_key=ADMIN_KEY,
    )
    return config_file


def _register_and_annotate(base_url, username="tester"):
    """Register a user, log in, navigate, and submit an annotation."""
    session = requests.Session()
    session.post(f"{base_url}/register", data={"email": username, "pass": "pass"})
    session.post(f"{base_url}/auth", data={"email": username, "pass": "pass"})
    session.get(f"{base_url}/annotate")
    # Submit annotation using the frontend format (schema:label keys)
    resp = session.post(f"{base_url}/updateinstance", json={
        "instance_id": "item_1",
        "annotations": {"sentiment:positive": "true"},
    })
    return session, resp


# ---------------------------------------------------------------------------
# Test class: core API behavior
# ---------------------------------------------------------------------------

class TestAdminExportAPI:
    """Integration tests for the admin export API endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(port=9880, config_file=_make_config())
        if not server.start():
            pytest.fail("Failed to start export API test server")
        request.cls.server = server
        yield server
        server.stop()

    def _api_get(self, endpoint, key=ADMIN_KEY):
        headers = {"X-API-Key": key} if key else {}
        return requests.get(
            f"{self.server.base_url}{endpoint}",
            headers=headers,
            timeout=10,
        )

    def _api_post(self, endpoint, data=None, key=ADMIN_KEY):
        headers = {"X-API-Key": key} if key else {}
        return requests.post(
            f"{self.server.base_url}{endpoint}",
            headers=headers,
            json=data,
            timeout=10,
        )

    # ========== Authentication ==========

    def test_formats_requires_auth(self):
        resp = self._api_get("/admin/api/export/formats", key=None)
        assert resp.status_code == 403

    def test_formats_rejects_bad_key(self):
        resp = self._api_get("/admin/api/export/formats", key="wrong")
        assert resp.status_code == 403

    def test_export_requires_auth(self):
        resp = self._api_post("/admin/api/export", {"format": "coco"}, key=None)
        assert resp.status_code == 403

    def test_export_rejects_bad_key(self):
        resp = self._api_post("/admin/api/export", {"format": "coco"}, key="wrong")
        assert resp.status_code == 403

    # ========== GET /admin/api/export/formats ==========

    def test_formats_returns_list(self):
        resp = self._api_get("/admin/api/export/formats")
        assert resp.status_code == 200
        data = resp.json()
        assert "formats" in data
        assert isinstance(data["formats"], list)
        assert len(data["formats"]) > 0

    def test_formats_contain_expected_fields(self):
        resp = self._api_get("/admin/api/export/formats")
        data = resp.json()
        for fmt in data["formats"]:
            assert "format_name" in fmt
            assert "description" in fmt
            assert "file_extensions" in fmt

    def test_formats_include_known_exporters(self):
        resp = self._api_get("/admin/api/export/formats")
        names = [f["format_name"] for f in resp.json()["formats"]]
        for expected in ("coco", "yolo", "parquet", "conll_2003"):
            assert expected in names, f"Expected format '{expected}' not found"

    # ========== POST /admin/api/export ==========

    def test_export_missing_format_returns_400(self):
        resp = self._api_post("/admin/api/export", {})
        assert resp.status_code == 400
        assert "format" in resp.json()["error"]

    def test_export_empty_body_returns_400(self):
        resp = self._api_post("/admin/api/export", None)
        assert resp.status_code == 400

    def test_export_unknown_format_returns_500(self):
        resp = self._api_post("/admin/api/export", {
            "format": "nonexistent_format_xyz",
            "output": "/tmp/out",
        })
        assert resp.status_code == 500
        assert "error" in resp.json()

    def test_export_no_annotations_returns_failure(self):
        """Exporting with no annotations should return success=False."""
        output_dir = os.path.join(
            create_test_directory("export_empty_out"), "export"
        )
        resp = self._api_post("/admin/api/export", {
            "format": "parquet",
            "output": output_dir,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert len(data["errors"]) > 0

    def test_export_result_structure(self):
        """Verify the JSON response has all expected keys regardless of success."""
        output_dir = os.path.join(
            create_test_directory("export_structure_out"), "export"
        )
        resp = self._api_post("/admin/api/export", {
            "format": "parquet",
            "output": output_dir,
        })
        data = resp.json()
        for key in ("success", "format", "files_written", "stats", "warnings", "errors"):
            assert key in data, f"Missing key '{key}' in export response"


# ---------------------------------------------------------------------------
# Test class: export with annotations
# ---------------------------------------------------------------------------

class TestAdminExportWithAnnotations:
    """Test export after creating annotations (end-to-end flow)."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(port=9881, config_file=_make_config("export_annotated", num_items=3))
        if not server.start():
            pytest.fail("Failed to start annotated export test server")
        request.cls.server = server
        # Create annotations via the running server
        _register_and_annotate(server.base_url)
        yield server
        server.stop()

    def test_parquet_export_succeeds_with_annotations(self):
        """Parquet export should succeed when annotations exist."""
        output_dir = os.path.join(
            create_test_directory("export_annotated_out"), "export"
        )
        resp = requests.post(
            f"{self.server.base_url}/admin/api/export",
            headers={"X-API-Key": ADMIN_KEY},
            json={"format": "parquet", "output": output_dir},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        if not data["success"]:
            # Helpful debug output on failure
            print(f"Export failed: {data}")
        assert data["success"] is True
        assert data["format"] == "parquet"
        assert len(data["files_written"]) > 0
        assert data["errors"] == []

    def test_export_result_has_stats(self):
        """Stats dict should contain annotation counts."""
        output_dir = os.path.join(
            create_test_directory("export_stats_out"), "export"
        )
        resp = requests.post(
            f"{self.server.base_url}/admin/api/export",
            headers={"X-API-Key": ADMIN_KEY},
            json={"format": "parquet", "output": output_dir},
            timeout=10,
        )
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["stats"], dict)
        # At least one stat key should be present
        assert len(data["stats"]) > 0

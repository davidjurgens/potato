"""
Unit tests for admin export API endpoints.

Tests authentication enforcement, format listing, export execution,
and result serialization for POST /admin/api/export and
GET /admin/api/export/formats.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass, field
from typing import List, Dict, Any


# ---------------------------------------------------------------------------
# Fake ExportResult for mocking
# ---------------------------------------------------------------------------

@dataclass
class FakeExportResult:
    success: bool = True
    format_name: str = "coco"
    files_written: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_test_app():
    """Create a minimal Flask app with the admin export routes patched in."""
    from flask import Flask, request, jsonify

    app = Flask(__name__)
    app.config["TESTING"] = True

    mock_config = {"debug": False, "__config_file__": "/fake/config.yaml"}

    def validate_admin_api_key(provided_key):
        if mock_config.get("debug"):
            return True
        import hmac
        expected = "test-api-key"
        return hmac.compare_digest(str(provided_key or ""), expected)

    @app.route('/admin/api/export/formats', methods=['GET'])
    def admin_api_export_formats():
        api_key = request.headers.get('X-API-Key')
        if not validate_admin_api_key(api_key):
            return jsonify({"error": "Admin access required"}), 403

        from potato.export import export_registry
        formats = export_registry.list_exporters()
        return jsonify({"formats": formats})

    @app.route('/admin/api/export', methods=['POST'])
    def admin_api_export():
        api_key = request.headers.get('X-API-Key')
        if not validate_admin_api_key(api_key):
            return jsonify({"error": "Admin access required"}), 403

        data = request.get_json(silent=True) or {}
        fmt = data.get("format")
        if not fmt:
            return jsonify({"error": "Missing required field: format"}), 400

        output = data.get("output", "")
        options = data.get("options") or {}

        config_file = mock_config.get("__config_file__")
        if not config_file:
            return jsonify({"error": "Config file path not available"}), 500

        try:
            from potato.export.cli import build_export_context
            from potato.export import export_registry

            context = build_export_context(config_file)
            result = export_registry.export(fmt, context, output, options)

            return jsonify({
                "success": result.success,
                "format": result.format_name,
                "files_written": result.files_written,
                "stats": result.stats,
                "warnings": result.warnings,
                "errors": result.errors,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app


# ---------------------------------------------------------------------------
# Authentication Tests
# ---------------------------------------------------------------------------

class TestExportAuth:
    """Tests for authentication on export endpoints."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app = _create_test_app()
        self.client = self.app.test_client()

    def test_formats_requires_api_key(self):
        resp = self.client.get('/admin/api/export/formats')
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "Admin access required"

    def test_formats_rejects_invalid_key(self):
        resp = self.client.get(
            '/admin/api/export/formats',
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    def test_export_requires_api_key(self):
        resp = self.client.post(
            '/admin/api/export',
            json={"format": "coco"},
        )
        assert resp.status_code == 403

    def test_export_rejects_invalid_key(self):
        resp = self.client.post(
            '/admin/api/export',
            json={"format": "coco"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Format Listing Tests
# ---------------------------------------------------------------------------

class TestExportFormats:
    """Tests for GET /admin/api/export/formats."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app = _create_test_app()
        self.client = self.app.test_client()

    @patch("potato.export.export_registry.list_exporters")
    def test_returns_formats_list(self, mock_list):
        mock_list.return_value = [
            {"format_name": "coco", "description": "COCO format", "file_extensions": [".json"]},
            {"format_name": "yolo", "description": "YOLO format", "file_extensions": [".txt"]},
        ]
        resp = self.client.get(
            '/admin/api/export/formats',
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "formats" in data
        assert len(data["formats"]) == 2
        assert data["formats"][0]["format_name"] == "coco"

    @patch("potato.export.export_registry.list_exporters")
    def test_returns_empty_when_no_exporters(self, mock_list):
        mock_list.return_value = []
        resp = self.client.get(
            '/admin/api/export/formats',
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["formats"] == []


# ---------------------------------------------------------------------------
# Export Endpoint Tests
# ---------------------------------------------------------------------------

class TestExportEndpoint:
    """Tests for POST /admin/api/export."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app = _create_test_app()
        self.client = self.app.test_client()

    def test_missing_format_returns_400(self):
        resp = self.client.post(
            '/admin/api/export',
            json={},
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status_code == 400
        assert "format" in resp.get_json()["error"]

    def test_empty_body_returns_400(self):
        resp = self.client.post(
            '/admin/api/export',
            headers={"X-API-Key": "test-api-key"},
            content_type="application/json",
            data="{}",
        )
        assert resp.status_code == 400

    @patch("potato.export.export_registry.export")
    @patch("potato.export.cli.build_export_context")
    def test_successful_export(self, mock_build, mock_export):
        mock_build.return_value = MagicMock()
        mock_export.return_value = FakeExportResult(
            success=True,
            format_name="coco",
            files_written=["/out/annotations.json"],
            stats={"num_annotations": 42},
        )

        resp = self.client.post(
            '/admin/api/export',
            json={"format": "coco", "output": "/out"},
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["format"] == "coco"
        assert data["files_written"] == ["/out/annotations.json"]
        assert data["stats"]["num_annotations"] == 42
        assert data["warnings"] == []
        assert data["errors"] == []

    @patch("potato.export.export_registry.export")
    @patch("potato.export.cli.build_export_context")
    def test_failed_export_result(self, mock_build, mock_export):
        mock_build.return_value = MagicMock()
        mock_export.return_value = FakeExportResult(
            success=False,
            format_name="yolo",
            errors=["No annotations found"],
        )

        resp = self.client.post(
            '/admin/api/export',
            json={"format": "yolo", "output": "/out"},
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False
        assert "No annotations found" in data["errors"]

    @patch("potato.export.export_registry.export")
    @patch("potato.export.cli.build_export_context")
    def test_export_passes_options(self, mock_build, mock_export):
        mock_build.return_value = MagicMock()
        mock_export.return_value = FakeExportResult()

        resp = self.client.post(
            '/admin/api/export',
            json={
                "format": "huggingface",
                "output": "org/repo",
                "options": {"token": "hf_xxx", "private": "true"},
            },
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status_code == 200
        mock_export.assert_called_once()
        call_args = mock_export.call_args
        assert call_args[0][0] == "huggingface"
        assert call_args[0][2] == "org/repo"
        assert call_args[0][3] == {"token": "hf_xxx", "private": "true"}

    @patch("potato.export.cli.build_export_context", side_effect=FileNotFoundError("config not found"))
    def test_build_context_error_returns_500(self, mock_build):
        resp = self.client.post(
            '/admin/api/export',
            json={"format": "coco", "output": "/out"},
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status_code == 500
        assert "config not found" in resp.get_json()["error"]

    @patch("potato.export.export_registry.export", side_effect=ValueError("Unknown format: badformat"))
    @patch("potato.export.cli.build_export_context")
    def test_unknown_format_returns_500(self, mock_build, mock_export):
        mock_build.return_value = MagicMock()
        resp = self.client.post(
            '/admin/api/export',
            json={"format": "badformat", "output": "/out"},
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status_code == 500
        assert "Unknown format" in resp.get_json()["error"]

    @patch("potato.export.export_registry.export")
    @patch("potato.export.cli.build_export_context")
    def test_default_output_and_options(self, mock_build, mock_export):
        """When output and options are omitted, defaults are used."""
        mock_build.return_value = MagicMock()
        mock_export.return_value = FakeExportResult()

        resp = self.client.post(
            '/admin/api/export',
            json={"format": "parquet"},
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status_code == 200
        call_args = mock_export.call_args
        assert call_args[0][2] == ""  # default output
        assert call_args[0][3] == {}  # default options

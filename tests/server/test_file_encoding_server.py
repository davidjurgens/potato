"""
Server integration tests for file encoding configuration support.

Tests that data files with non-UTF-8 encodings are correctly loaded
when the encoding is specified in the config.
"""

import json
import os
import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_config


def _write_json_data(path, data, encoding="utf-8"):
    """Write JSONL data with a specific encoding."""
    with open(path, "w", encoding=encoding) as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _write_csv_data(path, rows, encoding="utf-8"):
    """Write CSV data with a specific encoding."""
    with open(path, "w", encoding=encoding) as f:
        # header
        f.write(",".join(rows[0].keys()) + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row.values()) + "\n")


# Test data containing characters that differ between encodings
LATIN1_ITEMS = [
    {"id": "lat1", "text": "caf\u00e9 na\u00efve r\u00e9sum\u00e9"},
    {"id": "lat2", "text": "\u00fcber stra\u00dfe"},
    {"id": "lat3", "text": "Cr\u00e8me br\u00fbl\u00e9e"},
]


class TestLatin1JsonLoading:
    """Test loading a latin-1 encoded JSON file."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("encoding_latin1_json")

        # Write data in latin-1 encoding
        data_file = os.path.join(test_dir, "latin1_data.jsonl")
        _write_json_data(data_file, LATIN1_ITEMS, encoding="latin-1")

        # Config with encoding specified in dict form
        config = {
            "annotation_task_name": "Encoding Test",
            "task_dir": os.path.abspath(test_dir),
            "data_files": [{"path": "latin1_data.jsonl", "encoding": "latin-1"}],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "label",
                    "annotation_type": "radio",
                    "labels": ["a", "b"],
                    "description": "Pick one.",
                }
            ],
            "output_annotation_dir": os.path.join(os.path.abspath(test_dir), "output"),
            "site_dir": "default",
            "alert_time_each_instance": 0,
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "persist_sessions": False,
            "debug": False,
            "host": "0.0.0.0",
            "secret_key": "test-secret",
            "session_lifetime_days": 1,
            "user_config": {"allow_all_users": True, "users": []},
            "admin_api_key": "test_key",
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    def test_server_loads_latin1_data(self, flask_server):
        """Server should start successfully with latin-1 encoded data."""
        resp = requests.get(
            f"{flask_server.base_url}/admin/health",
            headers={"X-API-Key": "test_key"},
            timeout=5,
        )
        assert resp.status_code == 200

    def test_latin1_text_accessible(self, flask_server):
        """Accented characters from latin-1 file should be accessible."""
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register", data={"email": "user1", "pass": "pass"})
        session.post(f"{flask_server.base_url}/auth", data={"email": "user1", "pass": "pass"})

        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        # The accented characters should appear in the page
        assert "caf\u00e9" in resp.text or "r\u00e9sum\u00e9" in resp.text or "stra\u00dfe" in resp.text


class TestLatin1CsvLoading:
    """Test loading a latin-1 encoded CSV file."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("encoding_latin1_csv")

        # Write CSV in latin-1 encoding
        data_file = os.path.join(test_dir, "latin1_data.csv")
        _write_csv_data(data_file, LATIN1_ITEMS, encoding="latin-1")

        config = {
            "annotation_task_name": "Encoding CSV Test",
            "task_dir": os.path.abspath(test_dir),
            "data_files": [{"path": "latin1_data.csv", "encoding": "latin-1"}],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "label",
                    "annotation_type": "radio",
                    "labels": ["a", "b"],
                    "description": "Pick one.",
                }
            ],
            "output_annotation_dir": os.path.join(os.path.abspath(test_dir), "output"),
            "site_dir": "default",
            "alert_time_each_instance": 0,
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "persist_sessions": False,
            "debug": False,
            "host": "0.0.0.0",
            "secret_key": "test-secret",
            "session_lifetime_days": 1,
            "user_config": {"allow_all_users": True, "users": []},
            "admin_api_key": "test_key",
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    def test_csv_server_loads_latin1(self, flask_server):
        """Server should load latin-1 CSV data successfully."""
        resp = requests.get(
            f"{flask_server.base_url}/admin/health",
            headers={"X-API-Key": "test_key"},
            timeout=5,
        )
        assert resp.status_code == 200

    def test_csv_latin1_text_accessible(self, flask_server):
        """Accented characters from latin-1 CSV should be accessible."""
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register", data={"email": "user2", "pass": "pass"})
        session.post(f"{flask_server.base_url}/auth", data={"email": "user2", "pass": "pass"})

        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        assert "caf\u00e9" in resp.text or "r\u00e9sum\u00e9" in resp.text or "stra\u00dfe" in resp.text


class TestUtf8DefaultStillWorks:
    """Test that plain string entries (no encoding specified) still work as UTF-8."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("encoding_utf8_default")

        data_file = os.path.join(test_dir, "utf8_data.jsonl")
        utf8_items = [
            {"id": "u1", "text": "Hello world"},
            {"id": "u2", "text": "Simple ASCII text"},
        ]
        _write_json_data(data_file, utf8_items, encoding="utf-8")

        # Use plain string entry (no dict, no encoding) — should default to utf-8
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[{
                "name": "label",
                "annotation_type": "radio",
                "labels": ["a", "b"],
                "description": "Pick one.",
            }],
            data_files=[data_file],
            annotation_task_name="UTF8 Default Test",
            admin_api_key="test_key",
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    def test_utf8_default_loads(self, flask_server):
        """Plain string data_files entry should load as UTF-8."""
        resp = requests.get(
            f"{flask_server.base_url}/admin/health",
            headers={"X-API-Key": "test_key"},
            timeout=5,
        )
        assert resp.status_code == 200

"""Integration tests for Pocket Mode (/pocket/*)."""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "pocket_test_admin_key"

TEST_ITEMS = [
    {"id": "p1", "text": "The pasta was incredible but the wait was brutal."},
    {"id": "p2", "text": "Exactly as described. It's a toaster."},
    {"id": "p3", "text": "Smells like burning plastic on the highest setting."},
]


class TestPocketAPI:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("pocket_api")
        create_test_data_file(test_dir, TEST_ITEMS)
        annotation_schemes = [{
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "How does this read?",
            "labels": ["Positive", "Mixed", "Negative"],
        }]
        config_path = create_test_config(
            test_dir,
            annotation_schemes,
            admin_api_key=ADMIN_KEY,
            additional_config={"pocket": {"enabled": True, "batch_size": 10}},
        )
        server = FlaskTestServer(port=9081, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    @pytest.fixture()
    def authed_session(self, flask_server):
        session = requests.Session()
        user = {"email": "pocket_user", "pass": "pass"}
        session.post(f"{flask_server.base_url}/register", data=user, timeout=5)
        response = session.post(f"{flask_server.base_url}/auth", data=user, timeout=5)
        assert response.status_code in (200, 302)
        session.headers.update({"Origin": flask_server.base_url})
        return session

    # ------------------------------------------------------------- auth ----
    def test_task_requires_login(self, flask_server):
        response = requests.get(f"{flask_server.base_url}/pocket/api/task", timeout=5)
        assert response.status_code == 401

    def test_page_redirects_anonymous_to_login(self, flask_server):
        response = requests.get(f"{flask_server.base_url}/pocket",
                                allow_redirects=False, timeout=5)
        assert response.status_code == 302
        assert "login" in response.headers.get("Location", "")

    # ------------------------------------------------------------ surface ----
    def test_task_reports_capability_and_schemas(self, flask_server, authed_session):
        data = authed_session.get(
            f"{flask_server.base_url}/pocket/api/task", timeout=5).json()
        assert data["capable"] is True
        assert data["incompatible_schemes"] == []
        assert data["schemas"][0]["name"] == "sentiment"
        assert data["schemas"][0]["labels"] == ["Positive", "Mixed", "Negative"]

    def test_batch_returns_unannotated_items(self, flask_server, authed_session):
        data = authed_session.get(
            f"{flask_server.base_url}/pocket/api/batch", timeout=5).json()
        assert data["total"] == 3
        assert data["done"] == 0
        ids = [i["instance_id"] for i in data["items"]]
        assert set(ids) == {"p1", "p2", "p3"}
        assert all(i["text"] for i in data["items"])

    def test_save_via_updateinstance_then_batch_shrinks(self, flask_server, authed_session):
        response = authed_session.post(
            f"{flask_server.base_url}/updateinstance",
            json={"instance_id": "p1",
                  "annotations": {"sentiment:Mixed": "Mixed"},
                  "span_annotations": []},
            timeout=5,
        )
        assert response.status_code == 200
        assert response.json().get("status") != "error"

        data = authed_session.get(
            f"{flask_server.base_url}/pocket/api/batch", timeout=5).json()
        assert data["done"] == 1
        ids = [i["instance_id"] for i in data["items"]]
        assert "p1" not in ids and len(ids) == 2

    def test_page_renders_for_authed_user(self, flask_server, authed_session):
        response = authed_session.get(f"{flask_server.base_url}/pocket", timeout=5)
        assert response.status_code == 200
        assert "Potato Pocket" in response.text
        assert "pocket.js" in response.text

    def test_manifest_and_sw(self, flask_server, authed_session):
        manifest = authed_session.get(
            f"{flask_server.base_url}/pocket/manifest.webmanifest", timeout=5)
        assert manifest.status_code == 200
        assert manifest.json()["scope"] == "/pocket"
        sw = authed_session.get(f"{flask_server.base_url}/pocket/sw.js", timeout=5)
        assert sw.status_code == 200
        assert "application/javascript" in sw.headers["Content-Type"]
        assert "potato-pocket" in sw.text


class TestPocketIncompatibleTask:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("pocket_incompatible")
        create_test_data_file(test_dir, TEST_ITEMS)
        annotation_schemes = [
            {"annotation_type": "radio", "name": "sentiment",
             "description": "d", "labels": ["Positive", "Negative"]},
            {"annotation_type": "span", "name": "evidence",
             "description": "d", "labels": ["claim"]},
        ]
        config_path = create_test_config(
            test_dir,
            annotation_schemes,
            additional_config={"pocket": {"enabled": True}},
        )
        server = FlaskTestServer(port=9082, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    def test_span_task_reported_incompatible(self, flask_server):
        session = requests.Session()
        user = {"email": "pocket_user2", "pass": "pass"}
        session.post(f"{flask_server.base_url}/register", data=user, timeout=5)
        session.post(f"{flask_server.base_url}/auth", data=user, timeout=5)
        data = session.get(f"{flask_server.base_url}/pocket/api/task", timeout=5).json()
        assert data["capable"] is False
        assert data["incompatible_schemes"] == ["evidence"]


class TestPocketDisabled:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("pocket_disabled")
        create_test_data_file(test_dir, TEST_ITEMS)
        annotation_schemes = [{
            "annotation_type": "radio", "name": "sentiment",
            "description": "d", "labels": ["Positive", "Negative"],
        }]
        config_path = create_test_config(test_dir, annotation_schemes)
        server = FlaskTestServer(port=9083, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    def test_pocket_404_when_disabled(self, flask_server):
        response = requests.get(f"{flask_server.base_url}/pocket", timeout=5)
        assert response.status_code == 404

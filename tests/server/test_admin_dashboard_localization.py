"""Admin dashboard localization: the /admin page renders bundled-language chrome.

The admin dashboard consumes the same ``ui_lang`` dict as the annotation UI.
These tests confirm a bundled language code (``ui_language: es`` / ``ar``)
localizes the admin chrome (tabs, header, injected window.UI_LANG) and drives
document direction, and that an unknown code degrades to English.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)


def _admin_server(name, port, ui_language):
    test_dir = create_test_directory(name)
    data = [
        {"id": f"it_{i:02d}", "text": f"item {i}", "displayed_text": f"Item {i}"}
        for i in range(1, 6)
    ]
    data_file = create_test_data_file(test_dir, data, "data.jsonl")
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "name": "sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "negative"],
            "description": "Sentiment",
        }],
        data_files=[data_file],
        annotation_task_name="Admin L10n Task",
        admin_api_key="test_admin_key",
        additional_config={"ui_language": ui_language},
    )
    server = FlaskTestServer(config=config_file, port=port)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    return server


ADMIN_HEADERS = {"X-API-Key": "test_admin_key"}


class TestAdminSpanish:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = _admin_server("admin_l10n_es", 9171, "es")
        yield server
        server.stop()

    def test_tabs_and_lang_localized(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        # Spanish tab labels present; the English originals gone.
        assert "Resumen" in r.text          # Overview
        assert "Anotadores" in r.text        # Annotators
        assert 'lang="es"' in r.text
        # window.UI_LANG injected so the inline JS can localize status messages.
        assert "window.UI_LANG" in r.text


class TestAdminRtl:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = _admin_server("admin_l10n_ar", 9172, "ar")
        yield server
        server.stop()

    def test_admin_is_rtl(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert 'dir="rtl"' in r.text
        assert 'lang="ar"' in r.text


class TestAdminSubPageSpanish:
    """An admin sub-page (IAA report) also renders localized chrome."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = _admin_server("admin_l10n_subpage", 9174, "es")
        yield server
        server.stop()

    def test_iaa_subpage_localized(self, flask_server):
        # The IAA route renders HTML only with ?format=html (default is JSON).
        r = requests.get(
            f"{flask_server.base_url}/admin/iaa?format=html",
            headers={"X-API-Key": "test_admin_key"},
        )
        assert r.status_code == 200
        assert 'lang="es"' in r.text
        # Spanish IAA title from the bundled catalog ("Acuerdo entre anotadores").
        assert "anotadores" in r.text.lower()


class TestAdminUnknownLangFallsBack:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = _admin_server("admin_l10n_bad", 9173, "zz")
        yield server
        server.stop()

    def test_falls_back_to_english(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/admin", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert "Overview" in r.text
        assert "Annotators" in r.text

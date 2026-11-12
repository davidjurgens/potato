"""
An imported survey runs: the project `potato import` writes boots, and its
translated page rules route a participant the way the source survey would.
"""

import os
from pathlib import Path

import pytest
import requests

from potato.importers.surveys import IMPORTERS
from potato.importers.surveys.writer import write_new_project
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "surveys"


def _login(base_url, username):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"action": "signup", "email": username, "pass": "pass"}, timeout=5)
    s.post(f"{base_url}/auth", data={"action": "login", "email": username, "pass": "pass"}, timeout=5)
    return s


def _submit_page(s, base_url, annotations):
    r = s.post(f"{base_url}/updateinstance",
               json={"instance_id": "__phase_page__", "annotations": annotations,
                     "span_annotations": []}, timeout=5)
    assert r.status_code == 200, r.text
    return s.post(f"{base_url}/annotate", json={"action": "next_instance"},
                  allow_redirects=True, timeout=5)


@pytest.fixture(scope="module")
def surveyjs_server(request):
    test_dir = create_test_directory("survey_import_server_surveyjs")
    result = IMPORTERS["surveyjs"].parse_path(FIXTURES / "surveyjs_screener.json")
    write_new_project(result, test_dir, "surveyjs_screener.json")
    server = FlaskTestServer(config=os.path.join(test_dir, "config.yaml"))
    if not server.start():
        pytest.fail("Failed to start Flask test server on the imported project")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
    return server


def test_first_page_renders(surveyjs_server):
    s = _login(surveyjs_server.base_url, "sj_first")
    r = s.get(f"{surveyjs_server.base_url}/", timeout=5)
    assert 'data-schema-name="age"' in r.text and 'data-schema-name="country"' in r.text


def test_adult_reaches_the_second_page(surveyjs_server):
    s = _login(surveyjs_server.base_url, "sj_adult")
    s.get(f"{surveyjs_server.base_url}/", timeout=5)
    r = _submit_page(s, surveyjs_server.base_url,
                     {"age:::age": "30", "country:::United States": "United States"})
    assert 'data-schema-name="annot_exp"' in r.text


def test_minor_is_ended_by_the_complete_trigger(surveyjs_server):
    s = _login(surveyjs_server.base_url, "sj_minor")
    s.get(f"{surveyjs_server.base_url}/", timeout=5)
    r = _submit_page(s, surveyjs_server.base_url,
                     {"age:::age": "15", "country:::United Kingdom": "United Kingdom"})
    assert 'id="screened-out"' in r.text

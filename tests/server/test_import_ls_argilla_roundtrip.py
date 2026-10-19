"""
A Label Studio project imported with --keep-annotators is a working study.

The importer writes each source annotator's answers as that person's
user_state.json. These tests start a real server on the generated project and
check that the server reads those states the way it reads its own: the answers
come back through /get_annotations, and /admin/api/agreement computes an
agreement statistic over the imported people.
"""

import json
import os
import re
import shutil

import pytest
import requests
import yaml

from potato.importers.cli import main as import_main
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

ADMIN_KEY = "roundtrip-admin-key"
FIXTURES = os.path.join(os.path.dirname(__file__), "..", "data", "importers")


def _start(project):
    config_file = os.path.join(project, "config.yaml")
    with open(config_file) as f:
        config = yaml.safe_load(f)
    port = find_free_port(preferred_port=9894)
    # Not debug mode: debug logs every session in as one debug user, which
    # would hide whose annotations the server is serving.
    config.update({"port": port, "task_dir": project, "admin_api_key": ADMIN_KEY})
    # --keep-annotators closes enrolment to the imported names; let the test's
    # newcomer in the way a researcher adds an annotator.
    if config.get("user_config", {}).get("allow_all_users") is False:
        config["user_config"]["users"].append("newcomer")
    with open(config_file, "w") as f:
        yaml.safe_dump(config, f)
    server = FlaskTestServer(port=port, config_file=config_file, debug=False)
    if not server.start():
        pytest.fail("Failed to start server")
    return server


def _login(server, username):
    """Log in by name: the imported project is passwordless, and the imported
    people are already accounts, so they log in rather than register."""
    session = requests.Session()
    response = session.post(f"{server.base_url}/auth", data={"email": username, "pass": ""})
    assert response.status_code == 200, response.text[:300]
    return session


@pytest.fixture(scope="module")
def ls_server():
    test_dir = create_test_directory("import_ls_roundtrip")
    project = os.path.join(test_dir, "project")
    assert import_main([
        "-i", os.path.join(FIXTURES, "label_studio", "text_project.json"),
        "--ls-config", os.path.join(FIXTURES, "label_studio", "text_label_config.xml"),
        "-o", project, "--keep-annotators",
    ]) == 0
    server = _start(project)
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


class TestLabelStudioProject:
    def test_an_imported_annotators_answers_are_served(self, ls_server):
        session = _login(ls_server, "ls_user_7")
        response = session.get(f"{ls_server.base_url}/get_annotations",
                               params={"instance_id": "101"})
        assert response.status_code == 200, response.text
        body = response.text
        assert "Neutral" in body            # sentiment
        assert "Trip to Rome" in body       # summary textarea
        assert '"PER"' in body or "PER" in body   # ner span

    def test_agreement_is_computed_over_the_imported_people(self, ls_server):
        response = requests.get(f"{ls_server.base_url}/admin/api/agreement",
                                headers={"X-API-Key": ADMIN_KEY})
        assert response.status_code == 200, response.text
        sentiment = response.json()["by_schema"]["sentiment"]
        assert "error" not in sentiment, sentiment
        # Item 101: Neutral vs Positive. Item 102: Positive vs Positive.
        # Nominal alpha: Do = 2/4, De = (1*3*2)/(4*3) = 0.5, so alpha = 0.
        assert sentiment["krippendorff_alpha"] == pytest.approx(0.0, abs=1e-6)

    def test_the_iaa_page_reports_the_imported_people(self, ls_server):
        """The docs point people at /admin/iaa, so check that page too."""
        from bs4 import BeautifulSoup
        response = requests.get(f"{ls_server.base_url}/admin/iaa",
                                headers={"X-API-Key": ADMIN_KEY})
        assert response.status_code == 200, response.text[:300]
        text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        # The page embeds the report as JSON. /admin/iaa scores only items that
        # have reached their annotator cap, which the importer sets from the
        # source study (here: two people per task).
        match = re.search(r'"sentiment":\{"annotation_type":"radio","kind":"nominal",'
                          r'"metrics":(\{[^{}]*\})', text)
        assert match, text[:800]
        metrics = json.loads(match.group(1))
        assert metrics["n_items"] == 2 and metrics["n_annotators"] == 2, metrics
        assert metrics["alpha_nominal"] == pytest.approx(0.0, abs=1e-6), metrics

    def test_items_the_source_finished_count_as_complete(self, ls_server):
        """Both tasks had two annotators, so the cap of two leaves no work."""
        session = _login(ls_server, "newcomer")
        page = session.get(f"{ls_server.base_url}/annotate").text
        assert 'id="instance_id"' not in page
        assert "already has as many annotators as it needs" in page

    def test_a_name_outside_the_roster_cannot_sign_in(self, ls_server):
        """--keep-annotators closes enrolment to the imported names."""
        session = _login(ls_server, "stranger")
        response = session.get(f"{ls_server.base_url}/annotate")
        assert 'id="instance_id"' not in response.text
        assert "Enter your username" in response.text


@pytest.fixture(scope="module")
def ls_server_suggestions_only():
    """The same export without --keep-annotators: suggestions only, no cap."""
    test_dir = create_test_directory("import_ls_suggestions")
    project = os.path.join(test_dir, "project")
    assert import_main([
        "-i", os.path.join(FIXTURES, "label_studio", "text_project.json"),
        "--ls-config", os.path.join(FIXTURES, "label_studio", "text_label_config.xml"),
        "-o", project,
    ]) == 0
    server = _start(project)
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


class TestSuggestionsOnly:
    def test_a_new_annotator_sees_the_model_suggestion(self, ls_server_suggestions_only):
        from bs4 import BeautifulSoup
        server = ls_server_suggestions_only
        session = requests.Session()
        session.post(f"{server.base_url}/register", data={"email": "newcomer", "pass": "pw"})
        session.post(f"{server.base_url}/auth", data={"email": "newcomer", "pass": "pw"})
        soup = BeautifulSoup(session.get(f"{server.base_url}/annotate").text, "html.parser")
        assert soup.find("input", {"id": "instance_id"})["value"] == "101"
        # Item 101's highest-scoring prediction (sentiment-v2, 0.91) says Neutral;
        # the lower-scoring one said Positive.
        checked = [i.get("value") for i in soup.find_all("input", {"name": "sentiment"})
                   if i.has_attr("checked")]
        assert checked == ["Neutral"], checked


@pytest.fixture(scope="module")
def argilla_server():
    test_dir = create_test_directory("import_argilla_roundtrip")
    project = os.path.join(test_dir, "project")
    assert import_main([
        "-i", os.path.join(FIXTURES, "argilla", "to_disk"),
        "-o", project, "--keep-annotators",
    ]) == 0
    server = _start(project)
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


class TestArgillaDataset:
    def test_an_imported_annotators_answers_are_served(self, argilla_server):
        session = _login(argilla_server, "argilla_1f3a9c2e")
        response = session.get(f"{argilla_server.base_url}/get_annotations",
                               params={"instance_id": "r1"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert "yes" in json.dumps(body["label_annotations"]["helpful"])
        assert body["label_annotations"]["score"] == ["4"] or "4" in json.dumps(body)
        spans = json.dumps(body.get("span_annotations", {}))
        # "Ada Lovelace" (0-12) and "Babbage" (25-32), both PER.
        assert "name:PER, start:0, end:12" in spans, spans
        assert "name:PER, start:25, end:32" in spans, spans

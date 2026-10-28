"""An authenticated participant with an existing LOGIN state must get unstuck."""

import json
from pathlib import Path
import uuid

import pytest
import requests

from potato.phase import UserPhase
from potato.user_state_management import get_user_state_manager
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager as ConfigManager


@pytest.fixture(scope="module", params=[False, True], ids=["annotation", "consent"])
def resume_server(request):
    consent_first = request.param
    phases = {"order": ["annotation"], "annotation": {"type": "annotation"}}
    if consent_first:
        phases["order"].insert(0, "consent")
        phases["consent"] = {"type": "consent", "file": "surveys/consent.json"}
    schemes = [{"name": "choice", "annotation_type": "radio",
                "description": "Choose", "labels": ["yes", "no"]}]
    with ConfigManager("login_resume_" + str(consent_first), schemes,
                       require_password=True, phases=phases) as cfg:
        if consent_first:
            surveys = Path(cfg.test_dir) / "surveys"
            surveys.mkdir(exist_ok=True)
            (surveys / "consent.json").write_text(json.dumps([{
                "name": "agreement", "annotation_type": "radio",
                "description": "Do you agree?", "labels": ["agree", "decline"],
            }]))
        server = FlaskTestServer(config_file=cfg.config_path)
        assert server.start()
        try:
            yield server, Path(cfg.test_dir) / "output", consent_first
        finally:
            server.stop()


@pytest.fixture
def interrupted_login(resume_server):
    server, output, consent_first = resume_server
    username = "resume_" + uuid.uuid4().hex[:12]
    with requests.Session() as session:
        session.max_redirects = 6
        response = session.post(server.base_url + "/register", data={
            "email": username, "pass": "synthetic-password",
        }, timeout=10)
        assert response.status_code == 200
        manager = get_user_state_manager()
        state = manager.get_user_state(username)
        expected = state.get_current_phase_and_page()
        assert expected[0] == (UserPhase.CONSENT if consent_first else UserPhase.ANNOTATION)
        # Model an initialized/restored state that never left LOGIN, while
        # retaining the valid authenticated browser session.
        state.advance_to_phase(UserPhase.LOGIN, None)
        manager.save_user_state(state)
        yield session, username, state, expected, output


@pytest.mark.parametrize("path", ["/", "/auth", "/annotate"])
def test_active_session_resumes_at_the_configured_first_page(
        resume_server, interrupted_login, path):
    server, _, _ = resume_server
    session, username, state, expected, output = interrupted_login
    response = session.get(server.base_url + path, timeout=10)
    assert response.status_code == 200
    assert state.get_current_phase_and_page() == expected
    saved = json.loads((output / username / "user_state.json").read_text())
    assert saved["current_phase_and_page"] == list(state.to_json()["current_phase_and_page"])


def test_fresh_password_login_also_resumes_an_existing_login_state(
        resume_server, interrupted_login):
    server, _, _ = resume_server
    _, username, state, expected, _ = interrupted_login
    with requests.Session() as fresh:
        fresh.max_redirects = 6
        response = fresh.post(server.base_url + "/auth", data={
            "email": username, "pass": "synthetic-password",
        }, timeout=10)
        assert response.status_code == 200
    assert state.get_current_phase_and_page() == expected


def test_failed_authentication_does_not_advance_the_state(resume_server, interrupted_login):
    server, _, _ = resume_server
    _, username, state, _, _ = interrupted_login
    with requests.Session() as fresh:
        response = fresh.post(server.base_url + "/auth", data={
            "email": username, "pass": "wrong-password",
        }, timeout=10)
        assert "Invalid user ID or password" in response.text
    assert state.get_phase() == UserPhase.LOGIN


def test_anonymous_visit_does_not_advance_an_existing_user(resume_server, interrupted_login):
    server, _, _ = resume_server
    _, _, state, _, _ = interrupted_login
    assert requests.get(server.base_url + "/auth", timeout=10).status_code == 200
    assert state.get_phase() == UserPhase.LOGIN


def test_repeated_visits_do_not_advance_past_the_first_page(
        resume_server, interrupted_login):
    server, _, _ = resume_server
    session, _, state, expected, _ = interrupted_login
    for _ in range(2):
        assert session.get(server.base_url + "/auth", timeout=10).status_code == 200
        assert state.get_current_phase_and_page() == expected


def test_a_completed_state_is_not_reopened(resume_server, interrupted_login):
    server, _, _ = resume_server
    session, _, state, _, _ = interrupted_login
    state.advance_to_phase(UserPhase.DONE, None)
    response = session.get(server.base_url + "/auth", allow_redirects=False, timeout=10)
    assert response.status_code == 302
    assert state.get_phase() == UserPhase.DONE

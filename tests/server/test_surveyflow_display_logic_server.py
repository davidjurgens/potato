"""
Server integration tests for SurveyFlow conditional display_logic (issue #165).

- A prestudy survey whose JSON questions carry `display_logic` boots and renders
  the display-logic wrapper markup (so the frontend engine can act on it).
- A survey `display_logic` with an unknown reference fails fast at startup
  rather than silently reaching the frontend as a no-op.
"""

import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)


PRESTUDY_QUESTIONS = [
    {
        "name": "prior_experience",
        "annotation_type": "radio",
        "description": "Have you annotated before?",
        "labels": ["Yes", "No"],
        "label_requirement": {"required": True},
    },
    {
        "name": "experience_details",
        "annotation_type": "text",
        "description": "Describe your experience.",
        "label_requirement": {"required": True},
        "display_logic": {
            "show_when": [
                {"schema": "prior_experience", "operator": "equals", "value": "Yes"}
            ],
            "logic": "all",
        },
    },
]


def _write_prestudy(test_dir, questions):
    path = os.path.join(test_dir, "prestudy.json")
    with open(path, "w") as f:
        json.dump(questions, f)
    return path


def _auth_session(base_url, username):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"action": "signup", "email": username, "pass": "pass"}, timeout=5)
    s.post(f"{base_url}/auth", data={"action": "login", "email": username, "pass": "pass"}, timeout=5)
    s.get(f"{base_url}/annotate", timeout=5)
    return s


class TestSurveyflowDisplayLogicRenders:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("surveyflow_dl_ok")
        data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hello"}])
        prestudy_file = _write_prestudy(test_dir, PRESTUDY_QUESTIONS)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {"name": "rating", "annotation_type": "radio", "labels": ["good", "bad"],
                 "description": "Rate."}
            ],
            data_files=[data_file],
            phases={
                "order": ["prestudy", "annotation"],
                "prestudy": {"type": "prestudy", "file": prestudy_file},
            },
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        return server

    def test_server_boots(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/", timeout=5, allow_redirects=False)
        assert r.status_code in (200, 302)

    def test_prestudy_page_has_display_logic_wrapper(self, flask_server):
        session = _auth_session(flask_server.base_url, "dl_render_user")
        r = session.get(f"{flask_server.base_url}/", timeout=5)
        assert r.status_code == 200
        html = r.text
        # The conditional question is wrapped for the frontend engine and starts hidden.
        assert 'data-display-logic-target="true"' in html
        assert 'data-schema-name="experience_details"' in html
        assert "display-logic-hidden" in html
        # The unconditional trigger question is NOT wrapped.
        assert 'data-schema-name="prior_experience"' in html


class TestSurveyflowDisplayLogicFailFast:
    def test_unknown_reference_aborts_startup(self, request):
        test_dir = create_test_directory("surveyflow_dl_bad")
        data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hello"}])
        bad_questions = [
            {"name": "q1", "annotation_type": "radio", "labels": ["Yes", "No"]},
            {
                "name": "q2",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [{"schema": "does_not_exist", "operator": "equals", "value": "Yes"}]
                },
            },
        ]
        prestudy_file = _write_prestudy(test_dir, bad_questions)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {"name": "rating", "annotation_type": "radio", "labels": ["good", "bad"],
                 "description": "Rate."}
            ],
            data_files=[data_file],
            phases={
                "order": ["prestudy", "annotation"],
                "prestudy": {"type": "prestudy", "file": prestudy_file},
            },
        )
        server = FlaskTestServer(config=config_file)
        started = server.start()
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        # Boot must fail because the display_logic references a nonexistent question.
        assert not started, "Server unexpectedly started with invalid survey display_logic"

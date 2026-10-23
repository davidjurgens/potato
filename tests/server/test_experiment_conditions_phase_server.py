"""
The phase-page render path (get_current_page_html) exposes the participant's
condition too, so a survey question can be gated on condition.<factor>.
Separate module from test_experiment_conditions_server so the two servers
never overlap in one process.
"""

import json
import os

import pytest

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)
from tests.server.test_experiment_conditions_server import ITEMS, _conditions, _login



@pytest.fixture(scope="module")
def phase_cond_server(request):
    """Same design with a survey page first: the phase-page render path
    (get_current_page_html) must expose the condition as well."""
    test_dir = create_test_directory("experiment_conditions_phase_server")
    data_file = create_test_data_file(test_dir, ITEMS)
    survey = os.path.join(test_dir, "survey.json")
    with open(survey, "w") as f:
        json.dump([
            {"name": "age", "annotation_type": "number", "description": "Age?"},
            {"name": "font_probe", "annotation_type": "text", "description": "Serif only.",
             "display_logic": {"show_when": [
                 {"schema": "condition.font", "operator": "equals", "value": "serif"}]}},
        ], f)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{"name": "rating", "annotation_type": "radio",
                             "labels": ["good", "bad"], "description": "Rate."}],
        data_files=[data_file],
        phases={"order": ["survey", "annotation"],
                "survey": {"type": "prestudy", "file": survey}},
        additional_config={"conditions": {"factors": {"font": ["serif", "sans"]}}},
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
    return server


def test_phase_page_exposes_condition(phase_cond_server):
    s = _login(phase_cond_server.base_url, "phase_cond_user")
    html = s.get(f"{phase_cond_server.base_url}/", timeout=5).text
    assert 'data-schema-name="age"' in html, "expected the survey page first"
    conds = _conditions(html)
    assert conds is not None and conds["font"] in ("serif", "sans")

"""
Server tests for between-subjects conditions.

Participants register over HTTP and are assigned a cell of a one-factor
design. `batch_assignment.group_by_condition` routes each one to the item
list named after their level, a question gated on `condition.list` renders
for one level only, and the assignment is written to user_state.json.
"""

import json
import os
import re

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ITEMS = [
    {"id": "a1", "text": "List A item one"},
    {"id": "a2", "text": "List A item two"},
    {"id": "b1", "text": "List B item one"},
    {"id": "b2", "text": "List B item two"},
]


@pytest.fixture(scope="module")
def cond_server(request):
    test_dir = create_test_directory("experiment_conditions_server")
    data_file = create_test_data_file(test_dir, ITEMS)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[
            {"name": "rating", "annotation_type": "radio", "labels": ["good", "bad"],
             "description": "Rate."},
            {"name": "list_b_probe", "annotation_type": "text",
             "description": "Only list B sees this.",
             "display_logic": {"show_when": [
                 {"schema": "condition.list", "operator": "equals", "value": "list_b"}]}},
        ],
        data_files=[data_file],
        assignment_strategy="batch",
        max_annotations_per_item=-1,
        additional_config={
            "conditions": {"factors": {"list": ["list_a", "list_b"]}},
            "batch_assignment": {
                "auto_assign_annotators": True,
                "group_by_condition": "list",
                "groups": [
                    {"name": "list_a", "instances": ["a1", "a2"]},
                    {"name": "list_b", "instances": ["b1", "b2"]},
                ],
            },
        },
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
    return server


def _login(base_url, username):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"action": "signup", "email": username, "pass": "pass"}, timeout=5)
    s.post(f"{base_url}/auth", data={"action": "login", "email": username, "pass": "pass"}, timeout=5)
    return s


def _conditions(html):
    m = re.search(r"window\.potatoConditions = (\{.*?\});", html)
    return json.loads(m.group(1)) if m else None


def _output_dir(server):
    with open(server.config) as f:
        cfg = yaml.safe_load(f)
    out = cfg["output_annotation_dir"]
    return out if os.path.isabs(out) else os.path.join(os.path.dirname(server.config), out)


def test_participants_are_balanced_and_routed(cond_server):
    seen = {}
    for i in range(4):
        name = f"cond_user_{i}"
        s = _login(cond_server.base_url, name)
        html = s.get(f"{cond_server.base_url}/annotate", timeout=5).text
        conds = _conditions(html)
        assert conds is not None, "window.potatoConditions missing from the annotation page"
        level = conds["list"]
        seen.setdefault(level, []).append(name)
        expected_text = "List A item" if level == "list_a" else "List B item"
        other_text = "List B item" if level == "list_a" else "List A item"
        assert expected_text in html
        assert other_text not in html
    assert sorted(len(v) for v in seen.values()) == [2, 2]


def test_condition_is_persisted(cond_server):
    s = _login(cond_server.base_url, "cond_persist")
    html = s.get(f"{cond_server.base_url}/annotate", timeout=5).text
    level = _conditions(html)["list"]
    # Any save writes the state file.
    item = "a1" if level == "list_a" else "b1"
    s.post(f"{cond_server.base_url}/updateinstance",
           json={"instance_id": item, "annotations": {"rating:::good": "good"},
                 "span_annotations": []}, timeout=5)
    with open(os.path.join(_output_dir(cond_server), "cond_persist", "user_state.json")) as f:
        state = json.load(f)
    assert state["flow_record"]["conditions"] == {"list": level}
    assert isinstance(state["flow_record"]["condition_ordinal"], int)


def test_server_requires_condition_gated_scheme_only_in_its_cell(cond_server):
    # The display_logic wrapper is rendered for everyone; which cell sees the
    # question is decided by window.potatoConditions in the browser. Here we
    # check the server-side counterpart: hidden-scheme computation for the
    # required-answer check reads the condition.
    from potato.flask_server import _hidden_scheme_names
    from potato.user_state_management import get_user_state_manager
    usm = get_user_state_manager()
    a = next(u for u in usm.get_all_users()
             if (u.flow_record.get("conditions") or {}).get("list") == "list_a")
    b = next(u for u in usm.get_all_users()
             if (u.flow_record.get("conditions") or {}).get("list") == "list_b")
    assert "list_b_probe" in _hidden_scheme_names(a, "a1")
    assert "list_b_probe" not in _hidden_scheme_names(b, "b1")


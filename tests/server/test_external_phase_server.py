"""type: external over HTTP: the page links out with the participant, run and
return address filled in; only the participant's current run can come back;
the return stores the listed parameters and moves the participant on."""

import json
import os
import re
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file, create_test_directory)


@pytest.fixture(scope="module")
def ext_server(request):
    d = create_test_directory("external_phase_server")
    data = create_test_data_file(d, [{"id": "1", "text": "hello"}])
    after = os.path.join(d, "after.json")
    with open(after, "w") as f:
        json.dump([{"name": "code_seen", "annotation_type": "text", "description": "Thanks"}], f)
    config = create_test_config(
        d, annotation_schemes=[{"name": "r", "annotation_type": "radio", "labels": ["a", "b"],
                                "description": "R"}],
        data_files=[data],
        phases={"order": ["game", "after", "annotation"],
                "game": {"type": "external",
                         "url": "https://otree.example.org/room/s1/?participant_label={participant}&back={return_url}&arm={condition.arm}",
                         "return_params": ["payoff"]},
                "after": {"type": "prestudy", "file": after,
                          "show_when": [{"schema": "game_returned", "operator": "equals", "value": "yes"}]}},
        additional_config={"conditions": {"factors": {"arm": ["solo", "solo2"]}, "assignment": "round_robin"}})
    server = FlaskTestServer(config=config)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(d)))
    return server


def test_link_out_and_return(ext_server):
    base = ext_server.base_url
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": "ext_user", "pass": "p"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": "ext_user", "pass": "p"}, timeout=5)
    page = s.get(f"{base}/", timeout=5).text
    cfg = json.loads(re.search(r'id="potato-runtime-config">(.*?)</script>', page, re.S).group(1))
    link = urlparse(cfg["runtime"]["link"])
    q = parse_qs(link.query)
    assert link.netloc == "otree.example.org" and q["participant_label"] == ["ext_user"]
    assert q["arm"][0] in ("solo", "solo2")
    back = urlparse(q["back"][0])
    assert back.path == "/runtime/game/return" and parse_qs(back.query)["run"] == [cfg["run_id"]]

    stale = s.get(f"{base}/runtime/game/return?run=bogus&payoff=9", timeout=5, allow_redirects=False)
    assert stale.status_code == 409

    r = s.get(f"{base}{back.path}?{back.query}&payoff=4.50&junk=x", timeout=5)
    assert 'data-schema-name="code_seen"' in r.text     # moved on, and the gated page shows
    from potato.user_state_management import get_user_state_manager
    rec = get_user_state_manager().get_user_state("ext_user").flow_record
    assert rec["runtime_answers"] == {"game_returned": "yes", "game_payoff": "4.50"}
    from potato.flask_server import config as live
    from potato.runtimes import store
    run = store.get_run(live["task_dir"], cfg["run_id"])
    assert run["status"] == "complete" and run["trials"][0]["params"] == {"payoff": "4.50"}


def test_return_without_a_session_goes_home(ext_server):
    r = requests.get(f"{ext_server.base_url}/runtime/game/return?run=x", timeout=5,
                     allow_redirects=False)
    assert r.status_code in (302, 303)

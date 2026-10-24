"""type: external with return_secret: a return must carry a valid sig.

A participant can read their own run id from the link they are handed, so an
unsigned return lets them type any payoff (audit 97 T6)."""

import json
import re
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
import requests

from potato.runtimes.adapters.external import return_signature
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file, create_test_directory)

SECRET = "s3cret-shared-with-otree"


@pytest.fixture(scope="module")
def signed_server(request):
    d = create_test_directory("external_phase_signed_server")
    data = create_test_data_file(d, [{"id": "1", "text": "hello"}])
    config = create_test_config(
        d, annotation_schemes=[{"name": "r", "annotation_type": "radio", "labels": ["a", "b"],
                                "description": "R"}],
        data_files=[data],
        phases={"order": ["game", "annotation"],
                "game": {"type": "external",
                         "url": "https://otree.example.org/room/s1/?participant_label={participant}&back={return_url}",
                         "return_params": ["payoff"], "return_secret": SECRET}})
    server = FlaskTestServer(config=config, port=9871)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(d)))
    return server


def _login(base, name):
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "p"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "p"}, timeout=5)
    page = s.get(f"{base}/", timeout=5).text
    cfg = json.loads(re.search(r'id="potato-runtime-config">(.*?)</script>', page, re.S).group(1))
    assert SECRET not in page
    back = urlparse(parse_qs(urlparse(cfg["runtime"]["link"]).query)["back"][0])
    return s, cfg["run_id"], back.path


def _answers(name):
    from potato.user_state_management import get_user_state_manager
    return get_user_state_manager().get_user_state(name).flow_record.get("runtime_answers") or {}


def test_a_forged_return_is_refused(signed_server):
    base = signed_server.base_url
    s, run_id, path = _login(base, "forger")
    for query in ({"run": run_id, "payoff": "99"},
                  {"run": run_id, "payoff": "99", "sig": "0" * 64},
                  {"run": run_id, "payoff": "99",
                   "sig": return_signature(SECRET, run_id, {"payoff": "1.00"})}):
        r = s.get(f"{base}{path}?{urlencode(query)}", timeout=5, allow_redirects=False)
        assert r.status_code == 409, query
        assert "could not be confirmed" in r.text
    assert "game_payoff" not in _answers("forger")


def test_a_signed_return_is_accepted(signed_server):
    base = signed_server.base_url
    s, run_id, path = _login(base, "player")
    sig = return_signature(SECRET, run_id, {"payoff": "4.50"})
    r = s.get(f"{base}{path}?{urlencode({'run': run_id, 'payoff': '4.50', 'sig': sig})}",
              timeout=5, allow_redirects=False)
    assert r.status_code in (302, 303)
    assert _answers("player") == {"game_returned": "yes", "game_payoff": "4.50"}

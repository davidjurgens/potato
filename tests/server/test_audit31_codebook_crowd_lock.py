"""
A crowd backend must force-lock the codebook however the platform is named.

`get_codebook_mode` force-locks `fixed` when the deployment is a crowd
backend, because annotators on a paid HIT must not reshape the shared
codebook. `_crowd_backend` used to read only the legacy spellings -- a
top-level `prolific:`/`mturk:` block, or `login.type` -- and never
`crowdsourcing.provider`, which is the documented way to name a crowd
platform and the key the codebook_mode registry entry itself points at.

Two configs naming the same platform, differing only in how they name it,
gave paid workers opposite protection. The protected one was the legacy
spelling, so the control was strongest on the path nobody is told to use.

Driven to the real 403 rather than asserted on the resolver: the mode is
only worth anything because /api/codebook gates add, edit and delete on
it, and a resolver returning "fixed" while the route still writes is the
failure this file has to be able to see.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory, create_test_data_file, create_test_config,
    cleanup_test_directory)

_CB = [{"name": "themes", "description": "T", "annotation_type": "multiselect",
        "codebook": True, "labels": ["alpha", "beta"]}]


def _run(tag, crowd_config):
    """Start a study with `codebook_mode: open`, then have a plain
    annotator try to add a code. Returns the HTTP status."""
    test_dir = create_test_directory("cb_lock_" + tag)
    data_file = create_test_data_file(test_dir, [{"id": "i1", "text": "x"}])
    additional = {"codebook_mode": "open"}
    additional.update(crowd_config)
    config_file = create_test_config(
        test_dir, _CB, data_files=[data_file], require_password=False,
        additional_config=additional)
    server = FlaskTestServer(port=find_free_port(), debug=False,
                             config_file=config_file)
    if not server.start_server():
        cleanup_test_directory(test_dir)
        pytest.fail("server did not start")
    server._wait_for_server_ready(timeout=10)
    try:
        session = requests.Session()
        session.post(f"{server.base_url}/register",
                     data={"email": "worker", "pass": "p"})
        session.post(f"{server.base_url}/auth",
                     data={"email": "worker", "pass": "p"})
        response = session.post(f"{server.base_url}/api/codebook",
                                json={"name": "WORKER_INJECTED_CODE"})
        return response.status_code, response.text
    finally:
        server.stop_server()
        cleanup_test_directory(test_dir)


@pytest.mark.parametrize("tag,crowd", [
    ("legacy_prolific", {"prolific": {"completion_code": "ABC123"}}),
    ("legacy_mturk", {"mturk": {"aws_access_key_id": "x"}}),
    ("provider_prolific", {"crowdsourcing": {"provider": "prolific"}}),
    ("provider_mturk", {"crowdsourcing": {"provider": "mturk"}}),
    ("provider_connect", {"crowdsourcing": {"provider": "connect"}}),
    ("provider_sona", {"crowdsourcing": {"provider": "sona"}}),
    ("provider_microworkers", {"crowdsourcing": {"provider": "microworkers"}}),
    ("provider_clickworker", {"crowdsourcing": {"provider": "clickworker"}}),
    ("provider_generic", {"crowdsourcing": {"provider": "generic"}}),
])
def test_a_crowd_worker_cannot_add_a_code(tag, crowd):
    status, body = _run(tag, crowd)
    assert status == 403, f"{tag}: a crowd worker added a code ({body[:200]})"


def test_an_unrecognized_provider_still_locks():
    """A typo must not switch the control off. `prolfic` is not a
    provider this version knows, and neither is a platform added after
    it -- both arrive locked and get trusted deliberately or not at
    all."""
    status, body = _run("provider_typo",
                        {"crowdsourcing": {"provider": "prolfic"}})
    assert status == 403, body[:200]


def test_a_hired_expert_keeps_an_open_codebook():
    """The one provider that stays open. Experts are pre-authorized by
    invite token and hired by name -- a collaborator doing QDA, not an
    anonymous worker on a HIT -- and locking them would silently change
    behaviour for a legitimate design."""
    status, body = _run("provider_expert",
                        {"crowdsourcing": {"provider": "expert"}})
    assert status == 200, body[:200]


def test_a_study_with_no_crowd_backend_is_untouched():
    """The control must not have locked ordinary open codebooks."""
    status, body = _run("no_crowd", {})
    assert status == 200, body[:200]


def test_a_crowdsourcing_block_naming_no_provider_is_not_a_crowd_backend():
    """`crowdsourcing: {enabled: true}` with no provider does not select
    one, so it must not lock -- otherwise the presence of the block
    alone becomes the control, which is not what it reads."""
    status, body = _run("crowd_no_provider",
                        {"crowdsourcing": {"enabled": True}})
    assert status == 200, body[:200]

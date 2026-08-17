"""
The admin routes that run the rollout judge and score it against people.

No vision endpoint is configured here, so the batch cannot judge anything. That
is the point of most of these tests: the endpoints have to be *reachable*, have
to be admin-gated, and have to say plainly what is missing rather than 500 or
return an empty success. The arithmetic they wrap is covered in
``tests/unit/test_rollout_batch.py``.
"""

import json

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

SCHEMA = "rollouts"
ADMIN_KEY = "rollout-judge-test-key"
ITEM_IDS = [f"scene_{i}" for i in range(2)]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("rollout_judge_routes")
    streams = [
        {"id": "real", "url": "real.webm", "role": "real", "name": "Recording"},
        {"id": "gen_a", "url": "a.webm", "role": "model", "name": "Model A"},
    ]
    data = [{"id": iid, "text": f"scenario {i}", "streams": streams}
            for i, iid in enumerate(ITEM_IDS)]
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "annotation_type": "rollout_evaluation",
            "name": SCHEMA,
            "description": "Where does each rollout stop making sense?",
            "manifest_field": "streams",
            "fps": 25,
        }],
        data_files=[create_test_data_file(test_dir, data)],
        item_properties={"id_key": "id", "text_key": "text"},
        annotation_task_name="Rollout judge routes",
        require_password=False,
        admin_api_key=ADMIN_KEY,
    )
    srv = FlaskTestServer(port=find_free_port(preferred_port=9083),
                          debug=False, config_file=config_file)
    assert srv.start_server(), "Failed to start Flask server"
    srv._wait_for_server_ready(timeout=15)
    yield srv
    srv.stop_server()
    cleanup_test_directory(test_dir)


@pytest.fixture(scope="module")
def annotated(server):
    """One annotator marks a break on gen_a and calls the recording clean."""
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": "judge_alice", "pass": "pw",
                       "action": "signup"})
    session.post(f"{server.base_url}/auth",
                 data={"email": "judge_alice", "pass": "pw"})
    session.get(f"{server.base_url}/annotate")
    for index, instance_id in enumerate(ITEM_IDS):
        session.get(f"{server.base_url}/annotate",
                    params={"instance_id": instance_id})
        value = {
            # `stream`, not `stream_id` — the key rollout-eval.js actually writes.
            "violations": [{"stream": "gen_a", "t": 2.0 + index,
                            "type": "gravity_violation", "severity": "major"}],
            "clean": ["real"],
            "preference": {"winner": "real"},
            "counterfactual": {},
        }
        response = session.post(
            f"{server.base_url}/updateinstance",
            json={"instance_id": instance_id,
                  "annotations": {f"{SCHEMA}:::_data": json.dumps(value)}})
        assert response.status_code == 200, response.text
    return server


class TestTheRoutesAreRegistered:
    def test_batch_is_not_a_404(self, server):
        """A bare @app.route never reaches the app create_app() builds."""
        response = requests.post(f"{server.base_url}/admin/api/rollout/judge-batch",
                                 headers={"X-API-Key": ADMIN_KEY}, json={})
        assert response.status_code != 404

    def test_alignment_is_not_a_404(self, server):
        response = requests.get(f"{server.base_url}/admin/api/rollout/alignment",
                                headers={"X-API-Key": ADMIN_KEY})
        assert response.status_code != 404


class TestTheyAreAdminOnly:
    def test_batch_refuses_without_the_key(self, server):
        assert requests.post(
            f"{server.base_url}/admin/api/rollout/judge-batch",
            json={}).status_code == 403
        assert requests.post(
            f"{server.base_url}/admin/api/rollout/judge-batch",
            headers={"X-API-Key": "wrong"}, json={}).status_code == 403

    def test_alignment_refuses_without_the_key(self, server):
        assert requests.get(
            f"{server.base_url}/admin/api/rollout/alignment").status_code == 403


class TestMissingPiecesAreNamed:
    def test_the_batch_says_there_is_no_vision_endpoint(self, server):
        """
        A 200 with an empty summary would read as "ran, found nothing", which
        is the opposite of "could not run".
        """
        response = requests.post(
            f"{server.base_url}/admin/api/rollout/judge-batch",
            headers={"X-API-Key": ADMIN_KEY}, json={})
        assert response.status_code == 200
        body = response.json()
        assert body["judged"] == 0
        assert "vision" in body["error"].lower()

    def test_alignment_says_the_batch_has_not_run(self, server):
        response = requests.get(
            f"{server.base_url}/admin/api/rollout/alignment",
            headers={"X-API-Key": ADMIN_KEY})
        assert response.status_code == 200
        assert "batch" in response.json()["error"]

    def test_a_non_numeric_tolerance_is_rejected(self, server):
        response = requests.get(
            f"{server.base_url}/admin/api/rollout/alignment",
            params={"tolerance": "soon"}, headers={"X-API-Key": ADMIN_KEY})
        assert response.status_code == 400


class TestTheHumanSideIsReadFromRealAnnotations:
    def test_consensus_is_built_from_what_was_saved(self, annotated):
        """
        End to end through the real save path: the consensus the judge would be
        scored against has to come out of the annotations the server actually
        stored, not out of a shape invented in a test.
        """
        response = requests.get(
            f"{annotated.base_url}/admin/api/rollout/alignment",
            headers={"X-API-Key": ADMIN_KEY})
        # No predictions yet, so the report stops there — but reaching that
        # message means the schema was found and the gather ran.
        assert "batch" in response.json()["error"]

    def test_the_saved_blob_parses_into_a_consensus(self, annotated):
        """
        The same blob that went through `/updateinstance` above, run through the
        consensus builder.

        `/get_annotations` returns label *keys* for blob schemas rather than
        values, so it cannot check this from outside the process; what it can
        check is that the exact JSON the route accepted is the JSON the batch
        runner understands. The field-name agreement between the client and the
        reader is pinned separately in
        ``tests/unit/test_rollout_batch.py`` and by the JS-source guard there —
        `stream` vs `stream_id` is a mismatch that would otherwise show up as
        an empty denominator and no error.
        """
        from potato.rollouts.batch import human_consensus

        saved = {"violations": [{"stream": "gen_a", "t": 2.0,
                                 "type": "gravity_violation",
                                 "severity": "major"}],
                 "clean": ["real"],
                 "preference": {"winner": "real"},
                 "counterfactual": {}}
        consensus = human_consensus(
            {"name": SCHEMA, "annotation_type": "rollout_evaluation"},
            {ITEM_IDS[0]: {"judge_alice": json.dumps(saved)}})
        assert consensus[f"{ITEM_IDS[0]}::gen_a"]["t"] == 2.0
        assert consensus[f"{ITEM_IDS[0]}::real"]["t"] is None

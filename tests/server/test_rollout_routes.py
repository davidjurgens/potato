"""
``/api/rollout/set`` against a real server.

The route exists because two decisions cannot be made in the browser: the panel
order (stable per annotator, or their own second look disagrees with their
first) and the blinding (a client that receives the generator names has them in
the DOM). Both are properties of the *response*, so they can only be checked
here — a unit test of `RolloutSet.to_json` proves the shaping, not that the
route applies it to the right user's session.

The route also has to be registered through ``configure_routes``: a bare
``@app.route`` decorator 404s under ``potato start`` (invariant 4), and
``FlaskTestServer`` builds its own app, so a route that works in development
and 404s here is exactly the failure this file is written to catch.
"""

from __future__ import annotations

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory


ITEMS = [
    {"id": "ball_drop",
     "prompt": "A ball is dropped.",
     "intervention": "",
     "note": "Find the break.",
     "real": "rollouts/ball_drop/real.webm",
     "gen_a": "rollouts/ball_drop/gen_a.webm",
     "gen_b": "rollouts/ball_drop/gen_b.webm"},
    {"id": "block_push",
     "prompt": "A block slides into a wall.",
     "intervention": "The wall moved left at 1.5 s.",
     "intervention_t": 1.5,
     "note": "Find the break.",
     "real": "rollouts/block_push/real.webm",
     "gen_a": "rollouts/block_push/gen_a.webm",
     "gen_b": "rollouts/block_push/gen_b.webm"},
]


def _write_config(test_dir, **schema_overrides):
    media = os.path.join(test_dir, "media", "rollouts")
    os.makedirs(media, exist_ok=True)

    data_file = os.path.join(test_dir, "rollouts.json")
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump(ITEMS, handle)

    scheme = {
        "annotation_type": "rollout_evaluation",
        "name": "rollout_review",
        "description": "Where does it break?",
        "streams": [
            {"field": "real", "name": "Recording", "role": "real"},
            {"field": "gen_a", "name": "Model A"},
            {"field": "gen_b", "name": "Model B"},
        ],
        "fps": 25,
    }
    scheme.update(schema_overrides)

    config = {
        "port": 0,
        "annotation_task_name": "rollout routes",
        "task_dir": test_dir,
        "media_directory": os.path.join(test_dir, "media"),
        "output_annotation_dir": os.path.join(test_dir, "out"),
        "output_annotation_format": "json",
        "data_files": [data_file],
        "item_properties": {"id_key": "id", "text_key": "note"},
        "user_config": {"allow_all_users": True},
        "annotation_schemes": [scheme],
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle)
    return config_path


def _login(server, user):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": user, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    session.get(f"{server.base_url}/annotate")
    return session


class TestRolloutSetRoute:
    @pytest.fixture(scope="class")
    def server(self):
        test_dir = create_test_directory("rollout_routes")
        config_path = _write_config(test_dir)
        server = FlaskTestServer(config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start the rollout test server")
        yield server
        server.stop()

    def test_the_route_is_registered(self, server):
        # A bare @app.route decorator 404s under `potato start`; this asserts
        # the add_url_rule in configure_routes is doing its job.
        response = requests.get(f"{server.base_url}/api/rollout/set"
                                f"?schema=rollout_review")
        assert response.status_code != 404

    def test_unauthenticated_is_refused(self, server):
        response = requests.get(f"{server.base_url}/api/rollout/set"
                                f"?schema=rollout_review")
        assert response.status_code == 401

    def test_a_manifest_comes_back_for_the_current_item(self, server):
        session = _login(server, "alice@example.com")
        payload = session.get(f"{server.base_url}/api/rollout/set"
                              f"?schema=rollout_review").json()
        assert len(payload["streams"]) == 3
        assert payload["fps"] == 25
        assert payload["prompt"]

    def test_an_unknown_schema_is_a_404_naming_the_schema(self, server):
        session = _login(server, "bob@example.com")
        response = session.get(f"{server.base_url}/api/rollout/set"
                               f"?schema=nope")
        assert response.status_code == 404
        assert "nope" in response.json()["error"]

    def test_the_order_is_identical_on_a_second_request(self, server):
        # The property everything rests on: an annotator who reloads must see
        # the same panels in the same places, or their stored answers about
        # "panel B" become unpoolable with their own earlier ones.
        session = _login(server, "carol@example.com")
        url = f"{server.base_url}/api/rollout/set?schema=rollout_review"
        first = [s["stream_id"] for s in session.get(url).json()["streams"]]
        for _ in range(4):
            assert [s["stream_id"]
                    for s in session.get(url).json()["streams"]] == first

    def test_two_annotators_do_not_share_one_order(self, server):
        url = f"{server.base_url}/api/rollout/set?schema=rollout_review"
        orders = set()
        for name in ("d", "e", "f", "g", "h", "i"):
            session = _login(server, f"{name}@example.com")
            orders.add(tuple(s["stream_id"]
                             for s in session.get(url).json()["streams"]))
        assert len(orders) > 1

    def test_blinding_strips_the_generator_names_from_the_response(self, server):
        session = _login(server, "jane@example.com")
        payload = session.get(f"{server.base_url}/api/rollout/set"
                              f"?schema=rollout_review").json()
        names = [s["name"] for s in payload["streams"]]
        assert names == ["A", "B", "C"]
        assert "Model A" not in json.dumps(payload)
        assert payload["blind"] is True


class TestUnblindedAndUnshuffled:
    @pytest.fixture(scope="class")
    def server(self):
        test_dir = create_test_directory("rollout_open")
        config_path = _write_config(test_dir, blind=False, shuffle=False)
        server = FlaskTestServer(config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start the rollout test server")
        yield server
        server.stop()

    def test_without_shuffle_the_order_is_the_configured_one(self, server):
        session = _login(server, "kate@example.com")
        payload = session.get(f"{server.base_url}/api/rollout/set"
                              f"?schema=rollout_review").json()
        assert [s["stream_id"] for s in payload["streams"]] == [
            "real", "gen_a", "gen_b"]

    def test_without_blinding_the_names_and_roles_survive(self, server):
        session = _login(server, "leo@example.com")
        payload = session.get(f"{server.base_url}/api/rollout/set"
                              f"?schema=rollout_review").json()
        assert [s["name"] for s in payload["streams"]] == [
            "Recording", "Model A", "Model B"]
        assert payload["streams"][0]["role"] == "real"


class TestBadSchemaConfiguration:
    @pytest.fixture(scope="class")
    def server(self):
        test_dir = create_test_directory("rollout_wrongtype")
        config_path = _write_config(test_dir)
        # A second, non-rollout schema, so asking for it by name reaches the
        # type check rather than the not-found branch.
        with open(config_path, encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        config["annotation_schemes"].append({
            "annotation_type": "text", "name": "notes",
            "description": "Anything else?"})
        with open(config_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(config, handle)

        server = FlaskTestServer(config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start the rollout test server")
        yield server
        server.stop()

    def test_asking_for_a_non_rollout_schema_says_what_it_actually_is(
            self, server):
        session = _login(server, "mia@example.com")
        response = session.get(f"{server.base_url}/api/rollout/set"
                               f"?schema=notes")
        assert response.status_code == 400
        assert "text" in response.json()["error"]


class TestJudgeRoute:
    @pytest.fixture(scope="class")
    def server(self):
        test_dir = create_test_directory("rollout_judge")
        config_path = _write_config(test_dir)
        server = FlaskTestServer(config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start the rollout test server")
        yield server
        server.stop()

    def test_the_judge_route_is_registered(self, server):
        response = requests.post(f"{server.base_url}/api/rollout/judge",
                                 json={"schema": "rollout_review"})
        assert response.status_code != 404

    def test_unauthenticated_is_refused(self, server):
        response = requests.post(f"{server.base_url}/api/rollout/judge",
                                 json={"schema": "rollout_review"})
        assert response.status_code == 401

    def test_no_vision_endpoint_is_a_503_that_says_why(self, server):
        # Not a 500. The request is fine and the capability is absent, and the
        # message has to name the capability so an admin can add it.
        session = _login(server, "nina@example.com")
        response = session.post(f"{server.base_url}/api/rollout/judge",
                                json={"schema": "rollout_review"})
        assert response.status_code == 503
        assert "vision" in response.json()["error"].lower()

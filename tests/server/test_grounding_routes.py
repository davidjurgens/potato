"""
The grounding expression route, end to end.

The route exists because the schema generator runs without the item and so
cannot know what the phrases are. What can only be checked here is that it is
reachable under the app ``create_app()`` builds, that it reads the item the
annotator is actually on, and that it normalizes the several shapes a benchmark
might use into the one the client expects.
"""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

SCHEMA = "grounding"


def _build(test_dir, scheme_overrides=None, items=None):
    data_file = os.path.join(test_dir, "items.json")
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump(items or [
            {"id": "i0", "text": "a picture",
             "expressions": ["the red cup", "the blue plate"]},
        ], handle)

    scheme = {
        "annotation_type": "grounding_eval",
        "name": SCHEMA,
        "description": "What does each phrase refer to?",
    }
    scheme.update(scheme_overrides or {})

    config = {
        "port": 0,
        "annotation_task_name": "grounding routes",
        "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "out"),
        "data_files": [data_file],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True},
        "annotation_schemes": [scheme],
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle)
    return config_path


def _login(server, user="ground_alice"):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": user, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    session.get(f"{server.base_url}/annotate")
    return session


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("grounding_routes")
    srv = FlaskTestServer(port=find_free_port(),
                          config_file=_build(test_dir))
    if not srv.start():
        pytest.fail("Failed to start the grounding test server")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


class TestTheRoute:
    def test_it_is_registered(self, server):
        """A bare @app.route never reaches the app create_app() builds."""
        response = requests.get(f"{server.base_url}/api/grounding/expressions",
                                params={"schema": SCHEMA})
        assert response.status_code != 404

    def test_it_needs_a_session(self, server):
        response = requests.get(f"{server.base_url}/api/grounding/expressions",
                                params={"schema": SCHEMA})
        assert response.status_code == 401

    def test_it_returns_the_current_items_expressions(self, server):
        session = _login(server)
        body = session.get(f"{server.base_url}/api/grounding/expressions",
                           params={"schema": SCHEMA}).json()
        assert [e["text"] for e in body["expressions"]] == [
            "the red cup", "the blue plate"]
        assert body["instance_id"] == "i0"

    def test_an_unknown_schema_is_a_404(self, server):
        session = _login(server, "ground_bob")
        response = session.get(f"{server.base_url}/api/grounding/expressions",
                               params={"schema": "nope"})
        assert response.status_code == 404

    def test_a_wrong_schema_type_says_which_type_it_is(self, server):
        """A 400 naming the actual type beats a 404 that says nothing."""
        session = _login(server, "ground_carol")
        response = session.get(f"{server.base_url}/api/grounding/expressions",
                               params={"schema": ""})
        assert response.status_code == 404


class TestExpressionShapes:
    """
    A benchmark may ship strings, objects, or a mapping. Normalizing on the
    server means the browser sees one shape and a new source format is a change
    in one place.
    """

    @pytest.mark.parametrize("raw,expected_texts,expected_ids", [
        (["one", "two"], ["one", "two"], ["0", "1"]),
        ([{"id": "a", "text": "one"}], ["one"], ["a"]),
        ([{"expression_id": "x", "expression": "one"}], ["one"], ["x"]),
        ({"k1": "one", "k2": "two"}, ["one", "two"], ["k1", "k2"]),
    ])
    def test_shapes_normalize(self, raw, expected_texts, expected_ids):
        from potato.grounding.routes import normalize_expressions

        result = normalize_expressions(raw)
        assert [e["text"] for e in result] == expected_texts
        assert [e["id"] for e in result] == expected_ids

    def test_a_non_list_is_empty_not_an_exception(self):
        from potato.grounding.routes import normalize_expressions

        assert normalize_expressions(None) == []
        assert normalize_expressions(42) == []


class TestMissingData:
    def test_no_expressions_names_the_field_that_was_read(self):
        """
        An empty list with no explanation reads as "this item has nothing to
        do", which is indistinguishable from a mis-configured field name.
        """
        test_dir = create_test_directory("grounding_empty")
        config_path = _build(test_dir, items=[{"id": "i0", "text": "a picture"}])
        srv = FlaskTestServer(port=find_free_port(), config_file=config_path)
        assert srv.start()
        try:
            session = _login(srv)
            body = session.get(f"{srv.base_url}/api/grounding/expressions",
                               params={"schema": SCHEMA}).json()
            assert body["expressions"] == []
            assert "expressions" in body["warning"]
            assert "expressions_field" in body["warning"]
        finally:
            srv.stop()
            cleanup_test_directory(test_dir)


class TestCaptionMode:
    def test_the_caption_travels_with_the_response(self):
        """
        Rather than being scraped out of the rendered instance, which would
        break the moment a display type wrapped it in markup.
        """
        test_dir = create_test_directory("grounding_caption")
        config_path = _build(
            test_dir,
            scheme_overrides={"expression_source": "spans",
                              "caption_field": "caption"},
            items=[{"id": "i0", "text": "a picture",
                    "caption": "A red bicycle beside a wall."}])
        srv = FlaskTestServer(port=find_free_port(), config_file=config_path)
        assert srv.start()
        try:
            session = _login(srv)
            body = session.get(f"{srv.base_url}/api/grounding/expressions",
                               params={"schema": SCHEMA}).json()
            assert body["caption"] == "A red bicycle beside a wall."
            assert body["expression_source"] == "spans"
            # The phrases are not known in advance in this mode.
            assert body["expressions"] == []
        finally:
            srv.stop()
            cleanup_test_directory(test_dir)

    def test_a_missing_caption_names_the_field(self):
        test_dir = create_test_directory("grounding_nocaption")
        config_path = _build(
            test_dir,
            scheme_overrides={"expression_source": "spans"},
            items=[{"id": "i0", "text": "a picture"}])
        srv = FlaskTestServer(port=find_free_port(), config_file=config_path)
        assert srv.start()
        try:
            session = _login(srv)
            body = session.get(f"{srv.base_url}/api/grounding/expressions",
                               params={"schema": SCHEMA}).json()
            assert "caption_field" in body["warning"]
        finally:
            srv.stop()
            cleanup_test_directory(test_dir)

"""
Copy-annotations-from-the-previous-image (V7's carry-over).

The route reads only the requesting user's own state, so it exposes nothing
they could not get by pressing Previous -- these tests pin that, along with the
boundary behaviour at the start of the queue, which the button has to render as
an ordinary empty result rather than an error.
"""

import json

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


SCHEMA = "objects"

#: One bbox and one mask, in the exact shape the client serializes.
CLIENT_BLOB = [
    {"type": "bbox", "label": "car", "color": "#f00",
     "coordinates": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}},
    {"type": "mask", "label": "road", "color": "#0f0",
     "rle": {"counts": [0, 5, 95], "size": [10, 10]}},
]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("carry_over_test")
    data = [
        {"id": "img_1", "text": "one", "image_url": "http://example.invalid/1.jpg"},
        {"id": "img_2", "text": "two", "image_url": "http://example.invalid/2.jpg"},
        {"id": "img_3", "text": "three", "image_url": "http://example.invalid/3.jpg"},
    ]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "annotation_type": "image_annotation",
            "name": SCHEMA,
            "description": "Objects",
            "tools": ["bbox", "brush"],
            "labels": [{"name": "car", "color": "#f00"},
                       {"name": "road", "color": "#0f0"}],
            "carry_over": "prompt",
        }],
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "text"},
        annotation_task_name="Carry Over Test",
        require_password=False,
    )

    srv = FlaskTestServer(port=find_free_port(preferred_port=9061),
                          debug=False, config_file=config_file)
    assert srv.start_server(), "Failed to start Flask server"
    srv._wait_for_server_ready(timeout=15)
    yield srv
    srv.stop_server()
    cleanup_test_directory(test_dir)


def _login(server, user):
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"email": user, "pass": "pw", "action": "signup"})
    s.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    s.get(f"{server.base_url}/annotate")
    return s


def _previous(session, server, schema=SCHEMA):
    return session.get(f"{server.base_url}/api/image_annotations/previous",
                       params={"schema": schema})


class TestRouteIsRegistered:
    def test_route_is_reachable(self, server):
        """
        A bare @app.route decorator does not reach the app create_app() builds.
        A 404 here means the add_url_rule in configure_routes went missing.
        """
        s = _login(server, "reg_user")
        assert _previous(s, server).status_code != 404


class TestContract:
    def test_requires_a_session(self, server):
        r = requests.get(f"{server.base_url}/api/image_annotations/previous",
                         params={"schema": SCHEMA})
        assert r.status_code == 401

    def test_requires_a_schema(self, server):
        s = _login(server, "noschema_user")
        r = s.get(f"{server.base_url}/api/image_annotations/previous")
        assert r.status_code == 400

    def test_first_item_is_an_empty_result_not_an_error(self, server):
        """
        At the start of the queue there is nothing to copy. That is a normal
        state the button renders, so it must not be a 4xx.
        """
        s = _login(server, "first_user")
        r = _previous(s, server)
        assert r.status_code == 200
        body = r.json()
        assert body["objects"] == []
        assert body["reason"] == "no_previous"

    def test_unknown_schema_returns_empty_not_an_error(self, server):
        s = _login(server, "unknown_schema_user")
        s.get(f"{server.base_url}/annotate")
        r = _previous(s, server, schema="does_not_exist")
        assert r.status_code == 200
        assert r.json()["objects"] == []


class TestReturnsPreviousWork:
    def test_returns_the_previous_items_objects(self, server):
        s = _login(server, "carry_user")

        # Annotate item 1, then move to item 2.
        s.post(f"{server.base_url}/updateinstance", json={
            "instance_id": "img_1",
            "annotations": {f"{SCHEMA}:::_data": json.dumps(CLIENT_BLOB)},
            "span_annotations": {},
        })
        s.get(f"{server.base_url}/annotate", params={"instance_id": "img_2"})

        body = _previous(s, server).json()
        assert body["instance_id"] == "img_1"
        assert body["count"] == 2
        # Round-trips the client contract untouched, so addAnnotation can
        # consume it without a translation layer.
        assert body["objects"] == CLIENT_BLOB

    def test_does_not_leak_another_users_annotations(self, server):
        """The route reads session-scoped state only."""
        owner = _login(server, "owner_user")
        owner.post(f"{server.base_url}/updateinstance", json={
            "instance_id": "img_1",
            "annotations": {f"{SCHEMA}:::_data": json.dumps(CLIENT_BLOB)},
            "span_annotations": {},
        })

        other = _login(server, "other_user")
        other.get(f"{server.base_url}/annotate", params={"instance_id": "img_2"})
        assert _previous(other, server).json()["objects"] == []

    def test_previous_with_no_annotations_is_empty(self, server):
        s = _login(server, "sparse_user")
        s.get(f"{server.base_url}/annotate", params={"instance_id": "img_2"})
        body = _previous(s, server).json()
        assert body["instance_id"] == "img_1"
        assert body["objects"] == []


class TestSchemaWiring:
    def test_button_and_shortcut_only_when_enabled(self):
        from potato.server_utils.schemas.image_annotation import (
            generate_image_annotation_layout,
        )
        base = {"annotation_type": "image_annotation", "name": "seg",
                "description": "d", "tools": ["bbox"],
                "labels": [{"name": "road"}]}

        off_html, off_keys = generate_image_annotation_layout(dict(base))
        on_html, on_keys = generate_image_annotation_layout(
            dict(base, carry_over="prompt"))

        assert "carry-over-btn" not in off_html
        assert "carry-over-btn" in on_html
        assert not any(k == "Ctrl+D" for k, _ in off_keys)
        assert any(k == "Ctrl+D" for k, _ in on_keys)

    @pytest.mark.parametrize("value", [False, "prompt", "auto"])
    def test_valid_carry_over_values(self, value):
        from potato.server_utils.config_module import validate_annotation_schemes
        validate_annotation_schemes({"annotation_schemes": [{
            "annotation_type": "image_annotation", "name": "seg",
            "description": "d", "tools": ["bbox"],
            "labels": [{"name": "road"}], "carry_over": value,
        }]})

    def test_invalid_carry_over_rejected(self):
        from potato.server_utils.config_module import (
            validate_annotation_schemes, ConfigValidationError,
        )
        with pytest.raises(ConfigValidationError, match="carry_over"):
            validate_annotation_schemes({"annotation_schemes": [{
                "annotation_type": "image_annotation", "name": "seg",
                "description": "d", "tools": ["bbox"],
                "labels": [{"name": "road"}], "carry_over": "always",
            }]})

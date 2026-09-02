"""
The /api/critique_annotations route.

Runs against a real server with AI support switched off, which is the
interesting half of the contract: the route must fail clearly and safely
without a model. Behaviour *with* a model is covered by
tests/unit/test_critique_service.py, which drives the same service through a
fake endpoint without a network.
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

SCHEMA = "objects"
ENDPOINT = "/api/critique_annotations"

CLIENT_BLOB = [
    {"type": "bbox", "label": "car", "color": "#f00",
     "coordinates": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}},
]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("critique_route_test")
    data = [
        {"id": "img_1", "text": "one", "image_url": "/media/one.png"},
        {"id": "img_2", "text": "two", "image_url": "/media/two.png"},
    ]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[
            {
                "annotation_type": "image_annotation",
                "name": SCHEMA,
                "description": "Objects",
                "tools": ["bbox"],
                "labels": [{"name": "car", "color": "#f00"},
                           {"name": "road", "color": "#0f0"}],
            },
            {
                "annotation_type": "radio",
                "name": "quality",
                "description": "Quality",
                "labels": ["good", "bad"],
            },
        ],
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "image_url"},
        annotation_task_name="Critique Route Test",
        require_password=False,
    )

    srv = FlaskTestServer(port=find_free_port(preferred_port=9081),
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


def _critique(session, server, **body):
    body.setdefault("schema", SCHEMA)
    return session.post(f"{server.base_url}{ENDPOINT}", json=body)


class TestRouteIsRegistered:
    def test_route_is_reachable(self, server):
        """
        A bare @app.route decorator does not reach the app create_app() builds.
        A 404 here means the add_url_rule in configure_routes went missing.
        """
        s = _login(server, "critique_reg")
        assert _critique(s, server).status_code != 404

    def test_it_is_a_post_only_route(self, server):
        s = _login(server, "critique_method")
        r = s.get(f"{server.base_url}{ENDPOINT}")
        assert r.status_code == 405


class TestContract:
    def test_requires_a_session(self, server):
        r = requests.post(f"{server.base_url}{ENDPOINT}",
                          json={"schema": SCHEMA})
        assert r.status_code == 401

    def test_requires_a_schema(self, server):
        s = _login(server, "critique_noschema")
        r = s.post(f"{server.base_url}{ENDPOINT}", json={})
        assert r.status_code == 400
        assert "schema" in r.json()["error"].lower()

    def test_an_unknown_schema_is_a_404(self, server):
        s = _login(server, "critique_unknown")
        r = _critique(s, server, schema="does_not_exist")
        assert r.status_code == 404

    def test_a_non_image_schema_is_rejected(self, server):
        """Critique crops regions, so a radio schema has nothing to review —
        and answering 200 with an empty result would read as 'reviewed, all
        clear'."""
        s = _login(server, "critique_radio")
        r = _critique(s, server, schema="quality")
        assert r.status_code == 404

    def test_an_unknown_instance_is_a_404(self, server):
        s = _login(server, "critique_badinstance")
        r = _critique(s, server, instance_id="no_such_item",
                      objects=CLIENT_BLOB)
        assert r.status_code == 404


class TestWithoutAModel:
    def test_it_says_what_is_missing_rather_than_failing_opaquely(self, server):
        """This project has no AI support configured. The annotator pressed a
        button that is on screen, so the answer has to name the reason."""
        s = _login(server, "critique_noai")
        r = _critique(s, server, objects=CLIENT_BLOB)
        assert r.status_code in (400, 503)
        message = r.json()["error"].lower()
        assert "ai" in message or "vision" in message

    def test_it_never_returns_a_traceback(self, server):
        s = _login(server, "critique_notrace")
        r = _critique(s, server, objects=CLIENT_BLOB)
        assert "Traceback" not in r.text
        assert "File \"" not in r.text


class TestItDoesNotMutateAnnotations:
    def test_a_critique_request_leaves_stored_work_untouched(self, server):
        """The route is advisory. Nothing it does may edit the annotator's
        work, whatever a model says — every change goes through a button."""
        s = _login(server, "critique_readonly")
        instance = s.get(f"{server.base_url}/api/current_instance").json()
        instance_id = instance.get("instance_id") or instance.get("id")

        s.post(f"{server.base_url}/updateinstance",
               json={"annotations": {f"{SCHEMA}:::_data": json.dumps(CLIENT_BLOB)}})

        before = s.get(f"{server.base_url}/api/image_annotations/previous",
                       params={"schema": SCHEMA}).text
        _critique(s, server, objects=CLIENT_BLOB, instance_id=instance_id)
        after = s.get(f"{server.base_url}/api/image_annotations/previous",
                      params={"schema": SCHEMA}).text
        assert before == after


class TestToolbarWiring:
    def test_the_review_button_renders_when_ai_is_enabled(self):
        from potato.server_utils.schemas.image_annotation import (
            generate_image_annotation_layout,
        )

        html, _ = generate_image_annotation_layout({
            "annotation_type": "image_annotation",
            "name": SCHEMA,
            "description": "Objects",
            "tools": ["bbox"],
            "labels": [{"name": "car", "color": "#f00"}],
            "ai_support": {"enabled": True},
        })
        assert 'data-action="critique"' in html

    def test_it_can_be_switched_off_per_schema(self):
        from potato.server_utils.schemas.image_annotation import (
            generate_image_annotation_layout,
        )

        html, _ = generate_image_annotation_layout({
            "annotation_type": "image_annotation",
            "name": SCHEMA,
            "description": "Objects",
            "tools": ["bbox"],
            "labels": [{"name": "car", "color": "#f00"}],
            "ai_support": {"enabled": True, "features": {"critique": False}},
        })
        assert 'data-action="critique"' not in html

    def test_no_ai_means_no_button(self):
        from potato.server_utils.schemas.image_annotation import (
            generate_image_annotation_layout,
        )

        html, _ = generate_image_annotation_layout({
            "annotation_type": "image_annotation",
            "name": SCHEMA,
            "description": "Objects",
            "tools": ["bbox"],
            "labels": [{"name": "car", "color": "#f00"}],
        })
        assert 'data-action="critique"' not in html


class TestPromptRegistration:
    def test_critique_is_registered_as_an_assistant(self):
        """The capability gate and the toolbar both read this registry."""
        import json as _json
        import pathlib

        prompts = _json.loads(
            pathlib.Path("potato/ai/prompt/image_annotation.json").read_text())
        assert "critique" in prompts
        assert prompts["critique"]["output_format"] == "annotation_critique"

    def test_its_output_format_resolves_to_a_model(self):
        from potato.ai.prompt.models_module import CLASS_REGISTRY

        assert CLASS_REGISTRY["annotation_critique"] is not None
        assert CLASS_REGISTRY["missed_objects"] is not None

    def test_the_registered_prompt_is_deliberately_empty(self):
        """Prompts are built per region in potato/ai/critique.py, because each
        names that region's own label. A prompt filled in here would look
        authoritative and do nothing."""
        import json as _json
        import pathlib

        prompts = _json.loads(
            pathlib.Path("potato/ai/prompt/image_annotation.json").read_text())
        assert prompts["critique"]["prompt"] == ""
        assert "critique.py" in prompts["critique"]["note"]


class TestCapabilityGating:
    def test_a_vision_model_that_can_explain_supports_critique(self):
        from potato.ai.ai_endpoint import ModelCapabilities

        caps = ModelCapabilities(text_generation=True, vision_input=True,
                                 rationale_generation=True)
        assert caps.supports_assistant("critique", has_image_input=True)

    def test_a_detector_does_not(self):
        """YOLO can find boxes but cannot say why it disagrees, and a verdict
        with no reason is not reviewable."""
        from potato.ai.ai_endpoint import ModelCapabilities

        caps = ModelCapabilities(vision_input=True, bounding_box_output=True,
                                 image_classification=True)
        assert not caps.supports_assistant("critique", has_image_input=True)

    def test_a_text_only_model_does_not(self):
        from potato.ai.ai_endpoint import ModelCapabilities

        caps = ModelCapabilities(text_generation=True,
                                 rationale_generation=True)
        assert not caps.supports_assistant("critique", has_image_input=True)

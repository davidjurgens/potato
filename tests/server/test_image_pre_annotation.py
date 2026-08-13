"""
Imported image annotations must actually reach the browser.

The parsing and export sides are covered by tests/unit/test_coco_*.py, but all
of that is worthless if the annotations never make it into the page. Image
schemas used to fall through the pre-annotation prefill's terminal ``else``
("Pre-annotation not yet supported for image_annotation"), so there was no path
at all for seeding them.

This test asserts on the rendered HTML: the hidden `annotation-data-input` for
the schema must carry the imported objects and be flagged `data-server-set`,
which is what ImageAnnotationManager._loadExistingAnnotations() reads.
"""

import json
import os

import pytest
import requests
from bs4 import BeautifulSoup

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, cleanup_test_directory

SCHEMA = "object_detection"

#: Client-shaped objects, exactly what the COCO importer emits.
SEEDED = [
    {"type": "bbox", "label": "person", "color": "#e6194b",
     "coordinates": {"x": 0.125, "y": 0.2083, "width": 0.3125, "height": 0.5}},
    {"type": "polygon", "label": "dog", "color": "#3cb44b",
     "coordinates": [{"x": 0.5625, "y": 0.333}, {"x": 0.875, "y": 0.333},
                     {"x": 0.875, "y": 0.667}, {"x": 0.5625, "y": 0.667}]},
    {"type": "mask", "label": "person", "color": "#e6194b",
     "instance": 0, "iscrowd": 0,
     "rle": {"counts": [0, 8, 8], "size": [4, 4]}},
]


@pytest.fixture(scope="module")
def seeded_server():
    test_dir = create_test_directory("image_pre_annotation")

    data_path = os.path.join(test_dir, "images.json")
    with open(data_path, "w") as f:
        # Item 1 carries pre-annotations; item 2 deliberately does not, so we
        # can tell a seeded page from an unseeded one.
        f.write(json.dumps({
            "id": "img1",
            "image_url": "https://example.invalid/a.jpg",
            "image_width": 64, "image_height": 48,
            "predictions": {SCHEMA: SEEDED},
        }) + "\n")
        f.write(json.dumps({
            "id": "img2",
            "image_url": "https://example.invalid/b.jpg",
            "image_width": 64, "image_height": 48,
        }) + "\n")

    config = {
        "port": 8000,
        "server_name": "test",
        "annotation_task_name": "image pre-annotation",
        "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "image_url"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default",
        "pre_annotation": {"enabled": True, "field": "predictions",
                           "allow_modification": True},
        "annotation_schemes": [{
            "annotation_type": "image_annotation",
            "name": SCHEMA,
            "description": "Correct the imported annotations",
            "source_field": "image_url",
            "tools": ["bbox", "polygon", "brush", "eraser", "fill"],
            "labels": [
                {"name": "person", "color": "#e6194b", "label_id": 1},
                {"name": "dog", "color": "#3cb44b", "label_id": 18},
            ],
        }],
    }

    import yaml
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f)

    server = FlaskTestServer(config_file=config_path)
    if not server.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start server")

    yield server

    server.stop()
    cleanup_test_directory(test_dir)


def _annotate(server, username):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": username, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth",
                 data={"email": username, "pass": "pw", "action": "login"})
    response = session.get(f"{server.base_url}/annotate")
    assert response.status_code == 200, response.text[:400]
    return session, response.text


def _data_input(html, schema=SCHEMA):
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("input", {"name": schema, "class": "annotation-data-input"})


class TestSeededAnnotationsReachThePage:

    def test_the_hidden_input_carries_the_imported_objects(self, seeded_server):
        _session, html = _annotate(seeded_server, "seed_reader")
        field = _data_input(html)

        assert field is not None, (
            "no annotation-data-input rendered for the image schema")
        value = field.get("value")
        assert value, (
            "the image schema's data input is empty — pre-annotations never "
            "reached the page")

        parsed = json.loads(value)
        assert len(parsed) == len(SEEDED)
        assert [o["type"] for o in parsed] == ["bbox", "polygon", "mask"]

    def test_input_is_flagged_server_set(self, seeded_server):
        """populateInputValues() skips data-server-set inputs, so without this
        flag the restored value is treated as browser cache and overwritten."""
        _session, html = _annotate(seeded_server, "seed_flag")
        field = _data_input(html)
        assert field.get("data-server-set") == "true"

    def test_geometry_survives_the_render(self, seeded_server):
        _session, html = _annotate(seeded_server, "seed_geometry")
        parsed = json.loads(_data_input(html).get("value"))

        box = next(o for o in parsed if o["type"] == "bbox")
        assert box["coordinates"]["width"] == pytest.approx(0.3125)
        assert box["label"] == "person"

        polygon = next(o for o in parsed if o["type"] == "polygon")
        assert len(polygon["coordinates"]) == 4

    def test_mask_instance_and_crowd_flags_survive(self, seeded_server):
        """iscrowd=0 must be explicit: a mask with no flag defaults to crowd on
        export, which would collapse imported instances into one blob."""
        _session, html = _annotate(seeded_server, "seed_mask")
        parsed = json.loads(_data_input(html).get("value"))

        mask = next(o for o in parsed if o["type"] == "mask")
        assert mask["instance"] == 0
        assert mask["iscrowd"] == 0
        assert mask["rle"]["size"] == [4, 4]


class TestUnseededItemsAreUntouched:

    def test_an_item_without_predictions_renders_an_empty_input(
            self, seeded_server):
        session, html = _annotate(seeded_server, "unseeded_reader")
        assert _data_input(html).get("value"), "item 1 should be seeded"
        assert "a.jpg" in html

        # Move to item 2, which has no predictions field.
        response = session.post(f"{seeded_server.base_url}/annotate",
                                data={"action": "next_instance"})
        assert response.status_code == 200
        assert "b.jpg" in response.text, "did not advance to the second item"

        field = _data_input(response.text)
        if field is not None:
            assert not field.get("value"), (
                "an item with no predictions was seeded anyway")

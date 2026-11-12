"""
Imported point-cloud objects must reach the browser.

`spatial_annotation` fell through the pre-annotation prefill to "not yet
supported", so a KITTI tracking import (or any `predictions` on a lidar item)
showed an empty viewer. The objects go into the schema's hidden
`annotation-data-input`, flagged `data-server-set`, which is what the viewer's
_restoreFromInput reads.
"""

import json
import os

import pytest
import requests
import yaml
from bs4 import BeautifulSoup

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

SCHEMA = "objects"

#: A two-keyframe track, in the stored contract (metres, sensor frame).
SEEDED = [
    {"type": "cuboid_3d", "label": "car", "frame": frame, "track_id": "7",
     "source": "import",
     "coordinates": {"center": [10.0 + frame, 2.0, -0.9], "size": [4.0, 1.8, 1.5],
                     "rotation": [0.0, 0.0, 0.0, 1.0]}}
    for frame in (0, 2)
]


@pytest.fixture(scope="module")
def seeded_server():
    test_dir = create_test_directory("spatial_pre_annotation")
    data_path = os.path.join(test_dir, "sequences.jsonl")
    with open(data_path, "w") as f:
        f.write(json.dumps({"id": "seq1",
                            "point_cloud": ["f/000000.bin", "f/000001.bin", "f/000002.bin"],
                            "predictions": {SCHEMA: SEEDED}}) + "\n")
    config = {
        "port": 8000,
        "server_name": "test",
        "annotation_task_name": "spatial pre-annotation",
        "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "id"},
        "user_config": {"allow_all_users": True, "users": []},
        "pre_annotation": {"enabled": True, "field": "predictions",
                           "allow_modification": True},
        "annotation_schemes": [{
            "annotation_type": "spatial_annotation",
            "name": SCHEMA,
            "description": "Correct the imported tracks",
            "source_field": "point_cloud",
            "tools": ["cuboid_3d"],
            "labels": [{"name": "car", "color": "#FF6B6B"}],
        }],
    }
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


def test_the_hidden_input_carries_the_imported_track(seeded_server):
    session = requests.Session()
    session.post(f"{seeded_server.base_url}/register",
                 data={"email": "reader", "pass": "pw", "action": "signup"})
    session.post(f"{seeded_server.base_url}/auth",
                 data={"email": "reader", "pass": "pw", "action": "login"})
    response = session.get(f"{seeded_server.base_url}/annotate")
    assert response.status_code == 200, response.text[:400]
    field = BeautifulSoup(response.text, "html.parser").find(
        "input", {"name": SCHEMA, "class": "annotation-data-input"})
    assert field is not None
    assert field.get("data-server-set") == "true"
    assert json.loads(field.get("value")) == SEEDED

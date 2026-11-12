"""
Attribute agreement through the real path: /updateinstance -> /admin/iaa.

The unit tests call the agreement function directly with client-shaped
objects. On a running server the shapes reach it through the IAA gather step,
which converts every stored shape to a canonical form, and that conversion
dropped `attributes`: matched objects came through, values did not, and every
attribute reported "no object was matched". Found by the potato-skill agent on
an imported Label Studio project.
"""

import json
import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)

ADMIN_KEY = "attr-iaa-key"
SCHEME = {
    "annotation_type": "image_annotation", "name": "objects", "description": "Box each car",
    "source_field": "image", "tools": ["bbox"], "labels": ["car"],
    "attributes": [{"name": "occlusion", "type": "select",
                    "options": ["none", "partial", "heavy"]}],
}
OCCLUSION = {"a": ["none", "partial", "heavy"], "b": ["none", "heavy", "heavy"]}


def _blob(value):
    return json.dumps([{"type": "bbox", "label": "car", "source": "human",
                        "coordinates": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.3},
                        "attributes": {"occlusion": value}}])


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("object_attributes_iaa")
    data_file = create_test_data_file(
        test_dir, [{"id": f"img{n}", "image": f"/media/img{n}.png"} for n in range(1, 4)])
    port = find_free_port(preferred_port=9899)
    config_file = create_test_config(
        test_dir, [SCHEME], data_files=[data_file], port=port,
        item_properties={"id_key": "id", "text_key": "image"},
        additional_config={"admin_api_key": ADMIN_KEY, "max_annotations_per_item": 2})
    srv = FlaskTestServer(port=port, debug=False, config_file=config_file)
    if not srv.start():
        pytest.fail("Failed to start server")
    for name, values in OCCLUSION.items():
        session = requests.Session()
        session.post(f"{srv.base_url}/register", data={"email": name, "pass": "pw"})
        session.post(f"{srv.base_url}/auth", data={"email": name, "pass": "pw"})
        session.get(f"{srv.base_url}/annotate")
        for n, value in enumerate(values, start=1):
            response = session.post(f"{srv.base_url}/updateinstance", json={
                "instance_id": f"img{n}",
                "annotations": {"objects:::_data": _blob(value)},
                "span_annotations": [],
            })
            assert response.status_code == 200, response.text
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def test_the_iaa_report_scores_the_attribute(server):
    response = requests.get(f"{server.base_url}/admin/iaa", headers={"X-API-Key": ADMIN_KEY})
    assert response.status_code == 200, response.text[:300]
    match = re.search(r'"occlusion":\s*(\{[^{}]*\})', response.text)
    assert match, response.text[:1500]
    metrics = json.loads(match.group(1).replace("NaN", "null"))
    assert metrics["n_objects"] == 3 and metrics["n_annotators"] == 2, metrics
    # (none, none), (partial, heavy), (heavy, heavy): Do = 2/6, De = 22/30.
    assert metrics["alpha"] == pytest.approx(12 / 22, abs=1e-6), metrics
    assert metrics["percent_agreement"] == pytest.approx(2 / 3), metrics

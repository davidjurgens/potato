"""Audit 97 V6 and V7, through a running server.

V6  Junk spectrogram pre-annotation entries ("a", "junk", a box without
    numeric times) reached the page's hidden input, and so the stored answer
    on an untouched Next. Real boxes are still pre-filled.
V7  A per-item basemap went to the browser unchecked: an item with external
    tiles and no attribution loaded them. /api/instance_data now withholds a
    refused basemap and says why.
"""

import json
import os

import pytest
import requests
import yaml
from bs4 import BeautifulSoup

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory


def _session(server, username):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": username, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth",
                 data={"email": username, "pass": "pw", "action": "login"})
    return session


def _start(test_dir, config, port):
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f)
    server = FlaskTestServer(config_file=config_path, port=port)
    if not server.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start server")
    return server


def _base(test_dir, data_path, schemes, **extra):
    config = {
        "annotation_task_name": "audit 97", "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "id"},
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": schemes,
    }
    config.update(extra)
    return config


@pytest.fixture(scope="class")
def spectrogram_server():
    test_dir = create_test_directory("audit97_spectrogram_prefill")
    data_path = os.path.join(test_dir, "data.jsonl")
    with open(data_path, "w") as f:
        f.write(json.dumps({"id": "rec1", "audio_url": "/media/rec1.wav", "predictions": {
            "calls": ["a", "junk", {"start_s": "x"},
                     {"start_s": 0.5, "end_s": 0.2, "low_hz": 100, "high_hz": 900,
                      "label": "call", "source": "import"}]}}) + "\n")
    server = _start(test_dir, _base(
        test_dir, data_path,
        [{"annotation_type": "spectrogram_annotation", "name": "calls",
          "description": "Check the calls", "source_field": "audio_url", "labels": ["call"]}],
        pre_annotation={"enabled": True, "field": "predictions", "allow_modification": True}),
        port=9761)
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


class TestSpectrogramPrefill:

    def test_junk_spectrogram_prefill_never_reaches_the_page(self, spectrogram_server):
        html = _session(spectrogram_server, "v6").get(f"{spectrogram_server.base_url}/annotate").text
        field = BeautifulSoup(html, "html.parser").find(
            "input", {"name": "calls", "class": "annotation-data-input"})
        assert field is not None and field.get("data-server-set") == "true"
        boxes = json.loads(field["value"])
        assert len(boxes) == 1
        assert (boxes[0]["start_s"], boxes[0]["end_s"]) == (0.2, 0.5)
        assert boxes[0]["source"] == "import"          # still a reviewed import


@pytest.fixture(scope="class")
def geo_server():
    test_dir = create_test_directory("audit97_item_basemap")
    os.makedirs(os.path.join(test_dir, "maps"), exist_ok=True)
    with open(os.path.join(test_dir, "maps", "r.geojson"), "w") as f:
        json.dump({"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"id": "a"},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}]}, f)
    data_path = os.path.join(test_dir, "data.jsonl")
    with open(data_path, "w") as f:
        f.write(json.dumps({"id": "evil", "map": {
            "tiles": "https://evil.example/{z}/{x}/{y}.png"}}) + "\n")
    server = _start(test_dir, _base(
        test_dir, data_path,
        [{"annotation_type": "geo_annotation", "name": "where", "description": "Where?",
          "labels": ["site"], "basemap": {"geojson": "maps/r.geojson"}, "basemap_field": "map"}]),
        port=9762)
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


class TestItemBasemap:

    def test_refused_item_basemap_is_withheld_with_a_reason(self, geo_server):
        session = _session(geo_server, "v7")
        assert session.get(f"{geo_server.base_url}/annotate").status_code == 200
        data = session.get(f"{geo_server.base_url}/api/instance_data").json()
        assert "map" not in data
        assert "attribution" in data["_geo_basemap_refused"]["map"]

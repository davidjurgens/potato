"""
A model's audio segments must reach the waveform as editable regions.

An audio timeline is one JSON object, ``{"segments": [...]}``, which is what
``hf-audio-tagger`` writes back and what
AudioAnnotationManager._loadExistingAnnotations() reads from the schema's
hidden ``annotation-data-input``. ``audio_annotation`` was missing from the
pre-annotation prefill, so a trained tagger's predictions were stored and
never shown.
"""

import json
import os

import pytest
import requests
from bs4 import BeautifulSoup

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

SCHEMA = "calls"

PREDICTED = {"segments": [
    {"id": "model_0", "start_time": 0.5, "end_time": 1.25, "label": "beep",
     "confidence": 0.91},
    {"id": "model_1", "start_time": 2.0, "end_time": 2.4, "label": "beep",
     "confidence": 0.62},
]}


@pytest.fixture(scope="module")
def seeded_server():
    test_dir = create_test_directory("audio_pre_annotation")
    data_path = os.path.join(test_dir, "audio.json")
    with open(data_path, "w") as f:
        f.write(json.dumps({"id": "rec1",
                            "audio_url": "https://example.invalid/rec1.wav",
                            "predictions": {SCHEMA: PREDICTED}}) + "\n")
        f.write(json.dumps({"id": "rec2",
                            "audio_url": "https://example.invalid/rec2.wav"}) + "\n")

    config = {
        "port": 8000,
        "server_name": "test",
        "annotation_task_name": "audio pre-annotation",
        "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "audio_url"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default",
        "pre_annotation": {"enabled": True, "field": "predictions",
                           "allow_modification": True},
        "annotation_schemes": [{
            "annotation_type": "audio_annotation",
            "name": SCHEMA,
            "description": "Correct the model's segments",
            "mode": "label",
            "labels": [{"name": "beep", "color": "#4ECDC4"}],
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


def _first_page(server, username):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": username, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth",
                 data={"email": username, "pass": "pw", "action": "login"})
    response = session.get(f"{server.base_url}/annotate")
    assert response.status_code == 200, response.text[:400]
    return response.text


def _data_input(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("input", {"name": SCHEMA, "class": "annotation-data-input"})


def test_the_predicted_segments_are_in_the_hidden_input(seeded_server):
    field = _data_input(_first_page(seeded_server, "audio_reader"))
    assert field is not None, "no annotation-data-input for the audio schema"
    assert field.get("value"), "the model's segments never reached the page"
    assert json.loads(field["value"]) == PREDICTED
    # Without the flag, populateInputValues() treats the value as browser
    # cache and clears it.
    assert field.get("data-server-set") == "true"

"""
A preference model's choice must pre-select the right pairwise card.

``llm-dpo`` predicts in data order: "A" is the item's first candidate. The
page stores the letter of the card shown first, so with ``randomize_order``
the prediction has to move to wherever this annotator sees that candidate.
Before this, pairwise schemes had no pre-annotation path at all.
"""

import json
import os

import pytest
import requests
from bs4 import BeautifulSoup

from potato.server_utils.presentation_order import item_order
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

ITEM = {"id": "p1", "prompt": "Advice about sleep?",
        "responses": ["Keep a regular bedtime.", "Sleep is overrated."],
        "predictions": {"pref": {"label": "A", "confidence": 0.93}}}


def _server(name, randomize):
    test_dir = create_test_directory(name)
    data_path = os.path.join(test_dir, "pairs.json")
    with open(data_path, "w") as f:
        f.write(json.dumps(ITEM) + "\n")
    config = {
        "port": 8000, "server_name": "test", "annotation_task_name": name,
        "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "responses"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default",
        "pre_annotation": {"enabled": True, "field": "predictions",
                           "allow_modification": True},
        "annotation_schemes": [{
            "annotation_type": "pairwise", "name": "pref",
            "description": "Which answer is more helpful?", "mode": "binary",
            "items_key": "responses", "labels": ["A", "B"],
            "randomize_order": randomize}],
    }
    import yaml
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f)
    server = FlaskTestServer(config_file=config_path)
    if not server.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start server")
    return server, test_dir, config["annotation_schemes"][0]


def _selected(server, username):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": username, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth",
                 data={"email": username, "pass": "pw", "action": "login"})
    html = session.get(f"{server.base_url}/annotate").text
    field = BeautifulSoup(html, "html.parser").find(
        "input", {"class": "pairwise-value", "schema": "pref"})
    assert field is not None, "no pairwise input on the page"
    return field.get("value"), field.get("data-server-set")


@pytest.fixture(scope="module")
def fixed_server():
    server, test_dir, _ = _server("pairwise_prelabel_fixed", False)
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture(scope="module")
def shuffled_server():
    server, test_dir, scheme = _server("pairwise_prelabel_shuffled", True)
    yield server, scheme
    server.stop()
    cleanup_test_directory(test_dir)


def test_the_predicted_card_is_preselected(fixed_server):
    value, server_set = _selected(fixed_server, "pair_reader")
    assert value == "A"
    # Without the flag, the page treats the value as browser cache.
    assert server_set == "true"


def test_a_swapped_layout_preselects_the_card_where_the_answer_is(shuffled_server):
    server, scheme = shuffled_server
    swapped = next(u for u in ("u%d" % n for n in range(50))
                   if item_order(scheme, ITEM, u, "p1") == [1, 0])
    kept = next(u for u in ("u%d" % n for n in range(50))
                if item_order(scheme, ITEM, u, "p1") == [0, 1])
    # The first candidate is shown second to this annotator, as card "B".
    assert _selected(server, swapped)[0] == "B"
    assert _selected(server, kept)[0] == "A"

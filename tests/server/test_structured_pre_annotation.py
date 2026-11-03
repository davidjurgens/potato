"""
A trained model's ranking, soft label, scale preference, gloss and
conversation-tree answer must pre-fill the page.

These types had no pre-annotation branch: the page logged "not yet
supported" and showed a blank item. Each stores its answer in hidden inputs
or sliders, which the page's DOM walk fills and marks server-set for the
widget's restore code to read.
"""

import json
import os

import pytest
import requests
import yaml
from bs4 import BeautifulSoup

from potato.server_utils.presentation_order import item_order
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

GLOSS = {"words": [{"word": "kitabım", "morphemes": "kitab-ım",
                    "gloss": "book-1SG.POSS"}], "translation": "my book"}
TREE = {"id": "root", "speaker": "A", "text": "Hi",
        "children": [{"id": "r1", "speaker": "B", "text": "Hello", "children": []},
                     {"id": "r2", "speaker": "B", "text": "Hey", "children": []}]}
ITEM = {"id": "x1", "text": "kitabım", "responses": ["Short answer.", "Long answer."],
        "tree": TREE,
        "predictions": {
            "rank": {"order": ["Speed", "Cost", "Quality"], "rewards": {}},
            "soft": {"pos": 0.6667, "neg": 0.3333},
            "pref": {"value": -2, "rewards": [1.0, -1.0]},
            "igt": GLOSS,
            "conv": {"path": ["root", "r2"], "nodes": {"r1": {"conv_node": "4"}}}}}
SCHEMES = [
    {"annotation_type": "ranking", "name": "rank", "description": "Order these",
     "labels": ["Cost", "Speed", "Quality"]},
    {"annotation_type": "soft_label", "name": "soft", "description": "How sure?",
     "labels": ["pos", "neg"], "total": 100},
    {"annotation_type": "pairwise", "name": "pref", "description": "Which?",
     "mode": "scale", "items_key": "responses", "randomize_order": True,
     "scale": {"min": -3, "max": 3}},
    {"annotation_type": "interlinear_gloss", "name": "igt", "description": "Gloss",
     "source_field": "text"},
    {"annotation_type": "tree_annotation", "name": "conv", "description": "Tree",
     "node_scheme": {"annotation_type": "likert", "name": "conv_node",
                     "description": "Quality", "size": 5},
     "path_selection": {"enabled": True}},
]


@pytest.fixture(scope="module")
def server():
    name = "structured_prelabel"
    test_dir = create_test_directory(name)
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        f.write(json.dumps(ITEM) + "\n")
    config = {
        "port": 8000, "server_name": "test", "annotation_task_name": name,
        "task_dir": test_dir, "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "instance_display": {"fields": [
            {"key": "tree", "type": "conversation_tree"}]},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default",
        "pre_annotation": {"enabled": True, "field": "predictions",
                           "allow_modification": True},
        "annotation_schemes": SCHEMES,
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=config_path)
    if not srv.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start server")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def _page(server, username):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": username, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth",
                 data={"email": username, "pass": "pw", "action": "login"})
    return BeautifulSoup(session.get(f"{server.base_url}/annotate").text,
                         "html.parser")


def _input(soup, name):
    field = soup.find("input", {"name": name})
    assert field is not None, "no input named %s on the page" % name
    return field


def test_a_ranking_prediction_fills_the_order(server):
    field = _input(_page(server, "rank_reader"), "rank:::rank_order")
    assert field.get("value") == "Speed,Cost,Quality"
    assert field.get("data-server-set") == "true"


def test_a_soft_label_prediction_fills_the_sliders_with_whole_numbers(server):
    soup = _page(server, "soft_reader")
    values = {label: _input(soup, "soft:::%s" % label).get("value")
              for label in ("pos", "neg")}
    assert values == {"pos": "67", "neg": "33"}


def test_a_gloss_and_a_tree_prediction_fill_their_hidden_inputs(server):
    soup = _page(server, "gloss_reader")
    assert json.loads(_input(soup, "igt:::igt").get("value"))["words"][0]["gloss"] \
        == "book-1SG.POSS"
    assert json.loads(_input(soup, "conv:::selected_path").get("value")) == ["root", "r2"]
    assert json.loads(_input(soup, "conv:::node_annotations").get("value")) == {
        "r1": {"conv_node": "4"}}


def test_a_scale_prediction_is_mirrored_for_a_swapped_layout(server):
    scheme = SCHEMES[2]
    swapped = next(u for u in ("s%d" % n for n in range(60))
                   if item_order(scheme, ITEM, u, "x1") == [1, 0])
    kept = next(u for u in ("s%d" % n for n in range(60))
                if item_order(scheme, ITEM, u, "x1") == [0, 1])
    def slider(username):
        field = _page(server, username).find(
            "input", {"class": "pairwise-scale-slider", "schema": "pref"})
        assert field is not None, "no scale slider on the page"
        return field.get("value"), field.get("data-server-set")

    # -2 prefers the first candidate; shown second, that is +2.
    assert slider(kept) == ("-2", "true")
    assert slider(swapped)[0] == "2"

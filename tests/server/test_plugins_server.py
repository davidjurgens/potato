"""
A server booted with a plugin: its types render, its assets are served and
linked from every page built on the base template, and answers to a plugin
scheme save and read back like any other.

The plugin is the test-only package in tests/data/plugins/installed, installed by
putting that folder on sys.path (FlaskTestServer runs in this process).
"""

import os
import sys

import pytest
import requests

from potato import plugins
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)

SITE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "plugins", "installed"))
STARS = {"annotation_type": "test_stars", "name": "quality", "description": "How good?",
         "max_stars": 4}


@pytest.fixture(scope="module")
def server():
    sys.path.insert(0, SITE)
    test_dir = create_test_directory("plugins_server")
    data_file = create_test_data_file(test_dir, [{"id": "a", "text": "first item"},
                                                 {"id": "b", "text": "second item"}])
    port = find_free_port(preferred_port=9917)
    config_file = create_test_config(
        test_dir, [STARS], data_files=[data_file], port=port,
        additional_config={
            "plugins": ["testplugin"],
            "instance_display": {"fields": [{"key": "text", "type": "test_shout"}]},
        })
    flask = FlaskTestServer(port=port, debug=False, config_file=config_file)
    if not flask.start():
        pytest.fail("Failed to start server")
    yield flask
    flask.stop()
    plugins.unload("testplugin")
    sys.path.remove(SITE)
    cleanup_test_directory(test_dir)


def login(server, name):
    session = requests.Session()
    session.post(f"{server.base_url}/register", data={"email": name, "pass": "pw"})
    session.post(f"{server.base_url}/auth", data={"email": name, "pass": "pw"})
    return session


def test_the_page_renders_plugin_types_and_links_their_assets(server):
    page = login(server, "reader").get(f"{server.base_url}/annotate").text
    assert 'data-annotation-type="test_stars"' in page
    assert '<div class="test-shout">FIRST ITEM</div>' in page
    assert '<script src="/plugin-static/testplugin/test.js?v=1.0"></script>' in page
    assert 'href="/plugin-static/testplugin/test.css?v=1.0"' in page


def test_assets_are_served_and_only_from_the_plugins_folder(server):
    base = f"{server.base_url}/plugin-static"
    script = requests.get(f"{base}/testplugin/test.js")
    assert script.status_code == 200 and "potatoTestPluginLoaded" in script.text
    assert requests.get(f"{base}/testplugin/../__init__.py").status_code == 404
    assert requests.get(f"{base}/testplugin/%2e%2e/__init__.py").status_code == 404
    assert requests.get(f"{base}/notloaded/test.js").status_code == 404


def test_an_answer_saves_and_reads_back(server):
    session = login(server, "annotator")
    session.get(f"{server.base_url}/annotate")
    response = session.post(f"{server.base_url}/updateinstance", json={
        "instance_id": "a", "annotations": {"quality:::stars": "3"},
        "cleared_schemas": [], "span_annotations": []})
    assert response.status_code == 200, response.text
    stored = session.get(f"{server.base_url}/get_annotations", params={"instance_id": "a"}).json()
    assert stored["label_values"]["quality"] == {"stars": "3"}

"""Read the navbar counter over HTTP for two disjoint batch groups."""

import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager as ConfigManager


@pytest.fixture(scope="module")
def batch_server():
    schemes = [{"name": "choice", "annotation_type": "radio",
                "description": "Choose", "labels": ["yes", "no"]}]
    with ConfigManager("batch_progress_scope", schemes, num_instances=5,
                       assignment_strategy="batch", max_annotations_per_user=-1,
                       max_annotations_per_item=-1, additional_config={
                           "batch_assignment": {"groups": [
                               {"annotators": ["alice"], "instances": ["1", "2"]},
                               {"annotators": ["bob"], "instances": ["3", "4"]},
                           ]},
                       }) as cfg:
        server = FlaskTestServer(config_file=cfg.config_path)
        assert server.start()
        try:
            yield server
        finally:
            server.stop()


@pytest.mark.timeout(60)
@pytest.mark.parametrize("username, item_id", [("alice", "1"), ("bob", "3")])
def test_navbar_counts_only_the_participants_batch(batch_server, username, item_id):
    with requests.Session() as session:
        credentials = {"email": username, "pass": "test-password"}
        session.post(batch_server.base_url + "/register", data=credentials, timeout=10)
        session.post(batch_server.base_url + "/auth", data=credentials, timeout=10)
        page = session.get(batch_server.base_url + "/annotate", timeout=10)
        assert page.status_code == 200
        assert re.search(r'id="progress-counter"[^>]*>\s*0/2\s*<', page.text)
        response = session.post(batch_server.base_url + "/updateinstance", json={
            "instance_id": item_id, "annotations": {"choice:::yes": "yes"},
        }, timeout=30)
        assert response.status_code == 200, response.text
        page = session.get(batch_server.base_url + "/annotate", timeout=10)
        assert re.search(r'id="progress-counter"[^>]*>\s*1/2\s*<', page.text)

"""
Server-level regression for F-040: display-based bounding boxes persist.

document_display.py / pdf_display.py now render a hidden
input.annotation-data-input for the bbox field, so the save pipeline collects
the boxes as "{field}:::_data", the server stores them, and
render_page_with_annotations repopulates the input (value + data-server-set) on
restore. This test exercises that round-trip without a canvas (which is hard to
drive headless): the client widgets write the same input the save path reads.
"""

import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory, create_test_config, create_test_data_file,
)

PORT = 9711


def _bbox_config(test_dir, field_type):
    """Config with a document/pdf bbox display field + a radio scheme."""
    data_file = create_test_data_file(test_dir, [
        {"id": "a1", "doc": "Region one text", "task": "label it"},
        {"id": "a2", "doc": "Region two text", "task": "label it"},
    ])
    return create_test_config(
        test_dir,
        [{"annotation_type": "radio", "name": "region_type",
          "description": "type", "labels": ["TITLE", "BODY"]}],
        data_files=[data_file],
        additional_config={
            "item_properties": {"id_key": "id", "text_key": "task"},
            "instance_display": {
                "fields": [{
                    "key": "doc", "type": field_type, "label": "Doc",
                    "display_options": {"annotation_mode": "bounding_box"},
                }]
            },
        },
    )


class TestDocumentBboxServerPersistence:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("doc_bbox_persist")
        cfg = _bbox_config(test_dir, "document")
        server = FlaskTestServer(port=PORT, config_file=cfg)
        if not server.start():
            pytest.fail("Failed to start server")
        yield server
        server.stop()

    def _session(self, server, name):
        s = requests.Session()
        s.post(f"{server.base_url}/register",
               data={"email": name, "pass": "x", "action": "signup"})
        s.post(f"{server.base_url}/auth",
               data={"email": name, "pass": "x", "action": "login"})
        return s

    def test_bbox_input_rendered_and_round_trips(self, flask_server):
        s = self._session(flask_server, "doc_bbox_u")
        html = s.get(f"{flask_server.base_url}/annotate").text

        # The persistence channel must exist server-side.
        m = re.search(r'<input[^>]*annotation-data-input[^>]*>', html)
        assert m, "bbox display must render a hidden annotation-data-input"
        assert 'name="doc"' in m.group(0), m.group(0)

        iid = s.get(f"{flask_server.base_url}/api/current_instance").json()["instance_id"]
        boxes = '[{"id":"b1","bbox":[0.1,0.2,0.3,0.2],"label":"TITLE"}]'
        r = s.post(f"{flask_server.base_url}/updateinstance",
                   json={"instance_id": iid, "annotations": {"doc:::_data": boxes}})
        assert r.status_code == 200, r.text

        # Stored under the field name.
        ga = s.get(f"{flask_server.base_url}/get_annotations?instance_id={iid}").json()
        assert "doc" in ga.get("label_annotations", {}), ga

        # Restored into the input on the next render (value + data-server-set).
        html2 = s.get(f"{flask_server.base_url}/annotate").text
        m2 = re.search(r'<input[^>]*annotation-data-input[^>]*>', html2)
        assert m2 and "0.3" in m2.group(0) and "TITLE" in m2.group(0), \
            f"box must be restored into the input, got {m2 and m2.group(0)}"
        assert "data-server-set" in m2.group(0)


class TestPdfBboxServerPersistence(TestDocumentBboxServerPersistence):
    """Same round-trip for the PDF bbox display (shares the channel)."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("pdf_bbox_persist")
        cfg = _bbox_config(test_dir, "pdf")
        server = FlaskTestServer(port=PORT + 1, config_file=cfg)
        if not server.start():
            pytest.fail("Failed to start server")
        yield server
        server.stop()

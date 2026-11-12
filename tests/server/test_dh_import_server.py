"""Imported IIIF and PAGE XML projects boot and render: the canvas image and
its pre-annotations, the cropped text line and its HTR text; and a line
corrected through /updateinstance comes out in the exported PAGE XML."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import requests
from bs4 import BeautifulSoup

from potato.importers.projects.iiif import IIIFImporter
from potato.importers.projects.page_xml import PageXMLImporter
from potato.importers.projects.writer import write_project
from tests.helpers import dh_fixtures as fx
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory


def _login(base, user):
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": user, "pass": "p"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": user, "pass": "p"}, timeout=5)
    return s


def _serve(request, project):
    # An absolute output directory: a relative one resolves against the
    # process's working directory, which in-process test servers share.
    import yaml
    config_path = project / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["output_annotation_dir"] = str(project / "annotation_output")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    server = FlaskTestServer(config=str(project / "config.yaml"))
    if not server.start():
        pytest.fail(f"could not start {project}")
    request.addfinalizer(server.stop)
    return server


class TestIIIFProject:
    @pytest.fixture(scope="class")
    def server(self, request):
        d = Path(create_test_directory("dh_iiif_server"))
        manifest = fx.make_iiif(d / "src")
        write_project(IIIFImporter().parse_path(manifest), str(d / "project"), source=str(manifest))
        request.addfinalizer(lambda: cleanup_test_directory(str(d)))
        return _serve(request, d / "project")

    def test_canvas_opens_with_its_regions_and_image(self, server):
        s = _login(server.base_url, "iiif_user")
        page = s.get(f"{server.base_url}/annotate", timeout=5).text
        soup = BeautifulSoup(page, "html.parser")
        field = soup.find("input", id="input-regions")
        assert field is not None and field.get("data-server-set") == "true"
        objects = json.loads(field["value"])
        assert [o["label"] for o in objects] == ["initial", "text block"]
        assert "Folio 1r" in page and "Shelfmark: MS Synthetic 1" in page
        image = s.get(f"{server.base_url}/media/f1r.png", timeout=5)
        assert image.status_code == 200 and image.content[:4] == b"\x89PNG"


class TestPageXMLProject:
    @pytest.fixture(scope="class")
    def project(self, request):
        d = Path(create_test_directory("dh_page_xml_server"))
        fx.make_page_xml(d / "src", transkribus_layout=True)
        result = PageXMLImporter().parse_path(d / "src")
        write_project(result, str(d / "project"), source=str(d / "src"))
        request.addfinalizer(lambda: cleanup_test_directory(str(d)))
        return d / "project", result

    @pytest.fixture(scope="class")
    def server(self, request, project):
        return _serve(request, project[0])

    def test_line_is_cropped_and_its_text_offered_for_correction(self, server):
        s = _login(server.base_url, "htr_user")
        page = s.get(f"{server.base_url}/annotate", timeout=5).text
        soup = BeautifulSoup(page, "html.parser")
        region = soup.find("div", class_="image-region")
        assert region is not None and region["data-region"] == "120,60,640,56"
        assert region.find("img")["src"] == "/media/letter.png"
        assert soup.find("form", attrs={"data-annotation-type": "text_edit"})["data-source-field"] == "htr_text"
        data = s.get(f"{server.base_url}/api/instance_data", timeout=5).json()
        assert data["htr_text"] == "Letter to the harbour rnaster"
        assert s.get(f"{server.base_url}/media/letter.png", timeout=5).status_code == 200

    def test_saved_correction_reaches_the_page_xml_export(self, server, project):
        project_dir, result = project
        s = _login(server.base_url, "htr_saver")
        s.get(f"{server.base_url}/annotate", timeout=5)
        iid = result.items[0].instance_id
        blob = json.dumps({"edited_text": "Letter to the harbour master",
                           "original_text": "Letter to the harbour rnaster",
                           "edit_distance_chars": 2, "edit_distance_words": 1})
        r = s.post(f"{server.base_url}/updateinstance", json={
            "instance_id": iid, "annotations": {"transcription:::transcription": blob},
            "span_annotations": []}, timeout=5)
        assert r.status_code == 200, r.text
        stored = s.get(f"{server.base_url}/get_annotations", params={"instance_id": iid}, timeout=5).json()
        assert "harbour master" in json.dumps(stored)

        from potato.export.cli import build_export_context
        from potato.export.page_xml_exporter import PageXMLExporter
        ctx = build_export_context(str(project_dir / "config.yaml"))
        out = project_dir / "export"
        res = PageXMLExporter().export(ctx, str(out), {"annotator": "htr_saver"})
        assert res.success, res.errors
        root = ET.parse(out / "page_xml" / "page" / "letter.xml").getroot()
        ns = {"p": fx.PAGE_NS}
        assert root.find(".//p:TextLine[@id='r1l1']/p:TextEquiv/p:Unicode", ns).text == \
            "Letter to the harbour master"

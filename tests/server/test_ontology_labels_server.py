"""
Ontology-backed labels through a running server: the search and terms routes
(file mode, and OLS4 with the HTTP call mocked), and the restore of a stored
term into the annotation page after a reload.
"""

import json
import os
import shutil
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "classification", "ontology-labels")
VERSION = "scl/releases/2026-10-01"


def _copy_example(name, mutate=None):
    work = os.path.join(create_test_directory(name), "onto")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache"))
    path = os.path.join(work, "config.yaml")
    if mutate:
        with open(path) as fh:
            cfg = yaml.safe_load(fh)
        mutate(cfg)
        with open(path, "w") as fh:
            yaml.safe_dump(cfg, fh)
    return path


@pytest.fixture(scope="module")
def server():
    def add_ols(cfg):
        cfg["annotation_schemes"].append({
            "annotation_type": "radio", "name": "remote_type", "description": "Remote",
            "labels": ["unclear"],
            "label_source": {"ontology": "cl", "service": "ols4", "allow_network": True,
                             "base_url": "https://ols.example.org/api", "max_results": 5}})
    srv = FlaskTestServer(config_file=_copy_example("ontology_labels_server", add_ols))
    if not srv.start():
        pytest.fail("could not start the ontology-labels server")
    yield srv
    srv.stop()


def _session(server, user):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"action": "signup", "email": user, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"action": "login", "email": user, "pass": "pw"})
    return s


def test_search_needs_a_session_and_a_configured_scheme(server):
    r = requests.get(f"{server.base_url}/api/ontology/search",
                     params={"schema": "main_cell_type", "q": "cell"})
    assert r.status_code == 401
    s = _session(server, "onto_srv_auth")
    assert s.get(f"{server.base_url}/api/ontology/search",
                 params={"schema": "no_such", "q": "cell"}).status_code == 404


def test_file_search_and_terms(server):
    s = _session(server, "onto_srv_search")
    body = s.get(f"{server.base_url}/api/ontology/search",
                 params={"schema": "immune_cell_mentions", "q": "cytotoxic"}).json()
    assert body["service"] == "file" and body["version"] == VERSION
    assert body["results"][0]["obo_id"] == "SCL:0000006"
    assert body["results"][0]["synonym"] == "cytotoxic T cell"
    short = s.get(f"{server.base_url}/api/ontology/search",
                  params={"schema": "main_cell_type", "q": "c"}).json()
    assert short["results"] == []
    terms = s.get(f"{server.base_url}/api/ontology/terms",
                  params={"schema": "immune_cell_mentions",
                          "ids": "SCL:0000006,SCL:0000015,SCL:404"}).json()["terms"]
    # neuron (SCL:0000015) is outside the span scheme's root.
    assert set(terms) == {"SCL:0000006"}


def test_ols4_search_is_proxied(server):
    s = _session(server, "onto_srv_ols")
    docs = [{"iri": "http://purl.obolibrary.org/obo/CL_0000236", "label": "B cell",
             "obo_id": "CL:0000236", "ontology_name": "cl"}]

    def fake_get(url, params=None, timeout=None, headers=None):
        resp = MagicMock(status_code=200)
        body = ({"response": {"numFound": 40, "docs": docs}} if url.endswith("/search")
                else {"config": {"version": "2026-09-30"}})
        resp.json.return_value = body
        resp.content = json.dumps(body).encode()
        assert url.startswith("https://ols.example.org/api/")
        return resp

    real_get = requests.get

    def route(url, *a, **kw):
        if url.startswith("https://ols.example.org/"):
            return fake_get(url, *a, **kw)
        return real_get(url, *a, **kw)

    with patch("requests.get", side_effect=route) as get:
        body = s.get(f"{server.base_url}/api/ontology/search",
                     params={"schema": "remote_type", "q": "b cell"}).json()
    assert body["service"] == "ols4"
    assert body["results"] == [{"obo_id": "CL:0000236", "label": "B cell",
                                "iri": "http://purl.obolibrary.org/obo/CL_0000236",
                                "ontology_version": "2026-09-30"}]
    assert body["truncated"] is True and body["total"] == 40
    assert any(str(c.args[0]).startswith("https://ols.example.org/") for c in get.call_args_list)

    def down(url, *a, **kw):
        if url.startswith("https://ols.example.org/"):
            raise requests.Timeout()
        return real_get(url, *a, **kw)

    with patch("requests.get", side_effect=down):
        r = s.get(f"{server.base_url}/api/ontology/search",
                  params={"schema": "remote_type", "q": "something new"})
    assert r.status_code == 502 and "within" in r.json()["error"]


def test_stored_term_is_restored_into_the_page(server):
    s = _session(server, "onto_srv_restore")
    page = s.get(f"{server.base_url}/annotate").text
    assert 'data-ontology-picker="true"' in page
    assert "ontology-picker.js" in page
    record = {"obo_id": "SCL:0000005", "label": "CD4-positive T cell",
              "iri": "http://purl.obolibrary.org/obo/SCL_0000005", "ontology_version": VERSION}
    r = s.post(f"{server.base_url}/updateinstance", json={
        "instance_id": "cells_01",
        "annotations": {"main_cell_type:SCL:0000005": json.dumps(record)}})
    assert r.status_code == 200
    page = s.get(f"{server.base_url}/annotate").text
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page, "html.parser")
    inp = soup.find("input", attrs={"schema": "main_cell_type", "label_name": "SCL:0000005"})
    assert inp is not None, "stored term has no input on the page"
    assert inp.has_attr("checked")
    assert json.loads(inp["value"]) == record
    assert soup.find(class_="ontology-required-sentinel")["value"] == "1"

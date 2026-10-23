"""
Item-driven cloze over HTTP: the page renders the item's blanks as inputs,
and the answer field is absent from the page and from both instance APIs.
Saved blanks come back on the re-rendered page.
"""

import pytest
import requests
from bs4 import BeautifulSoup

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

SECRET = "quetzalcoatlus"


@pytest.fixture(scope="module")
def cloze_server(request):
    test_dir = create_test_directory("cloze_server")
    data_file = create_test_data_file(test_dir, [
        {"id": "p1", "text": "Passage one",
         "passage": "A [[]] flew over the [[]].", "answers": [SECRET, "valley"]},
        {"id": "p2", "text": "Passage two",
         "passage": "The [[LEAKKEY]] is cold.", "answers": ["river"]}])
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{"name": "fill", "annotation_type": "cloze",
                             "description": "Fill in", "source_field": "passage",
                             "answer_field": "answers"}],
        data_files=[data_file],
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
    return server


def _login(base, name):
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "pass"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "pass"}, timeout=5)
    return s


def test_blanks_rendered_and_key_absent(cloze_server):
    s = _login(cloze_server.base_url, "cloze_page")
    html = s.get(f"{cloze_server.base_url}/annotate", timeout=5).text
    soup = BeautifulSoup(html, "html.parser")
    blanks = soup.select("p.cloze-passage input.cloze-blank")
    assert [b["name"] for b in blanks] == ["fill:::blank_1", "fill:::blank_2"]
    assert "flew over the" in soup.select_one("p.cloze-passage").get_text()
    assert SECRET not in html


@pytest.mark.parametrize("route", ["/api/current_instance", "/api/instance_data"])
def test_apis_omit_the_answer_field(cloze_server, route):
    s = _login(cloze_server.base_url, f"cloze_api_{route.rsplit('/', 1)[-1]}")
    s.get(f"{cloze_server.base_url}/annotate", timeout=5)
    r = s.get(f"{cloze_server.base_url}{route}", timeout=5)
    assert r.status_code == 200
    assert SECRET not in r.text
    assert "passage" in r.text


def test_saved_blanks_restored(cloze_server):
    base = cloze_server.base_url
    s = _login(base, "cloze_restore")
    s.get(f"{base}/annotate", timeout=5)
    r = s.post(f"{base}/updateinstance", json={
        "instance_id": "p1", "annotations": {"fill:::blank_1": "pterosaur",
                                             "fill:::blank_2": "valley"},
        "span_annotations": []}, timeout=5)
    assert r.status_code == 200
    soup = BeautifulSoup(s.get(f"{base}/annotate", timeout=5).text, "html.parser")
    values = [b.get("value") for b in soup.select("input.cloze-blank")]
    assert values == ["pterosaur", "valley"]


def test_inline_key_in_passage_never_reaches_the_page(cloze_server):
    """Audit 94, C1."""
    base = cloze_server.base_url
    s = _login(base, "cloze_leak")
    s.get(f"{base}/annotate", timeout=5)
    s.post(f"{base}/updateinstance", json={
        "instance_id": "p1", "annotations": {"fill:::blank_1": "a", "fill:::blank_2": "b"},
        "span_annotations": []}, timeout=5)
    s.post(f"{base}/annotate", json={"action": "next_instance", "instance_id": "p1"}, timeout=5)
    html = s.get(f"{base}/annotate", timeout=5).text
    assert "The" in html and "is cold" in html
    assert "LEAKKEY" not in html
    for route in ("/api/current_instance", "/api/instance_data"):
        assert "LEAKKEY" not in s.get(f"{base}{route}", timeout=5).text

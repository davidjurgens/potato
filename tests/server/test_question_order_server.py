"""
randomize_questions on a real survey page: the generated markup is reordered
per participant, stays put on reload, and saved answers are still restored
after the reorder.
"""

import json
import os
import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

QUESTIONS = [f"q{i}" for i in range(1, 7)]


@pytest.fixture(scope="module")
def order_server(request):
    test_dir = create_test_directory("question_order_server")
    data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hello"}])
    survey = os.path.join(test_dir, "survey.json")
    questions = [{"name": n, "annotation_type": "radio", "description": f"Question {n}",
                  "labels": ["agree", "disagree"]} for n in QUESTIONS]
    questions[2]["display_logic"] = {"show_when": [
        {"schema": "q1", "operator": "equals", "value": "agree"}]}
    with open(survey, "w") as f:
        json.dump(questions, f)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{"name": "rating", "annotation_type": "radio",
                             "labels": ["good", "bad"], "description": "Rate."}],
        data_files=[data_file],
        phases={"order": ["survey", "annotation"],
                "survey": {"type": "prestudy", "file": survey,
                           "randomize_questions": {"pin_last": ["q6"]}}},
    )
    server = FlaskTestServer(config=config_file)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
    return server


def _login(base_url, username):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"action": "signup", "email": username, "pass": "pass"}, timeout=5)
    s.post(f"{base_url}/auth", data={"action": "login", "email": username, "pass": "pass"}, timeout=5)
    return s


def _order(html):
    return re.findall(r'<form[^>]*class="annotation-form[^"]*"[^>]*data-schema-name="(q\d)"', html)


def test_orders_vary_and_are_stable(order_server):
    orders = set()
    for i in range(8):
        s = _login(order_server.base_url, f"order_user_{i}")
        first = _order(s.get(f"{order_server.base_url}/", timeout=5).text)
        assert sorted(first) == QUESTIONS
        assert first[-1] == "q6"
        again = _order(s.get(f"{order_server.base_url}/", timeout=5).text)
        assert again == first
        orders.add(tuple(first))
    assert len(orders) > 1


def test_answers_restored_after_reorder(order_server):
    s = _login(order_server.base_url, "order_restore")
    s.get(f"{order_server.base_url}/", timeout=5)
    r = s.post(f"{order_server.base_url}/updateinstance",
               json={"instance_id": "__phase_page__",
                     "annotations": {"q2:::disagree": "disagree", "q5:::agree": "agree"},
                     "span_annotations": []}, timeout=5)
    assert r.status_code == 200
    html = s.get(f"{order_server.base_url}/", timeout=5).text
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for name, label in (("q2", "disagree"), ("q5", "agree")):
        form = soup.find("form", attrs={"data-schema-name": name})
        checked = [i.get("label_name") for i in form.find_all("input", attrs={"type": "radio"})
                   if i.has_attr("checked")]
        assert checked == [label], f"{name} answer not restored: {checked}"

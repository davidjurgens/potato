"""
Adaptive escalation through the real routes.

Every autosave re-scores the item, and a question an annotator had not reached
yet counted as a blank answer: a half-finished save boosted an item both
annotators went on to agree on, and a third annotator was handed it. A blank
counts once the annotator leaves the item.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory)


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("adaptive_escalation_server")
    data_file = create_test_data_file(
        test_dir, [{"id": f"i{n}", "text": f"item {n}"} for n in range(4)])
    config_file = create_test_config(
        test_dir,
        [{"annotation_type": "radio", "name": "q1", "description": "Q1", "labels": ["x", "y"]},
         {"annotation_type": "radio", "name": "q2", "description": "Q2", "labels": ["x", "y"]}],
        data_files=[data_file],
        num_annotators_per_item={"default": 2, "adaptive": {
            "enabled": True, "disagreement_threshold": 0.5, "boost_to": 3}},
        assignment_strategy="fixed_order",
    )
    srv = FlaskTestServer(port=9875, config_file=config_file)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def _login(server, user):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": user, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    s.get(f"{server.base_url}/annotate")
    return s


def _save(server, s, iid, answers):
    r = s.post(f"{server.base_url}/updateinstance", json={
        "instance_id": iid, "span_annotations": [],
        "annotations": {f"{q}:::{v}": v for q, v in answers.items()}})
    assert r.status_code == 200, r.text


def _next(server, s):
    s.post(f"{server.base_url}/annotate", json={"action": "next_instance"})


def _cap(iid):
    from potato.item_state_management import get_item_state_manager
    return get_item_state_manager().find_item(iid).get_metadata("required_annotations")


def test_a_half_finished_save_does_not_escalate(server):
    a, b = _login(server, "a1"), _login(server, "b1")
    _save(server, a, "i0", {"q1": "x", "q2": "x"})
    _next(server, a)
    _save(server, b, "i0", {"q1": "x"})            # autosave before q2
    assert _cap("i0") is None
    _save(server, b, "i0", {"q1": "x", "q2": "x"})
    _next(server, b)
    assert _cap("i0") is None


def _current(server, s):
    return s.get(f"{server.base_url}/api/current_instance").json()["instance_id"]


def test_a_question_left_blank_on_next_escalates(server):
    a, b = _login(server, "a2"), _login(server, "b2")
    iid = _current(server, a)
    assert _current(server, b) == iid
    _save(server, a, iid, {"q1": "x", "q2": "y"})
    _next(server, a)
    _save(server, b, iid, {"q1": "x"})
    assert _cap(iid) is None                        # b is still on it
    _next(server, b)                                # and leaves q2 blank
    assert _cap(iid) == 3


def test_going_back_does_not_count_as_leaving_a_blank(server):
    """Previous from a half-done item is not an answer; it boosted the item."""
    a, b = _login(server, "a3"), _login(server, "b3")
    first = _current(server, a)
    for s in (a, b):
        _save(server, s, first, {"q1": "x", "q2": "x"})
        _next(server, s)
    second = _current(server, a)
    _save(server, a, second, {"q1": "x", "q2": "x"})
    _next(server, a)
    _save(server, b, second, {"q1": "x"})
    b.post(f"{server.base_url}/annotate", json={"action": "prev_instance"})
    assert _cap(second) is None
    b.post(f"{server.base_url}/annotate", json={"action": "next_instance"})
    _save(server, b, second, {"q1": "x", "q2": "x"})
    _next(server, b)
    assert _cap(second) is None


@pytest.fixture(scope="module")
def short_server():
    """Two items, so the second is each annotator's last."""
    test_dir = create_test_directory("adaptive_escalation_last_item")
    data_file = create_test_data_file(
        test_dir, [{"id": f"s{n}", "text": f"item {n}"} for n in range(2)])
    config_file = create_test_config(
        test_dir,
        [{"annotation_type": "radio", "name": "q1", "description": "Q1", "labels": ["x", "y"]},
         {"annotation_type": "radio", "name": "q2", "description": "Q2", "labels": ["x", "y"]}],
        data_files=[data_file],
        num_annotators_per_item={"default": 2, "adaptive": {
            "enabled": True, "disagreement_threshold": 0.5, "boost_to": 3}},
        assignment_strategy="fixed_order",
    )
    srv = FlaskTestServer(port=9876, config_file=config_file)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def test_a_blank_on_the_last_item_escalates(short_server):
    """Next on the last item finishes the phase, and returned before the
    item was checked again, so its blanks never counted."""
    a, b = _login(short_server, "a4"), _login(short_server, "b4")
    for s in (a, b):
        _save(short_server, s, "s0", {"q1": "x", "q2": "x"})
        _next(short_server, s)
    _save(short_server, a, "s1", {"q1": "x", "q2": "x"})
    _next(short_server, a)
    _save(short_server, b, "s1", {"q1": "x"})
    assert _cap("s1") is None
    _next(short_server, b)                            # last item: finishes
    assert _cap("s1") == 3

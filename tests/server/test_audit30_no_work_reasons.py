"""
The no-work page must name the cause that actually returned zero.

It used to state one cause unconditionally -- "every item in this study
already has as many annotators as it needs" -- and by round 30 that page
was the observed symptom of three unrelated causes. On two of them the
sentence is not merely unhelpful, it is false: a study where nothing has
been annotated at all tells the annotator every item is full, and the
advice it gives (raise num_annotators_per_item, add data) cannot help.

Each case is driven through the real register + login + /annotate path,
and asserts on what the annotator reads, because the failure mode here
is a page that is confidently wrong rather than one that errors.
"""

import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory, create_test_data_file, create_test_config,
    cleanup_test_directory)

SCHEMES = [{"name": "verdict", "description": "Verdict?",
            "annotation_type": "radio", "labels": ["yes", "no"]}]

_HEADLINE = re.compile(r'potato-page-title">\s*(.*?)\s*</h1>', re.S)


def _server(tag, items, extra):
    test_dir = create_test_directory("nowork_" + tag)
    data_file = create_test_data_file(test_dir, items)
    config_file = create_test_config(
        test_dir, SCHEMES, data_files=[data_file], require_password=False,
        additional_config=extra)
    server = FlaskTestServer(port=find_free_port(), debug=False,
                             config_file=config_file)
    if not server.start_server():
        cleanup_test_directory(test_dir)
        pytest.fail("server did not start")
    server._wait_for_server_ready(timeout=10)
    return server, test_dir


def _login(server, who):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": who, "pass": "p"})
    s.post(f"{server.base_url}/auth", data={"email": who, "pass": "p"})
    return s


def _annotate_page(session, server):
    body = session.get(f"{server.base_url}/annotate").text
    match = _HEADLINE.search(body)
    return (match.group(1).strip() if match else None), body


class TestNoWorkReasons:
    def test_an_annotator_outside_every_batch_group(self):
        """Adding data or raising the annotator cap cannot give this
        person work; only being put in a group can."""
        server, test_dir = _server(
            "batch",
            [{"id": f"i{i}", "text": f"t{i}"} for i in range(1, 9)],
            {"assignment_strategy": "batch",
             "batch_assignment": {"groups": [
                 {"name": "g1", "annotators": ["alice"],
                  "instances": ["i1", "i2", "i3", "i4"]}]}})
        try:
            headline, body = _annotate_page(_login(server, "bob"), server)
            assert headline == "You are not in an annotator group for this study"
            assert "as many annotators as it needs" not in body
            assert "not in an annotator group" in body
        finally:
            server.stop_server()
            cleanup_test_directory(test_dir)

    def test_static_category_assignment_with_nobody_qualified(self):
        """Every item is unannotated and unsaturated here; the old page
        said they were all full."""
        server, test_dir = _server(
            "category",
            [{"id": f"i{i}", "text": f"t{i}", "topic": "medical"}
             for i in range(1, 5)],
            {"assignment_strategy": "category_based",
             "item_properties": {"id_key": "id", "text_key": "text",
                                 "category_key": "topic"},
             "category_assignment": {"enabled": True,
                                     "fallback": "uncategorized"}})
        try:
            headline, body = _annotate_page(_login(server, "alice"), server)
            assert headline == "You are not qualified for any category yet"
            assert "as many annotators as it needs" not in body
        finally:
            server.stop_server()
            cleanup_test_directory(test_dir)

    def test_an_annotator_whose_quota_is_zero(self):
        """0 is a legal quota and means this account is served nothing.
        The page has to say that rather than blame the corpus."""
        server, test_dir = _server(
            "zeroquota",
            [{"id": f"i{i}", "text": f"t{i}"} for i in range(1, 4)],
            {"per_annotator_quota": {"default": 5, "by_user": {"alice": 0}}})
        try:
            headline, _ = _annotate_page(_login(server, "alice"), server)
            assert headline == "Your account is set to zero items"
            # bob, on the same study, is unaffected
            other, body = _annotate_page(_login(server, "bob"), server)
            assert other != "Your account is set to zero items", body[:400]
        finally:
            server.stop_server()
            cleanup_test_directory(test_dir)

    def test_a_genuinely_used_up_study_still_says_so(self):
        """The saturation answer is the one that is true when nothing
        more specific is, and it must survive the new branches."""
        server, test_dir = _server(
            "saturated",
            [{"id": f"i{i}", "text": f"t{i}"} for i in range(1, 3)],
            {"num_annotators_per_item": 1})
        try:
            alice = _login(server, "alice")
            alice.get(f"{server.base_url}/annotate")
            for iid in ("i1", "i2"):
                alice.post(
                    f"{server.base_url}/updateinstance",
                    json={"instance_id": iid,
                          "annotations": {"verdict:::yes": "true"}})
            headline, body = _annotate_page(_login(server, "bob"), server)
            assert headline == "There is no work left for you", body[:400]
            assert "as many annotators as it needs" in body
        finally:
            server.stop_server()
            cleanup_test_directory(test_dir)


class TestHeldItems:
    """Under assignment_hold_minutes the items are taken, not finished, and
    "every item already has as many annotators as it needs" is false."""

    def test_an_annotator_who_finds_every_item_held_is_told_so(self):
        server, test_dir = _server(
            "held", [{"id": "i1", "text": "t1"}],
            {"num_annotators_per_item": 1, "assignment_hold_minutes": 20,
             "max_annotations_per_user": 10})
        try:
            _annotate_page(_login(server, "alice"), server)
            headline, body = _annotate_page(_login(server, "bob"), server)
            assert headline == "Every item is taken right now", body[:400]
            assert "20 minutes" in body
        finally:
            server.stop_server()
            cleanup_test_directory(test_dir)

    def test_the_active_annotator_waits_instead_of_finishing(self):
        """u1's unreached items moved to u2 and u3. Saving the item on screen
        and pressing Next used to send u1 to done, the one person working,
        with room for nine more; when the other holds lapsed nobody was left."""
        server, test_dir = _server(
            "held_active", [{"id": f"i{n}", "text": f"t{n}"} for n in range(3)],
            {"num_annotators_per_item": 1, "assignment_hold_minutes": 30,
             "max_annotations_per_user": 10, "assignment_strategy": "fixed_order"})
        try:
            from potato.item_state_management import get_item_state_manager
            from potato.user_state_management import get_user_state_manager
            sessions = {u: _login(server, u) for u in ("u1", "u2", "u3")}
            for s in sessions.values():
                s.get(f"{server.base_url}/annotate")
            u1 = sessions["u1"]
            u1.post(f"{server.base_url}/updateinstance", json={
                "instance_id": "i0", "span_annotations": [],
                "annotations": {"verdict:::yes": "yes"}})
            assert get_user_state_manager().get_user_state("u1").has_annotated("i0")
            u1.post(f"{server.base_url}/annotate", json={"action": "next_instance"})
            headline, body = _annotate_page(u1, server)
            assert headline == "Every item is taken right now", body[:400]
            state = get_user_state_manager().get_user_state("u1")
            assert state.get_phase().name == "ANNOTATION"

            # u2 walks away: their hold lapses, and u1's reload picks it up.
            ism = get_item_state_manager()
            ism.assignment_timestamps["i1"]["u2"] -= 31 * 60
            import datetime
            get_user_state_manager().get_user_state("u2").last_activity_time = (
                datetime.datetime.now() - datetime.timedelta(minutes=31))
            headline, body = _annotate_page(u1, server)
            assert headline is None, headline
            assert "i1" in state.get_assigned_instance_ids()
        finally:
            server.stop_server()
            cleanup_test_directory(test_dir)

    def test_the_waiting_annotator_finishes_once_the_last_item_is_saved(self):
        """The held page is a wait, not a trap: when the item someone else
        held is saved, nothing is left and the waiting annotator is done."""
        server, test_dir = _server(
            "held_finish", [{"id": f"i{n}", "text": f"t{n}"} for n in range(2)],
            {"num_annotators_per_item": 1, "assignment_hold_minutes": 30,
             "max_annotations_per_user": 10, "assignment_strategy": "fixed_order"})
        try:
            from potato.user_state_management import get_user_state_manager
            u1, u2 = _login(server, "u1"), _login(server, "u2")
            u1.get(f"{server.base_url}/annotate")
            u2.get(f"{server.base_url}/annotate")
            def save(s, iid):
                s.post(f"{server.base_url}/updateinstance", json={
                    "instance_id": iid, "span_annotations": [],
                    "annotations": {"verdict:::yes": "yes"}})
            states = get_user_state_manager()
            save(u1, "i0")
            u1.post(f"{server.base_url}/annotate", json={"action": "next_instance"})
            assert _annotate_page(u1, server)[0] == "Every item is taken right now"
            save(u2, "i1")
            assert states.get_user_state("u2").has_annotated("i1")
            u2.post(f"{server.base_url}/annotate", json={"action": "next_instance"})
            # Both items are in: u1's next look at the page finishes them.
            u1.get(f"{server.base_url}/annotate")
            assert states.get_user_state("u1").get_phase().name == "DONE"
            assert states.get_user_state("u2").get_phase().name == "DONE"
        finally:
            server.stop_server()
            cleanup_test_directory(test_dir)

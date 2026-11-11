"""Live collaborative sessions over HTTP, with two members at once.

Boots a real server with ``collab.enabled`` and a configured team, and drives
it from two logged-in members the way two browsers would: the session page,
saves through /updateinstance with the collab context, the event poll, the
item history, and revert. Every assertion about the shared answer reads it
back from the server (and once from disk), not from what was sent.
"""

import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ITEMS = [{"id": f"c{i}", "text": f"Barack Obama visited city number {i}."}
         for i in range(1, 6)]
TEAM_ITEMS = ["c1", "c2", "c3"]


@pytest.fixture(scope="module")
def flask_server():
    test_dir = create_test_directory("collab_api")
    create_test_data_file(test_dir, ITEMS)
    schemes = [
        {"annotation_type": "radio", "name": "sentiment", "description": "Tone?",
         "labels": ["positive", "neutral", "negative"]},
        {"annotation_type": "multiselect", "name": "topics", "description": "Topics",
         "labels": ["politics", "travel", "sports"]},
        {"annotation_type": "text", "name": "note", "description": "Note"},
        {"annotation_type": "span", "name": "ner", "description": "Entities",
         "labels": ["PER", "LOC"]},
    ]
    config_path = create_test_config(
        test_dir, schemes,
        additional_config={
            "collab": {
                "enabled": True,
                "teams": [{"id": "red", "members": ["ana", "ben", "obs"],
                           "leader": "ana", "items": TEAM_ITEMS}],
            },
        })
    server = FlaskTestServer(port=9093, config_file=config_path)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    server.test_dir = test_dir
    yield server
    server.stop()


def login(server, name):
    s = requests.Session()
    user = {"email": name, "pass": "pass"}
    s.post(f"{server.base_url}/register", data=user, timeout=5)
    r = s.post(f"{server.base_url}/auth", data=user, timeout=5)
    assert r.status_code in (200, 302)
    s.headers.update({"Origin": server.base_url})
    return s


@pytest.fixture(scope="module")
def ana(flask_server):
    return login(flask_server, "ana")


@pytest.fixture(scope="module")
def ben(flask_server):
    return login(flask_server, "ben")


SID = "RED"


def api(server, s, method, path, **kw):
    return s.request(method, f"{server.base_url}/collab/api/{SID}{path}", timeout=10, **kw)


def item(server, s, iid):
    r = api(server, s, "GET", f"/item/{iid}")
    assert r.status_code == 200, r.text
    return r.json()


def save(server, s, iid, annotations=None, spans=None, base_rev=None, cleared=None):
    body = {"instance_id": iid, "annotations": annotations or {}}
    if spans is not None:
        body["span_annotations"] = spans
    if cleared:
        body["cleared_schemas"] = cleared
    rev = item(server, s, iid)["rev"] if base_rev is None else base_rev
    body["collab"] = {"sid": SID, "base_rev": rev}
    return s.post(f"{server.base_url}/updateinstance", json=body, timeout=10)


def labels(answer, schema):
    prefix = f"L:{schema}:::"
    return {k[len(prefix):]: v for k, v in answer.items() if k.startswith(prefix)}


class TestSessionBasics:
    def test_configured_team_exists_for_its_members(self, flask_server, ana):
        r = api(flask_server, ana, "GET", "/state")
        assert r.status_code == 200, r.text
        state = r.json()
        assert state["team_user"] == "team-red"
        assert state["item_ids"] == TEAM_ITEMS
        assert state["leader"] == "ana"

    def test_outsider_cannot_read_or_write(self, flask_server):
        eve = login(flask_server, "eve")
        assert api(flask_server, eve, "GET", "/state").status_code == 403
        r = eve.post(f"{flask_server.base_url}/updateinstance", timeout=10, json={
            "instance_id": "c1", "annotations": {"sentiment:::positive": "positive"},
            "collab": {"sid": SID, "base_rev": 0}})
        assert r.status_code == 403
        # A configured team takes no walk-ins.
        assert api(flask_server, eve, "POST", "/join", json={}).status_code == 403

    def test_page_renders_the_team_answer_for_the_viewer(self, flask_server, ana, ben):
        assert save(flask_server, ana, "c2",
                    {"sentiment:::negative": "negative"}).status_code == 200
        page = ben.get(f"{flask_server.base_url}/collab/s/{SID}/i/c2", timeout=10)
        assert page.status_code == 200
        html = page.text
        assert 'value="c2"' in html                       # the item asked for
        assert "window.potatoCollab" in html or "potato-collab-config" in html
        # The team's radio is restored on the member's page.
        import re
        checked = re.search(r'<input[^>]*value="negative"[^>]*>', html).group(0)
        assert "checked" in checked


class TestSharedAnswer:
    def test_edits_to_different_schemes_both_survive(self, flask_server, ana, ben):
        save(flask_server, ana, "c1", {"sentiment:::neutral": "neutral"})
        base = item(flask_server, ana, "c1")["rev"]
        assert save(flask_server, ana, "c1", {"sentiment:::positive": "positive"},
                    base_rev=base).status_code == 200
        # Ben's page still reflects `base` and he only typed a note -- but a
        # page saves its whole answer, so his save repeats the stale radio.
        assert save(flask_server, ben, "c1", {"sentiment:::neutral": "neutral",
                                              "note:::text_box": "about travel"},
                    base_rev=base).status_code == 200

        answer = item(flask_server, ana, "c1")["answer"]
        assert labels(answer, "sentiment") == {"positive": "positive"}
        assert labels(answer, "note") == {"text_box": "about travel"}

    def test_same_key_last_writer_wins_and_names_who_was_overwritten(
            self, flask_server, ana, ben):
        base = item(flask_server, ana, "c3")["rev"]
        save(flask_server, ana, "c3", {"sentiment:::neutral": "neutral"}, base_rev=base)
        r = save(flask_server, ben, "c3", {"sentiment:::negative": "negative"},
                 base_rev=base)
        assert r.status_code == 200
        assert [o["user"] for o in r.json()["collab"]["overwrote"]] == ["ana"]
        assert labels(item(flask_server, ana, "c3")["answer"], "sentiment") == {
            "negative": "negative"}

    def test_a_span_deleted_by_one_is_not_restored_by_the_others_stale_page(
            self, flask_server, ana, ben):
        sp = {"schema": "ner", "name": "PER", "title": "PER", "start": 0, "end": 12,
              "id": "per-obama", "value": "true"}
        save(flask_server, ana, "c1", spans=[sp])
        base = item(flask_server, ben, "c1")["rev"]
        assert "S:per-obama" in item(flask_server, ben, "c1")["answer"]
        save(flask_server, ana, "c1", spans=[dict(sp, value=None)])
        # Ben's page still has the span and he saves something else.
        save(flask_server, ben, "c1", {"note:::text_box": "edited"}, spans=[sp],
             base_rev=base)
        answer = item(flask_server, ana, "c1")["answer"]
        assert "S:per-obama" not in answer
        assert labels(answer, "note") == {"text_box": "edited"}

    def test_history_names_each_change_and_its_author(self, flask_server, ana):
        history = item(flask_server, ana, "c1")["history"]
        assert history, "every save that changed the answer is logged"
        assert {h["user"] for h in history} >= {"ana", "ben"}
        assert any("sentiment" in line for h in history for line in h["summary"])
        assert any("span PER" in line for h in history for line in h["summary"])

    def test_revert_puts_back_what_an_edit_changed(self, flask_server, ana):
        before = labels(item(flask_server, ana, "c2")["answer"], "topics")
        r = save(flask_server, ana, "c2", {"topics:::sports": "sports"})
        seq = r.json()["collab"]["seq"]
        assert labels(item(flask_server, ana, "c2")["answer"], "topics") == {
            **before, "sports": "sports"}
        assert api(flask_server, ana, "POST", "/revert", json={"seq": seq}).status_code == 200
        assert labels(item(flask_server, ana, "c2")["answer"], "topics") == before
        assert item(flask_server, ana, "c2")["history"][-1]["reverts"] == seq

    def test_observer_cannot_write(self, flask_server, ana):
        obs = login(flask_server, "obs")
        # Demote obs by leaving and rejoining as an observer is not possible
        # for a config team; check the refusal from a closed-to-edit role via
        # the API instead: an observer joining a lobby session.
        r = obs.post(f"{flask_server.base_url}/collab/api/create", timeout=10,
                     json={"name": "solo", "item_ids": ["c4"]})
        assert r.status_code == 200, r.text
        lobby_sid = r.json()["session"]["session_id"]
        ben2 = login(flask_server, "zed")
        assert ben2.post(f"{flask_server.base_url}/collab/api/{lobby_sid}/join",
                         json={"role": "observer"}, timeout=10).status_code == 200
        r = ben2.post(f"{flask_server.base_url}/updateinstance", timeout=10, json={
            "instance_id": "c4", "annotations": {"sentiment:::positive": "positive"},
            "collab": {"sid": lobby_sid, "base_rev": 0}})
        assert r.status_code == 403


class TestPollingAndNavigation:
    def test_events_carry_edits_after_the_cursor(self, flask_server, ana, ben):
        cursor = api(flask_server, ben, "GET", "/events?since=0").json()["cursor"]
        save(flask_server, ana, "c2", {"note:::text_box": "polled"})
        page = api(flask_server, ben, "GET", f"/events?since={cursor}").json()
        edits = [e for e in page["events"] if e["type"] == "edit"]
        assert edits and edits[-1]["user"] == "ana"
        assert edits[-1]["data"]["instance_id"] == "c2"
        assert page["cursor"] == cursor + len(page["events"])

    def test_navigation_moves_within_the_team_items(self, flask_server, ben):
        r = api(flask_server, ben, "POST", "/navigate",
                json={"action": "go_to", "go_to": "c1"})
        assert r.json()["instance_id"] == "c1"
        r = api(flask_server, ben, "POST", "/navigate", json={"action": "next_instance"})
        assert r.json()["instance_id"] == "c2"
        assert r.headers["X-Potato-Location"].endswith("/collab/s/RED/i/c2")
        # Ben moved by hand, so he no longer follows the leader.
        me = api(flask_server, ben, "GET", "/state").json()["me"]
        assert me["viewing"] == "c2" and me["following"] is False

    def test_follow_returns_to_the_leaders_item(self, flask_server, ana, ben):
        api(flask_server, ana, "POST", "/navigate", json={"action": "go_to", "go_to": "c3"})
        r = api(flask_server, ben, "POST", "/navigate", json={"action": "follow"})
        assert r.json()["instance_id"] == "c3"
        assert api(flask_server, ben, "GET", "/state").json()["me"]["following"] is True


class TestIsolation:
    def test_team_answer_is_not_the_members_own(self, flask_server, ana):
        r = ana.get(f"{flask_server.base_url}/get_annotations?instance_id=c1", timeout=10)
        # Ana has no solo answer for a team item.
        assert not (r.json().get("label_annotations") or {})

    def test_a_save_without_the_session_is_refused_for_a_team_item(self, flask_server, ana):
        r = ana.post(f"{flask_server.base_url}/updateinstance", timeout=10, json={
            "instance_id": "c1", "annotations": {"sentiment:::negative": "negative"}})
        assert r.status_code in (403, 409)

    def test_member_is_not_given_team_items_solo(self, flask_server, ana):
        ana.get(f"{flask_server.base_url}/annotate", timeout=10)
        r = ana.get(f"{flask_server.base_url}/api/current_instance", timeout=10)
        if r.status_code == 200:
            assert r.json().get("instance_id") not in TEAM_ITEMS

    def test_the_log_and_team_state_are_on_disk(self, flask_server):
        out = None
        for root, dirs, files in os.walk(flask_server.test_dir):
            if "session-RED.jsonl" in files:
                out = os.path.join(root, "session-RED.jsonl")
        assert out, "session log written"
        with open(out) as f:
            types = [json.loads(line)["type"] for line in f if line.strip()]
        assert types[0] == "session_created" and "edit" in types


class TestLobby:
    def test_the_lobby_page_renders_for_a_member(self, flask_server, ana):
        r = ana.get(f"{flask_server.base_url}/collab/", timeout=10)
        assert r.status_code == 200
        assert "Live sessions" in r.text

    def test_the_lobby_lists_the_team_to_its_members_only(self, flask_server, ana):
        rows = ana.get(f"{flask_server.base_url}/collab/api/list", timeout=10).json()["sessions"]
        assert any(r["session_id"] == SID and r["is_member"] for r in rows)
        stranger = login(flask_server, "lobby_stranger")
        rows = stranger.get(f"{flask_server.base_url}/collab/api/list", timeout=10).json()["sessions"]
        assert all(r["session_id"] != SID for r in rows)

    def test_the_annotation_page_links_to_the_lobby(self, flask_server, ana):
        page = ana.get(f"{flask_server.base_url}/annotate", timeout=10)
        assert "/collab/" in page.text

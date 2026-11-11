"""Live sessions over HTTP, Phases 4-5: drawings merged shape by shape,
blind-first answers and their reveal, sign-off, quick polls, discussion with
@mentions, metrics, replay and the admin overview.

Two members drive a real server the way two browsers would. Every assertion
about an answer reads it back from the server, not from what was sent.
"""

import json

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ITEMS = [{"id": f"p{i}", "text": f"Item number {i}.", "image": f"https://example.org/{i}.png"}
         for i in range(1, 7)]
ADMIN_KEY = "collab-phase5-admin-key"


@pytest.fixture(scope="module")
def flask_server():
    test_dir = create_test_directory("collab_phase5_api")
    create_test_data_file(test_dir, ITEMS)
    schemes = [
        {"annotation_type": "radio", "name": "stance", "description": "Stance?",
         "labels": ["pro", "con", "neutral"]},
        {"annotation_type": "text", "name": "note", "description": "Note"},
        {"annotation_type": "image_annotation", "name": "objects", "description": "Objects",
         "source_field": "image", "tools": ["bbox"],
         "labels": [{"name": "person", "color": "#f00"}]},
    ]
    config_path = create_test_config(
        test_dir, schemes,
        additional_config={
            "admin_api_key": ADMIN_KEY,
            "collab": {
                "enabled": True,
                "teams": [
                    {"id": "red", "members": ["ana", "ben"], "leader": "ana",
                     "items": ["p1", "p2", "p3"], "require_signoff": True},
                    {"id": "blue", "members": ["cy", "dee"], "leader": "cy",
                     "items": ["p4", "p5"], "blind_first": True},
                ],
            },
        })
    server = FlaskTestServer(port=9094, config_file=config_path)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    yield server
    server.stop()


def login(server, name):
    s = requests.Session()
    user = {"email": name, "pass": "pass"}
    s.post(f"{server.base_url}/register", data=user, timeout=5)
    r = s.post(f"{server.base_url}/auth", data=user, timeout=5)
    assert r.status_code in (200, 302)
    s.headers.update({"Origin": server.base_url})
    s.get(f"{server.base_url}/annotate", timeout=10)   # past the opening pages
    return s


@pytest.fixture(scope="module")
def members(flask_server):
    return {name: login(flask_server, name) for name in ("ana", "ben", "cy", "dee")}


def api(server, s, sid, method, path, **kw):
    return s.request(method, f"{server.base_url}/collab/api/{sid}{path}", timeout=10, **kw)


def item(server, s, sid, iid):
    r = api(server, s, sid, "GET", f"/item/{iid}")
    assert r.status_code == 200, r.text
    return r.json()


def save(server, s, sid, iid, annotations, base_rev=None):
    rev = item(server, s, sid, iid)["rev"] if base_rev is None else base_rev
    return s.post(f"{server.base_url}/updateinstance", timeout=10, json={
        "instance_id": iid, "annotations": annotations,
        "collab": {"sid": sid, "base_rev": rev}})


def box(i):
    return {"id": i, "type": "bbox", "label": "person", "coordinates": {"x": 1, "y": 1}}


class TestDrawingsMergeByShape:
    def test_two_members_boxes_on_one_image_both_survive(self, flask_server, members):
        ana, ben = members["ana"], members["ben"]
        base = item(flask_server, ana, "RED", "p1")["rev"]
        r1 = save(flask_server, ana, "RED", "p1",
                  {"objects:::_data": json.dumps([box("ana-1")])}, base_rev=base)
        assert r1.status_code == 200, r1.text
        # Ben's page still showed the empty image when he drew.
        r2 = save(flask_server, ben, "RED", "p1",
                  {"objects:::_data": json.dumps([box("ben-1")])}, base_rev=base)
        assert r2.status_code == 200, r2.text
        stored = json.loads(item(flask_server, ana, "RED", "p1")["answer"]["L:objects:::_data"])
        assert sorted(b["id"] for b in stored) == ["ana-1", "ben-1"]
        assert r2.json()["collab"]["overwrote"] == []

    def test_undoing_one_shape_leaves_the_others(self, flask_server, members):
        ana = members["ana"]
        r = save(flask_server, ana, "RED", "p1", {"objects:::_data": json.dumps(
            [box("ana-1"), box("ben-1"), box("ana-2")])})
        seq = r.json()["collab"]["seq"]
        save(flask_server, members["ben"], "RED", "p1", {"objects:::_data": json.dumps(
            [box("ana-1"), box("ben-1"), box("ana-2"), box("ben-2")])})
        assert api(flask_server, ana, "RED", "POST", "/revert", json={"seq": seq}).status_code == 200
        stored = json.loads(item(flask_server, ana, "RED", "p1")["answer"]["L:objects:::_data"])
        assert sorted(b["id"] for b in stored) == ["ana-1", "ben-1", "ben-2"]


class TestSignoff:
    def test_ready_marks_clear_when_the_answer_changes(self, flask_server, members):
        ana, ben = members["ana"], members["ben"]
        save(flask_server, ana, "RED", "p2", {"stance:::pro": "pro"})
        for s in (ana, ben):
            assert api(flask_server, s, "RED", "POST", "/signoff",
                       json={"instance_id": "p2", "ready": True}).status_code == 200
        status = item(flask_server, ana, "RED", "p2")["status"]
        assert status["signed_off"] is True and status["ready"] == ["ana", "ben"]
        save(flask_server, ben, "RED", "p2", {"stance:::con": "con"})
        status = item(flask_server, ana, "RED", "p2")["status"]
        assert status["signed_off"] is False and status["ready"] == []


class TestBlindFirst:
    def test_answers_are_private_until_everyone_is_done(self, flask_server, members):
        cy, dee = members["cy"], members["dee"]
        assert item(flask_server, cy, "BLUE", "p4")["blind"] is True
        assert save(flask_server, cy, "BLUE", "p4",
                    {"stance:::pro": "pro", "note:::text_box": "cy thinks"}).status_code == 200
        assert save(flask_server, dee, "BLUE", "p4",
                    {"stance:::pro": "pro", "note:::text_box": "dee thinks"}).status_code == 200
        # Neither the team's answer nor the poll stream shows them yet.
        assert item(flask_server, dee, "BLUE", "p4")["answer"] == {}
        events = api(flask_server, dee, "BLUE", "GET", "/events?since=0").json()["events"]
        assert not [e for e in events if e["type"] == "edit"]
        # Each member's page reads their own answer.
        own = cy.get(f"{flask_server.base_url}/get_annotations?instance_id=p4",
                     headers={"X-Potato-Collab": "BLUE"}, timeout=10).json()
        assert "cy thinks" in json.dumps(own) and "dee thinks" not in json.dumps(own)

        api(flask_server, cy, "BLUE", "POST", "/blind_done", json={"instance_id": "p4"})
        assert item(flask_server, cy, "BLUE", "p4")["blind"] is True
        api(flask_server, dee, "BLUE", "POST", "/blind_done", json={"instance_id": "p4"})
        revealed = item(flask_server, cy, "BLUE", "p4")
        assert revealed["status"]["blind"] is False
        assert revealed["reveal"]["units"]["L:stance"]["agree"] is True
        assert revealed["reveal"]["units"]["L:note"]["answers"] == {
            "cy": "'cy thinks'", "dee": "'dee thinks'"}
        # What they agreed on starts the team's answer; the rest is theirs to settle.
        assert revealed["answer"] == {"L:stance:::pro": "pro"}

    def test_after_the_reveal_saves_go_to_the_team(self, flask_server, members):
        dee = members["dee"]
        assert save(flask_server, dee, "BLUE", "p4",
                    {"stance:::pro": "pro", "note:::text_box": "agreed text"}).status_code == 200
        answer = item(flask_server, dee, "BLUE", "p4")["answer"]
        assert answer["L:note:::text_box"] == "agreed text"
        # And the member's own pre-discussion answer is kept as it was.
        r = dee.get(f"{flask_server.base_url}/get_annotations?instance_id=p4", timeout=10)
        assert "dee thinks" in r.text

    def test_a_page_that_showed_my_own_answer_cannot_save_into_the_team(self, flask_server,
                                                                        members):
        # Found driving two browsers: the page reloaded at the reveal with the
        # member's own drawing restored into its fields, and saved it.
        r = members["cy"].post(f"{flask_server.base_url}/updateinstance", timeout=10, json={
            "instance_id": "p4", "annotations": {"note:::text_box": "cy thinks"},
            "collab": {"sid": "BLUE", "base_rev": 0, "rendered_blind": True}})
        assert r.status_code == 409
        assert item(flask_server, members["cy"], "BLUE", "p4")["answer"].get(
            "L:note:::text_box") == "agreed text"

    def test_session_pages_ask_the_browser_not_to_restore_fields(self, flask_server, members):
        html = members["cy"].get(f"{flask_server.base_url}/collab/s/BLUE/i/p5", timeout=10).text
        import re
        tags = re.findall(r'<input[^>]*class="annotation-data-input"[^>]*>', html)
        assert tags and all('autocomplete="off"' in t for t in tags)

    def test_a_solo_save_of_a_blind_team_item_is_refused(self, flask_server, members):
        r = members["cy"].post(f"{flask_server.base_url}/updateinstance", timeout=10, json={
            "instance_id": "p5", "annotations": {"stance:::con": "con"}})
        assert r.status_code == 409


class TestPollsAndDiscussion:
    def test_a_poll_closes_on_the_last_vote_and_applies_its_winner(self, flask_server, members):
        ana, ben = members["ana"], members["ben"]
        r = api(flask_server, ana, "RED", "POST", "/poll",
                json={"instance_id": "p3", "schema": "stance"})
        assert r.status_code == 200, r.text
        pid = r.json()["poll_id"]
        api(flask_server, ana, "RED", "POST", f"/poll/{pid}/vote", json={"option": "neutral"})
        # Ben sees that ana voted, not what.
        votes = [e for e in api(flask_server, ben, "RED", "GET", "/events?since=0").json()["events"]
                 if e["type"] == "poll_vote"]
        assert votes and "option" not in votes[-1]["data"]
        api(flask_server, ben, "RED", "POST", f"/poll/{pid}/vote", json={"option": "neutral"})
        r = api(flask_server, ana, "RED", "POST", f"/poll/{pid}/close", json={"apply": True})
        assert r.json()["poll"]["winner"] == "neutral"
        assert item(flask_server, ben, "RED", "p3")["answer"] == {"L:stance:::neutral": "neutral"}

    def test_a_discussion_post_mentions_a_teammate(self, flask_server, members):
        ana, ben = members["ana"], members["ben"]
        r = api(flask_server, ana, "RED", "POST", "/discuss",
                json={"instance_id": "p3", "body": "@ben is this neutral?"})
        assert r.status_code == 200, r.text
        events = api(flask_server, ben, "RED", "GET", "/events?since=0").json()["events"]
        talk = [e for e in events if e["type"] == "discussion"]
        assert talk[-1]["data"]["mentions"] == ["ben"]
        memos = ben.get(f"{flask_server.base_url}/api/memos?instance_id=p3", timeout=10).json()
        assert any(m["body"] == "@ben is this neutral?" and m.get("team_id") == "team-red"
                   for m in memos["memos"])


class TestWatching:
    def test_members_get_metrics_and_replay(self, flask_server, members):
        ana = members["ana"]
        metrics = api(flask_server, ana, "RED", "GET", "/metrics").json()
        assert metrics["members"]["ana"]["edits"] >= 1
        frames = api(flask_server, ana, "RED", "GET", "/replay?instance_id=p2").json()["frames"]
        assert [f["answer"] for f in frames if f["type"] == "edit"][-1] == ["stance: con"]

    def test_outsiders_get_neither(self, flask_server, members):
        assert api(flask_server, members["cy"], "RED", "GET", "/metrics").status_code == 403
        assert api(flask_server, members["cy"], "RED", "GET", "/replay").status_code == 403

    def test_the_admin_overview_and_watching(self, flask_server, members):
        cy = members["cy"]
        r = cy.get(f"{flask_server.base_url}/collab/api/admin/overview", timeout=10)
        assert r.status_code == 403
        boss = login(flask_server, "boss")
        boss.headers.update({"X-API-Key": ADMIN_KEY})
        rows = boss.get(f"{flask_server.base_url}/collab/api/admin/overview", timeout=10).json()
        assert {s["session_id"] for s in rows["sessions"]} >= {"RED", "BLUE"}
        boss.get(f"{flask_server.base_url}/collab/s/RED/observe", timeout=10)
        me = api(flask_server, boss, "RED", "GET", "/state").json()["me"]
        assert me["role"] == "observer"
        # Watching is not editing.
        r = save(flask_server, boss, "RED", "p3", {"stance:::pro": "pro"})
        assert r.status_code == 403

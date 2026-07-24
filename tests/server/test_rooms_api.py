"""Integration tests for Multiplayer Rooms (/rooms/*).

Boots a real server with ``rooms.enabled`` and drives a full norming session
over HTTP from three authenticated users: create → join → blind vote (with a
redaction check against the events API!) → reveal → post-reveal vote change →
advance → close. Also checks persistence of final votes into real annotation
state, the JSONL event log on disk, and access control.
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

ADMIN_KEY = "rooms_test_admin_key"

TEST_ITEMS = [
    {"id": f"r{i}", "text": f"Room test message number {i}."}
    for i in range(1, 7)
]


class TestRoomsAPI:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("rooms_api")
        create_test_data_file(test_dir, TEST_ITEMS)
        annotation_schemes = [{
            "annotation_type": "radio",
            "name": "sarcasm",
            "description": "Sarcastic or sincere?",
            "labels": ["Sarcastic", "Sincere"],
        }]
        config_path = create_test_config(
            test_dir,
            annotation_schemes,
            admin_api_key=ADMIN_KEY,
            additional_config={
                "rooms": {
                    "enabled": True,
                    "persist_votes": True,
                    "max_members": 5,
                },
            },
        )
        server = FlaskTestServer(port=9081, config_file=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        server.test_dir = test_dir
        yield server
        server.stop()

    def _login(self, flask_server, name):
        session = requests.Session()
        user = {"email": name, "pass": "pass"}
        session.post(f"{flask_server.base_url}/register", data=user, timeout=5)
        response = session.post(f"{flask_server.base_url}/auth", data=user, timeout=5)
        assert response.status_code in (200, 302)
        session.headers.update({"Origin": flask_server.base_url})
        return session

    def _post(self, session, flask_server, path, payload=None):
        return session.post(f"{flask_server.base_url}{path}",
                            json=payload or {}, timeout=5)

    def _get(self, session, flask_server, path):
        return session.get(f"{flask_server.base_url}{path}", timeout=5)

    # ------------------------------------------------------------------

    def test_01_full_norming_session(self, flask_server):
        host = self._login(flask_server, "host_hana")
        bob = self._login(flask_server, "member_bob")
        cara = self._login(flask_server, "member_cara")

        # Create a room over two known items
        response = self._post(host, flask_server, "/rooms/api/create", {
            "room_type": "norming", "item_ids": ["r1", "r2"]})
        assert response.status_code == 200, response.text
        room_id = response.json()["room_id"]
        base = f"/rooms/api/{room_id}"

        # Members join; lobby lists the room
        for member in (bob, cara):
            assert self._post(member, flask_server, f"{base}/join").json()["success"]
        rooms = self._get(host, flask_server, "/rooms/api/list").json()["rooms"]
        assert any(r["room_id"] == room_id and r["n_members"] == 3
                   for r in rooms)

        # State shows the first item with its text; nobody has voted
        state = self._get(bob, flask_server, f"{base}/state").json()
        assert state["phase"] == "voting"
        assert state["current_instance_id"] == "r1"
        assert "Room test message number 1." in state["item_text"]
        assert state["current_item"]["n_voted"] == 0

        # Blind votes
        assert self._post(host, flask_server, f"{base}/vote",
                          {"label": "Sarcastic"}).json()["success"]
        assert self._post(bob, flask_server, f"{base}/vote",
                          {"label": "Sarcastic"}).json()["success"]
        assert self._post(cara, flask_server, f"{base}/vote",
                          {"label": "Sincere"}).json()["success"]

        # THE BLIND INVARIANT: before reveal, another member's events and
        # state must show who voted but never what.
        events = self._get(bob, flask_server, f"{base}/events?since=0").json()
        vote_events = [e for e in events["events"] if e["type"] == "vote_cast"]
        assert len(vote_events) == 3
        assert all("label" not in e["data"] for e in vote_events)
        state = self._get(bob, flask_server, f"{base}/state").json()
        assert state["current_item"]["n_voted"] == 3
        assert state["all_voted"] is True
        assert "initial_votes" not in state["current_item"]
        assert state["current_item"]["my_vote"] == "Sarcastic"  # own vote OK
        assert "Sincere" not in json.dumps(
            self._get(bob, flask_server, f"{base}/state").json()["current_item"])

        # Only the host can reveal
        assert self._post(bob, flask_server, f"{base}/reveal").status_code == 400
        assert self._post(host, flask_server, f"{base}/reveal").json()["success"]

        # Post-reveal: everyone's votes are public
        state = self._get(cara, flask_server, f"{base}/state").json()
        assert state["phase"] == "revealed"
        assert state["current_item"]["initial_votes"] == {
            "host_hana": "Sarcastic", "member_bob": "Sarcastic",
            "member_cara": "Sincere"}

        # Discussion + conformity: cara converges to the majority
        assert self._post(cara, flask_server, f"{base}/message",
                          {"text": "ok, reading it again it IS sarcastic"}
                          ).json()["success"]
        assert self._post(cara, flask_server, f"{base}/vote",
                          {"label": "Sarcastic"}).json()["success"]
        state = self._get(host, flask_server, f"{base}/state").json()
        item = state["current_item"]
        assert item["current_votes"]["member_cara"] == "Sarcastic"
        assert item["initial_votes"]["member_cara"] == "Sincere"  # immutable
        assert len(item["changes"]) == 1
        assert item["changes"][0]["majority_at_time"] == "Sarcastic"

        # Advance to item 2, vote unanimously, reveal, and close
        assert self._post(host, flask_server, f"{base}/advance").json()["success"]
        for member in (host, bob, cara):
            assert self._post(member, flask_server, f"{base}/vote",
                              {"label": "Sincere"}).json()["success"]
        assert self._post(host, flask_server, f"{base}/reveal").json()["success"]
        response = self._post(host, flask_server, f"{base}/advance")
        assert response.json()["success"]

        state = self._get(host, flask_server, f"{base}/state").json()
        assert state["status"] == "closed"

        # Metrics: 2 revealed items, one conformity change toward majority
        metrics = state["metrics"]
        assert metrics["n_revealed"] == 2
        assert metrics["total_changes"] == 1
        assert metrics["toward_majority"] == 1
        assert metrics["final_alpha"] is not None
        assert metrics["final_alpha"] == pytest.approx(1.0)  # unanimous finals
        if metrics["blind_alpha"] is not None:
            assert metrics["blind_alpha"] < metrics["final_alpha"]

        flask_server._rooms_test_room_id = room_id

    def test_02_final_votes_persisted_into_annotations(self, flask_server):
        """persist_votes: final room votes count as real annotations."""
        cara = self._login(flask_server, "member_cara")
        response = self._get(cara, flask_server, "/get_annotations?instance_id=r1")
        assert response.status_code == 200
        payload = response.json()
        text = json.dumps(payload)
        assert "Sarcastic" in text, (
            f"cara's final vote for r1 missing from annotations: {payload}")

    def test_03_jsonl_event_log_on_disk(self, flask_server):
        room_id = flask_server._rooms_test_room_id
        rooms_dir = None
        for root, dirs, files in os.walk(flask_server.test_dir):
            if f"room-{room_id}.jsonl" in files:
                rooms_dir = root
                break
        assert rooms_dir, "room JSONL log not found on disk"
        with open(os.path.join(rooms_dir, f"room-{room_id}.jsonl")) as f:
            events = [json.loads(line) for line in f]
        types = [e["type"] for e in events]
        assert types[0] == "room_created"
        assert "revealed" in types
        assert "vote_changed" in types
        assert types[-1] == "room_closed"
        # Full labels ARE in the persisted log (replay needs them)
        blind = [e for e in events if e["type"] == "vote_cast"]
        assert all("label" in e["data"] for e in blind)

    def test_04_access_control(self, flask_server):
        host = self._login(flask_server, "acl_host")
        response = self._post(host, flask_server, "/rooms/api/create",
                              {"item_ids": ["r3"]})
        room_id = response.json()["room_id"]
        base = f"/rooms/api/{room_id}"

        # Unauthenticated → 401
        anon = requests.Session()
        assert anon.get(f"{flask_server.base_url}{base}/state",
                        timeout=5).status_code == 401
        # Authenticated non-member → 403 on state/events
        stranger = self._login(flask_server, "acl_stranger")
        assert self._get(stranger, flask_server, f"{base}/state").status_code == 403
        assert self._get(stranger, flask_server, f"{base}/events").status_code == 403
        # Non-member vote → 400 (not a member)
        assert self._post(stranger, flask_server, f"{base}/vote",
                          {"label": "Sincere"}).status_code == 400
        # Cross-origin POST → 403
        evil = self._login(flask_server, "acl_evil")
        evil.headers.update({"Origin": "https://evil.example"})
        assert self._post(evil, flask_server, f"{base}/join").status_code == 403
        # Export: member (non-host) is refused, host is allowed
        member = self._login(flask_server, "acl_member")
        self._post(member, flask_server, f"{base}/join")
        assert self._get(member, flask_server, f"{base}/export").status_code == 403
        export = self._get(host, flask_server, f"{base}/export")
        assert export.status_code == 200
        assert export.json()["room"]["room_id"] == room_id
        # Unknown room → 404
        assert self._get(host, flask_server,
                         "/rooms/api/ZZZZ99/state").status_code == 404

    def test_05_shadow_room_forces_observers(self, flask_server):
        expert = self._login(flask_server, "shadow_expert")
        trainee = self._login(flask_server, "shadow_trainee")
        response = self._post(expert, flask_server, "/rooms/api/create",
                              {"room_type": "shadow", "item_ids": ["r4", "r5"]})
        room_id = response.json()["room_id"]
        base = f"/rooms/api/{room_id}"

        joined = self._post(trainee, flask_server, f"{base}/join").json()
        assert joined["role"] == "observer"
        # Observers cannot vote…
        assert self._post(trainee, flask_server, f"{base}/vote",
                          {"label": "Sincere"}).status_code == 400
        # …but they see the expert's activity via events + presence
        assert self._post(expert, flask_server, f"{base}/vote",
                          {"label": "Sarcastic"}).json()["success"]
        assert self._post(expert, flask_server, f"{base}/presence",
                          {"data": {"kind": "selection", "start": 3, "end": 9}}
                          ).json()["success"]
        events = self._get(trainee, flask_server,
                           f"{base}/events?since=0&presence=0").json()
        assert any(e["type"] == "vote_cast" for e in events["events"])
        assert events["presence"][0]["data"]["kind"] == "selection"
        assert events["presence"][0]["user"] == "shadow_expert"

    def test_06_events_cursor_resume(self, flask_server):
        host = self._login(flask_server, "cursor_host")
        response = self._post(host, flask_server, "/rooms/api/create",
                              {"item_ids": ["r6"]})
        room_id = response.json()["room_id"]
        base = f"/rooms/api/{room_id}"
        first = self._get(host, flask_server, f"{base}/events?since=0").json()
        assert first["events"]  # room_created + member_joined
        cursor = first["cursor"]
        # Nothing new → empty page, same cursor
        again = self._get(host, flask_server,
                          f"{base}/events?since={cursor}").json()
        assert again["events"] == []
        assert again["cursor"] == cursor
        # New event appears after the cursor
        self._post(host, flask_server, f"{base}/message", {"text": "hi"})
        page = self._get(host, flask_server,
                         f"{base}/events?since={cursor}").json()
        assert [e["type"] for e in page["events"]] == ["message"]

    def test_08_huddle_seeded_from_disagreements(self, flask_server):
        """A norming room's persisted disagreement becomes a huddle seed."""
        host = self._login(flask_server, "huddle_host")
        partner = self._login(flask_server, "huddle_partner")

        # Manufacture a real disagreement on r5 via a norming room whose
        # final votes persist into annotation state.
        response = self._post(host, flask_server, "/rooms/api/create",
                              {"item_ids": ["r5"]})
        room_id = response.json()["room_id"]
        base = f"/rooms/api/{room_id}"
        self._post(partner, flask_server, f"{base}/join")
        self._post(host, flask_server, f"{base}/vote", {"label": "Sarcastic"})
        self._post(partner, flask_server, f"{base}/vote", {"label": "Sincere"})
        self._post(host, flask_server, f"{base}/reveal")
        self._post(host, flask_server, f"{base}/advance")  # closes + persists

        # The disagreement surfaces
        rows = self._get(host, flask_server,
                         "/rooms/api/disagreements").json()["disagreements"]
        r5 = [r for r in rows if r["instance_id"] == "r5"]
        assert r5, f"r5 not in disagreements: {rows}"
        assert r5[0]["annotations"] == {"huddle_host": "Sarcastic",
                                        "huddle_partner": "Sincere"}
        assert "Room test message number 5." in r5[0]["text"]

        # A huddle room seeds itself from it
        response = self._post(host, flask_server, "/rooms/api/create",
                              {"room_type": "huddle"})
        assert response.status_code == 200, response.text
        huddle_id = response.json()["room_id"]
        state = self._get(host, flask_server,
                          f"/rooms/api/{huddle_id}/state").json()
        assert state["room_type"] == "huddle"
        assert "r5" in state["item_ids"]
        # The original annotations show as context for the current item
        if state["current_instance_id"] == "r5":
            assert state["seed_votes"]["huddle_host"] == "Sarcastic"

    def test_09_huddle_without_disagreements_rejected(self, flask_server):
        host = self._login(flask_server, "huddle_empty_host")
        response = self._post(host, flask_server, "/rooms/api/create",
                              {"room_type": "huddle", "item_ids": ["r6"]})
        # r6 has no conflicting annotations → nothing to huddle over
        assert response.status_code == 400
        assert "disagreements" in response.json()["error"].lower()

    def test_07_lobby_and_room_pages_render(self, flask_server):
        host = self._login(flask_server, "page_host")
        response = self._get(host, flask_server, "/rooms")
        assert response.status_code == 200
        assert "room" in response.text.lower()
        created = self._post(host, flask_server, "/rooms/api/create",
                             {"item_ids": ["r1"]})
        room_id = created.json()["room_id"]
        response = self._get(host, flask_server, f"/rooms/{room_id}")
        assert response.status_code == 200
        assert room_id in response.text

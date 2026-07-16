"""Unit tests for RoomsManager (persistence, replay, metrics, event stream)."""

import json
import os

import pytest

from potato.rooms.config import parse_rooms_config
from potato.rooms.manager import (
    RoomsManager,
    clear_rooms_manager,
    get_rooms_manager,
    init_rooms_manager,
)
from potato.rooms.models import HOST, OBSERVER, RoomError
from tests.helpers.test_utils import create_test_directory

LABELS = ["Sarcastic", "Sincere"]


def make_config(tmp_dir=None, **rooms_overrides):
    rooms = {"enabled": True, "persist_votes": False}
    rooms.update(rooms_overrides)
    config = {
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "sarcasm", "labels": LABELS},
        ],
        "rooms": rooms,
    }
    if tmp_dir:
        config["output_annotation_dir"] = tmp_dir
    return config


def make_manager(tmp_dir=None, **rooms_overrides):
    return RoomsManager(make_config(tmp_dir, **rooms_overrides))


class TestConfigParsing:
    def test_defaults_and_schema_autopick(self):
        cfg = parse_rooms_config(make_config())
        assert cfg.enabled
        assert cfg.schema == "sarcasm"
        assert cfg.who_can_create == "any"
        assert cfg.persist_votes is False  # our override

    def test_disabled_by_default(self):
        assert not parse_rooms_config({}).enabled

    def test_no_votable_schema_disables(self):
        cfg = parse_rooms_config({
            "annotation_schemes": [
                {"annotation_type": "textbox", "name": "notes"}],
            "rooms": {"enabled": True},
        })
        assert not cfg.enabled

    def test_bad_numeric_values_fall_back(self):
        cfg = parse_rooms_config(make_config(
            poll_interval_ms="soon", max_members="lots"))
        assert cfg.poll_interval_ms == 1500
        assert cfg.max_members == 12


class TestSingleton:
    def test_init_get_clear(self):
        init_rooms_manager(make_config())
        assert get_rooms_manager() is not None
        clear_rooms_manager()
        assert get_rooms_manager() is None

    def test_disabled_config_leaves_none(self):
        init_rooms_manager({"rooms": {"enabled": False}})
        assert get_rooms_manager() is None


class TestLifecycle:
    def test_create_join_and_lobby(self):
        manager = make_manager()
        room = manager.create_room("alice", "norming", ["s1", "s2"], LABELS)
        assert room.members["alice"].role == HOST
        manager.join(room, "bob")
        rooms = manager.list_rooms()
        assert len(rooms) == 1
        assert rooms[0]["n_members"] == 2
        assert manager.get_room(room.room_id.lower()) is room  # case-insensitive

    def test_room_full(self):
        manager = make_manager(max_members=2)
        room = manager.create_room("alice", "norming", ["s1"], LABELS)
        manager.join(room, "bob")
        with pytest.raises(RoomError):
            manager.join(room, "carol")
        # Rejoin of an existing member is always allowed
        manager.join(room, "bob")

    def test_unknown_room(self):
        manager = make_manager()
        assert manager.get_room("NOPE99") is None


class TestPersistenceAndReplay:
    def test_events_written_as_jsonl(self):
        tmp_dir = create_test_directory("rooms_jsonl")
        manager = make_manager(tmp_dir)
        room = manager.create_room("alice", "norming", ["s1"], LABELS)
        manager.vote(room, "alice", "Sincere")
        path = os.path.join(tmp_dir, "rooms", f"room-{room.room_id}.jsonl")
        with open(path) as f:
            lines = [json.loads(line) for line in f]
        assert [e["type"] for e in lines] == [
            "room_created", "member_joined", "vote_cast"]
        assert lines[2]["data"]["label"] == "Sincere"  # full event persisted

    def test_restart_replays_rooms(self):
        tmp_dir = create_test_directory("rooms_replay")
        manager = make_manager(tmp_dir)
        room = manager.create_room("alice", "norming", ["s1", "s2"], LABELS)
        manager.join(room, "bob")
        manager.vote(room, "alice", "Sarcastic")
        manager.vote(room, "bob", "Sincere")
        manager.reveal(room, "alice")
        manager.vote(room, "bob", "Sarcastic")
        room_id = room.room_id

        reborn = make_manager(tmp_dir)  # fresh manager, same disk
        restored = reborn.get_room(room_id)
        assert restored is not None
        item = restored.item_states["s1"]
        assert item.revealed
        assert item.initial_votes == {"alice": "Sarcastic", "bob": "Sincere"}
        assert item.current_votes == {"alice": "Sarcastic", "bob": "Sarcastic"}
        assert len(item.changes) == 1
        # And the restored room keeps working
        reborn.advance(restored, "alice")
        assert restored.current_item_id == "s2"

    def test_corrupt_log_is_skipped_not_fatal(self):
        tmp_dir = create_test_directory("rooms_corrupt")
        manager = make_manager(tmp_dir)
        manager.create_room("alice", "norming", ["s1"], LABELS)
        bad = os.path.join(tmp_dir, "rooms", "room-BADBAD.jsonl")
        with open(bad, "w") as f:
            f.write("not json at all\n")
        reborn = make_manager(tmp_dir)
        assert len(reborn.rooms) == 1
        assert reborn.get_room("BADBAD") is None


class TestEventStream:
    def test_cursor_semantics_and_redaction(self):
        manager = make_manager()
        room = manager.create_room("alice", "norming", ["s1"], LABELS)
        cursor = len(room.events)
        manager.join(room, "bob")
        manager.vote(room, "bob", "Sincere")
        events = manager.events_since(room, cursor)
        assert [e["type"] for e in events] == ["member_joined", "vote_cast"]
        assert "label" not in events[1]["data"]  # blind redaction
        # After reveal, the vote table becomes public in the revealed event
        manager.reveal(room, "alice")
        events = manager.events_since(room, cursor)
        revealed = [e for e in events if e["type"] == "revealed"][0]
        assert revealed["data"]["votes"] == {"bob": "Sincere"}
        # Cursor past the end returns nothing
        assert manager.events_since(room, len(room.events)) == []


class TestPresence:
    def test_presence_is_ephemeral_and_bounded(self):
        tmp_dir = create_test_directory("rooms_presence")
        manager = make_manager(tmp_dir)
        room = manager.create_room("alice", "shadow", ["s1"], LABELS)
        for i in range(80):
            manager.record_presence(room, "alice", {"x": i})
        since_all = manager.presence_since(room, 0)
        assert len(since_all) == 50  # ring buffer cap
        # Nothing about presence in the persisted log
        path = os.path.join(tmp_dir, "rooms", f"room-{room.room_id}.jsonl")
        with open(path) as f:
            assert all("presence" not in line for line in f)


class TestMetrics:
    def seeded_room(self, manager):
        room = manager.create_room(
            "alice", "norming", ["s1", "s2", "s3"], LABELS)
        for user in ("bob", "carol"):
            manager.join(room, user)
        return room

    def run_item(self, manager, room, votes, changes=()):
        for user, label in votes.items():
            manager.vote(room, user, label)
        manager.reveal(room, "alice")
        for user, label in changes:
            manager.vote(room, user, label)
        manager.advance(room, "alice")

    def test_alpha_lift_and_conformity(self):
        manager = make_manager()
        room = self.seeded_room(manager)
        # Two items of blind disagreement that discussion resolves:
        self.run_item(manager, room,
                      {"alice": "Sarcastic", "bob": "Sarcastic", "carol": "Sincere"},
                      changes=[("carol", "Sarcastic")])
        self.run_item(manager, room,
                      {"alice": "Sincere", "bob": "Sarcastic", "carol": "Sincere"},
                      changes=[("bob", "Sincere")])
        metrics = manager.metrics(room)
        assert metrics["n_revealed"] == 2
        assert metrics["final_alpha"] is not None
        # Unanimous final votes vs split blind votes → alpha improved.
        if metrics["blind_alpha"] is not None:
            assert metrics["final_alpha"] > metrics["blind_alpha"]
            assert metrics["alpha_lift"] == pytest.approx(
                metrics["final_alpha"] - metrics["blind_alpha"])
        assert metrics["total_changes"] == 2
        assert metrics["toward_majority"] == 2
        assert metrics["per_member"]["carol"]["changes"] == 1
        assert metrics["per_member"]["carol"]["toward_majority"] == 1
        assert metrics["per_member"]["alice"]["changes"] == 0

    def test_single_revealed_item_reports_no_alpha(self):
        """One item cannot support an alpha, so the meter must stay empty.

        Krippendorff's alpha estimates expected disagreement from variation
        across units: over a single item it collapses to exactly 0.0 no matter
        how the room voted. Reporting that 0.0 showed "Blind alpha 0.00" and
        invited a near-consensus to be read as chance-level agreement. Only
        unanimity used to be caught, and only because it divides by zero.
        """
        manager = make_manager()
        room = self.seeded_room(manager)
        # A 2-1 split: real disagreement, but still only one item.
        self.run_item(manager, room,
                      {"alice": "Sarcastic", "bob": "Sarcastic", "carol": "Sincere"},
                      changes=[])
        metrics = manager.metrics(room)
        assert metrics["n_revealed"] == 1
        assert metrics["blind_alpha"] is None
        assert metrics["final_alpha"] is None
        assert metrics["alpha_lift"] is None

    def test_alpha_appears_once_a_second_item_is_revealed(self):
        manager = make_manager()
        room = self.seeded_room(manager)
        self.run_item(manager, room,
                      {"alice": "Sarcastic", "bob": "Sarcastic", "carol": "Sarcastic"},
                      changes=[])
        assert manager.metrics(room)["blind_alpha"] is None
        self.run_item(manager, room,
                      {"alice": "Sincere", "bob": "Sincere", "carol": "Sincere"},
                      changes=[])
        # Two items with perfect within-item agreement → alpha is now real.
        assert manager.metrics(room)["blind_alpha"] is not None

    def test_metrics_empty_room(self):
        manager = make_manager()
        room = manager.create_room("alice", "norming", ["s1"], LABELS)
        metrics = manager.metrics(room)
        assert metrics["n_revealed"] == 0
        assert metrics["blind_alpha"] is None
        assert metrics["alpha_lift"] is None

    def test_export_shape(self):
        manager = make_manager()
        room = self.seeded_room(manager)
        self.run_item(manager, room,
                      {"alice": "Sarcastic", "bob": "Sincere", "carol": "Sincere"})
        export = manager.export_room(room)
        assert export["schema"] == "sarcasm"
        assert len(export["items"]) == 3
        assert export["items"][0]["initial_votes"]  # full votes in export
        assert export["metrics"]["n_revealed"] == 1
        assert export["events"][0]["type"] == "room_created"

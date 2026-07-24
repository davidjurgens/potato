"""Unit tests for the Room state machine (potato/rooms/models.py)."""

import pytest

from potato.rooms.models import (
    CLOSED,
    HOST,
    MEMBER,
    OBSERVER,
    OPEN,
    REVEALED,
    VOTING,
    Room,
    RoomError,
    new_room_id,
)

LABELS = ["Sarcastic", "Sincere"]
ITEMS = ["s01", "s02", "s03"]


def make_room(**overrides):
    kwargs = dict(room_id="TEST42", room_type="norming", host="alice",
                  schema="sarcasm", labels=LABELS, item_ids=ITEMS)
    kwargs.update(overrides)
    room = Room(**kwargs)
    room.record_created()
    room.join("alice", role=HOST)
    return room


class TestRoomBasics:
    def test_room_id_alphabet_avoids_ambiguous_glyphs(self):
        for _ in range(50):
            rid = new_room_id()
            assert len(rid) == 6
            assert not set(rid) & set("0O1IL")

    def test_requires_items(self):
        with pytest.raises(RoomError):
            Room(room_id="X", room_type="norming", host="a", schema="s",
                 labels=LABELS, item_ids=[])

    def test_unknown_room_type_rejected(self):
        with pytest.raises(RoomError):
            Room(room_id="X", room_type="party", host="a", schema="s",
                 labels=LABELS, item_ids=ITEMS)

    def test_initial_state(self):
        room = make_room()
        assert room.status == OPEN
        assert room.phase == VOTING
        assert room.current_item_id == "s01"
        assert room.members["alice"].role == HOST


class TestVotingAndReveal:
    def test_blind_vote_then_reveal(self):
        room = make_room()
        room.join("bob")
        room.vote("alice", "Sarcastic")
        room.vote("bob", "Sincere")
        assert room.all_voted()
        room.reveal("alice")
        assert room.phase == REVEALED
        item = room.current_item
        assert item.initial_votes == {"alice": "Sarcastic", "bob": "Sincere"}

    def test_blind_revote_overwrites_without_conformity_record(self):
        room = make_room()
        room.vote("alice", "Sarcastic")
        room.vote("alice", "Sincere")
        item = room.current_item
        assert item.initial_votes == {"alice": "Sincere"}
        assert item.changes == []

    def test_unknown_label_rejected(self):
        room = make_room()
        with pytest.raises(RoomError):
            room.vote("alice", "Confused")

    def test_nonmember_cannot_vote(self):
        room = make_room()
        with pytest.raises(RoomError):
            room.vote("mallory", "Sincere")

    def test_observer_cannot_vote(self):
        room = make_room()
        room.join("watcher", role=OBSERVER)
        with pytest.raises(RoomError):
            room.vote("watcher", "Sincere")

    def test_reveal_requires_host(self):
        room = make_room()
        room.join("bob")
        room.vote("bob", "Sincere")
        with pytest.raises(RoomError):
            room.reveal("bob")

    def test_reveal_requires_votes(self):
        room = make_room()
        with pytest.raises(RoomError):
            room.reveal("alice")

    def test_double_reveal_rejected(self):
        room = make_room()
        room.vote("alice", "Sincere")
        room.reveal("alice")
        with pytest.raises(RoomError):
            room.reveal("alice")


class TestConformity:
    def make_revealed_room(self):
        room = make_room()
        room.join("bob")
        room.join("carol")
        room.vote("alice", "Sarcastic")
        room.vote("bob", "Sarcastic")
        room.vote("carol", "Sincere")
        room.reveal("alice")
        return room

    def test_post_reveal_change_is_logged_with_majority(self):
        room = self.make_revealed_room()
        event = room.vote("carol", "Sarcastic")
        assert event["type"] == "vote_changed"
        item = room.current_item
        assert item.initial_votes["carol"] == "Sincere"  # blind vote immutable
        assert item.current_votes["carol"] == "Sarcastic"
        assert len(item.changes) == 1
        change = item.changes[0]
        assert change["from"] == "Sincere"
        assert change["to"] == "Sarcastic"
        assert change["majority_at_time"] == "Sarcastic"

    def test_change_to_same_label_rejected(self):
        room = self.make_revealed_room()
        with pytest.raises(RoomError):
            room.vote("carol", "Sincere")

    def test_late_vote_after_reveal_flagged_post_reveal(self):
        room = self.make_revealed_room()
        room.join("dave")
        event = room.vote("dave", "Sincere")
        assert event["type"] == "vote_cast"
        assert event["data"]["post_reveal"] is True

    def test_majority_none_on_tie(self):
        room = make_room()
        room.join("bob")
        room.vote("alice", "Sarcastic")
        room.vote("bob", "Sincere")
        room.reveal("alice")
        assert room.current_item.majority_label() is None


class TestBlindRedaction:
    def test_blind_vote_events_carry_no_label_in_public_view(self):
        room = make_room()
        event = room.vote("alice", "Sarcastic")
        public = Room.public_view(event)
        assert "label" not in public["data"]
        assert event["data"]["label"] == "Sarcastic"  # full event untouched

    def test_post_reveal_events_are_public(self):
        room = make_room()
        room.vote("alice", "Sarcastic")
        room.reveal("alice")
        room.join("bob")
        event = room.vote("bob", "Sincere")
        assert Room.public_view(event)["data"]["label"] == "Sincere"

    def test_state_snapshot_hides_votes_pre_reveal(self):
        room = make_room()
        room.join("bob")
        room.vote("alice", "Sarcastic")
        state = room.to_state(viewer="bob")
        assert state["current_item"]["n_voted"] == 1
        assert state["current_item"]["voted_users"] == ["alice"]
        assert "initial_votes" not in state["current_item"]
        assert state["current_item"]["my_vote"] is None

    def test_state_snapshot_shows_own_vote(self):
        room = make_room()
        room.vote("alice", "Sarcastic")
        state = room.to_state(viewer="alice")
        assert state["current_item"]["my_vote"] == "Sarcastic"

    def test_state_snapshot_shows_votes_post_reveal(self):
        room = make_room()
        room.vote("alice", "Sarcastic")
        room.reveal("alice")
        state = room.to_state(viewer="bob-the-latecomer")
        assert state["current_item"]["initial_votes"] == {"alice": "Sarcastic"}


class TestHuddleSeeds:
    def test_seed_votes_exposed_for_current_item_only(self):
        room = make_room(room_type="huddle", settings={
            "seed_annotations": {"s01": {"dana": "Sincere", "eli": "Sarcastic"}}})
        state = room.to_state(viewer="alice")
        assert state["seed_votes"] == {"dana": "Sincere", "eli": "Sarcastic"}
        room.advance("alice")  # s02 has no seeds
        assert room.to_state(viewer="alice")["seed_votes"] is None

    def test_no_seeds_means_none(self):
        room = make_room()
        assert room.to_state(viewer="alice")["seed_votes"] is None


class TestAdvanceAndClose:
    def test_advance_moves_and_skips_unrevealed(self):
        room = make_room()
        room.advance("alice")  # skip s01 without reveal
        assert room.current_item_id == "s02"
        assert room.item_states["s01"].skipped

    def test_advance_past_last_item_closes(self):
        room = make_room(item_ids=["only"])
        room.vote("alice", "Sincere")
        room.reveal("alice")
        event = room.advance("alice")
        assert event["type"] == "room_closed"
        assert room.status == CLOSED
        assert room.phase == CLOSED
        assert room.current_item_id is None

    def test_advance_requires_host(self):
        room = make_room()
        room.join("bob")
        with pytest.raises(RoomError):
            room.advance("bob")

    def test_closed_room_rejects_everything(self):
        room = make_room()
        room.close("alice")
        for call in (lambda: room.vote("alice", "Sincere"),
                     lambda: room.join("newbie"),
                     lambda: room.message("alice", "hi"),
                     lambda: room.advance("alice")):
            with pytest.raises(RoomError):
                call()


class TestMessages:
    def test_message_appended(self):
        room = make_room()
        event = room.message("alice", "  hello room  ")
        assert event["data"]["text"] == "hello room"

    def test_empty_message_rejected(self):
        room = make_room()
        with pytest.raises(RoomError):
            room.message("alice", "   ")

    def test_message_capped_at_2000_chars(self):
        room = make_room()
        event = room.message("alice", "x" * 5000)
        assert len(event["data"]["text"]) == 2000


class TestReplay:
    def replay(self, source: Room) -> Room:
        clone = Room(room_id=source.room_id, room_type=source.room_type,
                     host=source.host, schema=source.schema,
                     labels=source.labels, item_ids=source.item_ids,
                     settings=source.settings, created_at=source.created_at)
        for event in source.events:
            clone.apply(event)
        return clone

    def test_full_session_replay_reconstructs_state(self):
        room = make_room()
        room.join("bob")
        room.join("watcher", role=OBSERVER)
        room.vote("alice", "Sarcastic")
        room.vote("bob", "Sincere")
        room.reveal("alice")
        room.message("bob", "I read it as deadpan")
        room.vote("bob", "Sarcastic")  # conformity change
        room.advance("alice")
        room.vote("alice", "Sincere")
        room.leave("bob")

        clone = self.replay(room)
        assert clone.status == room.status
        assert clone.current_index == room.current_index
        assert clone.phase == room.phase
        assert set(clone.members) == set(room.members)
        assert clone.members["watcher"].role == OBSERVER
        assert clone.members["bob"].active is False
        for iid in room.item_ids:
            src, dst = room.item_states[iid], clone.item_states[iid]
            assert dst.initial_votes == src.initial_votes
            assert dst.current_votes == src.current_votes
            assert dst.revealed == src.revealed
            assert dst.skipped == src.skipped
            assert [c["to"] for c in dst.changes] == [c["to"] for c in src.changes]
        assert [e["seq"] for e in clone.events] == [e["seq"] for e in room.events]

    def test_replay_of_closed_room(self):
        room = make_room(item_ids=["a"])
        room.vote("alice", "Sincere")
        room.reveal("alice")
        room.advance("alice")
        clone = self.replay(room)
        assert clone.status == CLOSED
        assert clone.current_item_id is None

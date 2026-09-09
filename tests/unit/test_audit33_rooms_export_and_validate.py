"""Rooms: the export cannot be used as a peephole, and a rooms block that
disables itself says so before boot.

Three defects, all measured against a live server by the audit before they
were reproduced here.

1. `GET /rooms/api/<id>/export` is gated on host-or-admin but not on phase, and
   `export_room` returned `to_dict(include_votes=True)` plus the raw event log.
   The host is a voting member, so one participant in every room could read the
   others' blind votes before casting their own -- while `/state`, the surface
   the room page actually polls, redacted them correctly. `blind_alpha`, the
   number the feature exists to produce, is computed as though a peek and an
   honest vote were the same thing.

2. `rooms.enabled: true` with nothing votable parses to `enabled = False` and
   warns on the rooms logger, which `potato validate` does not listen to. The
   config validated clean and /rooms then 404'd.

3. Both boot paths logged "Multiplayer Rooms initialized successfully" one line
   under the warning saying they were disabled.
"""

import io
import logging

from potato.rooms.manager import RoomsManager
from potato.rooms.models import CLOSED

LABELS = ["Sarcastic", "Sincere"]


def make_manager():
    return RoomsManager({
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "sarcasm", "labels": LABELS},
        ],
        "rooms": {"enabled": True, "persist_votes": False},
    })


def live_room(manager):
    """A room mid-session: item s1 voted by two members, not yet revealed."""
    room = manager.create_room("bob", "norming", ["s1", "s2"], LABELS)
    manager.join(room, "alice")
    manager.join(room, "carol")
    manager.vote(room, "alice", "Sarcastic")
    manager.vote(room, "carol", "Sincere")
    return room


# ----------------------------------------------------------------------
# 1. The export is not a peephole
# ----------------------------------------------------------------------

class TestExportRespectsTheBlindPhase:

    def test_a_live_export_hides_the_votes_state_hides(self):
        """The measurement the audit made: bob hosts, has not voted, and his
        /state is redacted. His export must tell the same story."""
        manager = make_manager()
        room = live_room(manager)

        state_item = room.to_state("bob")["current_item"]
        assert state_item["my_vote"] is None
        assert "initial_votes" not in state_item, "the /state redaction broke"

        item = manager.export_room(room)["items"][0]
        assert item["instance_id"] == "s1"
        assert "initial_votes" not in item, (
            "export handed the host every blind vote: "
            f"{item.get('initial_votes')}")
        assert "current_votes" not in item
        # What the host is allowed to know is unchanged.
        assert item["n_voted"] == 2
        assert item["voted_users"] == ["alice", "carol"]

    def test_a_live_export_strips_labels_from_blind_vote_events(self):
        """The item snapshot and the event log are two ways to the same
        secret. Closing one is not a fix."""
        manager = make_manager()
        room = live_room(manager)

        events = manager.export_room(room)["events"]
        casts = [e for e in events if e["type"] == "vote_cast"]
        assert len(casts) == 2, "fixture stopped producing vote events"
        for event in casts:
            assert event["data"].get("post_reveal") is False
            assert "label" not in event["data"], (
                f"blind vote label leaked through the event log: {event}")

    def test_a_revealed_item_still_exports_in_full_while_live(self):
        """Redaction follows reveal, not the room. Once an item is revealed
        its votes are public on every other surface, and blanking them here
        would take data away for nothing."""
        manager = make_manager()
        room = live_room(manager)
        manager.vote(room, "bob", "Sarcastic")
        manager.reveal(room, "bob")

        item = manager.export_room(room)["items"][0]
        assert item["revealed"] is True
        assert item["initial_votes"] == {
            "alice": "Sarcastic", "carol": "Sincere", "bob": "Sarcastic"}

    def test_closing_the_room_releases_everything(self):
        """The researcher's export is unaffected. A room can be closed with an
        item still unrevealed, and those votes are real data -- withholding
        them past the end of the session would lose them for good."""
        manager = make_manager()
        room = live_room(manager)
        manager.close(room, "bob")
        assert room.status == CLOSED

        export = manager.export_room(room)
        item = export["items"][0]
        assert item["revealed"] is False, "fixture revealed the item"
        assert item["initial_votes"] == {
            "alice": "Sarcastic", "carol": "Sincere"}, (
            "a closed room withheld votes the session is over for")
        casts = [e for e in export["events"] if e["type"] == "vote_cast"]
        assert all("label" in e["data"] for e in casts)

    def test_the_export_says_when_it_is_redacted(self):
        """An export that is quietly thinner than the caller expected reads as
        missing data."""
        manager = make_manager()
        room = live_room(manager)
        assert manager.export_room(room)["redacted"] is True
        manager.close(room, "bob")
        assert manager.export_room(room)["redacted"] is False


# ----------------------------------------------------------------------
# 2. validate says what boot says
# ----------------------------------------------------------------------

def _validate(name, config):
    """Run the real `potato validate` on a config that is otherwise clean, so
    the only thing left to report is the rooms block."""
    import json
    import os

    import yaml

    from potato.validate_cli import validate_config_file
    from tests.helpers.test_utils import create_test_directory

    task_dir = create_test_directory(f"audit33_rooms_{name}")
    data_path = os.path.join(task_dir, "items.json")
    with io.open(data_path, "w", encoding="utf-8") as fh:
        json.dump([{"id": "s1", "text": "well that went great"}], fh)

    config = dict(config)
    config.setdefault("port", 8000)
    config.setdefault("annotation_task_name", "audit33")
    config.setdefault("task_dir", task_dir)
    config.setdefault("data_files", [data_path])
    config.setdefault("item_properties",
                      {"id_key": "id", "text_key": "text"})
    config.setdefault("output_annotation_dir",
                      os.path.join(task_dir, "out"))

    path = os.path.join(task_dir, "cfg.yaml")
    with io.open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh)

    report = validate_config_file(path)
    assert report.ok, f"fixture config is not valid: {report.errors}"
    return report


def _rooms_warnings(report):
    return [w for w in report.other_warnings if "rooms" in w.lower()]


class TestValidateWarnsAboutRooms:

    def test_no_votable_scheme_is_reported(self):
        """The audit's config: one textbox scheme, rooms on. Boot disables
        rooms; validate used to print 'OK -- no issues found'."""
        report = _validate("no_votable", {
            "annotation_schemes": [
                {"annotation_type": "text", "name": "notes",
                 "description": "Notes"}],
            "rooms": {"enabled": True},
        })
        warnings = _rooms_warnings(report)
        assert warnings, (
            "validate passed a config whose /rooms returns 404. "
            f"other_warnings={report.other_warnings}")
        assert "404" in warnings[0], warnings[0]

    def test_a_votable_scheme_is_quiet(self):
        """The warning must not fire on the config rooms was built for."""
        report = _validate("votable", {
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "sarcasm",
                 "description": "Sarcasm?", "labels": LABELS}],
            "rooms": {"enabled": True},
        })
        assert not _rooms_warnings(report), report.other_warnings

    def test_rooms_off_is_quiet(self):
        report = _validate("rooms_off", {
            "annotation_schemes": [
                {"annotation_type": "text", "name": "notes",
                 "description": "Notes"}],
            "rooms": {"enabled": False},
        })
        assert not _rooms_warnings(report), report.other_warnings

    def test_a_schema_name_that_matches_nothing_is_reported(self):
        """`rooms.schema` is taken on trust by the parser, so the config boots
        with rooms 'enabled' and every create returns 400."""
        report = _validate("bad_name", {
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "sarcasm",
                 "description": "Sarcasm?", "labels": LABELS}],
            "rooms": {"enabled": True, "schema": "sarcams"},
        })
        warnings = _rooms_warnings(report)
        assert warnings, report.other_warnings
        assert "sarcams" in warnings[0]

    def test_strict_refuses_the_broken_rooms_config(self):
        """The warning has to reach the exit code, or CI cannot use it."""
        report = _validate("strict", {
            "annotation_schemes": [
                {"annotation_type": "text", "name": "notes",
                 "description": "Notes"}],
            "rooms": {"enabled": True},
        })
        assert report.ok, "this is a warning, not an error"
        assert report.other_warnings, "nothing for --strict to fail on"


# ----------------------------------------------------------------------
# 3. The boot line reports what happened
# ----------------------------------------------------------------------

class TestBootLogTellsTheTruth:

    def _config(self, votable):
        scheme = ({"annotation_type": "radio", "name": "sarcasm",
                   "labels": LABELS} if votable else
                  {"annotation_type": "textbox", "name": "notes"})
        return {"annotation_schemes": [scheme], "rooms": {"enabled": True}}

    def test_disabled_rooms_do_not_report_success(self, caplog):
        from potato.flask_server import _init_rooms_if_enabled

        with caplog.at_level(logging.INFO):
            manager = _init_rooms_if_enabled(self._config(votable=False))

        assert manager is None
        text = caplog.text
        assert "initialized successfully" not in text, (
            "boot claimed rooms started, one line under the warning saying "
            f"they did not:\n{text}")
        assert "404" in text, (
            "nothing told the author what the disabled rooms will do")

    def test_working_rooms_still_report_success(self, caplog):
        from potato.flask_server import _init_rooms_if_enabled

        with caplog.at_level(logging.INFO):
            manager = _init_rooms_if_enabled(self._config(votable=True))

        assert manager is not None
        assert "Multiplayer Rooms initialized successfully" in caplog.text

    def test_rooms_off_starts_nothing(self, caplog):
        from potato.flask_server import _init_rooms_if_enabled

        with caplog.at_level(logging.INFO):
            assert _init_rooms_if_enabled({"rooms": {"enabled": False}}) is None
        assert "Multiplayer Rooms" not in caplog.text


# ----------------------------------------------------------------------
# 4. A room vote is spelled like every other vote
# ----------------------------------------------------------------------

def test_a_room_vote_is_stored_the_way_the_form_stores_one():
    """A selected radio posts `on`, so that is what /updateinstance stores.
    `_persist_final_votes` wrote "true", which put the same answer in an
    exported column two ways for no reason -- and anything downstream that
    string-compares the value sees a room vote as a different kind of thing.
    """
    from potato.item_state_management import Label

    manager = make_manager()
    room = live_room(manager)
    manager.vote(room, "bob", "Sarcastic")
    manager.reveal(room, "bob")

    written = {}

    class _UserState:
        def __init__(self, name):
            self.instance_id_to_label_to_value = {"s1": {}}
            self.name = name

    class _USM:
        def __init__(self):
            self.states = {u: _UserState(u)
                           for u in ("alice", "bob", "carol")}

        def get_user_state(self, username):
            return self.states.get(username)

        def save_user_state(self, state):
            written[state.name] = dict(state.instance_id_to_label_to_value["s1"])

    class _ISM:
        instance_annotators = {"s1": set()}

        def has_item(self, iid):
            return True

        def register_annotator(self, iid, user):
            self.instance_annotators[iid].add(user)

    import potato.item_state_management as ism_mod
    import potato.user_state_management as usm_mod
    real_ism, real_usm = (ism_mod.get_item_state_manager,
                          usm_mod.get_user_state_manager)
    ism_mod.get_item_state_manager = lambda: _ISM()
    usm_mod.get_user_state_manager = lambda: _USM()
    try:
        manager.rooms_config.persist_votes = True
        manager._persist_final_votes(room, room.item_states["s1"])
    finally:
        ism_mod.get_item_state_manager = real_ism
        usm_mod.get_user_state_manager = real_usm

    assert written, "the fixture never reached the persist path"
    for user, labels in written.items():
        assert len(labels) == 1, (user, labels)
        (label, value), = labels.items()
        assert isinstance(label, Label)
        assert value == "on", (
            f"{user}'s room vote stored as {value!r}; the form posts 'on' for "
            "the same radio selection")

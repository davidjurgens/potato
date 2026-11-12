"""Live sessions, Phase 5: sign-off, blind first, polls, mentions, metrics,
replay, observers -- and the fixes from potato-skill's Phases 0-3 review.

Real item and user stores (in memory), as in test_collab_manager.py.
"""

import json
import os
import threading

import pytest

from potato.collab.manager import CollabManager, clear_collab_manager, init_collab_manager
from potato.collab.models import OBSERVER, CollabError
from potato.collab.state import item_snapshot, label_key
from potato.item_state_management import (
    Label,
    clear_item_state_manager,
    excluded_items_for,
    init_item_state_manager,
)
from potato.user_state_management import (
    clear_user_state_manager,
    get_user_state_manager,
    init_user_state_manager,
)
from tests.helpers.test_utils import create_test_directory

ITEMS = [f"i{n}" for n in range(1, 7)]
_count = [0]


def make_config(**collab):
    _count[0] += 1
    out = create_test_directory(f"collab_phase5_{_count[0]}")
    block = {"enabled": True,
             "teams": [{"id": "red", "members": ["ana", "ben"], "leader": "ana",
                        "items": ["i1", "i2", "i3"]}]}
    block.update(collab)
    return {
        "output_annotation_dir": os.path.join(out, "out"),
        "task_dir": out,
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "stance", "description": "Stance?",
             "labels": ["pro", "con"]},
            {"annotation_type": "text", "name": "note", "description": "Note"},
        ],
        "collab": block,
    }


@pytest.fixture
def stores():
    def boot(**collab):
        cfg = make_config(**collab)
        clear_user_state_manager()
        clear_item_state_manager()
        init_user_state_manager(cfg)
        ism = init_item_state_manager(cfg)
        ism.add_items({iid: {"id": iid, "text": f"text {iid}"} for iid in ITEMS})
        return cfg
    yield boot
    clear_collab_manager()
    clear_user_state_manager()
    clear_item_state_manager()


def answer(user, iid, stance=None, note=None):
    """Write an answer straight into a user's state (as the save core would)."""
    from potato.phase import UserPhase
    usm = get_user_state_manager()
    state = usm.get_user_state(user) if usm.has_user(user) else usm.add_user(user)
    if state.get_phase() != UserPhase.ANNOTATION:
        state.advance_to_phase(UserPhase.ANNOTATION, None)   # past onboarding
    if stance:
        state.add_label_annotation(iid, Label("stance", stance), stance)
    if note:
        state.add_label_annotation(iid, Label("note", "text_box"), note)
    return state


def team_edit(manager, session, actor, iid, stance):
    team = get_user_state_manager().get_user_state(session.team_user)
    before = item_snapshot(team, iid)
    for other in ("pro", "con"):
        team.remove_label_annotation(iid, Label("stance", other))
    team.add_label_annotation(iid, Label("stance", stance), stance)
    return manager.record_edit(session, actor, iid, before, item_snapshot(team, iid))


class TestSignoff:
    def test_ready_is_bound_to_the_revision_signed(self, stores):
        manager = init_collab_manager(stores(require_signoff=True))
        session = manager.get_session("RED")
        team_edit(manager, session, "ana", "i1", "pro")
        manager.signoff(session, "ana", "i1")
        manager.signoff(session, "ben", "i1")
        assert session.is_signed_off("i1")
        # Any later change takes everyone's mark away.
        team_edit(manager, session, "ben", "i1", "con")
        assert session.ready_members("i1") == []
        assert not session.is_signed_off("i1")

    def test_the_export_record_says_who_signed(self, stores):
        manager = init_collab_manager(stores(require_signoff=True))
        session = manager.get_session("RED")
        team_edit(manager, session, "ana", "i2", "pro")
        manager.signoff(session, "ana", "i2")
        manager.signoff(session, "ben", "i2")
        team = get_user_state_manager().get_user_state(session.team_user)
        record = team.instance_id_to_collab_provenance["i2"]
        assert record["signed_off_by"] == ["ana", "ben"] and record["consensus"] is True

    def test_jump_to_unannotated_means_not_signed_off(self, stores):
        manager = init_collab_manager(stores(require_signoff=True))
        session = manager.get_session("RED")
        for iid in ("i1", "i2"):
            team_edit(manager, session, "ana", iid, "pro")
        manager.signoff(session, "ana", "i2")
        manager.signoff(session, "ben", "i2")
        # i1 is answered but not signed: still where "next unfinished" goes.
        assert manager.target_for(session, "ana", "jump_to_unannotated", current="i3") == "i1"


class TestBlindFirst:
    def test_reveal_waits_for_everyone_then_seeds_what_they_agreed(self, stores):
        manager = init_collab_manager(stores(blind_first=True))
        session = manager.get_session("RED")
        assert session.is_blind("i1")
        answer("ana", "i1", stance="pro", note="mine")
        answer("ben", "i1", stance="pro", note="his")
        manager.blind_done(session, "ana", "i1")
        assert session.is_blind("i1"), "one member done is not everyone"
        manager.blind_done(session, "ben", "i1")
        assert not session.is_blind("i1")

        reveal = manager.reveal_of(session, "i1")["data"]
        assert reveal["units"]["L:stance"]["agree"] is True
        assert reveal["units"]["L:note"]["agree"] is False
        assert reveal["agreement"] == 0.5
        team = get_user_state_manager().get_user_state(session.team_user)
        assert item_snapshot(team, "i1") == {label_key("stance", "pro"): "pro"}
        # The members' own answers stay theirs: the pre-discussion record.
        own = item_snapshot(get_user_state_manager().get_user_state("ben"), "i1")
        assert own[label_key("note", "text_box")] == "his"

    def test_two_drawings_with_the_same_labels_differ_in_placement(self, stores):
        manager = init_collab_manager(stores(blind_first=True))
        session = manager.get_session("RED")
        for user, x in (("ana", 1), ("ben", 9)):
            state = answer(user, "i3")
            state.add_label_annotation("i3", Label("objects", "_data"), json.dumps(
                [{"id": f"{user}-1", "type": "bbox", "label": "car", "coordinates": [x]}]))
        manager.reveal(session, "ana", "i3")
        unit = manager.reveal_of(session, "i3")["data"]["units"]["L:objects"]
        assert unit["answers"] == {"ana": "1 car", "ben": "1 car"}
        assert unit["agree"] is False and unit["detail"] == "placement"

    def test_only_the_leader_reveals_early(self, stores):
        manager = init_collab_manager(stores(blind_first=True))
        session = manager.get_session("RED")
        with pytest.raises(CollabError):
            manager.reveal(session, "ben", "i2")
        manager.reveal(session, "ana", "i2")
        assert not session.is_blind("i2")

    def test_the_team_answer_is_not_signed_while_blind(self, stores):
        manager = init_collab_manager(stores(blind_first=True, require_signoff=True))
        session = manager.get_session("RED")
        with pytest.raises(CollabError):
            manager.signoff(session, "ana", "i1")

    def test_metrics_say_how_much_of_each_own_answer_the_team_kept(self, stores):
        manager = init_collab_manager(stores(blind_first=True))
        session = manager.get_session("RED")
        answer("ana", "i1", stance="pro")
        answer("ben", "i1", stance="con")
        manager.reveal(session, "ana", "i1")
        team_edit(manager, session, "ben", "i1", "pro")
        rows = manager.metrics(session)["members"]
        assert rows["ana"]["blind_kept"] == 1.0
        assert rows["ben"]["blind_kept"] == 0.0


class TestPolls:
    def test_options_come_from_the_scheme_and_votes_stay_hidden(self, stores):
        manager = init_collab_manager(stores())
        session = manager.get_session("RED")
        event = manager.open_poll(session, "ana", "i1", schema="stance")
        pid = event["data"]["poll_id"]
        assert session.polls[pid]["options"] == ["pro", "con"]
        manager.vote(session, "ana", pid, "con")
        seen_by_ben = session.poll_view(session.polls[pid], "ben")
        assert seen_by_ben["voted"] == ["ana"] and "votes" not in seen_by_ben
        assert seen_by_ben["my_vote"] is None

    def test_the_last_vote_closes_it_and_the_winner_can_be_applied(self, stores):
        manager = init_collab_manager(stores())
        session = manager.get_session("RED")
        pid = manager.open_poll(session, "ana", "i1", schema="stance")["data"]["poll_id"]
        manager.vote(session, "ana", pid, "con")
        manager.vote(session, "ben", pid, "con")
        poll = session.polls[pid]
        assert poll["open"] is False and poll["winner"] == "con"
        manager.close_poll(session, "ana", pid, apply=True)
        team = get_user_state_manager().get_user_state(session.team_user)
        assert item_snapshot(team, "i1") == {label_key("stance", "con"): "con"}
        assert session.edits_of("i1")[-1]["data"]["via"] == "poll"

    def test_one_open_poll_per_item(self, stores):
        manager = init_collab_manager(stores())
        session = manager.get_session("RED")
        manager.open_poll(session, "ana", "i1", question="Sarcastic?", options=["yes", "no"])
        with pytest.raises(CollabError):
            manager.open_poll(session, "ben", "i1", schema="stance")


class TestMentionsMetricsReplay:
    def test_mentions_name_members_once_in_any_case(self, stores):
        manager = init_collab_manager(stores())
        session = manager.get_session("RED")
        assert manager.mentions_in(session, "@Ben look, and @ben. Not @zed or me@ana", "ana") == ["ben"]
        event = manager.message(session, "ben", "@ana what do you think?")
        assert event["data"]["mentions"] == ["ana"]

    def test_metrics_count_who_replaced_whom(self, stores):
        manager = init_collab_manager(stores())
        session = manager.get_session("RED")
        team_edit(manager, session, "ana", "i1", "pro")
        team = get_user_state_manager().get_user_state(session.team_user)
        before = item_snapshot(team, "i1")
        team.remove_label_annotation("i1", Label("stance", "pro"))
        team.add_label_annotation("i1", Label("stance", "con"), "con")
        manager.record_edit(session, "ben", "i1", before, item_snapshot(team, "i1"),
                            conflicts=[{"key": "L:stance", "theirs": {"pro": "pro"}}],
                            base_rev=0)
        rows = manager.metrics(session)["members"]
        assert rows["ben"]["overwrote"] == 1 and rows["ana"]["overwritten"] == 1
        assert manager.metrics(session)["conflicts"] == 1

    def test_replay_gives_the_answer_after_each_change(self, stores):
        manager = init_collab_manager(stores())
        session = manager.get_session("RED")
        team_edit(manager, session, "ana", "i1", "pro")
        manager.message(session, "ben", "really?")
        team_edit(manager, session, "ben", "i1", "con")
        frames = manager.replay(session, "i1")["frames"]
        edits = [f for f in frames if f["type"] == "edit"]
        assert [f["answer"] for f in edits] == [["stance: pro"], ["stance: con"]]
        assert any(f["type"] == "message" and f["lines"] == ["really?"] for f in frames)


class TestObservers:
    def test_an_admin_may_watch_a_configured_team(self, stores):
        manager = init_collab_manager(stores())
        session = manager.get_session("RED")
        with pytest.raises(CollabError):
            manager.join(session, "boss", role=OBSERVER)
        manager.join(session, "boss", role=OBSERVER, admin=True)
        assert session.is_member("boss") and not session.can_edit("boss")
        # An observer is not someone the team waits for.
        assert "boss" not in session.editors()


class TestReviewFixes:
    """potato-skill's Phases 0-3 review, one regression each."""

    def test_leaving_gives_the_solo_queue_back(self, stores):
        manager = init_collab_manager(stores())
        session = manager.create_session("cara", name="mine", item_ids=["i4", "i5"])
        assert excluded_items_for("cara") >= {"i4", "i5"}
        manager.leave(session, "cara")
        assert excluded_items_for("cara") == set()
        assert manager.session_holding("cara", "i4") is None
        assert session.team_user not in manager.teams_of("cara")

    def test_a_cut_off_last_line_and_the_appends_after_it_survive_reboots(self, stores):
        cfg = stores()
        manager = init_collab_manager(cfg)
        session = manager.get_session("RED")
        team_edit(manager, session, "ana", "i1", "pro")
        path = os.path.join(cfg["output_annotation_dir"], "collab", "session-RED.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"seq": 99, "type": "mess')          # a crash mid-write

        rebooted = init_collab_manager(cfg)
        restored = rebooted.get_session("RED")
        assert restored.rev_of("i1") == 1, "everything before the cut is kept"
        rebooted.message(restored, "ben", "after the crash")

        again = CollabManager(cfg).get_session("RED")
        assert again.rev_of("i1") == 1
        assert [e["data"]["text"] for e in again.events if e["type"] == "message"] == [
            "after the crash"]

    def test_an_unreadable_log_is_set_aside_not_appended_to(self, stores):
        cfg = stores()
        init_collab_manager(cfg)
        folder = os.path.join(cfg["output_annotation_dir"], "collab")
        path = os.path.join(folder, "session-RED.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not json\n{}\n")
        init_collab_manager(cfg)
        names = os.listdir(folder)
        assert any(n.startswith("session-RED.jsonl.unreadable-") for n in names)
        with open(path, encoding="utf-8") as f:
            assert json.loads(f.readline())["type"] == "session_created"

    def test_a_tracked_write_lets_go_of_the_lock_when_the_snapshot_fails(self, stores, monkeypatch):
        from flask import Flask
        from potato.collab import context
        manager = init_collab_manager(stores())
        session = manager.get_session("RED")

        def broken(*_a, **_k):
            raise RuntimeError("snapshot failed")
        monkeypatch.setattr(context.collab_state, "item_snapshot", broken)
        app = Flask(__name__)
        with app.test_request_context("/api/spans/i1/clear"):
            with pytest.raises(RuntimeError):
                context._begin_tracked_write(manager, session, "ana", "i1")

        got = []
        t = threading.Thread(target=lambda: got.append(
            manager.raw_session_lock(session).acquire(timeout=1)))
        t.start()
        t.join()
        assert got == [True], "the session lock was left held"

    def test_an_attention_check_named_for_a_session_is_refused(self, stores, monkeypatch):
        import potato.quality_control as qc_module
        manager = init_collab_manager(stores())

        class QC:
            def is_attention_check(self, iid):
                return iid == "i5"

            def is_gold_standard(self, iid):
                return iid == "i6"
        monkeypatch.setattr(qc_module, "get_quality_control_manager", lambda: QC())
        with pytest.raises(CollabError, match="i5"):
            manager.create_session("cara", item_ids=["i4", "i5"])
        # Choosing "every item" quietly leaves them out.
        session = manager.create_session("dev")
        assert "i5" not in session.item_ids and "i6" not in session.item_ids
        assert "i4" in session.item_ids

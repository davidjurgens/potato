"""The live-session manager: lifecycle, replay, history, hooks, config.

Uses the real item and user stores (in memory) so the team user it creates is
the same kind of object the server would have.
"""

import json
import os

import pytest

from potato.collab.config import (
    parse_collab_config,
    team_user_for,
    validate_collab_block,
)
from potato.collab.manager import CollabManager, clear_collab_manager, init_collab_manager
from potato.collab.models import FOLLOW, FREE, LEADER, OBSERVER, CollabError
from potato.collab.state import item_snapshot, label_key
from potato.item_state_management import (
    Label,
    clear_item_state_manager,
    excluded_items_for,
    init_item_state_manager,
)
from potato.memos import service as memo_service
from potato.user_state_management import clear_user_state_manager, init_user_state_manager
from tests.helpers.test_utils import create_test_directory

ITEMS = [f"i{n}" for n in range(1, 7)]
_count = [0]


@pytest.fixture
def config():
    _count[0] += 1
    out = create_test_directory(f"collab_manager_{_count[0]}")
    cfg = {
        "output_annotation_dir": os.path.join(out, "out"),
        "task_dir": out,
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "stance", "labels": ["pro", "con"]},
        ],
        "collab": {"enabled": True,
                   "teams": [{"id": "Red Team", "members": ["ana", "ben"],
                              "leader": "ana", "items": ["i1", "i2", "i3"]}]},
    }
    clear_user_state_manager()
    clear_item_state_manager()
    init_user_state_manager(cfg)
    ism = init_item_state_manager(cfg)
    ism.add_items({iid: {"id": iid, "text": f"text {iid}"} for iid in ITEMS})
    yield cfg
    clear_collab_manager()
    clear_user_state_manager()
    clear_item_state_manager()


def _edit(manager, session, actor, iid, label):
    """Write a radio answer to the team user and log it, as the save path does."""
    from potato.user_state_management import get_user_state_manager
    team = get_user_state_manager().get_user_state(session.team_user)
    before = item_snapshot(team, iid)
    for other in ("pro", "con"):
        team.remove_label_annotation(iid, Label("stance", other))
    team.add_label_annotation(iid, Label("stance", label), label)
    return manager.record_edit(session, actor, iid, before, item_snapshot(team, iid))


class TestConfiguredTeams:
    def test_team_gets_a_session_and_a_team_user(self, config):
        manager = init_collab_manager(config)
        session = manager.get_session("RED-TEAM")
        assert session is not None
        assert session.team_user == team_user_for("Red Team") == "team-red-team"
        assert session.leader == "ana"
        assert set(m for m in session.members) == {"ana", "ben"}
        from potato.user_state_management import get_user_state_manager
        team = get_user_state_manager().get_user_state("team-red-team")
        assert set(team.get_assigned_instance_ids()) == {"i1", "i2", "i3"}

    def test_set_up_is_idempotent(self, config):
        manager = init_collab_manager(config)
        manager.ensure_config_teams()
        assert len(manager.sessions) == 1

    def test_hooks_are_installed_and_removed(self, config):
        init_collab_manager(config)
        assert excluded_items_for("ana") == {"i1", "i2", "i3"}
        assert excluded_items_for("zoe") == set()
        assert memo_service.team_membership_resolver("ben") == {"team-red-team"}
        clear_collab_manager()
        assert excluded_items_for("ana") == set()
        assert memo_service.team_membership_resolver is None


class TestLifecycle:
    def test_lobby_session_and_walk_ins(self, config):
        manager = init_collab_manager(config)
        session = manager.create_session("cara", name="mine", item_ids=["i4", "i5"])
        assert session.leader == "cara" and session.mode == FOLLOW
        manager.join(session, "dev")
        manager.join(session, "eli", role=OBSERVER)
        assert session.can_edit("dev") and not session.can_edit("eli")

    def test_configured_team_takes_no_walk_ins(self, config):
        manager = init_collab_manager(config)
        with pytest.raises(CollabError):
            manager.join(manager.get_session("RED-TEAM"), "zoe")

    def test_leader_leaving_hands_over(self, config):
        manager = init_collab_manager(config)
        session = manager.get_session("RED-TEAM")
        manager.leave(session, "ana")
        assert session.leader == "ben"
        assert session.members["ben"].role == LEADER

    def test_only_the_leader_changes_the_mode(self, config):
        manager = init_collab_manager(config)
        session = manager.get_session("RED-TEAM")
        with pytest.raises(CollabError):
            manager.set_mode(session, "ben", FREE)
        manager.set_mode(session, "ana", FREE)
        assert session.mode == FREE

    def test_navigation_stays_inside_the_session(self, config):
        manager = init_collab_manager(config)
        session = manager.get_session("RED-TEAM")
        assert manager.target_for(session, "ben", "next_instance", current="i3") == "i3"
        assert manager.target_for(session, "ben", "prev_instance", current="i2") == "i1"
        assert manager.target_for(session, "ben", "go_to", go_to="2") == "i2"
        with pytest.raises(CollabError):
            manager.target_for(session, "ben", "go_to", go_to="i5")
        manager.view(session, "ana", "i3")
        assert manager.target_for(session, "ben", "follow", current="i1") == "i3"


class TestHistory:
    def test_state_at_reconstructs_earlier_revisions(self, config):
        manager = init_collab_manager(config)
        session = manager.get_session("RED-TEAM")
        _edit(manager, session, "ana", "i1", "pro")
        _edit(manager, session, "ben", "i1", "con")
        from potato.user_state_management import get_user_state_manager
        team = get_user_state_manager().get_user_state(session.team_user)
        now = item_snapshot(team, "i1")
        assert session.rev_of("i1") == 2
        assert manager.state_at(session, "i1", 2, now) == {label_key("stance", "con"): "con"}
        assert manager.state_at(session, "i1", 1, now) == {label_key("stance", "pro"): "pro"}
        assert manager.state_at(session, "i1", 0, now) == {}

    def test_an_edit_records_who_contributed(self, config):
        manager = init_collab_manager(config)
        session = manager.get_session("RED-TEAM")
        _edit(manager, session, "ana", "i2", "pro")
        _edit(manager, session, "ana", "i2", "con")
        from potato.user_state_management import get_user_state_manager
        team = get_user_state_manager().get_user_state(session.team_user)
        record = team.instance_id_to_collab_provenance["i2"]
        assert record["contributors"] == {"ana": 2}
        assert record["session_id"] == "RED-TEAM"

    def test_revert_puts_the_old_answer_back(self, config):
        manager = init_collab_manager(config)
        session = manager.get_session("RED-TEAM")
        _edit(manager, session, "ana", "i1", "pro")
        second = _edit(manager, session, "ben", "i1", "con")
        manager.revert(session, "ana", second["seq"])
        from potato.user_state_management import get_user_state_manager
        team = get_user_state_manager().get_user_state(session.team_user)
        assert item_snapshot(team, "i1") == {label_key("stance", "pro"): "pro"}
        assert session.edits_of("i1")[-1]["data"]["reverts"] == second["seq"]

    def test_the_summary_reads_as_a_change(self, config):
        manager = init_collab_manager(config)
        session = manager.get_session("RED-TEAM")
        _edit(manager, session, "ana", "i1", "pro")
        event = _edit(manager, session, "ben", "i1", "con")
        assert event["data"]["summary"] == ["stance: pro → con"]

    def test_replay_restores_sessions_members_and_revisions(self, config):
        manager = init_collab_manager(config)
        session = manager.get_session("RED-TEAM")
        _edit(manager, session, "ana", "i1", "pro")
        manager.view(session, "ben", "i2", following=False)
        manager.message(session, "ben", "looks pro to me")

        restored = CollabManager(config).get_session("RED-TEAM")
        assert restored.rev_of("i1") == 1
        assert restored.members["ben"].viewing == "i2"
        assert restored.members["ben"].following is False
        assert [e["type"] for e in restored.events] == [e["type"] for e in session.events]

    def test_presence_is_not_logged_and_counts_up(self, config):
        manager = init_collab_manager(config)
        session = manager.get_session("RED-TEAM")
        manager.record_presence(session, "ana", {"instance_id": "i1", "focus": "stance"})
        manager.record_presence(session, "ben", {"instance_id": "i1"})
        seqs = sorted(p["seq"] for p in manager.presence_of(session))
        assert seqs == [1, 2]
        path = os.path.join(config["output_annotation_dir"], "collab", "session-RED-TEAM.jsonl")
        with open(path) as f:
            assert all(json.loads(line)["type"] != "presence" for line in f)


class TestConfig:
    def test_defaults(self):
        parsed = parse_collab_config({"collab": {"enabled": True}})
        assert parsed.transport == "poll" and parsed.default_mode == "follow"
        assert parsed.exclude_members_from_solo is True

    @pytest.mark.parametrize("block, needle", [
        ({"enabled": True, "default_mode": "chaos"}, "default_mode"),
        ({"enabled": True, "teams": [{"id": "a", "members": ["x"], "leader": "y"}]}, "leader"),
        ({"enabled": True, "teams": [{"id": "a", "members": ["x"]},
                                     {"id": "b", "members": ["x"]}]}, "more than one team"),
        ({"enabled": True, "teams": [{"id": "a", "members": ["x"], "colour": "red"}]}, "unknown"),
        ({"enabled": True, "teams": [{"id": "a", "members": ["x"], "items": "all"}]}, "items"),
    ])
    def test_bad_blocks_are_refused_with_the_reason(self, block, needle):
        with pytest.raises(ValueError, match=needle):
            validate_collab_block({"collab": block})

    def test_text_as_image_is_refused(self):
        with pytest.raises(ValueError, match="text_as_image"):
            validate_collab_block({"collab": {"enabled": True},
                                   "text_as_image": {"enabled": True}})

    def test_team_usernames_are_safe_directory_names(self):
        assert team_user_for("Ops: Night/Shift") == "team-ops-night-shift"

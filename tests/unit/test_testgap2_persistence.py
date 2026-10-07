"""
State that has to survive a restart: fields of the saved user state, and the
IBWS round the study had reached.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from potato.item_state_management import Label
from potato.user_state_management import InMemoryUserState, UserPhase
from tests.helpers.test_utils import create_test_directory


def _reloaded(state):
    path = create_test_directory("tg2_state_roundtrip")
    state.save(path)
    return InMemoryUserState.load(path)


class TestSavedUserState:
    def test_a_pending_icl_verification_survives(self):
        state = InMemoryUserState("u1")
        state.mark_instance_as_verification("i2", "sentiment")
        assert _reloaded(state).get_verification_schema("i2") == "sentiment"

    def test_performance_metrics_are_rebuilt_from_the_history(self):
        from potato.annotation_history import AnnotationHistoryManager
        state = InMemoryUserState("u1")
        state.advance_to_phase(UserPhase.ANNOTATION, None)
        for i in range(3):
            state.add_annotation_action(AnnotationHistoryManager.create_action(
                user_id="u1", instance_id=f"i{i}", action_type="add_label",
                schema_name="s", label_name="a", old_value=None, new_value="a"))
        before = state.get_performance_metrics()["total_actions"]
        assert before == 3
        assert _reloaded(state).get_performance_metrics()["total_actions"] == before

    def test_clearing_the_last_label_makes_the_item_unannotated(self):
        state = InMemoryUserState("u1")
        state.advance_to_phase(UserPhase.ANNOTATION, None)
        state.add_label_annotation("i1", Label("tags", "a"), "a")
        state.clear_schema_labels("i1", "tags")
        assert not state.has_annotated("i1")
        assert "i1" not in _reloaded(state).instance_id_to_label_to_value


def _pool(n):
    return [{"id": f"item_{v:03d}", "text": str(v), "value": v} for v in range(n)]


def test_a_restart_returns_ibws_to_the_round_it_had_reached():
    """Rounds lived in memory, so every boot restarted at round 1."""
    from potato import flask_server
    from potato.ibws_manager import IBWSManager
    cfg = {"ibws_config": {"tuple_size": 4, "seed": 1, "tuples_per_item_per_round": 2}}
    pool = _pool(12)
    value = {p["id"]: p["value"] for p in pool}

    store = {}
    user = SimpleNamespace(get_user_id=lambda: "u", instance_id_to_label_to_value=store)
    usm = MagicMock()
    usm.get_all_users.return_value = [user]
    items = {}
    ism = SimpleNamespace(instance_annotators={}, has_item=lambda i: i in items,
                          add_item=lambda i, d: items.__setitem__(i, d))

    def annotate(tuples):
        for t in tuples:
            members = t["_bws_items"]
            store[t["id"]] = {
                Label("bws", "best"): max(members, key=lambda m: value[m["source_id"]])["position"],
                Label("bws", "worst"): min(members, key=lambda m: value[m["source_id"]])["position"]}
            ism.instance_annotators[t["id"]] = {"u"}
            items[t["id"]] = t

    # The first run: round 1 annotated, round 2 generated and half done.
    first = IBWSManager(cfg, pool, "id", "text")
    annotate(first.generate_round_tuples())
    round2 = first.advance_round(ism, usm, "bws")
    assert first.current_round == 2 and round2
    for t in round2:
        items[t["id"]] = t

    # The restart: a fresh manager at round 1, everything stored still there.
    second = IBWSManager(cfg, pool, "id", "text")
    second.generate_round_tuples()
    config = {"annotation_schemes": [{"name": "bws", "annotation_type": "bws"}],
              "item_properties": {"id_key": "id", "text_key": "text"}}
    with patch("potato.ibws_manager.get_ibws_manager", return_value=second), \
            patch.object(flask_server, "get_item_state_manager", return_value=ism), \
            patch.object(flask_server, "get_user_state_manager", return_value=usm), \
            patch.object(flask_server, "_render_displayed_text"):
        flask_server._restore_ibws_rounds(config)
    assert second.current_round == 2
    assert second.round_tuples[2] == first.round_tuples[2]

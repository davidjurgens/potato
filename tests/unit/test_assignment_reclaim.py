import time

from potato.item_state_management import Item, ItemStateManager, Label
from potato.user_state_management import InMemoryUserState, UserPhase
from potato.server_utils.prolific_apis import ProlificStudy


def _manager_with_items():
    manager = ItemStateManager(
        {
            "assignment_strategy": "fixed_order",
            "max_annotations_per_item": 1,
            "instance_reclaim": {"enabled": True, "timeout_hours": 1},
        }
    )
    manager.add_items(
        {
            "item_1": {"id": "item_1", "text": "one"},
            "item_2": {"id": "item_2", "text": "two"},
            "item_3": {"id": "item_3", "text": "three"},
        }
    )
    return manager


def test_unassign_instance_keeps_assignment_indexes_consistent():
    user = InMemoryUserState("worker")
    user.assign_instance(Item("item_1", {"text": "one"}))
    user.assign_instance(Item("item_2", {"text": "two"}))
    user.assign_instance(Item("item_3", {"text": "three"}))
    user.go_to_index(1)

    removed = user.unassign_instance("item_2")

    assert removed is True
    assert user.get_assigned_instance_ids() == {"item_1", "item_3"}
    assert user.instance_id_ordering == ["item_1", "item_3"]
    assert user.instance_id_to_order == {"item_1": 0, "item_3": 1}
    assert user.get_current_instance_index() == 1


def test_reclaim_unannotated_assignments_keeps_completed_work():
    manager = _manager_with_items()
    user = InMemoryUserState("dropout")
    user.advance_to_phase(UserPhase.ANNOTATION, None)
    for item_id in ("item_1", "item_2", "item_3"):
        user.assign_instance(manager.get_item(item_id))
        manager.assignment_timestamps[item_id][user.get_user_id()] = time.time() - 7200

    user.add_label_annotation("item_1", Label("sentiment", "positive"), "true")
    manager.register_annotator("item_1", user.get_user_id())

    reclaimed = manager.reclaim_unannotated_assignments_for_user(
        user,
        reason="test_dropout",
    )

    assert set(reclaimed) == {"item_2", "item_3"}
    assert user.get_assigned_instance_ids() == {"item_1"}
    assert user.instance_id_ordering == ["item_1"]
    assert user.has_annotated("item_1") is True
    assert "dropout" not in manager.assignment_timestamps.get("item_2", {})
    assert "dropout" not in manager.assignment_timestamps.get("item_3", {})


def test_stale_reclaim_removes_assignment_from_real_user_state(monkeypatch):
    manager = _manager_with_items()
    user = InMemoryUserState("stale_worker")
    user.assign_instance(manager.get_item("item_1"))
    manager.assignment_timestamps["item_1"][user.get_user_id()] = time.time() - 7200

    class StubUserStateManager:
        def get_user_state(self, user_id):
            return user if user_id == "stale_worker" else None

    monkeypatch.setattr(
        "potato.user_state_management.get_user_state_manager",
        lambda: StubUserStateManager(),
    )

    manager._reclaim_stale_assignments()

    assert "item_1" not in user.get_assigned_instance_ids()
    assert "item_1" not in user.instance_id_ordering


def test_prolific_dropped_users_release_unannotated_assignments(monkeypatch):
    manager = _manager_with_items()
    user = InMemoryUserState("PROLIFIC_PID_1")
    user.assign_instance(manager.get_item("item_1"))

    class StubUserStateManager:
        def get_user_state(self, user_id):
            return user if user_id == "PROLIFIC_PID_1" else None

        def save_user_state(self, user_state):
            return None

    monkeypatch.setattr(
        "potato.user_state_management.get_user_state_manager",
        lambda: StubUserStateManager(),
    )
    monkeypatch.setattr(
        "potato.item_state_management.get_item_state_manager",
        lambda: manager,
    )

    study = ProlificStudy.__new__(ProlificStudy)
    study.user_status_dict = {
        "RETURNED": {"PROLIFIC_PID_1"},
        "TIMED-OUT": set(),
        "REJECTED": set(),
    }

    reclaimed = study.reclaim_dropped_user_assignments()

    assert reclaimed == {"PROLIFIC_PID_1": ["item_1"]}
    assert user.get_assigned_instance_ids() == set()


def test_quality_control_block_reclaims_batch_and_does_not_keep_failed_response(monkeypatch):
    from potato import routes

    manager = _manager_with_items()
    user = InMemoryUserState("blocked_worker")
    user.advance_to_phase(UserPhase.ANNOTATION, None)
    user.assign_instance(manager.get_item("item_1"))
    user.assign_instance(manager.get_item("item_2"))
    user.add_label_annotation("item_2", Label("attention", "wrong"), "true")

    class StubUserStateManager:
        def save_user_state(self, user_state):
            return None

    monkeypatch.setattr(routes, "get_item_state_manager", lambda: manager)
    monkeypatch.setattr(routes, "get_user_state_manager", lambda: StubUserStateManager())

    reclaimed = routes._reclaim_blocked_user_assignments(
        "blocked_worker",
        user,
        current_instance_id="item_2",
    )

    assert set(reclaimed) == {"item_1", "item_2"}
    assert user.get_assigned_instance_ids() == set()
    assert user.has_annotated("item_2") is False

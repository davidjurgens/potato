import threading
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


def test_blocked_user_reclaim_survives_save_user_state_failure(monkeypatch, caplog):
    """If save_user_state raises, the in-memory reclaim must still hold and
    the failure must be logged rather than swallowed silently."""
    from potato import routes

    manager = _manager_with_items()
    user = InMemoryUserState("save_fail_worker")
    user.advance_to_phase(UserPhase.ANNOTATION, None)
    user.assign_instance(manager.get_item("item_1"))
    user.assign_instance(manager.get_item("item_2"))

    class FailingUserStateManager:
        def save_user_state(self, user_state):
            raise RuntimeError("disk on fire")

    monkeypatch.setattr(routes, "get_item_state_manager", lambda: manager)
    monkeypatch.setattr(routes, "get_user_state_manager", lambda: FailingUserStateManager())

    with caplog.at_level("WARNING", logger="potato.routes"):
        reclaimed = routes._reclaim_blocked_user_assignments(
            "save_fail_worker",
            user,
            current_instance_id="item_1",
        )

    assert set(reclaimed) == {"item_1", "item_2"}
    assert user.get_assigned_instance_ids() == set()
    assert any("disk on fire" in r.getMessage() or "save_fail_worker" in r.getMessage()
               for r in caplog.records), \
        "expected a warning log mentioning the failing user"


def test_prolific_dropped_user_can_be_reassigned_after_reclaim(monkeypatch):
    """After a Prolific worker is dropped and their items are reclaimed,
    the same items must be freely reassignable (to that user or others)."""
    manager = _manager_with_items()
    user = InMemoryUserState("PROLIFIC_PID_X")
    user.assign_instance(manager.get_item("item_1"))
    user.assign_instance(manager.get_item("item_2"))

    class StubUserStateManager:
        def get_user_state(self, user_id):
            return user if user_id == "PROLIFIC_PID_X" else None

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
        "RETURNED": {"PROLIFIC_PID_X"},
        "TIMED-OUT": set(),
        "REJECTED": set(),
    }
    study.reclaim_dropped_user_assignments()

    # The items are now back in the pool — assignment_timestamps for the
    # dropped user must be cleared so a reconnecting worker doesn't trip
    # the stale-assignment heuristic on items they were never reassigned.
    assert "PROLIFIC_PID_X" not in manager.assignment_timestamps.get("item_1", {})
    assert "PROLIFIC_PID_X" not in manager.assignment_timestamps.get("item_2", {})
    assert set(manager.remaining_instance_ids) >= {"item_1", "item_2"}

    # A new (or returning) user can now be reassigned the reclaimed items.
    fresh_user = InMemoryUserState("PROLIFIC_PID_X")
    fresh_user.assign_instance(manager.get_item("item_1"))
    assert "item_1" in fresh_user.get_assigned_instance_ids()


def test_concurrent_reclaim_for_users_is_idempotent(monkeypatch):
    """Two threads racing on reclaim_unannotated_assignments_for_users for the
    same user set must agree on the final state and never double-reclaim."""
    manager = _manager_with_items()
    user = InMemoryUserState("racing_worker")
    user.advance_to_phase(UserPhase.ANNOTATION, None)
    for item_id in ("item_1", "item_2", "item_3"):
        user.assign_instance(manager.get_item(item_id))

    class StubUserStateManager:
        def get_user_state(self, user_id):
            return user if user_id == "racing_worker" else None

        def save_user_state(self, user_state):
            return None

    monkeypatch.setattr(
        "potato.user_state_management.get_user_state_manager",
        lambda: StubUserStateManager(),
    )

    results = [None, None]
    barrier = threading.Barrier(2)

    def worker(idx):
        barrier.wait()
        results[idx] = manager.reclaim_unannotated_assignments_for_users(
            ["racing_worker"],
            reason=f"thread_{idx}",
        )

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    # Combined claims across both threads cover exactly the three items, no duplicates
    claimed = []
    for r in results:
        claimed.extend(r.get("racing_worker", []))
    assert sorted(claimed) == ["item_1", "item_2", "item_3"]
    assert user.get_assigned_instance_ids() == set()
    # remaining_instance_ids may legitimately contain each item once
    for iid in ("item_1", "item_2", "item_3"):
        assert list(manager.remaining_instance_ids).count(iid) == 1


def test_prolific_reclaim_survives_per_user_save_failure(monkeypatch, caplog):
    """A save failure for one dropped user must not block reclaim for others."""
    manager = _manager_with_items()
    user_a = InMemoryUserState("PROLIFIC_PID_A")
    user_b = InMemoryUserState("PROLIFIC_PID_B")
    user_a.assign_instance(manager.get_item("item_1"))
    user_b.assign_instance(manager.get_item("item_2"))

    class PartiallyFailingUserStateManager:
        def get_user_state(self, user_id):
            return {"PROLIFIC_PID_A": user_a, "PROLIFIC_PID_B": user_b}.get(user_id)

        def save_user_state(self, user_state):
            if user_state.get_user_id() == "PROLIFIC_PID_A":
                raise RuntimeError("simulated save failure for A")
            return None

    monkeypatch.setattr(
        "potato.user_state_management.get_user_state_manager",
        lambda: PartiallyFailingUserStateManager(),
    )

    with caplog.at_level("WARNING"):
        result = manager.reclaim_unannotated_assignments_for_users(
            ["PROLIFIC_PID_A", "PROLIFIC_PID_B"],
            reason="prolific_dropped",
        )

    # Both users had their assignments reclaimed in memory, even though A's save failed.
    assert set(result.keys()) == {"PROLIFIC_PID_A", "PROLIFIC_PID_B"}
    assert user_a.get_assigned_instance_ids() == set()
    assert user_b.get_assigned_instance_ids() == set()
    assert any("PROLIFIC_PID_A" in r.getMessage() for r in caplog.records), \
        "expected warning naming the failing user"

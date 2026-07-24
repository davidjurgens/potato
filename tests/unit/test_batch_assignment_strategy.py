"""Unit tests for cohort-based batch assignment."""

import json

import pytest

from potato.item_state_management import (
    get_item_state_manager,
    init_item_state_manager,
    Label,
)
from potato.flask_server import load_instance_data, load_user_data
from potato.server_utils.config_module import (
    ConfigSecurityError,
    ConfigValidationError,
    validate_file_paths,
    validate_yaml_structure,
)
from potato.user_state_management import (
    get_user_state_manager,
    InMemoryUserState,
    clear_user_state_manager,
    init_user_state_manager,
)


def _reset_item_manager():
    import potato.item_state_management

    potato.item_state_management.ITEM_STATE_MANAGER = None


def _config(**overrides):
    config = {
        "assignment_strategy": "batch",
        "max_annotations_per_item": -1,
        "batch_assignment": {
            "groups": [
                {
                    "name": "round1_batch_a",
                    "annotators": ["alice", "bob", "chris", "dana"],
                    "instances": ["a1", "a2"],
                },
                {
                    "name": "round1_batch_b",
                    "annotators": ["erin", "fran", "gabe", "hana"],
                    "instances": ["b1"],
                },
            ],
        },
    }
    config.update(overrides)
    return config


def _valid_yaml_config(**overrides):
    config = {
        "assignment_strategy": "batch",
        "annotation_task_name": "Batch Assignment Test",
        "item_properties": {"id_key": "id", "text_key": "text"},
        "data_files": ["data.json"],
        "task_dir": ".",
        "output_annotation_dir": ".",
        "annotation_schemes": [
            {
                "name": "choice",
                "annotation_type": "radio",
                "description": "Choose yes or no",
                "labels": ["yes", "no"],
            }
        ],
        "batch_assignment": {
            "groups": [
                {
                    "annotators": ["alice", "bob"],
                    "instances": ["item_1", "item_2"],
                }
            ],
        },
    }
    config.update(overrides)
    return config


def _manager(config=None):
    _reset_item_manager()
    ism = init_item_state_manager(config or _config())
    ism.add_items(
        {
            "a1": {"id": "a1", "text": "batch A item 1"},
            "a2": {"id": "a2", "text": "batch A item 2"},
            "b1": {"id": "b1", "text": "batch B item 1"},
            "open": {"id": "open", "text": "not assigned to any batch"},
        }
    )
    return ism


def _manager_with_items(config, item_ids):
    _reset_item_manager()
    ism = init_item_state_manager(config)
    ism.add_items(
        {
            item_id: {"id": item_id, "text": f"item {item_id}"}
            for item_id in item_ids
        }
    )
    return ism


def _user(user_id, max_assignments=10):
    return InMemoryUserState(user_id, max_assignments=max_assignments)


def test_batch_assignment_keeps_round_one_cohort_on_same_items():
    ism = _manager()

    alice = _user("alice")
    bob = _user("bob")
    erin = _user("erin")

    assert ism.assign_instances_to_user(alice) == 2
    assert alice.instance_id_ordering == ["a1", "a2"]
    assert alice.has_remaining_assignments() is True

    assert ism.assign_instances_to_user(bob) == 2
    assert bob.instance_id_ordering == ["a1", "a2"]

    assert ism.assign_instances_to_user(erin) == 1
    assert erin.instance_id_ordering == ["b1"]


def test_batch_assignment_with_unlimited_user_quota_assigns_whole_batch():
    ism = _manager()
    alice = _user("alice", max_assignments=-1)

    assert ism.assign_instances_to_user(alice) == 2
    assert alice.instance_id_ordering == ["a1", "a2"]


def test_batch_assignment_blocks_users_outside_any_cohort():
    ism = _manager()
    outsider = _user("outsider")

    assert ism.has_unlabeled_items_for_user(outsider) is False
    assert ism.assign_instances_to_user(outsider) == 0
    assert outsider.instance_id_ordering == []


def test_batch_assignment_auto_assigns_unknown_users_to_balanced_groups():
    config = _config(
        max_annotations_per_item=2,
        batch_assignment={
            "auto_assign_annotators": True,
            "groups": [
                {
                    "name": "batch_a",
                    "instances": ["a1", "a2"],
                },
                {
                    "name": "batch_b",
                    "instances": ["b1"],
                },
            ],
        },
    )
    ism = _manager(config)

    user_1 = _user("PROLIFIC_PID_1")
    user_2 = _user("PROLIFIC_PID_2")
    user_3 = _user("PROLIFIC_PID_3")
    user_4 = _user("PROLIFIC_PID_4")
    user_5 = _user("PROLIFIC_PID_5")

    assert ism.assign_instances_to_user(user_1) == 2
    assert user_1.instance_id_ordering == ["a1", "a2"]

    assert ism.assign_instances_to_user(user_2) == 1
    assert user_2.instance_id_ordering == ["b1"]

    assert ism.assign_instances_to_user(user_3) == 2
    assert user_3.instance_id_ordering == ["a1", "a2"]

    assert ism.assign_instances_to_user(user_4) == 1
    assert user_4.instance_id_ordering == ["b1"]

    assert ism.assign_instances_to_user(user_5) == 0
    assert user_5.instance_id_ordering == []


def test_batch_assignment_auto_group_choice_is_stable_for_same_unknown_user():
    config = _config(
        max_annotations_per_item=2,
        batch_assignment={
            "auto_assign_annotators": True,
            "groups": [
                {"name": "batch_a", "instances": ["a1", "a2"]},
                {"name": "batch_b", "instances": ["b1"]},
            ],
        },
    )
    ism = _manager(config)
    user = _user("PROLIFIC_PID_1")

    assert ism.assign_instances_to_user(user) == 2
    assert ism.assign_instances_to_user(user) == 0
    assert user.instance_id_ordering == ["a1", "a2"]


def _auto_pin_maps(ism):
    """Snapshot the auto-batch pin state, dropping empty reverse-map entries."""
    return (
        dict(ism.batch_auto_user_to_group),
        {index: set(users) for index, users in ism.batch_auto_group_to_users.items() if users},
    )


def test_batch_assignment_auto_pins_survive_restart():
    """Reconstruct cohort pins from persisted assignments so a restart keeps
    every user in their group and new users balance against accurate counts."""
    config = _config(
        max_annotations_per_item=100,  # groups effectively unbounded here
        batch_assignment={
            "auto_assign_annotators": True,
            "groups": [
                {"name": "batch_a", "instances": ["a1", "a2"]},
                {"name": "batch_b", "instances": ["b1"]},
            ],
        },
    )

    ism = _manager(config)
    user_1, user_2, user_3 = _user("PID_1"), _user("PID_2"), _user("PID_3")
    assert ism.assign_instances_to_user(user_1) == 2  # -> batch_a
    assert ism.assign_instances_to_user(user_2) == 1  # -> batch_b
    assert ism.assign_instances_to_user(user_3) == 2  # tie -> batch_a
    pins_before, counts_before = _auto_pin_maps(ism)
    assert pins_before == {"PID_1": 0, "PID_2": 1, "PID_3": 0}
    assert counts_before == {0: {"PID_1", "PID_3"}, 1: {"PID_2"}}

    # Simulate a restart: a brand-new manager starts with empty pins, then
    # reconstructs them from the users' persisted assignments.
    restarted = _manager(config)
    assert _auto_pin_maps(restarted) == ({}, {})
    user_map = {
        u.user_id: set(u.get_assigned_instance_ids())
        for u in (user_1, user_2, user_3)
    }
    restarted.rebuild_auto_batch_pins_from_users(user_map)

    assert _auto_pin_maps(restarted) == (pins_before, counts_before)

    # A new user must balance against the reconstructed counts (batch_b is the
    # least-filled), not against a zeroed-out map (which would pick batch_a).
    user_4 = _user("PID_4")
    assert restarted.assign_instances_to_user(user_4) == 1
    assert user_4.instance_id_ordering == ["b1"]
    assert restarted.batch_auto_user_to_group["PID_4"] == 1


def test_batch_assignment_auto_pin_released_when_group_saturated():
    """A user routed to a group whose items are all saturated is assigned
    nothing and must not consume an auto-batch slot (so the pin stays
    reconstructable from real assignments)."""
    config = _config(
        max_annotations_per_item=1,  # items saturate after one annotator
        batch_assignment={
            "auto_assign_annotators": True,
            "groups": [
                # High capacity so the group is chosen by selection, but its
                # items are already saturated below.
                {"name": "batch_a", "instances": ["a1", "a2"], "max_annotators": 5},
            ],
        },
    )
    ism = _manager(config)

    # Saturate both items via prior annotators (cap = 1).
    ism.register_annotator("a1", "prior_1")
    ism.register_annotator("a2", "prior_2")

    latecomer = _user("PID_LATE")
    assert ism.assign_instances_to_user(latecomer) == 0
    assert latecomer.instance_id_ordering == []
    # No slot consumed: the fresh pin was rolled back.
    assert "PID_LATE" not in ism.batch_auto_user_to_group
    assert _auto_pin_maps(ism) == ({}, {})


def test_batch_assignment_auto_pin_reconstruction_handles_overlap(caplog):
    """Overlapping group items and cross-group users pin to the majority group
    (ties -> lowest index) and emit warnings."""
    config = _config(
        max_annotations_per_item=100,
        batch_assignment={
            "auto_assign_annotators": True,
            "groups": [
                {"name": "batch_a", "instances": ["a1", "a2"]},
                {"name": "batch_b", "instances": ["a2", "b1"]},  # a2 overlaps
            ],
        },
    )
    ism = _manager(config)

    with caplog.at_level("WARNING"):
        ism.rebuild_auto_batch_pins_from_users(
            {
                "spanner": {"a1", "a2", "b1"},  # 2 in batch_a, 1 in batch_b
                "tied": {"a2", "b1"},           # after overlap: a2->A, b1->B, tie
            }
        )

    pins, _ = _auto_pin_maps(ism)
    assert pins["spanner"] == 0  # majority is batch_a
    assert pins["tied"] == 0     # tie broken by lowest index
    warnings = caplog.text
    assert "overlap" in warnings.lower()
    assert "spanning multiple" in warnings.lower()


def test_batch_assignment_can_use_item_level_round_one_annotator_key():
    config = _config(
        batch_assignment={
            "annotator_key": "round1_annotators",
            "groups": [],
        }
    )
    _reset_item_manager()
    ism = init_item_state_manager(config)
    ism.add_items(
        {
            "item_1": {
                "id": "item_1",
                "text": "round 2 item",
                "round1_annotators": ["alice", "bob", "chris", "dana"],
            },
            "item_2": {
                "id": "item_2",
                "text": "other cohort",
                "round1_annotators": ["erin", "fran", "gabe", "hana"],
            },
        }
    )

    alice = _user("alice")
    erin = _user("erin")

    assert ism.assign_instances_to_user(alice) == 1
    assert alice.instance_id_ordering == ["item_1"]

    assert ism.assign_instances_to_user(erin) == 1
    assert erin.instance_id_ordering == ["item_2"]


def test_batch_assignment_group_can_load_instances_from_json_data_file(tmp_path):
    batch_file = tmp_path / "batch_a.json"
    batch_file.write_text(
        json.dumps(
            [
                {"id": "a1", "text": "round 2 item 1"},
                {"id": "a2", "text": "round 2 item 2"},
            ]
        ),
        encoding="utf-8",
    )
    config = _config(
        task_dir=str(tmp_path),
        batch_assignment={
            "groups": [
                {
                    "annotators": ["alice", "bob", "chris", "dana"],
                    "instances_file": "batch_a.json",
                }
            ],
        },
    )
    ism = _manager_with_items(config, ["a1", "a2", "b1"])
    alice = _user("alice")

    assert ism.assign_instances_to_user(alice) == 2
    assert alice.instance_id_ordering == ["a1", "a2"]


def test_batch_assignment_group_can_load_instances_from_csv_data_file(tmp_path):
    batch_file = tmp_path / "batch_a.csv"
    batch_file.write_text("id,text\na1,one\na2,two\n", encoding="utf-8")
    config = _config(
        task_dir=str(tmp_path),
        batch_assignment={
            "groups": [
                {
                    "annotators": ["alice", "bob", "chris", "dana"],
                    "instances_file": {"path": "batch_a.csv", "encoding": "utf-8"},
                }
            ],
        },
    )
    ism = _manager_with_items(config, ["a1", "a2", "b1"])
    alice = _user("alice")

    assert ism.assign_instances_to_user(alice) == 2
    assert alice.instance_id_ordering == ["a1", "a2"]


def test_batch_assignment_group_data_file_loads_items_and_batch_ids(tmp_path):
    batch_file = tmp_path / "batch_a.json"
    batch_file.write_text(
        json.dumps(
            [
                {"id": "a1", "text": "round 2 item 1"},
                {"id": "a2", "text": "round 2 item 2"},
            ]
        ),
        encoding="utf-8",
    )
    config = _valid_yaml_config(
        task_dir=str(tmp_path),
        output_annotation_dir=str(tmp_path),
        data_files=[],
        batch_assignment={
            "groups": [
                {
                    "annotators": ["alice", "bob", "chris", "dana"],
                    "data_file": "batch_a.json",
                }
            ],
        },
    )
    validate_yaml_structure(config)
    validate_file_paths(config, str(tmp_path))

    _reset_item_manager()
    clear_user_state_manager()
    init_user_state_manager(config)
    ism = init_item_state_manager(config)
    load_instance_data(config)

    alice = _user("alice")

    assert ism.get_instance_ids() == ["a1", "a2"]
    assert ism.assign_instances_to_user(alice) == 2
    assert alice.instance_id_ordering == ["a1", "a2"]


def test_batch_assignment_auto_pins_restored_through_load_user_data(tmp_path):
    """End-to-end boot path: assign auto users, persist to disk, then reload via
    load_user_data() and confirm the cohort pins are rebuilt."""
    (tmp_path / "batch_a.json").write_text(
        json.dumps([{"id": "a1", "text": "A1"}, {"id": "a2", "text": "A2"}]),
        encoding="utf-8",
    )
    (tmp_path / "batch_b.json").write_text(
        json.dumps([{"id": "b1", "text": "B1"}]),
        encoding="utf-8",
    )
    config = _valid_yaml_config(
        task_dir=str(tmp_path),
        output_annotation_dir=str(tmp_path),
        data_files=[],
        max_annotations_per_item=100,
        batch_assignment={
            "auto_assign_annotators": True,
            "groups": [
                {"name": "batch_a", "data_file": "batch_a.json"},
                {"name": "batch_b", "data_file": "batch_b.json"},
            ],
        },
    )
    validate_yaml_structure(config)
    validate_file_paths(config, str(tmp_path))

    def _boot():
        _reset_item_manager()
        clear_user_state_manager()
        init_user_state_manager(config)
        init_item_state_manager(config)
        load_instance_data(config)

    # First run: two unknown users land in different balanced groups.
    _boot()
    ism = get_item_state_manager()
    usm = get_user_state_manager()
    user_a = _user("PID_A")
    user_b = _user("PID_B")
    assert ism.assign_instances_to_user(user_a) == 2  # batch_a
    assert ism.assign_instances_to_user(user_b) == 1  # batch_b
    usm.save_user_state(user_a)
    usm.save_user_state(user_b)

    # Restart: reload persisted users; pins must be reconstructed.
    _boot()
    load_user_data(config)
    restarted = get_item_state_manager()
    assert restarted.batch_auto_user_to_group == {"PID_A": 0, "PID_B": 1}

    # Returning user (reloaded from disk) keeps their batch and gets nothing new.
    reloaded_a = get_user_state_manager().get_user_state("PID_A")
    assert reloaded_a.instance_id_ordering == ["a1", "a2"]
    assert restarted.assign_instances_to_user(reloaded_a) == 0

    # A new user fills the least-filled group.
    user_c = _user("PID_C")
    assert restarted.assign_instances_to_user(user_c) == 2  # both had 1 -> batch_a
    assert restarted.batch_auto_user_to_group["PID_C"] == 0


def test_batch_assignment_instances_file_blocks_path_traversal(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    outside_file = tmp_path / "outside.json"
    outside_file.write_text(json.dumps(["a1"]), encoding="utf-8")
    config = _config(
        task_dir=str(task_dir),
        batch_assignment={
            "groups": [
                {
                    "annotators": ["alice"],
                    "instances_file": "../outside.json",
                }
            ],
        },
    )

    _reset_item_manager()
    with pytest.raises(ConfigSecurityError):
        init_item_state_manager(config)


def test_batch_assignment_instances_file_validates_path_security(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    outside_file = tmp_path / "outside.json"
    outside_file.write_text(json.dumps(["a1"]), encoding="utf-8")
    config = _valid_yaml_config(
        task_dir=str(task_dir),
        output_annotation_dir=str(task_dir),
        data_files=[],
        batch_assignment={
            "groups": [
                {
                    "annotators": ["alice"],
                    "instances_file": "../outside.json",
                }
            ],
        },
    )

    with pytest.raises(ConfigSecurityError):
        validate_file_paths(config, str(task_dir))


def test_batch_assignment_group_combines_inline_and_file_instances(tmp_path):
    batch_file = tmp_path / "batch_a.json"
    batch_file.write_text(json.dumps(["a2", "a3"]), encoding="utf-8")
    config = _config(
        task_dir=str(tmp_path),
        batch_assignment={
            "groups": [
                {
                    "annotators": ["alice", "bob", "chris", "dana"],
                    "instances": ["a1"],
                    "instances_file": "batch_a.json",
                }
            ],
        },
    )
    ism = _manager_with_items(config, ["a1", "a2", "a3"])
    alice = _user("alice")

    assert ism.assign_instances_to_user(alice) == 3
    assert alice.instance_id_ordering == ["a1", "a2", "a3"]


def test_batch_assignment_respects_item_annotation_cap():
    ism = _manager(_config(max_annotations_per_item=1))

    alice = _user("alice")
    bob = _user("bob")

    assert ism.assign_instances_to_user(alice) == 2
    alice.add_label_annotation("a1", Label("choice", "choice"), "yes")
    ism.register_annotator("a1", "alice")

    assert ism.assign_instances_to_user(bob) == 1
    assert bob.instance_id_ordering == ["a2"]


def test_batch_assignment_config_validation_accepts_strategy_and_groups():
    config = _valid_yaml_config(
        batch_assignment={
                "annotator_key": "round1_annotators",
                "groups": [
                    {
                        "annotators": ["alice", "bob"],
                        "instances": ["item_1", "item_2"],
                    }
                ],
            }
    )
    validate_yaml_structure(config)


def test_batch_assignment_config_validation_accepts_group_file_reference():
    config = _valid_yaml_config(
        batch_assignment={
            "groups": [
                {
                    "annotators": ["alice", "bob"],
                    "instances_file": {"path": "batch_a.csv", "encoding": "utf-8"},
                }
            ],
        }
    )
    validate_yaml_structure(config)


def test_batch_assignment_config_validation_accepts_auto_groups_without_known_users():
    config = _valid_yaml_config(
        batch_assignment={
            "auto_assign_annotators": True,
            "groups": [
                {
                    "name": "batch_a",
                    "instances": ["item_1", "item_2"],
                    "max_annotators": 4,
                }
            ],
        }
    )

    validate_yaml_structure(config)


def test_batch_assignment_config_validation_rejects_invalid_groups():
    with pytest.raises(ConfigValidationError, match="non-empty annotators/users list"):
        validate_yaml_structure(
            _valid_yaml_config(
                batch_assignment={
                    "groups": [
                        {
                            "annotators": [],
                            "instances": ["item_1"],
                        }
                    ],
                }
            )
        )


def test_batch_assignment_config_validation_requires_instances_or_file():
    with pytest.raises(ConfigValidationError, match="must define either"):
        validate_yaml_structure(
            _valid_yaml_config(
                batch_assignment={
                    "groups": [
                        {
                            "annotators": ["alice", "bob"],
                        }
                    ],
                }
            )
        )

"""Unit tests for cohort-based batch assignment."""

import json

import pytest

from potato.item_state_management import init_item_state_manager, Label
from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_yaml_structure,
)
from potato.user_state_management import InMemoryUserState


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


def test_batch_assignment_blocks_users_outside_any_cohort():
    ism = _manager()
    outsider = _user("outsider")

    assert ism.has_unlabeled_items_for_user(outsider) is False
    assert ism.assign_instances_to_user(outsider) == 0
    assert outsider.instance_id_ordering == []


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

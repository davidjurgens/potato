"""
Keys a config may set that nothing reads are named at boot.

`surveyflow`, `automatic_assignment` and the top-level `prestudy` block are
Potato 1.x settings. 2.x accepted them silently, so a 1.x config booted with no
survey pages, no screener and no assignment cap, and nothing said so. The
`active_learning` routing keys were documented as routing machine labels past
annotators, and nothing read them either.
"""

import logging

import pytest

from potato.server_utils.config_module import (
    UNREAD_CONFIG_KEYS, unread_key_warnings, validate_unknown_keys,
)


@pytest.mark.parametrize("config, key", [
    ({"surveyflow": {"on": True, "pre_annotation": ["consent.jsonl"]}}, "surveyflow"),
    ({"surveyflow": {"on": False}}, "surveyflow"),
    ({"prestudy": {"on": True}}, "prestudy"),
    ({"automatic_assignment": {"on": True, "labels_per_instance": 3}}, "automatic_assignment"),
    ({"active_learning": {"annotation_routing": True}}, "active_learning.annotation_routing"),
    ({"active_learning": {"routing_thresholds": {}}}, "active_learning.routing_thresholds"),
    ({"active_learning": {"verification_sample_rate": 0.2}},
     "active_learning.verification_sample_rate"),
])
def test_each_unread_key_is_named(config, key):
    messages = unread_key_warnings(config)
    assert len(messages) == 1
    assert f"'{key}' is not read" in messages[0]


def test_read_keys_and_a_phase_called_prestudy_are_not_named():
    config = {
        "phases": {"order": ["prestudy"], "prestudy": {"type": "prestudy", "file": "s.json"}},
        "active_learning": {"enabled": True, "classifier_name": "logistic"},
        "assignment_strategy": "random",
    }
    assert unread_key_warnings(config) == []


def test_unread_keys_are_still_accepted_so_they_get_one_warning_not_two(caplog):
    # An "unrecognized key" warning on top would suggest a typo, not a 1.x key.
    config = {"surveyflow": {"on": False}, "automatic_assignment": {"on": False},
              "prestudy": {"on": False},
              "active_learning": {"annotation_routing": True, "routing_thresholds": {},
                                  "verification_sample_rate": 0.2}}
    with caplog.at_level(logging.WARNING):
        validate_unknown_keys(config)
    assert not [r for r in caplog.records if "Unrecognized" in r.getMessage()]
    assert len(unread_key_warnings(config)) == len(UNREAD_CONFIG_KEYS)


@pytest.mark.parametrize("key", ["classifier_name", "vectorizer_name", "classifier_kwargs",
                                 "vectorizer_kwargs", "cold_start_batch_size",
                                 "model_persistence_enabled", "model_save_directory",
                                 "model_retention_count", "llm_enabled", "llm_config"])
def test_flat_active_learning_fields_the_guides_use_are_recognised(key, caplog):
    with caplog.at_level(logging.WARNING):
        validate_unknown_keys({"active_learning": {"enabled": True, key: None}})
    assert not caplog.records, [r.getMessage() for r in caplog.records]

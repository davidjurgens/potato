"""
`category_assignment.dynamic: true` must be refused, not crash at boot.

Every reader of the block does `dynamic.get('enabled')`, so the natural
shorthand -- writing the flag directly on `dynamic` instead of nesting it under
`enabled` -- reached them as a bool and raised AttributeError while the item
state manager was being built. A crash during startup, from a config that
passed validation and named a real key with a plausible value.

`dynamic` had no type check at all: it was on the allowed-keys list and nothing
else, so nothing between the YAML and the crash looked at it.

Refusal rather than a warning, because there is no reading of `dynamic: true`
under which the study works: the flag is unreachable, dynamic expertise stays
off, and static qualification then serves the annotator nothing.
"""

import pytest

from potato.server_utils import config_module
from potato.server_utils.config_module import ConfigValidationError


def _config(dynamic):
    return {"category_assignment": {"enabled": True, "dynamic": dynamic}}


@pytest.mark.parametrize("dynamic", [True, False, "true", 1, ["enabled"]])
def test_a_non_mapping_dynamic_is_refused(dynamic):
    with pytest.raises(ConfigValidationError) as excinfo:
        config_module.validate_category_assignment_config(_config(dynamic))
    message = str(excinfo.value)
    assert "category_assignment.dynamic" in message
    # The message has to carry the fix, not just the complaint.
    assert "enabled: true" in message, message


@pytest.mark.parametrize("dynamic", [{}, {"enabled": True},
                                     {"enabled": False}])
def test_a_mapping_dynamic_is_accepted(dynamic):
    config_module.validate_category_assignment_config(_config(dynamic))


def test_absent_dynamic_is_fine():
    config_module.validate_category_assignment_config(
        {"category_assignment": {"enabled": True}})


class TestManagerSurvivesIt:
    """Validation is the real defence, but a manager built directly --
    by a test, or by tooling that skips validation -- must degrade to
    "dynamic off" rather than raise. This is the crash the config-level
    refusal exists to prevent, so it is worth building the object."""

    def _manager(self, dynamic):
        from potato.item_state_management import (
            clear_item_state_manager, init_item_state_manager)

        clear_item_state_manager()
        try:
            return init_item_state_manager({
                "annotation_task_name": "dynamic_shape_probe",
                "task_dir": ".",
                "assignment_strategy": "category_based",
                "item_properties": {"id_key": "id", "text_key": "text",
                                    "category_key": "topic"},
                "category_assignment": {"enabled": True,
                                        "dynamic": dynamic},
                "annotation_schemes": [{"name": "v", "description": "V",
                                        "annotation_type": "radio",
                                        "labels": ["yes", "no"]}],
            })
        finally:
            pass

    def teardown_method(self):
        from potato.item_state_management import clear_item_state_manager
        clear_item_state_manager()

    def test_a_bool_dynamic_does_not_raise_and_reads_as_off(self):
        manager = self._manager(True)
        assert manager.dynamic_expertise_enabled is False

    def test_a_real_dynamic_block_still_turns_it_on(self):
        """The guard must not have turned the feature off for everyone."""
        manager = self._manager({"enabled": True})
        assert manager.dynamic_expertise_enabled is True

"""`min_annotators_per_instance` reaches the assigner as the cap.

It used to be parsed into `ItemStateManager.min_annotations_per_item`,
an attribute assigned in three places and read in none. A study whose
config asked for three annotators an item collected as many as it got,
and nothing in the output showed the number had been discarded.

It names no setting that `num_annotators_per_item` does not, so it is
now a deprecated spelling of it: the number the author wrote becomes the
enforced per-item cap. These tests assert the resolved cap and the
manager's live behaviour, not the presence of a branch.
"""

import pathlib
import warnings

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    resolve_num_annotators_per_item,
    validate_optional_field_types,
    warn_unenforced_coverage_floor,
)


class TestItResolvesToTheCap:
    def test_alone_it_is_the_cap(self):
        assert resolve_num_annotators_per_item(
            {"min_annotators_per_instance": 3}) == 3

    def test_it_no_longer_leaves_the_study_uncapped(self):
        # The defect, stated as the number it produced: -1 is unlimited.
        assert resolve_num_annotators_per_item(
            {"min_annotators_per_instance": 3}) != -1

    def test_the_canonical_key_still_wins(self):
        assert resolve_num_annotators_per_item({
            "num_annotators_per_item": 5,
            "min_annotators_per_instance": 5,
        }) == 5

    def test_the_structured_default_still_wins(self):
        assert resolve_num_annotators_per_item({
            "num_annotators_per_item": {"default": 4},
            "min_annotators_per_instance": 4,
        }) == 4

    def test_absent_is_still_unlimited(self):
        assert resolve_num_annotators_per_item({}) == -1


class TestConflictsAreRefusedNotGuessed:
    """Two numbers for one slot is a question only the author can answer."""

    def test_disagreeing_with_num_annotators_per_item_is_refused(self):
        with pytest.raises(ConfigValidationError) as exc:
            validate_optional_field_types({
                "num_annotators_per_item": 5,
                "min_annotators_per_instance": 3,
            })
        assert "5" in str(exc.value) and "3" in str(exc.value)

    def test_disagreeing_with_the_structured_default_is_refused(self):
        with pytest.raises(ConfigValidationError):
            validate_optional_field_types({
                "num_annotators_per_item": {"default": 5},
                "min_annotators_per_instance": 3,
            })

    def test_disagreeing_with_the_other_legacy_key_is_refused(self):
        with pytest.raises(ConfigValidationError):
            validate_optional_field_types({
                "max_annotations_per_item": 5,
                "min_annotators_per_instance": 3,
            })

    def test_agreeing_is_allowed(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            validate_optional_field_types({
                "num_annotators_per_item": 3,
                "min_annotators_per_instance": 3,
            })

    def test_zero_is_refused(self):
        # Rejected here rather than resolving to "retire immediately".
        with pytest.raises(ConfigValidationError):
            validate_optional_field_types({"min_annotators_per_instance": 0})


class TestTheRenameIsAudible:
    def test_it_warns_that_the_key_is_deprecated(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            validate_optional_field_types({"min_annotators_per_instance": 3})
        assert any(issubclass(w.category, DeprecationWarning)
                   and "min_annotators_per_instance" in str(w.message)
                   for w in caught), [str(w.message) for w in caught]

    def test_the_log_says_the_behaviour_changed(self, caplog):
        # Someone upgrading needs to learn that items now retire, from the
        # log rather than from a coverage count months later.
        with caplog.at_level("WARNING"), warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            validate_optional_field_types({"min_annotators_per_instance": 3})
        assert "retire" in caplog.text


class TestTheNestedFloorIsUntouched:
    """`num_annotators_per_item.min` cannot be an alias for the mapping it
    lives in, so it keeps the not-enforced warning."""

    def test_nested_min_still_warns(self, caplog):
        with caplog.at_level("WARNING"):
            warn_unenforced_coverage_floor(
                {"num_annotators_per_item": {"default": 5, "min": 3}})
        assert "num_annotators_per_item.min is not enforced" in caplog.text

    def test_the_flat_key_no_longer_warns_about_enforcement(self, caplog):
        # It IS enforced now; the old warning would be false.
        with caplog.at_level("WARNING"):
            warn_unenforced_coverage_floor({"min_annotators_per_instance": 3})
        assert "not enforced" not in caplog.text


class TestTheManagerRetiresAtTheNumber:
    """The end of the chain: the cap the assigner actually applies."""

    def test_the_manager_caps_at_the_deprecated_number(self):
        from potato.item_state_management import (
            ItemStateManager, clear_item_state_manager)

        clear_item_state_manager()
        try:
            manager = ItemStateManager({"min_annotators_per_instance": 3})
            assert manager.max_annotations_per_item == 3
        finally:
            clear_item_state_manager()

    def test_it_no_longer_lands_on_the_dead_attribute(self):
        from potato.item_state_management import (
            ItemStateManager, clear_item_state_manager)

        clear_item_state_manager()
        try:
            manager = ItemStateManager({"min_annotators_per_instance": 3})
            assert manager.min_annotations_per_item is None
        finally:
            clear_item_state_manager()


class TestTheIclKeyOfTheSameNameIsUntouched:
    """`icl_labeling.example_selection.min_annotators_per_instance` is a
    different setting that happens to share the name: how many annotators
    an item needs before it can serve as an in-context example. Two
    bundled examples set it. Reading it as a per-item cap would rewrite
    their coverage.
    """

    ICL = {
        "icl_labeling": {
            "example_selection": {
                "min_agreement_threshold": 0.8,
                "min_annotators_per_instance": 2,
            }
        }
    }

    def test_it_does_not_become_the_cap(self):
        assert resolve_num_annotators_per_item(dict(self.ICL)) == -1

    def test_it_does_not_conflict_with_the_top_level_key(self):
        config = dict(self.ICL)
        config["num_annotators_per_item"] = 5
        validate_optional_field_types(config)
        assert resolve_num_annotators_per_item(config) == 5

    def test_it_does_not_warn(self, caplog):
        with caplog.at_level("WARNING"):
            warn_unenforced_coverage_floor(dict(self.ICL))
        assert "min_annotators_per_instance" not in caplog.text

    def test_the_bundled_examples_still_load(self):
        """The two configs that set it, read from disk."""
        import yaml

        for path in ("examples/custom-layouts/icl-labeling/config.yaml",
                     "examples/advanced/active-learning-llm-cold-start/config.yaml"):
            config = yaml.safe_load(pathlib.Path(path).read_text())
            nested = (config.get("icl_labeling") or {}).get("example_selection") or {}
            assert nested.get("min_annotators_per_instance") is not None, path
            assert "min_annotators_per_instance" not in config, path
            validate_optional_field_types(config)

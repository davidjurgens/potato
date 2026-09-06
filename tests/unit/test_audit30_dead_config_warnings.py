"""
Config keys that will never be read must say so at load.

Three cases, all found by driving a study rather than by a failing test,
and all sharing a shape: the config validates, the server boots, and the
half that works is what convinces the author the whole thing took effect.

- `per_annotator_quota.default` makes `max_annotations_per_user`
  unreachable for every annotator. The two keys DO compose when
  `default` is absent, so the warning is about `default`, not the block.
- `batch_assignment.groups` item lists are only read under
  `assignment_strategy: batch`, but the groups' `schemes` binding is
  honoured under any strategy. Cohorts visibly answering different
  questions reads as proof, while every annotator is served every item.
- `min_annotators_per_instance` (and the structured
  `num_annotators_per_item.min`) is assigned in three places and read in
  none. It reads as the floor to `num_annotators_per_item`'s ceiling, so
  an author setting both believes coverage is bracketed. It is not.
- Static `category_based` grants qualifications only by passing a
  training phase, so with no training block nobody ever qualifies and a
  categorised item is never a candidate for anyone.

Each test pairs the warning with the config that must stay silent. A
warning that fires on a legitimate config is worse than no warning: it
teaches authors to skim the log -- and `--strict` makes every warning
fatal, so a false positive refuses a correct config outright.

These are `warn_*`, deliberately not `validate_*`: the module already has
`validate_batch_assignment_config` and `validate_category_assignment_config`,
which RAISE on a malformed block. Two families, two prefixes, so a later
check lands in the right one.
"""

import pytest

from potato.server_utils import config_module


def _warnings(caplog):
    return [r.message for r in caplog.records if r.levelname == "WARNING"]


class TestQuotaShadowing:
    def test_default_shadows_the_global(self, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_unreachable_quota_keys({
                "per_annotator_quota": {"default": 5},
                "max_annotations_per_user": 20,
            })
        msgs = _warnings(caplog)
        assert any("max_annotations_per_user" in m
                   and "per_annotator_quota.default" in m for m in msgs), msgs

    def test_the_two_keys_compose_without_a_default(self, caplog):
        """by_user/by_user_role fall through to the global, which is a
        correct config and must not be warned about."""
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_unreachable_quota_keys({
                "per_annotator_quota": {"by_user": {"alice": 3},
                                        "by_user_role": {"expert": 7}},
                "max_annotations_per_user": 20,
            })
        assert not any("never be read" in m for m in _warnings(caplog))

    def test_a_misspelled_role_name_is_flagged(self, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_unreachable_quota_keys({
                "per_annotator_quota": {"by_user_role": {"exprt": 7}},
                "user_roles": {"alice": "expert", "bob": "expert"},
            })
        msgs = _warnings(caplog)
        assert any("'expert'" in m and "'exprt'" in m for m in msgs), msgs

    def test_a_role_that_deliberately_takes_the_default_is_silent(
            self, caplog):
        """`--strict` makes warnings fatal, so a role that simply has no
        quota rule must not be warned about: falling through to the
        default is a correct config, not a near miss."""
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_unreachable_quota_keys({
                "per_annotator_quota": {"by_user_role": {"expert": 7}},
                "user_roles": {"alice": "expert", "carol": "novice"},
            })
        assert _warnings(caplog) == []

    def test_every_role_named_is_silent(self, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_unreachable_quota_keys({
                "per_annotator_quota": {"by_user_role": {"expert": 7,
                                                         "novice": 5}},
                "user_roles": {"alice": "expert", "carol": "novice"},
            })
        assert _warnings(caplog) == []


class TestBatchGroups:
    _GROUPS = [{"name": "g1", "annotators": ["alice"],
                "instances": ["i1", "i2"]}]

    def test_item_lists_under_the_wrong_strategy_are_flagged(self, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_batch_groups_need_the_batch_strategy({
                "batch_assignment": {"groups": self._GROUPS}})
        msgs = _warnings(caplog)
        assert any("'g1'" in m and "assignment_strategy: batch" in m
                   for m in msgs), msgs

    def test_silent_under_the_batch_strategy(self, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_batch_groups_need_the_batch_strategy({
                "assignment_strategy": "batch",
                "batch_assignment": {"groups": self._GROUPS}})
        assert _warnings(caplog) == []

    def test_a_schemes_only_group_is_legitimate_under_any_strategy(
            self, caplog):
        """Binding a cohort's questions without splitting the items is a
        real config; warning about it would be noise."""
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_batch_groups_need_the_batch_strategy({
                "batch_assignment": {"groups": [
                    {"name": "g1", "annotators": ["alice"],
                     "schemes": "detailed"}]}})
        assert _warnings(caplog) == []


class TestCategoryAssignment:
    def test_no_training_and_no_dynamic_is_flagged(self, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_category_assignment_cannot_qualify({
                "assignment_strategy": "category_based",
                "category_assignment": {"enabled": True,
                                        "fallback": "uncategorized"}})
        msgs = _warnings(caplog)
        assert any("no annotator will ever qualify" in m for m in msgs), msgs

    def test_the_consequence_named_matches_the_fallback(self, caplog):
        """`fallback: none` means literally nothing is served; saying
        'only uncategorized items' there would be wrong."""
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_category_assignment_cannot_qualify({
                "assignment_strategy": "category_based",
                "category_assignment": {"enabled": True, "fallback": "none"}})
        msgs = _warnings(caplog)
        assert any("served anything at all" in m for m in msgs), msgs

    def test_silent_with_dynamic_expertise(self, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_category_assignment_cannot_qualify({
                "assignment_strategy": "category_based",
                "category_assignment": {"dynamic": {"enabled": True}}})
        assert _warnings(caplog) == []

    def test_silent_with_a_training_phase(self, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_category_assignment_cannot_qualify({
                "assignment_strategy": "category_based",
                "training": {"data_files": ["train.json"]},
                "category_assignment": {"enabled": True}})
        assert _warnings(caplog) == []

    def test_silent_under_another_strategy(self, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_category_assignment_cannot_qualify({
                "assignment_strategy": "random",
                "category_assignment": {"enabled": True}})
        assert _warnings(caplog) == []


class TestCoverageFloor:
    """`min_annotators_per_instance` is inert. Until it is implemented or
    removed, the config must say so rather than accept a guarantee the
    software never made."""

    def test_the_legacy_spelling_is_flagged(self, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_unenforced_coverage_floor(
                {"min_annotators_per_instance": 3})
        msgs = _warnings(caplog)
        assert any("min_annotators_per_instance is not enforced" in m
                   for m in msgs), msgs

    def test_the_structured_spelling_is_flagged(self, caplog):
        """`num_annotators_per_item.min` reaches the same unread
        attribute, so the same config is inert written either way."""
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_unenforced_coverage_floor(
                {"num_annotators_per_item": {"default": 5, "min": 3}})
        msgs = _warnings(caplog)
        assert any("num_annotators_per_item.min is not enforced" in m
                   for m in msgs), msgs

    @pytest.mark.parametrize("nap", [
        {"num_annotators_per_item": 3},
        {"num_annotators_per_item": {"default": 5}},
        {},
    ])
    def test_a_config_without_a_floor_is_silent(self, nap, caplog):
        with caplog.at_level("WARNING", logger="potato.server_utils.config_module"):
            config_module.warn_unenforced_coverage_floor(nap)
        assert _warnings(caplog) == []

"""Unit tests for the search.annotator_claim x assignment compat guard."""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_search_assignment_compat as guard,
)

CLAIM = {"search": {"annotator_claim": True}}


def _cfg(**extra):
    c = {"search": {"annotator_claim": True}}
    c.update(extra)
    return c


class TestAllowed:
    def test_no_claim_never_raises(self):
        guard({"search": {"annotator_claim": False},
               "assignment_strategy": "random",
               "max_annotations_per_item": 5})  # no raise

    def test_no_search_block(self):
        guard({"assignment_strategy": "random"})

    def test_fixed_order_no_overlap_ok(self):
        guard(_cfg(assignment_strategy="fixed_order"))

    def test_claim_with_default_strategy_ok(self):
        guard(_cfg())  # no assignment_strategy at all

    def test_solo_mode_exempt_even_with_random(self):
        guard(_cfg(assignment_strategy="random",
                   solo_mode={"enabled": True}))

    def test_qda_mode_exempt_even_with_overlap(self):
        guard(_cfg(max_annotations_per_item=5,
                   qda_mode={"enabled": True}))

    def test_max_annotations_one_is_ok(self):
        guard(_cfg(max_annotations_per_item=1))


class TestBlocked:
    def _assert_blocks(self, cfg, needle):
        with pytest.raises(ConfigValidationError) as e:
            guard(cfg)
        assert needle in str(e.value)

    def test_random_strategy(self):
        self._assert_blocks(_cfg(assignment_strategy="random"),
                            "assignment_strategy")

    def test_strategy_as_dict(self):
        self._assert_blocks(
            _cfg(assignment_strategy={"name": "active_learning"}),
            "active_learning")

    def test_overlap_max_annotations(self):
        self._assert_blocks(_cfg(max_annotations_per_item=3),
                            "max_annotations_per_item")

    def test_overlap_num_annotators(self):
        self._assert_blocks(_cfg(num_annotators_per_item=2),
                            "num_annotators_per_item")

    def test_attention_checks(self):
        self._assert_blocks(_cfg(attention_checks={"enabled": True}),
                            "attention_checks")

    def test_gold_standards(self):
        self._assert_blocks(_cfg(gold_standards={"enabled": True}),
                            "gold_standards")

    def test_icl_labeling(self):
        self._assert_blocks(_cfg(icl_labeling={"enabled": True}),
                            "icl_labeling")

    def test_adjudication(self):
        self._assert_blocks(_cfg(adjudication={"enabled": True}),
                            "adjudication")

    def test_mturk_backend(self):
        self._assert_blocks(_cfg(mturk={"hit_id": "x"}), "crowdsourcing")

    def test_prolific_login(self):
        self._assert_blocks(_cfg(login={"type": "prolific"}),
                            "crowdsourcing")

    def test_multiple_conflicts_all_listed(self):
        with pytest.raises(ConfigValidationError) as e:
            guard(_cfg(assignment_strategy="random",
                       gold_standards={"enabled": True},
                       adjudication={"enabled": True}))
        msg = str(e.value)
        assert "assignment_strategy" in msg
        assert "gold_standards" in msg
        assert "adjudication" in msg

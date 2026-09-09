"""MACE competence numbers ship with the reasons not to trust them.

The algorithm is right in the regime it is designed for. Measured on 200
balanced items with four genuine annotators and one constant spammer,
competence tracked true accuracy to about 0.01 and the spammer ranked last.

It is wrong in a regime a lot of annotation studies live in. MACE explains an
answer as "trying" or "spamming from a fixed strategy", so a spammer whose
fixed strategy IS the majority class is nearly unidentifiable by construction.
From a 40-trial-per-cell sweep:

    prior     items   spammer ranked last
    50/50        30           95%
    50/50       300          100%
    67/33        30           75%
    67/33       300          100%
    80/20        30           32%
    80/20       300           10%      <- worse than at 30 items

On one 300-item draw at 4:1 an annotator who never looked at an item tied for
the highest competence in the study, and MACE's aggregate (0.940) came in below
plain majority vote (0.987).

That is the model, not the implementation, and this does not try to fix it.
What it fixes is that `/admin/api/mace/overview` returned `has_results: true`
and a per-annotator number with nothing about the item count, the label
distribution, or whether any of it was reliable -- while the registry entry
promises reliability is inferred "from the disagreement pattern alone".

Two of the three checks need no model at all: a constant-response annotator is
found by looking at their answers, and skew is a count. Both are cheap, and
both describe exactly where the competence numbers are most confidently wrong.
"""

import numpy as np
import pytest

from potato.mace_manager import _assess_reliability


IDX = {0: "no", 1: "yes"}


def matrix(columns):
    """An items x annotators matrix from per-annotator answer lists."""
    return np.array(columns, dtype=int).T


def assess(m, annotators=None, min_items=5):
    annotators = annotators or [f"a{i}" for i in range(m.shape[1])]
    return _assess_reliability(m, annotators, IDX, min_items, "s")


class TestAConstantAnnotatorIsNamed:

    def test_they_are_found_without_the_model(self):
        m = matrix([[0, 1, 0, 1] * 10, [0] * 40])
        report = assess(m, ["genuine", "spammer"])
        assert [c["user_id"] for c in report["constant_annotators"]] == \
            ["spammer"]

    def test_the_answer_and_the_count_are_reported(self):
        m = matrix([[0, 1] * 20, [1] * 40])
        entry = assess(m, ["genuine", "spammer"])["constant_annotators"][0]
        assert entry["answer"] == "yes" and entry["items"] == 40

    def test_a_varied_annotator_is_not_flagged(self):
        m = matrix([[0, 1] * 20, [0, 0, 0, 1] * 10])
        assert assess(m, ["a", "b"])["constant_annotators"] == []

    def test_a_single_answer_is_not_evidence_of_anything(self):
        """One item is not a pattern; flagging it would be noise."""
        m = np.full((40, 2), -1, dtype=int)
        m[:, 0] = [0, 1] * 20
        m[0, 1] = 1
        assert assess(m, ["a", "b"])["constant_annotators"] == []

    def test_only_the_items_they_answered_are_counted(self):
        m = np.full((40, 2), -1, dtype=int)
        m[:, 0] = [0, 1] * 20
        m[:10, 1] = 0
        entry = assess(m, ["a", "spammer"])["constant_annotators"][0]
        assert entry["items"] == 10


class TestSkewIsReported:

    def test_a_skewed_corpus_is_flagged(self):
        m = matrix([[0] * 90 + [1] * 10, [0] * 88 + [1] * 12])
        report = assess(m)
        assert report["majority_label_share"] > 0.75
        assert any("skew" in w or "majority class" in w
                   for w in report["warnings"]), (
            "the regime where a constant annotator outranks a real one was "
            "not mentioned beside the numbers")

    def test_a_balanced_corpus_is_not_flagged_for_skew(self):
        m = matrix([[0, 1] * 20, [0, 1, 1, 0] * 10])
        assert not any("majority class" in w for w in assess(m)["warnings"])

    def test_the_label_counts_are_reported(self):
        m = matrix([[0] * 30 + [1] * 10])
        assert assess(m)["label_counts"] == {"no": 30, "yes": 10}

    def test_unanswered_cells_are_not_counted_as_a_label(self):
        m = np.full((40, 2), -1, dtype=int)
        m[:, 0] = [0] * 40
        assert assess(m, ["a", "b"])["num_answers"] == 40


class TestSampleSizeIsReported:

    def test_a_small_fit_is_flagged(self):
        m = matrix([[0, 1] * 3, [0, 1, 1, 0, 0, 1]])
        assert any("item" in w for w in assess(m)["warnings"]), (
            "`min_items` defaults to 5, and a competence score off five items "
            "is not a basis for a decision about a person")

    def test_a_large_balanced_fit_is_clean(self):
        rng = np.random.default_rng(0)
        truth = (rng.random(300) < 0.5).astype(int)
        columns = []
        for accuracy in (0.95, 0.90, 0.85):
            flip = rng.random(300) > accuracy
            columns.append(np.where(flip, 1 - truth, truth))
        report = assess(np.array(columns, dtype=int).T)
        assert report["trustworthy"] is True
        assert report["warnings"] == []

    def test_the_configured_minimum_is_reported(self):
        assert assess(matrix([[0, 1] * 20, [0] * 40]),
                      min_items=17)["min_items_configured"] == 17


class TestTheRegimeTheSweepFound:
    """A 4:1 corpus with a majority-class spammer: the case where MACE is
    confidently wrong and every earlier version of this API said nothing."""

    def _skewed(self):
        rng = np.random.default_rng(0)
        truth = (rng.random(300) < 0.2).astype(int)
        columns = []
        for accuracy in (0.95, 0.90, 0.85, 0.80):
            flip = rng.random(300) > accuracy
            columns.append(np.where(flip, 1 - truth, truth))
        columns.append(np.zeros(300, dtype=int))  # constant majority answer
        return np.array(columns, dtype=int).T

    def test_it_is_not_reported_as_trustworthy(self):
        report = assess(self._skewed(),
                        ["a", "b", "c", "d", "spammer"])
        assert report["trustworthy"] is False

    def test_both_reasons_are_given(self):
        report = assess(self._skewed(), ["a", "b", "c", "d", "spammer"])
        joined = " ".join(report["warnings"])
        assert "majority class" in joined
        assert "spammer" in joined

    def test_more_data_does_not_clear_the_flag(self):
        """The sweep's counterintuitive result: at 4:1 the ranking gets WORSE
        with more items, so sample size must not silence the skew warning."""
        report = assess(self._skewed(), ["a", "b", "c", "d", "spammer"])
        assert any("majority class" in w for w in report["warnings"])

"""Overlapping spans count in span agreement.

The BIO conversion kept the longest span where spans overlapped and dropped
the rest, so a coder who applied two codes to a passage agreed perfectly with
one who applied only the longer code.
"""

import math

from potato.server_utils.iaa import span

BOTH = [(0, 10, "PER"), (5, 8, "ORG")]
LONGER_ONLY = [(0, 10, "PER")]


def test_an_overlap_keeps_both_labels():
    tags = span.spans_to_bio(BOTH, 12)
    assert tags[:5] == ["B-PER"] + ["I-PER"] * 4
    assert tags[5:8] == ["B-ORG+PER", "I-ORG+PER", "I-ORG+PER"]
    assert tags[8:10] == ["B-PER", "I-PER"]
    assert tags[10:] == ["O", "O"]


def test_the_dropped_code_is_a_disagreement():
    users = {"a": BOTH, "b": LONGER_ONLY}
    assert span.positional_alpha(users, 12) < 1.0
    assert span.token_level_kappa(users, 12) < 1.0


def test_the_same_overlapping_codes_agree():
    users = {"a": BOTH, "b": list(reversed(BOTH))}
    assert span.positional_alpha(users, 12) == 1.0
    assert span.token_level_kappa(users, 12) == 1.0


def test_adjacent_spans_of_one_label_stay_two_spans():
    tags = span.spans_to_bio([(0, 3, "PER"), (3, 6, "PER")], 6)
    assert tags == ["B-PER", "I-PER", "I-PER", "B-PER", "I-PER", "I-PER"]

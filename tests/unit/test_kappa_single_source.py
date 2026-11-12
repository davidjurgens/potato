"""
One Cohen's kappa: the paper report, the agreement module and the IAA report
compute it through ``iaa.nominal.cohen_kappa``.

Checked against a textbook formula written out here, not against the shared
function, so the test still means something if that function changes.
"""

import random

import pandas as pd
import pytest

from potato.agreement import cohen_kappa_pairwise
from potato.paper.metrics import cohen_kappa as paper_kappa
from potato.server_utils.iaa.nominal import cohen_kappa as iaa_kappa


def textbook_kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    cats = set(a) | set(b)
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return None if pe == 1 else (po - pe) / (1 - pe)


@pytest.mark.parametrize("seed", range(8))
def test_all_three_match_the_textbook(seed):
    rng = random.Random(seed)
    labels = ["pos", "neg", "neu"][: rng.choice([2, 3])]
    a = [rng.choice(labels) for _ in range(40)]
    b = [x if rng.random() < 0.7 else rng.choice(labels) for x in a]
    want = textbook_kappa(a, b)
    assert paper_kappa(list(zip(a, b))) == pytest.approx(want)
    assert iaa_kappa(a, b) == pytest.approx(want)
    df = pd.DataFrame([{"unit": i, "annotator": "u1", "annotation": x} for i, x in enumerate(a)]
                      + [{"unit": i, "annotator": "u2", "annotation": y} for i, y in enumerate(b)])
    assert cohen_kappa_pairwise(df)["mean_kappa"] == pytest.approx(want, abs=1e-4)


def test_one_label_throughout_is_undefined_not_perfect():
    pairs = [("pos", "pos")] * 10
    assert paper_kappa(pairs) is None
    assert paper_kappa([]) is None

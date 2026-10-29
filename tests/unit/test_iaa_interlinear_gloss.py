"""
Agreement for interlinear_gloss, through the overlap-IAA report.

The scheme used to have no entry in the dispatcher, so /admin/iaa reported
nothing for it, and /admin/api/agreement reduced the stored blob to the scheme
name and reported perfect agreement for any two annotators. Each line of the
analysis is now scored separately; see potato/server_utils/iaa/glossing.py.
"""

from __future__ import annotations

import json

from potato.server_utils.iaa import dispatcher
from tests.unit.test_iaa_dispatcher_gathering import run_report

SCHEME = {"annotation_type": "interlinear_gloss", "name": "igt", "tiers": ["pos"]}


def answer(*words, translation=""):
    """Words as (word, morphemes, gloss, pos) tuples."""
    return {("igt", "igt"): json.dumps({
        "words": [{"word": w, "morphemes": m, "gloss": g, "pos": p} for w, m, g, p in words],
        "translation": translation,
    })}


# Two sentences, so alpha has more than one unit and more than one value.
S1 = [("evlerde", "ev-ler-de", "house-PL-LOC", "N"), ("oturuyorum", "otur-uyor-um", "sit-PROG-1SG", "V")]
S2 = [("kitap", "kitap", "book", "N"), ("okudum", "oku-du-m", "read-PST-1SG", "V")]


def test_classified_as_gloss():
    assert dispatcher.classify_schema(SCHEME) == dispatcher.SchemaKind.GLOSS


def test_identical_analyses_agree_on_every_line():
    both = {"i1": answer(*S1), "i2": answer(*S2)}
    m = run_report({"a": both, "b": both}, SCHEME)
    assert m["n_items"] == 2 and m["n_annotators"] == 2
    for layer in ("segmentation", "gloss", "morpheme_gloss", "tier_pos"):
        assert m[layer]["percent_agreement"] == 1.0, layer
    assert m["segmentation"]["alpha"] == 1.0
    assert m["gloss"]["n_units"] == 4
    # 3 + 3 + 1 + 3 morphemes.
    assert m["morpheme_gloss"]["n_units"] == 10


def test_disagreeing_glosses_lower_gloss_but_not_segmentation():
    other = [("evlerde", "ev-ler-de", "home-PL-LOC", "N"), ("oturuyorum", "otur-uyor-um", "live-PROG-1SG", "V")]
    m = run_report({"a": {"i1": answer(*S1), "i2": answer(*S2)},
                    "b": {"i1": answer(*other), "i2": answer(*S2)}}, SCHEME)
    assert m["segmentation"]["percent_agreement"] == 1.0
    assert m["gloss"]["percent_agreement"] == 0.5
    assert m["gloss"]["alpha"] < 1.0
    # Only the stems differ: 2 of the 10 morphemes.
    assert m["morpheme_gloss"]["percent_agreement"] == 0.8


def test_morpheme_glosses_skip_words_segmented_differently():
    resegmented = [("evlerde", "evler-de", "house.PL-LOC", "N"), S1[1]]
    m = run_report({"a": {"i1": answer(*S1), "i2": answer(*S2)},
                    "b": {"i1": answer(*resegmented), "i2": answer(*S2)}}, SCHEME)
    assert m["segmentation"]["percent_agreement"] == 0.75
    # evlerde is left out; positions there would compare "house" with
    # "house.PL" and charge the segmentation split to the gloss.
    assert m["morpheme_gloss"]["n_units"] == 7
    assert m["morpheme_gloss"]["percent_agreement"] == 1.0


def test_empty_cells_are_unanswered_not_agreement():
    blank = [(w, "", "", "") for w, *_ in S1]
    m = run_report({"a": {"i1": answer(*blank)}, "b": {"i1": answer(*blank)}}, SCHEME)
    assert m["gloss"]["n_units"] == 0
    assert m["gloss"]["percent_agreement"] is None


"""
The `embedding` caption distance, against a REAL sentence-transformers model.

Everything else about caption agreement is tested with a stub, deliberately: the
suite must not download a model, and importing sentence-transformers on the boot
path is what invariant 6 forbids. But a stub can only prove the *wiring* — that
the callable is asked for and its answer is used. It cannot prove the claim the
whole feature rests on, which is that embeddings actually rate a paraphrase as
close when the default token distance rates it as maximally far apart.

So this file is **opt-in twice**: it needs sentence-transformers installed AND
`POTATO_TEST_EMBEDDINGS=1` in the environment. Both conditions must be explicit,
because a test that quietly downloads ~90 MB the first time someone runs `pytest`
is a bad citizen even when the assertion is sound.

    POTATO_TEST_EMBEDDINGS=1 pytest tests/unit/test_caption_embedding_distance.py -v

Skipped otherwise, and the skip reason says which switch is off — a silently
absent test is indistinguishable from a passing one.
"""

import importlib.util
import os

import pytest

from potato.server_utils.iaa import captions as C

MODEL = "all-MiniLM-L6-v2"

_HAVE_PACKAGE = importlib.util.find_spec("sentence_transformers") is not None
_OPTED_IN = os.environ.get("POTATO_TEST_EMBEDDINGS") == "1"

pytestmark = [
    pytest.mark.skipif(not _HAVE_PACKAGE,
                       reason="sentence-transformers is not installed"),
    pytest.mark.skipif(not _OPTED_IN,
                       reason="set POTATO_TEST_EMBEDDINGS=1 to run against a "
                              "real model (may download one)"),
]

#: Pairs that mean the same thing and share no content word. These are the whole
#: argument for the feature: the default token distance scores every one of them
#: as 1.0, complete disagreement, which is wrong.
PARAPHRASES = [
    ("a man in a red shirt", "person wearing a crimson top"),
    ("a small dog on the grass", "a puppy in the lawn"),
    ("two people talking", "a pair of individuals conversing"),
]

#: Pairs that genuinely describe different things.
DIFFERENT = [
    ("a man in a red shirt", "an empty parking lot at night"),
    ("a small dog on the grass", "a plate of spaghetti"),
]


@pytest.fixture(scope="module")
def distance():
    fn = C.embedding_distance_fn(MODEL)
    if fn is None:
        pytest.skip(f"the model {MODEL} could not be loaded")
    return fn


class TestTheClaimTheFeatureRestsOn:
    """
    What matters is SEPARATION, not an absolute threshold.

    Running this against a real model corrected an assumption. The documented
    flagship example scores **0.598** with `all-MiniLM-L6-v2` — the embedding
    distance does not consider "a man in a red shirt" and "person wearing a
    crimson top" to be nearly the same sentence. Substituting both the colour
    word and the garment word is genuinely hard for a small model.

    An absolute assertion like `< 0.5` would therefore have failed on the very
    example the docs use, and tightening the threshold until it passed would
    have been fitting the test to one model. What alpha actually needs is that
    paraphrases land closer than unrelated captions, by a margin — which holds
    comfortably (0.13–0.60 against 0.97–1.00) and is the property that survives
    changing the model.
    """

    @pytest.mark.parametrize("a,b", PARAPHRASES)
    def test_the_token_distance_gets_these_completely_wrong(self, a, b):
        """
        The control. Without it, the separation test below proves only that some
        numbers differ — not that the default was inadequate, which is the whole
        reason the option exists.
        """
        assert C.token_distance(a, b) == pytest.approx(1.0), (
            "the token distance no longer scores this paraphrase as total "
            "disagreement, so it is no longer the example to use in the docs")

    def test_every_paraphrase_is_closer_than_every_unrelated_pair(self, distance):
        """The separation that makes alpha mean something. No overlap allowed."""
        paraphrase = {(a, b): distance(a, b) for a, b in PARAPHRASES}
        unrelated = {(a, b): distance(a, b) for a, b in DIFFERENT}
        assert max(paraphrase.values()) < min(unrelated.values()), (
            f"paraphrases and unrelated captions overlap:\n"
            f"  paraphrases: {paraphrase}\n"
            f"  unrelated:   {unrelated}")

    @pytest.mark.parametrize("a,b", PARAPHRASES)
    def test_paraphrases_are_at_least_meaningfully_closer_than_the_default(
            self, distance, a, b):
        """
        Loose on purpose. The token distance calls every one of these 1.0, so
        anything materially below that is information the default cannot
        provide — and pinning a tighter bound would encode this one model's
        behaviour as a requirement.
        """
        assert distance(a, b) < 0.7

    @pytest.mark.parametrize("a,b", DIFFERENT)
    def test_genuinely_different_captions_stay_far_apart(self, distance, a, b):
        """
        A δ that returned "close" for everything would pass the tests above and
        make alpha meaningless. Both directions have to hold.
        """
        assert distance(a, b) > 0.9


class TestItIsAUsableDistance:
    def test_identical_text_is_zero(self, distance):
        assert distance("a red mug on a table", "a red mug on a table") == \
            pytest.approx(0.0, abs=1e-5)

    def test_symmetric(self, distance):
        a, b = PARAPHRASES[0]
        assert distance(a, b) == pytest.approx(distance(b, a), abs=1e-6)

    @pytest.mark.parametrize("a,b", PARAPHRASES + DIFFERENT + [("", "")])
    def test_bounded_to_the_unit_interval(self, distance, a, b):
        """
        Alpha's arithmetic is meaningless outside [0, 1]. Cosine over normalized
        vectors runs to -1, so the clamp in embedding_distance_fn is load-bearing
        and not decoration.
        """
        value = distance(a, b)
        assert 0.0 <= value <= 1.0

    def test_empty_against_text_does_not_raise(self, distance):
        assert 0.0 <= distance("", "a red mug") <= 1.0


class TestItReachesAlpha:
    def test_alpha_reports_the_distance_it_actually_used(self):
        """
        The failure this catches is silent: a fallback to the token distance
        that still reports "embedding" would publish a number computed one way
        under the name of another.
        """
        rows = [
            ("alice", "item1", "a man in a red shirt"),
            ("bob", "item1", "person wearing a crimson top"),
            ("alice", "item2", "an empty road"),
            ("bob", "item2", "a deserted street"),
        ]
        result = C.caption_alpha(rows, distance="embedding", model_name=MODEL)
        assert result["distance_requested"] == "embedding"
        assert result["distance_used"] == "embedding"

    def test_embeddings_find_agreement_the_token_distance_cannot(self):
        """
        End to end, on the same data: two annotators who paraphrased each other
        agree, and only the embedding distance can see it.

        The token distance makes every pair maximally distant, so the observed
        disagreement equals the expected disagreement and alpha is 0 or
        undefined. That is not a subtle difference in a coefficient — it is the
        difference between "these annotators disagree completely" and "these
        annotators agree", reported about identical data.
        """
        rows = [
            ("alice", "item1", "a man in a red shirt"),
            ("bob", "item1", "person wearing a crimson top"),
            ("alice", "item2", "a small dog on the grass"),
            ("bob", "item2", "a puppy in the lawn"),
            ("alice", "item3", "an empty parking lot at night"),
            ("bob", "item3", "a plate of spaghetti"),
        ]
        embedding = C.caption_alpha(rows, distance="embedding", model_name=MODEL)
        token = C.caption_alpha(rows, distance="token")

        assert embedding["mean_pairwise_distance"] < \
            token["mean_pairwise_distance"], (
            "the embedding distance did not bring the paraphrases closer than "
            "the token distance did — the feature is not doing anything")

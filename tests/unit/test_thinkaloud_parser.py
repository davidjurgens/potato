"""Unit tests for the Think-Aloud rule-based label-phrase parser."""

import pytest

from potato.thinkaloud.parser import LabelPhraseParser, count_fillers, normalize

LABELS = ["Polite", "Neutral", "Impolite"]


@pytest.fixture()
def parser():
    return LabelPhraseParser(LABELS)


class TestNormalize:
    def test_strips_punctuation_and_case(self):
        assert normalize("I label this, POLITE!") == "i label this polite"

    def test_collapses_whitespace(self):
        assert normalize("a   b\t c") == "a b c"


class TestStemDetection:
    @pytest.mark.parametrize("utterance,expected", [
        ("I label this polite", "Polite"),
        ("I label this as impolite", "Impolite"),
        ("i'd call this neutral", "Neutral"),
        ("I would mark that as polite", "Polite"),
        ("my answer is impolite", "Impolite"),
        ("My rating is neutral, I think.", "Neutral"),
        ("final answer: polite", "Polite"),
        ("The final answer is neutral", "Neutral"),
        ("I choose impolite", "Impolite"),
        ("I go with polite", "Polite"),
        ("label it neutral", "Neutral"),
        ("I classify this one as impolite", "Impolite"),
        ("this is definitely impolite", "Impolite"),
    ])
    def test_accepted_phrasings(self, parser, utterance, expected):
        detection = parser.parse(utterance)
        assert detection is not None, utterance
        assert detection.label == expected
        assert detection.confidence == "exact"

    def test_free_speech_without_stem_not_detected(self, parser):
        # Mentioning a label while thinking must NOT commit it
        assert parser.parse("hmm this seems quite polite to me but the "
                            "deadline mention is aggressive") is None

    def test_stem_without_valid_label_not_detected(self, parser):
        assert parser.parse("I label this bananas") is None

    def test_empty_and_none_safe(self, parser):
        assert parser.parse("") is None
        assert parser.parse("   ") is None


class TestLastWins:
    def test_mind_change(self, parser):
        detection = parser.parse(
            "I'd call this polite... no wait, actually my answer is neutral")
        assert detection.label == "Neutral"

    def test_later_stem_wins_across_patterns(self, parser):
        detection = parser.parse(
            "final answer polite. hmm. I label this impolite")
        assert detection.label == "Impolite"

    # A correction that REUSES the phrasing is the natural way people correct
    # themselves, and it lands inside the first match's greedy `rest` capture.
    # Every case below regressed while the cross-stem tests above still passed.
    def test_mind_change_reusing_the_same_stem(self, parser):
        detection = parser.parse("I label this polite. I label this neutral.")
        assert detection.label == "Neutral"

    def test_correcting_a_mishearing_does_not_keep_the_misheard_label(self, parser):
        # "in polite" fuzzy-matches Impolite; saying the label again must win,
        # otherwise the annotator is recorded as the label they corrected away from.
        detection = parser.parse("I label this in polite. I label this polite.")
        assert detection.label == "Polite"

    def test_last_of_several_same_stem_commitments_wins(self, parser):
        detection = parser.parse(
            "I label this polite. I label this impolite. I label this neutral.")
        assert detection.label == "Neutral"


class TestFuzzyMatching:
    def test_split_mishearing(self, parser):
        # Whisper often splits compounds: "impolite" -> "in polite"
        detection = parser.parse("I label this in polite")
        assert detection.label == "Impolite"
        assert detection.confidence in ("prefix", "fuzzy")

    def test_small_edit_distance(self, parser):
        detection = parser.parse("my answer is impolyte")
        assert detection.label == "Impolite"
        assert detection.confidence == "fuzzy"

    def test_multiword_labels(self):
        parser = LabelPhraseParser(["Strongly Agree", "Strongly Disagree"])
        detection = parser.parse("I label this strongly disagree")
        assert detection.label == "Strongly Disagree"
        assert detection.confidence == "exact"

    def test_fuzzy_does_not_cross_similar_labels(self, parser):
        # 'polite' must not fuzzy-match Impolite
        detection = parser.parse("I label this polite")
        assert detection.label == "Polite"
        assert detection.confidence == "exact"


class TestCustomStems:
    def test_yaml_provided_stem(self):
        parser = LabelPhraseParser(LABELS, stems=[r"verdict\s+"])
        assert parser.parse("verdict impolite").label == "Impolite"
        assert parser.parse("I label this impolite") is None


class TestDetectionMetadata:
    def test_matched_and_stem_text(self, parser):
        detection = parser.parse("okay so um I label this as impolite because wow")
        assert detection.matched_text == "impolite"
        assert "label this as" in detection.stem_text


class TestFillers:
    def test_counts_fillers(self):
        text = "um so I guess this is, um, hmm, maybe fine"
        assert count_fillers(text, ["um", "hmm", "i guess", "maybe"]) == 5

    def test_no_partial_word_matches(self):
        # 'um' must not match inside 'umbrella'
        assert count_fillers("the umbrella summary", ["um"]) == 0

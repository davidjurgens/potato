"""
Tests for NLP export utilities.
"""

import pytest
from potato.export.nlp_utils import (
    tokenize_text,
    char_spans_to_bio_tags,
    group_sentences,
)


class TestTokenizeText:
    def test_whitespace_tokenization(self):
        tokens = tokenize_text("Hello world foo")
        assert len(tokens) == 3
        assert tokens[0] == {"token": "Hello", "start": 0, "end": 5}
        assert tokens[1] == {"token": "world", "start": 6, "end": 11}
        assert tokens[2] == {"token": "foo", "start": 12, "end": 15}

    def test_empty_text(self):
        assert tokenize_text("") == []

    def test_whitespace_only(self):
        assert tokenize_text("   ") == []

    def test_multiple_spaces(self):
        tokens = tokenize_text("a   b")
        assert len(tokens) == 2
        assert tokens[0]["end"] == 1
        assert tokens[1]["start"] == 4

    def test_word_punct_tokenization(self):
        tokens = tokenize_text("Hello, world!", method="word_punct")
        token_strs = [t["token"] for t in tokens]
        assert "Hello" in token_strs
        assert "," in token_strs
        assert "world" in token_strs
        assert "!" in token_strs

    def test_offsets_are_correct(self):
        text = "The cat sat"
        tokens = tokenize_text(text)
        for tok in tokens:
            assert text[tok["start"]:tok["end"]] == tok["token"]


class TestCharSpansToBioTags:
    def test_no_spans(self):
        tokens = tokenize_text("Hello world")
        tags = char_spans_to_bio_tags(tokens, [])
        assert tags == ["O", "O"]

    def test_empty_tokens(self):
        assert char_spans_to_bio_tags([], []) == []

    def test_single_token_entity(self):
        tokens = tokenize_text("John likes cats")
        spans = [{"start": 0, "end": 4, "label": "PER"}]
        tags = char_spans_to_bio_tags(tokens, spans)
        assert tags == ["B-PER", "O", "O"]

    def test_multi_token_entity(self):
        tokens = tokenize_text("New York is great")
        spans = [{"start": 0, "end": 8, "label": "LOC"}]
        tags = char_spans_to_bio_tags(tokens, spans)
        assert tags == ["B-LOC", "I-LOC", "O", "O"]

    def test_multiple_entities(self):
        tokens = tokenize_text("John lives in New York")
        spans = [
            {"start": 0, "end": 4, "label": "PER"},
            {"start": 14, "end": 22, "label": "LOC"},
        ]
        tags = char_spans_to_bio_tags(tokens, spans)
        assert tags == ["B-PER", "O", "O", "B-LOC", "I-LOC"]

    def test_overlapping_spans_longest_wins(self):
        tokens = tokenize_text("New York City is nice")
        spans = [
            {"start": 0, "end": 13, "label": "LOC"},      # "New York City"
            {"start": 0, "end": 8, "label": "CITY"},       # "New York" (shorter)
        ]
        tags = char_spans_to_bio_tags(tokens, spans)
        # Longest first, so LOC wins for "New York City"
        assert tags == ["B-LOC", "I-LOC", "I-LOC", "O", "O"]

    def test_adjacent_entities(self):
        tokens = tokenize_text("JohnSmith")
        spans = [
            {"start": 0, "end": 4, "label": "FIRST"},
            {"start": 4, "end": 9, "label": "LAST"},
        ]
        # Single token "JohnSmith" can only get one tag
        tags = char_spans_to_bio_tags(tokens, spans)
        assert len(tags) == 1

    def test_span_with_name_field(self):
        """Spans can use 'name' instead of 'label'."""
        tokens = tokenize_text("John likes cats")
        spans = [{"start": 0, "end": 4, "name": "PER"}]
        tags = char_spans_to_bio_tags(tokens, spans)
        assert tags == ["B-PER", "O", "O"]

    def test_bioes_scheme(self):
        tokens = tokenize_text("John lives in New York")
        spans = [
            {"start": 0, "end": 4, "label": "PER"},
            {"start": 14, "end": 22, "label": "LOC"},
        ]
        tags = char_spans_to_bio_tags(tokens, spans, scheme="BIOES")
        assert tags[0] == "S-PER"        # Single-token entity
        assert tags[3] == "B-LOC"
        assert tags[4] == "E-LOC"        # End of multi-token entity


class TestGroupSentences:
    def test_single_sentence(self):
        tokens = tokenize_text("Hello world")
        sentences = group_sentences(tokens, "Hello world")
        assert len(sentences) == 1
        assert sentences[0] == [0, 1]

    def test_two_sentences(self):
        text = "Hello world. How are you?"
        tokens = tokenize_text(text)
        sentences = group_sentences(tokens, text)
        assert len(sentences) == 2

    def test_empty_tokens(self):
        assert group_sentences([], "") == []

    def test_no_sentence_boundary(self):
        text = "no punctuation here"
        tokens = tokenize_text(text)
        sentences = group_sentences(tokens, text)
        assert len(sentences) == 1
        assert len(sentences[0]) == 3

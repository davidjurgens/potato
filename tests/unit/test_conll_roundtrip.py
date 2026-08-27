"""
CoNLL export -> import, against the exporters that already shipped.

Potato wrote CoNLL-2003 and CoNLL-U and could read neither, so the most common
way to arrive with an existing NER corpus was to write a conversion script
first. This is the self-checking case for the new importer: the two exporters
are independent code we did not touch, so a round trip through them is a real
test rather than a reader agreeing with its own writer.

What is *not* asserted here is that the round trip is lossless in general. It
is not, and the reason is in the format: CoNLL records tokens and tags, never
spacing, so ``"Dr. Smith"`` and ``"Dr.  Smith"`` produce the same file. The
tests below draw the line where the loss actually falls -- at tokenization --
rather than pretending it is not there.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from potato.export.base import ExportContext
from potato.export.conll_2003_exporter import CoNLL2003Exporter
from potato.export.conll_u_exporter import CoNLLUExporter
from potato.importers.text.conll_importer import CoNLLImporter

#: Chosen so whitespace tokens and span boundaries coincide: every entity ends
#: at a space. Where they do NOT coincide the loss is real and is asserted
#: separately in TestTokenizationIsWhereItIsLossy.
TEXT = "Barack Obama visited Paris in April with Angela Merkel ."

ENTITIES = [
    {"name": "PER", "start": 0, "end": 12},    # Barack Obama
    {"name": "LOC", "start": 21, "end": 26},   # Paris
    {"name": "PER", "start": 40, "end": 53},   # Angela Merkel
]


def make_context(text=TEXT, spans=None, instance_id="doc1"):
    schemas = [{
        "annotation_type": "span",
        "name": "entities",
        "description": "entities",
        "labels": [{"name": "PER"}, {"name": "LOC"}],
    }]
    return ExportContext(
        config={"item_properties": {"text_key": "text"}},
        annotations=[{
            "instance_id": instance_id,
            "user_id": "alice",
            "labels": {},
            "spans": {"entities": list(ENTITIES if spans is None else spans)},
        }],
        items={instance_id: {"id": instance_id, "text": text}},
        schemas=schemas,
        output_dir="",
    )


def round_trip(exporter, tmp_path, context, filename):
    result = exporter.export(context, str(tmp_path))
    assert result.success, result.errors
    path = Path(os.path.join(str(tmp_path), filename))
    assert path.is_file()
    return CoNLLImporter().parse_path(path), path


def covered(document):
    return [(s.label, document.text[s.start:s.end]) for s in document.spans]


class TestCoNLL2003RoundTrip:
    @pytest.fixture
    def imported(self, tmp_path):
        result, _ = round_trip(CoNLL2003Exporter(), tmp_path, make_context(),
                               "annotations.conll")
        return result

    def test_every_entity_comes_back_on_the_right_text(self, imported):
        document = imported.documents[0]
        assert covered(document) == [
            ("PER", "Barack Obama"),
            ("LOC", "Paris"),
            ("PER", "Angela Merkel"),
        ]

    def test_the_text_survives(self, imported):
        assert imported.documents[0].text == TEXT

    def test_two_adjacent_entities_of_one_type_stay_two(self, tmp_path):
        """
        The failure BIO decoding is prone to. Exported as B-PER B-PER, a
        reader that treats B- as merely "inside" returns one span covering
        both -- and every count-based test still passes.
        """
        text = "Alice Bob talked"
        spans = [{"name": "PER", "start": 0, "end": 5},
                 {"name": "PER", "start": 6, "end": 9}]
        result, _ = round_trip(CoNLL2003Exporter(), tmp_path,
                               make_context(text=text, spans=spans),
                               "annotations.conll")
        assert covered(result.documents[0]) == [("PER", "Alice"), ("PER", "Bob")]

    def test_the_labels_come_back(self, imported):
        assert {label["name"] for label in imported.labels} == {"PER", "LOC"}

    def test_no_offsets_had_to_be_guessed(self, imported):
        assert not imported.warnings


class TestCoNLLURoundTrip:
    @pytest.fixture
    def imported(self, tmp_path):
        result, _ = round_trip(CoNLLUExporter(), tmp_path, make_context(),
                               "annotations.conllu")
        return result

    def test_every_entity_comes_back_on_the_right_text(self, imported):
        assert covered(imported.documents[0]) == [
            ("PER", "Barack Obama"),
            ("LOC", "Paris"),
            ("PER", "Angela Merkel"),
        ]

    def test_the_instance_id_is_recovered_from_sent_id(self, imported):
        """
        The exporter writes `# sent_id = <instance_id>-s<n>`. Reading it back
        is what makes an export/import cycle land on the original ids instead
        of on synthetic ones, so a re-import can be diffed against the source.
        """
        assert imported.documents[0].instance_id == "doc1"

    def test_the_text_comment_makes_the_text_exact(self, tmp_path):
        """
        CoNLL-U carries `# text =`, so unlike CoNLL-2003 the punctuation
        spacing of the original survives.
        """
        text = "Paris, France is large."
        spans = [{"name": "LOC", "start": 0, "end": 5}]
        result, _ = round_trip(CoNLLUExporter(), tmp_path,
                               make_context(text=text, spans=spans),
                               "annotations.conllu")
        assert result.documents[0].text == text


class TestTokenizationIsWhereItIsLossy:
    def test_a_span_ending_mid_token_widens_to_the_token(self, tmp_path):
        """
        CoNLL is token-level. "Paris." is one whitespace token, so a span
        covering only "Paris" cannot survive -- it comes back as the whole
        token.

        This is documented rather than fixed because the alternative is worse:
        emitting sub-token spans would produce a file no other CoNLL tool can
        read. Asserting it here means the loss stays a known boundary instead
        of turning into a bug report.
        """
        text = "He visited Paris."
        spans = [{"name": "LOC", "start": 11, "end": 16}]  # "Paris" without "."
        result, _ = round_trip(CoNLL2003Exporter(), tmp_path,
                               make_context(text=text, spans=spans),
                               "annotations.conll")
        assert covered(result.documents[0]) == [("LOC", "Paris.")]

    def test_repeated_whitespace_is_not_preserved(self, tmp_path):
        """The format records no spacing at all, so this cannot round trip."""
        text = "Alice  met  Bob"
        spans = [{"name": "PER", "start": 0, "end": 5}]
        result, _ = round_trip(CoNLL2003Exporter(), tmp_path,
                               make_context(text=text, spans=spans),
                               "annotations.conll")
        assert result.documents[0].text == "Alice met Bob"

    def test_the_stored_text_is_always_what_the_offsets_index(self, tmp_path):
        """
        The loss above is tolerable only because the reconstruction is what we
        store. An annotator must never see one string while the spans point
        into another.
        """
        text = "Alice  met  Bob"
        spans = [{"name": "PER", "start": 12, "end": 15}]
        result, _ = round_trip(CoNLL2003Exporter(), tmp_path,
                               make_context(text=text, spans=spans),
                               "annotations.conll")
        document = result.documents[0]
        for span in document.spans:
            assert document.text[span.start:span.end] == span.text
        assert covered(document) == [("PER", "Bob")]


class TestMultipleDocuments:
    def test_docstart_keeps_documents_apart(self, tmp_path):
        context = make_context()
        context.items["doc2"] = {"id": "doc2", "text": "Berlin is cold ."}
        context.annotations.append({
            "instance_id": "doc2", "user_id": "alice", "labels": {},
            "spans": {"entities": [{"name": "LOC", "start": 0, "end": 6}]},
        })
        result, _ = round_trip(CoNLL2003Exporter(), tmp_path, context,
                               "annotations.conll")
        assert len(result.documents) == 2
        assert covered(result.documents[1]) == [("LOC", "Berlin")]

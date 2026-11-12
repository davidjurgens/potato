"""
Text-annotation importers: brat, CoNLL, doccano, Prodigy.

Potato registered fifteen importers and every one was computer vision, so an
NLP team -- the market we compete in most directly -- could not bring an
existing project in at all.

The assertions here are about *offsets*, not about counts. A reader that
imports the right number of spans at the wrong positions passes a shape test
and silently shifts every coding in someone's project, which is the failure
these formats actually produce. So each test checks the text under the span,
not the length of the list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from potato.importers.text.conll_importer import CoNLLImporter, bio_tags_to_spans
from potato.importers.text.registry import text_import_registry


def covered(document):
    """(label, text) for every span, read back out of the stored text."""
    return [(s.label, document.text[s.start:s.end]) for s in document.spans]


# --------------------------------------------------------------------- BIO


class TestBioDecoding:
    def test_iob2(self):
        tags = ["B-PER", "I-PER", "O", "B-LOC"]
        assert bio_tags_to_spans(tags) == [(0, 1, "PER"), (3, 3, "LOC")]

    def test_iob1_opens_on_a_bare_i(self):
        """IOB1 has no B- at all until two same-type entities collide."""
        assert bio_tags_to_spans(["I-PER", "I-PER", "O"]) == [(0, 1, "PER")]

    def test_adjacent_same_type_entities_do_not_merge(self):
        """
        The bug this exists for: reading B- as merely "inside" turns two
        adjacent PER mentions into one, and no count-based test notices.
        """
        assert bio_tags_to_spans(["B-PER", "B-PER"]) == [
            (0, 0, "PER"), (1, 1, "PER")]

    def test_bioes(self):
        assert bio_tags_to_spans(["B-ORG", "E-ORG", "S-LOC"]) == [
            (0, 1, "ORG"), (2, 2, "LOC")]

    def test_bilou(self):
        assert bio_tags_to_spans(["B-ORG", "L-ORG", "U-LOC"]) == [
            (0, 1, "ORG"), (2, 2, "LOC")]

    def test_an_entity_running_to_the_last_token_is_closed(self):
        assert bio_tags_to_spans(["O", "B-PER", "I-PER"]) == [(1, 2, "PER")]

    def test_type_change_without_an_o_between_splits(self):
        assert bio_tags_to_spans(["B-PER", "I-LOC"]) == [
            (0, 0, "PER"), (1, 1, "LOC")]


# ------------------------------------------------------------------- CoNLL


CONLL_2003 = """-DOCSTART- -X- -X- O

Barack\tNNP\tI-NP\tB-PER
Obama\tNNP\tI-NP\tI-PER
visited\tVBD\tI-VP\tO
Paris\tNNP\tI-NP\tB-LOC
.\t.\tO\tO
"""


class TestCoNLL2003:
    @pytest.fixture
    def result(self, tmp_path):
        path = tmp_path / "eng.train.conll"
        path.write_text(CONLL_2003, encoding="utf-8")
        return CoNLLImporter().parse_path(path)

    def test_spans_land_on_the_right_text(self, result):
        document = result.documents[0]
        assert covered(document) == [("PER", "Barack Obama"), ("LOC", "Paris")]

    def test_the_stored_text_is_what_the_offsets_index(self, result):
        """
        CoNLL cannot record spacing, so the text is a reconstruction. What
        matters is that the reconstruction is what we store -- an annotator
        must never see one string while the spans refer to another.
        """
        document = result.documents[0]
        assert document.text == "Barack Obama visited Paris ."
        assert not result.warnings

    def test_labels_are_collected(self, result):
        assert {label["name"] for label in result.labels} == {"PER", "LOC"}

    def test_docstart_starts_a_document(self, tmp_path):
        path = tmp_path / "two.conll"
        path.write_text(CONLL_2003 + "\n-DOCSTART- -X- -X- O\n\nBerlin\tNNP\tI-NP\tB-LOC\n",
                        encoding="utf-8")
        result = CoNLLImporter().parse_path(path)
        assert len(result.documents) == 2
        assert covered(result.documents[1]) == [("LOC", "Berlin")]

    def test_without_docstart_each_sentence_is_an_item(self, tmp_path):
        path = tmp_path / "plain.conll"
        path.write_text("A\tO\nb\tO\n\nC\tO\nd\tO\n", encoding="utf-8")
        result = CoNLLImporter().parse_path(path)
        assert [d.text for d in result.documents] == ["A b", "C d"]


CONLL_U = """# sent_id = doc1-s1
# text = Barack Obama visited Paris.
1\tBarack\t_\t_\t_\t_\t_\t_\t_\tNER=B-PER
2\tObama\t_\t_\t_\t_\t_\t_\t_\tNER=I-PER
3\tvisited\t_\t_\t_\t_\t_\t_\t_\t_
4\tParis\t_\t_\t_\t_\t_\t_\t_\tSpaceAfter=No|NER=B-LOC
5\t.\t_\t_\t_\t_\t_\t_\t_\t_
"""


class TestCoNLLU:
    @pytest.fixture
    def result(self, tmp_path):
        path = tmp_path / "corpus.conllu"
        path.write_text(CONLL_U, encoding="utf-8")
        return CoNLLImporter().parse_path(path)

    def test_the_text_comment_is_used_verbatim(self, result):
        """`# text =` is the real string; reconstructing over it loses spacing."""
        assert result.documents[0].text == "Barack Obama visited Paris."

    def test_ner_is_read_out_of_misc(self, result):
        assert covered(result.documents[0]) == [
            ("PER", "Barack Obama"), ("LOC", "Paris")]

    def test_sent_id_recovers_the_instance_id(self, result):
        """`<id>-s<n>` is what our own exporter writes, so import lands back
        on the original ids instead of inventing new ones."""
        assert result.documents[0].instance_id == "doc1"

    def test_multiword_ranges_are_not_counted_as_tokens(self, tmp_path):
        path = tmp_path / "mwt.conllu"
        path.write_text(
            "# text = del gato\n"
            "1-2\tdel\t_\t_\t_\t_\t_\t_\t_\t_\n"
            "1\tde\t_\t_\t_\t_\t_\t_\t_\t_\n"
            "2\tel\t_\t_\t_\t_\t_\t_\t_\t_\n"
            "3\tgato\t_\t_\t_\t_\t_\t_\t_\tNER=B-ANIMAL\n",
            encoding="utf-8")
        result = CoNLLImporter().parse_path(path)
        assert covered(result.documents[0]) == [("ANIMAL", "gato")]

    def test_space_after_no_is_honoured_without_a_text_comment(self, tmp_path):
        path = tmp_path / "nospace.conllu"
        path.write_text(
            "1\tParis\t_\t_\t_\t_\t_\t_\t_\tSpaceAfter=No|NER=B-LOC\n"
            "2\t.\t_\t_\t_\t_\t_\t_\t_\t_\n",
            encoding="utf-8")
        result = CoNLLImporter().parse_path(path)
        assert result.documents[0].text == "Paris."
        assert covered(result.documents[0]) == [("LOC", "Paris")]


class TestCoNLLDetection:
    def test_prose_in_a_txt_file_is_not_claimed(self, tmp_path):
        """
        The extension list has to include .txt, so the content check is the
        only thing between a README and a very confusing import.
        """
        path = tmp_path / "notes.txt"
        path.write_text("This is a paragraph of ordinary prose.\n"
                        "It has several words on each line.\n", encoding="utf-8")
        assert text_import_registry.detect_path(path) is None

    def test_a_real_conll_file_is_claimed(self, tmp_path):
        path = tmp_path / "train.txt"
        path.write_text(CONLL_2003, encoding="utf-8")
        assert text_import_registry.detect_path(path) == "conll"


# -------------------------------------------------------------------- brat


class TestBrat:
    @pytest.fixture
    def corpus(self, tmp_path):
        (tmp_path / "doc1.txt").write_text(
            "Barack Obama visited Paris.", encoding="utf-8")
        (tmp_path / "doc1.ann").write_text(
            "T1\tPER 0 12\tBarack Obama\n"
            "T2\tLOC 21 26\tParis\n"
            "#1\tAnnotatorNotes T1\tformer president\n",
            encoding="utf-8")
        return tmp_path

    def test_offsets_are_taken_as_written(self, corpus):
        result = text_import_registry.parse_path("brat", corpus)
        assert covered(result.documents[0]) == [
            ("PER", "Barack Obama"), ("LOC", "Paris")]
        assert not result.warnings

    def test_the_recorded_text_is_checked_against_the_offsets(self, tmp_path):
        """
        brat writes the covered text in column three. When it disagrees with
        the offsets the file is wrong, and saying so at import time beats
        letting a researcher find it span by span.
        """
        (tmp_path / "bad.txt").write_text("Barack Obama visited Paris.",
                                          encoding="utf-8")
        (tmp_path / "bad.ann").write_text("T1\tPER 0 6\tBarack Obama\n",
                                          encoding="utf-8")
        result = text_import_registry.parse_path("brat", tmp_path)
        assert any("recorded" in w for w in result.warnings)

    def test_discontinuous_mentions_keep_their_other_fragments(self, tmp_path):
        (tmp_path / "d.txt").write_text("New and exciting York", encoding="utf-8")
        (tmp_path / "d.ann").write_text("T1\tLOC 0 3;17 21\tNew York\n",
                                        encoding="utf-8")
        result = text_import_registry.parse_path("brat", tmp_path)
        span = result.documents[0].spans[0]
        assert (span.start, span.end) == (0, 3)
        assert span.additional_parts == [{"start": 17, "end": 21, "text": "York"}]
        assert not result.warnings, (
            "brat records a discontinuous mention's covered text as the "
            "fragments joined, which must not be reported as a mismatch")

    def test_relations_are_reported_rather_than_silently_dropped(self, tmp_path):
        (tmp_path / "r.txt").write_text("A works at B", encoding="utf-8")
        (tmp_path / "r.ann").write_text(
            "T1\tPER 0 1\tA\nT2\tORG 11 12\tB\n"
            "R1\tEmployment Arg1:T1 Arg2:T2\n", encoding="utf-8")
        result = text_import_registry.parse_path("brat", tmp_path)
        assert any("relation" in w for w in result.warnings)

    def test_an_ann_with_no_txt_is_skipped_loudly(self, tmp_path):
        (tmp_path / "orphan.ann").write_text("T1\tPER 0 1\tA\n", encoding="utf-8")
        result = text_import_registry.parse_path("brat", tmp_path)
        assert result.documents == []
        assert any("no matching .txt" in w for w in result.warnings)

    def test_a_directory_of_ann_files_is_detected(self, corpus):
        assert text_import_registry.detect_path(corpus) == "brat"


# ----------------------------------------------------------------- doccano


class TestDoccano:
    @staticmethod
    def write(tmp_path, records, name="export.jsonl"):
        path = tmp_path / name
        path.write_text("\n".join(json.dumps(r) for r in records),
                        encoding="utf-8")
        return path

    def test_sequence_labelling_offsets(self, tmp_path):
        path = self.write(tmp_path, [{
            "id": 7, "text": "Barack Obama visited Paris.",
            "label": [[0, 12, "PER"], [21, 26, "LOC"]],
        }])
        result = text_import_registry.parse_path("doccano", path)
        assert covered(result.documents[0]) == [
            ("PER", "Barack Obama"), ("LOC", "Paris")]
        assert result.documents[0].instance_id == "7"

    @pytest.mark.parametrize("entry", [
        [0, 12, "PER"],
        {"start_offset": 0, "end_offset": 12, "label": "PER"},
        {"start": 0, "end": 12, "label": "PER"},
    ])
    def test_every_shape_doccano_has_emitted_is_read(self, tmp_path, entry):
        """
        A reader that knows only the current shape imports zero spans from an
        older export and still reports success.
        """
        path = self.write(tmp_path, [
            {"text": "Barack Obama visited Paris.", "label": [entry]}])
        result = text_import_registry.parse_path("doccano", path)
        assert covered(result.documents[0]) == [("PER", "Barack Obama")]

    def test_document_categories_become_their_own_scheme(self, tmp_path):
        path = self.write(tmp_path, [
            {"text": "A complaint.", "label": ["negative"]},
            {"text": "A compliment.", "label": ["positive"]},
        ])
        result = text_import_registry.parse_path("doccano", path)
        assert result.documents[0].labels == {"categories": ["negative"]}
        scheme = result.document_schemes[0]
        assert scheme["annotation_type"] == "multiselect"
        assert {label["name"] for label in scheme["labels"]} == {"negative",
                                                                 "positive"}

    def test_a_span_past_the_end_of_the_text_is_dropped_loudly(self, tmp_path):
        path = self.write(tmp_path, [{"text": "short", "label": [[0, 99, "X"]]}])
        result = text_import_registry.parse_path("doccano", path)
        assert result.documents[0].spans == []
        assert any("does not fit" in w for w in result.warnings)

    def test_a_json_array_is_accepted_too(self, tmp_path):
        path = tmp_path / "array.json"
        path.write_text(json.dumps(
            [{"text": "Barack Obama", "label": [[0, 12, "PER"]]}]),
            encoding="utf-8")
        result = text_import_registry.parse_path("doccano", path)
        assert covered(result.documents[0]) == [("PER", "Barack Obama")]


# ----------------------------------------------------------------- Prodigy


class TestProdigy:
    @staticmethod
    def write(tmp_path, records):
        path = tmp_path / "db-out.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records),
                        encoding="utf-8")
        return path

    def test_accepted_tasks_import(self, tmp_path):
        path = self.write(tmp_path, [{
            "text": "Barack Obama visited Paris.", "answer": "accept",
            "_view_id": "ner_manual", "_task_hash": 111,
            "spans": [{"start": 0, "end": 12, "label": "PER"}],
        }])
        result = text_import_registry.parse_path("prodigy", path)
        assert covered(result.documents[0]) == [("PER", "Barack Obama")]

    def test_rejected_tasks_are_dropped_by_default(self, tmp_path):
        """
        A rejection is a human saying the annotations are wrong. Importing it
        as though it were approved turns an explicit negative judgement into
        positive training signal.
        """
        path = self.write(tmp_path, [
            {"text": "good", "answer": "accept", "_view_id": "ner_manual",
             "spans": [{"start": 0, "end": 4, "label": "X"}]},
            {"text": "bad", "answer": "reject", "_view_id": "ner_manual",
             "spans": [{"start": 0, "end": 3, "label": "X"}]},
        ])
        result = text_import_registry.parse_path("prodigy", path)
        assert [d.text for d in result.documents] == ["good"]
        assert any("reject" in w for w in result.warnings)

    def test_the_override_brings_them_back(self, tmp_path):
        path = self.write(tmp_path, [
            {"text": "bad", "answer": "reject", "_view_id": "ner_manual",
             "spans": [{"start": 0, "end": 3, "label": "X"}]}])
        result = text_import_registry.parse_path(
            "prodigy", path, {"prodigy_keep_rejected": True})
        assert [d.text for d in result.documents] == ["bad"]

    def test_the_verdict_becomes_a_scheme(self, tmp_path):
        path = self.write(tmp_path, [
            {"text": "x", "answer": "accept", "_view_id": "ner_manual"}])
        result = text_import_registry.parse_path("prodigy", path)
        assert result.documents[0].labels == {"prodigy_answer": "accept"}
        assert result.document_schemes[0]["annotation_type"] == "radio"

    def test_prodigy_wins_the_detection_race_against_doccano(self, tmp_path):
        """
        Both formats are JSONL with text plus a label list. doccano's own
        detector would happily claim a Prodigy file, so the order is load
        bearing rather than incidental.
        """
        path = self.write(tmp_path, [{
            "text": "x", "answer": "accept", "_input_hash": 1,
            "spans": [{"start": 0, "end": 1, "label": "X"}]}])
        assert text_import_registry.detect_path(path) == "prodigy"


# ---------------------------------------------------------------- registry


class TestRegistryContract:
    @pytest.mark.parametrize("name", text_import_registry.get_supported_formats())
    def test_every_importer_declares_itself(self, name):
        importer = text_import_registry.get(name)
        assert importer.format_name == name
        assert importer.description, f"{name} has no --list-formats description"
        assert importer.file_extensions

    @pytest.mark.parametrize("name", text_import_registry.get_supported_formats())
    def test_detect_is_side_effect_free_on_junk(self, name, tmp_path):
        """
        The registry calls detect_path on every importer in turn, so one that
        raises on an unfamiliar file breaks detection for all the others.
        """
        importer = text_import_registry.get(name)
        junk = tmp_path / "junk.bin"
        junk.write_bytes(b"\x00\x01\x02not text at all\xff")
        for candidate in (junk, tmp_path / "missing.txt", tmp_path):
            assert isinstance(importer.detect_path(Path(candidate)), bool)

    def test_a_coco_file_is_never_claimed_by_a_text_importer(self, tmp_path):
        """
        The CLI tries text detection before the CV path. That is only safe if
        no text detector accepts a CV format's file.
        """
        path = tmp_path / "instances.json"
        path.write_text(json.dumps({
            "images": [{"id": 1, "file_name": "a.jpg", "width": 4, "height": 4}],
            "annotations": [{"id": 1, "image_id": 1, "category_id": 1,
                             "bbox": [0, 0, 2, 2]}],
            "categories": [{"id": 1, "name": "cat"}],
        }), encoding="utf-8")
        assert text_import_registry.detect_path(path) is None

    def test_stats_use_the_keys_the_cli_prints(self, tmp_path):
        from potato.importers.text.base import REQUIRED_STATS

        path = tmp_path / "x.conll"
        path.write_text(CONLL_2003, encoding="utf-8")
        stats = CoNLLImporter().parse_path(path).stats
        for key in REQUIRED_STATS:
            assert key in stats

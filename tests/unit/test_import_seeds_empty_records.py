"""An item reviewed with nothing in it gets an empty record, not no record.

`--seed-user` writes the imported annotations as a fabricated annotator's work,
and it skipped any item whose annotation list was empty. So an entity-free
sentence, or an image with no objects, was left in the corpus with no evidence
anyone had reviewed it.

Measured on a five-sentence CoNLL round trip: the corpus kept all five items and
`instance_id_to_span_to_value` held records for four. The exporter is already
right -- given an empty record it writes the sentence with O tags, which is a
confirmed negative -- so the round trip lost "Nothing to see here" on the way IN
rather than on the way out. Mirror image of the COCO case, where the importer
preserved the item and the exporter dropped it.

This is not fabricating a claim. A CoNLL file asserts something about every
sentence, including "this one has no entities", which is what an O-only sentence
means; a COCO file listing an image with no annotations asserts the same. The
skip discarded a claim the source made.

The text seeder is shared by every text importer -- conll, brat, doccano,
prodigy, qdpx -- so this covers all five.
"""

import json
import os
import tempfile

import pytest

from potato.importers.cli import _write_seed_user, _write_text_seed_user


class Span:
    def __init__(self, label, start, end):
        self.label, self.start, self.end = label, start, end

    def as_client_span(self, schema_name):
        return {"schema": schema_name, "name": self.label,
                "start": self.start, "end": self.end}


class Document:
    def __init__(self, instance_id, spans):
        self.instance_id, self.spans = instance_id, spans


class Image:
    def __init__(self, instance_id, objects):
        self.instance_id, self.objects = instance_id, objects


class Result:
    def __init__(self, documents=None, images=None):
        self.documents = documents or []
        self.images = images or []


def seed_text(documents):
    with tempfile.TemporaryDirectory() as out:
        _write_text_seed_user(out, "seeded", "ner", Result(documents=documents))
        with open(os.path.join(out, "annotation_output", "seeded",
                               "user_state.json")) as fh:
            return json.load(fh)


def seed_images(images):
    with tempfile.TemporaryDirectory() as out:
        _write_seed_user(out, "seeded", "boxes", Result(images=images))
        with open(os.path.join(out, "annotation_output", "seeded",
                               "user_state.json")) as fh:
            return json.load(fh)


DOCS = [
    Document("in-s1", []),
    Document("in-s2", [Span("ORG", 4, 18), Span("LOC", 19, 24)]),
    Document("in-s5", []),
]


class TestTextSeeding:

    def test_every_document_gets_a_record(self):
        spans = seed_text(DOCS)["instance_id_to_span_to_value"]
        assert set(spans) == {"in-s1", "in-s2", "in-s5"}, (
            "an entity-free sentence was left with no evidence anyone had "
            "reviewed it, and the exporter had nothing to write")

    def test_an_entity_free_document_records_an_empty_list(self):
        spans = seed_text(DOCS)["instance_id_to_span_to_value"]
        assert spans["in-s5"] == []

    def test_an_annotated_document_keeps_its_spans(self):
        spans = seed_text(DOCS)["instance_id_to_span_to_value"]
        assert len(spans["in-s2"]) == 2

    def test_the_span_shape_is_unchanged(self):
        record = seed_text(DOCS)["instance_id_to_span_to_value"]["in-s2"][0]
        assert record[1] == "1"
        assert record[0]["schema"] == "ner" and record[0]["name"] == "ORG"

    def test_the_ordering_still_lists_every_document(self):
        state = seed_text(DOCS)
        assert state["instance_id_ordering"] == ["in-s1", "in-s2", "in-s5"]

    def test_the_warning_separates_the_two_counts(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            seed_text(DOCS)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "3 item(s)" in message
        assert "1 of them carrying spans" in message
        assert "2 recorded as reviewed with none" in message
        assert "fabricated" in message, (
            "the fabrication warning is the reason --seed-user is safe to "
            "offer at all")

    def test_an_empty_import_writes_an_empty_map(self):
        assert seed_text([])["instance_id_to_span_to_value"] == {}


class TestImageSeeding:
    """The same shape in the CV path, which is the other half of the COCO
    round trip: the exporter now writes a confirmed negative, and this is what
    tells it one was confirmed."""

    IMAGES = [Image("a", []),
              Image("c", [{"type": "bbox", "label": "alpha"}])]

    def test_every_image_gets_a_record(self):
        labels = seed_images(self.IMAGES)["instance_id_to_label_to_value"]
        assert set(labels) == {"a", "c"}

    def test_an_empty_image_records_an_empty_list(self):
        labels = seed_images(self.IMAGES)["instance_id_to_label_to_value"]
        assert json.loads(labels["a"][0][1]) == []

    def test_an_annotated_image_keeps_its_objects(self):
        labels = seed_images(self.IMAGES)["instance_id_to_label_to_value"]
        assert len(json.loads(labels["c"][0][1])) == 1

    def test_the_record_shape_is_unchanged(self):
        record = seed_images(self.IMAGES)["instance_id_to_label_to_value"]["c"]
        assert record[0][0] == {"schema": "boxes", "name": "_data"}

    def test_the_warning_separates_the_two_counts(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            seed_images(self.IMAGES)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "2 item(s)" in message
        assert "1 of them carrying objects" in message
        assert "1 recorded as reviewed with none" in message

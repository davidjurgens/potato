"""LexTALE scoring, its config block, and that the key never reaches a page."""

import csv
import os

import pytest

from potato.export.base import ExportContext
from potato.export.lextale_exporter import LexTALEExporter
from potato.server_utils.config_module import ConfigValidationError, validate_single_annotation_scheme
from potato.server_utils.schemas.cloze import strip_answer_fields
from tests.helpers.test_utils import create_test_directory

SCHEME = {"annotation_type": "radio", "name": "lex", "description": "Is this a word?",
          "labels": ["yes", "no"], "lextale": {"answer_field": "is_word", "word": "yes", "nonword": "no"}}
ITEMS = {"w1": {"id": "w1", "text": "platery", "is_word": "no"},
         "w2": {"id": "w2", "text": "denial", "is_word": "yes"},
         "w3": {"id": "w3", "text": "mensible", "is_word": "no"},
         "w4": {"id": "w4", "text": "scornful", "is_word": "yes"}}


def test_score_is_the_mean_of_the_two_percentages():
    out = create_test_directory("lextale_export")
    answers = {"w1": "no", "w2": "yes", "w3": "yes", "w4": "yes"}   # words 2/2, nonwords 1/2
    anns = [{"user_id": "u", "instance_id": i, "labels": {"lex": {a: a}}} for i, a in answers.items()]
    ctx = ExportContext(config={"annotation_schemes": [SCHEME]}, annotations=anns, items=ITEMS,
                        schemas=[SCHEME], output_dir=out)
    assert LexTALEExporter().export(ctx, out).success
    row = next(csv.DictReader(open(os.path.join(out, "lextale.csv"))))
    assert row["pct_words_correct"] == "100.0" and row["pct_nonwords_correct"] == "50.0"
    assert row["lextale_score"] == "75.0"


def test_key_is_stripped_from_item_records():
    clean = strip_answer_fields({"annotation_schemes": [SCHEME]}, ITEMS["w2"])
    assert "is_word" not in clean and clean["text"] == "denial"


def test_bad_block_refused():
    bad = dict(SCHEME, lextale={"answer_field": "is_word", "word": "word"})
    with pytest.raises(ConfigValidationError, match="not one of the labels"):
        validate_single_annotation_scheme(bad, "annotation_schemes[0]")


def test_a_lextale_scheme_on_a_phase_page_is_named_not_missed():
    config = {"annotation_schemes": [],
              "phases": {"order": ["vocab", "annotation"],
                         "vocab": {"type": "prestudy", "annotation_schemes": [SCHEME]},
                         "annotation": {"type": "annotation"}}}
    ctx = ExportContext(config=config, annotations=[], items=ITEMS, schemas=[],
                        output_dir=create_test_directory("lextale_phase"))
    ok, why = LexTALEExporter().can_export(ctx)
    assert not ok
    assert "lex is on the phase page vocab" in why and "annotation_schemes" in why


def test_a_phase_page_lextale_is_warned_beside_a_scored_one():
    other = {**SCHEME, "name": "lex2"}
    config = {"annotation_schemes": [SCHEME],
              "phases": {"order": ["vocab", "annotation"],
                         "vocab": {"type": "prestudy", "annotation_schemes": [other]},
                         "annotation": {"type": "annotation"}}}
    out = create_test_directory("lextale_phase_warn")
    ctx = ExportContext(config=config, annotations=[], items=ITEMS, schemas=[SCHEME], output_dir=out)
    result = LexTALEExporter().export(ctx, out)
    assert result.success and any("lex2 is on the phase page vocab" in w for w in result.warnings)

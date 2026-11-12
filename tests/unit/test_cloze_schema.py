"""Cloze schema: rendering without the answer key, scoring, and the API mask."""

import pytest
from bs4 import BeautifulSoup

from potato.export.base import ExportContext
from potato.export.tabular_exporter import _flatten_annotation
from potato.server_utils.schemas.cloze import (
    parse_passage,
    public_text,
    score_responses,
)
from potato.server_utils.schemas.registry import schema_registry

SCHEME = {"annotation_type": "cloze", "name": "c1", "description": "Fill in the blanks",
          "text": "The [[cat|kitten]] sat on the [[Mat]] near [[]] the <door>."}


def _render(scheme=SCHEME):
    html, keys = schema_registry.generate(dict(scheme))
    return BeautifulSoup(html, "html.parser"), keys


def test_blanks_render_as_text_inputs():
    soup, keys = _render()
    blanks = soup.find_all("input", class_="cloze-blank")
    assert [b["name"] for b in blanks] == ["c1:::blank_1", "c1:::blank_2", "c1:::blank_3"]
    assert all(b["type"] == "text" and b["label_name"].startswith("blank_") for b in blanks)
    assert keys == []
    form = soup.find("form")
    assert form["data-schema-name"] == "c1" and "annotation-form" in form["class"]


def test_answer_key_never_rendered():
    soup, _ = _render()
    html = str(soup).lower()
    for answer in ("cat", "kitten", "mat"):
        assert answer not in html, answer
    assert "&lt;door&gt;" in str(soup)   # passage text is escaped


def test_required_marks_every_blank():
    scheme = dict(SCHEME, label_requirement={"required": True})
    soup, _ = _render(scheme)
    assert {b["validation"] for b in soup.find_all("input", class_="cloze-blank")} == {"required"}


def test_passage_without_blanks_is_an_error_card():
    soup, _ = _render(dict(SCHEME, text="No blanks here."))
    assert not soup.find_all("input", class_="cloze-blank")


def test_parse():
    segments, answers = parse_passage("a [[x|y]] b [[]]")
    assert segments == ["a ", 0, " b ", 1]
    assert answers == [["x", "y"], []]


@pytest.mark.parametrize("mode,given,ok", [
    ("case_insensitive", {"blank_1": " Kitten ", "blank_2": "mat"}, (1, 1)),
    ("exact", {"blank_1": "Kitten", "blank_2": "mat"}, (0, 0)),
    ("exact", {"blank_1": "kitten", "blank_2": "Mat"}, (1, 1)),
    ("normalized", {"blank_1": "cät!", "blank_2": "MAT."}, (1, 1)),
])
def test_scoring(mode, given, ok):
    out = score_responses(dict(SCHEME, scoring=mode), given)
    assert (out["blank_1_correct"], out["blank_2_correct"]) == ok
    assert out["score"] == sum(ok) and out["scored_blanks"] == 2
    assert "blank_3_correct" not in out      # [[]] has no key


def test_no_key_no_score():
    assert score_responses({"text": "a [[]] b"}, {"blank_1": "x"}) is None


def test_public_text_masks_answers():
    assert public_text(SCHEME["text"]) == "The [[]] sat on the [[]] near [[]] the <door>."


def test_export_adds_score_columns():
    ctx = ExportContext(config={"annotation_schemes": [SCHEME]}, annotations=[], items={},
                        schemas=[SCHEME], output_dir=".")
    ann = {"instance_id": "i1", "user_id": "u", "spans": {}, "links": {},
           "labels": {"c1": {"blank_1": "cat", "blank_2": "rug"}}}
    row = _flatten_annotation(ann, set(), [], ctx)
    assert row["c1.blank_1_correct"] == 1 and row["c1.blank_2_correct"] == 0
    assert row["c1.score"] == 1


ITEM_SCHEME = {"annotation_type": "cloze", "name": "ct", "description": "Complete",
               "source_field": "passage", "answer_field": "answers"}


def test_item_driven_placeholder_then_fill():
    from potato.server_utils.schemas.cloze import fill_item_passages
    soup, _ = _render(ITEM_SCHEME)
    holder = soup.find(attrs={"data-cloze-source": "passage"})
    assert holder is not None and not holder.find("input")
    n = fill_item_passages(soup, {"annotation_schemes": [ITEM_SCHEME]},
                           {"passage": "A [[secret]] and [[]].", "answers": ["x", "y"]})
    assert n == 1
    names = [i["name"] for i in soup.find_all("input", class_="cloze-blank")]
    assert names == ["ct:::blank_1", "ct:::blank_2"]
    assert "secret" not in str(soup)


def test_item_driven_scoring_and_strip():
    from potato.server_utils.schemas.cloze import strip_answer_fields
    item = {"passage": "A [[]] [[]]", "answers": [["dog", "hound"], "cat|kitten"]}
    out = score_responses(ITEM_SCHEME, {"blank_1": "Hound", "blank_2": "kitten"}, item)
    assert out["score"] == 2
    cfg = {"annotation_schemes": [ITEM_SCHEME]}
    assert strip_answer_fields(cfg, item) == {"passage": "A [[]] [[]]"}


def test_text_and_source_field_together_is_an_error_card():
    soup, _ = _render(dict(ITEM_SCHEME, text="a [[b]]"))
    assert not soup.find(attrs={"data-cloze-source": True})
    assert not soup.find_all("input", class_="cloze-blank")


@pytest.mark.parametrize("extra,match", [
    ({}, "exactly one"),
    ({"text": "a [[b]]", "source_field": "p"}, "exactly one"),
    ({"text": "no blanks"}, "at least one"),
    ({"text": "a [[b]]", "answer_field": "ans"}, "only applies"),
    ({"text": "a [[b]]", "scoring": "fuzzy"}, "scoring"),
])
def test_config_validation(extra, match):
    from potato.server_utils.config_module import (
        ConfigValidationError, validate_single_annotation_scheme)
    scheme = {"annotation_type": "cloze", "name": "c", "description": "d"}
    scheme.update(extra)
    with pytest.raises(ConfigValidationError, match=match):
        validate_single_annotation_scheme(scheme, "annotation_schemes[0]")


def test_inline_key_in_passage_is_masked_for_the_page():
    """Audit 94, C1: text inside [[...]] of an item passage reached
    data-instance-json."""
    from potato.server_utils.schemas.cloze import strip_answer_fields
    cfg = {"annotation_schemes": [ITEM_SCHEME]}
    out = strip_answer_fields(cfg, {"passage": "I [[LEAKKEY]] a [[]].", "answers": ["x", "y"]})
    assert out == {"passage": "I [[]] a [[]]."}


def test_more_answers_than_blanks_scores_only_the_blanks():
    """Audit 94, C2."""
    item = {"passage": "One [[]] here.", "answers": ["x1", "EXTRA", "EXTRA2"]}
    out = score_responses(ITEM_SCHEME, {"blank_1": "x1"}, item)
    assert out == {"blank_1_correct": 1, "score": 1, "scored_blanks": 1}


def test_string_key_for_one_blank():
    item = {"passage": "One [[]] here.", "answers": "cat|kitten"}
    assert score_responses(ITEM_SCHEME, {"blank_1": "Kitten"}, item)["score"] == 1


def test_all_blanks_required():
    """Audit 94, C3: one filled blank or whitespace satisfied required."""
    from potato.server_utils.schemas.cloze import all_blanks_filled
    assert not all_blanks_filled(SCHEME, {"blank_1": "cat"})
    assert not all_blanks_filled(SCHEME, {"blank_1": "cat", "blank_2": "  ", "blank_3": "x"})
    assert all_blanks_filled(SCHEME, {"blank_1": "cat", "blank_2": "mat", "blank_3": "x"})


def test_unanswered_scores_zero():
    ctx = ExportContext(config={"annotation_schemes": [SCHEME]}, annotations=[], items={},
                        schemas=[SCHEME], output_dir=".")
    row = _flatten_annotation({"instance_id": "i1", "user_id": "u", "spans": {}, "links": {},
                               "labels": {}}, set(), [], ctx)
    assert row["c1.score"] == 0


def test_export_warns_about_key_length_mismatch():
    """Audit 94 re-verify, C2: the truncation was only in the server log."""
    from potato.export.tabular_exporter import _write_delimited
    from tests.helpers.test_utils import create_test_directory
    out = create_test_directory("cloze_mismatch_export")
    items = {"p1": {"passage": "One [[]].", "answers": ["x", "extra"]},
             "p2": {"passage": "Two [[]] [[]].", "answers": ["a", "b"]}}
    ctx = ExportContext(config={"annotation_schemes": [ITEM_SCHEME]},
                        annotations=[{"instance_id": "p1", "user_id": "u", "spans": {}, "links": {},
                                      "labels": {"ct": {"blank_1": "x"}}}],
                        items=items, schemas=[ITEM_SCHEME], output_dir=out)
    result = _write_delimited(ctx, out, "csv", ",")
    assert any("p1" in w and "blanks" in w for w in result.warnings), result.warnings
    assert not any("p2" in w for w in result.warnings)

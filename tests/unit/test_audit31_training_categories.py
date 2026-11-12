"""
A training question's category must survive the loader, whichever way it is
spelled.

Category-based assignment qualifies an annotator only from their per-category
training scores. Three spellings reach the loader from reasonable authors and
only one used to work:

  category    the historic singular
  categories  the plural -- the same word the READER uses
              (`get_training_instance_categories`)
  <category_key>  whatever `item_properties.category_key` names, which is the
              one category spelling the author has already committed to,
              because it is how their corpus is tagged

The plural was worse than ignored. `item_data = dict(instance)` copied the
author's value and the `update()` below then overwrote it with the empty list
normalized from the absent singular, so the loader clobbered the author's own
data with a blank.

The consequence is silent and self-defeating: the annotator passes training,
qualifies for nothing, and lands on a page telling them to add categorized
training questions -- which is what they did.
"""

import json
import tempfile
from pathlib import Path

import pytest

import potato.flask_server as flask_server


def _config(tmp_path, training_instances, category_key="topic"):
    data_file = Path(tmp_path) / "training.json"
    data_file.write_text(json.dumps(
        {"training_instances": training_instances}), encoding="utf-8")
    return {
        "task_dir": str(tmp_path),
        "assignment_strategy": "category_based",
        "item_properties": {"id_key": "id", "text_key": "text",
                            "category_key": category_key},
        "category_assignment": {"enabled": True},
        "annotation_schemes": [{"name": "verdict", "description": "V",
                                "annotation_type": "radio",
                                "labels": ["yes", "no"]}],
        "training": {"enabled": True, "data_file": str(data_file)},
    }


def _load(tmp_path, extra, category_key="topic"):
    row = {"id": "t1", "text": "a practice question",
           "correct_answers": {"verdict": ["yes"]}}
    row.update(extra)
    flask_server.load_training_data(
        _config(tmp_path, [row], category_key=category_key))
    return flask_server.get_training_instance_categories("t1")


@pytest.mark.parametrize("spelling,value", [
    ("category", "medical"),
    ("category", ["medical"]),
    ("categories", ["medical"]),
    ("categories", "medical"),
    ("topic", "medical"),
    ("topic", ["medical"]),
])
def test_every_accepted_spelling_reaches_the_reader(
        tmp_path, spelling, value):
    """`get_training_instance_categories` is what qualification reads, so
    asserting on it rather than on the stored dict is the difference
    between 'the loader kept it' and 'qualification can see it'."""
    assert _load(tmp_path, {spelling: value}) == ["medical"]


def test_the_plural_is_not_clobbered_by_the_absent_singular(tmp_path):
    """The specific regression: the author wrote `categories`, the loader
    copied it, then overwrote it with the empty list it had normalized
    from a `category` key that was never there."""
    assert _load(tmp_path, {"categories": ["medical", "legal"]}) == [
        "medical", "legal"]


def test_the_singular_wins_when_both_are_present(tmp_path):
    """`category` is the historic key and the only one that ever worked,
    so a config carrying both must not change meaning."""
    assert _load(tmp_path, {"category": "medical",
                            "categories": ["legal"]}) == ["medical"]


def test_a_question_with_no_category_yields_none(tmp_path):
    assert _load(tmp_path, {}) == []


def test_an_unrelated_key_is_not_mistaken_for_a_category(tmp_path):
    """Only `category`, `categories` and the CONFIGURED category_key are
    read. Guessing more widely would pick up arbitrary item fields."""
    assert _load(tmp_path, {"domain": "medical"}) == []


def test_the_configured_key_is_honoured_not_hardcoded(tmp_path):
    """`topic` works because the config says so, not because the loader
    knows the word."""
    assert _load(tmp_path, {"subject": "medical"},
                 category_key="subject") == ["medical"]
    assert _load(tmp_path, {"topic": "medical"},
                 category_key="subject") == []


def test_uncategorized_training_under_category_based_warns(tmp_path, caplog):
    """The case the config-level warning cannot see: the training block
    exists and looks complete, and every question is uncategorized."""
    with caplog.at_level("WARNING", logger="potato.flask_server"):
        _load(tmp_path, {})
    assert any("carries a category" in r.message
               for r in caplog.records if r.levelname == "WARNING"), [
                   r.message for r in caplog.records]


def test_categorized_training_does_not_warn(tmp_path, caplog):
    with caplog.at_level("WARNING", logger="potato.flask_server"):
        _load(tmp_path, {"category": "medical"})
    assert not any("carries a category" in r.message
                   for r in caplog.records if r.levelname == "WARNING")

"""Training practice items on a media task.

An image project points `text_key` at the image URL field, so its practice
questions carry the URL under that key rather than under `text`.
`load_training_data` rebuilt each Item from a fixed six keys and discarded
every other field on the instance -- including the one `text_key` names -- and
derived `displayed_text` from `text` alone. The practice page then had the
item's prose where it expected an image URL, and the annotation canvas asked
the browser to fetch a sentence.

The loader now derives the question from `text_key` when the instance carries
it, and carries the rest of the instance through. `_training_page_context` is
unchanged and still reads `displayed_text` first, which is what keeps a
list-valued practice item rendering as formatted HTML rather than as a Python
list.
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from potato.flask_server import load_training_data, get_training_instances


IMAGE_CONFIG = {
    "item_properties": {"id_key": "id", "text_key": "image_url"},
    "training": {"enabled": True, "data_file": "training.json"},
    "annotation_schemes": [
        {"name": "object_detection", "annotation_type": "image_annotation"}
    ],
}

TEXT_CONFIG = {
    "item_properties": {"id_key": "id", "text_key": "text"},
    "training": {"enabled": True, "data_file": "training.json"},
    "annotation_schemes": [{"name": "sentiment", "annotation_type": "radio"}],
}


def _load(config, instances):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"training_instances": instances}, f)
        path = f.name
    try:
        with patch("potato.flask_server.get_abs_or_rel_path", return_value=path):
            load_training_data(config)
        return get_training_instances()
    finally:
        os.unlink(path)


class TestTrainingInstanceFieldsSurvive:
    def test_text_key_field_reaches_the_item(self):
        items = _load(IMAGE_CONFIG, [{
            "id": "train_1",
            "image_url": "https://example.com/chart.png",
            "text": "Unemployment rate, 2019-2024.",
            "correct_answers": {"object_detection": "[]"},
        }])

        assert len(items) == 1
        assert items[0].get_data()["image_url"] == "https://example.com/chart.png"

    def test_displayed_text_comes_from_the_text_key_field(self):
        items = _load(IMAGE_CONFIG, [{
            "id": "train_1",
            "image_url": "https://example.com/chart.png",
            "text": "Unemployment rate, 2019-2024.",
            "correct_answers": {"object_detection": "[]"},
        }])

        assert items[0].get_data()["displayed_text"] == "https://example.com/chart.png"

    def test_text_key_field_alone_is_enough(self):
        """No `text` at all: the configured text_key is the question."""
        items = _load(IMAGE_CONFIG, [{
            "id": "train_1",
            "image_url": "https://example.com/chart.png",
            "correct_answers": {"object_detection": "[]"},
        }])

        assert items[0].get_data()["displayed_text"] == "https://example.com/chart.png"

    def test_neither_text_nor_text_key_is_an_error(self):
        with pytest.raises(Exception, match="neither 'text' nor"):
            _load(IMAGE_CONFIG, [{
                "id": "train_1",
                "correct_answers": {"object_detection": "[]"},
            }])

    def test_plain_text_project_is_unchanged(self):
        items = _load(TEXT_CONFIG, [{
            "id": "train_1",
            "text": "This is a positive sentiment text.",
            "correct_answers": {"sentiment": "positive"},
            "explanation": "Positive emotions.",
        }])

        data = items[0].get_data()
        assert data["text"] == "This is a positive sentiment text."
        assert data["displayed_text"] == "This is a positive sentiment text."
        assert data["explanation"] == "Positive emotions."

    def test_a_list_valued_question_is_still_formatted(self):
        """list_as_text formatting has to survive the loader change."""
        items = _load(TEXT_CONFIG, [{
            "id": "train_1",
            "text": ["First turn", "Second turn"],
            "correct_answers": {"sentiment": "positive"},
        }])

        displayed = items[0].get_data()["displayed_text"]
        assert "First turn" in displayed and "Second turn" in displayed
        assert not isinstance(items[0].get_data()["displayed_text"], list)


class _TrainingState:
    training_instances = ["train_1"]
    show_feedback = False
    feedback_message = ""
    feedback_type = "info"
    allow_retry = True

    def get_current_question_index(self):
        return 0

    def get_correct_answer_count(self):
        return 0

    def get_total_mistakes(self):
        return 0


class _UserState:
    """A user state whose current training instance returns fixed data."""

    def __init__(self, data):
        self._data = data

    def get_training_state(self):
        return _TrainingState()

    def get_current_training_instance(self):
        data = self._data

        class _Instance:
            def get_data(self):
                return data

            def get_id(self):
                return "train_1"

        return _Instance()


class TestTrainingPageContextResolvesTheQuestion:
    """The page reads `displayed_text`, which the loader now derives correctly."""

    def test_the_page_gets_the_image_url(self):
        from potato import flask_server

        # The shape load_training_data now produces for an image project:
        # displayed_text derived from the text_key field, not from `text`.
        user_state = _UserState({
            "image_url": "https://example.com/chart.png",
            "displayed_text": "https://example.com/chart.png",
            "text": "Unemployment rate, 2019-2024.",
        })

        with patch.object(flask_server, "config", IMAGE_CONFIG):
            context = flask_server._training_page_context(user_state)

        assert context["instance"] == "https://example.com/chart.png"
        assert context["instance_plain_text"] == "https://example.com/chart.png"

    def test_formatted_list_text_is_not_replaced_by_the_raw_list(self):
        """`displayed_text` stays ahead of the raw field for exactly this case."""
        from potato import flask_server

        user_state = _UserState({
            "displayed_text": "<b>A.</b> First turn <b>B.</b> Second turn",
            "text": ["First turn", "Second turn"],
        })

        with patch.object(flask_server, "config", TEXT_CONFIG):
            context = flask_server._training_page_context(user_state)

        assert context["instance"] == "<b>A.</b> First turn <b>B.</b> Second turn"

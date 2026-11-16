"""prior_answers: a participant's own earlier survey answers, shown on
annotation pages. Rendering, escaping and config validation."""

from collections import defaultdict

import pytest

from potato.item_state_management import Label
from potato.server_utils.config_module import ConfigValidationError
from potato.server_utils.prior_answers import (
    collect_prior_answers,
    render_prior_answer_blocks,
    validate_prior_answer_references,
    validate_prior_answers_block,
)


class _State:
    """The one attribute the reader uses."""

    def __init__(self, answers):
        self.phase_to_page_to_label_to_value = defaultdict(lambda: defaultdict(dict))
        for (phase, page), labels in answers.items():
            for (schema, name), value in labels.items():
                self.phase_to_page_to_label_to_value[phase][page][Label(schema, name)] = value


SCHEMES = [
    {"name": "definition", "annotation_type": "text",
     "description": "In your own words, how would you define populism?"},
    {"name": "party", "annotation_type": "radio", "labels": ["Left", "Right", "None"]},
    {"name": "media", "annotation_type": "multiselect", "labels": ["TV", "Radio", "Web"]},
    {"name": "optional_note", "annotation_type": "text"},
]


def _config(entries):
    return {"prior_answers": entries, "_surveyflow_schemes": SCHEMES}


def _state():
    return _State({
        ("prestudy", "pre"): {
            ("definition", "text_box"): "Elite vs. <b>the people</b> & more",
            ("party", "Left"): "Left",
            ("media", "TV"): "TV",
            ("media", "Web"): "Web",
        },
    })


def test_text_answer_is_escaped_and_titled_from_description():
    [block] = render_prior_answer_blocks(_config([{"schema": "definition"}]), _state())
    assert block["answer_html"] == "Elite vs. &lt;b&gt;the people&lt;/b&gt; &amp; more"
    assert block["title"] == "In your own words, how would you define populism?"
    assert block["collapsible"] is True
    assert block["open"] is False


def test_title_and_open_state_come_from_the_entry():
    [block] = render_prior_answer_blocks(_config([
        {"schema": "definition", "title": "Definition", "collapsed_default": False}]), _state())
    assert block["title"] == "Definition"
    assert block["open"] is True


def test_radio_shows_the_chosen_label():
    [block] = render_prior_answer_blocks(_config([{"schema": "party"}]), _state())
    assert block["answer_html"] == "Left"


def test_multiselect_shows_every_chosen_label():
    [block] = render_prior_answer_blocks(_config([{"schema": "media"}]), _state())
    assert block["answer_html"] == "TV<br>Web"


def test_unanswered_question_shows_no_block():
    assert render_prior_answer_blocks(_config([{"schema": "optional_note"}]), _state()) == []


def test_text_with_several_boxes_keeps_every_box():
    state = _State({("prestudy", "pre"): {
        ("definition", "core"): "anti-elitism", ("definition", "people"): "one will"}})
    [block] = render_prior_answer_blocks(_config([{"schema": "definition"}]), state)
    assert block["answer_html"] == "core: anti-elitism<br>people: one will"


def test_other_text_rides_along_with_the_choice():
    state = _State({("prestudy", "pre"): {
        ("party", "None"): "None", ("party", "free_response"): "Pirates"}})
    [block] = render_prior_answer_blocks(_config([{"schema": "party"}]), state)
    assert block["answer_html"] == "None<br>Pirates"


def test_collect_excludes_the_given_page():
    state = _State({("prestudy", "pre"): {("party", "Left"): "Left"},
                    ("poststudy", "post"): {("media", "TV"): "TV"}})
    assert collect_prior_answers(state, exclude=("poststudy", "post")) == {
        "party": {"Left": "Left"}}


@pytest.mark.parametrize("entries, message", [
    ("definition", "must be a list"),
    (["definition"], "must be a mapping"),
    ([{"title": "x"}], "schema must be a question name"),
    ([{"schema": "definition", "label": "x"}], "unknown key"),
    ([{"schema": "definition", "title": 3}], "title must be text"),
    ([{"schema": "definition", "collapsible": "yes"}], "collapsible must be true or false"),
])
def test_shape_errors(entries, message):
    with pytest.raises(ConfigValidationError, match=message):
        validate_prior_answers_block({"prior_answers": entries})


def test_valid_shape_passes():
    validate_prior_answers_block({"prior_answers": [
        {"schema": "definition", "title": "Definition",
         "collapsible": True, "collapsed_default": False}]})
    validate_prior_answers_block({})


def test_reference_must_be_a_survey_question():
    config = {"prior_answers": [{"schema": "nope"}],
              "annotation_schemes": [{"name": "stance"}]}
    with pytest.raises(ConfigValidationError, match="not a question on any survey page"):
        validate_prior_answer_references(config, SCHEMES)


def test_reference_to_an_annotation_scheme_is_refused():
    config = {"prior_answers": [{"schema": "stance"}],
              "annotation_schemes": [{"name": "stance"}]}
    with pytest.raises(ConfigValidationError, match="is an annotation scheme"):
        validate_prior_answer_references(config, SCHEMES + [{"name": "stance"}])


def test_reference_to_a_survey_question_passes():
    validate_prior_answer_references(
        {"prior_answers": [{"schema": "definition"}]}, SCHEMES)

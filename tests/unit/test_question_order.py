"""Per-participant question order on survey pages (randomize_questions)."""

import pytest
from bs4 import BeautifulSoup

from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_phase_flow_config,
    validate_phase_flow_references,
)
from potato.server_utils.question_order import apply_question_order
from potato.user_state_management import InMemoryUserState

NAMES = ["q1", "q2", "q3", "q4", "q5", "q6"]


def _page():
    forms = []
    for n in NAMES:
        form = (f'<form class="annotation-form radio" data-schema-name="{n}">'
                f'<input name="{n}:::x"></form>')
        if n == "q3":  # a display_logic wrapper around one question
            form = f'<div class="display-logic-container" data-schema-name="{n}">{form}</div>'
        forms.append(form)
    return BeautifulSoup(
        '<div id="annotation-forms"><h2 id="heading">Survey</h2>'
        + "".join(forms) + '<p id="footer">end</p></div>', "html.parser")


def _order(soup):
    return [f["data-schema-name"] for f in soup.find_all("form")]


def _config(spec=True):
    return {"phases": {"order": ["survey"],
                       "survey": {"type": "poststudy", "file": "s.json",
                                  "randomize_questions": spec}}}


def test_reorders_and_keeps_other_content_in_place():
    us = InMemoryUserState("alice", -1)
    soup = _page()
    order, newly = apply_question_order(_config(), us, "survey", soup)
    assert newly
    assert sorted(order) == NAMES
    assert _order(soup) == order
    children = [c for c in soup.find(id="annotation-forms").children if getattr(c, "name", None)]
    assert children[0].get("id") == "heading"
    assert children[-1].get("id") == "footer"
    # The wrapper travels with its question.
    wrapper = soup.find("div", class_="display-logic-container")
    assert wrapper.find("form")["data-schema-name"] == "q3"


def test_stable_for_a_participant_and_recorded():
    us = InMemoryUserState("bob", -1)
    first, _ = apply_question_order(_config(), us, "survey", _page())
    again, newly = apply_question_order(_config(), us, "survey", _page())
    assert again == first and not newly
    assert us.flow_record["question_orders"]["survey"] == first
    fresh = InMemoryUserState("bob", -1)
    assert apply_question_order(_config(), fresh, "survey", _page())[0] == first


def test_differs_across_participants():
    orders = {tuple(apply_question_order(_config(), InMemoryUserState(f"u{i}", -1),
                                         "survey", _page())[0]) for i in range(20)}
    assert len(orders) > 1


def test_pins():
    spec = {"pin_first": ["q6"], "pin_last": ["q1"]}
    for i in range(10):
        order, _ = apply_question_order(_config(spec), InMemoryUserState(f"p{i}", -1),
                                        "survey", _page())
        assert order[0] == "q6" and order[-1] == "q1"


def test_page_without_flag_untouched():
    soup = _page()
    cfg = {"phases": {"order": ["survey"], "survey": {"type": "poststudy", "file": "s.json"}}}
    assert apply_question_order(cfg, InMemoryUserState("c", -1), "survey", soup) == (None, False)
    assert _order(soup) == NAMES


@pytest.mark.parametrize("spec", ["yes", 3, {"pin_first": "q1"}, {"shuffle": True}])
def test_bad_spec_refused(spec):
    with pytest.raises(ConfigValidationError):
        validate_phase_flow_config(_config(spec))


def test_unknown_pin_refused_at_boot():
    with pytest.raises(ConfigValidationError, match="not a question on that page"):
        validate_phase_flow_references(_config({"pin_first": ["nope"]}),
                                       {"survey": [{"name": n} for n in NAMES]})

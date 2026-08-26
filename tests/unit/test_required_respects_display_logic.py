"""
A required scheme hidden by `display_logic` must not block saving.

Found by an agent building a task from a plain-English brief. It wrote the
shape the documentation recommends -- a gate question, follow-ups behind
`display_logic`, everything required -- and produced a task where an annotator
who picked the "no" branch could never leave the item. `/updateinstance`
answered 400 with `Required annotation(s) not completed: <hidden scheme>`, and
the page showed nothing at all.

The task validated, previewed and screenshotted clean, because none of those
look at what happens after a click. That is what makes this worth a test rather
than a note in the docs: every static check passed.

`require_fully_annotated: false` does not help. The block comes from
`label_requirement` on the scheme, and the fix belongs there too -- the check
now asks `display_logic` whether the scheme is on screen before demanding an
answer to it.
"""

from unittest.mock import patch

import pytest


class FakeLabel:
    """Stands in for the Label objects a user state keys annotations by."""

    def __init__(self, schema, name):
        self._schema = schema
        self._name = name

    def get_schema(self):
        return self._schema

    def get_name(self):
        return self._name


class FakeUserState:
    def __init__(self, annotations=None):
        self.instance_id_to_label_to_value = annotations or {}
        self.instance_id_to_span_to_value = {}


GATE = {
    "annotation_type": "radio",
    "name": "seeking_support",
    "description": "Is this person seeking support?",
    "labels": ["Yes", "No"],
    "label_requirement": {"required": True},
}

FOLLOW_UP = {
    "annotation_type": "multiselect",
    "name": "support_types",
    "description": "Which kinds?",
    "labels": ["Information", "Emotional"],
    "label_requirement": {"required": True},
    "display_logic": {
        "show_when": [
            {"schema": "seeking_support", "operator": "equals", "value": "Yes"}
        ]
    },
}


def _unsatisfied(schemes, annotations):
    from potato import flask_server

    with patch.object(flask_server, "config", {"annotation_schemes": schemes}):
        return flask_server._instance_meets_required_annotation_rules(
            FakeUserState(annotations), "item1"
        )


class TestTheHiddenBranch:
    def test_answering_no_does_not_demand_the_hidden_follow_up(self):
        """The bug, exactly as an annotator hit it."""
        annotations = {"item1": {FakeLabel("seeking_support", "No"): True}}
        assert _unsatisfied([GATE, FOLLOW_UP], annotations) == [], (
            "picking the branch that hides the follow-up left it 'required', "
            "so every save is refused and the annotator cannot move on"
        )

    def test_answering_yes_still_demands_the_follow_up(self):
        """The fix must not turn the requirement off altogether."""
        annotations = {"item1": {FakeLabel("seeking_support", "Yes"): True}}
        assert _unsatisfied([GATE, FOLLOW_UP], annotations) == ["support_types"]

    def test_answering_yes_and_the_follow_up_satisfies_both(self):
        annotations = {
            "item1": {
                FakeLabel("seeking_support", "Yes"): True,
                FakeLabel("support_types", "Emotional"): True,
            }
        }
        assert _unsatisfied([GATE, FOLLOW_UP], annotations) == []

    def test_the_gate_itself_is_still_required(self):
        assert _unsatisfied([GATE, FOLLOW_UP], {"item1": {}}) == ["seeking_support"]


class TestItDoesNotBreakTheOrdinaryCase:
    def test_no_display_logic_anywhere_behaves_as_before(self):
        plain = dict(GATE)
        assert _unsatisfied([plain], {"item1": {}}) == ["seeking_support"]
        answered = {"item1": {FakeLabel("seeking_support", "Yes"): True}}
        assert _unsatisfied([plain], answered) == []

    def test_an_optional_hidden_scheme_is_still_not_demanded(self):
        optional = dict(FOLLOW_UP)
        optional.pop("label_requirement")
        annotations = {"item1": {FakeLabel("seeking_support", "No"): True}}
        assert _unsatisfied([GATE, optional], annotations) == []

    def test_a_broken_display_logic_block_fails_open(self):
        """A condition that cannot be evaluated must not lock the annotator out.

        Failing closed here would reproduce the original bug for anyone with a
        malformed block, which validation would normally have rejected -- but
        this path also runs for configs loaded by other routes.
        """
        broken = dict(FOLLOW_UP)
        broken["display_logic"] = {"show_when": "not a list"}
        annotations = {"item1": {FakeLabel("seeking_support", "No"): True}}
        result = _unsatisfied([GATE, broken], annotations)
        assert result in ([], ["support_types"])


class TestMultiselectValues:
    """A multiselect contributes several labels; conditions still have to work."""

    def test_a_condition_on_a_multiselect_sees_every_ticked_label(self):
        chained = {
            "annotation_type": "text",
            "name": "explain",
            "description": "Why?",
            "label_requirement": {"required": True},
            "display_logic": {
                "show_when": [
                    {"schema": "support_types", "operator": "contains",
                     "value": "Emotional"}
                ]
            },
        }
        annotations = {
            "item1": {
                FakeLabel("seeking_support", "Yes"): True,
                FakeLabel("support_types", "Information"): True,
                FakeLabel("support_types", "Emotional"): True,
            }
        }
        assert "explain" in _unsatisfied([GATE, FOLLOW_UP, chained], annotations), (
            "a condition matching one of several ticked labels should show the "
            "scheme, which makes its answer genuinely required"
        )

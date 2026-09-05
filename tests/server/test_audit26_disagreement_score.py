"""
`_calculate_disagreement_score` returned 0.0 for every item, always.

Audit 26. `get_label_annotations` returns the FLAT ``{Label: value}``
container, and the loop unpacked it two names at a time as though it were
``{schema_name: [label, ...]}``. So ``schema`` bound to a Label object and
``labels`` bound to the *value string*, which the comprehension then iterated
one character at a time: a1's "eligible" became ``('b','e','e','g','i','i',
'l','l')``.

The result is not noise, it is a constant zero, and for two reasons at once:

* When two annotators agree they carry the same Label key, so the tuples match,
  ``distinct`` is 1, and the ratio is ``(1-1)/(2-1) = 0``.
* When they DISAGREE their answers are different Label keys --
  ``eligibility/eligible`` against ``eligibility/ineligible`` -- so each key
  holds exactly one user, the group is skipped for having fewer than two, and
  the function returns 0.0 with nothing collected.

Two documented features consume it and neither has ever worked:
``AssignmentStrategy.MAX_DIVERSITY``, whose docstring says it "prioritizes
items with high disagreement" and which sorts by an all-zero key, and
``adaptive_boost``, whose threshold defaults to 0.5 and is never cleared.

Fixture note: annotators who agree cannot catch this, because the broken code
and the correct code both return 0.0 for them. Every assertion below that
matters rests on an item two people answered differently.
"""

import time

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


# item 1: both say eligible, both tick {age}          -> agreement
# item 2: eligible vs ineligible                      -> disagreement
# item 3: {age} vs {age, meds}                         -> set disagreement
ANSWERS = {
    "a1": [("eligible", ["age"]), ("eligible", ["age"]), ("eligible", ["age"])],
    "a2": [("eligible", ["age"]), ("ineligible", ["age"]),
           ("eligible", ["age", "meds"])],
}


@pytest.fixture(scope="module")
def disagreement_server():
    schemes = [
        {
            "annotation_type": "radio",
            "name": "eligibility",
            "description": "Is this patient eligible?",
            "labels": ["eligible", "ineligible", "nei"],
        },
        {
            "annotation_type": "multiselect",
            "name": "reasons",
            "description": "Why?",
            "labels": ["age", "meds"],
        },
    ]
    with TestConfigManager("audit26_disagreement", schemes,
                           num_instances=3, num_annotators_per_item=2) as cfg:
        server = FlaskTestServer(port=9051, config_file=cfg.config_path,
                                 debug=True)
        if not server.start():
            pytest.fail("Failed to start server")

        for annotator in ("a1", "a2"):
            session = requests.Session()
            session.post(f"{server.base_url}/register",
                         data={"email": f"{annotator}@lab.org", "pass": "pw"})
            session.post(f"{server.base_url}/auth",
                         data={"email": f"{annotator}@lab.org", "pass": "pw"})
            session.get(f"{server.base_url}/annotate")
            for index in range(3):
                choice, reasons = ANSWERS[annotator][index]
                payload = {f"eligibility:::{choice}": "true"}
                payload.update({f"reasons:::{r}": "true" for r in reasons})
                response = session.post(
                    f"{server.base_url}/updateinstance",
                    json={"instance_id": str(index + 1),
                          "annotations": payload})
                assert response.status_code == 200, response.text
        time.sleep(0.2)
        yield server
        server.stop()


def _score(instance_id):
    """The manager is in-process, so the test can call the real method."""
    from potato.item_state_management import get_item_state_manager
    return get_item_state_manager()._calculate_disagreement_score(instance_id)


class TestDisagreementScore:

    def test_two_annotators_are_registered_on_every_item(
            self, disagreement_server):
        """Guards the guard: the function returns 0.0 early when fewer than
        two annotators have rated an item, which would make every assertion
        below pass for the wrong reason."""
        from potato.item_state_management import get_item_state_manager
        manager = get_item_state_manager()
        for instance_id in ("1", "2", "3"):
            annotators = manager.instance_annotators.get(instance_id, ())
            assert len(annotators) == 2, (instance_id, annotators)

    def test_a_disagreement_on_a_radio_scores_above_zero(
            self, disagreement_server):
        """eligible against ineligible, two annotators.

        This is the whole finding: the old code put those in separate Label
        keys, saw one user in each, skipped both, and returned 0.0.
        """
        assert _score("2") == pytest.approx(1.0)

    def test_a_disagreement_on_a_multiselect_scores_above_zero(
            self, disagreement_server):
        """{age} against {age, meds} is one disagreement, not two.

        Grouping by Label rather than by schema also split a multiselect's
        ticked labels into separate groups, so the set was never compared as a
        set even once the character iteration was fixed.
        """
        assert _score("3") == pytest.approx(1.0)

    def test_agreement_still_scores_zero(self, disagreement_server):
        """The control. Both annotators gave the same answer to both schemas,
        so a correct measure returns 0.0 here -- and so does the broken one,
        which is why this test alone proves nothing."""
        assert _score("1") == pytest.approx(0.0)

    def test_the_score_orders_disagreement_above_agreement(
            self, disagreement_server):
        """What MAX_DIVERSITY actually needs. It sorts by this key, so a
        constant makes it degenerate to dict order however large the study."""
        ordered = sorted(("1", "2", "3"), key=_score, reverse=True)
        assert ordered[-1] == "1", ordered
        assert _score("2") > _score("1")
        assert _score("3") > _score("1")

    def test_the_score_clears_the_adaptive_boost_threshold(
            self, disagreement_server):
        """adaptive_boost fires at 0.5 by default, and 0.0 never reaches it,
        so the boost has never triggered under any configuration."""
        assert _score("2") >= 0.5


# The span branch of the same function unpacked the same way, against
# `{SpanAnnotation: value}`. The auditor did not report it -- only the label
# branch -- but it is the identical mistake two lines down, and the old code
# also overwrote a user's entry once per span rather than accumulating, so a
# user who drew two spans was compared on whichever one came last.
SPANS = {
    "a1": [
        [{"schema": "mentions", "name": "drug", "title": "drug",
          "start": 0, "end": 7, "value": "drug"}],
        [{"schema": "mentions", "name": "drug", "title": "drug",
          "start": 0, "end": 7, "value": "drug"}],
    ],
    "a2": [
        [{"schema": "mentions", "name": "drug", "title": "drug",
          "start": 0, "end": 7, "value": "drug"}],
        [{"schema": "mentions", "name": "drug", "title": "drug",
          "start": 8, "end": 12, "value": "drug"}],
    ],
}


@pytest.fixture(scope="module")
def span_server():
    schemes = [{
        "annotation_type": "span",
        "name": "mentions",
        "description": "Mark the mentions",
        "labels": ["drug"],
    }]
    with TestConfigManager("audit26_disagreement_spans", schemes,
                           num_instances=2, num_annotators_per_item=2) as cfg:
        server = FlaskTestServer(port=9052, config_file=cfg.config_path,
                                 debug=True)
        if not server.start():
            pytest.fail("Failed to start server")

        for annotator in ("a1", "a2"):
            session = requests.Session()
            session.post(f"{server.base_url}/register",
                         data={"email": f"{annotator}@lab.org", "pass": "pw"})
            session.post(f"{server.base_url}/auth",
                         data={"email": f"{annotator}@lab.org", "pass": "pw"})
            session.get(f"{server.base_url}/annotate")
            for index in range(2):
                response = session.post(
                    f"{server.base_url}/updateinstance",
                    json={"instance_id": str(index + 1),
                          "annotations": {},
                          "span_annotations": SPANS[annotator][index]})
                assert response.status_code == 200, response.text
        time.sleep(0.2)
        yield server
        server.stop()


class TestDisagreementScoreOverSpans:

    def test_identical_spans_score_zero(self, span_server):
        """The control: both drew 0-7, so a correct measure says they agree."""
        assert _score("1") == pytest.approx(0.0)

    def test_different_spans_score_above_zero(self, span_server):
        """0-7 against 8-12 on the same schema and label.

        The old loop bound `schema` to a SpanAnnotation and `spans` to the
        value string, so it compared sorted characters of "drug" -- identical
        for both annotators, which reads as agreement.
        """
        assert _score("2") == pytest.approx(1.0)

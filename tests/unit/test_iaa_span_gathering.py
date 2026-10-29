"""
Span agreement must see spans saved the way the server saves them.

``UserState.get_span_annotations(iid)`` returns a flat ``{SpanAnnotation:
value}`` for every span scheme on the item. ``_gather_spans`` read it as
``{scheme: [spans]}``, found nothing, and every span measure at /admin/iaa was
n/a over 0 items. The earlier tests passed because their fake returned the
grouped shape. These use real ``InMemoryUserState`` objects.
"""

from __future__ import annotations

import math

from potato.item_state_management import SpanAnnotation
from potato.phase import UserPhase
from potato.server_utils.iaa import dispatcher
from potato.user_state_management import InMemoryUserState
from tests.unit.test_iaa_dispatcher_gathering import FakeISM, FakeUSM

NER = {"annotation_type": "span", "name": "ner", "description": "Entities",
       "labels": ["PER", "LOC"]}


def _state(uid, spans_by_item):
    state = InMemoryUserState(uid)
    state.current_phase_and_page = (UserPhase.ANNOTATION, "annotation")
    for iid, spans in spans_by_item.items():
        for schema, label, start, end in spans:
            state.add_span_annotation(
                iid, SpanAnnotation(schema, label, label, start, end), True)
    return state


def _metrics(spans_by_user):
    states = {uid: _state(uid, items) for uid, items in spans_by_user.items()}
    iids = sorted({iid for items in spans_by_user.values() for iid in items})
    report = dispatcher.compute_overlap_iaa(
        FakeISM(iids, list(states)), FakeUSM(states),
        {"annotation_schemes": [NER]})
    return report["schemas"]["ner"]["metrics"]


def test_identical_spans_agree():
    spans = {"i1": [("ner", "PER", 0, 3)], "i2": [("ner", "LOC", 4, 9)]}
    metrics = _metrics({"a": spans, "b": spans})
    assert metrics["n_items"] == 2
    assert metrics["span_f1_exact"] == 1.0


def test_different_spans_disagree():
    metrics = _metrics({
        "a": {"i1": [("ner", "PER", 0, 3)]},
        "b": {"i1": [("ner", "LOC", 10, 15)]},
    })
    assert metrics["n_items"] == 1
    assert metrics["span_f1_exact"] == 0.0
    assert not math.isnan(metrics["token_level_kappa"])


def test_another_schemes_spans_are_not_counted():
    # b's only span on i1 belongs to a different scheme, so on "ner" b marked
    # nothing and a's entity is a miss.
    metrics = _metrics({
        "a": {"i1": [("ner", "PER", 0, 3)]},
        "b": {"i1": [("topic", "PER", 0, 3)]},
    })
    assert metrics["n_items"] == 1
    assert metrics["span_f1_exact"] == 0.0

"""
Agreement on span links, coreference chains and events.

These schemes were classified as span schemes, so ``/admin/iaa`` looked for
spans saved under the link scheme's own name. Their answers are links (or
events) in the user state's link and event stores, over spans saved under
``span_schema``, so nothing was found and the schemes were never scored.
These tests save annotations the way ``/updateinstance`` does, on real
``InMemoryUserState`` objects, with different browser-assigned ids per
annotator.
"""

from __future__ import annotations

import math

from potato.item_state_management import EventAnnotation, SpanAnnotation, SpanLink
from potato.phase import UserPhase
from potato.server_utils.iaa import dispatcher
from potato.server_utils.iaa.dispatcher import SchemaKind, classify_schema
from potato.user_state_management import InMemoryUserState
from tests.unit.test_iaa_dispatcher_gathering import FakeISM, FakeUSM

MENTIONS = {"annotation_type": "span", "name": "mentions",
            "description": "Mentions", "labels": ["PER", "ORG"]}
COREF = {"annotation_type": "coreference", "name": "coref",
         "description": "Chains", "span_schema": "mentions"}
LINKS = {"annotation_type": "span_link", "name": "rels",
         "description": "Relations", "span_schema": "mentions",
         "link_types": [{"name": "WORKS_FOR", "directed": True}]}
EVENTS = {"annotation_type": "event_annotation", "name": "events",
          "description": "Events", "span_schema": "mentions",
          "event_types": [{"type": "HIRE", "arguments": [{"role": "employer"}]}]}

# (start, end, label) per mention; offsets into FakeItem's text.
SPANS = [(0, 3, "PER"), (4, 9, "PER"), (10, 15, "ORG")]


def _state(uid, iid, spans=SPANS, chains=(), links=(), events=()):
    """Save *spans* and the structures over them, each with ids private to
    this annotator, as two browsers would assign them."""
    state = InMemoryUserState(uid)
    state.current_phase_and_page = (UserPhase.ANNOTATION, "annotation")
    ids = []
    for n, (start, end, label) in enumerate(spans):
        span = SpanAnnotation("mentions", label, label, start, end,
                              id=f"{uid}-span-{n}")
        state.add_span_annotation(iid, span, True)
        ids.append(span.get_id())
    for chain in chains:
        state.add_link_annotation(iid, SpanLink(
            "coref", "coreference", [ids[p] for p in chain]))
    for head, dependent in links:
        state.add_link_annotation(iid, SpanLink(
            "rels", "WORKS_FOR", [ids[head], ids[dependent]],
            direction="directed"))
    for trigger, argument in events:
        state.add_event_annotation(iid, EventAnnotation(
            "events", "HIRE", ids[trigger],
            [{"role": "employer", "span_id": ids[argument]}]))
    return state


def _report(scheme, states):
    report = dispatcher.compute_overlap_iaa(
        FakeISM(["i1"], list(states)), FakeUSM(states),
        {"annotation_schemes": [MENTIONS, scheme]})
    return report["schemas"][scheme["name"]]


def test_link_types_have_their_own_kinds():
    assert classify_schema(COREF) == SchemaKind.COREFERENCE
    assert classify_schema(LINKS) == SchemaKind.RELATION
    assert classify_schema(EVENTS) == SchemaKind.EVENT


def test_identical_coreference_chains_are_scored_as_agreement():
    states = {uid: _state(uid, "i1", chains=[(0, 1)]) for uid in ("a", "b")}
    schema = _report(COREF, states)
    metrics = schema["metrics"]
    assert schema["kind"] == "coreference"
    assert metrics["n_items"] == 1
    assert metrics["n_annotators"] == 2
    assert metrics["n_pairs"] == 1
    assert metrics["conll_f1"] == 1.0
    assert metrics["muc_f1"] == 1.0


def test_different_coreference_chains_score_below_one():
    states = {"a": _state("a", "i1", chains=[(0, 1)]),
              "b": _state("b", "i1", chains=[(1, 2)])}
    metrics = _report(COREF, states)["metrics"]
    assert metrics["n_items"] == 1
    assert metrics["muc_f1"] == 0.0
    assert 0.0 < metrics["conll_f1"] < 1.0


def test_identical_links_agree_and_a_missing_link_does_not():
    same = {uid: _state(uid, "i1", links=[(0, 2)]) for uid in ("a", "b")}
    assert _report(LINKS, same)["metrics"]["link_f1"] == 1.0
    # b drew the same mentions and saved the item, but linked nothing.
    apart = {"a": _state("a", "i1", links=[(0, 2)]),
             "b": _state("b", "i1")}
    metrics = _report(LINKS, apart)["metrics"]
    assert metrics["n_items"] == 1
    assert metrics["link_f1"] == 0.0
    assert metrics["mention_f1"] == 1.0


def test_identical_events_agree():
    states = {uid: _state(uid, "i1", events=[(1, 2)]) for uid in ("a", "b")}
    metrics = _report(EVENTS, states)["metrics"]
    assert metrics["n_items"] == 1
    assert metrics["trigger_f1"] == 1.0
    assert metrics["argument_f1"] == 1.0


def test_no_overlapping_answers_reports_nan_with_a_note():
    states = {uid: _state(uid, "i1", spans=[]) for uid in ("a", "b")}
    metrics = _report(COREF, states)["metrics"]
    assert metrics["n_items"] == 0
    assert math.isnan(metrics["conll_f1"])
    assert metrics["note"]


def test_multi_document_event_is_not_scored():
    scheme = {"annotation_type": "multi_document_event", "name": "events",
              "description": "Cross-document events", "slots": []}
    assert classify_schema(scheme) == SchemaKind.UNSUPPORTED
    report = dispatcher.compute_overlap_iaa(
        FakeISM(["i1"], ["a", "b"]),
        FakeUSM({uid: _state(uid, "i1") for uid in ("a", "b")}),
        {"annotation_schemes": [scheme]})
    assert "events" not in report["schemas"]


def test_both_annotators_drawing_no_links_agree():
    """Audit 105 B8: identical mentions and no links on either side scored
    link_f1 0 and muc_f1 0, total disagreement on what they agreed on."""
    states = {uid: _state(uid, "i1") for uid in ("a", "b")}
    links = _report(LINKS, states)["metrics"]
    if links["n_pairs"]:
        assert links["link_f1"] == 1.0 and links["mention_f1"] == 1.0
    coref = _report(COREF, states)["metrics"]
    if coref["n_pairs"]:
        assert coref["muc_f1"] == 1.0 and coref["conll_f1"] == 1.0
    assert links["n_pairs"] or coref["n_pairs"], "nothing was compared"

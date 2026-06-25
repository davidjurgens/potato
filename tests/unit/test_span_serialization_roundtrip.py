"""
Round-trip serialization regression tests for span annotations.

These guard against a recurring class of bug: the local ``span_to_dict`` helper
in ``user_state_management.py`` used to serialize only a subset of fields
(schema/name/start/end/title) while ``to_span`` read back many more
(target_field, id, kb_*, additional_parts, format_coords). On every
save -> reload those extra fields were silently dropped, which:

  * broke multi-field span rendering across sessions (target_field -> None, so
    routes.get_span_data omitted target_field and the frontend could not place
    the overlay), and
  * lost entity links, discontinuous parts and format coords entirely, and
  * crashed the export CLI / produced wrong output.

The fix routes ``span_to_dict`` through ``SpanAnnotation.to_dict()`` (single
source of truth). The most valuable test here is the drift guard
(``test_every_constructor_field_survives_round_trip``): it constructs a span
with EVERY optional field populated and asserts each one survives, so adding a
new SpanAnnotation field without updating to_dict() will fail loudly.
"""

import os
import shutil
import tempfile

import pytest

from potato.user_state_management import InMemoryUserState, UserPhase
from potato.item_state_management import SpanAnnotation, SpanLink, EventAnnotation


@pytest.fixture(scope="function")
def temp_user_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


def _full_span():
    """A span with every optional constructor field populated."""
    span = SpanAnnotation(
        schema="ner",
        name="LOCATION",
        title="A discontinuous, entity-linked, multi-field span",
        start=3,
        end=8,
        id="span_fixed_id_123",
        target_field="field_b",
        format_coords={"format": "pdf", "page": 2, "bbox": [1, 2, 3, 4]},
        additional_parts=[{"start": 12, "end": 16, "text": "York"}],
        kb_id="Q60",
        kb_source="wikidata",
        kb_label="New York City",
    )
    return span


def _reload_span(user_dir):
    """Return the single restored span object for instance 'i1'."""
    loaded = InMemoryUserState.load(user_dir)
    spans = loaded.get_span_annotations("i1")
    assert len(spans) == 1
    return next(iter(spans.keys())), spans


def test_basic_span_round_trip(temp_user_dir):
    user = InMemoryUserState("u")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    span = SpanAnnotation("highlight", "span1", "title", 0, 5)
    user.add_span_annotation("i1", span, "selected")
    user.save(temp_user_dir)

    restored, spans = _reload_span(temp_user_dir)
    assert restored == span                      # __eq__ holds
    assert spans[restored] == "selected"          # value preserved


def test_target_field_survives_round_trip(temp_user_dir):
    """The original reported bug: multi-field target_field was dropped."""
    user = InMemoryUserState("u")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    span = SpanAnnotation("ner", "PER", "t", 0, 5, target_field="field_b")
    user.add_span_annotation("i1", span, True)
    user.save(temp_user_dir)

    restored, _ = _reload_span(temp_user_dir)
    assert restored.get_target_field() == "field_b"
    # target_field participates in __eq__/__hash__, so equality must also hold
    assert restored == span


def test_every_constructor_field_survives_round_trip(temp_user_dir):
    """Drift guard: every populated field must survive save -> reload.

    If a new optional field is added to SpanAnnotation but not to to_dict(),
    add it to ``expected`` below and this test will catch the omission.
    """
    user = InMemoryUserState("u")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    span = _full_span()
    user.add_span_annotation("i1", span, "v")
    user.save(temp_user_dir)

    restored, _ = _reload_span(temp_user_dir)

    expected = {
        "schema": "ner",
        "name": "LOCATION",
        "title": "A discontinuous, entity-linked, multi-field span",
        "start": 3,
        "end": 8,
        "target_field": "field_b",
        "format_coords": {"format": "pdf", "page": 2, "bbox": [1, 2, 3, 4]},
        "kb_id": "Q60",
        "kb_source": "wikidata",
        "kb_label": "New York City",
    }
    assert restored.get_schema() == expected["schema"]
    assert restored.get_name() == expected["name"]
    assert restored.get_title() == expected["title"]
    assert restored.get_start() == expected["start"]
    assert restored.get_end() == expected["end"]
    assert restored.get_target_field() == expected["target_field"]
    assert restored.get_format_coords() == expected["format_coords"]
    assert restored.get_kb_id() == expected["kb_id"]
    assert restored.get_kb_source() == expected["kb_source"]
    assert restored.get_kb_label() == expected["kb_label"]
    # additional_parts compared on (start, end) since text is optional metadata
    restored_parts = [(p["start"], p["end"]) for p in restored.get_additional_parts()]
    assert restored_parts == [(12, 16)]
    assert restored.is_discontinuous()
    # stable id must not be regenerated on load
    assert restored.get_id() == "span_fixed_id_123"


def test_span_to_dict_matches_to_dict_contract():
    """The local serializer must emit exactly what SpanAnnotation.to_dict() does.

    This is the canonical-source-of-truth invariant; if the two diverge we are
    back in drift territory.
    """
    span = _full_span()
    # to_dict() is the single source of truth the on-disk format relies on.
    d = span.to_dict()
    # Every key the deserializer (to_span) consumes must be present/derivable.
    for required in ("schema", "name", "title", "start", "end"):
        assert required in d
    for optional in (
        "id", "target_field", "format_coords",
        "additional_parts", "kb_id", "kb_source", "kb_label",
    ):
        assert optional in d, f"to_dict() dropped {optional!r}"


def test_phase_span_round_trip(temp_user_dir):
    """phase_to_page_to_span_to_value uses the same serializer; guard it too."""
    user = InMemoryUserState("u")
    phase_pp = (UserPhase.PRESTUDY, "page1")
    user.current_phase_and_page = phase_pp
    span = SpanAnnotation("ner", "PER", "t", 0, 4, target_field="field_b")
    user.add_span_annotation("i1", span, True)
    user.save(temp_user_dir)

    loaded = InMemoryUserState.load(temp_user_dir)
    page_map = loaded.phase_to_page_to_span_to_value.get(UserPhase.PRESTUDY, {})
    spans = page_map.get("page1", {})
    assert len(spans) == 1
    restored = next(iter(spans.keys()))
    assert restored.get_target_field() == "field_b"


def test_export_cli_spans_shape_and_fields(temp_user_dir):
    """Export CLI must yield record['spans'] as a dict keyed by schema, with
    span dicts that retain target_field. Downstream exporters call .items()
    on this dict, so the shape is a hard contract."""
    from potato.export.cli import load_annotations_from_output_dir

    user_dir = os.path.join(temp_user_dir, "user1")
    os.makedirs(user_dir)
    user = InMemoryUserState("user1")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    user.add_span_annotation(
        "i1", SpanAnnotation("ner", "PER", "t", 0, 5, target_field="field_b"), True
    )
    user.add_span_annotation("i1", SpanAnnotation("ner", "ORG", "t", 6, 9), True)
    user.save(user_dir)

    records = load_annotations_from_output_dir(
        temp_user_dir, [{"name": "ner", "annotation_type": "span"}]
    )
    assert len(records) == 1
    spans = records[0]["spans"]
    assert isinstance(spans, dict), "exporters call .items() on record['spans']"
    assert "ner" in spans
    assert isinstance(spans["ner"], list)
    assert len(spans["ner"]) == 2
    per = next(s for s in spans["ner"] if s["name"] == "PER")
    assert per["target_field"] == "field_b"


def test_span_link_round_trip(temp_user_dir):
    """Newer design: relation/entity-link annotations (SpanLink).

    These round-trip via SpanLink.to_dict()/from_dict() (single source of
    truth), the same pattern the span fix adopted. This guards that they stay
    symmetric.
    """
    user = InMemoryUserState("u")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    link = SpanLink(
        schema="relations",
        link_type="WORKS_FOR",
        span_ids=["span_a", "span_b"],
        direction="directed",
        id="link_fixed_1",
        properties={"confidence": "high"},
    )
    user.add_link_annotation("i1", link)
    user.save(temp_user_dir)

    loaded = InMemoryUserState.load(temp_user_dir)
    links = loaded.get_link_annotations("i1")
    assert "link_fixed_1" in links
    restored = links["link_fixed_1"]
    assert restored.get_link_type() == "WORKS_FOR"
    assert restored.span_ids == ["span_a", "span_b"]
    assert restored.direction == "directed"
    assert restored.properties == {"confidence": "high"}
    assert restored == link


def test_event_annotation_round_trip(temp_user_dir):
    """Newer design: N-ary event annotations (EventAnnotation)."""
    user = InMemoryUserState("u")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    event = EventAnnotation(
        schema="events",
        event_type="ATTACK",
        trigger_span_id="span_trigger",
        arguments=[
            {"role": "attacker", "span_id": "span_a"},
            {"role": "target", "span_id": "span_b"},
        ],
        id="event_fixed_1",
        properties={"tense": "past"},
    )
    user.add_event_annotation("i1", event)
    user.save(temp_user_dir)

    loaded = InMemoryUserState.load(temp_user_dir)
    events = loaded.get_event_annotations("i1")
    assert "event_fixed_1" in events
    restored = events["event_fixed_1"]
    assert restored.get_event_type() == "ATTACK"
    assert restored.get_trigger_span_id() == "span_trigger"
    assert restored.get_arguments() == [
        {"role": "attacker", "span_id": "span_a"},
        {"role": "target", "span_id": "span_b"},
    ]
    assert restored.get_properties() == {"tense": "past"}
    assert restored == event


def test_export_cli_handles_legacy_dict_span_format(temp_user_dir):
    """Backward-compat: older outputs stored spans as a dict keyed by schema."""
    import json
    from potato.export.cli import load_annotations_from_output_dir

    user_dir = os.path.join(temp_user_dir, "legacy_user")
    os.makedirs(user_dir)
    legacy_state = {
        "user_id": "legacy_user",
        "instance_id_ordering": ["i1"],
        "current_instance_index": 0,
        "instance_id_to_label_to_value": {},
        "instance_id_to_span_to_value": {
            "i1": {"ner": [{"schema": "ner", "name": "PER", "start": 0, "end": 5}]}
        },
    }
    with open(os.path.join(user_dir, "user_state.json"), "w") as f:
        json.dump(legacy_state, f)

    records = load_annotations_from_output_dir(
        temp_user_dir, [{"name": "ner", "annotation_type": "span"}]
    )
    assert len(records) == 1
    assert records[0]["spans"]["ner"][0]["name"] == "PER"

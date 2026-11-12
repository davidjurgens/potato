"""The three-way merge behind a team's shared answer.

A collaborative page saves its whole answer for the item. These pin what the
merge keeps from such a save: only what the member changed since the
revision their page shows, laid over the team's current answer.
"""

import json

from potato.collab.state import (
    diff,
    label_key,
    merge_payload,
    unapply,
)
from potato.server_utils.annotation_keys import split_annotation_key

RADIO = {"sentiment"}
MULTI = {"topics"}


def merge(payload, base, current):
    return merge_payload(payload, base, current, split_key=_split,
                         is_single_select=lambda s: s in RADIO,
                         is_multiselect=lambda s: s in MULTI)


def _split(key):
    # The server's reader needs config schema names; these tests use the
    # explicit ':::' form, which it reads without them.
    schema, sep, label = key.partition(":::")
    if sep:
        return schema, label
    schema, sep, label = key.partition(":")
    return (schema, label) if sep else None


def L(schema, label):
    return label_key(schema, label)


def span(sid, name="PER", start=0, end=4, value="true"):
    return {"span": {"schema": "ner", "name": name, "title": name, "start": start,
                     "end": end, "id": sid}, "value": value}


def payload_span(sid, name="PER", start=0, end=4, value="true"):
    return {"schema": "ner", "name": name, "title": name, "start": start, "end": end,
            "id": sid, "value": value}


class TestLabels:
    def test_a_stale_page_does_not_revert_a_teammates_radio(self):
        base = {L("sentiment", "neutral"): "neutral"}
        current = {L("sentiment", "negative"): "negative"}   # teammate changed it
        # My page still shows neutral and I edited only the note.
        mine = {"annotations": {"sentiment:::neutral": "neutral", "note:::text_box": "hi"}}

        result = merge(mine, base, current)

        assert "sentiment:::neutral" not in result.payload["annotations"]
        assert result.payload["annotations"]["note:::text_box"] == "hi"
        assert result.conflicts == []

    def test_my_radio_change_wins_and_is_reported_as_overwriting(self):
        base = {L("sentiment", "neutral"): "neutral"}
        current = {L("sentiment", "negative"): "negative"}
        mine = {"annotations": {"sentiment:::positive": "positive"}}

        result = merge(mine, base, current)

        assert result.payload["annotations"]["sentiment:::positive"] == "positive"
        assert result.payload["annotations"]["sentiment:::negative"] == ""
        assert [c["key"] for c in result.conflicts] == ["L:sentiment"]

    def test_different_checkboxes_both_survive(self):
        base = {L("topics", "sports"): "sports"}
        current = {L("topics", "sports"): "sports", L("topics", "art"): "art"}  # teammate
        mine = {"annotations": {"topics:::sports": "sports", "topics:::news": "news"}}

        result = merge(mine, base, current)

        sent = result.payload["annotations"]
        assert sent == {"topics:::sports": "sports", "topics:::art": "art",
                        "topics:::news": "news"}

    def test_unticking_the_last_box_names_the_scheme_as_cleared(self):
        base = {L("topics", "sports"): "sports"}
        mine = {"annotations": {}, "cleared_schemas": ["topics"]}

        result = merge(mine, base, dict(base))

        assert result.payload["annotations"] == {"topics:::sports": ""}
        assert result.payload["cleared_schemas"] == ["topics"]

    def test_a_cleared_text_box_is_sent_as_a_removal(self):
        base = {L("note", "text_box"): "old"}
        mine = {"annotations": {"note:::text_box": ""}}

        result = merge(mine, base, dict(base))

        assert result.payload["annotations"] == {"note:::text_box": ""}

    def test_an_unchanged_save_changes_nothing(self):
        base = {L("sentiment", "neutral"): "neutral", L("note", "text_box"): "x"}
        mine = {"annotations": {"sentiment:::neutral": "neutral", "note:::text_box": "x"}}

        result = merge(mine, base, dict(base))

        assert result.changed is False
        assert result.payload["annotations"] == {}

    def test_reordered_blob_json_is_not_a_change(self):
        shape = [{"type": "bbox", "label": "car", "coordinates": {"x": 1, "y": 2}}]
        base = {L("img", "_data"): json.dumps(shape)}
        theirs = [{"type": "bbox", "label": "car", "coordinates": {"x": 9, "y": 9}}]
        current = {L("img", "_data"): json.dumps(theirs)}
        # Same content as the base, keys in another order.
        resent = '[{"coordinates": {"y": 2, "x": 1}, "label": "car", "type": "bbox"}]'
        mine = {"annotations": {"img:::_data": resent}}

        result = merge(mine, base, current)

        assert result.changed is False


    def test_an_empty_canvas_does_not_clear_a_teammates_drawing(self):
        # The page loaded before the teammate drew; its widget saves "[]".
        theirs = [{"type": "bbox", "label": "person", "coordinates": {"x": 1}}]
        current = {L("img", "_data"): json.dumps(theirs)}
        mine = {"annotations": {"img:::_data": "[]"}}

        result = merge(mine, {}, current)

        assert result.changed is False
        assert result.payload["annotations"] == {}

    def test_clearing_my_own_drawing_still_goes_through(self):
        shape = [{"type": "bbox", "label": "car", "coordinates": {"x": 1}}]
        base = {L("img", "_data"): json.dumps(shape)}
        mine = {"annotations": {"img:::_data": "[]"}}

        result = merge(mine, base, dict(base))

        # Sent as the page sent it, which is what an ordinary save stores.
        assert result.payload["annotations"] == {"img:::_data": "[]"}


class TestSpans:
    def test_a_span_a_teammate_deleted_is_not_put_back(self):
        base = {"S:s1": span("s1")}
        current = {}                                    # teammate deleted it
        mine = {"annotations": {}, "span_annotations": [payload_span("s1")]}

        result = merge(mine, base, current)

        assert result.payload["span_annotations"] == []
        assert result.changed is False

    def test_a_new_span_goes_through(self):
        mine = {"annotations": {}, "span_annotations": [payload_span("s2", start=5, end=9)]}

        result = merge(mine, {}, {})

        assert [s["id"] for s in result.payload["span_annotations"]] == ["s2"]

    def test_deleting_a_span_my_page_showed_goes_through(self):
        base = {"S:s1": span("s1")}
        mine = {"annotations": {},
                "span_annotations": [dict(payload_span("s1"), value=None)]}

        result = merge(mine, base, dict(base))

        assert result.payload["span_annotations"][0]["value"] is None


class TestDiffAndUnapply:
    def test_unapply_restores_the_earlier_snapshot(self):
        first = {L("a", "x"): "1"}
        second = {L("a", "x"): "2", "S:s1": span("s1")}
        third = {"S:s1": span("s1", value="false")}
        ops1, ops2 = diff(first, second), diff(second, third)

        assert unapply(third, ops2) == second
        assert unapply(unapply(third, ops2), ops1) == first

    def test_diff_names_every_changed_key(self):
        ops = diff({L("a", "x"): "1", L("a", "y"): "1"}, {L("a", "x"): "2"})
        assert {op["key"]: (op["before"], op["after"]) for op in ops} == {
            L("a", "x"): ("1", "2"), L("a", "y"): ("1", None)}


def test_the_servers_key_reader_reads_both_spellings():
    """The interceptor passes the real reader; it must accept ':::' keys."""
    assert split_annotation_key("img:::_data") == ("img", "_data")

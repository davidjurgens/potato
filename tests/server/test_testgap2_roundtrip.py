"""
What the browser sends, what /updateinstance stores, and what comes back,
posted in the exact shapes annotation.js and span-core.js produce.

The earlier tests posted well-formed keys with plain ASCII names, never
cleared the last checkbox, and never put an entity, a tag or a doubled space
in front of a span.
"""

import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

SCHEMES = [
    {"name": "tags", "annotation_type": "multiselect", "description": "d", "labels": ["a", "b"]},
    {"name": "q1:topic", "annotation_type": "radio", "description": "d", "labels": ["pos", "neg"]},
    {"name": "rad", "annotation_type": "radio", "description": "d", "labels": ["a:::b", "c"]},
    {"name": "note", "annotation_type": "text", "description": "d"},
    {"name": "score", "annotation_type": "slider", "description": "d",
     "min_value": 0, "max_value": 10, "starting_value": 5},
    {"name": "ent", "annotation_type": "span", "description": "d", "labels": ["X"]},
]

TEXTS = {
    "ent": "R&amp;D team TARGET here",
    "tag": "<b>bold</b> then TARGET",
    "lt": "if x < y and y > z then TARGET wins",
    "ws": "two  spaces then TARGET end",
}


@pytest.fixture(scope="module")
def server():
    with TestConfigManager("tg2_roundtrip", SCHEMES, num_instances=4) as tc:
        # Replace the generated items with ones whose text needs care.
        import json
        with open(tc.data_file, "w") as f:
            for iid, text in TEXTS.items():
                f.write(json.dumps({"id": iid, "text": text}) + "\n")
        srv = FlaskTestServer(port=9810, config_file=tc.config_path)
        assert srv.start()
        yield srv
        srv.stop()


def _user(server, name):
    s = requests.Session()
    s.post(server.base_url + "/register", data={"email": name, "pass": "pw"})
    s.post(server.base_url + "/auth", data={"email": name, "pass": "pw"})
    s.get(server.base_url + "/annotate")
    return s


def _save(s, server, iid, annotations, **extra):
    return s.post(server.base_url + "/updateinstance",
                  json={"instance_id": iid, "annotations": annotations, **extra})


def _stored(s, server, iid):
    return s.get(server.base_url + "/get_annotations", params={"instance_id": iid}).json()


def _labels(username, iid):
    from potato.user_state_management import get_user_state_manager
    state = get_user_state_manager().get_user_state(username)
    return {(l.get_schema(), l.get_name()): v
            for l, v in (state.get_label_annotations(iid) or {}).items()}


class TestLabelsRoundTrip:
    def test_unticking_the_last_box_is_saved(self, server):
        s = _user(server, "ms_user")
        _save(s, server, "ent", {"tags:a": "a"})
        assert ("tags", "a") in _labels("ms_user", "ent")
        # What the page sends once the last box is unticked.
        r = _save(s, server, "ent", {}, cleared_schemas=["tags"])
        assert r.status_code == 200
        assert _labels("ms_user", "ent") == {}
        from potato.user_state_management import get_user_state_manager
        assert not get_user_state_manager().get_user_state("ms_user").has_annotated("ent")
        from potato.item_state_management import get_item_state_manager
        assert "ms_user" not in get_item_state_manager().instance_annotators.get("ent", set())

    def test_a_schema_name_with_a_colon_is_stored_under_that_schema(self, server):
        s = _user(server, "colon_user")
        _save(s, server, "ent", {"q1:topic:pos": "pos"})
        _save(s, server, "ent", {"q1:topic:neg": "neg"})
        assert _labels("colon_user", "ent") == {("q1:topic", "neg"): "neg"}

    def test_a_label_containing_the_blob_separator_is_its_own_label(self, server):
        s = _user(server, "sep_user")
        _save(s, server, "ent", {"rad:c": "c"})
        _save(s, server, "ent", {"rad:a:::b": "a:::b"})
        assert _labels("sep_user", "ent") == {("rad", "a:::b"): "a:::b"}

    def test_an_emptied_text_box_is_not_an_answer(self, server):
        s = _user(server, "text_user")
        _save(s, server, "ent", {"note:text_box": "hello"})
        _save(s, server, "ent", {"note:text_box": ""})
        assert _labels("text_user", "ent") == {}

    def test_a_slider_at_zero_is_reported(self, server):
        s = _user(server, "zero_user")
        _save(s, server, "ent", {"score:slider": 0})
        body = _stored(s, server, "ent")
        assert body["label_values"]["score"]["slider"] == 0
        assert body["label_annotations"]["score"] == ["slider"]

    def test_a_keyword_overlay_on_the_page_does_not_break_the_save(self, server):
        """extractSpanAnnotationsFromDOM used to post the AI keyword overlay."""
        s = _user(server, "kw_user")
        r = _save(s, server, "ent", {"q1:topic:pos": "pos"},
                  span_annotations=[{"schema": None, "name": None, "start": None, "end": None,
                                     "title": None, "value": "", "target_field": "", "id": None}])
        assert r.status_code == 200
        from potato.item_state_management import get_item_state_manager
        assert "kw_user" in get_item_state_manager().instance_annotators["ent"]


class TestSpanOffsets:
    """Offsets count the characters the browser shows."""

    @pytest.mark.parametrize("iid,start,end", [
        ("ent", 9, 15),    # R&D team TARGET
        ("tag", 10, 16),   # bold then TARGET
        ("lt", 24, 30),    # if x < y and y > z then TARGET
        ("ws", 16, 22),    # two spaces then TARGET
    ])
    def test_the_server_reads_the_same_words(self, server, iid, start, end):
        s = _user(server, f"span_{iid}")
        _save(s, server, iid, {}, span_annotations=[
            {"schema": "ent", "name": "X", "start": start, "end": end, "value": "TARGET"}])
        body = s.get(server.base_url + f"/api/spans/{iid}").json()
        assert body["text"][start:end] == "TARGET"
        assert [sp["text"] for sp in body["spans"]] == ["TARGET"]

    def test_the_reloaded_page_keeps_the_markup_intact(self, server):
        s = _user(server, "span_page")
        _save(s, server, "tag", {}, span_annotations=[
            {"schema": "ent", "name": "X", "start": 10, "end": 16, "value": "TARGET"}])
        page = ""
        for _ in range(len(TEXTS)):
            page = s.get(server.base_url + "/annotate").text
            if "then TARGET" in page and "<b>bold</b>" in page:
                break
            s.post(server.base_url + "/annotate", data={"action": "next_instance"})
        # The highlight wraps TARGET and nothing leaks out of the <b> tag.
        assert re.search(r'<span class="span-highlight[^>]*>TARGET</span>', page)
        assert "bold&gt;" not in page and "bold>" not in page

    def test_deleting_a_span_by_id_leaves_its_twin_in_another_field(self, server):
        s = _user(server, "span_delete")
        twins = [{"schema": "ent", "name": "X", "start": 0, "end": 3, "value": "x",
                  "target_field": field, "id": f"span_{field}"} for field in ("f1", "f2")]
        _save(s, server, "ent", {}, span_annotations=twins)
        s.post(server.base_url + "/updateinstance", json={
            "type": "span", "schema": "ent", "instance_id": "ent",
            "state": [{"id": "span_f1", "target_field": "f1", "name": "X",
                       "start": 0, "end": 3, "title": "X", "value": None}]})
        from potato.user_state_management import get_user_state_manager
        spans = get_user_state_manager().get_user_state("span_delete").get_span_annotations("ent")
        assert [sp.get_id() for sp in spans] == ["span_f2"]

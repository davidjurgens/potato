"""
Rooms on projects that are not text.

Two things were wrong, one of them destructive:

* `create_room` accepted any schema with a `labels` list. Image, video, audio
  and spatial schemas all have one — their class palettes — and closing an item
  writes the vote by *deleting* every annotation for that schema and storing
  `Label(schema, "car") = "true"`. Pointing rooms at `object_detection` fed a
  session that quietly replaced each member's geometry with a class name.
* the room page rendered the item as `item_text || "(no text)"`, so a norming
  session on an image project showed the literal string "(no text)" and asked
  the group to vote on it.
"""

import pytest

from potato.rooms.routes import _item_media, _item_text, votable_schema_error


def config_with(*schemes):
    return {"annotation_schemes": list(schemes),
            "item_properties": {"text_key": "text"}}


RADIO = {"name": "sarcasm", "annotation_type": "radio",
         "labels": ["Sarcastic", "Sincere"]}
LIKERT = {"name": "quality", "annotation_type": "likert", "size": 5,
          "labels": ["bad", "good"]}
MULTISELECT = {"name": "themes", "annotation_type": "multiselect",
               "labels": ["access", "cost"]}
IMAGE = {"name": "object_detection", "annotation_type": "image_annotation",
         "labels": ["car", "person"], "tools": ["bbox"]}
VIDEO = {"name": "events", "annotation_type": "video_annotation",
         "labels": ["goal", "foul"]}
AUDIO = {"name": "segments", "annotation_type": "audio_annotation",
         "labels": ["speech", "music"]}
SPATIAL = {"name": "cuboids", "annotation_type": "spatial_annotation",
           "labels": ["car", "cyclist"]}
SPAN = {"name": "codes", "annotation_type": "span", "labels": ["access"]}
ROLLOUT = {"name": "rollout", "annotation_type": "rollout_evaluation"}


class TestWhichSchemasCanBeVotedOn:
    @pytest.mark.parametrize("scheme", [RADIO, LIKERT, MULTISELECT],
                             ids=lambda s: s["annotation_type"])
    def test_label_schemas_are_allowed(self, scheme):
        assert votable_schema_error(config_with(scheme), scheme["name"]) is None

    @pytest.mark.parametrize("scheme", [IMAGE, VIDEO, AUDIO, SPATIAL, SPAN,
                                        ROLLOUT],
                             ids=lambda s: s["annotation_type"])
    def test_structured_schemas_are_refused(self, scheme):
        """These all carry a `labels` list, which is why 'has labels' failed."""
        error = votable_schema_error(config_with(scheme), scheme["name"])
        assert error is not None
        assert scheme["annotation_type"] in error
        assert "radio, likert or multiselect" in error

    def test_the_refusal_explains_the_consequence(self):
        error = votable_schema_error(config_with(IMAGE), "object_detection")
        assert "replace" in error and "existing work" in error

    def test_an_unknown_schema_is_named(self):
        error = votable_schema_error(config_with(RADIO), "nope")
        assert "No annotation scheme named 'nope'" == error


class TestTheItemIsActuallyShown:
    def test_an_image_item_reports_its_media(self):
        media = _item_media({"id": "img_1", "image_url": "media/cat.jpg"})
        assert media == {"kind": "image", "src": "media/cat.jpg"}

    def test_a_video_item(self):
        assert _item_media({"id": "v", "video_url": "clips/a.mp4"})["kind"] == "video"

    def test_an_audio_item(self):
        assert _item_media({"id": "a", "audio_url": "clips/a.wav"})["kind"] == "audio"

    def test_an_extension_is_enough_without_a_known_field_name(self):
        media = _item_media({"id": "x", "stimulus": "https://cdn/x.png?w=2"})
        assert media["kind"] == "image"

    def test_a_text_item_has_no_media(self):
        assert _item_media({"id": "t", "text": "hello"}) is None

    def test_a_sentence_is_not_mistaken_for_a_file(self):
        assert _item_media({"id": "t", "text": "a photo of a cat"}) is None


class TestRoomTextForMediaItems:
    """`_item_text` used to fall through to get_text(), i.e. the instance id."""

    def test_a_media_item_yields_no_text_rather_than_its_id(self, monkeypatch):
        import potato.rooms.routes as routes

        class Item:
            def get_data(self):
                return {"id": "img_01", "image_url": "media/cat.jpg"}

            def get_text(self):
                return "img_01"          # what the real Item returns

        class ISM:
            def has_item(self, _):
                return True

            def get_item(self, _):
                return Item()

        monkeypatch.setattr(routes, "get_item_state_manager", lambda: ISM())
        assert _item_text(config_with(IMAGE), "img_01") == ""

    def test_a_text_item_still_gets_its_text(self, monkeypatch):
        import potato.rooms.routes as routes

        class Item:
            def get_data(self):
                return {"id": "t1", "text": "the clinic was closed"}

            def get_text(self):
                return "the clinic was closed"

        class ISM:
            def has_item(self, _):
                return True

            def get_item(self, _):
                return Item()

        monkeypatch.setattr(routes, "get_item_state_manager", lambda: ISM())
        assert _item_text(config_with(RADIO), "t1") == "the clinic was closed"


class TestTheRoomPageRendersIt:
    """The template is the other half; assert on the shipped source."""

    def source(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        return (root / "potato" / "templates" / "room.html").read_text()

    def test_the_page_has_a_media_slot(self):
        assert 'id="item-media"' in self.source()

    def test_media_is_built_with_dom_calls_not_innerhtml(self):
        """The src comes from an item field; string-building it invites markup."""
        source = self.source()
        start = source.index("function renderItemMedia")
        body = source[start:start + 1200]
        assert "createElement" in body
        assert "innerHTML" not in body

    def test_no_text_is_only_shown_when_there_is_also_no_media(self):
        assert 'state.item_media ? "" : "(no text)"' in self.source()

"""Per-segment question forms: the server half.

`segment_schemes` was accepted by the config schema, required by the validator
for audio's questions/both modes, and passed to the browser as `segmentSchemes`
-- and nothing rendered it. audio-annotation.js drew a placeholder paragraph
where the fields belonged and video-annotation.js ignored the key entirely, so
every segment was stored with an empty `annotations` object.

The server now renders each sub-scheme once, through the same registry every
top-level scheme goes through, into a hidden `<template>` the client clones per
segment. Going through the registry is what makes every annotation type usable
inside a segment, including ones added after this file.
"""

import re

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_single_annotation_scheme,
)
from potato.server_utils.schemas.audio_annotation import (
    generate_audio_annotation_layout,
)
from potato.server_utils.schemas.segment_questions import (
    render_segment_question_template,
    segment_scheme_names,
)
from potato.server_utils.schemas.video_annotation import (
    generate_video_annotation_layout,
)


SUB_SCHEMES = [
    {"annotation_type": "radio", "name": "who_started",
     "description": "Who started?", "labels": ["Clinician", "Patient"]},
    {"annotation_type": "multiselect", "name": "cues",
     "description": "Which cues?", "labels": ["Raised voice", "Talking over"]},
    {"annotation_type": "text", "name": "note", "description": "Notes"},
]


def _template(html):
    match = re.search(
        r'<template id="segment-questions-template-[^"]+".*?</template>', html, re.S)
    return match.group(0) if match else None


class TestTemplateRendering:
    def test_one_block_per_sub_scheme(self):
        html, _ = render_segment_question_template(SUB_SCHEMES, "interruptions")

        assert re.findall(r'data-segment-scheme="([^"]+)"', html) == [
            "who_started", "cues", "note"]

    def test_the_template_is_keyed_by_the_parent_scheme(self):
        html, _ = render_segment_question_template(SUB_SCHEMES, "interruptions")

        assert 'id="segment-questions-template-interruptions"' in html

    def test_no_segment_schemes_renders_nothing(self):
        assert render_segment_question_template([], "interruptions") == ("", [])

    def test_no_keybindings_are_claimed(self):
        """A segment's fields exist only while a segment is selected."""
        _, keybindings = render_segment_question_template(SUB_SCHEMES, "x")

        assert keybindings == []

    def test_fields_come_from_the_registry(self):
        """Not hand-written inputs: every annotation type has to work here."""
        html, _ = render_segment_question_template(SUB_SCHEMES, "interruptions")

        assert 'type="radio"' in html
        assert 'type="checkbox"' in html
        assert "Clinician" in html and "Talking over" in html

    def test_a_broken_sub_scheme_does_not_take_the_widget_down(self):
        schemes = [
            {"annotation_type": "definitely_not_a_type", "name": "bad",
             "description": "d"},
            SUB_SCHEMES[0],
        ]
        html, _ = render_segment_question_template(schemes, "interruptions")

        assert "segment-question-error" in html
        # The good one still rendered.
        assert 'data-segment-scheme="who_started"' in html

    def test_a_non_mapping_entry_is_skipped(self):
        html, _ = render_segment_question_template(["not a scheme"], "x")

        assert html == ""

    def test_names_are_reported_for_the_storage_key(self):
        assert segment_scheme_names(SUB_SCHEMES) == ["who_started", "cues", "note"]


class TestBothWidgetsEmitIt:
    def test_audio(self):
        html, _ = generate_audio_annotation_layout({
            "annotation_type": "audio_annotation", "name": "interruptions",
            "description": "Mark", "source_field": "clip", "mode": "questions",
            "labels": [{"name": "speech"}], "segment_schemes": SUB_SCHEMES,
        })

        assert _template(html) is not None

    def test_video(self):
        html, _ = generate_video_annotation_layout({
            "annotation_type": "video_annotation", "name": "scenes",
            "description": "Mark", "mode": "combined",
            "labels": [{"name": "scene"}], "segment_schemes": SUB_SCHEMES,
        })

        assert _template(html) is not None

    @pytest.mark.parametrize("generator,scheme", [
        (generate_audio_annotation_layout, {
            "annotation_type": "audio_annotation", "name": "a", "description": "d",
            "source_field": "clip", "mode": "label", "labels": [{"name": "speech"}]}),
        (generate_video_annotation_layout, {
            "annotation_type": "video_annotation", "name": "v", "description": "d",
            "mode": "segment", "labels": [{"name": "scene"}]}),
    ])
    def test_no_template_without_segment_schemes(self, generator, scheme):
        html, _ = generator(scheme)

        assert _template(html) is None


class TestSubSchemeValidation:
    """Sub-schemes go through the registry, so they follow the same rules."""

    def _audio(self, segment_schemes):
        return {
            "annotation_type": "audio_annotation", "name": "interruptions",
            "description": "Mark", "source_field": "clip", "mode": "questions",
            "labels": [{"name": "speech"}], "segment_schemes": segment_schemes,
        }

    def test_a_valid_set_passes(self):
        validate_single_annotation_scheme(
            self._audio(SUB_SCHEMES), "annotation_schemes[0]")

    def test_a_missing_annotation_type_is_caught_at_validate_time(self):
        with pytest.raises(ConfigValidationError, match="missing 'annotation_type'"):
            validate_single_annotation_scheme(
                self._audio([{"name": "q", "description": "d"}]),
                "annotation_schemes[0]")

    def test_a_boolean_label_inside_a_sub_scheme_is_caught(self):
        # The YAML trap reaches one level down too.
        with pytest.raises(ConfigValidationError, match="boolean"):
            validate_single_annotation_scheme(
                self._audio([{"annotation_type": "radio", "name": "q",
                              "description": "d", "labels": [True, False]}]),
                "annotation_schemes[0]")

    def test_the_error_names_the_sub_scheme_position(self):
        with pytest.raises(ConfigValidationError,
                           match=r"segment_schemes\[1\]"):
            validate_single_annotation_scheme(
                self._audio([SUB_SCHEMES[0], {"name": "q", "description": "d"}]),
                "annotation_schemes[0]")

    @pytest.mark.parametrize("media_type", [
        "audio_annotation", "video_annotation", "tiered_annotation"])
    def test_a_segment_cannot_contain_a_timeline(self, media_type):
        with pytest.raises(ConfigValidationError, match="cannot itself own a timeline"):
            validate_single_annotation_scheme(
                self._audio([{"annotation_type": media_type, "name": "nested",
                              "description": "d"}]),
                "annotation_schemes[0]")

    def test_a_non_mapping_sub_scheme_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="must be a mapping"):
            validate_single_annotation_scheme(
                self._audio(["not a scheme"]), "annotation_schemes[0]")

    def test_video_sub_schemes_are_validated_too(self):
        with pytest.raises(ConfigValidationError, match="missing 'annotation_type'"):
            validate_single_annotation_scheme({
                "annotation_type": "video_annotation", "name": "scenes",
                "description": "Mark", "mode": "combined",
                "labels": [{"name": "scene"}],
                "segment_schemes": [{"name": "q", "description": "d"}],
            }, "annotation_schemes[0]")


class TestClientContract:
    """The two halves agree on which attributes make a field a proxy widget."""

    def test_the_client_strips_what_this_module_documents(self):
        from pathlib import Path
        import potato
        from potato.server_utils.schemas.segment_questions import (
            PROXY_STRIPPED_ATTRIBUTES, PROXY_STRIPPED_CLASS)

        client = (Path(potato.__file__).parent / "static"
                  / "segment-questions.js").read_text()

        for attribute in PROXY_STRIPPED_ATTRIBUTES:
            assert f"'{attribute}'" in client, (
                f"segment-questions.js no longer strips '{attribute}'. A cloned "
                "field carrying it is visible to syncAnnotationsFromDOM, which "
                "reads a segment's answer as a top-level one."
            )
        assert PROXY_STRIPPED_CLASS in client

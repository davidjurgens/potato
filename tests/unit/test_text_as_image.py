"""Tests for ``text_as_image``: the item text rendered to a PNG.

The feature exists to stop an annotator from pasting an item into a chatbot.
That only holds if the words are absent from the whole page, not merely hidden,
so the leak tests below check the rendered HTML rather than the visible box.
"""

from pathlib import Path

import pytest

from potato.server_utils import text_to_image

REPO_ROOT = Path(__file__).resolve().parents[2]
FLASK_SERVER = REPO_ROOT / "potato" / "flask_server.py"

#: Nonsense tokens on purpose. Ordinary words such as "the" occur in the
#: template's own comments, so only a distinctive string proves a leak.
SECRET = "Zorbaxil qynthorp veldrammic Wuxlotte 88271."
SECRET_TOKENS = ["Zorbaxil", "qynthorp", "veldrammic", "Wuxlotte", "88271"]


def _render(app, **overrides):
    """Render the annotation template with the context the server supplies."""
    context = dict(
        username="user",
        annotation_task_name="Task",
        annotation_status="unlabeled",
        finished=0,
        total_count=1,
        instance_index=0,
        instance="",
        instance_plain_text="",
        instance_id="i1",
        instance_record={},
        is_annotation_page=True,
        can_go_back=True,
        frontend_assets={},
        annotation_schemes=[],
        ui_config={},
    )
    context.update(overrides)
    with app.test_request_context("/"):
        return app.jinja_env.get_template("base_template_v2.html").render(**context)


class TestSettings:
    def test_the_feature_is_off_unless_asked_for(self):
        assert text_to_image.settings({}) is None
        assert text_to_image.settings({"text_as_image": False}) is None
        assert text_to_image.settings({"text_as_image": {"enabled": False}}) is None

    def test_true_and_the_mapping_both_work(self):
        assert text_to_image.settings({"text_as_image": True}) == text_to_image.DEFAULTS
        assert text_to_image.settings(
            {"text_as_image": {"enabled": True, "font_size": 24, "max_width": 700}}
        ) == {"font_size": 24, "max_width": 700}

    @pytest.mark.parametrize("bad", [0, -5, "20", True, 2.5])
    def test_a_bad_size_falls_back_to_the_default(self, bad):
        resolved = text_to_image.settings({"text_as_image": {"font_size": bad}})
        assert resolved["font_size"] == text_to_image.DEFAULTS["font_size"]


class TestApplicability:
    def test_a_plain_text_project_gets_the_picture(self):
        assert text_to_image.applies(
            {"text_as_image": True}, [{"annotation_type": "radio"}]
        ) == text_to_image.DEFAULTS

    @pytest.mark.parametrize("scheme", [
        {"annotation_type": "video_annotation"},
        {"annotation_type": "audio_annotation"},
        {"annotation_type": "image_annotation"},
        {"annotation_type": "tiered_annotation", "media_type": "video"},
    ])
    def test_a_media_project_is_left_alone(self, scheme):
        """These displays own the page. The text box is a hidden fallback."""
        assert text_to_image.applies({"text_as_image": True}, [scheme]) is None

    def test_an_instance_display_project_is_left_alone(self):
        assert text_to_image.applies(
            {"text_as_image": True, "instance_display": {}},
            [{"annotation_type": "radio"}],
        ) is None

    def test_span_schemes_are_reported_so_the_validator_can_warn(self):
        assert text_to_image.span_schemes([
            {"annotation_type": "span"},
            {"annotation_type": "radio"},
            {"annotation_type": "extractive_qa"},
        ]) == ["extractive_qa", "span"]


class TestRendering:
    def test_the_markup_carries_a_png_and_none_of_the_words(self):
        markup = text_to_image.image_html(SECRET, text_to_image.DEFAULTS)
        assert markup.startswith('<img src="data:image/png;base64,')
        for token in SECRET_TOKENS:
            assert token not in markup

    @pytest.mark.parametrize("blank", ["", "   ", "<p></p>"])
    def test_empty_text_produces_no_image(self, blank):
        assert text_to_image.image_html(blank, text_to_image.DEFAULTS) == ""

    def test_paragraph_breaks_survive_but_html_does_not(self):
        plain = text_to_image.to_plain("<p>One &amp; two.</p><p>Three.</p>")
        assert plain == "One & two.\nThree."

    def test_a_word_wider_than_the_image_is_broken_not_clipped(self):
        from PIL import ImageFont

        font = ImageFont.load_default(size=36)
        width = 800
        lines = text_to_image._wrap("z" * 400, font, width)
        assert len(lines) > 1
        assert all(font.getlength(line) <= width for line in lines)
        assert "".join(lines) == "z" * 400

    def test_the_item_record_loses_every_field_that_holds_the_text(self):
        record = {"id": "7", "text": SECRET, "displayed_text": SECRET, "topic": "fauna"}
        assert text_to_image.without_text(record, "text") == {"id": "7", "topic": "fauna"}


class TestThePageCarriesNoText:
    def test_the_rendered_page_holds_the_image_and_not_the_words(self):
        """The server sets `instance_image` and blanks `instance` and
        `instance_plain_text` together. Rendered that way, no branch of the
        template can put the words back."""
        from potato.flask_server import create_app

        rendered = _render(
            create_app(),
            instance_image=text_to_image.image_html(SECRET, text_to_image.DEFAULTS),
        )
        assert 'src="data:image/png;base64,' in rendered
        for token in SECRET_TOKENS:
            assert token not in rendered

    def test_the_template_branch_is_inert_when_the_feature_is_off(self):
        from potato.flask_server import create_app

        rendered = _render(create_app(), instance=SECRET, instance_plain_text=SECRET)
        assert "data:image/png" not in rendered
        assert SECRET in rendered


class TestBothRenderPathsApplyIt:
    """Two functions put real item text into the annotation template.

    A change applied to one of them is a silent no-op on the other, so this
    holds both in place. See tests/unit/test_annotation_sidebar_gating.py for
    the same guard on the sidebar flags.
    """

    @pytest.mark.parametrize("function_name", [
        "render_page_with_annotations",
        "_training_page_context",
    ])
    def test_the_path_asks_text_to_image_whether_it_applies(self, function_name):
        source = FLASK_SERVER.read_text(encoding="utf-8")
        start = source.index("def " + function_name + "(")
        end = source.index("\ndef ", start + 1)
        body = source[start:end]
        assert "text_to_image.applies(" in body, (
            function_name + " renders real item text but never consults "
            "text_to_image.applies(), so text_as_image does nothing there"
        )
        assert "text_to_image.image_html(" in body


class TestValidation:
    @pytest.mark.parametrize("value", ["yes", 3, [1, 2]])
    def test_a_wrong_shape_is_rejected(self, value):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_text_as_image_config)

        with pytest.raises(ConfigValidationError):
            validate_text_as_image_config({"text_as_image": value})

    @pytest.mark.parametrize("block", [
        {"font_size": 0},
        {"max_width": -1},
        {"font_size": "big"},
        {"enabled": "true"},
    ])
    def test_a_wrong_option_is_rejected(self, block):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_text_as_image_config)

        with pytest.raises(ConfigValidationError):
            validate_text_as_image_config({"text_as_image": block})

    def test_a_good_config_passes(self):
        from potato.server_utils.config_module import validate_text_as_image_config

        validate_text_as_image_config({})
        validate_text_as_image_config({"text_as_image": False})
        validate_text_as_image_config({
            "text_as_image": {"enabled": True, "font_size": 20, "max_width": 800},
            "annotation_schemes": [{"annotation_type": "radio"}],
        })

class TestSpanSchemesAreRefused:
    """A span scheme plus text_as_image must not start.

    The failure is silent otherwise: the annotator sees a picture, selects
    nothing, and the study collects empty spans. It looks like it worked. The
    same reasoning is written out in validate_live_ingestion_assignment_compat.
    """

    @pytest.mark.parametrize("scheme_type", sorted(text_to_image.SPAN_SCHEME_TYPES))
    def test_every_span_scheme_is_refused(self, scheme_type):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_text_as_image_config)

        with pytest.raises(ConfigValidationError) as caught:
            validate_text_as_image_config({
                "text_as_image": True,
                "annotation_schemes": [{"annotation_type": scheme_type}],
            })
        assert scheme_type in str(caught.value)
        assert "text_as_image" in str(caught.value)

    def test_a_span_scheme_beside_a_safe_one_is_still_refused(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_text_as_image_config)

        with pytest.raises(ConfigValidationError):
            validate_text_as_image_config({
                "text_as_image": True,
                "annotation_schemes": [
                    {"annotation_type": "radio"},
                    {"annotation_type": "span"},
                ],
            })

    def test_a_span_scheme_is_fine_while_the_feature_is_off(self):
        from potato.server_utils.config_module import validate_text_as_image_config

        validate_text_as_image_config({
            "annotation_schemes": [{"annotation_type": "span"}],
        })
        validate_text_as_image_config({
            "text_as_image": False,
            "annotation_schemes": [{"annotation_type": "span"}],
        })
        validate_text_as_image_config({
            "text_as_image": {"enabled": False},
            "annotation_schemes": [{"annotation_type": "span"}],
        })

    def test_the_refusal_runs_from_the_top_level_validator(self):
        """The check must be wired into validate_yaml_structure, not only
        callable on its own."""
        from potato.server_utils import config_module

        source = Path(config_module.__file__).read_text(encoding="utf-8")
        start = source.index("def validate_yaml_structure(")
        end = source.index("\ndef ", start + 1)
        assert "validate_text_as_image_config(config_data)" in source[start:end]


class TestSchemesReadingTheRemovedFieldAreRefused:
    """A scheme that reads the blanked data field must not start either.

    text_edit, card_sort, conjoint, pairwise and others name the field they
    read with an attribute of their own. When that field is the item text, the
    feature removes it and the scheme renders empty.
    """

    def test_the_check_reads_values_not_attribute_names(self):
        """Roughly thirty attribute names point at a data field across the
        registry. The check looks at values so a new schema needs no edit."""
        hits = text_to_image.schemes_reading_removed_fields([
            {"annotation_type": "text_edit", "name": "post_edit", "source_field": "text"},
            {"annotation_type": "card_sort", "name": "sort", "items_field": "body"},
            {"annotation_type": "pairwise", "name": "pref", "items_key": "text"},
        ], "body")
        assert hits == [
            "post_edit (source_field: text)",
            "pref (items_key: text)",
            "sort (items_field: body)",
        ]

    def test_a_scheme_pointing_elsewhere_is_fine(self):
        assert text_to_image.schemes_reading_removed_fields([
            {"annotation_type": "text_edit", "name": "e", "source_field": "mt_output"},
            {"annotation_type": "radio", "name": "r", "labels": ["a", "b"]},
        ], "text") == []

    def test_the_conflict_is_refused(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_text_as_image_config)

        with pytest.raises(ConfigValidationError) as caught:
            validate_text_as_image_config({
                "text_as_image": True,
                "item_properties": {"text_key": "text"},
                "annotation_schemes": [
                    {"annotation_type": "text_edit", "name": "e", "source_field": "text"},
                ],
            })
        assert "source_field: text" in str(caught.value)

    def test_a_media_project_is_not_refused_for_its_own_source_field(self):
        """Regression: an image project sets text_key to image_url and its
        scheme reads source_field: image_url. That is not a conflict, because
        the feature never runs on a media project. Checking the conflict before
        checking applicability rejected every image example."""
        from potato.server_utils.config_module import validate_text_as_image_config

        validate_text_as_image_config({
            "text_as_image": True,
            "item_properties": {"text_key": "image_url"},
            "annotation_schemes": [{
                "annotation_type": "image_annotation",
                "name": "objects",
                "source_field": "image_url",
                "labels": [{"name": "car"}],
            }],
        })

    def test_a_media_project_is_not_refused_for_a_span_scheme_either(self):
        from potato.server_utils.config_module import validate_text_as_image_config

        validate_text_as_image_config({
            "text_as_image": True,
            "annotation_schemes": [
                {"annotation_type": "image_annotation", "name": "o"},
                {"annotation_type": "span", "name": "s"},
            ],
        })

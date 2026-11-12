"""
Audit 6: the server-side half of eight defects, pinned.

Each test below names the thing an annotator did and the thing the study then
recorded, because the generated HTML is only interesting for what it makes the
shared save/validate pipeline do with it.
"""

import json
import re

import pytest

from potato.server_utils.config_module import ConfigValidationError
from potato.server_utils.schemas.registry import schema_registry


def gen(**scheme):
    scheme.setdefault("description", "d")
    html, _ = schema_registry.generate(scheme)
    return html


def strip_comments(js):
    """JS with its comments removed, so a check cannot match an explanation."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"^\s*//.*$", "", js, flags=re.M)


class TestMultiDocumentEventIsCollected:
    """
    The widget wrote the document's event memberships into a hidden input that
    carried no `annotation-input` class, so `syncAnnotationsFromDOM` -- which
    collects exactly `.annotation-input` -- never saw it, and after grouping
    two documents, naming an event, filling two slots and pressing Next,
    `instance_id_to_label_to_value` was `{}`.
    """

    def test_the_mirror_is_an_annotation_input(self):
        html = gen(annotation_type="multi_document_event", name="incidents",
                   slots=[{"name": "where"}])
        assert 'class="annotation-input mde-data-input"' in html

    def test_it_carries_the_schema_and_label_the_collector_reads(self):
        html = gen(annotation_type="multi_document_event", name="incidents")
        assert 'schema="incidents"' in html
        assert 'label_name="incidents"' in html

    def test_required_reaches_the_input(self):
        html = gen(annotation_type="multi_document_event", name="incidents",
                   label_requirement={"required": True})
        assert 'validation="required"' in html

    def test_the_container_names_its_schema_for_the_validator(self):
        # validateRequiredFields groups by the form's data-schema-name; without
        # it the input is collected but cannot be attributed.
        html = gen(annotation_type="multi_document_event", name="incidents")
        assert 'data-schema-name="incidents"' in html


class TestTrajectoryEvalScoresHonestly:
    """
    `show_score: true`, five steps all marked `incorrect` with an error type and
    no severity, published "Score: 100 / 100" and stored score: 100 -- because
    the number is computed from severities alone. The mirror image was as bad: a
    step marked `correct` kept a severity chosen while it was wrong, and 5 was
    deducted for it.
    """

    def js(self):
        return strip_comments(gen(annotation_type="trajectory_eval", name="te"))

    def test_a_severity_only_counts_against_a_step_called_wrong(self):
        assert "function stepPenalty(s)" in self.js()
        assert "s.correctness === 'correct'" in self.js()

    def test_marking_a_step_correct_clears_its_error_taxonomy(self):
        js = self.js()
        assert "function clearErrorFields(card, idx)" in js
        assert "if (hideErrors) clearErrorFields(card, idx);" in js

    def test_an_unjudged_or_unscored_step_blocks_next(self):
        js = self.js()
        assert "function declareCompleteness()" in js
        assert "data-incomplete-reason" in js
        assert "steps judged" in js
        assert "no severity chosen on step" in js

    def test_no_score_is_published_while_the_answer_is_incomplete(self):
        js = self.js()
        assert "score: incomplete ? null : score" in js
        assert "score_complete: !incomplete" in js


class TestTemporalGroundingCompleteness:
    """
    `required: true` on an item declaring two events was satisfied by typing a
    start into the first one: Next advanced with {"events":{"0":{"start":1.5}}}
    stored -- an interval with no end, one of two events answered.
    """

    def js(self):
        return strip_comments(gen(annotation_type="temporal_grounding", name="tg"))

    def test_it_declares_how_many_intervals_are_marked(self):
        assert "intervals marked" in self.js()

    def test_a_half_marked_interval_is_named(self):
        assert "missing a start or an end" in self.js()

    def test_an_inverted_interval_is_named(self):
        assert "before it starts" in self.js()

    def test_the_declaration_runs_on_arrival_not_only_on_edit(self):
        js = self.js()
        # Once inside build(), once inside save().
        assert js.count("declareCompleteness();") >= 3


class TestTrajectoryEditRequiresTheReasonItAsksFor:
    """
    `require_reason_on_edit` only decided whether the "Reason for edit" input
    was rendered. Editing a step and leaving it blank stored reason: "" and Next
    advanced with no warning.
    """

    def test_a_blank_reason_on_an_edited_step_blocks_next(self):
        js = strip_comments(gen(annotation_type="trajectory_edit", name="tx",
                                require_reason_on_edit=True))
        assert "no reason given for the edit on step" in js
        assert "data-incomplete-reason" in js

    def test_the_label_says_it_is_required(self):
        html = gen(annotation_type="trajectory_edit", name="tx",
                   require_reason_on_edit=True)
        assert "trajedit-reason-req" in html

    def test_without_the_key_nothing_is_required(self):
        js = strip_comments(gen(annotation_type="trajectory_edit", name="tx"))
        assert "if (!CONFIG.require_reason_on_edit)" in js


class TestCodeReviewDropsEmptyComments:
    """
    "+ Add Comment" appends a row immediately and the row was stored whether or
    not anything was typed into it, so an export reading `comments` counted two
    review comments on a file nobody commented on.
    """

    def test_only_comments_with_text_are_serialized(self):
        js = strip_comments(gen(annotation_type="code_review", name="cr"))
        assert "String(c.text || '').trim() !== ''" in js
        assert "comments: written" in js


class TestMultimodalReasoningReadsContent:
    """
    A trace keyed uniformly on `content` rendered its prose and then showed
    "Step 2 IMAGE missing image" and "Step 4 TOOL tool {}", because only the
    text branch fell back through `content`.
    """

    def js(self):
        return gen(annotation_type="multimodal_reasoning", name="mmr")

    def test_the_image_branch_accepts_content_url_and_src(self):
        assert "s.image || s.image_url || s.url || s.src || s.content" in self.js()

    def test_the_tool_branch_accepts_content(self):
        assert "s.input || s.content" in self.js()

    def test_a_genuinely_missing_value_says_which_key_was_expected(self):
        js = self.js()
        assert "expected one of " in js
        assert "image, image_url, url, src or content" in js
        assert "args, arguments, input or content" in js


class TestSegmentSchemesTakePartInValidation:
    """
    `label_requirement.required: true` never reached the browser on either of
    the segment widgets -- they emit no `validation` attribute at all -- so
    `min_segments` had nothing to report a shortfall to.
    """

    @pytest.mark.parametrize("kind", ["audio_annotation", "video_annotation"])
    def test_required_reaches_the_hidden_input(self, kind):
        html = gen(annotation_type=kind, name="seg", labels=["a", "b"],
                   label_requirement={"required": True})
        assert 'validation="required"' in html

    @pytest.mark.parametrize("kind", ["audio_annotation", "video_annotation"])
    def test_the_form_names_its_schema(self, kind):
        html = gen(annotation_type=kind, name="seg", labels=["a", "b"])
        assert 'data-schema-name="seg"' in html

    @pytest.mark.parametrize("kind", ["audio_annotation", "video_annotation"])
    def test_min_segments_still_reaches_the_client(self, kind):
        html = gen(annotation_type=kind, name="seg", labels=["a"], min_segments=2)
        assert '"minSegments": 2' in html


class TestConfigsThatCannotWorkAreRefused:
    """
    Three configurations validated clean, booted without a warning, rendered a
    full widget and could never collect anything.
    """

    def _validate(self, config):
        # The two rules directly, the way the ibws rules are tested: the full
        # validate_yaml_structure also demands task_dir and friends, which say
        # nothing about the defect under test. Both are wired into
        # validate_yaml_structure -- pinned separately below.
        from potato.server_utils.config_module import (
            _validate_multi_document_event_has_template,
            _validate_canvas_companion_schemes,
        )
        _validate_multi_document_event_has_template(config)
        _validate_canvas_companion_schemes(config)

    def base(self, schemes):
        return {
            "annotation_task_name": "t",
            "data_files": ["data.json"],
            "annotation_schemes": schemes,
        }

    def test_both_rules_run_inside_validate_yaml_structure(self):
        # A rule nothing calls is a rule that does not exist; `validate
        # --strict` is where an author meets it.
        import inspect
        from potato.server_utils import config_module

        src = inspect.getsource(config_module.validate_yaml_structure)
        assert "_validate_multi_document_event_has_template(config_data)" in src
        assert "_validate_canvas_companion_schemes(config_data)" in src

    def test_multi_document_event_without_event_template_is_refused(self):
        # The registry blueprint is only registered when the block is enabled,
        # so every /corpus/api/* call 404s and "+ New event" does nothing
        # forever, with nothing said to the annotator.
        cfg = self.base([{"annotation_type": "multi_document_event",
                          "name": "incidents", "description": "d",
                          "slots": [{"name": "where"}]}])
        with pytest.raises(ConfigValidationError, match="event_template"):
            self._validate(cfg)

    def test_the_scheme_is_accepted_once_the_block_is_enabled(self):
        cfg = self.base([{"annotation_type": "multi_document_event",
                          "name": "incidents", "description": "d"}])
        cfg["event_template"] = {"enabled": True, "name": "outage",
                                 "slots": [{"name": "where"}]}
        self._validate(cfg)

    def test_corpus_map_also_satisfies_it(self):
        cfg = self.base([{"annotation_type": "multi_document_event",
                          "name": "incidents", "description": "d"}])
        cfg["corpus_map"] = {"enabled": True}
        self._validate(cfg)

    @pytest.mark.parametrize("kind", ["region_caption", "grounding_eval"])
    def test_a_canvas_companion_alone_is_refused(self, kind):
        # Alone, region_caption's list can never fill and grounding_eval can
        # only ever answer "not present in the image".
        cfg = self.base([{"annotation_type": kind, "name": "x",
                          "description": "d"}])
        with pytest.raises(ConfigValidationError, match="image_annotation"):
            self._validate(cfg)

    @pytest.mark.parametrize("kind", ["region_caption", "grounding_eval"])
    def test_it_is_accepted_beside_an_image_annotation_scheme(self, kind):
        cfg = self.base([
            {"annotation_type": "image_annotation", "name": "regions",
             "description": "d", "tools": ["bbox"], "labels": ["referent"]},
            {"annotation_type": kind, "name": "x", "description": "d"},
        ])
        self._validate(cfg)

    def test_the_message_names_the_block_to_add(self):
        cfg = self.base([{"annotation_type": "multi_document_event",
                          "name": "incidents", "description": "d"}])
        with pytest.raises(ConfigValidationError) as exc:
            self._validate(cfg)
        assert "enabled: true" in str(exc.value)
        assert "slots:" in str(exc.value)


class TestBundledExamplesStillValidate:
    """The new refusals must not reject Potato's own examples."""

    @pytest.mark.parametrize("path", [
        "examples/advanced/multi-document-events/config.yaml",
        "examples/ai-assisted/grounding-eval/config.yaml",
        "examples/image/region-captioning/config.yaml",
    ])
    def test_example_config_passes(self, path):
        import yaml
        from pathlib import Path
        from potato.server_utils import config_module

        root = Path(__file__).resolve().parents[2]
        cfg = yaml.safe_load((root / path).read_text())
        config_module._validate_multi_document_event_has_template(cfg)
        config_module._validate_canvas_companion_schemes(cfg)

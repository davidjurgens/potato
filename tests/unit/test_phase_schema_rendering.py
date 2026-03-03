"""
Phase Schema Rendering Tests

Tests that schema generators work correctly when called from phase contexts
(consent, prestudy, poststudy) where annotation_id is not pre-assigned.

This is a regression test for the bug where generate_html_from_schematic
(used for phase pages) did not assign annotation_id to schema dicts,
causing KeyError crashes in schema generators.
"""

import pytest
from potato.server_utils.front_end import generate_schematic


class TestGenerateSchematicWithoutAnnotationId:
    """Test that generate_schematic works when annotation_id is missing."""

    def test_radio_without_annotation_id(self):
        """Radio schema should work without annotation_id pre-set."""
        scheme = {
            "annotation_type": "radio",
            "name": "age_consent",
            "description": "I certify that I am at least 18 years of age.",
            "labels": ["I agree", "I disagree"],
        }
        html, keybindings = generate_schematic(scheme)
        assert "age_consent" in html
        assert "Error Generating Annotation Form" not in html

    def test_likert_without_annotation_id(self):
        """Likert schema should work without annotation_id pre-set."""
        scheme = {
            "annotation_type": "likert",
            "name": "nlp_familiarity",
            "description": "How familiar are you with NLP?",
            "min_label": "Not at all",
            "max_label": "Expert",
            "size": 5,
        }
        html, keybindings = generate_schematic(scheme)
        assert "nlp_familiarity" in html
        assert "Error Generating Annotation Form" not in html

    def test_multiselect_without_annotation_id(self):
        """Multiselect schema should work without annotation_id pre-set."""
        scheme = {
            "annotation_type": "multiselect",
            "name": "topics",
            "description": "Select all that apply",
            "labels": ["NLP", "CV", "RL"],
        }
        html, keybindings = generate_schematic(scheme)
        assert "topics" in html
        assert "Error Generating Annotation Form" not in html

    def test_textbox_without_annotation_id(self):
        """Textbox schema should work without annotation_id pre-set."""
        scheme = {
            "annotation_type": "text",
            "name": "comments",
            "description": "Enter any comments",
        }
        html, keybindings = generate_schematic(scheme)
        assert "comments" in html
        assert "Error Generating Annotation Form" not in html

    def test_slider_without_annotation_id(self):
        """Slider schema should work without annotation_id pre-set."""
        scheme = {
            "annotation_type": "slider",
            "name": "confidence",
            "description": "Rate your confidence",
            "min_value": 1,
            "max_value": 10,
            "starting_value": 5,
        }
        html, keybindings = generate_schematic(scheme)
        assert "confidence" in html
        assert "Error Generating Annotation Form" not in html

    def test_number_without_annotation_id(self):
        """Number schema should work without annotation_id pre-set."""
        scheme = {
            "annotation_type": "number",
            "name": "age",
            "description": "Enter your age",
        }
        html, keybindings = generate_schematic(scheme)
        assert "age" in html
        assert "Error Generating Annotation Form" not in html

    def test_select_without_annotation_id(self):
        """Select schema should work without annotation_id pre-set."""
        scheme = {
            "annotation_type": "select",
            "name": "country",
            "description": "Select your country",
            "labels": ["USA", "UK", "Canada"],
        }
        html, keybindings = generate_schematic(scheme)
        assert "country" in html
        assert "Error Generating Annotation Form" not in html

    def test_annotation_id_gets_default_value(self):
        """generate_schematic should assign annotation_id=0 as default."""
        scheme = {
            "annotation_type": "radio",
            "name": "test",
            "description": "Test",
            "labels": ["A", "B"],
        }
        assert "annotation_id" not in scheme
        generate_schematic(scheme)
        assert scheme["annotation_id"] == 0

    def test_existing_annotation_id_preserved(self):
        """generate_schematic should not overwrite an existing annotation_id."""
        scheme = {
            "annotation_type": "radio",
            "name": "test",
            "description": "Test",
            "labels": ["A", "B"],
            "annotation_id": 5,
        }
        generate_schematic(scheme)
        assert scheme["annotation_id"] == 5


class TestConsentSchemaPattern:
    """Test typical consent page schema patterns (radio with required labels)."""

    def test_consent_radio_with_required_label(self):
        """Consent-style radio with required_label should render correctly."""
        scheme = {
            "annotation_type": "radio",
            "name": "data_consent",
            "description": "I consent to having my annotations used for research.",
            "labels": ["I consent", "I do not consent"],
            "label_requirement": {"required_label": ["I consent"]},
        }
        html, keybindings = generate_schematic(scheme)
        assert "data_consent" in html
        assert "I consent" in html
        assert "Error Generating Annotation Form" not in html

    def test_multiple_consent_schemas(self):
        """Multiple consent schemas should each get generated correctly."""
        schemas = [
            {
                "annotation_type": "radio",
                "name": "age_consent",
                "description": "I certify I am at least 18.",
                "labels": ["I agree", "I disagree"],
            },
            {
                "annotation_type": "radio",
                "name": "data_consent",
                "description": "I consent to data use.",
                "labels": ["I consent", "I do not consent"],
            },
        ]
        for i, scheme in enumerate(schemas):
            html, _ = generate_schematic(scheme)
            assert scheme["name"] in html
            assert "Error Generating Annotation Form" not in html


class TestPreStudySurveyPattern:
    """Test typical pre-study survey patterns (mixed schema types)."""

    def test_prestudy_mixed_schemas(self):
        """Pre-study survey with likert + radio should render correctly."""
        schemas = [
            {
                "annotation_type": "likert",
                "name": "familiarity",
                "description": "How familiar are you with this topic?",
                "min_label": "Not familiar",
                "max_label": "Very familiar",
                "size": 5,
            },
            {
                "annotation_type": "radio",
                "name": "native_language",
                "description": "Is English your native language?",
                "labels": ["Yes", "No"],
            },
        ]
        for scheme in schemas:
            html, _ = generate_schematic(scheme)
            assert scheme["name"] in html
            assert "Error Generating Annotation Form" not in html

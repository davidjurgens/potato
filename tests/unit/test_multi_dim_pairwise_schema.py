"""Unit tests for multi-dimensional pairwise and justified pairwise."""

import pytest
from potato.server_utils.schemas.pairwise import generate_pairwise_layout
from potato.server_utils.schemas.registry import schema_registry


class TestMultiDimensionPairwise:
    """Test multi_dimension mode HTML generation."""

    def _make_scheme(self, **overrides):
        base = {
            "annotation_type": "pairwise",
            "name": "comparison",
            "description": "Compare responses",
            "mode": "multi_dimension",
            "dimensions": [
                {"name": "helpfulness", "description": "Which is more helpful?", "allow_tie": True},
                {"name": "accuracy", "description": "Which is more accurate?"},
            ],
        }
        base.update(overrides)
        return base

    def test_generates_html_and_keybindings(self):
        html, keybindings = generate_pairwise_layout(self._make_scheme())
        assert isinstance(html, str)
        assert isinstance(keybindings, list)

    def test_html_has_multi_dimension_class(self):
        html, _ = generate_pairwise_layout(self._make_scheme())
        assert "pairwise-multi-dimension" in html

    def test_html_contains_dimension_rows(self):
        html, _ = generate_pairwise_layout(self._make_scheme())
        assert 'data-dimension="helpfulness"' in html
        assert 'data-dimension="accuracy"' in html

    def test_html_contains_dimension_labels(self):
        html, _ = generate_pairwise_layout(self._make_scheme())
        assert "Helpfulness" in html
        assert "Accuracy" in html

    def test_html_contains_dimension_descriptions(self):
        html, _ = generate_pairwise_layout(self._make_scheme())
        assert "Which is more helpful?" in html
        assert "Which is more accurate?" in html

    def test_tie_button_shown_per_dimension(self):
        html, _ = generate_pairwise_layout(self._make_scheme())
        # helpfulness has allow_tie=True
        assert html.count('data-dimension="helpfulness"') >= 3  # A tile, B tile, tie btn
        # accuracy has no tie button (allow_tie defaults to False)

    def test_hidden_inputs_per_dimension(self):
        html, _ = generate_pairwise_layout(self._make_scheme())
        assert 'label_name="helpfulness"' in html
        assert 'label_name="accuracy"' in html

    def test_custom_labels(self):
        html, _ = generate_pairwise_layout(self._make_scheme(labels=["Left", "Right"]))
        assert "Left" in html
        assert "Right" in html

    def test_requires_dimensions_list(self):
        # safe_generate_layout catches ValueError and returns empty HTML
        html, _ = generate_pairwise_layout(self._make_scheme(dimensions=[]))
        assert html.strip() == "" or "pairwise-dimension-row" not in html

    def test_via_registry(self):
        scheme = self._make_scheme()
        html, _ = schema_registry.generate(scheme)
        assert "pairwise-multi-dimension" in html


class TestPairwiseJustification:
    """Test justification section in pairwise modes."""

    def _make_binary_with_justification(self, **j_overrides):
        justification = {
            "required": True,
            "reason_categories": ["More accurate", "More helpful", "Safer"],
            "min_rationale_chars": 20,
            "rationale_placeholder": "Explain...",
        }
        justification.update(j_overrides)
        return {
            "annotation_type": "pairwise",
            "name": "test_pair",
            "description": "Compare",
            "mode": "binary",
            "justification": justification,
        }

    def test_justification_section_present(self):
        html, _ = generate_pairwise_layout(self._make_binary_with_justification())
        assert "pairwise-justification" in html

    def test_reason_categories_rendered(self):
        html, _ = generate_pairwise_layout(self._make_binary_with_justification())
        assert "More accurate" in html
        assert "More helpful" in html
        assert "Safer" in html

    def test_rationale_textarea_present(self):
        html, _ = generate_pairwise_layout(self._make_binary_with_justification())
        assert "pairwise-rationale-textarea" in html
        assert "Explain..." in html

    def test_hidden_justification_input(self):
        html, _ = generate_pairwise_layout(self._make_binary_with_justification())
        assert 'label_name="justification"' in html

    def test_no_justification_when_not_configured(self):
        scheme = {
            "annotation_type": "pairwise",
            "name": "no_just",
            "description": "Compare",
            "mode": "binary",
        }
        html, _ = generate_pairwise_layout(scheme)
        assert "pairwise-justification" not in html

    def test_justification_in_multi_dimension(self):
        scheme = {
            "annotation_type": "pairwise",
            "name": "md_just",
            "description": "Compare",
            "mode": "multi_dimension",
            "dimensions": [
                {"name": "quality", "description": "Overall quality"},
            ],
            "justification": {
                "reason_categories": ["Better quality"],
                "min_rationale_chars": 10,
            },
        }
        html, _ = generate_pairwise_layout(scheme)
        assert "pairwise-justification" in html
        assert "Better quality" in html

    def test_min_chars_in_counter(self):
        html, _ = generate_pairwise_layout(
            self._make_binary_with_justification(min_rationale_chars=50)
        )
        assert "50" in html

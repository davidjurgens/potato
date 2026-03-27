"""Unit tests for the code_review annotation schema."""

import pytest
from potato.server_utils.schemas.code_review import generate_code_review_layout


class TestCodeReviewSchema:
    """Tests for generate_code_review_layout()."""

    def _make_scheme(self, **kwargs):
        base = {
            "name": "test_review",
            "description": "Test code review",
            "annotation_type": "code_review",
            "comment_categories": ["bug", "style", "suggestion"],
            "verdict_options": ["approve", "request_changes"],
            "file_rating_dimensions": ["correctness", "quality"],
        }
        base.update(kwargs)
        return base

    def test_generates_html(self):
        html, kb = generate_code_review_layout(self._make_scheme())
        assert isinstance(html, str)
        assert len(html) > 0

    def test_contains_container(self):
        html, _ = generate_code_review_layout(self._make_scheme())
        assert "code-review-container" in html
        assert "test_review" in html

    def test_contains_hidden_input(self):
        html, _ = generate_code_review_layout(self._make_scheme())
        assert "code-review-data-input" in html
        assert 'type="hidden"' in html

    def test_verdict_options(self):
        html, _ = generate_code_review_layout(self._make_scheme())
        assert "Approve" in html
        assert "Request Changes" in html
        assert "cr-verdict-group" in html

    def test_custom_verdicts(self):
        html, _ = generate_code_review_layout(self._make_scheme(
            verdict_options=["lgtm", "needs_work", "blocked"]
        ))
        assert "Lgtm" in html
        assert "Needs Work" in html
        assert "Blocked" in html

    def test_comment_categories(self):
        html, _ = generate_code_review_layout(self._make_scheme())
        assert "Bug" in html
        assert "Style" in html
        assert "Suggestion" in html

    def test_add_comment_button(self):
        html, _ = generate_code_review_layout(self._make_scheme())
        assert "Add Comment" in html
        assert "cr-add-comment-btn" in html

    def test_comment_template(self):
        html, _ = generate_code_review_layout(self._make_scheme())
        assert "<template" in html
        assert "cr-comment-card" in html
        assert "cr-comment-category" in html
        assert "cr-comment-text" in html

    def test_file_ratings_section(self):
        html, _ = generate_code_review_layout(self._make_scheme())
        assert "cr-ratings-list" in html
        assert "File Ratings" in html

    def test_iife_persistence(self):
        html, _ = generate_code_review_layout(self._make_scheme())
        assert "data-modified" in html
        assert "saveState" in html
        # Check for persistence pattern: reads existing value
        assert "input.value" in html

    def test_diff_line_click_handler(self):
        html, _ = generate_code_review_layout(self._make_scheme())
        assert "ct-diff-line" in html  # Listens for clicks on diff lines
        assert "ct-file-path" in html  # Extracts file path from display

    def test_css_styles(self):
        html, _ = generate_code_review_layout(self._make_scheme())
        assert ".cr-verdict-option" in html
        assert ".cr-comment-card" in html
        assert ".cr-star" in html

    def test_no_keybindings(self):
        _, kb = generate_code_review_layout(self._make_scheme())
        assert kb == []


class TestCodeReviewRegistration:
    """Test schema registry integration."""

    def test_registered(self):
        from potato.server_utils.schemas.registry import schema_registry
        assert "code_review" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        from potato.server_utils.schemas.registry import schema_registry
        html, kb = schema_registry.generate({
            "annotation_type": "code_review",
            "name": "reg_test",
            "description": "Registry test",
        })
        assert "code-review-container" in html

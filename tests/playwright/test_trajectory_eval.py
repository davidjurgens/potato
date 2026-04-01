"""Playwright tests for the trajectory_eval schema.

Tests rendering, interaction, and persistence using navigate-away-and-back
(not page refresh, which gives false positives due to browser form caching).
"""

import json
import os
import pytest

try:
    from playwright.sync_api import expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from tests.playwright.test_base import BasePlaywrightTest


def _make_server(make_server):
    """Create a server with trajectory_eval schema and step data."""
    from tests.helpers.test_utils import create_test_directory

    test_dir = create_test_directory("pw_traj_eval")
    data_file = os.path.join(test_dir, "data.jsonl")
    items = [
        {
            "id": "trace_001",
            "text": "Find weather info",
            "steps": [
                {"action": "search_web('weather')"},
                {"action": "click_result(0)"},
                {"action": "extract_text('.info')"},
            ],
        },
        {
            "id": "trace_002",
            "text": "Book a flight",
            "steps": [
                {"action": "navigate('flights.com')"},
                {"action": "fill_form(from='NYC')"},
            ],
        },
    ]
    with open(data_file, "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")

    schemes = [
        {
            "annotation_type": "trajectory_eval",
            "name": "step_evaluation",
            "description": "Evaluate each step",
            "steps_key": "steps",
            "step_text_key": "action",
            "error_types": [
                {"name": "reasoning", "subtypes": ["logical_error"]},
                {"name": "execution"},
            ],
            "severities": [
                {"name": "minor", "weight": -1},
                {"name": "major", "weight": -5},
            ],
            "show_score": True,
        }
    ]
    return make_server(schemes)


@pytest.mark.playwright
@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed")
class TestTrajectoryEvalPlaywright(BasePlaywrightTest):
    """Test trajectory_eval rendering and persistence in a real browser."""

    def test_step_cards_render(self, page, make_server):
        srv = _make_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".traj-step-card", timeout=10_000)
        cards = page.query_selector_all(".traj-step-card")
        assert len(cards) >= 2, "Expected at least 2 step cards"

    def test_correctness_toggle(self, page, make_server):
        srv = _make_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".traj-step-card", timeout=10_000)

        # Click "Incorrect" on step 0
        btn = page.query_selector(
            '.traj-step-card[data-step-index="0"] .traj-correctness-incorrect'
        )
        assert btn is not None
        btn.click()

        # Error details should appear
        error_div = page.query_selector("#step_evaluation-error-0")
        assert error_div is not None
        assert error_div.is_visible()

        # Click "Correct" on step 0 — error details should hide
        correct_btn = page.query_selector(
            '.traj-step-card[data-step-index="0"] .traj-correctness-correct'
        )
        correct_btn.click()
        page.wait_for_timeout(200)
        assert not error_div.is_visible()

    def test_persistence_navigate_away_and_back(self, page, make_server):
        """The gold-standard persistence test: annotate, navigate away, come back."""
        srv = _make_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".traj-step-card", timeout=10_000)

        # Mark step 0 as incorrect
        page.click('.traj-step-card[data-step-index="0"] .traj-correctness-incorrect')
        page.wait_for_timeout(300)

        # Set error type
        page.select_option(
            '.traj-step-card[data-step-index="0"] .traj-error-type',
            value="reasoning::logical_error",
        )

        # Set severity
        page.click(
            '.traj-step-card[data-step-index="0"] input[type="radio"][value="major"]'
        )

        # Wait for debounce save
        self.wait_for_debounce(page)

        # Navigate to next instance
        self.click_next(page)
        page.wait_for_timeout(500)

        # Navigate back
        self.click_prev(page)
        page.wait_for_timeout(1000)

        # Verify visual state was restored
        page.wait_for_selector(".traj-step-card", timeout=10_000)
        incorrect_btn = page.query_selector(
            '.traj-step-card[data-step-index="0"] .traj-correctness-incorrect.selected'
        )
        assert incorrect_btn is not None, "Incorrect button should be selected after nav"

        error_div = page.query_selector("#step_evaluation-error-0")
        assert error_div is not None and error_div.is_visible(), "Error details should be visible"

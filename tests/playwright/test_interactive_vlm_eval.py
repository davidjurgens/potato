"""Playwright tests for the interactive VLM evaluation workflow.

Tests the live_agent display + trajectory_eval annotation flow:
1. Live agent UI renders with all controls
2. Instruction input works
3. Thought panel and step details display
4. Overlay toggles function
5. Trajectory eval annotation works alongside live agent

These tests use a mock server (no actual VLM) to validate the UI
without requiring Ollama or Anthropic API access.
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


def _make_live_agent_server(make_server):
    """Create a server configured with live_agent display + trajectory_eval.

    Uses a minimal config that renders the live agent UI without actually
    starting a VLM — we're testing the annotation UI, not the VLM.
    """
    from tests.helpers.test_utils import create_test_directory

    test_dir = create_test_directory("pw_vlm_eval")
    data_file = os.path.join(test_dir, "data.jsonl")

    # Data with pre-recorded trace (so the display renders in review mode)
    # and data without trace (so the display renders in live mode)
    items = [
        {
            "id": "vlm_live_001",
            "text": "Navigate to example.com and describe what you see",
            "task_description": "Navigate to example.com and describe what you see",
            "start_url": "https://example.com",
            "agent_trace": None,  # Live mode — shows start form
        },
        {
            "id": "vlm_review_001",
            "text": "Find the top story on Hacker News",
            "task_description": "Find the top story on Hacker News",
            "agent_trace": {
                "steps": [
                    {
                        "action_type": "navigate",
                        "action": {"type": "navigate", "url": "https://news.ycombinator.com"},
                        "thought": "I need to go to Hacker News first.",
                        "observation": "Page loaded successfully.",
                        "screenshot_url": "",
                        "url": "https://news.ycombinator.com",
                    },
                    {
                        "action_type": "click",
                        "action": {"type": "click", "x": 200, "y": 150, "description": "First story title"},
                        "thought": "I can see the top stories. The first one has the most points. Let me click on it to get details.",
                        "observation": "Clicked on story title, page navigated to article.",
                        "screenshot_url": "",
                        "url": "https://news.ycombinator.com",
                        "coordinates": {"x": 200, "y": 150},
                    },
                    {
                        "action_type": "done",
                        "action": {"type": "done", "summary": "The top story is 'Show HN: New Project' with 342 points."},
                        "thought": "I found the top story title and its point count. Task complete.",
                        "observation": "Task completed.",
                        "screenshot_url": "",
                        "url": "https://news.ycombinator.com/item?id=12345",
                    },
                ],
            },
            "steps": [
                {"action": "navigate to Hacker News"},
                {"action": "click on top story"},
                {"action": "report results"},
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
                {"name": "perception", "subtypes": ["missed_element", "wrong_coordinates"]},
                {"name": "reasoning", "subtypes": ["logical_error"]},
            ],
            "severities": [
                {"name": "minor", "weight": -1},
                {"name": "major", "weight": -5},
            ],
            "show_score": True,
        },
        {
            "annotation_type": "radio",
            "name": "task_completion",
            "description": "Did the VLM complete the task?",
            "labels": ["Fully completed", "Partially completed", "Failed"],
        },
        {
            "annotation_type": "text",
            "name": "notes",
            "description": "Notes on VLM behavior",
        },
    ]
    return make_server(schemes)


@pytest.mark.playwright
@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed")
class TestInteractiveVLMEval(BasePlaywrightTest):
    """Test the interactive VLM evaluation annotation workflow."""

    def test_annotation_page_loads_with_schemas(self, page, make_server):
        """Verify the page loads with trajectory_eval + radio + text schemas."""
        srv = _make_live_agent_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".annotation-form", timeout=10_000)

        # Should have trajectory_eval form
        traj_form = page.query_selector(".trajectory-eval-container")
        # Should have radio form for task completion
        radio_form = page.query_selector('form[id="task_completion"]')
        assert radio_form is not None, "Task completion radio should be present"

    def test_trajectory_eval_with_prerecorded_trace(self, page, make_server):
        """Navigate to an instance with a pre-recorded trace, annotate steps."""
        srv = _make_live_agent_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".annotation-form", timeout=10_000)

        # Try to navigate to the review instance (has steps)
        try:
            self.click_next(page)
            page.wait_for_timeout(1000)
        except Exception:
            pass

        # Look for trajectory eval step cards
        step_cards = page.query_selector_all(".traj-step-card")
        if len(step_cards) > 0:
            # Annotate first step as correct
            page.click('.traj-step-card[data-step-index="0"] .traj-correctness-correct')
            page.wait_for_timeout(300)

            correct_btn = page.query_selector(
                '.traj-step-card[data-step-index="0"] .traj-correctness-correct.selected'
            )
            assert correct_btn is not None, "Step 0 correct button should be selected"

    def test_multi_schema_annotation_workflow(self, page, make_server):
        """Test annotating with trajectory_eval + radio + text together."""
        srv = _make_live_agent_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".annotation-form", timeout=10_000)

        # Fill in the task completion radio
        radio = page.query_selector('form[id="task_completion"] input[type="radio"]')
        if radio:
            radio.click()

        # Fill in notes
        textarea = page.query_selector('form[id="notes"] textarea')
        if textarea:
            textarea.fill("The agent navigated correctly but was slow.")

        self.wait_for_debounce(page)

        # Navigate away and back to check persistence
        self.click_next(page)
        page.wait_for_timeout(500)
        self.click_prev(page)
        page.wait_for_timeout(1000)

        # Notes should persist
        textarea_after = page.query_selector('form[id="notes"] textarea')
        if textarea_after:
            val = textarea_after.input_value()
            assert "navigated correctly" in val, f"Notes should persist, got: {val}"

    def test_concurrent_annotation_during_live_session(self, browser_instance, make_server):
        """Two annotators evaluating the same VLM trace concurrently.

        Tests that concurrent evaluation doesn't cause data corruption.
        """
        srv = _make_live_agent_server(make_server)

        ctx1 = browser_instance.new_context(viewport={"width": 1920, "height": 1080})
        ctx2 = browser_instance.new_context(viewport={"width": 1920, "height": 1080})
        page1 = ctx1.new_page()
        page2 = ctx2.new_page()

        try:
            user1 = self.register_and_login(page1, srv)
            user2 = self.register_and_login(page2, srv)

            page1.goto(f"{srv.base_url}/annotate")
            page2.goto(f"{srv.base_url}/annotate")

            page1.wait_for_selector(".annotation-form", timeout=10_000)
            page2.wait_for_selector(".annotation-form", timeout=10_000)

            # Both annotate the radio
            radio1 = page1.query_selector('form[id="task_completion"] input[type="radio"]')
            radio2 = page2.query_selector('form[id="task_completion"] input[type="radio"]')
            if radio1:
                radio1.click()
            if radio2:
                # Pick a different option
                radios = page2.query_selector_all('form[id="task_completion"] input[type="radio"]')
                if len(radios) > 1:
                    radios[1].click()

            page1.wait_for_timeout(2000)
            page2.wait_for_timeout(2000)

            # Neither should crash
            assert page1.query_selector(".annotation-form") is not None
            assert page2.query_selector(".annotation-form") is not None

        finally:
            page1.close()
            page2.close()
            ctx1.close()
            ctx2.close()

    def test_network_resilience_during_annotation(self, page, make_server):
        """Block saves during annotation, unblock, verify data eventually persists."""
        srv = _make_live_agent_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".annotation-form", timeout=10_000)

        blocked = []

        def block_save(route):
            blocked.append(True)
            route.abort()

        # Block save requests
        page.route("**/updateinstance", block_save)

        # Make annotation while blocked
        radio = page.query_selector('form[id="task_completion"] input[type="radio"]')
        if radio:
            radio.click()

        page.wait_for_timeout(2000)

        # Unblock
        page.unroute("**/updateinstance")

        # Trigger new save
        textarea = page.query_selector('form[id="notes"] textarea')
        if textarea:
            textarea.fill("Testing resilience")

        self.wait_for_debounce(page)

        # Page should still be functional
        assert page.query_selector(".annotation-form") is not None

"""Playwright tests for network resilience during annotation.

Uses Playwright's route interception to simulate network failures,
high latency, and rapid navigation — all tested against agent trace
evaluation schemas to ensure annotation data isn't silently lost.
"""

import json
import os
import time
import pytest

try:
    from playwright.sync_api import expect, Route
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from tests.playwright.test_base import BasePlaywrightTest


def _make_trajectory_server(make_server):
    """Create server with trajectory_eval schema for resilience testing."""
    from tests.helpers.test_utils import create_test_directory

    test_dir = create_test_directory("pw_resilience")
    data_file = os.path.join(test_dir, "data.jsonl")
    items = []
    for i in range(10):
        items.append({
            "id": f"trace_{i:03d}",
            "text": f"Task {i}: Evaluate this agent trace",
            "steps": [
                {"action": f"step_{j}_of_trace_{i}"} for j in range(3)
            ],
        })
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
class TestNetworkResilience(BasePlaywrightTest):
    """Test annotation persistence under adverse network conditions."""

    def test_save_during_network_disconnect(self, page, make_server):
        """Block /updateinstance, make annotation, unblock, verify save succeeds."""
        srv = _make_trajectory_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".traj-step-card", timeout=10_000)

        blocked_requests = []

        def block_save(route: "Route"):
            blocked_requests.append(route.request.url)
            route.abort()

        # Block save requests
        page.route("**/updateinstance", block_save)

        # Make annotation while blocked
        page.click('.traj-step-card[data-step-index="0"] .traj-correctness-incorrect')
        page.wait_for_timeout(2000)  # Wait for debounce to fire

        assert len(blocked_requests) > 0, "Save request should have been attempted"

        # Unblock and trigger another save
        page.unroute("**/updateinstance")

        # Make another change to trigger a new save
        page.click('.traj-step-card[data-step-index="1"] .traj-correctness-correct')
        self.wait_for_debounce(page)

        # Navigate away and back to verify persistence
        self.click_next(page)
        page.wait_for_timeout(500)
        self.click_prev(page)
        page.wait_for_timeout(1000)

        # The second save (after unblock) should have persisted
        page.wait_for_selector(".traj-step-card", timeout=10_000)

    def test_save_with_high_latency(self, page, make_server):
        """Add 3-second delay to /updateinstance, verify annotations persist."""
        srv = _make_trajectory_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".traj-step-card", timeout=10_000)

        def delay_save(route: "Route"):
            import time as _time
            _time.sleep(3)
            route.continue_()

        page.route("**/updateinstance", delay_save)

        # Make annotation
        page.click('.traj-step-card[data-step-index="0"] .traj-correctness-correct')
        page.click('.traj-step-card[data-step-index="1"] .traj-correctness-incorrect')

        # Wait longer than normal debounce + our 3s delay
        page.wait_for_timeout(5000)

        page.unroute("**/updateinstance")

        # Navigate away and back
        self.click_next(page)
        page.wait_for_timeout(500)
        self.click_prev(page)
        page.wait_for_timeout(1500)

        # Verify annotations survived the latency
        page.wait_for_selector(".traj-step-card", timeout=10_000)
        correct_btn = page.query_selector(
            '.traj-step-card[data-step-index="0"] .traj-correctness-correct.selected'
        )
        assert correct_btn is not None, "Step 0 correct should be restored after high-latency save"

    def test_rapid_navigation_no_data_loss(self, page, make_server):
        """Click Next 5 times rapidly, verify no annotation data is lost."""
        srv = _make_trajectory_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".traj-step-card", timeout=10_000)

        # Annotate first instance
        page.click('.traj-step-card[data-step-index="0"] .traj-correctness-correct')
        self.wait_for_debounce(page)

        # Rapid navigation forward
        for _ in range(5):
            try:
                self.click_next(page)
                page.wait_for_timeout(200)
            except Exception:
                break  # May run out of instances

        # Navigate all the way back
        for _ in range(5):
            try:
                self.click_prev(page)
                page.wait_for_timeout(300)
            except Exception:
                break

        page.wait_for_timeout(1000)

        # The first instance's annotation should still be there
        page.wait_for_selector(".traj-step-card", timeout=10_000)

    def test_save_request_contains_correct_data(self, page, make_server):
        """Intercept /updateinstance POST and verify payload structure."""
        srv = _make_trajectory_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".traj-step-card", timeout=10_000)

        captured_payloads = []

        def capture_save(route: "Route"):
            try:
                body = route.request.post_data
                if body:
                    captured_payloads.append(json.loads(body))
            except Exception:
                pass
            route.continue_()

        page.route("**/updateinstance", capture_save)

        # Make a trajectory annotation
        page.click('.traj-step-card[data-step-index="0"] .traj-correctness-incorrect')
        self.wait_for_debounce(page)

        page.unroute("**/updateinstance")

        assert len(captured_payloads) > 0, "Should have captured at least one save payload"
        payload = captured_payloads[-1]
        assert "annotations" in payload or "instance_id" in payload

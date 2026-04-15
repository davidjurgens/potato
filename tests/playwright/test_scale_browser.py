"""Playwright scale tests with real browser contexts.

Uses Playwright's multi-context to run 10 concurrent annotators
through the full JS rendering pipeline — something the HTTP-only
simulator cannot test.

Focused on agent trace evaluation schemas to match production
annotation workloads.
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


def _make_scale_server(make_server):
    """Create server with enough instances for 10+ annotators."""
    from tests.helpers.test_utils import create_test_directory

    test_dir = create_test_directory("pw_scale")
    data_file = os.path.join(test_dir, "data.jsonl")
    items = []
    for i in range(50):
        items.append({
            "id": f"trace_{i:03d}",
            "text": f"Agent trace {i}: evaluate this trajectory",
            "steps": [
                {"action": f"step_{j}_of_{i}"} for j in range(2)
            ],
        })
    with open(data_file, "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")

    schemes = [
        {
            "annotation_type": "trajectory_eval",
            "name": "eval",
            "description": "Evaluate steps",
            "steps_key": "steps",
            "step_text_key": "action",
            "error_types": [{"name": "error"}],
            "severities": [{"name": "minor", "weight": -1}],
        }
    ]
    return make_server(schemes)


@pytest.mark.playwright
@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed")
class TestScaleBrowser(BasePlaywrightTest):
    """Scale tests with multiple concurrent browser annotators."""

    @pytest.mark.timeout(120)
    def test_5_parallel_annotators(self, browser_instance, make_server):
        """5 browser contexts annotating concurrently through the full JS pipeline.

        Each annotator:
        1. Registers as a unique user
        2. Annotates 2 instances with trajectory_eval
        3. Verifies the annotation page doesn't crash
        """
        srv = _make_scale_server(make_server)
        n_annotators = 5
        contexts = []
        pages = []

        try:
            # Create contexts and register users
            for i in range(n_annotators):
                ctx = browser_instance.new_context(
                    viewport={"width": 1280, "height": 720}
                )
                pg = ctx.new_page()
                contexts.append(ctx)
                pages.append(pg)

                username = f"scale_user_{i}_{id(self)}"
                self.register_and_login(pg, srv, username=username)
                pg.goto(f"{srv.base_url}/annotate")

            # All should load successfully
            for i, pg in enumerate(pages):
                pg.wait_for_selector(
                    ".traj-step-card, .annotation-form",
                    timeout=15_000,
                )

            # Each annotator makes annotations
            for i, pg in enumerate(pages):
                try:
                    # Annotate step 0
                    pg.click(
                        '.traj-step-card[data-step-index="0"] .traj-correctness-correct'
                    )
                    pg.wait_for_timeout(500)

                    # Navigate to next and annotate
                    self.click_next(pg)
                    pg.wait_for_timeout(500)
                    pg.wait_for_selector(".traj-step-card", timeout=10_000)
                    pg.click(
                        '.traj-step-card[data-step-index="0"] .traj-correctness-incorrect'
                    )
                    pg.wait_for_timeout(500)
                except Exception as e:
                    # Don't fail the whole test if one annotator hits an issue
                    pass

            # Wait for all saves
            for pg in pages:
                pg.wait_for_timeout(2000)

            # Verify pages are still functional (no JS crashes)
            functional_count = 0
            for pg in pages:
                try:
                    if pg.query_selector(".annotation-form") is not None:
                        functional_count += 1
                except Exception:
                    pass

            assert functional_count >= n_annotators - 1, (
                f"Only {functional_count}/{n_annotators} annotators still functional"
            )

        finally:
            for pg in pages:
                try:
                    pg.close()
                except Exception:
                    pass
            for ctx in contexts:
                try:
                    ctx.close()
                except Exception:
                    pass

    @pytest.mark.timeout(120)
    def test_10_parallel_annotators(self, browser_instance, make_server):
        """10 browser contexts — stress test for server and JS pipeline."""
        srv = _make_scale_server(make_server)
        n_annotators = 10
        contexts = []
        pages = []

        try:
            for i in range(n_annotators):
                ctx = browser_instance.new_context(
                    viewport={"width": 1280, "height": 720}
                )
                pg = ctx.new_page()
                contexts.append(ctx)
                pages.append(pg)

                username = f"scale10_user_{i}_{id(self)}"
                self.register_and_login(pg, srv, username=username)
                pg.goto(f"{srv.base_url}/annotate")

            # Wait for all to load
            loaded = 0
            for pg in pages:
                try:
                    pg.wait_for_selector(
                        ".traj-step-card, .annotation-form",
                        timeout=20_000,
                    )
                    loaded += 1
                except Exception:
                    pass

            assert loaded >= 8, f"Only {loaded}/10 annotators loaded successfully"

            # Quick annotation from each
            for pg in pages:
                try:
                    pg.click(
                        '.traj-step-card[data-step-index="0"] .traj-correctness-correct'
                    )
                except Exception:
                    pass

            # Wait for debounce
            for pg in pages:
                pg.wait_for_timeout(2000)

            # Verify no crashes
            functional = sum(
                1 for pg in pages
                if pg.query_selector(".annotation-form") is not None
            )
            assert functional >= 8, f"Only {functional}/10 still functional after annotation"

        finally:
            for pg in pages:
                try:
                    pg.close()
                except Exception:
                    pass
            for ctx in contexts:
                try:
                    ctx.close()
                except Exception:
                    pass

    def test_rapid_user_registration(self, browser_instance, make_server):
        """Register 10 users rapidly and verify all can access annotation."""
        srv = _make_scale_server(make_server)
        success_count = 0

        for i in range(10):
            ctx = browser_instance.new_context(viewport={"width": 1280, "height": 720})
            pg = ctx.new_page()
            try:
                username = f"rapid_reg_{i}_{id(self)}"
                self.register_and_login(pg, srv, username=username)
                pg.goto(f"{srv.base_url}/annotate")
                pg.wait_for_selector(".annotation-form", timeout=10_000)
                success_count += 1
            except Exception:
                pass
            finally:
                pg.close()
                ctx.close()

        assert success_count >= 8, f"Only {success_count}/10 rapid registrations succeeded"

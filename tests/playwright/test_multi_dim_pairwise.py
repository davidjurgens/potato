"""Playwright tests for multi-dimensional pairwise and justification."""

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
    """Create server with multi-dim pairwise schema."""
    from tests.helpers.test_utils import create_test_directory

    test_dir = create_test_directory("pw_multi_dim")
    data_file = os.path.join(test_dir, "data.jsonl")
    items = [
        {
            "id": "cmp_001",
            "text": ["Response A: detailed answer", "Response B: brief answer"],
        },
        {
            "id": "cmp_002",
            "text": ["Response A: another answer", "Response B: different answer"],
        },
    ]
    with open(data_file, "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")

    schemes = [
        {
            "annotation_type": "pairwise",
            "name": "comparison",
            "description": "Compare responses",
            "mode": "multi_dimension",
            "items_key": "text",
            "dimensions": [
                {"name": "helpfulness", "description": "More helpful?", "allow_tie": True},
                {"name": "accuracy", "description": "More accurate?"},
            ],
            "justification": {
                "reason_categories": ["More accurate", "Safer"],
                "min_rationale_chars": 5,
            },
        }
    ]
    return make_server(schemes)


@pytest.mark.playwright
@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed")
class TestMultiDimPairwisePlaywright(BasePlaywrightTest):

    def test_dimension_rows_render(self, page, make_server):
        srv = _make_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".pairwise-dimension-row", timeout=10_000)
        rows = page.query_selector_all(".pairwise-dimension-row")
        assert len(rows) == 2

    def test_tile_selection_per_dimension(self, page, make_server):
        srv = _make_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".pairwise-dimension-row", timeout=10_000)

        # Select A for helpfulness
        page.click('.pairwise-dimension-row[data-dimension="helpfulness"] .pairwise-tile[data-value="A"]')
        # Select B for accuracy
        page.click('.pairwise-dimension-row[data-dimension="accuracy"] .pairwise-tile[data-value="B"]')

        page.wait_for_timeout(300)

        # Verify selections are independent
        help_a = page.query_selector('.pairwise-dimension-row[data-dimension="helpfulness"] .pairwise-tile[data-value="A"].selected')
        acc_b = page.query_selector('.pairwise-dimension-row[data-dimension="accuracy"] .pairwise-tile[data-value="B"].selected')
        assert help_a is not None
        assert acc_b is not None

    def test_justification_section_renders(self, page, make_server):
        srv = _make_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".pairwise-justification", timeout=10_000)
        assert page.query_selector(".pairwise-rationale-textarea") is not None
        assert len(page.query_selector_all(".pairwise-reason-cb")) == 2

    def test_persistence_navigate_away_and_back(self, page, make_server):
        srv = _make_server(make_server)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".pairwise-dimension-row", timeout=10_000)

        # Make selections
        page.click('.pairwise-dimension-row[data-dimension="helpfulness"] .pairwise-tile[data-value="A"]')
        page.click('.pairwise-dimension-row[data-dimension="accuracy"] .pairwise-tile[data-value="B"]')

        # Fill justification
        page.fill(".pairwise-rationale-textarea", "A is clearly better overall")
        page.click('.pairwise-reason-cb[value="More accurate"]')

        self.wait_for_debounce(page)

        # Navigate away and back
        self.click_next(page)
        page.wait_for_timeout(500)
        self.click_prev(page)
        page.wait_for_timeout(1000)

        # Verify visual state
        help_a = page.query_selector('.pairwise-dimension-row[data-dimension="helpfulness"] .pairwise-tile[data-value="A"].selected')
        acc_b = page.query_selector('.pairwise-dimension-row[data-dimension="accuracy"] .pairwise-tile[data-value="B"].selected')
        assert help_a is not None, "helpfulness=A should be restored"
        assert acc_b is not None, "accuracy=B should be restored"

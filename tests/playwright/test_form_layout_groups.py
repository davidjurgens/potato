"""Every scheme listed in a `layout.groups` entry ends up inside that group.

`validate_layout_config` checks each name in `groups[].schemas` against
`annotation_schemes`, so a config naming a real scheme always passes. The
browser then matched group members on `data-schema-name`, which sixteen
generators -- `slider`, `span`, `multi_document_event`, and the canvas and media
schemes -- never render. Those schemes stayed outside the group they were listed
in, and the page came up with a titled section holding fewer questions than the
config gave it, the rest loose above it in a different order. Nothing warned at
any layer.

Matching falls back to the element id, which every generator sets to the scheme
name.
"""

from __future__ import annotations

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

SCHEMES = [
    {"annotation_type": "radio", "name": "s_radio", "description": "Radio?",
     "labels": ["a", "b"]},
    {"annotation_type": "slider", "name": "s_slider", "description": "Slider?",
     "min_value": 0, "max_value": 100, "starting_value": 50},
    {"annotation_type": "span", "name": "s_span", "description": "Span?",
     "labels": ["thing"]},
]

LAYOUT = {
    "layout": {
        "grid": {"columns": 2},
        "groups": [
            {"id": "everything", "title": "All three questions",
             "schemas": ["s_radio", "s_slider", "s_span"]},
        ],
    }
}


@pytest.fixture
def grouped_server(make_server):
    return make_server(SCHEMES, num_items=2, extra_config=LAYOUT)


class TestGroupMembership(BasePlaywrightTest):

    def _dom(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_selector(".annotation-form")
        page.wait_for_timeout(2000)
        return page.evaluate("""() => {
            const group = document.querySelector('.annotation-form-group');
            const name = e => e.getAttribute('data-schema-name') || e.id;
            return {
                group_exists: !!group,
                inside: group
                    ? [...group.querySelectorAll('.annotation-form')].map(name)
                    : [],
                all: [...document.querySelectorAll('.annotation-form')].map(name),
            };
        }""")

    def test_the_group_holds_every_scheme_it_named(self, page, grouped_server):
        dom = self._dom(page, grouped_server)
        assert dom["group_exists"], "no group was created at all"
        assert set(dom["inside"]) == {"s_radio", "s_slider", "s_span"}, (
            f"the group was given three schemes and holds {dom['inside']} -- "
            "a scheme whose generator omits data-schema-name was dropped")

    def test_nothing_is_left_loose_outside_the_group(self, page, grouped_server):
        dom = self._dom(page, grouped_server)
        assert set(dom["all"]) == set(dom["inside"])

    def test_the_configured_order_is_kept(self, page, grouped_server):
        """Members used to come out in generator order rather than the order the
        group listed them, which is the order a researcher chose."""
        dom = self._dom(page, grouped_server)
        assert dom["inside"] == ["s_radio", "s_slider", "s_span"]

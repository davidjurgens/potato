"""
Browser tests for the single-select persistence fix (GH #167).

The reported bug only manifests when an annotator *changes their mind*: clicking a
likert scale point, waiting for the save debounce, then clicking a different point.
Existing likert UI tests only ever click once, which is why none of them caught this.

Persistence is verified by navigating away and back — never by ``page.reload()``.
Browsers cache form state across a refresh, so a reload-based check passes even when
the server stored nothing (or stored two values). The server is also queried directly
via ``/get_annotations``, which is the only assertion that can distinguish "one value
stored" from "two values stored, one of them rendered".
"""

import pytest

from tests.playwright.test_base import BasePlaywrightTest

SCHEMES = [
    {
        "annotation_type": "radio",
        "name": "veracity",
        "description": "Is this claim true?",
        "labels": ["True", "False", "Unverifiable"],
    },
    {
        "annotation_type": "likert",
        "name": "confidence",
        "description": "How confident are you?",
        "min_label": "Not confident",
        "max_label": "Very confident",
        "size": 5,
    },
]


@pytest.mark.playwright
class TestSingleSelectPersistence(BasePlaywrightTest):

    @pytest.fixture
    def ss_server(self, make_server):
        return make_server(SCHEMES)

    def _instance_id(self, page):
        """The instance the browser is actually on.

        BasePlaywrightTest.get_instance_id() reads a ``#instance-id`` element that this
        layout does not render, so it returns None and every /get_annotations lookup
        would silently query the wrong instance. Read the id the client itself uses.
        """
        instance_id = page.evaluate(
            "() => (window.currentInstance && window.currentInstance.id) || null")
        assert instance_id, "could not determine the current instance id"
        return instance_id

    def _click_option(self, page, schema, label):
        """Click a radio/likert option by its schema + label_name attributes.

        Likert inputs are visually hidden behind a styled <label>, so a plain click
        misses; dispatch the click on the input itself and fire `change` so the same
        handlers run as for a real user click.
        """
        page.evaluate(
            """([schema, label]) => {
                const input = document.querySelector(
                    `input[type=radio][schema="${schema}"][label_name="${label}"]`);
                if (!input) throw new Error(`no input for ${schema}/${label}`);
                input.click();
            }""",
            [schema, label],
        )

    def _stored(self, page, server, instance_id, schema):
        anns = self.verify_server_annotations(page, server, instance_id)
        return anns.get("label_annotations", {}).get(schema, [])

    def test_changed_likert_stores_exactly_one_value(self, page, ss_server):
        """The core regression: 5 then 4 must leave only 4 on the server."""
        self.register_and_login(page, ss_server)
        page.goto(f"{ss_server.base_url}/annotate")
        page.wait_for_selector("input[type=radio][schema='confidence']")
        instance_id = self._instance_id(page)

        self._click_option(page, "confidence", "5")
        self.wait_for_debounce(page)          # let the first save actually land
        self._click_option(page, "confidence", "4")
        self.wait_for_debounce(page)

        stored = self._stored(page, ss_server, instance_id, "confidence")
        assert stored == ["4"], (
            f"expected exactly one likert value on the server, got {stored}")

    def test_changed_likert_survives_navigation(self, page, ss_server):
        """Navigate away and back — the DOM must show one selection and the server
        must still hold one value."""
        self.register_and_login(page, ss_server)
        page.goto(f"{ss_server.base_url}/annotate")
        page.wait_for_selector("input[type=radio][schema='confidence']")
        instance_id = self._instance_id(page)

        self._click_option(page, "confidence", "5")
        self.wait_for_debounce(page)
        self._click_option(page, "confidence", "4")
        self.wait_for_debounce(page)

        self.click_next(page)
        page.wait_for_timeout(500)
        self.click_prev(page)
        page.wait_for_selector("input[type=radio][schema='confidence']")

        checked = page.evaluate(
            """() => Array.from(document.querySelectorAll(
                    "input[type=radio][schema='confidence']"))
                .filter(i => i.checked)
                .map(i => i.getAttribute('label_name'))"""
        )
        assert checked == ["4"], f"DOM shows {checked} selected after navigating back"
        assert self._stored(page, ss_server, instance_id, "confidence") == ["4"]

        # The restored in-browser state must also be clean, because it is what the
        # NEXT save re-posts: if loadAnnotations() seeded two values for the schema,
        # touching an unrelated field would write both straight back and re-cement the
        # corruption. (currentAnnotations is a module-scoped `let`, so it cannot be
        # read from the page directly — provoke a save and check the result instead.)
        self._click_option(page, "veracity", "True")
        self.wait_for_debounce(page)
        assert self._stored(page, ss_server, instance_id, "confidence") == ["4"], (
            "a save after navigating back re-introduced a second likert value")

    def test_changed_radio_stores_exactly_one_value(self, page, ss_server):
        self.register_and_login(page, ss_server)
        page.goto(f"{ss_server.base_url}/annotate")
        page.wait_for_selector("input[type=radio][schema='veracity']")
        instance_id = self._instance_id(page)

        self._click_option(page, "veracity", "True")
        self.wait_for_debounce(page)
        self._click_option(page, "veracity", "False")
        self.wait_for_debounce(page)

        assert self._stored(page, ss_server, instance_id, "veracity") == ["False"]

    def test_three_way_revision_keeps_the_last(self, page, ss_server):
        """5 -> 4 -> 5. The dict preserves FIRST-write order, so a naive
        last-in-order reading would answer 4; the stored state must be 5."""
        self.register_and_login(page, ss_server)
        page.goto(f"{ss_server.base_url}/annotate")
        page.wait_for_selector("input[type=radio][schema='confidence']")
        instance_id = self._instance_id(page)

        for point in ("5", "4", "5"):
            self._click_option(page, "confidence", point)
            self.wait_for_debounce(page)

        assert self._stored(page, ss_server, instance_id, "confidence") == ["5"]

    def test_revision_trail_records_the_superseded_value(self, page, ss_server):
        """Changing the answer must stay visible in the behavioral trail, with a real
        old_value — it used to always be null for radio/likert."""
        self.register_and_login(page, ss_server)
        page.goto(f"{ss_server.base_url}/annotate")
        page.wait_for_selector("input[type=radio][schema='confidence']")
        instance_id = self._instance_id(page)

        self._click_option(page, "confidence", "5")
        self.wait_for_debounce(page)
        self._click_option(page, "confidence", "4")
        self.wait_for_debounce(page)

        resp = page.request.get(
            f"{ss_server.base_url}/api/behavioral_data/{instance_id}")
        assert resp.ok, f"/api/behavioral_data returned {resp.status}"
        body = resp.json()
        changes = (body.get("annotation_changes")
                   or body.get("behavioral_data", {}).get("annotation_changes", []))
        confidence = [c for c in changes if c.get("schema_name") == "confidence"]

        assert [c.get("new_value") for c in confidence] == ["5", "4"], (
            f"trail lost the revision: {confidence}")
        assert confidence[-1].get("old_value") == "5", (
            "old_value must name the superseded answer, not null")
        assert confidence[-1].get("old_label") == "5"

"""
Browser test: a code_review answer is still on screen after navigating back.

The widget redraws its verdict radio and comment cards from the hidden input
as soon as its script runs. annotation.js then clears every text input and
radio on the page (``clearAllFormInputs``) before restoring the item's
answers, and the widget's visible controls are not annotation inputs, so
nothing put them back: the hidden input still held the verdict and the
comment, while the page showed no verdict and an empty file path.

Persistence is checked by navigating away and back, never ``page.reload()``
(browsers cache form state across a refresh).
"""

import json

import pytest

from tests.playwright.test_base import BasePlaywrightTest

SCHEMES = [
    {
        "annotation_type": "code_review",
        "name": "review",
        "description": "Review the agent's code changes",
    },
]


@pytest.mark.playwright
class TestCodeReviewPersistence(BasePlaywrightTest):

    @pytest.fixture
    def cr_server(self, make_server):
        return make_server(SCHEMES)

    def _instance_id(self, page):
        instance_id = page.evaluate(
            "() => (window.currentInstance && window.currentInstance.id) || null")
        assert instance_id, "could not determine the current instance id"
        return instance_id

    def test_verdict_and_comment_survive_navigation(self, page, cr_server):
        self.register_and_login(page, cr_server)
        page.goto(f"{cr_server.base_url}/annotate")
        page.wait_for_selector("#review-verdicts input[type=radio]")
        instance_id = self._instance_id(page)

        page.click("#review-verdicts input[value='request_changes']")
        page.click("#review-add-comment")
        card = page.locator("#review-comments .cr-comment-card").first
        card.locator(".cr-comment-category").select_option("security")
        card.locator(".cr-comment-file").fill("src/auth/login.py")
        card.locator(".cr-comment-line").fill("42")
        card.locator(".cr-comment-text").fill("Password compared in plain text.")
        self.wait_for_debounce(page)

        # The server holds the answer before we look at the page again.
        stored = self.verify_server_annotations(page, cr_server, instance_id)
        assert "request_changes" in json.dumps(stored), stored

        self.click_next(page)
        page.wait_for_function(
            "id => window.currentInstance && window.currentInstance.id !== id",
            arg=instance_id)
        self.click_prev(page)
        page.wait_for_function(
            "id => window.currentInstance && window.currentInstance.id === id",
            arg=instance_id)
        page.wait_for_selector("#review-comments .cr-comment-card")
        # Let every post-load step (populateInputValues, instance-ready) run.
        page.wait_for_timeout(500)

        shown = page.evaluate("""() => {
            const checked = document.querySelector(
                '#review-verdicts input[type=radio]:checked');
            const opt = document.querySelector('.cr-verdict-request_changes');
            const card = document.querySelector('#review-comments .cr-comment-card');
            return {
                verdict: checked ? checked.value : null,
                highlighted: !!(opt && opt.classList.contains('cr-checked')),
                category: card.querySelector('.cr-comment-category').value,
                file: card.querySelector('.cr-comment-file').value,
                line: card.querySelector('.cr-comment-line').value,
                text: card.querySelector('.cr-comment-text').value,
            };
        }""")
        assert shown == {
            "verdict": "request_changes",
            "highlighted": True,
            "category": "security",
            "file": "src/auth/login.py",
            "line": "42",
            "text": "Password compared in plain text.",
        }, shown

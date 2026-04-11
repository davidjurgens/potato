"""
Base helpers for Playwright annotation tests.

Provides ``BasePlaywrightTest`` — a mixin that mirrors the Selenium
``BaseSeleniumTest`` API: auto-register, auto-login, and a
``verify_server_annotations()`` helper that hits the ``/get_annotations``
API to confirm persistence (the gold standard).

Usage:
    import pytest
    from tests.playwright.test_base import BasePlaywrightTest

    @pytest.mark.playwright
    class TestMySchema(BasePlaywrightTest):
        def test_something(self, page, server):
            self.register_and_login(page, server)
            page.goto(f"{server.base_url}/annotate")
            # ... interact ...
            anns = self.verify_server_annotations(page, server, "instance_0")
            assert "my_schema" in anns
"""

import time
import json
import pytest

try:
    from playwright.sync_api import expect, Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@pytest.mark.playwright
class BasePlaywrightTest:
    """Mixin providing auth helpers and annotation verification for Playwright tests."""

    _user_counter = 0

    @classmethod
    def _next_user(cls):
        cls._user_counter += 1
        return f"pw_user_{cls.__name__}_{cls._user_counter}_{int(time.time())}"

    # ---- auth ----

    def register_and_login(self, page: "Page", server, username=None):
        """Register and log in a unique user, ending up on the annotation page.

        Works for both ``require_password=False`` (simple login) and
        ``require_password=True`` (register tab + login tab) flows.
        """
        if username is None:
            username = self._next_user()
        self._current_user = username

        page.goto(f"{server.base_url}/")
        page.wait_for_selector("#login-email", timeout=10_000)

        # Detect password mode
        register_tab = page.query_selector("#register-tab")
        if register_tab:
            # Password mode — register first
            register_tab.click()
            page.wait_for_selector("#register-content", state="visible")
            page.fill("#register-email", username)
            page.fill("#register-pass", "test_password_123")
            page.click("#register-content form button[type='submit'], #register-content form input[type='submit']")
            page.wait_for_timeout(500)

            # Now login
            page.goto(f"{server.base_url}/")
            login_tab = page.query_selector("#login-tab")
            if login_tab:
                login_tab.click()
            page.wait_for_selector("#login-email", state="visible")
            page.fill("#login-email", username)
            page.fill("#login-pass", "test_password_123")
            page.click("#login-content form button[type='submit'], #login-content form input[type='submit']")
        else:
            # Simple mode
            page.fill("#login-email", username)
            page.click("button[type='submit']")

        # Wait for annotation interface
        page.wait_for_selector("#main-content", state="visible", timeout=15_000)
        return username

    # ---- annotation verification ----

    def verify_server_annotations(self, page: "Page", server, instance_id):
        """Hit the ``/get_annotations`` API and return the parsed JSON.

        This is the gold-standard check — it reads from the server's
        in-memory state, bypassing any browser caching.
        """
        resp = page.request.get(
            f"{server.base_url}/get_annotations?instance_id={instance_id}"
        )
        assert resp.ok, f"/get_annotations returned {resp.status}"
        return resp.json()

    # ---- navigation helpers ----

    def click_next(self, page: "Page"):
        """Click the Next button and wait for new content to load."""
        page.click("#next-instance-btn, #annotate-next-btn, button:has-text('Next')")
        page.wait_for_timeout(500)

    def click_prev(self, page: "Page"):
        """Click the Previous button and wait for content to load."""
        page.click("#prev-instance-btn, #annotate-prev-btn, button:has-text('Previous'), button:has-text('Prev')")
        page.wait_for_timeout(500)

    def wait_for_debounce(self, page: "Page", ms=1500):
        """Wait long enough for the annotation debounce timer to fire."""
        page.wait_for_timeout(ms)

    # ---- JS helpers ----

    def get_current_annotations(self, page: "Page"):
        """Return the in-browser ``currentAnnotations`` object."""
        return page.evaluate("() => window.currentAnnotations || {}")

    def get_instance_id(self, page: "Page"):
        """Return the current instance ID shown in the browser."""
        return page.evaluate("""() => {
            const el = document.getElementById('instance-id');
            return el ? el.textContent.trim() : null;
        }""")

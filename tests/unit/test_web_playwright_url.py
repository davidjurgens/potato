"""Regression tests for URL normalization in the Playwright web-agent session.

Bug: typing a bare host (e.g. ``google.com``) into the Live Web Browsing Agent
start form — or an agent emitting a schemeless ``navigate`` action — reached
Playwright's ``page.goto`` unchanged and failed with
"Protocol error (Page.navigate): Cannot navigate to invalid URL", surfacing to
the user as "Failed to start Playwright browser session".

Fix: ``normalize_url`` prepends ``https://`` when no scheme is present, applied
at both ``PlaywrightSession.start`` and ``PlaywrightSession.navigate``.
"""

import pytest

from potato.web_playwright import normalize_url


class TestNormalizeUrl:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # The exact bug report: bare host with no scheme.
            ("google.com", "https://google.com"),
            ("www.wikipedia.org", "https://www.wikipedia.org"),
            ("example.com/path?q=1", "https://example.com/path?q=1"),
            # Whitespace is stripped.
            ("  google.com  ", "https://google.com"),
            # Protocol-relative URLs.
            ("//cdn.example.com", "https://cdn.example.com"),
        ],
    )
    def test_adds_scheme_when_missing(self, raw, expected):
        assert normalize_url(raw) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://en.wikipedia.org/wiki/Eiffel_Tower",
            "http://example.com",
            "https://example.com:8080/x",
            "about:blank",
            "file:///tmp/page.html",
        ],
    )
    def test_leaves_valid_urls_untouched(self, url):
        assert normalize_url(url) == url

    @pytest.mark.parametrize("empty", ["", "   ", None])
    def test_empty_input_returned_for_caller_validation(self, empty):
        # Empty/blank is returned as-is (falsy) so route/UI validation can
        # reject it with a clear "start_url is required" message rather than
        # producing a bogus "https://".
        assert not normalize_url(empty)

"""Odd input shapes are named, not fatal.

`[{"id": "a", "text": "normal"}, {"id": "nulltxt", "text": null}]` passed
`potato validate --strict` and then killed the boot with

    TypeError: expected string or bytes-like object, got 'NoneType'

naming no id, no field and no file. Same for a numeric text. On a 20k-row
export the next move was bisecting by hand. `get_displayed_text` already
branched for dict and list; it was simply not total.

The second finding here is narrower than it first looked, and the audit
corrected itself before I acted on it: the horizontal-whitespace collapse
applies to the DEFAULT rendering path only. A config declaring
`instance_display` preserves indentation exactly, even at `type: text`. So the
fix is not to drop the normalization -- span offsets depend on it -- but to
warn under the exact condition where the author's data is being changed
without them knowing: whitespace that carries meaning, and no
`instance_display`.
"""

import logging

import pytest


class TestNonStringTextDoesNotCrash:

    @pytest.mark.parametrize("value,expected", [
        (None, ""),
        (12345, "12345"),
        (3.5, "3.5"),
        (True, "True"),
    ])
    def test_it_renders_instead_of_raising(self, value, expected):
        from potato.flask_server import get_displayed_text

        assert get_displayed_text(value) == expected

    def test_a_string_is_unchanged_by_the_new_branches(self):
        from potato.flask_server import get_displayed_text

        assert get_displayed_text("a normal item") == "a normal item"

    def test_a_list_still_takes_the_list_branch(self):
        from potato.flask_server import get_displayed_text

        rendered = get_displayed_text(["alpha", "bravo"])
        assert "alpha" in rendered and "bravo" in rendered

    def test_a_dict_still_takes_the_dict_branch(self):
        from potato.flask_server import get_displayed_text

        assert '"a": 1' in get_displayed_text({"a": 1})


class TestTheOffendingRowsAreNamed:
    """A boot that renders empty text is better than a traceback, and worse
    than a traceback if nobody is told which rows did it."""

    def _warn(self, unusable=(), whitespace=()):
        from potato.flask_server import _warn_about_unusable_text

        return lambda caplog: _warn_about_unusable_text(
            "text", list(unusable), list(whitespace))

    def test_a_null_text_names_the_item(self, caplog):
        from potato.flask_server import _warn_about_unusable_text

        with caplog.at_level(logging.WARNING):
            _warn_about_unusable_text("text", [("nulltxt", "NoneType")], [])
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "nulltxt" in message, (
            "the traceback named no id, no field and no file, which is what "
            "made a 20k-row export a bisection")
        assert "text" in message

    def test_many_rows_are_summarized_rather_than_dumped(self, caplog):
        from potato.flask_server import _warn_about_unusable_text

        rows = [(f"i{n}", "NoneType") for n in range(40)]
        with caplog.at_level(logging.WARNING):
            _warn_about_unusable_text("text", rows, [])
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "and 35 more" in message
        assert "i39" not in message

    def test_whitespace_warning_names_the_fix(self, caplog):
        from potato.flask_server import _warn_about_unusable_text

        with caplog.at_level(logging.WARNING):
            _warn_about_unusable_text("text", [], ["snippet1"])
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "snippet1" in message
        assert "instance_display" in message, (
            "the warning has to name the path that keeps the whitespace, or "
            "it reports a transform the author cannot do anything about")

    def test_nothing_is_said_when_nothing_is_wrong(self, caplog):
        from potato.flask_server import _warn_about_unusable_text

        with caplog.at_level(logging.WARNING):
            _warn_about_unusable_text("text", [], [])
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


class TestTheWhitespaceConditionIsTheRightOne:
    """Pinned because the warning is only honest while both halves hold: the
    default path collapses, and the declared path does not."""

    def test_the_default_path_still_collapses(self):
        from potato.flask_server import get_displayed_text

        code = "def f(x):\n    if x > 0:\n        return x"
        assert "    " not in get_displayed_text(code)

    def test_the_declared_path_preserves_it(self):
        from potato.server_utils.displays.registry import display_registry

        rendered = display_registry.render(
            "text", {"type": "text", "key": "text"},
            "def f(x):\n    if x > 0:\n        return x")
        assert "    if x" in rendered or "&nbsp;" in rendered, (
            "instance_display is what the warning tells authors to use; if it "
            "stops preserving whitespace the advice is wrong")


class TestCodeDisplayCarriesItsLanguage:

    def _language(self, field_config, data):
        import re

        from potato.server_utils.displays.code_display import CodeDisplay

        html = CodeDisplay().render(field_config, data)
        found = re.findall(r'data-language="([^"]*)"', html)
        return found[0] if found else None

    def test_a_per_item_language_reaches_the_wrapper(self):
        assert self._language(
            {"key": "code"},
            {"text": "print(1)", "metadata": {"language": "python"}}
        ) == "python", (
            "render resolved metadata.language and _wrap_content recomputed "
            "it from options alone, so the attribute a highlighter reads said "
            "text")

    def test_a_configured_language_still_wins_when_the_item_has_none(self):
        assert self._language(
            {"key": "code", "display_options": {"language": "rust"}},
            "fn main() {}") == "rust"

    def test_neither_falls_back_to_text(self):
        assert self._language({"key": "code"}, "plain") == "text"

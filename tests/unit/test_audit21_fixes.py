"""Regressions for the findings in POTATO-BUGS-audit-21.

1  The SIGTERM handler was installed correctly but from the wrong place: the
   manager that installs it was first constructed on a Flask request thread,
   where signal.signal() cannot run, so the handler was never installed on any
   live server.
2  An inline `color` on a span label was parsed and then masked by a palette
   colour the generator invented, and `validate --strict` said nothing about a
   colour it could not read.
3  An absolute filesystem path used as an image reference went to the browser
   verbatim, 404ed, and logged nothing -- while its sibling, a traversal
   escape, was refused *and* logged.
"""

import logging
import os
import signal
import threading

import pytest


# ---------------------------------------------------------------------------
# 1. The handler has to be installed from the main thread, at boot.
# ---------------------------------------------------------------------------
class TestTerminationHandlerInstallSite:
    """The code was right; nothing on the main thread ever ran it.

    `signal.signal()` raises ValueError off the main thread, and the manager
    was first constructed by whichever request created the first session -- a
    Flask worker. So the guard returned early, silently, on every real server.
    """

    def test_installing_off_the_main_thread_does_not_install(self):
        from potato.coding_agent_runner_manager import CodingAgentRunnerManager

        before = signal.getsignal(signal.SIGTERM)
        result = {}

        def worker():
            manager = CodingAgentRunnerManager.__new__(CodingAgentRunnerManager)
            manager._install_termination_handler()
            result["after"] = signal.getsignal(signal.SIGTERM)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        assert result["after"] is before, (
            "installing from a worker thread must leave SIGTERM alone")
        assert signal.getsignal(signal.SIGTERM) is before

    def test_the_early_return_is_not_silent(self, caplog):
        """A guard that returns without a word is how this shipped broken."""
        from potato.coding_agent_runner_manager import CodingAgentRunnerManager

        logged = {}

        def worker():
            with caplog.at_level(logging.WARNING):
                manager = CodingAgentRunnerManager.__new__(
                    CodingAgentRunnerManager)
                manager._install_termination_handler()
            logged["text"] = caplog.text

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        assert "SIGTERM" in logged["text"]

    def test_booting_a_live_coding_agent_study_installs_the_handler(self):
        """The install site, not the installer.

        Drives the boot function a real server runs and reads the process's
        actual SIGTERM disposition. Asserting that flask_server *contains* the
        construction call would pass on a future edit that moves it back onto
        a request thread, which is the bug this is here to catch.
        """
        import flask
        from potato import flask_server

        prior = signal.getsignal(signal.SIGTERM)
        try:
            app = flask.Flask(__name__)
            flask_server._register_web_agent_blueprints_if_needed(app, {
                "task_dir": ".",
                "sandbox_mode": "none",
                "annotation_schemes": [],
                "site_dir": ".",
                "instance_display": {"fields": [
                    {"key": "task", "type": "live_coding_agent"}]},
            })
            installed = signal.getsignal(signal.SIGTERM)
        finally:
            signal.signal(signal.SIGTERM, prior)

        assert installed is not prior, (
            "booting a live_coding_agent study must install the SIGTERM "
            "handler; without it every stop except Ctrl-C leaks containers")
        assert callable(installed)


# ---------------------------------------------------------------------------
# 2. Inline span colours.
# ---------------------------------------------------------------------------
class TestRgbTripleParsing:
    """Span colours are stored as `(r, g, b)` because the chip builds its CSS
    as `"rgb" + color`. A hex value stored raw renders as `rgb#ffcc00`."""

    @pytest.mark.parametrize("value,expected", [
        ("#ffcc00", "(255, 204, 0)"),
        ("#FFCC00", "(255, 204, 0)"),
        ("#fc0", "(255, 204, 0)"),
        ("rgb(1, 2, 3)", "(1, 2, 3)"),
        ("rgb(1,2,3)", "(1, 2, 3)"),
        ("rgba(1, 2, 3, 0.5)", "(1, 2, 3)"),
        ("(34, 197, 94)", "(34, 197, 94)"),
    ])
    def test_readable_colours_become_triples(self, value, expected):
        from potato.server_utils.schemas.span import parse_rgb_triple
        assert parse_rgb_triple(value) == expected

    @pytest.mark.parametrize("value", [
        "chartreuse", "nonsense", "#gggggg", "(1, 2)", "(1, 2, 3, 4)",
        "", None, "rgb(", "#12345",
    ])
    def test_unreadable_colours_yield_nothing(self, value):
        from potato.server_utils.schemas.span import parse_rgb_triple
        assert parse_rgb_triple(value) == ""

    def test_the_pure_parser_does_not_log(self, caplog):
        """Config validation calls it and reports on its own logger."""
        from potato.server_utils.schemas.span import parse_rgb_triple
        with caplog.at_level(logging.WARNING):
            parse_rgb_triple("chartreuse")
        assert caplog.text == ""

    def test_the_wrapper_warns_on_something_unreadable(self, caplog):
        from potato.server_utils.schemas.span import to_rgb_triple
        with caplog.at_level(logging.WARNING):
            assert to_rgb_triple("chartreuse", "entities:Bad") == ""
        assert "chartreuse" in caplog.text
        assert "entities:Bad" in caplog.text

    def test_the_wrapper_is_quiet_about_no_colour_at_all(self, caplog):
        from potato.server_utils.schemas.span import to_rgb_triple
        with caplog.at_level(logging.WARNING):
            assert to_rgb_triple("", "entities:X") == ""
            assert to_rgb_triple(None, "entities:X") == ""
        assert caplog.text == ""


class TestInlineSpanColourSurvives:
    """The generator wrote a palette colour into `ui.spans.span_colors` for
    every label, and /api/colors reads that block *before* inline colours and
    only fills a label it has not already seen. So the author's colour lost to
    a palette entry the generator had just invented."""

    @pytest.fixture
    def generated(self):
        from potato.server_utils.schemas import span as spanmod

        original = spanmod.config
        cfg = {"annotation_schemes": []}
        spanmod.config = cfg
        spanmod.reset_span_counter()
        try:
            html, _ = spanmod.generate_span_layout({
                "annotation_type": "span",
                "name": "entities",
                "description": "Entities",
                "labels": [
                    {"name": "Defect", "color": "#ffcc00"},
                    {"name": "Injury", "color": "rgb(0, 128, 255)"},
                    "Plain",
                    {"name": "Bogus", "color": "chartreuse"},
                ],
            })
            yield cfg, html, spanmod
        finally:
            spanmod.config = original

    def test_an_inline_hex_colour_is_what_gets_registered(self, generated):
        cfg, _, spanmod = generated
        assert spanmod.get_span_color("entities", "Defect") == "(255, 204, 0)"

    def test_an_inline_rgb_colour_is_what_gets_registered(self, generated):
        cfg, _, spanmod = generated
        assert spanmod.get_span_color("entities", "Injury") == "(0, 128, 255)"

    def test_a_label_without_a_colour_still_gets_the_palette(self, generated):
        cfg, _, spanmod = generated
        colour = spanmod.get_span_color("entities", "Plain")
        assert colour and colour.startswith("(")
        assert colour not in {"(255, 204, 0)", "(0, 128, 255)"}

    def test_an_unreadable_colour_falls_back_rather_than_breaking_css(
            self, generated):
        cfg, html, spanmod = generated
        colour = spanmod.get_span_color("entities", "Bogus")
        assert colour.startswith("(") and colour.endswith(")")
        assert "chartreuse" not in html
        assert "rgbchartreuse" not in html

    def test_every_chip_renders_valid_css(self, generated):
        """The chip builds `"rgb" + color`, so a stored value that is not a
        triple produces CSS the browser drops entirely."""
        import re
        _, html, _ = generated
        chips = re.findall(r"background-color:\s*([^;\"']+)", html)
        assert chips
        for chip in chips:
            assert re.fullmatch(
                r"rgba?\(\s*\d+,\s*\d+,\s*\d+\s*(,\s*[\d.]+\s*)?\)",
                chip.strip()), f"chip CSS is not a colour: {chip!r}"


class TestUnreadableColourIsValidated:
    """`validate --strict` reported "OK -- no issues found" for a config whose
    colour Potato cannot read. The colour is not fatal -- the label falls back
    to the palette -- but it is silent, and the author asked for a colour."""

    def _validate(self, scheme):
        from potato.server_utils.config_module import (
            validate_label_list_elements)
        validate_label_list_elements(scheme, "annotation_schemes[0]")

    def test_an_unreadable_colour_warns(self, caplog):
        with caplog.at_level(
                logging.WARNING,
                logger="potato.server_utils.config_module"):
            self._validate({"labels": [{"name": "Bad", "color": "chartreuse"}]})
        assert "chartreuse" in caplog.text
        assert "Bad" in caplog.text

    @pytest.mark.parametrize("colour", [
        "#ffcc00", "#fc0", "rgb(0, 128, 255)", "(34, 197, 94)"])
    def test_a_readable_colour_is_silent(self, caplog, colour):
        with caplog.at_level(
                logging.WARNING,
                logger="potato.server_utils.config_module"):
            self._validate({"labels": [{"name": "Good", "color": colour}]})
        assert caplog.text == ""

    def test_no_colour_at_all_is_silent(self, caplog):
        with caplog.at_level(
                logging.WARNING,
                logger="potato.server_utils.config_module"):
            self._validate({"labels": ["Plain", {"name": "Named"}]})
        assert caplog.text == ""

    def test_options_lists_are_checked_too(self, caplog):
        with caplog.at_level(
                logging.WARNING,
                logger="potato.server_utils.config_module"):
            self._validate({"options": [{"name": "Bad", "color": "puce"}]})
        assert "puce" in caplog.text

    def test_strict_validation_refuses_the_config(self, tmp_path):
        """End to end: the CLI used to exit 0 on this."""
        from potato.validate_cli import validate_config_file

        (tmp_path / "items.json").write_text('[{"id":"1","text":"hi"}]')
        config = tmp_path / "colors.yaml"
        config.write_text(
            "port: 8000\n"
            "annotation_task_name: colours\n"
            "data_files: [items.json]\n"
            "item_properties: {id_key: id, text_key: text}\n"
            "user_config: {allow_all_users: true}\n"
            "task_dir: .\n"
            "output_annotation_dir: out\n"
            "annotation_schemes:\n"
            "  - annotation_type: span\n"
            "    name: entities\n"
            "    description: Entities\n"
            "    labels:\n"
            '      - {name: Good, color: "#ffcc00"}\n'
            '      - {name: Bad, color: "chartreuse"}\n')

        report = validate_config_file(str(config))
        assert not report.errors, report.errors
        assert any("chartreuse" in w for w in report.other_warnings), (
            f"expected a colour warning, got {report.other_warnings}")


# ---------------------------------------------------------------------------
# 3. Media references that silently 404.
# ---------------------------------------------------------------------------
class TestSilentlyBrokenMediaReferences:
    """`../outside/far.png` was refused and logged. `/private/tmp/far.png` was
    passed to the browser verbatim and logged nothing. Both give the annotator
    the same broken image; only one left the author something to search for."""

    @pytest.fixture
    def project(self, tmp_path):
        from potato.media import paths as media_paths

        (tmp_path / "media").mkdir()
        (tmp_path / "outside").mkdir()
        (tmp_path / "elsewhere").mkdir()
        (tmp_path / "media" / "in.png").write_bytes(b"x")
        (tmp_path / "outside" / "far.png").write_bytes(b"x")
        (tmp_path / "elsewhere" / "other.png").write_bytes(b"x")

        media_paths._warned_refs.clear()
        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            yield tmp_path, {"task_dir": ".", "media_directory": "media"}
        finally:
            os.chdir(cwd)
            media_paths._warned_refs.clear()

    def test_an_absolute_filesystem_path_now_says_so(self, project, caplog):
        from potato.media.paths import media_href
        tmp_path, cfg = project
        target = str(tmp_path / "outside" / "far.png")

        with caplog.at_level(logging.WARNING, logger="potato.media.paths"):
            assert media_href(cfg, target, context="image") == target
        assert target in caplog.text
        assert "media_directory" in caplog.text

    def test_a_relative_path_outside_media_says_so(self, project, caplog):
        from potato.media.paths import media_href
        _, cfg = project

        with caplog.at_level(logging.WARNING, logger="potato.media.paths"):
            media_href(cfg, "elsewhere/other.png", context="image")
        assert "elsewhere/other.png" in caplog.text

    def test_a_file_under_media_resolves_and_is_silent(self, project, caplog):
        from potato.media.paths import media_href
        _, cfg = project

        with caplog.at_level(logging.WARNING, logger="potato.media.paths"):
            assert media_href(cfg, "in.png", context="image") == "/media/in.png"
        assert caplog.text == ""

    @pytest.mark.parametrize("ref", [
        "/media/in.png", "/static/logo.png",
        "https://example.test/a.png", "http://example.test/a.png",
        "data:image/png;base64,AAAA", "//cdn.example.test/a.png",
    ])
    def test_routes_and_urls_stay_silent(self, project, caplog, ref):
        from potato.media.paths import media_href
        _, cfg = project

        with caplog.at_level(logging.WARNING, logger="potato.media.paths"):
            assert media_href(cfg, ref, context="image") == ref
        assert caplog.text == ""

    def test_a_path_that_resolves_nowhere_stays_silent(self, project, caplog):
        """It may be served by a route this code cannot see. Warning about
        every one of those would make the log useless."""
        from potato.media.paths import media_href
        _, cfg = project

        with caplog.at_level(logging.WARNING, logger="potato.media.paths"):
            media_href(cfg, "/somewhere/absent.png", context="image")
            media_href(cfg, "not/here.png", context="image")
        assert caplog.text == ""

    def test_a_dataset_full_of_the_same_bad_path_logs_once(
            self, project, caplog):
        from potato.media.paths import media_href
        tmp_path, cfg = project
        target = str(tmp_path / "outside" / "far.png")

        with caplog.at_level(logging.WARNING, logger="potato.media.paths"):
            for _ in range(50):
                media_href(cfg, target, context="image")
        assert caplog.text.count("absolute filesystem path") == 1

    def test_the_traversal_case_still_refuses_and_logs(self, project, caplog):
        """The behaviour the auditor called exactly right. Unchanged."""
        from potato.media.paths import media_href
        _, cfg = project

        with caplog.at_level(logging.WARNING, logger="potato.media.paths"):
            media_href(cfg, "../outside/far.png", context="image")
        assert "traversal blocked" in caplog.text

    def test_a_refused_reference_is_not_reported_twice(self, project, caplog):
        """The traversal guard has already said why. One bad reference, one
        line -- otherwise the escape that also happens to exist on disk gets
        two warnings that say different things about the same mistake."""
        from potato.media.paths import media_href
        tmp_path, cfg = project

        # `../outside/far.png` escapes media_directory *and* names a real file
        # relative to the process cwd -- so both warnings could fire on it.
        os.chdir(tmp_path / "media")
        with caplog.at_level(logging.WARNING, logger="potato.media.paths"):
            media_href(cfg, "../outside/far.png", context="image")
        assert os.path.isfile("../outside/far.png"), "probe setup is wrong"
        assert "traversal blocked" in caplog.text
        assert "not under media_directory" not in caplog.text, caplog.text


# ---------------------------------------------------------------------------
# Found while fixing 2: the keyword path had its own copy of the parser.
# ---------------------------------------------------------------------------
class TestKeywordColoursUseTheSameParser:
    """`_as_rgb_triple` read hex and passed everything else through unchanged,
    so a keyword colour written `rgb(0, 128, 255)` was stored raw and the chip
    rendered `rgbrgb(0, 128, 255)` -- the exact failure its hex branch existed
    to prevent. It delegates to the span parser now."""

    @pytest.mark.parametrize("value,expected", [
        ("#ffcc00", "(255, 204, 0)"),
        ("#fc0", "(255, 204, 0)"),
        ("(34, 197, 94)", "(34, 197, 94)"),
        ("rgb(0, 128, 255)", "(0, 128, 255)"),
        ("rgba(1, 2, 3, 0.5)", "(1, 2, 3)"),
    ])
    def test_every_accepted_form_becomes_a_triple(self, value, expected):
        from potato import flask_server as fs
        assert fs._as_rgb_triple(value, "w") == expected

    @pytest.mark.parametrize("value", ["chartreuse", "nonsense", "", None])
    def test_an_unreadable_colour_yields_nothing_not_broken_css(self, value):
        from potato import flask_server as fs
        assert fs._as_rgb_triple(value, "w") == ""

    def test_the_two_parsers_agree(self):
        """Two implementations of one normalisation is how this drifted."""
        from potato import flask_server as fs
        from potato.server_utils.schemas.span import parse_rgb_triple
        for value in ["#ffcc00", "#fc0", "(1, 2, 3)", "rgb(4, 5, 6)",
                      "rgba(7, 8, 9, 0.5)", "chartreuse", "", "#gggggg"]:
            assert fs._as_rgb_triple(value, "w") == parse_rgb_triple(value), value

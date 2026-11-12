"""A misspelled display option has to fail, not render at the default.

`get_display_options()` merges the author's options over the renderer's and
passes the result through, so a key the renderer does not read is inert: no
error, nothing in the log, and a page that renders at the default. An author who
wrote `speeker_key: agent` got every turn as an anonymous grey avatar and
`validate --strict` saying "OK — no issues found".

That was compounded by the registry under-reporting its own options (see
`test_display_registry_field_coverage.py`): an author could not find out what an
option was called, and could not find out that they had got it wrong.

The check found four dead keys in the repo's own shipped examples, so this
tests the real ones as well as the audit's specimen.
"""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    _validate_display_options,
    validate_instance_display_config,
)


PATH = "instance_display.fields[0]"


class TestUnknownOptionsAreRejected:
    def test_the_audits_typo(self):
        """`speeker_key` on a multi_agent_discussion, from the fifth audit."""
        with pytest.raises(ConfigValidationError) as excinfo:
            _validate_display_options("multi_agent_discussion", {"speeker_key": "agent"}, PATH)

        message = str(excinfo.value)
        assert "speeker_key" in message
        assert "ignored silently" in message
        assert "Did you mean 'speaker_key'?" in message

    def test_the_message_lists_what_is_accepted(self):
        with pytest.raises(ConfigValidationError) as excinfo:
            _validate_display_options("video", {"psoter": "thumb.png"}, PATH)

        assert "Accepted options:" in str(excinfo.value)

    def test_the_key_ten_shipped_examples_had_wrong(self):
        """`agent_trace` reads `show_step_numbers`. Ten configs set the other one.

        The other two dead keys the scan turned up -- `text.collapsed_by_default`
        and `dialogue.max_height` -- were real gaps rather than typos: the
        renderers did not implement what the examples asked for. Both are
        implemented now, and covered in TestValidOptionsStillPass.
        """
        with pytest.raises(ConfigValidationError) as excinfo:
            _validate_display_options("agent_trace", {"show_turn_numbers": True}, PATH)

        assert "Did you mean 'show_step_numbers'?" in str(excinfo.value)


class TestValidOptionsStillPass:
    @pytest.mark.parametrize("display,options", [
        ("multi_agent_discussion", {"speaker_key": "agent", "text_key": "text"}),
        ("pdf", {"ocr": True, "ocr_lang": "eng"}),
        ("agent_trace", {"show_step_numbers": False}),
        ("text", {"collapsible": True, "collapsed_by_default": True}),
        ("dialogue", {"max_height": 600, "show_turn_numbers": True}),
        ("video", {"poster": "thumb.png", "controls": True}),
    ])
    def test_declared_options_are_accepted(self, display, options):
        _validate_display_options(display, options, PATH)

    def test_an_empty_options_block_is_fine(self):
        _validate_display_options("text", {}, PATH)

    def test_a_display_declaring_no_options_is_not_policed(self):
        """A plugin that never set optional_fields cannot be distinguished from
        one that takes none, so it is skipped rather than guessed at."""
        from potato.server_utils.displays.registry import DisplayDefinition, display_registry

        display_registry.list_displays()
        definition = DisplayDefinition(name="_probe", renderer=lambda *_: "", optional_fields={})
        display_registry._displays["_probe"] = definition
        try:
            _validate_display_options("_probe", {"anything_at_all": 1}, PATH)
        finally:
            del display_registry._displays["_probe"]


class TestItFiresThroughTheRealEntryPoint:
    """The unit above calls the helper; this proves the config path reaches it."""

    def _config(self, options):
        return {
            "instance_display": {
                "fields": [{"key": "steps", "type": "multi_agent_discussion",
                            "display_options": options}]
            }
        }

    def test_a_typo_fails_full_instance_display_validation(self):
        with pytest.raises(ConfigValidationError, match="speeker_key"):
            validate_instance_display_config(self._config({"speeker_key": "agent"}))

    def test_the_corrected_key_passes(self):
        validate_instance_display_config(self._config({"speaker_key": "agent"}))


class TestOptionValuesMatchTheirDefaults:
    """
    A declared option with a value of the wrong type is warned about at load.

    Renderers read options straight from the merged dict, so
    `screenshot_max_height: tall` on a web_agent_trace only failed at render
    time, and the page fell back to plain text. Reported by the potato-skill
    agent. Warnings, not errors: `validate --strict` fails on them, but a
    renderer that accepts more than its default suggests still boots.
    """

    LOGGER = "potato.server_utils.config_module"

    def warnings(self, caplog, field_type, options):
        import logging
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=self.LOGGER):
            _validate_display_options(field_type, options, PATH)
        return [r.getMessage() for r in caplog.records if "expects" in r.getMessage()]

    def test_a_word_where_a_number_belongs(self, caplog):
        [msg] = self.warnings(caplog, "web_agent_trace", {"screenshot_max_height": "tall"})
        assert "screenshot_max_height" in msg and "a number" in msg

    def test_a_string_where_a_boolean_belongs(self, caplog):
        [msg] = self.warnings(caplog, "agent_trace", {"show_step_numbers": "yes"})
        assert "true or false" in msg

    def test_a_boolean_is_not_a_number(self, caplog):
        assert self.warnings(caplog, "web_agent_trace", {"screenshot_max_height": True})

    def test_right_types_pass(self, caplog):
        assert self.warnings(caplog, "web_agent_trace", {
            "screenshot_max_height": 400, "playback_step_delay": 1}) == []
        assert self.warnings(caplog, "agent_trace", {"show_step_numbers": False}) == []

    def test_options_with_a_string_or_none_default_are_not_typed(self, caplog):
        # code.max_width defaults to None and accepts "80%" as well as 800.
        assert self.warnings(caplog, "code", {"max_width": "80%"}) == []

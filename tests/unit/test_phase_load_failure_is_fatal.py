"""A phase that cannot be built must abort the boot, and `validate` must say so.

Both halves of one bug. The eight demographics instruments declared an
annotation type the registry does not have, so `load_phase_data()` raised while
building the poststudy phase -- and swallowed it. The study launched, the
server answered, `validate --strict` printed "OK", and annotators completed
the whole task with the post-study survey silently missing. The only trace was
a single ERROR line in the startup log.
"""

import pytest
from unittest.mock import patch

from potato.server_utils.config_module import (
    ConfigValidationError,
    _validate_phase_instruments,
)


BAD_QUESTION = [
    {"name": "q_age", "description": "Age?", "annotation_type": "textbox"}
]


class TestValidateResolvesInstrumentQuestions:
    """`validate` must resolve an instrument's questions, not just its name."""

    def test_unregistered_type_in_instruments_list_is_an_error(self):
        with patch(
            "potato.survey_instruments.get_instrument_questions",
            return_value=BAD_QUESTION,
        ):
            with pytest.raises(ConfigValidationError) as exc:
                _validate_phase_instruments(
                    {"instruments": ["anes-demographics"]}, "poststudy"
                )
        message = str(exc.value)
        assert "textbox" in message
        assert "anes-demographics" in message
        assert "q_age" in message

    def test_unregistered_type_in_single_instrument_is_an_error(self):
        """The `instrument:` (singular) spelling gets the same check."""
        with patch(
            "potato.survey_instruments.get_instrument_questions",
            return_value=BAD_QUESTION,
        ):
            with pytest.raises(ConfigValidationError):
                _validate_phase_instruments(
                    {"instrument": "anes-demographics"}, "prestudy"
                )

    def test_bundled_instruments_all_pass(self):
        """Every shipped instrument must survive the validator it now faces."""
        from potato.survey_instruments import get_registry

        for inst_id in get_registry()["instruments"]:
            _validate_phase_instruments({"instruments": [inst_id]}, "poststudy")

    def test_unknown_instrument_name_still_reported(self):
        with pytest.raises(ConfigValidationError, match="Unknown instrument"):
            _validate_phase_instruments(
                {"instruments": ["no-such-instrument"]}, "poststudy"
            )

    def test_non_list_instruments_still_reported(self):
        with pytest.raises(ConfigValidationError, match="must be a list"):
            _validate_phase_instruments(
                {"instruments": "anes-demographics"}, "poststudy"
            )

    def test_non_string_instrument_still_reported(self):
        with pytest.raises(ConfigValidationError, match="must be a string"):
            _validate_phase_instruments({"instrument": ["a-list"]}, "poststudy")

    def test_phase_without_instruments_is_a_no_op(self):
        _validate_phase_instruments({"file": "poststudy.json"}, "poststudy")


class TestPhaseLoadFailureAborts:
    """A phase the author asked for and did not get must stop the boot."""

    def test_failing_phase_raises_rather_than_being_dropped(self):
        from potato.flask_server import load_phase_data

        config = {
            "phases": {
                "order": ["annotation", "poststudy"],
                # No `instrument`, `instruments`, or `file`: the loader has no
                # source of questions and raises while building the phase.
                "poststudy": {"type": "poststudy"},
            },
            "annotation_schemes": [],
        }

        with pytest.raises(ConfigValidationError) as exc:
            load_phase_data(config)
        assert "poststudy" in str(exc.value)

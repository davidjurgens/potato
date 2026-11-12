"""
The set of display types that accept `span_target: true` lives in one place.

There used to be two: `supports_span_target` on each display, and a hardcoded
list inside `validate_instance_display_config`. They disagreed in both
directions.

  * `eval_trace` and `coding_trace` declared span support and were *rejected*
    by validation, so a config the display could have served would not boot.
  * `pdf`, `spreadsheet` and `agent_trace` were accepted by validation while
    declaring `supports_span_target = False`.

The second group turned out not to be a mistake. That flag means "wraps its
content in the `.text-content` element span offsets are measured against", and
those three anchor spans their own way instead -- into the PDF.js text layer,
per cell, and per step id. Both facts are real; the names just made them look
like one fact.

So there are two questions now, and these tests keep them from collapsing back
into one:

  `get_span_target_types()`          -- who honours the standard contract
  `get_span_target_capable_types()`  -- who accepts the key at all

Validation asks the second. Anything reasoning about character offsets asks the
first.
"""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_instance_display_config,
)
from potato.server_utils.displays.registry import (
    CUSTOM_SPAN_TARGET_TYPES,
    display_registry,
)

STANDARD = set(display_registry.get_span_target_types())
CAPABLE = set(display_registry.get_span_target_capable_types())
ALL_TYPES = set(display_registry.get_supported_types())


def _validate(field_type: str) -> None:
    validate_instance_display_config({
        "instance_display": {
            "fields": [{"key": "field", "type": field_type, "span_target": True}]
        }
    })


class TestTheTwoSetsRelate:
    def test_capable_is_standard_plus_the_custom_ones(self):
        assert CAPABLE == STANDARD | set(CUSTOM_SPAN_TARGET_TYPES)

    def test_custom_types_are_real_display_types(self):
        unknown = set(CUSTOM_SPAN_TARGET_TYPES) - ALL_TYPES
        assert not unknown, f"CUSTOM_SPAN_TARGET_TYPES names non-existent types: {unknown}"

    def test_custom_types_do_not_claim_the_standard_contract(self):
        """A type in both sets means one of the two declarations is wrong.

        Either it grew a `.text-content` wrapper, in which case drop it from
        `CUSTOM_SPAN_TARGET_TYPES`, or the flag was set by mistake.
        """
        both = set(CUSTOM_SPAN_TARGET_TYPES) & STANDARD
        assert not both, (
            f"{both} declare supports_span_target=True *and* are listed as "
            f"anchoring spans themselves; only one can be true"
        )

    def test_standard_set_is_not_empty(self):
        assert "text" in STANDARD, "plain text must support the standard contract"


class TestValidationAgreesWithTheRegistry:
    @pytest.mark.parametrize("field_type", sorted(CAPABLE))
    def test_every_capable_type_is_accepted(self, field_type):
        _validate(field_type)

    @pytest.mark.parametrize("field_type", sorted(ALL_TYPES - CAPABLE))
    def test_every_other_type_is_refused(self, field_type):
        with pytest.raises(ConfigValidationError) as excinfo:
            _validate(field_type)
        assert "span_target" in str(excinfo.value)

    def test_the_refusal_lists_the_alternatives(self):
        """An agent that picked the wrong type needs the right ones back."""
        incapable = sorted(ALL_TYPES - CAPABLE)
        if not incapable:
            pytest.skip("every display type accepts span_target")
        with pytest.raises(ConfigValidationError) as excinfo:
            _validate(incapable[0])
        message = str(excinfo.value)
        for name in sorted(CAPABLE):
            assert name in message, f"{name} is accepted but missing from the error"


class TestTheShippedExamplesStillValidate:
    """The examples are the evidence that the capable set is not too narrow."""

    def test_examples_using_span_target_use_a_capable_type(self):
        import glob

        import yaml

        offenders = []
        for path in sorted(glob.glob("examples/*/*/config.yaml")):
            try:
                config = yaml.safe_load(open(path, encoding="utf-8")) or {}
            except Exception:
                continue
            for field in ((config.get("instance_display") or {}).get("fields") or []):
                if isinstance(field, dict) and field.get("span_target"):
                    if field.get("type") not in CAPABLE:
                        offenders.append(f"{path}: {field.get('type')}")
        assert not offenders, (
            "shipped examples set span_target on a type validation refuses:\n"
            + "\n".join(offenders)
        )

"""Audit 95, G1: grid_view beside another required scheme ended the study
with that scheme unanswered on every grid item. The validator refuses it."""

import pytest

from potato.server_utils.config_module import ConfigValidationError, validate_grid_view_config

GRID = {"enabled": True, "scheme": "kind"}
KIND = {"name": "kind", "annotation_type": "radio", "labels": ["A", "B"], "description": "d"}


def _cfg(*others):
    return {"grid_view": dict(GRID), "annotation_schemes": [KIND, *others]}


@pytest.mark.parametrize("why", [
    {"name": "why", "annotation_type": "text", "description": "d",
     "label_requirement": {"required": True}},
    {"name": "why", "annotation_type": "text", "description": "d", "required": True},
    {"name": "why", "annotation_type": "text", "description": "d", "label_requirement": True},
])
def test_required_second_scheme_refused(why):
    with pytest.raises(ConfigValidationError, match="never be asked"):
        validate_grid_view_config(_cfg(why))


def test_optional_and_display_schemes_allowed():
    validate_grid_view_config(_cfg(
        {"name": "why", "annotation_type": "text", "description": "d"},
        {"name": "intro", "annotation_type": "pure_display", "description": "d",
         "label_requirement": {"required": True}}))


def test_grid_scheme_itself_may_be_required():
    cfg = _cfg()
    cfg["annotation_schemes"][0] = dict(KIND, label_requirement={"required": True})
    validate_grid_view_config(cfg)

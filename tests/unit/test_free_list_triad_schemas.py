"""
free_list and triad_test: what the generators hand the page, the asset
gate that loads their scripts, and the config checks `potato validate` runs.
"""

import html
import json
import re

import pytest

from potato.server_utils.config_module import ConfigValidationError, validate_single_annotation_scheme
from potato.server_utils.schemas.registry import schema_registry


def _config(markup, attr):
    m = re.search(attr + r"='([^']*)'", markup)
    return json.loads(html.unescape(m.group(1)))


def test_free_list_markup_carries_its_options():
    markup, keys = schema_registry.generate({
        "annotation_type": "free_list", "name": "fruit", "description": "List fruit",
        "min_items": 3, "max_items": 10, "time_limit_s": 60, "label_requirement": {"required": True}})
    assert keys == []
    cfg = _config(markup, "data-free-list-config")
    assert (cfg["min_items"], cfg["max_items"], cfg["time_limit_s"]) == (3, 10, 60)
    assert cfg["allow_duplicates"] is False
    assert 'class="annotation-input free-list-input"' in markup
    assert 'validation="required"' in markup


def test_triad_markup_carries_the_domain():
    markup, _ = schema_registry.generate({
        "annotation_type": "triad_test", "name": "tri", "description": "Triads",
        "labels": ["apple", {"name": "pear"}, " lime "], "max_triads": 4})
    cfg = _config(markup, "data-triad-config")
    assert cfg["labels"] == ["apple", "pear", "lime"]
    assert cfg["max_triads"] == 4 and cfg["design"] == "auto"
    assert cfg["question"] == "Which is most different?"


def test_both_generators_carry_the_asset_marker():
    from potato.flask_server import FRONTEND_ASSET_MARKERS
    markers = FRONTEND_ASSET_MARKERS["cultural_domain"]
    for scheme in ({"annotation_type": "free_list", "name": "f", "description": "d"},
                   {"annotation_type": "triad_test", "name": "t", "description": "d", "items_field": "items"}):
        markup, _ = schema_registry.generate(scheme)
        assert any(m in markup for m in markers), scheme["annotation_type"]


@pytest.mark.parametrize("scheme, message", [
    ({"annotation_type": "free_list", "min_items": 0}, "min_items"),
    ({"annotation_type": "free_list", "min_items": 5, "max_items": 3}, "larger than max_items"),
    ({"annotation_type": "free_list", "time_limit_s": -1}, "time_limit_s"),
    ({"annotation_type": "free_list", "normalize": ["stem"]}, "normalize"),
    ({"annotation_type": "triad_test", "labels": ["a", "b"]}, "at least three"),
    ({"annotation_type": "triad_test", "labels": list("abcdefgh"), "design": "steiner"}, "1 or 3 mod 6"),
    ({"annotation_type": "triad_test", "labels": list("abc"), "items_field": "items"}, "not both"),
    ({"annotation_type": "triad_test", "items_field": "items", "design": "bibd"}, "design"),
    ({"annotation_type": "triad_test", "items_field": "items", "max_triads": 0}, "max_triads"),
])
def test_bad_configs_are_refused(scheme, message):
    scheme = {"name": "x", "description": "d", **scheme}
    with pytest.raises(ConfigValidationError, match=message):
        validate_single_annotation_scheme(scheme, "annotation_schemes[0]")


@pytest.mark.parametrize("scheme", [
    {"annotation_type": "free_list", "min_items": 3, "max_items": 3, "time_limit_s": 1.5,
     "normalize": ["lowercase"]},
    {"annotation_type": "free_list", "normalize": True},
    {"annotation_type": "triad_test", "labels": list("abcdefg"), "design": "steiner"},
    {"annotation_type": "triad_test", "items_field": "items", "design": "sample", "max_triads": 12},
])
def test_good_configs_pass(scheme):
    validate_single_annotation_scheme({"name": "x", "description": "d", **scheme}, "annotation_schemes[0]")

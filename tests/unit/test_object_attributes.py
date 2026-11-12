"""
Per-object attributes: config validation, and agreement over them.

The attribute values ride on each shape's `attributes` dict (preserved through
save by tests/jest/shape-attributes.test.js). Agreement is computed over the
objects two annotators drew in the same place.
"""

import math

import pytest

from potato.server_utils.iaa.attribute_agreement import attribute_agreement
from potato.server_utils.schemas.object_attributes import (
    AttributeConfigError,
    normalize_attributes,
)

LABELS = ["car", "person"]


def norm(raw):
    return normalize_attributes(raw, LABELS, "annotation_schemes[objs]")


def box(x, label="car", **attributes):
    """A client-shaped bbox; boxes at the same x are the same object."""
    obj = {"type": "bbox", "label": label,
           "coordinates": {"x": x, "y": 0.1, "width": 0.2, "height": 0.2}}
    if attributes:
        obj["attributes"] = attributes
    return obj


class TestConfig:
    def test_a_full_definition_normalizes(self):
        [occ, trunc, share] = norm([
            {"name": "occlusion", "type": "select", "options": ["none", "partial"],
             "required": True, "default": "none"},
            {"name": "truncated", "type": "bool", "labels": ["car"]},
            {"name": "share", "type": "number", "min": 0, "max": 1,
             "show_if": {"attribute": "truncated", "equals": True}},
        ])
        assert occ == {"name": "occlusion", "type": "select", "required": True,
                       "options": ["none", "partial"], "default": "none"}
        assert trunc["labels"] == ["car"]
        assert share["show_if"] == {"attribute": "truncated", "equals": True}
        assert share["min"] == 0 and share["max"] == 1

    def test_yaml_booleans_in_options_become_text(self):
        """`options: [yes, no]` is read by YAML as [True, False]."""
        [d] = norm([{"name": "parked", "type": "select", "options": [True, False]}])
        assert d["options"] == ["yes", "no"]

    @pytest.mark.parametrize("raw,fragment", [
        ([{"name": "a", "type": "select"}], "needs a non-empty options list"),
        ([{"name": "a", "type": "colour"}], "type must be one of"),
        ([{"name": "a", "type": "bool", "labels": ["truck"]}], "not among the scheme's labels"),
        ([{"name": "a", "type": "select", "options": ["x"], "default": "y"}], "not one of the options"),
        ([{"name": "a", "type": "text"}, {"name": "a", "type": "text"}], "defined twice"),
        ([{"name": "a", "type": "text", "option": ["x"]}], "unknown key"),
        ([{"name": "a", "type": "bool", "show_if": {"attribute": "b", "equals": 1}}],
         "must name another attribute"),
        ({"name": "a"}, "must be a list"),
    ])
    def test_mistakes_name_the_attribute_and_the_fix(self, raw, fragment):
        with pytest.raises(AttributeConfigError, match=fragment):
            norm(raw)

    def test_a_typo_in_a_definition_gets_a_suggestion(self):
        with pytest.raises(AttributeConfigError, match="Did you mean: 'option' -> 'options'"):
            norm([{"name": "a", "type": "select", "option": ["x"]}])

    def test_config_load_rejects_a_bad_block(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_single_annotation_scheme)
        scheme = {"annotation_type": "image_annotation", "name": "objs",
                  "description": "d", "tools": ["bbox"], "labels": LABELS,
                  "attributes": [{"name": "occ", "type": "select"}]}
        with pytest.raises(ConfigValidationError, match="options"):
            validate_single_annotation_scheme(scheme, "annotation_schemes[0]")

    def test_attributes_is_a_declared_image_key(self):
        from potato.server_utils.schemas.registry import schema_registry
        assert "attributes" in schema_registry.get_accepted_fields("image_annotation")


OCCLUSION = norm([{"name": "occlusion", "type": "select",
                   "options": ["none", "partial", "heavy"]}])


class TestAgreement:
    def test_nominal_alpha_matches_the_hand_computed_value(self):
        rows = {
            "i1": {"a": [box(0.1, occlusion="none")], "b": [box(0.1, occlusion="none")]},
            "i2": {"a": [box(0.1, occlusion="partial")], "b": [box(0.1, occlusion="heavy")]},
            "i3": {"a": [box(0.1, occlusion="heavy")], "b": [box(0.1, occlusion="heavy")]},
        }
        result = attribute_agreement(rows, OCCLUSION)["occlusion"]
        # n_none=2, n_partial=1, n_heavy=3, n=6. Do = 2/6; De = 22/30.
        assert result["alpha"] == pytest.approx(12 / 22, abs=1e-6)
        assert result["percent_agreement"] == pytest.approx(2 / 3)
        assert result["n_objects"] == 3 and result["n_annotators"] == 2
        assert result["level"] == "nominal"

    def test_only_matched_objects_count(self):
        """A box only one annotator drew has nobody to agree with."""
        rows = {
            "i1": {"a": [box(0.1, occlusion="none"), box(0.7, occlusion="heavy")],
                   "b": [box(0.1, occlusion="none")]},
            "i2": {"a": [box(0.1, occlusion="heavy")], "b": [box(0.1, occlusion="partial")]},
        }
        assert attribute_agreement(rows, OCCLUSION)["occlusion"]["n_objects"] == 2

    def test_blank_and_inapplicable_values_contribute_nothing(self):
        defs = norm([{"name": "parked", "type": "bool", "labels": ["car"]}])
        rows = {
            # A person: parked does not apply.
            "i1": {"a": [box(0.1, "person", parked=True)], "b": [box(0.1, "person", parked=False)]},
            # One annotator left it blank.
            "i2": {"a": [box(0.1, parked=True)], "b": [box(0.1)]},
        }
        result = attribute_agreement(rows, defs)["parked"]
        assert result["n_objects"] == 0
        assert math.isnan(result["alpha"]) and "no object was matched" in result["note"]

    def test_unanimity_is_named_not_reported_as_failure(self):
        rows = {f"i{k}": {"a": [box(0.1, occlusion="none")], "b": [box(0.1, occlusion="none")]}
                for k in range(3)}
        result = attribute_agreement(rows, OCCLUSION)["occlusion"]
        assert math.isnan(result["alpha"]) and "Perfect agreement" in result["note"]
        assert result["percent_agreement"] == 1.0

    def test_number_is_interval_and_multi_is_masi(self):
        defs = norm([{"name": "count", "type": "number"},
                     {"name": "tags", "type": "multi", "options": ["x", "y", "z"]}])
        rows = {
            "i1": {"a": [box(0.1, count=1, tags=["x"])], "b": [box(0.1, count=2, tags=["x"])]},
            "i2": {"a": [box(0.1, count=5, tags=["x", "y"])], "b": [box(0.1, count=5, tags=["y", "x"])]},
            "i3": {"a": [box(0.1, count=9, tags=["z"])], "b": [box(0.1, count=8, tags=["y"])]},
        }
        report = attribute_agreement(rows, defs)
        assert report["count"]["level"] == "interval"
        assert report["count"]["alpha"] > 0.9   # 1-unit gaps on a 1..9 spread
        assert report["tags"]["level"] == "masi"
        # Order does not matter within a set: i2 counts as agreement.
        assert report["tags"]["percent_agreement"] == pytest.approx(2 / 3)

    def test_text_is_not_scored(self):
        defs = norm([{"name": "comment", "type": "text"}])
        rows = {"i1": {"a": [box(0.1, comment="x")], "b": [box(0.1, comment="x")]}}
        assert attribute_agreement(rows, defs)["comment"]["note"] == "free-text attributes are not scored"


class TestReportWiring:
    def test_the_geometry_report_carries_attribute_agreement(self):
        from potato.server_utils.iaa.dispatcher import _aggregate_blobs
        scheme = {"annotation_type": "image_annotation", "name": "objs", "labels": LABELS,
                  "tools": ["bbox"], "attributes": [{"name": "occlusion", "type": "select",
                                                     "options": ["none", "partial", "heavy"]}]}
        rows = {
            "i1": {"a": [box(0.1, occlusion="none")], "b": [box(0.1, occlusion="none")]},
            "i2": {"a": [box(0.1, occlusion="partial")], "b": [box(0.1, occlusion="heavy")]},
            "i3": {"a": [box(0.1, occlusion="heavy")], "b": [box(0.1, occlusion="heavy")]},
        }
        result = _aggregate_blobs(rows, scheme)
        assert result["attributes"]["occlusion"]["alpha"] == pytest.approx(12 / 22, abs=1e-6)

    def test_the_iaa_page_shows_one_group_per_attribute(self):
        from potato.server_utils.iaa.presentation import flatten
        rows = flatten({"attributes": {"occlusion": {
            "alpha": 0.5, "percent_agreement": 0.75, "n_objects": 4, "n_annotators": 2,
            "level": "nominal"}}})
        by_name = {r["name"]: r for r in rows}
        assert by_name["attributes.occlusion.alpha"]["scale"] == "kappa"
        assert by_name["attributes.occlusion.alpha"]["context"] == "4 objects, 2 annotators"
        assert by_name["attributes.occlusion.percent_agreement"]["scale"] == "raw"

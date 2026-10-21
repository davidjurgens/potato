"""
Audit 92 (the 2.12.0 pre-release audit of df2ee1c5).

F1  ai_support.holdout.fraction out of [0, 1] was clamped without a word.
F2  KITTI 2D export wrote the attribute docs' own occlusion values as 0 or 3.
F3  The JSON Schema left blocks nested inside blocks as bare objects.
F4  SAML idp sub-keys were unchecked; single_logout "false" left SLO on.
"""

import os

import pytest

from potato.export import spatial_sequences as seq
from potato.export.base import ExportContext
from potato.export.kitti_exporter import KITTIExporter
from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_ai_support_config,
)
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory


# --- F1 -------------------------------------------------------------------

class TestHoldoutFraction:
    @pytest.mark.parametrize("fraction", [1.5, 20, -0.3, "a lot", "0.2", True, None])
    def test_a_fraction_outside_zero_to_one_is_refused(self, fraction):
        config = {"ai_support": {"enabled": False, "holdout": {"fraction": fraction}}}
        with pytest.raises(ConfigValidationError, match="holdout.fraction"):
            validate_ai_support_config(config)

    @pytest.mark.parametrize("fraction", [0, 0.2, 1, 1.0])
    def test_a_fraction_in_range_is_accepted(self, fraction):
        validate_ai_support_config(
            {"ai_support": {"enabled": False, "holdout": {"fraction": fraction}}})

    def test_checked_when_ai_support_is_off(self):
        # The comparison group also withholds pre-annotations and SAM, which
        # run without ai_support.enabled.
        with pytest.raises(ConfigValidationError):
            validate_ai_support_config({"ai_support": {"holdout": {"fraction": 20}}})

    def test_holdout_must_be_a_mapping(self):
        with pytest.raises(ConfigValidationError, match="holdout"):
            validate_ai_support_config({"ai_support": {"holdout": 0.2}})


# --- F2 -------------------------------------------------------------------

W, H = 640, 480


def _box(label="Car", **attributes):
    return {"type": "bbox", "label": label,
            "coordinates": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
            "attributes": attributes}


def _columns(obj):
    fields = KITTIExporter()._line(obj, W, H).split()
    return fields[1], fields[2]           # truncated, occluded


class TestKittiAttributes:
    @pytest.mark.parametrize("attributes, truncated, occluded", [
        # object_attributes.md's first example
        ({"occlusion": "heavy", "truncated": True}, "0.50", "2"),
        ({"occlusion": "partial", "truncated": False}, "0.00", "1"),
        ({"occlusion": "none"}, "0.00", "0"),
        # its per_keyframe example
        ({"occluded": "partial"}, "0.00", "1"),
        ({"occluded": "heavy"}, "0.00", "2"),
        # what the KITTI 2D importer writes
        ({"occluded": "partly_occluded", "truncated": 0.4}, "0.40", "1"),
        ({"occluded": "largely_occluded", "truncated": 1.0}, "1.00", "2"),
        ({"occluded": "fully_visible", "truncated": 0.0}, "0.00", "0"),
        ({"occluded": "unknown"}, "0.00", "3"),
        ({"occluded": 2}, "0.00", "2"),
        ({}, "0.00", "0"),
    ])
    def test_columns(self, attributes, truncated, occluded):
        assert _columns(_box(**attributes)) == (truncated, occluded)

    def test_dont_care_rows_keep_the_devkit_values(self):
        assert _columns(_box("DontCare", truncated=-1.0, occluded="-1")) == ("-1.00", "-1")

    def test_unreadable_values_are_reported(self):
        test_dir = create_test_directory("audit92_kitti")
        try:
            objects = [_box(occluded="mostly"), _box(occluded="mostly"),
                       _box(truncated="sideways"), _box(occluded="partial")]
            context = ExportContext(
                config={"annotation_task_name": "audit92"},
                schemas=[{"annotation_type": "image_annotation", "name": "objects",
                          "labels": [{"name": "Car"}]}],
                annotations=[{"instance_id": "img_1",
                              "image_annotations": {"objects": objects}}],
                items={"img_1": {"image_width": W, "image_height": H,
                                 "file_name": "img_1.jpg"}},
                output_dir=test_dir)
            result = KITTIExporter().export(context, test_dir)
            text = " ".join(result.warnings)
            assert "2 object(s) have an occlusion value" in text and "'mostly'" in text
            assert "1 box(es) have a truncation value" in text and "'sideways'" in text
            with open(os.path.join(test_dir, "label_2", "img_1.txt")) as handle:
                occluded = [line.split()[2] for line in handle.read().splitlines()]
            assert occluded == ["3", "3", "0", "1"]
        finally:
            cleanup_test_directory(test_dir)

    def test_the_3d_reader_is_the_same_reader(self):
        # kitti_3d and the tracking writer read occlusion through this too;
        # the KITTI 2D importer's names used to come out as 0 there.
        assert seq._occlusion({"occluded": "partly_occluded"}) == 1
        assert seq._occlusion({"occlusion": "heavy"}) == 2
        assert seq.occlusion_attribute({"occluded": "mostly"}) == (3, "mostly")
        assert seq.occlusion_attribute({"occluded": 7}) == (3, 7)


# --- F3 -------------------------------------------------------------------

class TestNestedBlocksInTheSchema:
    @pytest.fixture(scope="class")
    def schema(self):
        from potato.server_utils.config_schema import build_config_schema
        return build_config_schema()

    def test_holdout_declares_its_keys(self, schema):
        holdout = schema["properties"]["ai_support"]["properties"]["holdout"]
        assert holdout["properties"]["fraction"]["type"] == "number"
        assert "salt" in holdout["properties"]

    def test_writeback_declares_its_keys_two_levels_down(self, schema):
        writeback = schema["properties"]["trace_ingestion"]["properties"]["writeback"]
        assert {"trigger", "min_annotators", "score_prefix", "langfuse", "langsmith"} \
            <= set(writeback["properties"])
        assert {"host", "public_key_env", "secret_key_env", "score_configs"} \
            <= set(writeback["properties"]["langfuse"]["properties"])
        assert {"api_url", "api_key_env"} \
            <= set(writeback["properties"]["langsmith"]["properties"])

    def test_a_list_of_blocks_stays_a_list(self, schema):
        groups = schema["properties"]["layout"]["properties"]["groups"]
        assert groups["type"] == "array"
        assert "schemas" in groups["items"]["properties"]

    def test_valid_and_invalid_holdout_in_an_editor(self, schema):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(schema)
        base = {"annotation_task_name": "t", "task_dir": ".",
                "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                        "description": "d", "labels": ["a", "b"]}]}
        good = dict(base, ai_support={"holdout": {"fraction": 0.2}})
        bad = dict(base, ai_support={"holdout": {"fraction": "a lot"}})
        assert not [e for e in validator.iter_errors(good) if "holdout" in e.json_path]
        assert [e for e in validator.iter_errors(bad) if "holdout" in e.json_path]


# --- F4 -------------------------------------------------------------------

class TestSamlChecks:
    @pytest.fixture(autouse=True)
    def _needs_saml(self):
        pytest.importorskip("onelogin.saml2", reason="SAML needs python3-saml")

    @staticmethod
    def _auth(**saml):
        idp = {"entity_id": "https://idp.test", "sso_url": "https://idp.test/sso",
               "x509cert": "MIIB"}
        idp.update(saml.pop("idp_extra", {}))
        return {"method": "saml",
                "saml": dict({"idp": idp, "user_identity_attribute": "eppn"}, **saml)}

    def _validate(self, auth):
        from potato.server_utils.config_module import _validate_saml_config
        _validate_saml_config(auth)

    def test_a_misspelt_slo_url_is_refused(self):
        with pytest.raises(ConfigValidationError, match="slo_ur"):
            self._validate(self._auth(idp_extra={"slo_ur": "https://idp.test/slo"}))

    def test_slo_url_is_accepted(self):
        self._validate(self._auth(idp_extra={"slo_url": "https://idp.test/slo"}))

    @pytest.mark.parametrize("value", ["false", 0, "no", None])
    def test_single_logout_must_be_a_boolean(self, value):
        with pytest.raises(ConfigValidationError, match="single_logout"):
            self._validate(self._auth(single_logout=value))

    @pytest.mark.parametrize("value", [True, False])
    def test_single_logout_booleans_are_accepted(self, value):
        self._validate(self._auth(single_logout=value))


# --- sign-off nits ----------------------------------------------------------

class TestSignOffNits:
    @pytest.mark.parametrize("value", [1.7, -0.2])
    def test_a_truncation_outside_zero_to_one_is_reported(self, value):
        assert seq.truncation_attribute({"truncated": value}) == (None, None, value)
        assert _columns(_box(truncated=value))[0] == "0.00"

    def test_the_docs_example_share_is_written(self):
        # object_attributes.md: truncated (bool) plus a truncation share.
        assert _columns(_box(truncated=True, truncation=0.3))[0] == "0.30"
        assert _columns(_box(truncated=True, truncation=1))[0] == "1.00"

    def test_a_share_left_behind_by_unsetting_truncated_is_ignored(self):
        assert _columns(_box(truncated=False, truncation=0.3))[0] == "0.00"

    def test_a_lone_whole_number_is_still_a_code(self):
        assert seq.truncation_attribute({"truncated": 1}) == (1, None, None)

    def test_the_schema_bounds_the_holdout_fraction(self):
        from potato.server_utils.config_schema import build_config_schema
        fraction = (build_config_schema()["properties"]["ai_support"]["properties"]
                    ["holdout"]["properties"]["fraction"])
        assert (fraction["minimum"], fraction["maximum"]) == (0, 1)

"""viewer_selection and the viewer-display framework: the scheme's markup and
validation, the per-viewer selection shapes, config validation across the
scheme and its display, and page asset gating."""

import json
import os
import re
import shutil
from unittest.mock import patch

import pytest
import yaml

from potato.server_utils.config_module import (
    ConfigValidationError, _validate_viewer_displays, _validate_viewer_selection)
from potato.server_utils.displays.viewer_display import (
    display_required_bundles, validate_selection, viewer_display, viewer_fields)
from potato.server_utils.schemas.registry import schema_registry
from potato.server_utils.schemas.viewer_selection import (
    LABEL_COLOURS, generate_viewer_selection_layout, label_names, parse_stored, validate_scheme)
from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEME = {"annotation_type": "viewer_selection", "name": "site", "description": "Binding site",
          "viewer_field": "structure"}
PROTEIN_FIELD = {"key": "structure", "type": "protein_structure"}


# ---------------------------------------------------------------------------
# The scheme
# ---------------------------------------------------------------------------

class TestScheme:
    def test_markup(self):
        html, keys = generate_viewer_selection_layout(
            dict(SCHEME, labels=["binding site", {"name": "epitope", "color": "#123456"}],
                 min_selections=2, max_selections=5))
        assert keys == []
        assert 'data-annotation-type="viewer_selection"' in html
        assert 'name="site:::site"' in html and 'class="annotation-input viewer-selection-input"' in html
        cfg = json.loads(re.search(r"data-selection-config='([^']*)'", html).group(1)
                         .replace("&quot;", '"').replace("&#x27;", "'"))
        assert cfg == {"schema": "site", "viewerField": "structure",
                       "labels": [{"name": "binding site", "color": LABEL_COLOURS[0]},
                                  {"name": "epitope", "color": "#123456"}],
                       "minSelections": 2, "maxSelections": 5}
        # The first label is the active one, and it is the only tab stop.
        assert re.findall(r'role="radio" aria-checked="(\w+)" tabindex="(-?\d)"', html) == [
            ("true", "0"), ("false", "-1")]

    def test_registered(self):
        assert "viewer_selection" in schema_registry.get_supported_types()
        html, _ = schema_registry.generate(dict(SCHEME))
        assert "viewer-selection" in html

    def test_a_bad_scheme_renders_an_error_card_and_fails_validation(self):
        bad = dict(SCHEME, labels=[True, False])
        html, _ = generate_viewer_selection_layout(bad)
        assert "viewer-selection-input" not in html
        with pytest.raises(ConfigValidationError, match="quote them"):
            _validate_viewer_selection(bad, "annotation_schemes[0]")

    @pytest.mark.parametrize("change,fragment", [
        ({"viewer_field": ""}, "viewer_field must name"),
        ({"labels": []}, "non-empty list"),
        ({"labels": ["a", "a"]}, "repeats a"),
        ({"labels": [{"name": "a", "colour": "red"}]}, "unknown key"),
        ({"min_selections": 3, "max_selections": 2}, "below min_selections"),
        ({"max_selections": 0}, "refuse every selection"),
        ({"min_selections": -1}, "whole number"),
        ({"min_selections": True}, "whole number"),
    ])
    def test_scheme_errors(self, change, fragment):
        errors = validate_scheme(dict(SCHEME, **change), "s")
        assert any(fragment in e for e in errors), errors

    def test_helpers(self):
        assert label_names({"labels": ["a", {"name": "b"}]}) == ["a", "b"]
        assert parse_stored('{"items": []}') == {"items": []}
        assert parse_stored("not json") == {} and parse_stored("") == {} and parse_stored("[1]") == {}


# ---------------------------------------------------------------------------
# Selection shapes
# ---------------------------------------------------------------------------

class TestSelectionShapes:
    def test_protein(self):
        good = {"viewer": "protein_structure", "items": [
            {"chain": "A", "resi": 57, "resn": "HIS", "label": "binding site"},
            {"chain": "AAA", "resi": -3, "resn": "A1LXZ", "icode": "B"}]}
        assert validate_selection("protein_structure", good, labels=["binding site"]) == []
        assert validate_selection("protein_structure", json.dumps(good)) == []
        assert validate_selection("protein_structure", "") == []

    @pytest.mark.parametrize("items,fragment", [
        ([{"chain": "A", "resi": "57", "resn": "HIS"}], "resi must be an integer"),
        ([{"chain": "A", "resi": True, "resn": "HIS"}], "resi must be an integer"),
        ([{"chain": "A B", "resi": 1, "resn": "HIS"}], "chain must be"),
        ([{"chain": "A", "resi": 1, "resn": ""}], "resn must be"),
        ([{"chain": "A", "resi": 1, "resn": "HIS", "icode": "AB"}], "icode"),
        ([{"chain": "A", "resi": 1, "resn": "HIS", "atom": "CA"}], "unexpected key"),
        ([{"chain": "A", "resi": 1, "resn": "HIS", "label": "other"}], "not one of"),
        ([{"chain": "A", "resi": 1, "resn": "HIS"}, {"chain": "A", "resi": 1, "resn": "HIS"}],
         "repeats an earlier item"),
        (["A:1"], "must be an object"),
    ])
    def test_protein_rejects(self, items, fragment):
        errors = validate_selection("protein_structure", {"items": items}, labels=["site"])
        assert any(fragment in e for e in errors), errors

    def test_counts_and_envelope(self):
        one = {"items": [{"chain": "A", "resi": 1, "resn": "GLY"}]}
        assert any("at least 2" in e for e in validate_selection("protein_structure", one, min_selections=2))
        assert any("at most 0" in e for e in validate_selection("protein_structure", one, max_selections=0))
        assert any("not valid JSON" in e for e in validate_selection("protein_structure", "{oops"))
        assert any("genome_locus" in e for e in validate_selection(
            "protein_structure", dict(one, viewer="genome_locus")))
        assert any("unexpected key" in e for e in validate_selection(
            "protein_structure", dict(one, locus="chr1:1-2")))
        assert validate_selection("text", one) == ["'text' is not a viewer display type"]

    def test_genome(self):
        good = {"viewer": "genome_locus", "locus": "chr1:1450-1550", "items": [
            {"chr": "chr1", "start": 1500, "end": 1500, "kind": "variant", "name": "rs1",
             "ref": "A", "alt": "G", "track": "Calls"},
            {"chr": "chr1", "start": 901, "end": 2400, "kind": "feature", "name": "GENE_A"}]}
        assert validate_selection("genome_locus", good) == []
        bad = {"locus": "chr1:9-3", "items": [{"chr": "chr1", "start": 0, "end": 5},
                                              {"chr": "chr1", "start": 9, "end": 3, "kind": "gene"}]}
        errors = validate_selection("genome_locus", bad)
        assert any("start must be a 1-based" in e for e in errors)
        assert any("end precedes" in e for e in errors)
        assert any("kind must be" in e for e in errors)
        assert any(e.startswith("locus:") for e in errors)


# ---------------------------------------------------------------------------
# Config validation across scheme and display
# ---------------------------------------------------------------------------

class TestConfigValidation:
    def test_viewer_field_must_name_a_viewer_display(self):
        config = {"instance_display": {"fields": [{"key": "structure", "type": "text"}]},
                  "annotation_schemes": [SCHEME]}
        with pytest.raises(ConfigValidationError, match="does not name a viewer display"):
            _validate_viewer_displays(config)
        config["instance_display"]["fields"][0] = PROTEIN_FIELD
        _validate_viewer_displays(config)

    def test_a_scheme_with_no_instance_display_is_reported(self):
        with pytest.raises(ConfigValidationError, match="viewer fields: none"):
            _validate_viewer_displays({"annotation_schemes": [SCHEME]})

    def test_display_options_are_checked(self):
        for field, fragment in [
            (dict(PROTEIN_FIELD, engine="pymol"), "not an engine for protein_structure"),
            (dict(PROTEIN_FIELD, display_options={"color_by": "rainbow"}), "color_by"),
            (dict(PROTEIN_FIELD, plddt="yes"), "plddt must be true or false"),
            (dict(PROTEIN_FIELD, allow_remote="yes"), "allow_remote"),
            ({"key": "l", "type": "genome_locus"}, "give a reference"),
        ]:
            with pytest.raises(ConfigValidationError, match=fragment):
                _validate_viewer_displays({"instance_display": {"fields": [field]}})

    def test_missing_bundle_names_the_fetch_command(self, monkeypatch):
        empty = create_test_directory("viewer_empty_vendor")
        monkeypatch.setenv("POTATO_VENDOR_DIR", empty)
        config = {"instance_display": {"fields": [dict(PROTEIN_FIELD, engine="molstar")]}}
        assert display_required_bundles(config) == ["molstar"]
        with pytest.raises(ConfigValidationError, match=r"`potato vendor fetch molstar`"):
            _validate_viewer_displays(config)
        # The default engine is committed and needs nothing.
        _validate_viewer_displays({"instance_display": {"fields": [PROTEIN_FIELD]}})

    def test_requirements_module_sees_viewer_bundles(self):
        from potato.vendoring.requirements import required_bundles
        config = {"instance_display": {"fields": [dict(PROTEIN_FIELD, display_options={"engine": "molstar"}),
                                                  {"key": "n", "type": "text"}]}}
        assert required_bundles(config) == ["molstar"]

    @pytest.mark.parametrize("example", ["protein-binding-site", "variant-review"])
    def test_examples_validate(self, example):
        from potato.validate_cli import validate_config_file
        work = os.path.join(create_test_directory("viewer_example_validate"), example)
        shutil.copytree(os.path.join(REPO, "examples", "advanced", example), work,
                        ignore=shutil.ignore_patterns("annotation_output", "*.sqlite*"))
        report = validate_config_file(os.path.join(work, "config.yaml"))
        assert report.ok, report.errors
        assert not report.unknown_keys, report.unknown_keys

    def test_registry_lookups(self):
        assert viewer_display("protein_structure").name == "protein_structure"
        assert viewer_display("genome_locus").engines["igv"].webgl is None
        assert viewer_display("image") is None
        fields = viewer_fields({"instance_display": {"fields": [
            {"key": "a", "type": "image"}, PROTEIN_FIELD, "junk"]}})
        assert [(i, f["key"]) for i, f, _ in fields] == [(1, "structure")]


class TestAssetGating:
    def test_page_with_a_viewer_loads_the_framework_only(self, tmp_path):
        from potato.flask_server import FRONTEND_ASSET_MARKERS, _detect_frontend_assets_for_page
        page = tmp_path / "page.html"
        page.write_text("<html></html>")
        display = '<div class="potato-viewer" data-viewer-kind="protein_structure"></div>'
        detected = _detect_frontend_assets_for_page(str(page), display)
        assert detected["viewer_display"] is True
        assert _detect_frontend_assets_for_page(str(page), "<p>plain</p>")["viewer_display"] is False
        scheme_only = tmp_path / "scheme.html"
        scheme_only.write_text(generate_viewer_selection_layout(dict(SCHEME))[0])
        assert _detect_frontend_assets_for_page(str(scheme_only), "")["viewer_display"] is True
        assert "viewer_display" in FRONTEND_ASSET_MARKERS

    def test_template_gates_the_scripts_and_never_loads_a_library_directly(self):
        template = open(os.path.join(REPO, "potato", "templates", "base_template_v2.html")).read()
        block = template.split("{% if frontend_assets.viewer_display | default(false) %}")
        assert len(block) == 3          # stylesheet gate + script gate
        scripts = block[2].split("{% endif %}")[0]
        assert "viewers/viewer-framework.js" in scripts and "viewers/viewer-selection.js" in scripts
        # The libraries are fetched by the framework when a viewer mounts.
        srcs = re.findall(r"(?:src|href)=\"([^\"]+)\"", template)
        assert not [s for s in srcs if re.search(r"3dmol|igv|molstar", s, re.I)]

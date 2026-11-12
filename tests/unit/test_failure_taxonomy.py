"""Unit tests for the MAST failure-mode taxonomy and its schema wiring."""

import pytest

from potato.server_utils import failure_taxonomy as ft
from potato.server_utils.schemas.hierarchical_multiselect import (
    generate_hierarchical_multiselect_layout,
)


class TestMastTaxonomy:
    def test_mast_has_three_categories(self):
        preset = ft.get_preset("mast")
        assert len(preset) == 3

    def test_mast_has_fourteen_modes(self):
        # MAST = 5 + 6 + 3 = 14 failure modes (Cemri et al. 2025).
        assert ft.mode_count("mast") == 14

    def test_modes_have_code_name_description(self):
        for category, modes in ft.get_preset("mast").items():
            for entry in modes:
                code, name, desc = entry
                assert code and name and desc
                assert isinstance(desc, str) and len(desc) > 10

    def test_to_hierarchical_prefixes_codes(self):
        h = ft.to_hierarchical("mast")
        labels = [lbl for modes in h.values() for lbl in modes]
        assert "1.1 Disobey task specification" in labels
        assert "3.1 Premature termination" in labels
        assert len(labels) == 14

    def test_to_tooltips_covers_every_label(self):
        h = ft.to_hierarchical("mast")
        tips = ft.to_tooltips("mast")
        for modes in h.values():
            for lbl in modes:
                assert lbl in tips and tips[lbl]

    def test_case_insensitive_lookup(self):
        assert ft.get_preset("MAST") is ft.get_preset("mast")

    def test_unknown_preset_raises(self):
        with pytest.raises(KeyError):
            ft.get_preset("does-not-exist")

    def test_list_presets(self):
        assert "mast" in ft.list_presets()


class TestHierarchicalPresetWiring:
    def _scheme(self, **kw):
        base = {
            "annotation_type": "hierarchical_multiselect",
            "name": "failure_modes",
            "description": "Tag failure modes",
        }
        base.update(kw)
        return base

    def test_preset_populates_taxonomy(self):
        html, _ = generate_hierarchical_multiselect_layout(
            self._scheme(taxonomy_preset="mast"))
        assert "Disobey task specification" in html
        assert "Inter-Agent Misalignment" in html
        assert "Premature termination" in html

    def test_preset_attaches_tooltips(self):
        html, _ = generate_hierarchical_multiselect_layout(
            self._scheme(taxonomy_preset="mast"))
        # the ⓘ marker and a description fragment should be present
        assert "hier-info" in html
        assert "ignores or violates the constraints" in html

    def test_explicit_tooltip_overrides_preset(self):
        html, _ = generate_hierarchical_multiselect_layout(self._scheme(
            taxonomy_preset="mast",
            tooltips={"1.1 Disobey task specification": "CUSTOM OVERRIDE TIP"}))
        assert "CUSTOM OVERRIDE TIP" in html

    def test_explicit_taxonomy_still_works_without_preset(self):
        html, _ = generate_hierarchical_multiselect_layout(self._scheme(
            taxonomy={"A": ["x", "y"], "B": ["z"]}))
        assert "x" in html and "z" in html

    def test_missing_taxonomy_and_preset_is_surfaced(self):
        # safe_generate_layout catches the ValueError and renders an error
        # layout rather than raising; the message must mention the requirement.
        html, _ = generate_hierarchical_multiselect_layout(self._scheme())
        assert "taxonomy" in html.lower()

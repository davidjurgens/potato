"""
The format matrix must not be able to lie.

A migration table that drifts from the code is worse than no table: it tells
someone their dataset will import when it will not, and they find out after
committing to the move. So the doc is checked against the registries in both
directions — nothing listed that is not registered, and nothing registered that
is missing from the page.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from potato.export.registry import export_registry
from potato.importers.registry import import_registry

DOC = Path("docs/data-export/format_matrix.md")

#: Exporters that carry annotations generically rather than as CV geometry.
#: They are mentioned in prose on the page but do not need a matrix row.
NON_CV_EXPORTERS = {
    "agent_eval", "codebook", "coding_eval", "conll_2003", "conll_u",
    "convokit", "csv", "eaf", "huggingface", "jsonl", "keystrokes",
    "parquet", "quotation_report", "textgrid", "trajectory_correction", "tsv",
    # Behavioural streams about how an annotation was made, not the annotation
    # itself. It carries no geometry, so it has no row in the format matrix.
    "annotation_telemetry",
}


@pytest.fixture(scope="module")
def doc_text():
    assert DOC.exists(), f"{DOC} is missing"
    return DOC.read_text()


def backticked(text):
    """Every `code` token in the document."""
    return set(re.findall(r"`([a-z0-9_]+)`", text))


class TestImporters:
    def test_every_registered_importer_appears(self, doc_text):
        listed = backticked(doc_text)
        for fmt in import_registry.get_supported_formats():
            assert fmt in listed, (
                f"importer '{fmt}' is registered but missing from {DOC}")

    def test_no_importer_is_claimed_that_does_not_exist(self, doc_text):
        """The dangerous direction: promising a migration path we do not have."""
        import_section = doc_text.split("## Export")[0]
        registered = set(import_registry.get_supported_formats())
        for fmt in re.findall(r"^\| `([a-z0-9_]+)`", import_section, re.M):
            assert fmt in registered, (
                f"{DOC} lists importer '{fmt}', which is not registered")


class TestExporters:
    def test_every_cv_exporter_appears(self, doc_text):
        listed = backticked(doc_text)
        cv_exporters = (set(export_registry.get_supported_formats())
                        - NON_CV_EXPORTERS)
        for fmt in cv_exporters:
            assert fmt in listed, (
                f"CV exporter '{fmt}' is registered but missing from {DOC}")

    def test_no_exporter_is_claimed_that_does_not_exist(self, doc_text):
        export_section = doc_text.split("## Export")[1].split("## What survives")[0]
        registered = set(export_registry.get_supported_formats())
        for fmt in re.findall(r"^\| `([a-z0-9_]+)`", export_section, re.M):
            assert fmt in registered, (
                f"{DOC} lists exporter '{fmt}', which is not registered")

    def test_the_non_cv_allowlist_has_not_gone_stale(self):
        """An entry for an exporter that no longer exists hides a real gap."""
        registered = set(export_registry.get_supported_formats())
        stale = NON_CV_EXPORTERS - registered
        assert not stale, (
            f"NON_CV_EXPORTERS names exporters that are no longer registered: "
            f"{stale}. Remove them, or a genuinely missing CV format could hide "
            f"behind the allowlist.")


class TestOneWayPathsAreMarked:
    """
    A one-way format must be labelled one-way, and — just as important — a
    format that gains an exporter must stop being labelled one-way. This test
    caught exactly that when LabelMe's exporter landed.
    """

    def test_every_import_only_format_is_marked_one_way(self, doc_text):
        importers = set(import_registry.get_supported_formats())
        exporters = set(export_registry.get_supported_formats())
        for fmt in sorted(importers - exporters):
            assert re.search(rf"(?i){fmt}.*one-way", doc_text), (
                f"'{fmt}' can be imported but not exported, and the page does "
                f"not say so — it implies a round trip that does not exist")

    def test_no_round_trippable_format_is_still_called_one_way(self, doc_text):
        """The stale-claim direction: understating is a bug too."""
        importers = set(import_registry.get_supported_formats())
        exporters = set(export_registry.get_supported_formats())
        for fmt in sorted(importers & exporters):
            stale = re.search(rf"(?i)\b{fmt}\b[^|\n]*one-way", doc_text)
            assert not stale, (
                f"'{fmt}' round-trips now, but the page still calls it one-way: "
                f"{stale.group(0)!r}")


class TestConventionsAreDocumented:
    @pytest.mark.parametrize("phrase", [
        "centre-based",   # YOLO
        "corners",        # VOC
        "two opposite corners",  # LabelMe rectangles
    ])
    def test_the_misreadable_conventions_are_called_out(self, doc_text, phrase):
        """
        Each of these produces a *plausible* wrong answer when misread, which
        is exactly why they are worth stating rather than leaving implicit.
        """
        assert phrase in doc_text


class TestDocIsLinked:
    def test_the_matrix_is_in_the_nav(self):
        nav = Path("mkdocs.yml").read_text()
        assert "data-export/format_matrix.md" in nav, (
            "the format matrix is not reachable from the docs nav")

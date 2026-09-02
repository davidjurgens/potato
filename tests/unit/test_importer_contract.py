"""
Every importer must honour the contract the CLI depends on.

These are guards against three bugs that have each already shipped once, and
that no per-format test caught because each format's own tests looked fine:

1. **Stats key drift.** The CLI prints `num_images`, `num_annotations` and
   `num_categories`. Two importers invented their own names, and the result was
   a `KeyError` at the very END of a long, otherwise successful import.
2. **`--image-url-prefix` ignored.** The flag was parsed, threaded through
   options, and then dropped by three importers, so the canvas 404'd with
   nothing in the UI explaining why.
3. **Copy-paste helpers.** `_apply_url_prefix` existed as five byte-identical
   private copies, which is how (2) happened.

They are written against the registry rather than a hand-listed set, so a
sixteenth importer is covered the moment it is registered.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from potato.importers import base as importer_base
from potato.importers.base import REQUIRED_STATS, ImportResult
from potato.importers.registry import import_registry

IMPORTER_DIR = Path("potato/importers")

#: Formats whose `parse` takes a marker dict this package builds, so they can
#: only be driven through `parse_directory`. They are exercised by their own
#: format tests; here we only check their shape.
DIRECTORY_ONLY = {"yolo", "kitti", "mot", "davis", "openimages", "webdataset",
                  "huggingface"}


def source_files():
    return sorted(p for p in IMPORTER_DIR.glob("*_importer.py"))


class TestStatsContract:
    def test_summarize_fills_every_key_the_cli_prints(self):
        result = ImportResult()
        stats = result.summarize()
        for key in REQUIRED_STATS:
            assert key in stats, f"summarize() omits {key}"

    def test_summarize_accepts_format_specific_extras(self):
        stats = ImportResult().summarize(num_tracks=4)
        assert stats["num_tracks"] == 4
        assert "num_images" in stats, "extras must not replace the base keys"

    @pytest.mark.parametrize("path", source_files(), ids=lambda p: p.stem)
    def test_no_importer_hand_rolls_its_stats(self, path):
        """
        The names drifted twice when each importer built its own dict. Going
        through summarize() is what makes that impossible.
        """
        source = path.read_text()
        assert "stats = {" not in source, (
            f"{path.name} builds its stats dict by hand. Call "
            f"result.summarize(...) instead — the CLI reads "
            f"{', '.join(REQUIRED_STATS)} and a typo here is a KeyError after "
            f"a successful import.")


class TestUrlPrefixContract:
    def test_only_one_definition_of_the_prefix_helper_exists(self):
        """Five copies is how three importers came to ignore the flag."""
        definitions = [p.name for p in source_files()
                       if "def apply_url_prefix" in p.read_text()
                       or "def _apply_url_prefix" in p.read_text()]
        assert definitions == [], (
            f"apply_url_prefix is redefined in {definitions}. Import it from "
            f"potato.importers._common so there is exactly one definition.")

    @pytest.mark.parametrize("path", source_files(), ids=lambda p: p.stem)
    def test_every_importer_applies_the_url_prefix(self, path):
        """
        An importer that never calls it silently produces a project whose
        images 404, which is only discovered in the browser one item at a time.
        """
        source = path.read_text()
        assert "apply_url_prefix" in source, (
            f"{path.name} never applies --image-url-prefix, so the generated "
            f"project will store bare filenames that no route serves.")

    def test_the_helper_joins_without_doubling_separators(self):
        from potato.importers._common import apply_url_prefix

        assert apply_url_prefix("a.jpg", {"image_url_prefix": "/media"}) == "/media/a.jpg"
        assert apply_url_prefix("a.jpg", {"image_url_prefix": "/media/"}) == "/media/a.jpg"
        assert apply_url_prefix("/a.jpg", {"image_url_prefix": "/media"}) == "/media/a.jpg"

    def test_no_prefix_leaves_the_name_alone(self):
        from potato.importers._common import apply_url_prefix

        assert apply_url_prefix("a.jpg", {}) == "a.jpg"
        assert apply_url_prefix("a.jpg", None) == "a.jpg"


class TestRegistryContract:
    @pytest.mark.parametrize("name", import_registry.get_supported_formats())
    def test_every_importer_declares_itself(self, name):
        importer = import_registry.get(name)
        assert importer.format_name == name
        assert importer.description, f"{name} has no description for --list-formats"

    @pytest.mark.parametrize("name", import_registry.get_supported_formats())
    def test_detect_is_side_effect_free_on_junk(self, name):
        """
        The registry calls detect() on every importer in turn, so one that
        raises on unfamiliar input breaks auto-detection for all the others.
        """
        importer = import_registry.get(name)
        for junk in (None, 42, "text", [], {}, {"unrelated": True}):
            result = importer.detect(junk)
            assert isinstance(result, bool), (
                f"{name}.detect({junk!r}) returned {result!r}, not a bool")

    def test_directory_formats_expose_parse_directory(self):
        for name in DIRECTORY_ONLY:
            importer = import_registry.get(name)
            assert importer is not None, f"{name} is not registered"
            assert hasattr(importer, "parse_directory"), (
                f"{name} is a directory format but has no parse_directory; the "
                f"CLI would reject the only input it accepts.")

    def test_auto_detection_does_not_claim_a_directory_marker(self):
        """
        Directory importers detect on a marker dict THIS package builds. If one
        ever matched a user's own JSON, auto-detection would hand a COCO file
        to the DAVIS importer.
        """
        plausible_user_files = [
            {"images": [], "annotations": [], "categories": []},   # COCO
            {"shapes": [], "imagePath": "a.jpg"},                  # LabelMe
            {"item": {}, "annotations": []},                       # Darwin
            {"objects": [], "imgWidth": 10, "imgHeight": 10},      # Cityscapes
        ]
        for name in DIRECTORY_ONLY:
            importer = import_registry.get(name)
            for doc in plausible_user_files:
                assert not importer.detect(doc), (
                    f"{name}.detect() claims a plain {list(doc)[0]} document")


class TestNoDuplicatedHelpers:
    def test_common_helpers_are_not_reimplemented(self):
        """
        A second copy of a helper is where conventions drift apart. The names
        here are the ones that have already been duplicated once.
        """
        shared = [name for name, _obj in inspect.getmembers(
            importer_base, inspect.isfunction)]
        for path in source_files():
            source = path.read_text()
            for helper in shared:
                assert f"def {helper}(" not in source, (
                    f"{path.name} redefines {helper}, which lives in base.py")

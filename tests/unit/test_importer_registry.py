"""
Importer registry mechanics, mirroring the trace-converter registry tests.
"""

import pytest

from potato.importers import import_registry
from potato.importers.base import BaseAnnotationImporter, ImportResult
from potato.importers.registry import ImporterRegistry


class _Dummy(BaseAnnotationImporter):
    format_name = "dummy"
    description = "test only"
    file_extensions = [".dummy"]

    def parse(self, data, options=None):
        return ImportResult(stats={"seen": data})

    def detect(self, data):
        return isinstance(data, dict) and data.get("kind") == "dummy"


class _Exploding(BaseAnnotationImporter):
    format_name = "exploding"
    description = "raises during detect"
    file_extensions = []

    def parse(self, data, options=None):
        return ImportResult()

    def detect(self, data):
        raise RuntimeError("detect blew up")


class TestRegistry:

    def test_register_and_get(self):
        reg = ImporterRegistry()
        imp = _Dummy()
        reg.register(imp)
        assert reg.get("dummy") is imp
        assert reg.is_registered("dummy")
        assert reg.get_supported_formats() == ["dummy"]

    def test_duplicate_registration_is_an_error(self):
        reg = ImporterRegistry()
        reg.register(_Dummy())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_Dummy())

    def test_nameless_importer_is_rejected(self):
        class Nameless(_Dummy):
            format_name = ""

        with pytest.raises(ValueError, match="non-empty format_name"):
            ImporterRegistry().register(Nameless())

    def test_unknown_format_lists_what_is_supported(self):
        reg = ImporterRegistry()
        reg.register(_Dummy())
        with pytest.raises(ValueError) as exc:
            reg.parse("nope", {})
        assert "nope" in str(exc.value)
        assert "dummy" in str(exc.value)

    def test_detect_format_returns_none_when_nothing_matches(self):
        reg = ImporterRegistry()
        reg.register(_Dummy())
        assert reg.detect_format({"kind": "other"}) is None

    def test_a_raising_detector_does_not_break_detection(self):
        reg = ImporterRegistry()
        reg.register(_Exploding())
        reg.register(_Dummy())
        assert reg.detect_format({"kind": "dummy"}) == "dummy"

    def test_list_importers_returns_metadata(self):
        reg = ImporterRegistry()
        reg.register(_Dummy())
        info, = reg.list_importers()
        assert info["name"] == "dummy"
        assert info["file_extensions"] == [".dummy"]


class TestBuiltins:

    def test_coco_is_registered_on_import(self):
        assert "coco" in import_registry.get_supported_formats()

    def test_coco_metadata_mentions_the_encodings_it_handles(self):
        info = next(i for i in import_registry.list_importers()
                    if i["name"] == "coco")
        assert "RLE" in info["description"]
        assert ".json" in info["file_extensions"]

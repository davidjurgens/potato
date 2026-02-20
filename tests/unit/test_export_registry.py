"""
Tests for the export registry.

Verifies:
1. Exporter registration and lookup
2. Duplicate registration handling
3. Export dispatch
4. All built-in exporters are registered
"""

import pytest
from unittest.mock import MagicMock
from potato.export.base import BaseExporter, ExportContext, ExportResult
from potato.export.registry import ExportRegistry, export_registry


class DummyExporter(BaseExporter):
    format_name = "dummy"
    description = "Dummy exporter for testing"
    file_extensions = [".dummy"]

    def export(self, context, output_path, options=None):
        return ExportResult(
            success=True, format_name=self.format_name,
            files_written=["test.dummy"],
        )

    def can_export(self, context):
        return True, ""


class FailExporter(BaseExporter):
    format_name = "fail"
    description = "Always fails can_export"
    file_extensions = [".fail"]

    def export(self, context, output_path, options=None):
        return ExportResult(success=False, format_name=self.format_name)

    def can_export(self, context):
        return False, "This format always fails"


class TestExportRegistry:
    def setup_method(self):
        self.registry = ExportRegistry()

    def test_register_and_get(self):
        exporter = DummyExporter()
        self.registry.register(exporter)
        assert self.registry.get("dummy") is exporter

    def test_register_duplicate_raises(self):
        self.registry.register(DummyExporter())
        with pytest.raises(ValueError, match="already registered"):
            self.registry.register(DummyExporter())

    def test_register_empty_name_raises(self):
        exporter = DummyExporter()
        exporter.format_name = ""
        with pytest.raises(ValueError, match="non-empty"):
            self.registry.register(exporter)

    def test_get_nonexistent(self):
        assert self.registry.get("nonexistent") is None

    def test_is_registered(self):
        self.registry.register(DummyExporter())
        assert self.registry.is_registered("dummy")
        assert not self.registry.is_registered("nonexistent")

    def test_get_supported_formats(self):
        self.registry.register(DummyExporter())
        self.registry.register(FailExporter())
        formats = self.registry.get_supported_formats()
        assert formats == ["dummy", "fail"]

    def test_list_exporters(self):
        self.registry.register(DummyExporter())
        exporters = self.registry.list_exporters()
        assert len(exporters) == 1
        assert exporters[0]["format_name"] == "dummy"
        assert exporters[0]["description"] == "Dummy exporter for testing"

    def test_export_unknown_format(self):
        ctx = ExportContext(
            config={}, annotations=[], items={}, schemas=[], output_dir=""
        )
        with pytest.raises(ValueError, match="Unknown export format"):
            self.registry.export("nonexistent", ctx, "/tmp")

    def test_export_can_export_false(self):
        self.registry.register(FailExporter())
        ctx = ExportContext(
            config={}, annotations=[], items={}, schemas=[], output_dir=""
        )
        result = self.registry.export("fail", ctx, "/tmp")
        assert not result.success
        assert "Cannot export" in result.errors[0]

    def test_export_success(self):
        self.registry.register(DummyExporter())
        ctx = ExportContext(
            config={}, annotations=[], items={}, schemas=[], output_dir=""
        )
        result = self.registry.export("dummy", ctx, "/tmp")
        assert result.success
        assert result.files_written == ["test.dummy"]


class TestBuiltinExportersRegistered:
    """Verify all built-in exporters are registered in the global registry."""

    def test_coco_registered(self):
        assert export_registry.is_registered("coco")

    def test_yolo_registered(self):
        assert export_registry.is_registered("yolo")

    def test_pascal_voc_registered(self):
        assert export_registry.is_registered("pascal_voc")

    def test_conll_2003_registered(self):
        assert export_registry.is_registered("conll_2003")

    def test_conll_u_registered(self):
        assert export_registry.is_registered("conll_u")

    def test_all_formats_listed(self):
        formats = export_registry.get_supported_formats()
        expected = ["coco", "conll_2003", "conll_u", "eaf", "mask_png", "pascal_voc", "textgrid", "yolo"]
        assert formats == expected

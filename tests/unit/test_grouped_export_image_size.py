"""
Exporters that group objects by image sized every image from the last record.

Seven exporters collect each image's objects in one loop and size the images
in a second loop. The second loop passed `annotation=ann`, the first loop's
variable, so `get_image_dimensions` read whichever record came last. When an
image's only size source is its own mask RLE (no metadata, no readable file),
every image took the size of the image annotated last, and its normalized
coordinates were scaled into the wrong frame.

Found by the Tier 4 clinical-formats work in labelme_exporter.py; the same
line was in six siblings.
"""

import importlib

import pytest

from potato.export.base import ExportContext
from potato.export import cv_utils


EXPORTERS = [
    ("cityscapes_exporter", "CityscapesExporter"),
    ("cvat_exporter", "CVATExporter"),
    ("darwin_exporter", "DarwinExporter"),
    ("kitti_exporter", "KITTIExporter"),
    ("davis_exporter", "DAVISExporter"),
    ("mot_exporter", "MOTExporter"),
    ("labelme_exporter", "LabelMeExporter"),
]


def _mask_record(instance_id, height, width):
    return {
        "instance_id": instance_id,
        "user_id": "u1",
        "image_annotations": {"img": [
            {"type": "mask", "label": "cell",
             "rle": {"size": [height, width], "counts": [height * width]}},
            {"type": "bbox", "label": "cell",
             "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
        ]},
    }


def _exporter_class(module_name, class_name):
    module = importlib.import_module(f"potato.export.{module_name}")
    cls = getattr(module, class_name, None)
    if cls is None:  # tolerate a differently-cased class name
        matches = [v for k, v in vars(module).items()
                   if k.lower() == class_name.lower() and isinstance(v, type)]
        cls = matches[0] if matches else None
    if cls is None:
        pytest.fail(f"no exporter class {class_name} in {module_name}")
    return module, cls


@pytest.mark.parametrize("module_name,class_name", EXPORTERS)
def test_each_image_is_sized_from_its_own_mask(module_name, class_name,
                                               tmp_path, monkeypatch):
    module, cls = _exporter_class(module_name, class_name)
    seen = {}
    real = cv_utils.get_image_dimensions

    def spy(item, *args, **kwargs):
        size = real(item, *args, **kwargs)
        seen[item.get("id")] = size
        return size

    monkeypatch.setattr(module, "get_image_dimensions", spy)

    items = {
        "a": {"id": "a", "image": "a.png", "video": "seq1", "frame": 0},
        "b": {"id": "b", "image": "b.png", "video": "seq1", "frame": 1},
    }
    context = ExportContext(
        config={"task_dir": str(tmp_path)},
        # b is annotated last, so the stale record was b's.
        annotations=[_mask_record("a", 400, 640), _mask_record("b", 200, 320)],
        items=items,
        schemas=[{"annotation_type": "image_annotation", "name": "img",
                  "labels": [{"name": "cell"}]}],
        output_dir="",
    )
    cls().export(context, str(tmp_path / "out"))

    assert seen, f"{class_name} never sized an image"
    if "a" in seen:
        assert seen["a"] == (640, 400)
    if "b" in seen:
        assert seen["b"] == (320, 200)


def test_the_grouped_record_carries_the_objects():
    objects = [{"type": "mask", "rle": {"size": [10, 20], "counts": [200]}}]
    assert cv_utils._dimensions_from_masks(
        cv_utils.grouped_objects_record(objects)) == (20, 10)
    assert cv_utils._dimensions_from_masks(
        cv_utils.grouped_objects_record([])) is None

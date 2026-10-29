"""
Multichannel microscopy: OME-Zarr / OME-TIFF reading, tile compositing, label
rasters, the scheme's validation, and the microscopy exporter.

Fixtures are written by the example's own generator
(examples/image/multichannel-microscopy/generate_data.py) into tests/output,
so the files read here are real OME-Zarr 0.4 / 0.5 stores and OME-TIFFs.
"""

import csv
import importlib.util
import io
import json
import os
import subprocess
import sys

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("tifffile")
zarr = pytest.importorskip("zarr")

from tests.helpers.test_utils import create_test_directory  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "image", "multichannel-microscopy")


def _generator():
    spec = importlib.util.spec_from_file_location(
        "mic_generate_data", os.path.join(EXAMPLE, "generate_data.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _generator()


@pytest.fixture(scope="module")
def media():
    from potato.science.converters import ome
    ome.clear_cache()
    root = create_test_directory("microscopy_unit")
    paths = {
        "zarr3": GEN.write_zarr(os.path.join(root, "a3.ome.zarr"), size=96, z_slices=3, chunk=32,
                                zarr_format=3, levels=3),
        "zarr2": GEN.write_zarr(os.path.join(root, "a2.ome.zarr"), size=96, z_slices=3, chunk=32,
                                zarr_format=2, levels=2),
        "tiff": GEN.write_tiff(os.path.join(root, "b.ome.tif"), os.path.join(root, "b_cells.tif"),
                               size=96, timepoints=3),
        "tiff_labels": os.path.join(root, "b_cells.tif"),
        "root": root,
    }
    return paths


def _raw(path):
    """The level-0 array straight from zarr, for comparison."""
    group = zarr.open_group(store=path, mode="r")
    return np.asarray(group["0"][...]), np.asarray(group["labels"]["cells"]["0"][...])


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key, version", [("zarr3", "0.5"), ("zarr2", "0.4")])
def test_ome_zarr_metadata_and_regions(media, key, version):
    from potato.science.converters.ome import open_ome, zarr_format_of

    assert zarr_format_of(media[key]) == (3 if version == "0.5" else 2)
    image = open_ome(media[key])
    assert image.axes == "czyx"
    assert (image.size_c, image.size_z, image.size_t, image.size_y, image.size_x) == (3, 3, 1, 96, 96)
    assert [c.name for c in image.channels] == ["DAPI", "Membrane", "Marker"]
    assert image.channels[0].color == "3b6cff"
    assert (image.channels[1].start, image.channels[1].end) == (150.0, 2200.0)
    assert image.physical["x"] == {"size": 0.325, "unit": "micrometer"}
    assert image.labels == ["cells"]
    assert image.level_factor(1) == (2.0, 2.0)

    data, labels = _raw(media[key])
    region = image.read_region(0, 2, 1, 0, 10, 40, 20, 70)
    assert np.array_equal(region, data[2, 1, 10:40, 20:70])
    assert np.array_equal(image.read_label_region("cells", 0, 2, 0, 0, 96, 0, 96), labels[2])


def test_coordinate_systems_axes_are_read(media):
    """The NGFF development spec lists axes under coordinateSystems."""
    from potato.science.converters.ome import clear_cache, open_ome

    root = create_test_directory("microscopy_cs")
    path = GEN.write_zarr(os.path.join(root, "cs.ome.zarr"), size=64, z_slices=2, chunk=32,
                          zarr_format=3, levels=2, with_labels=False)
    group = zarr.open_group(store=path, mode="r+")
    attrs = dict(group.attrs)
    multiscale = attrs["ome"]["multiscales"][0]
    axes = multiscale.pop("axes")
    multiscale["coordinateSystems"] = [{"name": "intrinsic", "axes": axes}]
    for ds in multiscale["datasets"]:
        scale = ds["coordinateTransformations"][0]["scale"]
        ds["coordinateTransformations"] = [{"type": "scale", "scale": scale,
                                            "input": {"path": ds["path"]},
                                            "output": {"name": "intrinsic"}}]
    attrs["ome"]["version"] = "0.6"
    group.attrs.put(attrs) if hasattr(group.attrs, "put") else group.attrs.update(attrs)
    clear_cache()
    image = open_ome(path)
    assert image.axes == "czyx" and image.size_z == 2
    assert image.physical["y"]["size"] == pytest.approx(0.325)


def test_ome_zarr_with_unknown_axis_is_refused(media):
    from potato.science.converters.ome import OmeError, clear_cache, open_ome

    root = create_test_directory("microscopy_badaxis")
    path = GEN.write_zarr(os.path.join(root, "bad.ome.zarr"), size=32, z_slices=1, chunk=32,
                          levels=1, with_labels=False)
    group = zarr.open_group(store=path, mode="r+")
    attrs = dict(group.attrs)
    attrs["ome"]["multiscales"][0]["axes"][0]["name"] = "q"
    group.attrs.update(attrs)
    clear_cache()
    with pytest.raises(OmeError, match="only t, c, z, y and x"):
        open_ome(path)


def test_ome_tiff_reader(media):
    import tifffile
    from potato.science.converters.ome import open_ome

    image = open_ome(media["tiff"], label_path=media["tiff_labels"])
    assert image.kind == "ome-tiff"
    assert image.axes == "tcyx"
    assert (image.size_t, image.size_c, image.size_z) == (3, 3, 1)
    assert [(c.name, c.color) for c in image.channels] == [
        ("DAPI", "3b6cff"), ("Membrane", "2fd16b"), ("Marker", "ff3b3b")]
    # No window in the file: estimated, and the range is the 12-bit depth the
    # data needs, not uint16's 65535.
    assert image.channels[0].max == 4095.0
    assert 50 < image.channels[0].start < 200 < 2000 < image.channels[0].end <= 4095
    assert len(image.levels) == 2 and image.level_factor(1) == (2.0, 2.0)
    data = tifffile.imread(media["tiff"])
    assert np.array_equal(image.read_region(0, 1, 0, 2, 0, 96, 0, 96), data[2, 1])
    labels = tifffile.imread(media["tiff_labels"])
    assert np.array_equal(image.read_label_region("cells", 0, 0, 1, 0, 96, 0, 96), labels[1])


def test_label_tiff_of_the_wrong_size_is_refused(media):
    import tifffile
    from potato.science.converters.ome import OmeError, open_ome

    wrong = os.path.join(media["root"], "wrong_cells.tif")
    tifffile.imwrite(wrong, np.zeros((50, 50), dtype="uint16"))
    with pytest.raises(OmeError, match="they must match"):
        open_ome(media["tiff"], label_path=wrong)


def test_tiff_plane_above_the_pixel_limit_is_refused(media):
    from potato.science.converters.ome import OmeError, clear_cache, open_ome

    clear_cache()
    image = open_ome(media["tiff"], max_pixels=4000)
    with pytest.raises(OmeError, match="MP limit"):
        image.read_region(0, 0, 0, 0, 0, 10, 0, 10)
    # The coarse level (48 x 48 = 2304 px) is still readable.
    assert image.read_region(1, 0, 0, 0, 0, 10, 0, 10).shape == (10, 10)


def test_readers_do_not_load_at_import():
    code = ("import sys; import potato.server_utils.schemas.microscopy, "
            "potato.science.converters.ome, potato.science.microscopy_routes; "
            "print(sorted(m for m in ('zarr', 'tifffile') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


def test_converter_registry_finds_ome_files():
    from potato.science.converters import converter_for
    from potato.science.converters.ome import open_ome

    assert converter_for("x/tissue.ome.zarr") is open_ome
    assert converter_for("tissue.ome.tif") is open_ome


# ---------------------------------------------------------------------------
# Compositing
# ---------------------------------------------------------------------------

def _tile_pixels(image, channel_spec, z=0, t=0, level=None):
    from PIL import Image
    from potato.media.tiles import PyramidSpec
    from potato.science.microscopy import parse_channel_spec, render_tile

    spec = PyramidSpec(image.size_x, image.size_y, tile_size=254, overlap=1)
    level = spec.max_level if level is None else level
    body = render_tile(image, spec, level, 0, 0, parse_channel_spec(channel_spec, image), z=z, t=t)
    return np.asarray(Image.open(io.BytesIO(body)).convert("RGB")).astype(int)


def _marker_cell(image):
    """A cell the generator gave the marker (index % 3 == 1), and its centre."""
    centres, radii = GEN.cell_layout(image.size_x, seed=7)
    cy, cx = centres[0]
    return int(round(cy)), int(round(cx))


def test_only_the_visible_channels_are_composited(media):
    from potato.science.converters.ome import open_ome

    image = open_ome(media["zarr3"])
    cy, cx = _marker_cell(image)
    red_only = _tile_pixels(image, "2:ff0000:150:2600", z=1)
    assert red_only.shape[:2] == (96, 96)
    assert red_only[cy, cx, 0] > 150 and red_only[cy, cx, 1] < 25 and red_only[cy, cx, 2] < 25
    blue_only = _tile_pixels(image, "0:0000ff:150:3200", z=1)
    assert blue_only[cy, cx, 2] > 150 and blue_only[cy, cx, 0] < 25
    assert _tile_pixels(image, "", z=1).max() < 10        # nothing on: black


def test_contrast_limits_change_the_rendering(media):
    from potato.science.converters.ome import open_ome

    image = open_ome(media["zarr3"])
    cy, cx = _marker_cell(image)
    raw = float(image.read_region(0, 0, 1, 0, cy, cy + 1, cx, cx + 1)[0, 0])
    wide = _tile_pixels(image, "0:0000ff:0:4095", z=1)[cy, cx, 2]
    narrow = _tile_pixels(image, f"0:0000ff:0:{raw / 2:g}", z=1)[cy, cx, 2]
    assert wide == pytest.approx(255 * raw / 4095, abs=8)
    assert narrow >= 250                                   # saturated


def test_zoomed_out_levels_read_the_coarse_pyramid(media):
    from potato.science.converters.ome import open_ome
    from potato.science.microscopy import pick_level

    image = open_ome(media["zarr3"])
    assert [pick_level(image, s) for s in (1, 1.5, 2, 3, 4, 64)] == [0, 0, 1, 1, 2, 2]
    # DZI level max-2 is a quarter scale: 24 x 24, cut from pyramid level 2.
    tile = _tile_pixels(image, "0:0000ff:150:3200", z=1, level=5)
    assert tile.shape[:2] == (24, 24)


@pytest.mark.parametrize("spec, message", [
    ("0:00f:1:2", "hex colour"), ("5:0000ff:1:2", "not in this image"),
    ("0:0000ff:1:2;0:ff0000:1:2", "twice"), ("0:0000ff:a:2", "non-numeric"),
    ("0:0000ff:1", "index:colour:start:end"), ("0:0000ff:nan:2", "not a number")])
def test_bad_channel_settings_are_refused(media, spec, message):
    from potato.science.converters.ome import OmeError, open_ome
    from potato.science.microscopy import parse_channel_spec

    with pytest.raises(OmeError, match=message):
        parse_channel_spec(spec, open_ome(media["zarr3"]))


def test_plane_outside_the_image_is_refused(media):
    from potato.science.converters.ome import OmeError, open_ome

    with pytest.raises(OmeError, match="z=3 is outside"):
        _tile_pixels(open_ome(media["zarr3"]), "0:0000ff:1:2", z=3)


# ---------------------------------------------------------------------------
# Label rasters, cells, class images
# ---------------------------------------------------------------------------

def test_label_raster_and_cell_table(media):
    import gzip
    from potato.science.converters.ome import open_ome
    from potato.science.microscopy import cell_table, encode_raster, label_raster

    image = open_ome(media["zarr3"])
    _data, labels = _raw(media["zarr3"])
    raster, factor = label_raster(image, "cells", z=1)
    assert factor == 1.0 and np.array_equal(raster, labels[1])
    # A smaller ceiling picks a coarser level: same ids, fewer pixels.
    small, small_factor = label_raster(image, "cells", z=1, max_side=48)
    assert small.shape == (48, 48) and small_factor == 2.0
    assert set(np.unique(small)) <= set(np.unique(labels[1]))
    body, width = encode_raster(raster)
    assert width == 2
    assert np.array_equal(np.frombuffer(gzip.decompress(body), "<u2").reshape(96, 96), raster)

    cells = cell_table(raster, factor)
    centres, _radii = GEN.cell_layout(96, seed=7)
    assert len(cells) == len(centres)
    first = next(c for c in cells if c["id"] == 1)
    assert first["x"] == pytest.approx(centres[0][1] + 0.5, abs=1.0)
    assert first["y"] == pytest.approx(centres[0][0] + 0.5, abs=1.0)
    assert first["area"] == int((labels[1] == 1).sum())


def test_class_volume_maps_ids_on_every_plane(media):
    from potato.science.converters.ome import open_ome
    from potato.science.microscopy import class_volume

    image = open_ome(media["zarr3"])
    _data, labels = _raw(media["zarr3"])
    volume, axes = class_volume(image, "cells", {1: 2, 3: 1})
    assert axes == "zyx" and volume.shape == labels.shape
    expected = np.where(labels == 1, 2, np.where(labels == 3, 1, 0))
    assert np.array_equal(volume, expected)


# ---------------------------------------------------------------------------
# Scheme
# ---------------------------------------------------------------------------

def _scheme(**extra):
    base = {"annotation_type": "microscopy", "name": "cells", "description": "d",
            "labels": ["damaged", {"name": "debris", "color": "#868e96"}]}
    base.update(extra)
    return base


def test_layout_carries_the_client_config():
    from potato.server_utils.schemas.microscopy import generate_microscopy_layout

    html, keys = generate_microscopy_layout(_scheme(cell_labels=["pos", "neg"], min_cells=2,
                                                    tools=["polygon"]))
    assert keys == []
    assert 'data-annotation-type="microscopy"' in html
    assert 'class="annotation-input microscopy-input"' in html
    import html as html_lib
    import re
    cfg = json.loads(html_lib.unescape(re.search(r"data-microscopy-config='([^']*)'", html).group(1)))
    assert cfg["tools"] == ["polygon"] and cfg["minCells"] == 2
    assert [l["name"] for l in cfg["cellLabels"]] == ["pos", "neg"]
    assert cfg["labels"][1] == {"name": "debris", "color": "#868e96"}


@pytest.mark.parametrize("extra, message", [
    ({"labels": None}, "labels is required"),
    ({"labels": []}, "non-empty list"),
    ({"labels": ["a", "a"]}, "duplicate"),
    ({"tools": ["cuboid"]}, "cuboid not supported"),
    ({"min_cells": -1}, "min_cells must be a whole number"),
    ({"tile_size": 10}, "tile_size"),
    ({"channels": [{"color": "#ff0000"}]}, "needs an index or a name"),
    ({"channels": [{"index": 0, "contrast": [10, 5]}]}, "contrast must be"),
    ({"channels": [{"index": 0, "colour": "#ff0000"}]}, "unknown keys: colour"),
    ({"image_key": ""}, "image_key must be"),
])
def test_config_validation_names_the_key(extra, message):
    from potato.server_utils.config_module import ConfigValidationError, _validate_microscopy

    scheme = _scheme(**extra)
    if extra.get("labels", 1) is None:
        scheme.pop("labels")
    with pytest.raises(ConfigValidationError, match=message):
        _validate_microscopy(scheme, "annotation_schemes[0]")


def test_valid_scheme_passes_and_empty_tools_is_cells_only():
    from potato.server_utils.config_module import _validate_microscopy
    from potato.server_utils.schemas.microscopy import client_config

    _validate_microscopy(_scheme(tools=[], channels=[{"name": "DAPI", "contrast": [0, 100]}]), "s")
    assert client_config(_scheme(tools=[]))["tools"] == []
    assert client_config(_scheme())["tools"] == ["bbox", "polygon", "landmark"]


def test_item_paths_stay_inside_the_project(media):
    from potato.science.microscopy_routes import resolve_item_path

    config = {"task_dir": media["root"], "media_directory": "."}
    # A real file one level above the project: reachable by "..", so only the
    # containment check keeps it out.
    outside = os.path.join(os.path.dirname(media["root"]), "outside_microscopy.ome.tif")
    with open(outside, "wb") as f:
        f.write(b"II*\x00")
    assert resolve_item_path(config, "../outside_microscopy.ome.tif") is None
    assert resolve_item_path(config, "a3.ome.zarr") == os.path.realpath(media["zarr3"])
    assert resolve_item_path(config, "/media/a3.ome.zarr") == os.path.realpath(media["zarr3"])
    for bad in ("../../etc/passwd", "/etc/passwd", "https://example.org/x.ome.zarr",
                "../microscopy_cs/cs.ome.zarr", "missing.ome.zarr"):
        assert resolve_item_path(config, bad) is None, bad


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _context(media, answers):
    from potato.export.base import ExportContext

    scheme = _scheme(cell_labels=[{"name": "pos", "color": "#ff0000"},
                                  {"name": "neg", "color": "#0000ff"}])
    anns = [{"user_id": u, "instance_id": i, "labels": {"cells": {"cells": json.dumps(a)}}}
            for u, i, a in answers]
    config = {"annotation_schemes": [scheme], "task_dir": media["root"], "media_directory": "."}
    return ExportContext(config=config, annotations=anns,
                         items={"a": {"id": "a", "image": "a3.ome.zarr"},
                                "b": {"id": "b", "image": "b.ome.tif"}},
                         schemas=[scheme], output_dir=media["root"])


def _answer(rois=(), cells=()):
    return {"image": {"width": 96, "height": 96}, "rois": list(rois), "cells": list(cells),
            "label_image": "cells"}


def test_export_rois_cells_and_label_arrays(media):
    from potato.export.microscopy_exporter import MicroscopyExporter

    rois = [{"type": "bbox", "label": "damaged", "color": "#e8590c", "z": 1, "t": 0,
             "coordinates": {"x": 0.25, "y": 0.5, "width": 0.25, "height": 0.125}},
            {"type": "polygon", "label": "debris", "z": 0, "t": 0,
             "coordinates": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.0}, {"x": 0.5, "y": 0.5}]},
            {"type": "landmark", "label": "damaged", "z": 2, "t": 0,
             "coordinates": {"x": 0.5, "y": 0.75}}]
    context = _context(media, [
        ("ann1", "a", _answer(rois, [{"label_id": 1, "class": "pos", "z": 1, "t": 0},
                                     {"label_id": 3, "class": "neg", "z": 1, "t": 0}])),
        ("ann2", "a", _answer(cells=[{"label_id": 1, "class": "neg", "z": 0, "t": 0}])),
    ])
    out = os.path.join(media["root"], "export")
    exporter = MicroscopyExporter()
    assert exporter.can_export(context)[0]
    result = exporter.export(context, out)
    assert result.success, result.errors
    assert result.stats == {"rois": 3, "cells": 3, "label_stores": 1}

    with open(os.path.join(out, "microscopy_rois.geojson")) as f:
        features = json.load(f)["features"]
    assert features[0]["geometry"] == {"type": "Polygon", "coordinates": [[
        [24.0, 48.0], [48.0, 48.0], [48.0, 60.0], [24.0, 60.0], [24.0, 48.0]]]}
    assert features[0]["properties"]["classification"] == {"name": "damaged", "color": [232, 89, 12]}
    assert features[0]["properties"]["z"] == 1
    assert features[1]["geometry"]["coordinates"][0][-1] == [0.0, 0.0]          # closed ring
    assert features[2]["geometry"] == {"type": "Point", "coordinates": [48.0, 72.0]}

    with open(os.path.join(out, "microscopy_cells.csv")) as f:
        rows = list(csv.DictReader(f))
    assert [(r["user_id"], r["label_id"], r["class"]) for r in rows] == [
        ("ann1", "1", "pos"), ("ann1", "3", "neg"), ("ann2", "1", "neg")]

    _data, labels = _raw(media["zarr3"])
    store = zarr.open_group(store=os.path.join(out, "ome_zarr", "a.ome.zarr"), mode="r")
    assert store["labels"].attrs["ome"]["labels"] == ["cells__ann1", "cells__ann2"]
    ann1 = np.asarray(store["labels"]["cells__ann1"]["0"][...])
    assert np.array_equal(ann1, np.where(labels == 1, 1, np.where(labels == 3, 2, 0)))
    meta = store["labels"]["cells__ann1"].attrs["ome"]
    assert meta["image-label"]["properties"] == [{"label-value": 1, "class": "pos"},
                                                 {"label-value": 2, "class": "neg"}]
    assert meta["image-label"]["colors"][0] == {"label-value": 1, "rgba": [255, 0, 0, 255]}
    ann2 = np.asarray(store["labels"]["cells__ann2"]["0"][...])
    assert set(np.unique(ann2)) == {0, 2}


def test_export_without_label_arrays_and_with_missing_source(media):
    from potato.export.microscopy_exporter import MicroscopyExporter

    context = _context(media, [("u", "a", _answer(cells=[{"label_id": 2, "class": "pos"}]))])
    out = os.path.join(media["root"], "export_off")
    result = MicroscopyExporter().export(context, out, {"label_arrays": "false"})
    assert result.stats["label_stores"] == 0 and not os.path.exists(os.path.join(out, "ome_zarr"))

    context.items["a"]["image"] = "gone.ome.zarr"
    result = MicroscopyExporter().export(context, os.path.join(media["root"], "export_gone"))
    assert result.stats["label_stores"] == 0
    assert any("not found under the media directory" in w for w in result.warnings)


def test_export_refuses_a_project_without_the_scheme():
    from potato.export.base import ExportContext
    from potato.export.microscopy_exporter import MicroscopyExporter

    context = ExportContext(config={}, annotations=[{"labels": {}}], items={}, schemas=[],
                            output_dir=".")
    assert MicroscopyExporter().can_export(context) == (False, "No microscopy scheme in this project")

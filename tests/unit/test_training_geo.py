"""Geo answers as detection targets on their raster, and predictions back
as GeoJSON.

The rasters are written here with real GeoTIFF tags (ModelPixelScale,
ModelTiepoint, GeoKeyDirectory), in EPSG:4326 and in Web Mercator, so the
transform is read the way a GIS file carries it.
"""

import json
import os

import pytest

from potato.training import rasters, registry
from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from tests.unit.test_training_detection_audio_dpo import _context, _predictions, _run, _spec

tifffile = pytest.importorskip("tifffile")
HAVE = __import__("importlib").util.find_spec


def geotiff(path, width, height, origin, pixel, epsg, bands=3):
    """A GeoTIFF whose top-left corner is *origin* (map x, y) and whose
    pixels are *pixel* map units square."""
    import numpy
    data = numpy.zeros((height, width, bands), dtype="uint16")
    data[..., 0] = 1000
    data[height // 4: height // 2, width // 4: width // 2, :] = 4000
    geokeys = [1, 1, 0, 3, 1024, 0, 1, 2 if epsg == 4326 else 1,
               1025, 0, 1, 1,
               2048 if epsg == 4326 else 3072, 0, 1, epsg]
    tifffile.imwrite(str(path), data, photometric="rgb" if bands == 3 else "minisblack",
                     extratags=[(33550, 12, 3, (pixel, pixel, 0.0), False),
                                (33922, 12, 6, (0.0, 0.0, 0.0, origin[0], origin[1], 0.0), False),
                                (34735, 3, len(geokeys), tuple(geokeys), False)])
    return path


def square_feature(lon0, lat0, lon1, lat1, label="Field"):
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"label": label, "tool": "polygon", "text": ""}}


def test_the_georef_of_a_lonlat_geotiff(tmp_path):
    path = geotiff(tmp_path / "w.tif", 100, 50, origin=(10.0, 50.0), pixel=0.01, epsg=4326)
    pixels, georef = rasters.read_georef(str(path))
    assert pixels.shape == (50, 100, 3) and pixels.dtype.name == "uint8"
    assert georef["crs"] == "EPSG:4326"
    assert georef["transform"] == pytest.approx([0.01, 0, 10.0, 0, -0.01, 50.0])
    forward = rasters.to_pixels(georef, 100, 50)
    back = rasters.to_lonlat(georef, 100, 50)
    assert forward(10.5, 49.75) == pytest.approx((0.5, 0.5))
    assert back(0.5, 0.5) == pytest.approx((10.5, 49.75))


def test_a_projected_geotiff_is_reprojected(tmp_path):
    pytest.importorskip("pyproj")
    from pyproj import Transformer
    to_merc = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    x0, y0 = to_merc.transform(10.0, 50.0)
    path = geotiff(tmp_path / "m.tif", 64, 64, origin=(x0, y0), pixel=100.0, epsg=3857)
    _, georef = rasters.read_georef(str(path))
    assert georef["crs"] == "EPSG:3857"
    lon, lat = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform(
        x0 + 3200, y0 - 3200)
    assert rasters.to_pixels(georef, 64, 64)(lon, lat) == pytest.approx((0.5, 0.5), abs=1e-6)
    assert rasters.to_lonlat(georef, 64, 64)(0.5, 0.5) == pytest.approx((lon, lat), abs=1e-9)


def test_features_and_shapes_round_trip():
    georef = {"kind": "extent", "extent": [10.0, 40.0, 12.0, 41.0], "width": 200, "height": 100}
    forward = rasters.to_pixels(georef, 200, 100)
    objects = rasters.features_to_objects([
        square_feature(10.5, 40.25, 11.0, 40.75),
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.0, 40.5]},
         "properties": {"label": "Well"}},
        square_feature(30.0, 10.0, 31.0, 11.0)], forward)   # off the raster
    assert [o["type"] for o in objects] == ["polygon", "landmark"]
    assert objects[0]["coordinates"][0] == pytest.approx({"x": 0.25, "y": 0.75})
    assert objects[1]["coordinates"] == pytest.approx({"x": 0.5, "y": 0.5})
    back = rasters.objects_to_features(
        [dict(objects[0], confidence=0.7), objects[1]], rasters.to_lonlat(georef, 200, 100))
    first, second = back["features"]
    assert first["geometry"]["coordinates"][0][0] == pytest.approx([10.5, 40.25])
    assert first["geometry"]["coordinates"][0][-1] == first["geometry"]["coordinates"][0][0]
    assert first["properties"] == {"label": "Field", "tool": "polygon", "text": "",
                                   "source": "model", "confidence": 0.7}
    assert second["geometry"] == {"type": "Point", "coordinates": [11.0, 40.5]}


def geo_project(tmp, n=8, extent_basemap=True):
    """Fields (bright squares) on an image basemap placed by its extent."""
    from PIL import Image, ImageDraw
    os.makedirs(tmp / "maps", exist_ok=True)
    items, annotations = {}, []
    extent = [10.0, 40.0, 12.0, 41.0]
    for i in range(n):
        image = Image.new("RGB", (120, 60), (40, 90, 40))
        draw = ImageDraw.Draw(image)
        x = 10 + (i * 11) % 80
        draw.rectangle([x, 15, x + 20, 35], fill=(230, 220, 120))
        image.save(tmp / "maps" / ("m%d.png" % i))
        lon0, lon1 = 10.0 + 2.0 * x / 120, 10.0 + 2.0 * (x + 20) / 120
        lat1, lat0 = 41.0 - 15 / 60, 41.0 - 35 / 60
        iid = "g%d" % i
        items[iid] = {"id": iid, "map": {"image": "maps/m%d.png" % i, "extent": extent}}
        answer = {"type": "FeatureCollection",
                  "features": [square_feature(lon0, lat0, lon1, lat1)]}
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {"fields": {"fields": json.dumps(answer)}}})
    scheme = {"annotation_type": "geo_annotation", "name": "fields", "description": "",
              "labels": ["Field"], "basemap_field": "map", "tools": ["polygon"]}
    config, context = _context(tmp, [scheme], items, annotations)
    return config, context


def test_geo_bundle_rows_are_shapes_on_the_raster(tmp_path):
    config, context = geo_project(tmp_path)
    bundle, stats, split_ids = build_bundle(context, str(tmp_path / "b"), ["fields"],
                                            split_spec={"train": 1.0})
    assert bundle.manifest["schemas"][0]["kind"] == "geo" and not stats.warnings
    row = next(r for r in bundle.read_split("train") if r["instance_id"] == "g0")
    assert row["georef"]["kind"] == "extent" and row["georef"]["width"] == 120
    (shape,) = row["targets"]["fields"]
    xs = [p["x"] for p in shape["coordinates"]]
    assert min(xs) == pytest.approx(10 / 120) and max(xs) == pytest.approx(30 / 120)
    assert os.path.isfile(os.path.join(bundle.root, "media", row["media"]))


def test_geo_offers_the_detectors_and_not_the_rest():
    names = sorted(t.name for t in registry.trainers_for_schema(
        {"annotation_type": "geo_annotation"}, "image"))
    assert names == ["torchvision-detect", "torchvision-segment",
                     "ultralytics-detect", "ultralytics-segment"]


@pytest.mark.skipif(not (HAVE("torch") and HAVE("torchvision")),
                    reason="torch/torchvision absent")
def test_detector_on_geo_writes_geojson_back(tmp_path):
    config, context = geo_project(tmp_path, n=12)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["fields"], split_seed=1)
    spec = _spec(tmp_path, config, bundle, "torchvision-detect", "fields",
                 {"pretrained": False, "epochs": 1, "min_size": 64, "batch_size": 4,
                  "min_instances": 2, "score_threshold": 0.0, "max_detections": 3})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["heldout_metric"].endswith("map_50")
    records = _predictions(spec)
    assert records
    answer = records[0]["payload"]
    assert answer["type"] == "FeatureCollection" and answer["features"]
    feature = answer["features"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["source"] == "model"
    for lon, lat in feature["geometry"]["coordinates"][0]:
        assert 9.9 <= lon <= 12.1 and 39.9 <= lat <= 41.1


def test_the_widget_reads_predictions_only_when_the_study_shows_them():
    from unittest.mock import patch
    from potato.server_utils.schemas import geo_annotation
    scheme = {"name": "fields"}
    with patch("potato.server_utils.config_module.config", {}):
        assert geo_annotation._prediction_field(scheme) is None
    with patch("potato.server_utils.config_module.config",
               {"model_training": {"writeback": {"schemas": ["fields"], "field": "preds"}}}):
        assert geo_annotation._prediction_field(scheme) == "preds"
    with patch("potato.server_utils.config_module.config",
               {"pre_annotation": {"enabled": True}}):
        assert geo_annotation._prediction_field(scheme) == "predictions"


def test_a_pixel_is_point_geotiff_is_shifted_half_a_pixel(tmp_path):
    """With GTRasterTypeGeoKey = PixelIsPoint the tiepoint is the first
    pixel's centre, not its corner."""
    import numpy
    data = numpy.zeros((10, 10, 3), dtype="uint8")
    keys = [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 2, 2048, 0, 1, 4326]
    tifffile.imwrite(str(tmp_path / "p.tif"), data, photometric="rgb", extratags=[
        (33550, 12, 3, (0.1, 0.1, 0.0), False),
        (33922, 12, 6, (0.0, 0.0, 0.0, 10.0, 50.0, 0.0), False),
        (34735, 3, len(keys), tuple(keys), False)])
    _, georef = rasters.read_georef(str(tmp_path / "p.tif"))
    assert georef["transform"][2] == pytest.approx(9.95)
    assert georef["transform"][5] == pytest.approx(50.05)


def test_a_user_defined_crs_is_refused(tmp_path):
    import numpy
    keys = [1, 1, 0, 2, 1024, 0, 1, 1, 3072, 0, 1, 32767]
    tifffile.imwrite(str(tmp_path / "u.tif"), numpy.zeros((4, 4, 3), "uint8"),
                     photometric="rgb", extratags=[
                         (33550, 12, 3, (1.0, 1.0, 0.0), False),
                         (33922, 12, 6, (0, 0, 0, 500000.0, 4000000.0, 0), False),
                         (34735, 3, len(keys), tuple(keys), False)])
    with pytest.raises(ValueError, match="32767"):
        rasters.read_georef(str(tmp_path / "u.tif"))

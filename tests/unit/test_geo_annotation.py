"""
geo_annotation: GeoJSON normalisation, the draw-a-map overlap raster,
config validation (no external map unless configured), the generator and the
two exporters.
"""

import json
import logging
import os
import struct
import zlib

import numpy as np
import pytest

from potato.geo.geojson import (GeoJSONError, area_km2, normalize_feature_collection,
                                normalize_geometry, ring_signed_area)
from potato.geo.overlap import coverage, grid_features, make_grid, polygon_mask
from potato.geo.png import encode_png
from tests.helpers.test_utils import create_test_directory


def square(x0, y0, x1, y1, clockwise=False):
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return ring[::-1] if clockwise else ring


def poly(*rings):
    return {"type": "Polygon", "coordinates": list(rings)}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

class TestNormalise:
    def test_clockwise_exterior_is_rewound_counter_clockwise(self):
        g = normalize_geometry(poly(square(0, 0, 2, 2, clockwise=True)))
        assert ring_signed_area(g["coordinates"][0]) > 0
        assert g["coordinates"][0][0] == g["coordinates"][0][-1]

    def test_counter_clockwise_hole_is_rewound_clockwise(self):
        g = normalize_geometry(poly(square(0, 0, 4, 4), square(1, 1, 2, 2)))
        assert ring_signed_area(g["coordinates"][0]) > 0
        assert ring_signed_area(g["coordinates"][1]) < 0

    def test_open_ring_is_closed_and_repeats_dropped(self):
        g = normalize_geometry(poly([[0, 0], [1, 0], [1, 0], [1, 1], [0, 1]]))
        assert g["coordinates"][0] == [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]

    def test_ring_needs_three_distinct_positions(self):
        with pytest.raises(GeoJSONError, match="three distinct"):
            normalize_geometry(poly([[0, 0], [1, 1], [0, 0]]))

    def test_collinear_ring_is_refused(self):
        with pytest.raises(GeoJSONError, match="no area"):
            normalize_geometry(poly([[0, 0], [1, 1], [2, 2], [0, 0]]))

    def test_swapped_order_is_named_in_the_error(self):
        # Ann Arbor written [lat, lon]: lat 42.28 is fine as a longitude, but
        # -83.74 is outside -90..90 only by luck -- use a point that fails.
        with pytest.raises(GeoJSONError, match=r"\[latitude, longitude\]"):
            normalize_geometry({"type": "Point", "coordinates": [10.0, 120.0]})

    def test_latlon_input_is_swapped(self):
        g = normalize_geometry({"type": "Point", "coordinates": [42.28, -83.74]}, order="latlon")
        assert g["coordinates"] == [-83.74, 42.28]

    def test_out_of_range_is_refused(self):
        with pytest.raises(GeoJSONError, match="outside"):
            normalize_geometry({"type": "Point", "coordinates": [200.0, 95.0]})

    def test_non_numbers_and_nan_are_refused(self):
        with pytest.raises(GeoJSONError):
            normalize_geometry({"type": "Point", "coordinates": ["1", 2]})
        with pytest.raises(GeoJSONError):
            normalize_geometry({"type": "Point", "coordinates": [float("nan"), 2]})
        with pytest.raises(GeoJSONError):
            normalize_geometry({"type": "Point", "coordinates": [True, 2]})

    def test_rounding(self):
        g = normalize_geometry({"type": "Point", "coordinates": [1.123456789, 2.987654321]})
        assert g["coordinates"] == [1.1234568, 2.9876543]

    def test_accepts_feature_geometry_list_and_string(self):
        pt = {"type": "Point", "coordinates": [1, 2]}
        for obj in (pt, {"type": "Feature", "geometry": pt, "properties": {"label": "x"}},
                    [{"type": "Feature", "geometry": pt, "properties": None}], json.dumps(pt)):
            fc, _ = normalize_feature_collection(obj)
            assert fc["type"] == "FeatureCollection" and fc["features"][0]["geometry"] == pt

    def test_non_strict_drops_bad_features_and_says_why(self):
        good = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {}}
        bad = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [500, 2]}, "properties": {}}
        fc, warnings = normalize_feature_collection([good, bad], strict=False)
        assert len(fc["features"]) == 1 and "feature 1" in warnings[0]
        with pytest.raises(GeoJSONError, match="feature 1"):
            normalize_feature_collection([good, bad])

    def test_multipolygon_and_null_geometry(self):
        mp = {"type": "MultiPolygon", "coordinates": [[square(0, 0, 1, 1, True)], [square(2, 2, 3, 3, True)]]}
        g = normalize_geometry(mp)
        assert all(ring_signed_area(p[0]) > 0 for p in g["coordinates"])
        fc, _ = normalize_feature_collection({"type": "Feature", "geometry": None, "properties": {"region": "a"}})
        assert fc["features"][0]["geometry"] is None

    def test_area_of_one_degree_square_at_equator(self):
        # 1° x 1° at the equator: about 111.2 km x 110.6 km.
        assert 12300 < area_km2(poly(square(0, 0, 1, 1))) < 12400
        # Holes are subtracted.
        assert area_km2(poly(square(0, 0, 2, 2), square(0.5, 0.5, 1.5, 1.5))) == pytest.approx(
            area_km2(poly(square(0, 0, 2, 2))) - area_km2(poly(square(0.5, 0.5, 1.5, 1.5))), rel=1e-9)


# ---------------------------------------------------------------------------
# Overlap raster
# ---------------------------------------------------------------------------

class TestOverlap:
    def test_two_overlapping_squares_by_hand(self):
        # 4 x 4 grid of 1° cells over [0,4]x[0,4]; centres at .5, 1.5, 2.5, 3.5.
        grid = make_grid([0, 0, 4, 4], cell_size=1)
        counts = coverage({"ann": [poly(square(0, 0, 2, 2))], "bob": [poly(square(1, 1, 3, 3))]}, grid)
        expected = np.array([   # row 0 is the south edge
            [1, 1, 0, 0],
            [1, 2, 1, 0],
            [0, 1, 1, 0],
            [0, 0, 0, 0]])
        assert (counts == expected).all()
        cells = grid_features(counts, 2, grid)
        shares = {(c["properties"]["row"], c["properties"]["col"]): c["properties"]["share"] for c in cells}
        assert shares[(1, 1)] == 1.0 and shares[(0, 0)] == 0.5 and len(cells) == 7
        ring = next(c for c in cells if (c["properties"]["row"], c["properties"]["col"]) == (1, 1)) \
            ["geometry"]["coordinates"][0]
        assert ring == [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]] and ring_signed_area(ring) > 0

    def test_a_participant_counts_once_where_their_polygons_overlap(self):
        grid = make_grid([0, 0, 4, 4], cell_size=1)
        counts = coverage({"ann": [poly(square(0, 0, 2, 2)), poly(square(0, 0, 3, 3))]}, grid)
        assert counts.max() == 1 and counts.sum() == 9

    def test_holes_are_not_covered(self):
        grid = make_grid([0, 0, 4, 4], cell_size=1)
        mask = polygon_mask([square(0, 0, 4, 4), square(1, 1, 3, 3, clockwise=True)], grid)
        assert mask.sum() == 12 and not mask[1, 1] and not mask[2, 2]

    def test_self_intersecting_outline_fills_by_even_odd(self):
        # A bow-tie: two triangles meeting at (2, 2).
        grid = make_grid([0, 0, 4, 4], cell_size=0.5)
        mask = polygon_mask([[[0, 0], [4, 4], [4, 0], [0, 4], [0, 0]]], grid)
        assert mask[grid.ny // 2, 0] and mask[grid.ny // 2, -1]      # left and right lobes
        assert not mask[0, grid.nx // 2] and not mask[-1, grid.nx // 2]   # top and bottom are outside

    def test_vertex_on_a_row_of_centres_is_counted_once(self):
        # A diamond whose side vertices sit exactly on the centre row y = 2.5.
        grid = make_grid([0, 0, 5, 5], cell_size=1)
        mask = polygon_mask([[[2.5, 0.1], [4.9, 2.5], [2.5, 4.9], [0.1, 2.5], [2.5, 0.1]]], grid)
        assert mask[2].tolist() == [True, True, True, True, True]

    def test_cells_option_sets_the_longer_side(self):
        grid = make_grid([0, 0, 10, 5], cells=20)
        assert (grid.nx, grid.ny) == (20, 10) and grid.dx == 0.5

    def test_png_encoder_round_trips(self):
        img = np.zeros((3, 5, 4), np.uint8)
        img[..., 0] = 200
        img[..., 3] = 255
        data = encode_png(img)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = struct.unpack(">II", data[16:24])
        assert (w, h) == (5, 3)
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        raw = zlib.decompress(idat)
        assert len(raw) == 3 * (5 * 4 + 1) and raw[1] == 200


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def scheme(**kw):
    base = {"annotation_type": "geo_annotation", "name": "m", "description": "Map",
            "labels": ["A", "B"], "basemap": {"geojson": "maps/regions.geojson"}}
    base.update(kw)
    return {k: v for k, v in base.items() if v is not None}


def validate(s):
    from potato.server_utils.config_module import validate_single_annotation_scheme
    validate_single_annotation_scheme(s, "annotation_schemes[0]")


class TestValidation:
    def test_a_project_outline_is_enough(self):
        validate(scheme())

    def test_no_basemap_is_refused_and_says_nothing_is_fetched(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="loads no map from the internet"):
            validate(scheme(basemap=None))

    def test_external_tiles_need_attribution(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="attribution"):
            validate(scheme(basemap={"tiles": "https://tiles.example.org/{z}/{x}/{y}.png"}))
        validate(scheme(basemap={"tiles": "https://tiles.example.org/{z}/{x}/{y}.png", "attribution": "Example"}))
        validate(scheme(basemap={"tiles": "/tiles/{z}/{x}/{-y}.png"}))   # served by this host

    def test_tile_url_needs_placeholders_and_a_scheme(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match=r"\{z\}"):
            validate(scheme(basemap={"tiles": "https://tiles.example.org/map.png", "attribution": "x"}))
        with pytest.raises(ConfigValidationError, match="http"):
            validate(scheme(basemap={"tiles": "ftp://x/{z}/{x}/{y}.png", "attribution": "x"}))

    def test_osm_tiles_warn_about_the_usage_policy(self, caplog):
        with caplog.at_level(logging.WARNING):
            validate(scheme(basemap={"tiles": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                                     "attribution": "© OpenStreetMap contributors"}))
        assert "usage policy" in caplog.text

    def test_one_raster_only_and_image_needs_extent(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="not tiles and image"):
            validate(scheme(basemap={"tiles": "/t/{z}/{x}/{y}.png", "image": "/media/a.png",
                                     "extent": [0, 0, 1, 1]}))
        with pytest.raises(ConfigValidationError, match="extent"):
            validate(scheme(basemap={"image": "/media/a.png"}))
        with pytest.raises(ConfigValidationError, match="extent"):
            validate(scheme(basemap={"image": "/media/a.png", "extent": [1, 0, 0, 1]}))

    def test_outline_path_must_stay_in_the_project(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="inside the project"):
            validate(scheme(basemap={"geojson": "../../etc/regions.geojson"}))

    def test_unknown_basemap_key_and_bad_task(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="unknown keys"):
            validate(scheme(basemap={"geojson": "maps/r.geojson", "osm": True}))
        with pytest.raises(ConfigValidationError, match="task"):
            validate(scheme(task="paint"))

    def test_classify_region_needs_an_outline(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="classify_region needs region outlines"):
            validate(scheme(task="classify_region", basemap={"image": "/media/a.png", "extent": [0, 0, 1, 1]}))

    def test_yaml_boolean_labels_are_refused(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="booleans"):
            validate(scheme(labels=[True, False]))

    def test_tools_and_feature_counts(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="tools"):
            validate(scheme(tools=["circle"]))
        with pytest.raises(ConfigValidationError, match="draw only"):
            validate(scheme(task="pin", tools=["point"]))
        with pytest.raises(ConfigValidationError, match="exceed"):
            validate(scheme(min_features=3, max_features=2))


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

@pytest.fixture
def project(monkeypatch):
    work = create_test_directory("geo_annotation_unit")
    os.makedirs(os.path.join(work, "maps"), exist_ok=True)
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"code": "n", "name": "North {#1} {{x}}"},
         "geometry": poly(square(0, 1, 1, 2, clockwise=True))},
        {"type": "Feature", "properties": {"code": "s", "name": "South"},
         "geometry": poly(square(0, 0, 1, 1))}]}
    with open(os.path.join(work, "maps", "regions.geojson"), "w") as f:
        json.dump(fc, f)
    from potato.server_utils import config_module
    monkeypatch.setitem(config_module.config, "task_dir", work)
    return work


def _attr(html, name):
    import html as h
    import re
    m = re.search(name + r'="([^"]*)"', html)
    return json.loads(h.unescape(m.group(1))) if m else None


class TestGenerator:
    def test_outline_is_embedded_with_region_ids_and_no_external_url(self, project):
        from potato.server_utils.schemas.geo_annotation import generate_geo_annotation_layout
        html, keys = generate_geo_annotation_layout(scheme(basemap={
            "geojson": "maps/regions.geojson", "region_id_property": "code"}))
        assert 'data-annotation-type="geo_annotation"' in html
        outline = _attr(html, "data-geo-basemap")
        assert [f["id"] for f in outline["features"]] == ["n", "s"]
        assert ring_signed_area(outline["features"][0]["geometry"]["coordinates"][0]) > 0
        assert "http://" not in html and "https://" not in html
        cfg = _attr(html, "data-geo-config")
        assert cfg["basemap"] == {"region_id_property": "code"} and cfg["task"] == "draw"
        assert keys == []

    def test_braces_never_reach_jinja(self, project):
        from potato.server_utils.schemas.geo_annotation import generate_geo_annotation_layout
        html, _ = generate_geo_annotation_layout(scheme())
        assert "{#" not in html and "{{" not in html and "{%" not in html
        assert _attr(html, "data-geo-basemap")["features"][0]["properties"]["name"] == "North {#1} {{x}}"
        # And Jinja really renders it untouched.
        from jinja2 import Template
        assert Template(html).render() == html

    def test_tiles_appear_only_when_configured(self, project):
        from potato.server_utils.schemas.geo_annotation import generate_geo_annotation_layout
        url = "https://tiles.example.org/{z}/{x}/{y}.png"
        html, _ = generate_geo_annotation_layout(scheme(basemap={"tiles": url, "attribution": "Ex"}))
        assert _attr(html, "data-geo-config")["basemap"]["tiles"] == url

    def test_required_reaches_the_page(self, project):
        from potato.server_utils.schemas.geo_annotation import generate_geo_annotation_layout
        html, _ = generate_geo_annotation_layout(scheme(label_requirement={"required": True}))
        assert _attr(html, "data-geo-config")["required"] is True
        assert 'validation="required"' in html


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------

def _answer(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def _feat(geom, label, text=None, fid="f1"):
    props = {"label": label}
    if text is not None:
        props["text"] = text
    return {"type": "Feature", "id": fid, "geometry": geom, "properties": props}


@pytest.fixture
def context(project):
    from potato.export.base import ExportContext
    draw = scheme(name="areas", basemap={"geojson": "maps/regions.geojson", "region_id_property": "code"})
    regions = scheme(name="regions", task="classify_region",
                     basemap={"geojson": "maps/regions.geojson", "region_id_property": "code"})
    anns = [
        {"user_id": "ann", "instance_id": "i1", "labels": {
            "areas": {"areas": _answer(_feat(poly(square(0, 0, 0.5, 0.5, clockwise=True)), "A", "  Coast  Talk"))},
            "regions": {"regions": _answer({"type": "Feature", "geometry": None,
                                            "properties": {"region": "n", "label": "B"}})}}},
        {"user_id": "bob", "instance_id": "i1", "labels": {
            "areas": {"areas": _answer(_feat(poly(square(0.25, 0.25, 1, 1)), "A", "coast talk"),
                                       _feat({"type": "Point", "coordinates": [0.5, 1.5]}, "B", fid="f2"))},
            "regions": {"regions": _answer({"type": "Feature", "geometry": None,
                                            "properties": {"region": "n", "label": "B"}})}}},
    ]
    phase = [{"user_id": "cat", "phase": "survey", "page": "p1", "schema": "areas", "label_name": "areas",
              "value": _answer(_feat(poly(square(0, 0, 1, 1)), "A"))}]
    return ExportContext(config={"task_dir": project}, annotations=anns, items={"i1": {"id": "i1"}},
                         schemas=[draw, regions], output_dir=project, phase_responses=phase)


class TestExporters:
    def test_geojson_per_item_rewinds_and_joins_region_geometry(self, context):
        from potato.export.geo_exporter import GeoJSONExporter
        out = os.path.join(create_test_directory("geo_export_geojson"), "out")
        res = GeoJSONExporter().export(context, out)
        assert res.success, res.errors
        with open(os.path.join(out, "geojson", "i1.geojson")) as f:
            fc = json.load(f)
        ann = next(f for f in fc["features"] if f["properties"]["user_id"] == "ann"
                   and f["properties"]["schema"] == "areas")
        assert ring_signed_area(ann["geometry"]["coordinates"][0]) > 0, "clockwise input rewound on export"
        region = next(f for f in fc["features"] if f["properties"]["schema"] == "regions")
        assert region["geometry"]["type"] == "Polygon" and region["properties"]["region"] == "n"
        assert os.path.exists(os.path.join(out, "geojson", "survey-p1.geojson"))

    def test_geojson_single_file(self, context):
        from potato.export.geo_exporter import GeoJSONExporter
        out = os.path.join(create_test_directory("geo_export_single"), "out")
        res = GeoJSONExporter().export(context, out, {"layout": "single"})
        with open(res.files_written[0]) as f:
            fc = json.load(f)
        assert {f["properties"]["item_id"] for f in fc["features"]} == {"i1", "survey/p1"}
        assert len({f["id"] for f in fc["features"]}) == len(fc["features"])

    def test_overlap_shares_names_and_regions(self, context):
        import csv
        from potato.export.geo_exporter import GeoOverlapExporter
        out = os.path.join(create_test_directory("geo_export_overlap"), "out")
        res = GeoOverlapExporter().export(context, out, {"cell_size": "0.25", "extent": "0,0,1,1"})
        assert res.success, res.errors
        with open(os.path.join(out, "geo_overlap_summary.csv")) as f:
            rows = {(r["item_id"], r["group"]): r for r in csv.DictReader(f)}
        r = rows[("i1", "A")]
        assert r["respondents"] == "2" and r["grid"] == "4x4" and r["max_share"] == "1.0"
        with open(os.path.join(out, r["geojson"])) as f:
            cells = json.load(f)["features"]
        share = {(c["properties"]["row"], c["properties"]["col"]): c["properties"]["share"] for c in cells}
        # ann covers [0,.5]^2 (rows/cols 0-1), bob [.25,1]^2 (rows/cols 1-3).
        assert share[(1, 1)] == 1.0 and share[(0, 0)] == 0.5 and share[(3, 3)] == 0.5
        assert (0, 3) not in share
        assert open(os.path.join(out, r["png"]), "rb").read(8) == b"\x89PNG\r\n\x1a\n"
        with open(os.path.join(out, "geo_name_counts.csv")) as f:
            counts = list(csv.DictReader(f))
        coast = next(c for c in counts if c["normalised_text"] == "coast talk")
        assert coast["participants"] == "2"     # "  Coast  Talk" and "coast talk" are one name
        with open(os.path.join(out, "geo_regions.csv")) as f:
            regions = list(csv.DictReader(f))
        assert regions == [{"item_id": "i1", "schema": "regions", "region": "n", "region_name": "",
                            "label": "B", "count": "2", "respondents": "2", "share": "1.0"}]

    def test_overlap_by_name(self, context):
        import csv
        from potato.export.geo_exporter import GeoOverlapExporter
        out = os.path.join(create_test_directory("geo_export_by_name"), "out")
        GeoOverlapExporter().export(context, out, {"group_by": "text", "cells": "8"})
        with open(os.path.join(out, "geo_overlap_summary.csv")) as f:
            groups = {r["group"] for r in csv.DictReader(f) if r["item_id"] == "i1"}
        assert groups == {"coast talk"}

    def test_can_export_needs_a_geo_scheme(self):
        from potato.export.base import ExportContext
        from potato.export.geo_exporter import GeoJSONExporter
        ok, why = GeoJSONExporter().can_export(ExportContext(config={}, annotations=[{}], items={},
                                                             schemas=[{"annotation_type": "radio", "name": "x"}],
                                                             output_dir="."))
        assert not ok and "geo_annotation" in why


def test_validate_names_a_missing_basemap_file(tmp_path=None):
    from potato.server_utils.config_module import warn_about_unreadable_optional_files
    from tests.helpers.test_utils import create_test_directory
    d = create_test_directory("geo_missing_basemap")
    cfg = {"task_dir": ".", "annotation_schemes": [
        {"annotation_type": "geo_annotation", "name": "m", "basemap": {"geojson": "maps/none.geojson"}}]}
    msgs = warn_about_unreadable_optional_files(cfg, d)
    assert any("maps/none.geojson" in m for m in msgs)

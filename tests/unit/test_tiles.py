"""
Deep-zoom tile pyramids.

Most of this file is arithmetic, because a tile server is almost entirely
arithmetic and every bug in one is an off-by-one that renders correctly until
the last column. The properties here are the ones a viewer actually depends on:
that the tiles of a level tile the level exactly, that overlap is added only
where there is a neighbour, and that the descriptor agrees with the tiles it
describes.
"""

import json
import math
from pathlib import Path

import pytest

from potato.media import tiles
from potato.media.tiles import PyramidSpec, TileError

PIL = pytest.importorskip("PIL", reason="tile generation needs Pillow")


def spec(width=4000, height=3000, **kwargs):
    return PyramidSpec(width, height, **kwargs)


class TestLevels:
    def test_the_top_level_is_the_image_at_full_size(self):
        s = spec(4000, 3000)
        assert s.level_size(s.max_level) == (4000, 3000)

    def test_level_zero_is_one_pixel(self):
        """DZI numbers levels from 0 = smallest, not 0 = the image."""
        assert spec(4000, 3000).level_size(0) == (1, 1)

    def test_each_level_halves(self):
        s = spec(4000, 3000)
        assert s.level_size(s.max_level - 1) == (2000, 1500)
        assert s.level_size(s.max_level - 2) == (1000, 750)

    def test_odd_dimensions_round_up(self):
        """
        Rounding down loses the last row or column, which shows up as a sliver
        of missing image at one edge and only at some zoom levels.
        """
        s = spec(3, 3)
        assert s.level_size(s.max_level) == (3, 3)
        assert s.level_size(s.max_level - 1) == (2, 2)

    def test_a_one_pixel_image_has_one_level(self):
        s = spec(1, 1)
        assert s.max_level == 0
        assert s.levels == 1

    def test_a_zero_size_image_is_refused(self):
        with pytest.raises(TileError):
            spec(0, 100)


class TestTileGrid:
    def test_the_grid_covers_the_level(self):
        s = spec(4000, 3000, tile_size=254)
        columns, rows = s.grid(s.max_level)
        assert (columns - 1) * 254 < 4000 <= columns * 254
        assert (rows - 1) * 254 < 3000 <= rows * 254

    def test_tiles_tile_the_level_exactly(self):
        """
        Ignoring overlap, the tile bodies must partition the level with no gap
        and no double-cover. A gap is a stripe of missing image; an overlap in
        the *body* is content drawn twice and misaligned.
        """
        s = spec(1000, 700, tile_size=254, overlap=0)
        level = s.max_level
        width, height = s.level_size(level)
        covered = set()
        columns, rows = s.grid(level)
        for column in range(columns):
            for row in range(rows):
                left, top, right, bottom = s.tile_box(level, column, row)
                for x in range(left, right):
                    for y in range(top, bottom):
                        assert (x, y) not in covered, f"{x},{y} covered twice"
                        covered.add((x, y))
        assert len(covered) == width * height

    def test_overlap_is_added_only_where_there_is_a_neighbour(self):
        """
        An edge tile that included phantom overlap would be shifted by a pixel
        against its neighbours for the whole of that row.
        """
        s = spec(1000, 700, tile_size=254, overlap=1)
        level = s.max_level
        columns, rows = s.grid(level)

        left, top, _r, _b = s.tile_box(level, 0, 0)
        assert (left, top) == (0, 0)

        _l, _t, right, bottom = s.tile_box(level, columns - 1, rows - 1)
        assert (right, bottom) == s.level_size(level)

        inner_left, inner_top, _r, _b = s.tile_box(level, 1, 1)
        assert inner_left == 254 - 1
        assert inner_top == 254 - 1

    def test_a_tile_outside_the_grid_is_refused(self):
        s = spec(1000, 700)
        columns, rows = s.grid(s.max_level)
        with pytest.raises(TileError):
            s.tile_box(s.max_level, columns, 0)
        with pytest.raises(TileError):
            s.tile_box(s.max_level, 0, -1)

    def test_an_interior_tile_is_tile_size_plus_two_overlaps(self):
        s = spec(2000, 2000, tile_size=254, overlap=1)
        left, top, right, bottom = s.tile_box(s.max_level, 1, 1)
        assert (right - left, bottom - top) == (256, 256)


class TestDescriptor:
    def test_the_dzi_matches_the_spec(self):
        s = spec(4000, 3000, tile_size=254, overlap=1)
        xml = s.dzi()
        assert 'TileSize="254"' in xml
        assert 'Overlap="1"' in xml
        assert 'Width="4000"' in xml and 'Height="3000"' in xml

    def test_the_dzi_declares_the_format_the_tiles_use(self):
        """
        A descriptor that said jpg while the tiles were png renders correctly
        until the first tile request and then 404s across the whole image.
        """
        s = spec(100, 100, fmt="png")
        assert 'Format="png"' in s.dzi()

    def test_iiif_info_describes_the_same_pyramid(self):
        s = spec(4000, 3000)
        info = s.iiif_info("photos/x.tif", "http://host/media/iiif")
        assert info["width"] == 4000 and info["height"] == 3000
        assert info["tiles"][0]["width"] == s.tile_size
        # The scale factors are the DZI levels, named the IIIF way.
        assert 1 in info["tiles"][0]["scaleFactors"]
        assert len(info["sizes"]) == s.levels

    def test_iiif_info_is_json_serialisable(self):
        json.dumps(spec(100, 100).iiif_info("a", "http://h"))


class TestIIIFParsing:
    def test_region_full_and_square(self):
        s = spec(400, 200)
        assert tiles._iiif_region_box(s, "full") == (0, 0, 400, 200)
        assert tiles._iiif_region_box(s, "square") == (100, 0, 300, 200)

    def test_region_pixels_and_percent(self):
        s = spec(400, 200)
        assert tiles._iiif_region_box(s, "10,20,30,40") == (10, 20, 40, 60)
        assert tiles._iiif_region_box(s, "pct:50,50,50,50") == (200, 100, 400, 200)

    def test_region_is_clamped_to_the_image(self):
        s = spec(400, 200)
        assert tiles._iiif_region_box(s, "300,100,500,500") == (300, 100, 400, 200)

    def test_a_malformed_region_names_the_forms_that_work(self):
        with pytest.raises(TileError) as excinfo:
            tiles._iiif_region_box(spec(), "10,20")
        assert "pct:" in str(excinfo.value)

    def test_size_forms(self):
        assert tiles._iiif_size("max", 400, 200) == (400, 200)
        assert tiles._iiif_size("200,", 400, 200) == (200, 100)
        assert tiles._iiif_size(",50", 400, 200) == (100, 50)
        assert tiles._iiif_size("100,100", 400, 200) == (100, 100)
        assert tiles._iiif_size("pct:25", 400, 200) == (100, 50)

    def test_best_fit_keeps_the_aspect_ratio(self):
        """`!w,h` fits inside the box; `w,h` stretches to it. Different results."""
        assert tiles._iiif_size("!100,100", 400, 200) == (100, 50)
        assert tiles._iiif_size("100,100", 400, 200) == (100, 100)


class TestBuilding:
    @pytest.fixture
    def source(self, tmp_path):
        from PIL import Image, ImageDraw

        path = tmp_path / "grid.png"
        image = Image.new("RGB", (1200, 800), "white")
        draw = ImageDraw.Draw(image)
        for x in range(0, 1200, 100):
            draw.line([(x, 0), (x, 800)], fill="red", width=2)
        draw.rectangle([500, 300, 700, 500], fill="blue")
        image.save(path)
        return path

    def test_describe_reads_the_size_without_building_anything(self, source, tmp_path):
        s = tiles.describe(str(source))
        assert (s.width, s.height) == (1200, 800)
        assert not list(tmp_path.glob("*_files"))

    def test_a_level_builds_all_of_its_tiles_at_once(self, source, tmp_path):
        """
        Whole-level generation is the design: one decode per magnification
        rather than one per tile. A partial level would mean panning triggers a
        fresh decode every few hundred pixels.
        """
        s = tiles.describe(str(source))
        cache = tmp_path / "cache"
        directory = tiles.ensure_level(cache, source, s, s.max_level)
        columns, rows = s.grid(s.max_level)
        built = list(directory.glob(f"*.{s.format}"))
        assert len(built) == columns * rows

    def test_the_completion_marker_is_written_last(self, source, tmp_path):
        """
        A run interrupted halfway must rebuild, not serve a level with holes.
        """
        s = tiles.describe(str(source))
        cache = tmp_path / "cache"
        directory = tiles.ensure_level(cache, source, s, s.max_level)
        marker = directory / ".complete"
        assert marker.exists()
        columns, rows = s.grid(s.max_level)
        assert marker.read_text().strip() == f"{columns}x{rows}"

    def test_tiles_have_the_dimensions_the_spec_predicts(self, source, tmp_path):
        from PIL import Image

        s = tiles.describe(str(source))
        cache = tmp_path / "cache"
        level = s.max_level
        for column, row in ((0, 0), (1, 1)):
            path = tiles.tile_file(cache, source, s, level, column, row)
            left, top, right, bottom = s.tile_box(level, column, row)
            assert Image.open(path).size == (right - left, bottom - top)

    def test_a_second_call_does_not_rebuild(self, source, tmp_path):
        s = tiles.describe(str(source))
        cache = tmp_path / "cache"
        first = tiles.tile_file(cache, source, s, s.max_level, 0, 0)
        stamp = first.stat().st_mtime_ns
        again = tiles.tile_file(cache, source, s, s.max_level, 0, 0)
        assert again.stat().st_mtime_ns == stamp

    def test_the_pixel_ceiling_refuses_rather_than_downgrading(self, source, tmp_path):
        """
        Serving a lower level instead would let the annotator draw on a blurred
        approximation, producing coordinates nothing downstream can detect as
        wrong.
        """
        s = tiles.describe(str(source))
        with pytest.raises(TileError) as excinfo:
            tiles.ensure_level(tmp_path / "cache", source, s, s.max_level,
                               max_pixels=1000)
        message = str(excinfo.value)
        assert "max_pixels" in message
        assert "MP" in message

    def test_a_missing_source_says_so(self, tmp_path):
        with pytest.raises(TileError):
            tiles.describe(str(tmp_path / "absent.png"))

    def test_an_alpha_source_gets_png_tiles(self, tmp_path):
        from PIL import Image

        path = tmp_path / "alpha.png"
        Image.new("RGBA", (300, 200), (0, 0, 0, 0)).save(path)
        assert tiles.describe(str(path)).format == "png"

    def test_two_tile_sizes_do_not_share_a_cache_entry(self, source, tmp_path):
        cache = tmp_path / "cache"
        a = tiles.describe(str(source), tile_size=254)
        b = tiles.describe(str(source), tile_size=512)
        assert (tiles.tile_dir(cache, source, a, 5)
                != tiles.tile_dir(cache, source, b, 5))


class TestIIIFRendering:
    @pytest.fixture
    def source(self, tmp_path):
        from PIL import Image

        path = tmp_path / "flat.png"
        Image.new("RGB", (800, 600), "green").save(path)
        return path

    def test_a_full_request_returns_the_whole_image(self, source, tmp_path):
        from io import BytesIO

        from PIL import Image

        s = tiles.describe(str(source))
        payload, mimetype = tiles.iiif_region(
            tmp_path / "cache", source, s, "full", "max", "0", "default", "jpg")
        assert mimetype == "image/jpeg"
        assert Image.open(BytesIO(payload)).size == (800, 600)

    def test_a_sized_request_is_resampled(self, source, tmp_path):
        from io import BytesIO

        from PIL import Image

        s = tiles.describe(str(source))
        payload, _ = tiles.iiif_region(
            tmp_path / "cache", source, s, "full", "200,", "0", "default", "jpg")
        assert Image.open(BytesIO(payload)).size == (200, 150)

    def test_a_region_request_crops(self, source, tmp_path):
        from io import BytesIO

        from PIL import Image

        s = tiles.describe(str(source))
        payload, _ = tiles.iiif_region(
            tmp_path / "cache", source, s, "0,0,400,300", "max", "0",
            "default", "jpg")
        assert Image.open(BytesIO(payload)).size == (400, 300)

    def test_png_is_honoured(self, source, tmp_path):
        s = tiles.describe(str(source))
        _payload, mimetype = tiles.iiif_region(
            tmp_path / "cache", source, s, "full", "100,", "0", "default", "png")
        assert mimetype == "image/png"


class TestSchemaHelpers:
    def test_tiles_enabled(self):
        assert tiles.tiles_enabled({"viewer": "deepzoom"})
        assert not tiles.tiles_enabled({"viewer": "fabric"})
        assert not tiles.tiles_enabled({})

    def test_settings_default(self):
        settings = tiles.tile_settings({})
        assert settings["tile_size"] == tiles.DEFAULT_TILE_SIZE
        assert settings["overlap"] == tiles.DEFAULT_OVERLAP

    def test_an_explicit_zero_overlap_is_kept(self):
        """`or` would turn a deliberate 0 back into the default."""
        assert tiles.tile_settings({"tiles": {"overlap": 0}})["overlap"] == 0

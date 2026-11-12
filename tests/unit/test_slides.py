"""
Whole-slide images served from their own pyramid (potato/media/slides.py).

Uses the synthetic Aperio slide from examples/image/whole-slide, regenerated
into a test directory, and skips without openslide (the optional `wsi` extra).
"""

import importlib.util
from pathlib import Path

import pytest

from potato.media import slides
from potato.media.tiles import TileError

GENERATOR = Path("examples/image/whole-slide/generate_slide.py")


@pytest.fixture(scope="module")
def slide(tmp_path_factory):
    if not slides.openslide_available():
        pytest.skip("openslide is not installed (pip install potato-annotation[wsi])")
    pytest.importorskip("tifffile")
    spec = importlib.util.spec_from_file_location("generate_slide", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE = tmp_path_factory.mktemp("slide")
    module.main()
    yield module.HERE / "media" / "synthetic_tissue.svs"
    slides.close_all()


class TestDetection:
    def test_slide_extensions_are_slides(self, slide):
        assert slides.is_slide(str(slide))
        assert slides.is_slide("anything.ndpi")

    def test_a_flat_tiff_stays_on_the_pillow_path(self, tmp_path):
        if not slides.openslide_available():
            pytest.skip("openslide is not installed")
        from PIL import Image
        path = tmp_path / "flat.tif"
        Image.new("RGB", (64, 48), "white").save(path)
        assert not slides.is_slide(str(path))
        assert not slides.is_slide(str(tmp_path / "photo.png"))


class TestGeometry:
    def test_the_spec_matches_openslides_deep_zoom_at_every_level(self, slide):
        spec = slides.describe_slide(str(slide))
        assert (spec.width, spec.height) == (6144, 4096)
        assert slides._spec_matches_generator(str(slide), spec) is None
        odd = slides.describe_slide(str(slide), tile_size=510, overlap=2)
        assert slides._spec_matches_generator(str(slide), odd) is None

    def test_metadata_carries_the_scale(self, slide):
        meta = slides.slide_metadata(str(slide))
        assert meta["vendor"] == "aperio"
        assert meta["mpp_x"] == pytest.approx(0.25)
        assert meta["objective_power"] == pytest.approx(40)
        assert meta["levels"] == 3


class TestTiles:
    def test_a_tile_is_read_from_the_slide_and_cached(self, slide, tmp_path):
        from PIL import Image
        spec = slides.describe_slide(str(slide))
        path = slides.slide_tile(tmp_path, slide, spec, spec.max_level, 3, 2)
        with Image.open(path) as tile:
            left, top, right, bottom = spec.tile_box(spec.max_level, 3, 2)
            assert tile.size == (right - left, bottom - top)
        mtime = path.stat().st_mtime_ns
        assert slides.slide_tile(tmp_path, slide, spec, spec.max_level, 3, 2) == path
        assert path.stat().st_mtime_ns == mtime          # served from the cache

    def test_the_tile_shows_the_slide_at_that_place(self, slide, tmp_path):
        # A level-0-of-the-pyramid tile (the whole slide in one pixel-ish
        # thumbnail) and a full-resolution tile at the background corner.
        from PIL import Image
        spec = slides.describe_slide(str(slide))
        corner = slides.slide_tile(tmp_path, slide, spec, spec.max_level, 0, 0)
        with Image.open(corner) as tile:
            r, g, b = tile.convert("RGB").getpixel((2, 2))
            assert min(r, g, b) > 230                   # white background

    def test_out_of_range_tiles_are_refused(self, slide, tmp_path):
        spec = slides.describe_slide(str(slide))
        with pytest.raises(TileError):
            slides.slide_tile(tmp_path, slide, spec, spec.max_level, 999, 0)

    def test_iiif_reads_a_coarse_level_for_a_thumbnail(self, slide, tmp_path):
        from potato.media.tiles import iiif_region
        spec = slides.describe_slide(str(slide))
        payload, mimetype = iiif_region(tmp_path, slide, spec, "full", "!300,300", "0",
                                        "default", "jpg")
        assert mimetype == "image/jpeg"
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(payload)) as image:
            assert image.size == (300, 200)


class TestWithoutOpenslide:
    def test_the_refusal_names_the_extra(self, monkeypatch):
        import builtins
        real = builtins.__import__

        def no_openslide(name, *args, **kwargs):
            if name == "openslide" or name.startswith("openslide."):
                raise ImportError("No module named 'openslide'")
            return real(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", no_openslide)
        with pytest.raises(TileError, match=r"potato-annotation\[wsi\]"):
            slides.describe_slide(str(GENERATOR))
        assert slides.is_slide("x.svs")                  # still routed, then refused

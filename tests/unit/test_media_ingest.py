"""
Media ingest: 16-bit windowing, caching, and honest failures.

The behaviour worth pinning is not "it converts a TIFF" — it is that the
conversion is *legible*. Pillow's default 8-bit cast on a 16-bit image divides
by 256, so a scan whose structure lives between 1200 and 1800 renders as
uniform black and looks like a corrupt file rather than a windowing problem.
The percentile stretch is what makes the first view usable, and it is asserted
here by measuring the output's contrast, not by checking that a file appeared.

The cache tests cover the failure that a path-only key produces: a corrected
source image that keeps serving the old pixels, which every user diagnoses as a
browser cache problem and none as a server one.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from potato.media.cache import MediaCache, cache_key
from potato.media.images import (IMAGE_PASSTHROUGH, ImageTranscodeError,
                                 TRANSCODE_IMAGE_EXTENSIONS, describe_image,
                                 needs_transcode, transcode_image)
from potato.media.video import (TRANSCODE_VIDEO_EXTENSIONS, VIDEO_PASSTHROUGH,
                                VideoTranscodeError, conversion_hint,
                                ffmpeg_available, transcode_video)

PIL = pytest.importorskip("PIL")


@pytest.fixture
def sixteen_bit_tiff(tmp_path):
    """
    A 16-bit image whose real content occupies a narrow, high band.

    This is the shape of actual microscopy and medical data, and the case a
    naive `>> 8` conversion destroys.
    """
    from PIL import Image

    path = tmp_path / "scan.tif"
    image = Image.new("I;16", (64, 64), 1200)
    pixels = image.load()
    for y in range(20, 44):
        for x in range(20, 44):
            pixels[x, y] = 1800
    # One hot pixel, which is what makes a min/max stretch useless.
    pixels[0, 0] = 65535
    image.save(path)
    return path


@pytest.fixture
def multipage_tiff(tmp_path):
    from PIL import Image

    path = tmp_path / "stack.tif"
    pages = [Image.new("L", (32, 32), v) for v in (10, 120, 240)]
    pages[0].save(path, save_all=True, append_images=pages[1:])
    return path


class TestFormatClassification:
    def test_native_formats_are_not_transcoded(self):
        for suffix in (".jpg", ".png", ".webp"):
            assert suffix in IMAGE_PASSTHROUGH
            assert not needs_transcode(f"a{suffix}")

    def test_the_formats_researchers_actually_bring_are_covered(self):
        for suffix in (".tif", ".tiff", ".heic", ".dng", ".nef", ".cr2"):
            assert needs_transcode(f"a{suffix}"), f"{suffix} is not handled"

    def test_no_format_is_both_native_and_transcoded(self):
        """An overlap would make the behaviour depend on check order."""
        overlap = IMAGE_PASSTHROUGH & set(TRANSCODE_IMAGE_EXTENSIONS)
        assert not overlap, f"{overlap} is classified twice"

    def test_video_lists_do_not_overlap_either(self):
        overlap = VIDEO_PASSTHROUGH & set(TRANSCODE_VIDEO_EXTENSIONS)
        assert not overlap, f"{overlap} is classified twice"

    def test_case_is_ignored(self):
        assert needs_transcode("SCAN.TIF")


class TestSixteenBitWindowing:
    def test_a_16_bit_source_is_reported_as_high_depth(self, sixteen_bit_tiff):
        info = describe_image(str(sixteen_bit_tiff))
        assert info["high_depth"] is True
        assert info["value_max"] == 65535, "the hot pixel should be visible"

    def test_the_suggested_window_ignores_the_hot_pixel(self, sixteen_bit_tiff):
        """
        A single 65535 pixel is enough to push all real content into the
        bottom 3% of a min/max stretch, rendering the image black.
        """
        info = describe_image(str(sixteen_bit_tiff))
        assert info["suggested_window"]["max"] < 65535

    def test_the_default_render_is_legible_not_black(self, sixteen_bit_tiff,
                                                     tmp_path):
        """
        The whole point. A naive cast divides by 256, so 1200 and 1800 become
        4 and 7 -- a difference of 3 levels out of 255, which is invisible.
        """
        from PIL import Image

        out = tmp_path / "out.webp"
        transcode_image(str(sixteen_bit_tiff), str(out))
        with Image.open(out) as rendered:
            low, high = rendered.convert("L").getextrema()
        assert high - low > 100, (
            f"rendered contrast is only {high - low} levels; a naive 8-bit "
            f"cast would give about 3, and the image would look empty")

    def test_an_explicit_window_is_honoured(self, sixteen_bit_tiff, tmp_path):
        from PIL import Image

        out = tmp_path / "windowed.webp"
        result = transcode_image(str(sixteen_bit_tiff), str(out),
                                 window_min=1200, window_max=1800)
        assert result["window"]["min"] == 1200
        with Image.open(out) as rendered:
            low, high = rendered.convert("L").getextrema()
        assert low <= 5, "the 1200 background should map to near-black"
        assert high >= 250, "the 1800 signal should map to near-white"

    def test_gamma_changes_the_midtones(self, sixteen_bit_tiff, tmp_path):
        from PIL import Image

        def mean(path):
            with Image.open(path) as img:
                data = list(img.convert("L").getdata())
            return sum(data) / len(data)

        plain = tmp_path / "plain.webp"
        gamma = tmp_path / "gamma.webp"
        transcode_image(str(sixteen_bit_tiff), str(plain),
                        window_min=1000, window_max=2000, gamma=1.0)
        transcode_image(str(sixteen_bit_tiff), str(gamma),
                        window_min=1000, window_max=2000, gamma=2.2)
        assert mean(gamma) > mean(plain), "gamma > 1 should brighten midtones"

    def test_an_8_bit_source_needs_no_window(self, tmp_path):
        from PIL import Image

        path = tmp_path / "plain.tif"
        Image.new("RGB", (16, 16), (10, 200, 30)).save(path)
        result = transcode_image(str(path), str(tmp_path / "o.webp"))
        assert result["window"] is None


class TestMultiPage:
    def test_the_page_count_is_reported(self, multipage_tiff):
        assert describe_image(str(multipage_tiff))["pages"] == 3

    def test_a_specific_page_can_be_rendered(self, multipage_tiff, tmp_path):
        """
        Silently showing page 0 would present a 40-slice stack as one image and
        lose the rest without saying anything.
        """
        from PIL import Image

        means = []
        for page in (0, 1, 2):
            out = tmp_path / f"p{page}.webp"
            transcode_image(str(multipage_tiff), str(out), page=page)
            with Image.open(out) as img:
                data = list(img.convert("L").getdata())
            means.append(sum(data) / len(data))
        assert means[0] < means[1] < means[2], "pages differ, so renders must"

    def test_asking_for_a_page_that_is_not_there_says_so(self, multipage_tiff,
                                                        tmp_path):
        with pytest.raises(ImageTranscodeError, match="no page 9"):
            transcode_image(str(multipage_tiff), str(tmp_path / "x.webp"),
                            page=9)


class TestDownscaling:
    def test_max_pixels_preserves_aspect(self, tmp_path):
        from PIL import Image

        path = tmp_path / "big.tif"
        Image.new("RGB", (400, 200)).save(path)
        out = tmp_path / "small.webp"
        result = transcode_image(str(path), str(out), max_pixels=10_000)
        assert result["width"] * result["height"] <= 11_000
        assert abs(result["width"] / result["height"] - 2.0) < 0.05


class TestCacheKeys:
    def test_the_same_inputs_give_the_same_key(self, tmp_path):
        path = tmp_path / "a.tif"
        path.write_bytes(b"x" * 100)
        assert cache_key(path, ".webp") == cache_key(path, ".webp")

    def test_editing_the_source_changes_the_key(self, tmp_path):
        """
        A path-only key serves the OLD pixels after the source is corrected,
        which everyone diagnoses as a browser cache problem.
        """
        path = tmp_path / "a.tif"
        path.write_bytes(b"x" * 100)
        before = cache_key(path, ".webp")
        time.sleep(1.05)  # mtime has one-second resolution on some filesystems
        path.write_bytes(b"y" * 200)
        assert cache_key(path, ".webp") != before

    def test_different_windows_get_different_entries(self, tmp_path):
        path = tmp_path / "a.tif"
        path.write_bytes(b"x")
        assert (cache_key(path, ".webp", window_min=0)
                != cache_key(path, ".webp", window_min=100))

    def test_different_suffixes_get_different_entries(self, tmp_path):
        path = tmp_path / "a.mov"
        path.write_bytes(b"x")
        assert cache_key(path, ".webm") != cache_key(path, ".webp")


class TestCacheEviction:
    def test_it_prunes_to_the_limit(self, tmp_path):
        cache = MediaCache(str(tmp_path), max_bytes=300)
        cache.ensure_dir()
        for i in range(5):
            entry = cache.root / f"e{i}.webp"
            entry.write_bytes(b"x" * 100)
            # Distinct atimes so "least recently used" is well defined.
            import os

            os.utime(entry, (1_000_000 + i, 1_000_000 + i))
        removed = cache.prune()
        assert removed >= 2
        assert cache.total_bytes() <= 300

    def test_it_evicts_the_least_recently_used_first(self, tmp_path):
        import os

        cache = MediaCache(str(tmp_path), max_bytes=250)
        cache.ensure_dir()
        for i in range(4):
            entry = cache.root / f"e{i}.webp"
            entry.write_bytes(b"x" * 100)
            os.utime(entry, (1_000_000 + i, 1_000_000 + i))
        cache.prune()
        remaining = sorted(p.name for p in cache.root.iterdir())
        assert "e0.webp" not in remaining, "oldest should go first"
        assert "e3.webp" in remaining, "newest should survive"

    def test_a_cache_under_the_limit_is_untouched(self, tmp_path):
        cache = MediaCache(str(tmp_path), max_bytes=10_000)
        cache.ensure_dir()
        (cache.root / "e.webp").write_bytes(b"x" * 100)
        assert cache.prune() == 0

    def test_concurrent_requests_share_one_lock_per_entry(self, tmp_path):
        cache = MediaCache(str(tmp_path))
        path = cache.path_for(Path("a.tif"), ".webp")
        assert cache.lock_for(path) is cache.lock_for(path)
        other = cache.path_for(Path("b.tif"), ".webp")
        assert cache.lock_for(path) is not cache.lock_for(other), (
            "one global lock would serialize every unrelated transcode")

    def test_a_zero_byte_entry_is_not_a_hit(self, tmp_path):
        """A killed transcode must not leave a 'valid' empty cache entry."""
        cache = MediaCache(str(tmp_path))
        cache.ensure_dir()
        source = tmp_path / "a.tif"
        source.write_bytes(b"x")
        cache.path_for(source, ".webp").write_bytes(b"")
        assert cache.get(source, ".webp") is None


class TestHonestFailures:
    def test_a_missing_file_says_so(self, tmp_path):
        with pytest.raises(ImageTranscodeError, match="does not exist"):
            transcode_image(str(tmp_path / "nope.tif"), str(tmp_path / "o.webp"))

    def test_the_ffmpeg_hint_is_copy_pasteable(self):
        hint = conversion_hint("clip.mov")
        assert hint.startswith("ffmpeg -i clip.mov")
        assert "libvpx-vp9" in hint

    @pytest.mark.skipif(ffmpeg_available(), reason="ffmpeg is installed here")
    def test_missing_ffmpeg_gives_the_command_not_a_stack_trace(self, tmp_path):
        source = tmp_path / "clip.mov"
        source.write_bytes(b"not really a video")
        with pytest.raises(VideoTranscodeError) as excinfo:
            transcode_video(str(source), str(tmp_path / "out.webm"))
        assert "ffmpeg -i" in str(excinfo.value), (
            "the error must carry the command to run, not just name the gap")

    def test_every_transcodable_video_extension_explains_why(self):
        for suffix, reason in TRANSCODE_VIDEO_EXTENSIONS.items():
            assert reason, f"{suffix} has no stated reason"

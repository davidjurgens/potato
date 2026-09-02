"""
Depth maps: readers, windowing, colour, and unprojection.

The failure mode this file exists to catch is not "it crashed" — depth
pipelines rarely crash. They produce a picture that looks like depth and is
wrong: mirrored vertically, in the wrong unit, with holes rendered as surfaces,
or unprojected into a scene that is upside down. Each of those is asserted
against a value computed by hand rather than against the code's own output.
"""

import math
import struct
from array import array
from pathlib import Path

import pytest

from potato.media.depth import (COLORMAPS, DEFAULT_DEPTH_SCALE, DepthError,
                                DepthMap, colorize, describe, detect_format,
                                from_wire, percentile_window, pixel_of,
                                read_depth, sample_colormap, to_wire,
                                unproject)

np = pytest.importorskip("numpy")


def depth_from(rows):
    """A DepthMap from a list of rows, NaN allowed."""
    flat = array("f", [v for row in rows for v in row])
    return DepthMap(values=flat, width=len(rows[0]), height=len(rows))


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

class TestNumpy:
    def test_reads_a_float_array_as_metres(self, tmp_path):
        path = tmp_path / "d.npy"
        np.save(path, np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32))

        depth = read_depth(path)
        assert (depth.width, depth.height) == (2, 2)
        assert list(depth.values) == [1.0, 2.0, 3.0, 4.0]
        assert depth.scale == 1.0

    def test_zero_becomes_a_non_measurement(self, tmp_path):
        """
        Zero is the near-universal "no return" code. Read as depth it paints a
        surface across every hole in the sensor's coverage.
        """
        path = tmp_path / "d.npy"
        np.save(path, np.array([[0.0, 2.0]], dtype=np.float32))

        depth = read_depth(path)
        assert math.isnan(depth.values[0])
        assert depth.values[1] == 2.0

    def test_a_channel_axis_is_stripped_but_a_row_axis_is_not(self, tmp_path):
        """
        `np.squeeze` would do both, and collapsing the row axis made a
        single-row depth map — a laser profile, a cropped strip — fail as
        "not 2-D".
        """
        channelled = tmp_path / "c.npy"
        np.save(channelled, np.ones((2, 3, 1), dtype=np.float32))
        assert (read_depth(channelled).width,
                read_depth(channelled).height) == (3, 2)

        one_row = tmp_path / "r.npy"
        np.save(one_row, np.array([[1.0, 2.0, 3.0]], dtype=np.float32))
        depth = read_depth(one_row)
        assert (depth.width, depth.height) == (3, 1)

    def test_rejects_an_array_that_is_not_a_grid(self, tmp_path):
        path = tmp_path / "d.npy"
        np.save(path, np.zeros((5,), dtype=np.float32))
        with pytest.raises(DepthError, match="2-D"):
            read_depth(path)

    def test_reads_the_first_array_of_an_npz(self, tmp_path):
        path = tmp_path / "d.npz"
        np.savez(path, depth=np.array([[5.0, 6.0]], dtype=np.float32))
        assert list(read_depth(path).values) == [5.0, 6.0]


class TestPfm:
    def _write(self, path, rows, scale=-1.0):
        height = len(rows)
        width = len(rows[0])
        flat = [v for row in rows for v in row]
        endian = "<" if scale < 0 else ">"
        with open(path, "wb") as fh:
            fh.write(b"Pf\n")
            fh.write(f"{width} {height}\n".encode())
            fh.write(f"{scale}\n".encode())
            fh.write(struct.pack(f"{endian}{len(flat)}f", *flat))

    def test_rows_are_flipped_back_to_top_down(self, tmp_path):
        """
        PFM stores rows bottom-up. Missing that gives a vertically mirrored
        depth map, which looks entirely plausible and unprojects into a scene
        that is upside down for no visible reason.
        """
        path = tmp_path / "d.pfm"
        # Written bottom-up: the file's first row is the image's LAST row.
        self._write(path, [[9.0, 9.0], [1.0, 1.0]])

        depth = read_depth(path)
        assert list(depth.values) == [1.0, 1.0, 9.0, 9.0]

    def test_positive_scale_means_big_endian(self, tmp_path):
        path = tmp_path / "d.pfm"
        self._write(path, [[1.5, 2.5]], scale=1.0)
        assert list(read_depth(path).values) == [1.5, 2.5]

    def test_a_truncated_file_says_so(self, tmp_path):
        path = tmp_path / "d.pfm"
        path.write_bytes(b"Pf\n2 2\n-1.0\n" + b"\x00" * 4)
        with pytest.raises(DepthError, match="truncated"):
            read_depth(path)

    def test_comments_in_the_header_are_skipped(self, tmp_path):
        path = tmp_path / "d.pfm"
        with open(path, "wb") as fh:
            fh.write(b"Pf\n# written by a tool\n1 1\n-1.0\n")
            fh.write(struct.pack("<f", 3.25))
        assert list(read_depth(path).values) == [3.25]


class TestRaster:
    def test_a_16_bit_png_uses_the_millimetre_default(self, tmp_path):
        Image = pytest.importorskip("PIL.Image")
        path = tmp_path / "d.png"
        # 1500 and 3000 stored units -> 1.5 m and 3.0 m at 1/1000.
        img = Image.new("I;16", (2, 1))
        img.putdata([1500, 3000])
        img.save(path)

        depth = read_depth(path)
        assert depth.scale == DEFAULT_DEPTH_SCALE
        assert list(depth.values) == pytest.approx([1.5, 3.0])

    def test_an_explicit_scale_overrides_the_default(self, tmp_path):
        """KITTI stores 1/256 m, and the file does not say so."""
        Image = pytest.importorskip("PIL.Image")
        path = tmp_path / "d.png"
        img = Image.new("I;16", (1, 1))
        img.putdata([2560])
        img.save(path)

        depth = read_depth(path, scale=1 / 256)
        assert list(depth.values) == pytest.approx([10.0])

    def test_a_colour_image_is_refused_with_a_reason(self, tmp_path):
        Image = pytest.importorskip("PIL.Image")
        path = tmp_path / "rgb.png"
        Image.new("RGB", (2, 2), (10, 20, 30)).save(path)

        with pytest.raises(DepthError, match="colour image"):
            read_depth(path)


class TestDetection:
    def test_content_beats_extension(self, tmp_path):
        Image = pytest.importorskip("PIL.Image")
        path = tmp_path / "depth.dat"
        Image.new("I;16", (1, 1)).save(path, format="PNG")
        assert detect_format(path) == "png"

    def test_an_unknown_format_lists_what_is_supported(self, tmp_path):
        path = tmp_path / "d.xyz"
        path.write_bytes(b"nonsense")
        with pytest.raises(DepthError, match="Supported"):
            detect_format(path)


# ---------------------------------------------------------------------------
# Windowing and description
# ---------------------------------------------------------------------------

class TestWindow:
    def test_invalid_pixels_do_not_enter_the_percentiles(self):
        nan = float("nan")
        depth = depth_from([[nan, nan, 5.0, 6.0, 7.0]])
        low, high = percentile_window(depth)
        assert low >= 5.0
        assert high <= 7.0

    def test_describe_reports_the_hole_fraction(self):
        # A stereo rig on a textureless wall really does return 80% holes, and
        # an annotator who cannot see that reads the holes as geometry.
        nan = float("nan")
        depth = depth_from([[nan, nan, nan, nan, 2.0]])
        info = describe(depth)
        assert info["invalid_fraction"] == pytest.approx(0.8)

    def test_an_entirely_invalid_map_says_what_to_check(self):
        nan = float("nan")
        info = describe(depth_from([[nan, nan]]))
        assert info["invalid_fraction"] == 1.0
        assert "depth_scale" in info["note"]

    def test_a_flat_map_still_yields_a_usable_window(self):
        low, high = percentile_window(depth_from([[2.0, 2.0, 2.0]]))
        assert high > low


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------

class TestColour:
    def test_every_colormap_spans_its_stops(self):
        for name in COLORMAPS:
            assert sample_colormap(name, 0.0) == COLORMAPS[name][0][1]
            assert sample_colormap(name, 1.0) == COLORMAPS[name][-1][1]

    def test_out_of_range_positions_clamp(self):
        assert sample_colormap("turbo", -5) == sample_colormap("turbo", 0.0)
        assert sample_colormap("turbo", 5) == sample_colormap("turbo", 1.0)

    def test_an_unknown_map_falls_back_rather_than_raising(self):
        assert sample_colormap("nope", 0.5) == sample_colormap("turbo", 0.5)

    def test_invalid_pixels_get_a_colour_no_map_produces(self):
        # Painting a hole black or white makes it indistinguishable from real
        # near or far depth, which is the whole reason it is magenta.
        nan = float("nan")
        rgb = colorize(depth_from([[nan, 1.0, 2.0]]), window=(1.0, 2.0))
        assert tuple(rgb[0:3]) == (255, 0, 220)
        for name in COLORMAPS:
            for i in range(256):
                assert sample_colormap(name, i / 255) != (255, 0, 220)

    def test_near_and_far_map_to_the_ends_of_the_ramp(self):
        rgb = colorize(depth_from([[1.0, 5.0]]), window=(1.0, 5.0),
                       colormap="gray")
        assert tuple(rgb[0:3]) == (0, 0, 0)
        assert tuple(rgb[3:6]) == (255, 255, 255)

    def test_invert_swaps_them(self):
        rgb = colorize(depth_from([[1.0, 5.0]]), window=(1.0, 5.0),
                       colormap="gray", invert=True)
        assert tuple(rgb[0:3]) == (255, 255, 255)

    def test_values_outside_the_window_saturate_rather_than_wrap(self):
        rgb = colorize(depth_from([[0.1, 99.0]]), window=(1.0, 5.0),
                       colormap="gray")
        assert tuple(rgb[0:3]) == (0, 0, 0)
        assert tuple(rgb[3:6]) == (255, 255, 255)


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

class TestWire:
    def test_round_trips_including_the_holes(self):
        nan = float("nan")
        depth = depth_from([[1.0, nan], [3.0, 4.0]])
        header, back = from_wire(to_wire(depth))

        assert header["width"] == 2 and header["height"] == 2
        assert header["units"] == "m"
        assert back.values[0] == 1.0
        assert math.isnan(back.values[1])
        assert back.values[3] == 4.0

    def test_rejects_a_buffer_that_is_not_dpt1(self):
        with pytest.raises(DepthError, match="not a DPT1"):
            from_wire(b"PNT1" + struct.pack("<I", 2) + b"{}")


# ---------------------------------------------------------------------------
# Unprojection
# ---------------------------------------------------------------------------

class TestUnproject:
    def test_the_principal_point_maps_to_the_optical_axis(self):
        """A pixel at (cx, cy) has no lateral offset at any depth."""
        depth = depth_from([[0.0, 0.0, 0.0],
                            [0.0, 4.0, 0.0],
                            [0.0, 0.0, 0.0]])
        cloud = unproject(depth, (100.0, 100.0, 1.0, 1.0), frame="camera")
        assert cloud.count == 1
        assert list(cloud.positions) == pytest.approx([0.0, 0.0, 4.0])

    def test_offsets_scale_with_depth_and_inverse_focal_length(self):
        depth = depth_from([[2.0]])
        # Pixel (0, 0) with cx = cy = 10, fx = fy = 5, z = 2:
        #   x = (0 - 10) * 2 / 5 = -4;  y = -4
        cloud = unproject(depth, (5.0, 5.0, 10.0, 10.0), frame="camera")
        assert list(cloud.positions) == pytest.approx([-4.0, -4.0, 2.0])

    def test_z_up_puts_forward_on_x_and_up_on_z(self):
        """
        The optical frame has Y pointing DOWN. A missing sign here puts the sky
        underground, and every fitted box height comes out negative.
        """
        depth = depth_from([[2.0]])
        cloud = unproject(depth, (5.0, 5.0, 10.0, 10.0), frame="z_up")
        x, y, z = list(cloud.positions)
        assert x == pytest.approx(2.0), "forward becomes X"
        assert y == pytest.approx(4.0), "a pixel left of centre becomes +Y"
        assert z == pytest.approx(4.0), "a pixel above centre becomes +Z"

    def test_a_pixel_below_centre_is_below_the_camera(self):
        depth = depth_from([[0.0], [3.0]])          # row 1, below cy = 0
        cloud = unproject(depth, (5.0, 5.0, 0.0, 0.0), frame="z_up")
        _x, _y, z = list(cloud.positions)
        assert z < 0

    def test_holes_produce_no_points(self):
        nan = float("nan")
        depth = depth_from([[nan, 1.0, 0.0]])
        assert unproject(depth, (1.0, 1.0, 0.0, 0.0)).count == 1

    def test_points_carry_their_pixel_index(self):
        # This is what makes a segment_3d drawn on the unprojected cloud map
        # back to pixels in the source image.
        depth = depth_from([[1.0, 1.0], [1.0, 1.0]])
        cloud = unproject(depth, (1.0, 1.0, 0.0, 0.0))
        assert list(cloud.indices) == [0, 1, 2, 3]
        assert pixel_of(depth, 3) == (1, 1)

    def test_stride_subsamples_both_axes(self):
        depth = depth_from([[1.0] * 4 for _ in range(4)])
        assert unproject(depth, (1.0, 1.0, 0.0, 0.0), stride=2).count == 4

    def test_max_points_stops_rather_than_growing_without_bound(self):
        depth = depth_from([[1.0] * 10 for _ in range(10)])
        assert unproject(depth, (1.0, 1.0, 0.0, 0.0), max_points=7).count == 7

    def test_a_zero_focal_length_is_refused(self):
        with pytest.raises(DepthError, match="focal length"):
            unproject(depth_from([[1.0]]), (0.0, 1.0, 0.0, 0.0))

    def test_an_extrinsic_matrix_overrides_the_axis_permutation(self):
        depth = depth_from([[3.0]])
        identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        cloud = unproject(depth, (1.0, 1.0, 0.0, 0.0), extrinsic=identity)
        # Identity means the camera frame, untouched.
        assert list(cloud.positions) == pytest.approx([0.0, 0.0, 3.0])

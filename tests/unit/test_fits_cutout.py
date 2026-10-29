"""fits_cutout: the FITS converter (cutouts, scaling, WCS JSON, limits and
errors), the PNG cache and its route, light-curve parsing, and the display's
option validation and rendering.

The FITS fixtures are written here with astropy: small images with a
minimal TAN WCS and a source at a known pixel.
"""

import html as html_module
import json
import math
import os
import re
import struct
import subprocess
import sys
import zlib
from unittest.mock import patch

import pytest

np = pytest.importorskip("numpy")
fits = pytest.importorskip("astropy.io.fits")
from astropy.wcs import WCS  # noqa: E402

from potato.science import astro  # noqa: E402
from potato.science.converters import ConverterUnavailable, converter_for, known_extensions  # noqa: E402
from potato.science.converters.fits import (FitsError, fits_cutout, parse_center,  # noqa: E402
                                            parse_size)
from potato.server_utils.displays.fits_cutout_display import FitsCutoutDisplay  # noqa: E402
from potato.server_utils.displays.registry import display_registry  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RA0, DEC0 = 150.0, 2.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def tan_wcs(nx=100, ny=80, scale_arcsec=1.0, ra=RA0, dec=DEC0, rot_deg=0.0, shift=(0, 0)):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [nx / 2 + 0.5 + shift[0], ny / 2 + 0.5 + shift[1]]
    s = scale_arcsec / 3600.0
    t = math.radians(rot_deg)
    w.wcs.cd = [[-s * math.cos(t), s * math.sin(t)], [s * math.sin(t), s * math.cos(t)]]
    return w


def image(nx=100, ny=80, spot=None, value=1000.0):
    """Flat 10.0 background, with ``value`` at FITS pixel ``spot`` (1-based)."""
    data = np.full((ny, nx), 10.0, dtype=np.float32)
    if spot:
        data[spot[1] - 1, spot[0] - 1] = value
    return data


def write(path, data, w=None, extra_hdus=(), primary_empty=False, header_extra=None):
    hdr = w.to_header() if w is not None else fits.Header()
    for k, v in (header_extra or {}).items():
        hdr[k] = v
    if primary_empty:
        hdus = [fits.PrimaryHDU(), fits.ImageHDU(data, header=hdr, name="SCI")]
    else:
        hdus = [fits.PrimaryHDU(data, header=hdr)]
    fits.HDUList(hdus + list(extra_hdus)).writeto(path, overwrite=True)
    return path


@pytest.fixture
def tmp():
    return create_test_directory("fits_cutout_unit")


def decode_png(blob):
    """(height, width, 4) uint8 for the RGBA PNGs the converter writes."""
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(blob):
        n = struct.unpack(">I", blob[pos:pos + 4])[0]
        tag, data = blob[pos + 4:pos + 8], blob[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", data[:8])
            assert data[8:10] == b"\x08\x06"
        elif tag == b"IDAT":
            idat += data
        pos += 12 + n
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(h, w * 4 + 1)
    assert (raw[:, 0] == 0).all()
    return raw[:, 1:].reshape(h, w, 4)


def sky_from_grid(wcs_json, u, v):
    """The browser's interpolation (fits-cutout.js skyAt), in Python."""
    g = wcs_json["grid"]
    xyz = np.array(g["xyz"]).reshape(g["ny"], g["nx"], 3)
    gx, gy = (g["nx"] - 1) * u, (g["ny"] - 1) * (1 - v)
    i0, j0 = min(g["nx"] - 2, int(gx)), min(g["ny"] - 2, int(gy))
    fx, fy = gx - i0, gy - j0
    p = ((1 - fx) * (1 - fy) * xyz[j0, i0] + fx * (1 - fy) * xyz[j0, i0 + 1]
         + (1 - fx) * fy * xyz[j0 + 1, i0] + fx * fy * xyz[j0 + 1, i0 + 1])
    p = p / np.linalg.norm(p)
    return math.degrees(math.atan2(p[1], p[0])) % 360, math.degrees(math.asin(p[2]))


def pixel_from_screen(wcs_json, meta, u, v):
    """fits-cutout.js pixelAt: screen fraction -> FITS (1-based) pixel."""
    o = wcs_json["origin"]
    return (o["x0"] + u * meta["width"] * o["step"] + 0.5,
            o["y0"] + (1 - v) * meta["height"] * o["step"] + 0.5)


def sep_arcsec(a, b):
    """Haversine: acos(cos) cannot resolve angles below ~3 mas in float64."""
    d1, d2 = math.radians(a[1]), math.radians(b[1])
    dra, ddec = math.radians(a[0] - b[0]), d2 - d1
    h = math.sin(ddec / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin(dra / 2) ** 2
    return math.degrees(2 * math.asin(math.sqrt(min(1.0, h)))) * 3600


# ---------------------------------------------------------------------------
# Option parsing
# ---------------------------------------------------------------------------

class TestParsing:
    @pytest.mark.parametrize("value,expected", [
        (64, ("px", 64.0)), ("64", ("px", 64.0)), ("64 px", ("px", 64.0)),
        ("30 arcsec", ("deg", 30 / 3600)), ('30"', ("deg", 30 / 3600)),
        ("1.5 arcmin", ("deg", 1.5 / 60)), ("0.01 deg", ("deg", 0.01)), (None, None),
    ])
    def test_size(self, value, expected):
        got = parse_size(value)
        assert got == expected if got is None else (got[0] == expected[0]
                                                    and abs(got[1] - expected[1]) < 1e-12)

    @pytest.mark.parametrize("value", [0, -3, "big", "30 parsec", True])
    def test_size_rejects(self, value):
        with pytest.raises(ValueError):
            parse_size(value)

    def test_center_sexagesimal(self):
        c = parse_center({"ra": "10:00:28.6", "dec": "-02:12:21"})
        assert abs(c["ra"] - (10 + 28.6 / 3600) * 15) < 1e-9
        assert abs(c["dec"] - -(2 + 12 / 60 + 21 / 3600)) < 1e-9
        assert parse_center({"x": 10, "y": 4.5}) == {"x": 10.0, "y": 4.5}

    @pytest.mark.parametrize("value", [{"ra": 1}, {"x": 1, "ra": 2, "dec": 3}, {"dec": 95, "ra": 0},
                                       {"x": "a", "y": 1}, [1, 2]])
    def test_center_rejects(self, value):
        with pytest.raises(ValueError):
            parse_center(value)


# ---------------------------------------------------------------------------
# The converter
# ---------------------------------------------------------------------------

class TestCutout:
    def test_registered_for_every_fits_extension(self):
        for ext in (".fits", ".fit", ".fts", ".fits.gz"):
            assert ext in known_extensions()
            assert converter_for("a/b/c" + ext.upper()) is fits_cutout
        assert converter_for("x.fits.fz") is None

    def test_pixel_position_is_fits_convention_and_north_is_up(self, tmp):
        # A bright pixel at FITS (40, 30): the 9 x 9 cutout around it has it
        # dead centre, and the PNG's top row is the image's highest y.
        p = write(os.path.join(tmp, "spot.fits"), image(spot=(40, 30)), tan_wcs())
        r = fits_cutout(p, center={"x": 40, "y": 30}, size=9, interval="minmax")
        assert r["meta"]["region"] == {"x0": 36, "y0": 26, "x1": 44, "y1": 34, "step": 1}
        px = decode_png(r["png"])
        assert px.shape == (9, 9, 4)
        assert np.unravel_index(px[..., 0].argmax(), px.shape[:2]) == (4, 4)
        assert px[4, 4, 0] == 255 and px[0, 0, 0] == 0

        p2 = write(os.path.join(tmp, "high.fits"), image(spot=(40, 34)), tan_wcs())
        px = decode_png(fits_cutout(p2, center={"x": 40, "y": 30}, size=9, interval="minmax")["png"])
        # y = 34 is the top row of a cutout spanning y 26..34.
        assert np.unravel_index(px[..., 0].argmax(), px.shape[:2]) == (0, 4)

    def test_sky_position_and_grid_agree_with_astropy(self, tmp):
        w = tan_wcs(rot_deg=25.0, scale_arcsec=0.7)
        p = write(os.path.join(tmp, "rot.fits"), image(), w)
        target = w.all_pix2world([[61.0 - 1, 33.0 - 1]], 0)[0]      # FITS (61, 33)
        r = fits_cutout(p, center={"ra": float(target[0]), "dec": float(target[1])}, size=21)
        assert r["meta"]["region"] == {"x0": 51, "y0": 23, "x1": 71, "y1": 43, "step": 1}
        wj, meta = r["wcs"], r["meta"]
        assert wj["axes"] == ["RA", "Dec"] and wj["sexagesimal"] and wj["frame"] == "icrs"
        assert abs(wj["pixel_scale_arcsec"][0] - 0.7) < 1e-6
        assert sep_arcsec(wj["center"], target) < 1e-3
        # The browser's readout at arbitrary points: pixel mapping and sky
        # interpolation both match astropy to well under a milliarcsecond.
        for u, v in ((0.5, 0.5), (0.13, 0.77), (0.99, 0.02), (0.0, 1.0)):
            x, y = pixel_from_screen(wj, meta, u, v)
            truth = w.all_pix2world([[x - 1, y - 1]], 0)[0]
            assert sep_arcsec(sky_from_grid(wj, u, v), truth) < 1e-3, (u, v)
        # Linear WCS of the cutout: CRPIX moved onto the cutout's grid.
        assert abs(wj["crpix"][0] - (w.wcs.crpix[0] - 50)) < 1e-9
        assert abs(wj["crpix"][1] - (w.wcs.crpix[1] - 22)) < 1e-9
        assert np.allclose(wj["cd"], w.wcs.cd)

    def test_north_and_east_follow_the_rotation(self, tmp):
        p = write(os.path.join(tmp, "n.fits"), image(), tan_wcs())
        wj = fits_cutout(p, center={"x": 50, "y": 40}, size=20)["wcs"]
        assert np.allclose(wj["north"], [0, -1], atol=1e-4)   # up on screen
        assert np.allclose(wj["east"], [-1, 0], atol=1e-4)    # left (CDELT1 < 0)
        p = write(os.path.join(tmp, "r.fits"), image(), tan_wcs(rot_deg=90))
        wj = fits_cutout(p, center={"x": 50, "y": 40}, size=20)["wcs"]
        assert abs(abs(wj["north"][0]) - 1) < 1e-3 and abs(wj["north"][1]) < 1e-3

    def test_ra_wraparound_grid(self, tmp):
        # A cutout straddling RA 0/360: interpolating unit vectors keeps the
        # readout continuous where interpolating RA would jump by 180 degrees.
        w = tan_wcs(ra=0.0, dec=10.0, scale_arcsec=2.0)
        p = write(os.path.join(tmp, "wrap.fits"), image(), w)
        r = fits_cutout(p, center={"x": 50.5, "y": 40.5}, size=40)
        x, y = pixel_from_screen(r["wcs"], r["meta"], 0.3, 0.4)
        truth = w.all_pix2world([[x - 1, y - 1]], 0)[0]
        assert sep_arcsec(sky_from_grid(r["wcs"], 0.3, 0.4), truth) < 1e-3

    def test_angular_size(self, tmp):
        p = write(os.path.join(tmp, "a.fits"), image(), tan_wcs(scale_arcsec=0.5))
        r = fits_cutout(p, center={"x": 50, "y": 40}, size="10 arcsec")
        assert (r["meta"]["width"], r["meta"]["height"]) == (20, 20)

    def test_partial_overlap_is_transparent(self, tmp):
        p = write(os.path.join(tmp, "edge.fits"), image(), tan_wcs())
        r = fits_cutout(p, center={"x": 1, "y": 1}, size=10)
        px = decode_png(r["png"])
        # Left columns and bottom rows (x, y < 1) are off the image.
        assert px[0, 9, 3] == 255 and px[9, 0, 3] == 0 and px[0, 0, 3] == 0
        assert any("edge" in n for n in r["meta"]["notes"])

    def test_nan_pixels_are_transparent(self, tmp):
        data = image()
        data[39, 49] = np.nan                          # FITS (50, 40)
        p = write(os.path.join(tmp, "nan.fits"), data, tan_wcs())
        px = decode_png(fits_cutout(p, center={"x": 50, "y": 40}, size=3)["png"])
        assert px[1, 1, 3] == 0 and px[0, 0, 3] == 255

    def test_blank_keyword_in_integer_images(self, tmp):
        data = np.full((20, 20), 100, dtype=np.int16)
        data[10, 10] = -32768
        hdu = fits.PrimaryHDU(data)
        hdu.header["BLANK"] = -32768
        p = os.path.join(tmp, "blank.fits")
        hdu.writeto(p, overwrite=True)
        px = decode_png(fits_cutout(p, center={"x": 11, "y": 11}, size=3)["png"])
        assert px[1, 1, 3] == 0 and px[0, 1, 3] == 255

    def test_unsigned_16_bit_images(self, tmp):
        # uint16 is stored as int16 with BZERO = 32768; a memory-mapped read
        # refuses scaled data, so this needs astropy's default open.
        data = np.full((20, 20), 40000, dtype=np.uint16)
        data[5, 5] = 65000
        p = os.path.join(tmp, "u16.fits")
        fits.PrimaryHDU(data).writeto(p, overwrite=True)
        r = fits_cutout(p, center={"x": 6, "y": 6}, size=3, interval="minmax")
        assert r["meta"]["limits"] == [40000.0, 65000.0]
        assert decode_png(r["png"])[1, 1, 0] == 255

    def test_stretches_and_intervals_differ(self, tmp):
        data = np.linspace(0, 1000, 64 * 64, dtype=np.float32).reshape(64, 64)
        p = write(os.path.join(tmp, "ramp.fits"), data, tan_wcs(64, 64))
        mid = {}
        for st in ("linear", "sqrt", "log", "asinh"):
            r = fits_cutout(p, stretch=st, interval="minmax")
            mid[st] = int(decode_png(r["png"])[32, 32, 0])     # a mid-grey pixel
        assert abs(mid["linear"] - 127) <= 2
        assert mid["sqrt"] > mid["linear"] and mid["log"] > mid["linear"]
        assert mid["asinh"] > mid["linear"]
        lim = fits_cutout(p, interval="percentile", percentile=90)["meta"]["limits"]
        assert 40 < lim[0] < 60 and 940 < lim[1] < 960
        inv = decode_png(fits_cutout(p, interval="minmax", invert=True)["png"])
        assert abs(int(inv[32, 32, 0]) - (255 - mid["linear"])) <= 1

    def test_zscale_ignores_one_hot_pixel(self, tmp):
        rng = np.random.default_rng(1)
        data = (100 + rng.normal(0, 5, (50, 50))).astype(np.float32)
        data[25, 25] = 1e6
        p = write(os.path.join(tmp, "hot.fits"), data)
        z = fits_cutout(p, interval="zscale")["meta"]["limits"]
        m = fits_cutout(p, interval="minmax")["meta"]["limits"]
        assert z[1] < 200 and m[1] == 1e6

    def test_primary_without_data_is_skipped_and_hdu_by_name(self, tmp):
        p = write(os.path.join(tmp, "ext.fits"), image(), tan_wcs(), primary_empty=True)
        r = fits_cutout(p, center={"x": 5, "y": 5}, size=4)
        assert (r["meta"]["hdu"], r["meta"]["hdu_name"]) == (1, "SCI")
        assert fits_cutout(p, center={"x": 5, "y": 5}, size=4, hdu="SCI")["meta"]["hdu"] == 1
        with pytest.raises(FitsError, match="not a 2-D"):
            fits_cutout(p, hdu=0)
        with pytest.raises(FitsError, match="no HDU 'NOPE'"):
            fits_cutout(p, hdu="NOPE")

    def test_file_without_image_hdu(self, tmp):
        table = fits.BinTableHDU.from_columns([fits.Column(name="mag", format="E", array=[1.0, 2.0])],
                                              name="EVENTS")
        p = os.path.join(tmp, "table.fits")
        fits.HDUList([fits.PrimaryHDU(), table]).writeto(p, overwrite=True)
        with pytest.raises(FitsError) as e:
            fits_cutout(p)
        msg = str(e.value)
        assert "no image HDU" in msg and "0 PRIMARY (no data)" in msg and "1 EVENTS (table)" in msg

    def test_not_fits(self, tmp):
        p = os.path.join(tmp, "fake.fits")
        with open(p, "w") as f:
            f.write("hello, not a FITS file\n" * 20)
        with pytest.raises(FitsError, match="not a readable FITS file"):
            fits_cutout(p)

    def test_file_size_limit(self, tmp):
        p = write(os.path.join(tmp, "big.fits"), image(), tan_wcs())
        with pytest.raises(FitsError, match="max_file_mb"):
            fits_cutout(p, max_file_bytes=1000)

    def test_whole_image_pixel_limit(self, tmp):
        p = write(os.path.join(tmp, "whole.fits"), image(), tan_wcs())
        with pytest.raises(FitsError, match="max_image_pixels"):
            fits_cutout(p, max_image_pixels=100 * 80 - 1)
        assert fits_cutout(p, max_image_pixels=100 * 80)["meta"]["width"] == 100

    def test_whole_image_is_block_averaged_down(self, tmp):
        data = np.arange(64 * 40, dtype=np.float32).reshape(40, 64)
        p = write(os.path.join(tmp, "down.fits"), data, tan_wcs(64, 40))
        r = fits_cutout(p, max_output_side=16)
        assert r["meta"]["region"]["step"] == 4
        assert (r["meta"]["width"], r["meta"]["height"]) == (16, 10)
        # The grid accounts for the block size.
        w = tan_wcs(64, 40)
        x, y = pixel_from_screen(r["wcs"], r["meta"], 0.25, 0.6)
        truth = w.all_pix2world([[x - 1, y - 1]], 0)[0]
        assert sep_arcsec(sky_from_grid(r["wcs"], 0.25, 0.6), truth) < 1e-3

    def test_position_off_the_image(self, tmp):
        p = write(os.path.join(tmp, "off.fits"), image(), tan_wcs())
        with pytest.raises(FitsError, match="outside"):
            fits_cutout(p, center={"x": 500, "y": 40}, size=10)
        with pytest.raises(FitsError, match="outside"):
            fits_cutout(p, center={"ra": RA0 + 1.0, "dec": DEC0}, size=10)

    def test_sky_position_needs_a_wcs(self, tmp):
        p = write(os.path.join(tmp, "nowcs.fits"), image())
        with pytest.raises(FitsError, match="no celestial WCS"):
            fits_cutout(p, center={"ra": RA0, "dec": DEC0}, size=10)
        r = fits_cutout(p, center={"x": 10, "y": 10}, size=5)
        assert r["wcs"] is None

    def test_size_needs_a_position(self, tmp):
        p = write(os.path.join(tmp, "s.fits"), image(), tan_wcs())
        with pytest.raises(FitsError, match="without a position"):
            fits_cutout(p, size=10)

    def test_cube_shows_first_plane(self, tmp):
        cube = np.zeros((3, 20, 20), dtype=np.float32)
        cube[0, 10, 10] = 50.0
        cube[1] = 99.0
        p = os.path.join(tmp, "cube.fits")
        fits.PrimaryHDU(cube).writeto(p, overwrite=True)
        r = fits_cutout(p, center={"x": 11, "y": 11}, size=3, interval="minmax")
        assert decode_png(r["png"])[1, 1, 0] == 255
        assert any("first plane" in n for n in r["meta"]["notes"])

    def test_gzipped(self, tmp):
        p = write(os.path.join(tmp, "z.fits.gz"), image(spot=(20, 20)), tan_wcs())
        r = converter_for(p)(p, center={"x": 20, "y": 20}, size=5, interval="minmax")
        assert decode_png(r["png"])[2, 2, 0] == 255

    def test_galactic_wcs_labels_l_and_b(self, tmp):
        w = WCS(naxis=2)
        w.wcs.ctype = ["GLON-TAN", "GLAT-TAN"]
        w.wcs.crval = [30.0, 0.5]
        w.wcs.crpix = [50, 40]
        w.wcs.cdelt = [-1 / 3600, 1 / 3600]
        p = write(os.path.join(tmp, "gal.fits"), image(), w)
        wj = fits_cutout(p, center={"x": 50, "y": 40}, size=10)["wcs"]
        assert wj["axes"] == ["l", "b"] and not wj["sexagesimal"] and wj["frame"] == "galactic"
        # An ICRS ra/dec is transformed into the galactic frame to find it.
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        icrs = SkyCoord(30.0 * u.deg, 0.5 * u.deg, frame="galactic").icrs
        r = fits_cutout(p, center={"ra": icrs.ra.deg, "dec": icrs.dec.deg}, size=11)
        assert r["meta"]["region"]["x0"] == 45 and r["meta"]["region"]["y0"] == 35

    def test_missing_astropy_names_the_extra(self, tmp, monkeypatch):
        p = write(os.path.join(tmp, "m.fits"), image(), tan_wcs())
        monkeypatch.setitem(sys.modules, "astropy.io", None)
        with pytest.raises(ConverterUnavailable, match=r"potato-annotation\[astro\]"):
            fits_cutout(p)

    def test_header_values_in_meta(self, tmp):
        p = write(os.path.join(tmp, "h.fits"), image(), tan_wcs(),
                  header_extra={"MJD-OBS": 60000.5, "FILTER": "r", "OBJECT": "SN x"})
        meta = fits_cutout(p, center={"x": 5, "y": 5}, size=3)["meta"]
        assert (meta["mjd_obs"], meta["filter"], meta["object"]) == (60000.5, "r", "SN x")


# ---------------------------------------------------------------------------
# Cache and route
# ---------------------------------------------------------------------------

class TestCache:
    def test_converted_once_and_again_when_the_file_changes(self, tmp):
        p = write(os.path.join(tmp, "c.fits"), image(), tan_wcs())
        cfg = {"task_dir": tmp}
        params = {"center": {"x": 10, "y": 10}, "size": 5}
        calls = []
        real = fits_cutout

        def counting(*a, **k):
            calls.append(1)
            return real(*a, **k)
        with patch("potato.science.converters.converter_for", lambda path: counting):
            first = astro.cutout(cfg, p, params)
            second = astro.cutout(cfg, p, params)
            assert len(calls) == 1 and first["src"] == second["src"]
            assert first["src"] == f"/science/fits/{first['key']}.png"
            assert os.path.isfile(os.path.join(tmp, ".potato_cache", "fits", first["key"] + ".png"))
            other = astro.cutout(cfg, p, dict(params, stretch="log"))
            assert other["key"] != first["key"] and len(calls) == 2
            st = os.stat(p)
            os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
            assert astro.cutout(cfg, p, params)["key"] != first["key"] and len(calls) == 3

    def test_cache_is_pruned(self, tmp):
        p = write(os.path.join(tmp, "prune.fits"), image(), tan_wcs())
        cfg = {"task_dir": tmp}
        keys = []
        for n in range(4):
            keys.append(astro.cutout(cfg, p, {"center": {"x": 10 + n, "y": 10}, "size": 3})["key"])
        astro._prune(astro.cache_dir(cfg), keep=2)
        left = sorted(f[:-5] for f in os.listdir(astro.cache_dir(cfg)) if f.endswith(".json"))
        assert len(left) == 2 and set(left) <= set(keys)

    def test_route_serves_only_cached_keys(self, tmp):
        from flask import Flask
        p = write(os.path.join(tmp, "r.fits"), image(), tan_wcs())
        cfg = {"task_dir": tmp}
        key = astro.cutout(cfg, p, {"center": {"x": 10, "y": 10}, "size": 3})["key"]
        app = Flask("fits_route_test")
        astro.register_astro_routes(app, cfg)
        with patch.object(astro, "live_config", lambda: cfg):
            client = app.test_client()
            ok = client.get(f"/science/fits/{key}.png")
            assert ok.status_code == 200 and ok.mimetype == "image/png"
            assert ok.data[:8] == b"\x89PNG\r\n\x1a\n"
            assert client.get("/science/fits/" + "0" * 32 + ".png").status_code == 404
            assert client.get("/science/fits/..%2F..%2Fr.png").status_code == 404
            assert client.get(f"/science/fits/{key[:-1]}X.png").status_code == 404


# ---------------------------------------------------------------------------
# Light curves
# ---------------------------------------------------------------------------

class TestLightCurve:
    def test_csv_bands_detections_and_limits(self, tmp):
        p = os.path.join(tmp, "lc.csv")
        with open(p, "w") as f:
            f.write("# a comment\nmjd,band,mag,magerr,limit\n"
                    "60000.1,r,19.5,0.05,\n60001.2,g,19.9,0.08,\n"
                    "60002.0,r,,,21.0\n60003.0,r,19.2,0.04,\nbad,r,1,1,\n")
        lc = astro.read_light_curve(p)
        assert [b["name"] for b in lc["bands"]] == ["g", "r"]     # g before r
        r = lc["bands"][1]
        assert r["t"] == [60000.1, 60003.0] and r["y"] == [19.5, 19.2] and r["err"] == [0.05, 0.04]
        assert r["limit_t"] == [60002.0] and r["limit_y"] == [21.0]
        assert lc["points"] == 4 and lc["skipped"] == 1

    def test_configured_columns_and_json(self, tmp):
        p = os.path.join(tmp, "lc.json")
        with open(p, "w") as f:
            json.dump([{"jd": 1.0, "flux": 5.0, "e": 0.5}, {"jd": 2.0, "flux": 6.0, "e": 0.4}], f)
        lc = astro.read_light_curve(p, {"time": "jd", "mag": "flux", "err": "e"})
        assert lc["bands"][0]["name"] == "all" and lc["bands"][0]["err"] == [0.5, 0.4]
        with pytest.raises(ValueError, match="no 'mjd' column"):
            astro.read_light_curve(p, {"time": "mjd"})

    def test_size_limit(self, tmp):
        p = os.path.join(tmp, "huge.csv")
        with open(p, "w") as f:
            f.write("mjd,mag\n")
        with patch.object(astro, "MAX_LIGHT_CURVE_BYTES", 4):
            with pytest.raises(ValueError, match="over the"):
                astro.read_light_curve(p)

    def test_no_time_column(self):
        with pytest.raises(ValueError, match="no time column"):
            astro.light_curve_from_rows([{"when": 1, "mag": 2}])


# ---------------------------------------------------------------------------
# The display
# ---------------------------------------------------------------------------

@pytest.fixture
def media():
    root = create_test_directory("fits_cutout_display")
    media = os.path.join(root, "media")
    os.makedirs(media, exist_ok=True)
    w = tan_wcs()
    for name in ("sci", "ref", "diff"):
        write(os.path.join(media, name + ".fits"), image(spot=(50, 40)), w,
              header_extra={"MJD-OBS": 60002.5})
    # The same sky on a pixel grid shifted by (4, 3) pixels.
    write(os.path.join(media, "other.fits"), image(), tan_wcs(shift=(4, 3)))
    with open(os.path.join(media, "lc.csv"), "w") as f:
        f.write("mjd,band,mag,magerr\n60001,g,19,0.1\n60003,g,18.8,0.1\n")
    with open(os.path.join(media, "notes.txt"), "w") as f:
        f.write("not an image")
    with patch.dict("potato.server_utils.config_module.config",
                    {"task_dir": root, "media_directory": "media"}):
        yield media


def _cfg(page):
    m = re.search(r"data-viewer-config='([^']*)'", page)
    return json.loads(html_module.unescape(m.group(1)))


def _render(value, **options):
    return display_registry.render("fits_cutout", {"key": "cand", "type": "fits_cutout",
                                                   "display_options": options}, value)


class TestDisplay:
    def test_triplet_with_light_curve(self, media):
        page = _render({"science": "sci.fits", "reference": "ref.fits", "difference": "diff.fits",
                        "x": 50, "y": 40, "size": 11, "light_curve": "lc.csv"})
        cfg = _cfg(page)
        assert [p["label"] for p in cfg["panels"]] == ["Science", "Reference", "Difference"]
        assert all(p["src"].startswith("/science/fits/") for p in cfg["panels"])
        assert cfg["aligned"] is True
        assert cfg["panels"][0]["meta"]["region"]["x0"] == 45
        assert cfg["lightCurve"]["bands"][0]["y"] == [19.0, 18.8]
        assert cfg["lightCurve"]["epoch"] == 60002.5            # MJD-OBS of the science image
        assert 'data-viewer-kind="fits_cutout"' in page and "fc-lightcurve" in page
        # The points are in the page as a table too.
        assert "<td>60001.000</td><td>g</td><td>19.000</td>" in page

    def test_single_path_and_precedence(self, media):
        cfg = _cfg(_render("sci.fits", stretch="log"))
        assert len(cfg["panels"]) == 1 and cfg["panels"][0]["meta"]["stretch"] == "log"
        cfg = _cfg(display_registry.render("fits_cutout", {
            "key": "c", "type": "fits_cutout", "display_options": {
                "stretch": "sqrt",
                "panels": [{"key": "science", "stretch": "log"}, {"key": "reference"},
                           {"key": "difference"}]}},
            {"science": "sci.fits", "reference": "ref.fits",
             "difference": {"path": "diff.fits", "stretch": "asinh"}, "interval": "minmax"}))
        stretches = [p["meta"]["stretch"] for p in cfg["panels"]]
        assert stretches == ["log", "sqrt", "asinh"]
        assert {p["meta"]["interval"] for p in cfg["panels"]} == {"minmax"}

    def test_one_bad_panel_does_not_hide_the_others(self, media):
        cfg = _cfg(_render({"science": "sci.fits", "reference": "missing.fits",
                            "difference": "notes.txt", "x": 50, "y": 40}))
        sci, ref, diff = cfg["panels"]
        assert sci["src"] and "src" not in ref and "src" not in diff
        assert "not in the media directory" in ref["error"]
        assert "not a FITS file" in diff["error"]

    def test_paths_outside_media_are_refused(self, media):
        cfg = _cfg(_render({"science": "../../../etc/passwd"}))
        assert "src" not in cfg["panels"][0] and cfg["panels"][0]["error"]
        cfg = _cfg(_render({"science": "https://example.org/a.fits"}))
        assert "remote" in cfg["panels"][0]["error"]

    def test_unaligned_panels_are_flagged(self, media):
        cfg = _cfg(_render({"science": "sci.fits", "reference": "other.fits",
                            "ra": RA0, "dec": DEC0, "size": 9}))
        assert cfg["aligned"] is True     # cut around one sky position: the same sky
        assert cfg["panels"][1]["meta"]["region"]["x0"] == cfg["panels"][0]["meta"]["region"]["x0"] + 4
        cfg = _cfg(_render({"science": "sci.fits", "reference": "other.fits",
                            "x": 50, "y": 40, "size": 9}))
        assert cfg["aligned"] is False    # the same pixels, 5 arcsec apart on the sky

    def test_bad_item_values_render_a_message(self, media):
        page = _render({"science": "sci.fits", "stretch": "rainbow"})
        assert "pv-failed" in page and "rainbow" in html_module.unescape(page)
        page = _render(None)
        assert "pv-failed" in page and "names no FITS file" in html_module.unescape(page)

    def test_light_curve_error_keeps_the_cutouts(self, media):
        cfg = _cfg(_render({"science": "sci.fits", "light_curve": "nope.csv"}))
        assert cfg["panels"][0]["src"] and "cannot be drawn" in cfg["lightCurveError"]

    @pytest.mark.parametrize("options,needle", [
        ({"stretch": "rainbow"}, "stretch 'rainbow'"),
        ({"interval": "mad"}, "interval 'mad'"),
        ({"percentile": 0}, "percentile"),
        ({"size": "3 parsec"}, ".size"),
        ({"panels": [{"key": "science"}, {"key": "science"}]}, "repeats"),
        ({"panels": [{"key": "science", "colour": "red"}]}, "unknown key(s) colour"),
        ({"allow_remote": True}, "remote files are not supported"),
        ({"light_curve_units": "jansky"}, "light_curve_units"),
        ({"light_curve_columns": {"when": "mjd"}}, "unknown role(s) when"),
        ({"max_file_mb": 0}, "max_file_mb"),
    ])
    def test_validate_options(self, options, needle):
        from potato.server_utils.displays.viewer_display import validate_viewer_field
        field = {"key": "c", "type": "fits_cutout", "display_options": options}
        errors = validate_viewer_field(field, "instance_display.fields[0]", check_bundles=False)
        assert any(needle in e for e in errors), errors

    def test_valid_options_pass(self):
        from potato.server_utils.displays.viewer_display import validate_viewer_field
        field = {"key": "c", "type": "fits_cutout", "display_options": {
            "size": "30 arcsec", "stretch": "asinh", "interval": "percentile", "percentile": 99,
            "panels": [{"key": "science", "label": "New", "invert": True}],
            "light_curve_columns": {"time": "mjd"}}}
        assert validate_viewer_field(field, "f", check_bundles=False) == []

    def test_missing_astropy_is_a_config_error(self):
        from potato.server_utils.displays.viewer_display import validate_viewer_field
        with patch("potato.science.converters.fits.astropy_available", lambda: False):
            errors = validate_viewer_field({"key": "c", "type": "fits_cutout"}, "f",
                                           check_bundles=False)
        assert any("potato-annotation[astro]" in e for e in errors)

    def test_config_load_rejects_a_bad_option(self):
        import copy
        from potato.server_utils.config_module import (ConfigValidationError,
                                                       load_and_validate_config,
                                                       validate_instance_display_config)
        path = os.path.join(REPO, "examples", "image", "astronomy-real-bogus", "config.yaml")
        cfg = load_and_validate_config(path, REPO)          # the example loads
        bad = copy.deepcopy(cfg)
        bad["instance_display"]["fields"][1]["display_options"]["stretch"] = "rainbow"
        with pytest.raises(ConfigValidationError, match="stretch 'rainbow'"):
            validate_instance_display_config(bad)


def test_boot_does_not_import_astropy():
    code = ("import sys; import potato.server_utils.displays.registry; "
            "import potato.science.astro; import potato.science.converters; "
            "print('astropy' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_example_files_are_what_the_generator_writes():
    """The committed example data: every FITS file opens with a celestial WCS
    and every item's position falls on its images."""
    base = os.path.join(REPO, "examples", "image", "astronomy-real-bogus")
    items = json.load(open(os.path.join(base, "data", "candidates.json")))
    assert len(items) == 4
    for item in items:
        c = item["candidate"]
        for key in ("science", "reference", "difference"):
            path = c[key]["path"] if isinstance(c[key], dict) else c[key]
            center = ({"ra": c["ra"], "dec": c["dec"]} if "ra" in c else {"x": c["x"], "y": c["y"]})
            r = fits_cutout(os.path.join(base, "media", path), center=center, size=c["size"])
            assert r["wcs"] is not None and r["meta"]["notes"] == []
        assert os.path.isfile(os.path.join(base, "media", c["light_curve"]))

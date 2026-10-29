"""Spectra: JCAMP-DX / CSV / mzML reading, downsampling, integration, peak
suggestions, the spectrum display, the peak_picking scheme and the peak-table
exporter.

The fixtures in tests/data/spectra/ are written by make_fixtures.py, whose
JCAMP-DX encoder is separate from the reader, so a decode is checked against
the values that were encoded rather than against itself.
"""

import html as html_module
import importlib.util
import json
import os
import re
import sys
from unittest.mock import patch

import numpy as np
import pytest

from potato.science.converters import converter_for, known_extensions
from potato.science.converters.jcamp import JcampError, read_jcamp, read_jcamp_text
from potato.science.converters.spectrum_csv import read_spectrum_csv
from potato.science.spectra import (Spectrum, SpectrumError, axis_title, check_size,
                                    decimals_for, detect_peaks, downsample, file_peaks,
                                    from_inline, integrate, read_file, reversed_by_convention)
from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIX = os.path.join(REPO, "tests", "data", "spectra")


def _fixtures():
    spec = importlib.util.spec_from_file_location("make_spectra_fixtures",
                                                  os.path.join(FIX, "make_fixtures.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _fixtures()


# ---------------------------------------------------------------------------
# JCAMP-DX
# ---------------------------------------------------------------------------

class TestJcampFiles:
    def test_difdup_nmr_decodes_to_the_encoded_values(self):
        s = read_jcamp(os.path.join(FIX, "ethyl_acetate_1h.jdx"))
        xs, ys = GEN.nmr_points()
        assert len(s) == 16384
        # The file runs 10 -> 0 ppm; the spectrum is stored ascending.
        assert np.array_equal(s.y, np.asarray(ys[::-1], dtype=float))
        np.testing.assert_allclose(s.x, xs[::-1], atol=1e-6)

    def test_nmr_in_hz_is_converted_to_ppm(self):
        s = read_jcamp(os.path.join(FIX, "ethyl_acetate_1h.jdx"))
        assert (s.kind, s.x_units) == ("nmr", "PPM")
        assert s.meta["observe_frequency_mhz"] == pytest.approx(400.13)
        assert s.meta["nucleus"] == "^1H"
        assert s.x[0] == pytest.approx(0.0, abs=1e-9) and s.x[-1] == pytest.approx(10.0)

    def test_affn_ir_with_yfactor(self):
        s = read_jcamp(os.path.join(FIX, "ester_ir.jdx"))
        xs, ys = GEN.ir_points()
        assert (s.kind, s.x_units, s.y_units) == ("ir", "1/CM", "TRANSMITTANCE")
        np.testing.assert_allclose(s.y, ys[::-1], atol=1e-9)
        assert (s.x[0], s.x[-1]) == (400.0, 4000.0)

    def test_peak_table_mass_spectrum_is_sticks(self):
        s = read_jcamp(os.path.join(FIX, "ei_ms.jdx"))
        assert (s.kind, s.sticks) == ("ms", True)
        assert list(s.x) == [29, 43, 45, 61, 70, 88]
        assert list(s.y) == [18.0, 100.0, 15.5, 12.0, 9.0, 6.5]


def _jdx(body, extra=""):
    return "\n".join(["##TITLE= t", "##JCAMP-DX= 5.01", "##DATA TYPE= INFRARED SPECTRUM",
                      "##XUNITS= 1/CM", "##YUNITS= ABSORBANCE", extra, body, "##END="])


class TestAsdf:
    def test_sqz_dif_dup_with_y_check(self):
        # 1 2 3 4 5 5 5 | 5 6 7 ; second line starts with the check value 5.
        text = _jdx("##FIRSTX= 1\n##LASTX= 9\n##NPOINTS= 9\n##XYDATA= (X++(Y..Y))\n"
                    "1AJUJ%T\n7EJJ")
        s = read_jcamp_text(text)
        assert list(s.y) == [1, 2, 3, 4, 5, 5, 5, 6, 7]
        assert list(s.x) == [1, 2, 3, 4, 5, 6, 7, 8, 9]

    def test_negative_sqz_and_dif(self):
        s = read_jcamp_text(_jdx("##FIRSTX= 0\n##LASTX= 3\n##NPOINTS= 4\n##XYDATA= (X++(Y..Y))\n"
                                 "0a5jU"))
        assert list(s.y) == [-15, -16, -17, -18]

    def test_failed_y_check_is_an_error(self):
        text = _jdx("##FIRSTX= 1\n##LASTX= 6\n##NPOINTS= 6\n##XYDATA= (X++(Y..Y))\n"
                    "1AJJ\n3DJJ")   # line 2 should start with 3 (C), not 4 (D)
        with pytest.raises(JcampError, match="Y-check"):
            read_jcamp_text(text)

    def test_pac_and_signed_exponents(self):
        s = read_jcamp_text(_jdx("##FIRSTX= 10\n##LASTX= 14\n##NPOINTS= 5\n##XYDATA= (X++(Y..Y))\n"
                                 "10+1-2+3\n13 1.5E+01,2.0e-01"))
        assert list(s.y) == [1, -2, 3, 15.0, 0.2]

    def test_bare_e_is_sqz_five_not_an_exponent(self):
        s = read_jcamp_text(_jdx("##FIRSTX= 1\n##LASTX= 2\n##NPOINTS= 2\n##XYDATA= (X++(Y..Y))\n"
                                 "1E1E2"))
        assert list(s.y) == [51, 52]

    def test_x_rebuilt_from_line_abscissas_when_npoints_disagrees(self):
        s = read_jcamp_text(_jdx("##XFACTOR= 0.5\n##DELTAX= 1\n##XYDATA= (X++(Y..Y))\n"
                                 "20 1 2 3\n26 4 5"))
        assert list(s.x) == [10, 11, 12, 13, 14]
        assert list(s.y) == [1, 2, 3, 4, 5]

    def test_unexpected_character(self):
        with pytest.raises(JcampError, match="unexpected character"):
            read_jcamp_text(_jdx("##XYDATA= (X++(Y..Y))\n1 2 #3"))

    def test_xypoints_and_missing_values(self):
        s = read_jcamp_text(_jdx("##XYPOINTS= (XY..XY)\n1,0.5; 2,?; 3,0.7"))
        assert list(s.x) == [1, 3] and list(s.y) == [0.5, 0.7]

    def test_peak_table_beside_xydata_becomes_the_file_peaks(self):
        s = read_jcamp_text(_jdx("##FIRSTX= 1\n##LASTX= 3\n##NPOINTS= 3\n##XYDATA= (X++(Y..Y))\n"
                                 "1 1 5 1\n##PEAK TABLE= (XYW..XYW)\n2,5,0.4"))
        assert not s.sticks and s.peaks == [(2.0, 5.0)]
        assert file_peaks(s) == [{"x": 2.0, "y": 5.0}]

    def test_ntuples_real_page(self):
        text = "\n".join([
            "##TITLE= nt", "##JCAMP-DX= 5.01", "##DATA TYPE= NMR SPECTRUM",
            "##.OBSERVE FREQUENCY= 100", "##NTUPLES= NMR SPECTRUM",
            "##VAR_NAME= FREQUENCY, SPECTRUM/REAL, SPECTRUM/IMAG, PAGE NUMBER",
            "##SYMBOL= X, R, I, N", "##UNITS= HZ, ARBITRARY UNITS, ARBITRARY UNITS,",
            "##FIRST= 300, 0, 0, 1", "##LAST= 0, 0, 0, 2", "##FACTOR= 1, 2, 1, 1",
            "##VAR_DIM= 4, 4, 4, 2",
            "##PAGE= N=1", "##DATA TABLE= (X++(R..R)), XYDATA", "300 1 2 3 4",
            "##PAGE= N=2", "##DATA TABLE= (X++(I..I)), XYDATA", "300 9 9 9 9",
            "##END NTUPLES= NMR SPECTRUM", "##END="])
        s = read_jcamp_text(text)
        assert s.x_units == "PPM"
        np.testing.assert_allclose(s.x, [0, 1, 2, 3])
        assert list(s.y) == [8, 6, 4, 2]       # real page, FACTOR 2, ascending x

    def test_compound_file_block_selection(self):
        one = _jdx("##FIRSTX= 1\n##LASTX= 2\n##NPOINTS= 2\n##XYDATA= (X++(Y..Y))\n1 1 2")
        two = _jdx("##FIRSTX= 1\n##LASTX= 2\n##NPOINTS= 2\n##XYDATA= (X++(Y..Y))\n1 7 8")
        text = "##TITLE= outer\n##JCAMP-DX= 5.01\n##BLOCKS= 2\n" + one + "\n" + two + "\n##END="
        assert list(read_jcamp_text(text).y) == [1, 2]
        assert list(read_jcamp_text(text, block=1).y) == [7, 8]
        with pytest.raises(JcampError, match="block 2 does not exist"):
            read_jcamp_text(text, block=2)

    def test_no_data_and_not_jcamp(self):
        with pytest.raises(JcampError, match="no spectrum data"):
            read_jcamp_text("##TITLE= x\n##END=")
        with pytest.raises(JcampError, match="not a JCAMP-DX"):
            read_jcamp_text("x,y\n1,2\n")

    def test_point_limit(self):
        with pytest.raises(JcampError, match="max_points"):
            read_jcamp(os.path.join(FIX, "ethyl_acetate_1h.jdx"), max_points=1000)


# ---------------------------------------------------------------------------
# CSV and mzML
# ---------------------------------------------------------------------------

class TestCsv:
    def test_header_units_and_values(self):
        s = read_spectrum_csv(os.path.join(FIX, "ester_ir.csv"))
        assert (s.kind, s.x_units, s.y_units) == ("ir", "1/CM", "TRANSMITTANCE")
        assert len(s) == 1801 and s.x[0] == 400

    def test_comments_tabs_and_bad_rows(self, tmp_path):
        p = tmp_path / "a.tsv"
        p.write_text("# made up\nshift (ppm)\tintensity\n1.0\t2\n2.0\t3\n")
        s = read_spectrum_csv(str(p))
        assert (s.kind, list(s.y)) == ("nmr", [2, 3])
        p.write_text("1,2\n2,x\n")
        with pytest.raises(SpectrumError, match="line 2"):
            read_spectrum_csv(str(p))


class TestMzml:
    def test_refuses_entities_before_parsing(self, tmp_path):
        from potato.science.converters.mzml import read_mzml
        p = tmp_path / "bomb.mzML"
        p.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><mzML/>')
        with pytest.raises(SpectrumError, match="DOCTYPE"):
            read_mzml(str(p))

    def test_missing_library_names_the_extra(self):
        from potato.science.converters.mzml import read_mzml
        with patch.dict(sys.modules, {"pyteomics": None}):
            with pytest.raises(SpectrumError, match=r"potato-annotation\[spectra\]"):
                read_file(os.path.join(FIX, "two_scans.mzML"))
            with pytest.raises(Exception, match=r"\[spectra\]"):
                read_mzml(os.path.join(FIX, "two_scans.mzML"))

    def test_index_and_scan_selection(self):
        pytest.importorskip("pyteomics")
        pytest.importorskip("psims")
        from potato.science.converters.mzml import read_mzml
        path = os.path.join(FIX, "two_scans.mzML")
        first = read_mzml(path)
        assert (first.title, first.sticks, first.kind) == ("scan 1, MS1", True, "ms")
        assert list(first.x) == [101.07, 147.11, 175.12, 262.15, 333.19]
        assert list(read_mzml(path, index=1).y) == list(read_mzml(path, scan=2).y) == [3100, 800, 4400, 1500]
        with pytest.raises(SpectrumError, match="scan 9 is not in"):
            read_mzml(path, scan=9)
        with pytest.raises(SpectrumError, match="index 5 is out of range"):
            read_mzml(path, index=5)


def test_converter_table():
    assert {".jdx", ".dx", ".mzml"} <= set(known_extensions())
    assert converter_for("a/B.JDX").__name__ == "read_jcamp"
    assert converter_for("run.mzML").__name__ == "read_mzml"
    # .csv is not claimed for spectra in the shared table.
    assert converter_for("table.csv") is None


# ---------------------------------------------------------------------------
# Downsampling, integration, peaks
# ---------------------------------------------------------------------------

class TestProcessing:
    def test_downsample_keeps_every_peak_height(self):
        s = read_jcamp(os.path.join(FIX, "ethyl_acetate_1h.jdx"))
        xs, ys = downsample(s.x, s.y, 1000)
        assert len(xs) <= 1000 and np.all(np.diff(xs) >= 0)
        assert ys.max() == s.y.max()
        # Each of the three multiplets keeps its tallest line.
        for lo, hi in ((4.0, 4.3), (1.9, 2.2), (1.1, 1.4)):
            m = (s.x >= lo) & (s.x <= hi)
            mm = (xs >= lo) & (xs <= hi)
            assert ys[mm].max() == s.y[m].max()

    def test_downsample_sticks_keeps_tallest(self):
        xs, ys = downsample([1, 2, 3, 4], [5, 1, 9, 2], 2, sticks=True)
        assert list(xs) == [1, 3] and list(ys) == [5, 9]

    def test_integrate_matches_the_analytic_area(self):
        x = np.linspace(0, 10, 1001)
        s = Spectrum(x=x, y=2 * x)
        assert integrate(s, 2, 4) == pytest.approx(12.0)
        assert integrate(s, 4, 2) == pytest.approx(12.0)            # either drag direction
        assert integrate(s, 2.005, 2.015) == pytest.approx(0.0402, rel=1e-6)   # ends interpolated
        assert integrate(s, 20, 30) == 0.0

    def test_nmr_integrals_follow_proton_counts(self):
        s = read_jcamp(os.path.join(FIX, "ethyl_acetate_1h.jdx"))
        base = 10.0                       # the fixture's flat baseline
        def area(a, b):
            return integrate(s, a, b) - base * (b - a)
        q, sg, t = area(4.05, 4.19), area(1.98, 2.10), area(1.19, 1.33)
        assert q / sg * 3 == pytest.approx(2.0, rel=0.05)
        assert t / sg * 3 == pytest.approx(3.0, rel=0.05)

    def test_detect_peaks_finds_the_multiplet_lines(self):
        s = read_jcamp(os.path.join(FIX, "ethyl_acetate_1h.jdx"))
        found = [p["x"] for p in detect_peaks(s, prominence=0.05)]
        j = 7.1 / 400.13
        expected = [1.26 - j, 1.26, 1.26 + j, 2.04,
                    4.12 - 1.5 * j, 4.12 - 0.5 * j, 4.12 + 0.5 * j, 4.12 + 1.5 * j, 7.26]
        assert len(found) == len(expected)
        np.testing.assert_allclose(found, expected, atol=0.001)
        # The 7.26 line is a tenth of the tallest: in at 5% prominence, out at 15%,
        # and the quartet's outer lines (8%) go with it.
        stricter = [p["x"] for p in detect_peaks(s, prominence=0.15)]
        assert len(stricter) == 6 and max(stricter) < 4.15 and not any(abs(x - 7.26) < 0.01 for x in stricter)

    def test_detect_peaks_reports_width_and_honours_max_peaks(self):
        s = read_jcamp(os.path.join(FIX, "ethyl_acetate_1h.jdx"))
        one = detect_peaks(s, prominence=0.05, max_peaks=1)
        assert len(one) == 1 and one[0]["x"] == pytest.approx(2.04, abs=0.001)
        # FWHM of a Lorentzian is twice its 0.6 Hz half width.
        assert one[0]["width"] == pytest.approx(1.2 / 400.13, rel=0.25)

    def test_transmittance_bands_are_minima(self):
        s = read_jcamp(os.path.join(FIX, "ester_ir.jdx"))
        found = [p["x"] for p in detect_peaks(s, direction="min")]
        assert found == [1048, 1240, 1372, 1742, 2936, 2980]
        assert detect_peaks(s, direction="max") != detect_peaks(s, direction="min")

    def test_size_limit(self):
        with pytest.raises(SpectrumError, match="max_file_mb"):
            check_size(os.path.join(FIX, "ethyl_acetate_1h.jdx"), 0.001)

    def test_inline_spectrum(self):
        s = from_inline({"x": [3, 1, 2], "y": [30, 10, 20], "x_units": "ppm"})
        assert list(s.x) == [1, 2, 3] and list(s.y) == [10, 20, 30] and s.kind == "nmr"
        with pytest.raises(SpectrumError):
            from_inline({"x": [1, 2], "y": [1]})
        with pytest.raises(SpectrumError):
            from_inline({"x": ["a"], "y": [1]})

    def test_conventions(self):
        assert reversed_by_convention("nmr", "PPM") and reversed_by_convention("ir", "1/CM")
        assert not reversed_by_convention("ms", "M/Z")
        assert not reversed_by_convention("ir", "MICROMETERS")
        assert axis_title("1/CM", "x") == "Wavenumber (cm⁻¹)"
        assert axis_title("", "x", "nmr") == "Chemical shift"
        assert decimals_for(10) == 3 and decimals_for(3600) == 1 and decimals_for(500) == 2


# ---------------------------------------------------------------------------
# The spectrum display
# ---------------------------------------------------------------------------

@pytest.fixture
def media():
    root = create_test_directory("spectrum_unit")
    media = os.path.join(root, "media")
    os.makedirs(os.path.join(media, "spectra"), exist_ok=True)
    for name in ("ethyl_acetate_1h.jdx", "ester_ir.jdx", "ei_ms.jdx", "ester_ir.csv"):
        with open(os.path.join(FIX, name), "rb") as src, \
                open(os.path.join(media, "spectra", name), "wb") as dst:
            dst.write(src.read())
    with patch.dict("potato.server_utils.config_module.config",
                    {"task_dir": root, "media_directory": "media"}):
        yield media


def _render(value, **options):
    from potato.server_utils.displays.registry import display_registry
    return display_registry.render("spectrum", {"key": "spectrum", "type": "spectrum",
                                                "display_options": options}, value)


def _cfg(page):
    m = re.search(r"data-viewer-config='([^']*)'", page)
    return json.loads(html_module.unescape(m.group(1)))


class TestSpectrumDisplay:
    def test_nmr_file_conventions_and_downsampling(self, media):
        cfg = _cfg(_render("spectra/ethyl_acetate_1h.jdx", max_points=1000))
        assert cfg["spectrumType"] == "nmr" and cfg["reversed"] is True and cfg["integrate"] is True
        assert cfg["xLabel"] == "Chemical shift (ppm)" and cfg["direction"] == "max"
        assert cfg["totalPoints"] == 16384 and cfg["shownPoints"] == len(cfg["x"]) <= 1000
        assert max(cfg["y"]) == read_jcamp(os.path.join(FIX, "ethyl_acetate_1h.jdx")).y.max()
        assert cfg["suggestions"] == [] and cfg["suggestionMethod"] is None
        assert cfg["assets"] == [{"type": "script", "src": "/static/vendor/plotly-2.27.0.min.js"}]

    def test_ir_csv_points_down_and_is_reversed(self, media):
        cfg = _cfg(_render("spectra/ester_ir.csv", prepick=True))
        assert (cfg["spectrumType"], cfg["reversed"], cfg["direction"], cfg["integrate"]) == ("ir", True, "min", False)
        assert [s["x"] for s in cfg["suggestions"]] == [1048, 1240, 1372, 1742, 2936, 2980]
        assert cfg["suggestionMethod"] == "detect"

    def test_ms_sticks_and_file_peaks(self, media):
        cfg = _cfg(_render("spectra/ei_ms.jdx", prepick={"method": "auto", "max_peaks": 3}))
        assert cfg["sticks"] is True and cfg["reversed"] is False and cfg["integrate"] is False
        assert [s["x"] for s in cfg["suggestions"]] == [29, 43, 45]   # tallest three, by x

    def test_overrides(self, media):
        cfg = _cfg(_render("spectra/ethyl_acetate_1h.jdx", x_reversed=False, integrate=False,
                           x_label="δ (ppm)", mode="sticks"))
        assert (cfg["reversed"], cfg["integrate"], cfg["xLabel"], cfg["sticks"]) == (False, False, "δ (ppm)", True)

    def test_item_peaks_are_the_suggestions(self, media):
        cfg = _cfg(_render({"file": "spectra/ethyl_acetate_1h.jdx",
                            "peaks": [2.04, {"x": 7.26, "label": "CHCl3"}]}, prepick=True))
        assert cfg["suggestionMethod"] == "item"
        assert [s["x"] for s in cfg["suggestions"]] == [2.04, 7.26]
        assert cfg["suggestions"][1]["label"] == "CHCl3"
        assert cfg["suggestions"][0]["y"] == pytest.approx(3001, rel=0.02)

    def test_inline_value(self, media):
        cfg = _cfg(_render({"x": [1, 2, 3], "y": [0, 5, 0], "x_units": "PPM"}))
        assert cfg["x"] == [1.0, 2.0, 3.0] and cfg["spectrumType"] == "nmr"

    @pytest.mark.parametrize("value, message", [
        ("https://example.org/a.jdx", "Spectra are read on the server"),
        ("spectra/missing.jdx", "not in the media directory"),
        ("../../etc/passwd.jdx", "not in the media directory"),
        (None, "has no spectrum"),
        ({"file": "spectra/ei_ms.jdx", "colour": "red"}, "unknown key"),
    ])
    def test_refusals_render_a_message(self, media, value, message):
        page = _render(value)
        assert 'class="potato-viewer pv-failed"' in page and 'data-viewer-kind="spectrum"' in page
        assert message in html_module.unescape(page)

    def test_item_text_is_escaped(self, media):
        evil = "<img src=x onerror=alert(1)>"
        page = _render({"x": [1, 2, 3], "y": [0, 5, 0], "title": evil, "x_units": evil})
        assert "<img" not in page and "onerror=alert(1)&gt;" in page
        assert _cfg(page)["title"] == evil       # the browser gets it as data, not markup
        bad = _render({"file": evil})
        assert "<img" not in bad

    def test_wrong_format_and_bad_file(self, media):
        with open(os.path.join(media, "spectra", "a.pdb"), "w") as f:
            f.write("ATOM\n")
        assert "not a spectrum format" in html_module.unescape(_render("spectra/a.pdb"))
        with open(os.path.join(media, "spectra", "bad.jdx"), "w") as f:
            f.write("##TITLE= x\n##XYDATA= (X++(Y..Y))\n1 2 #\n##END=\n")
        assert "unexpected character" in html_module.unescape(_render("spectra/bad.jdx"))

    def test_file_size_limit(self, media):
        page = html_module.unescape(_render("spectra/ethyl_acetate_1h.jdx", max_file_mb=0.001))
        assert "max_file_mb" in page

    @pytest.mark.parametrize("options, fragment", [
        ({"spectrum_type": "xray"}, "spectrum_type must be one of"),
        ({"x_reversed": "yes"}, "x_reversed must be one of"),
        ({"mode": "bars"}, "mode must be one of"),
        ({"peak_direction": "up"}, "peak_direction must be one of"),
        ({"integrate": "nmr"}, "integrate must be one of"),
        ({"max_points": 50}, "max_points must be"),
        ({"max_file_mb": 0}, "max_file_mb must be"),
        ({"max_file_mb": 900}, "max_file_mb must be"),
        ({"scan": 0}, "scan must be"),
        ({"scan": 1, "index": 0}, "scan or index, not both"),
        ({"prepick": "yes"}, "prepick must be"),
        ({"prepick": {"prominance": 0.1}}, "unknown key(s) prominance"),
        ({"prepick": {"prominence": 5}}, "prominence must be"),
        ({"prepick": {"max_peaks": 0}}, "max_peaks must be"),
        ({"prepick": {"method": "ml"}}, "method must be one of"),
        ({"allow_remote": True}, "allow_remote is not supported"),
        ({"snap": "on"}, "snap must be"),
    ])
    def test_option_validation(self, options, fragment):
        from potato.server_utils.displays.spectrum_display import SpectrumDisplay
        d = SpectrumDisplay()
        errors = d.validate_options(d.get_display_options({"key": "s", "display_options": options}), "f")
        assert any(fragment in e for e in errors), errors

    def test_default_options_are_valid(self):
        from potato.server_utils.displays.spectrum_display import SpectrumDisplay
        d = SpectrumDisplay()
        assert d.validate_options(d.get_display_options({"key": "s"}), "f") == []

    def test_selection_shape(self):
        from potato.server_utils.displays.viewer_display import validate_selection
        good = {"viewer": "spectrum", "rejected": [0.9],
                "items": [{"kind": "peak", "x": 2.04, "y": 3010, "source": "auto", "width": 0.003,
                           "fields": {"assignment": "CH3"}},
                          {"kind": "region", "from": 1.9, "to": 2.1, "integral": 12.5}]}
        assert validate_selection("spectrum", good) == []
        bad = {"viewer": "spectrum", "rejected": ["x"],
               "items": [{"kind": "peak", "x": "2", "source": "ai"},
                         {"kind": "region", "from": 2, "to": 1},
                         {"kind": "blob"},
                         {"kind": "peak", "x": 1, "source": "manual", "fields": {"a": 1}}]}
        errors = validate_selection("spectrum", bad)
        for fragment in ("items[0].x must be a number", "items[0].source must be auto or manual",
                         "items[1].to must be above .from", "items[2].kind must be peak or region",
                         "items[3].fields must map", "rejected must be a list"):
            assert any(fragment in e for e in errors), (fragment, errors)


# ---------------------------------------------------------------------------
# peak_picking scheme and config validation
# ---------------------------------------------------------------------------

def _scheme(**kw):
    base = {"annotation_type": "peak_picking", "name": "peaks", "description": "Pick",
            "viewer_field": "spectrum"}
    base.update(kw)
    return base


class TestPeakPickingScheme:
    def test_layout(self):
        from potato.server_utils.schemas.registry import schema_registry
        html, keys = schema_registry.generate(_scheme(peak_fields=[
            {"name": "assignment"}, {"name": "multiplicity", "options": ["s", "d"]}]))
        assert keys == []
        assert 'data-annotation-type="peak_picking"' in html
        assert 'class="annotation-input peak-picking-input"' in html and 'schema="peaks"' in html
        m = re.search(r"data-peak-config='([^']*)'", html)
        cfg = json.loads(html_module.unescape(m.group(1)))
        assert cfg["viewerField"] == "spectrum" and cfg["allowManual"] is True
        assert cfg["peakFields"][1] == {"name": "multiplicity", "type": "choice", "label": "Multiplicity",
                                        "required": False, "options": ["s", "d"]}
        assert cfg["regionFields"] == [{"name": "label", "type": "text", "label": "Label", "required": False}]
        assert 'class="pp-add"' in html

    def test_no_add_row_without_manual_peaks(self):
        from potato.server_utils.schemas.registry import schema_registry
        html, _ = schema_registry.generate(_scheme(allow_manual=False))
        assert 'class="pp-add"' not in html

    @pytest.mark.parametrize("extra, fragment", [
        ({"viewer_field": ""}, "viewer_field must name"),
        ({"peak_fields": "assignment"}, "peak_fields must be a list"),
        ({"peak_fields": [{"name": "a b"}]}, "short identifier"),
        ({"peak_fields": [{"name": "m", "type": "choice"}]}, "options must be a non-empty list"),
        ({"peak_fields": [{"name": "m", "options": [True, False]}]}, "quote them"),
        ({"peak_fields": [{"name": "m", "type": "number"}]}, "type must be text or choice"),
        ({"peak_fields": [{"name": "m"}, {"name": "m"}]}, "repeats m"),
        ({"region_fields": [{"name": "n", "colour": 1}]}, "unknown key(s) colour"),
        ({"min_peaks": -1}, "min_peaks must be"),
        ({"min_peaks": 3, "max_peaks": 2}, "below min_peaks"),
        ({"max_peaks": 0}, "would refuse every peak"),
        ({"require_review": "yes"}, "require_review must be"),
    ])
    def test_validation(self, extra, fragment):
        from potato.server_utils.schemas.peak_picking import validate_scheme
        errors = validate_scheme(_scheme(**extra), "s")
        assert any(fragment in e for e in errors), errors

    def test_config_validation_and_binding(self):
        from potato.server_utils.config_module import (ConfigValidationError,
                                                       validate_single_annotation_scheme)
        from potato.server_utils.displays.viewer_display import validate_viewer_config
        with pytest.raises(ConfigValidationError, match="max_peaks"):
            validate_single_annotation_scheme(_scheme(max_peaks=0), "annotation_schemes[0]")
        validate_single_annotation_scheme(_scheme(), "annotation_schemes[0]")
        fields = [{"key": "spectrum", "type": "spectrum"}, {"key": "note", "type": "text"}]
        ok = {"instance_display": {"fields": fields}, "annotation_schemes": [_scheme()]}
        assert validate_viewer_config(ok) == []
        wrong = {"instance_display": {"fields": fields},
                 "annotation_schemes": [_scheme(viewer_field="note")]}
        errors = validate_viewer_config(wrong)
        assert any("'note' does not name a spectrum display" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------

def _context(answers, schemes=None):
    from potato.export.base import ExportContext
    schemes = schemes or [_scheme(peak_fields=[{"name": "assignment"}, {"name": "x"}])]
    annotations = [{"user_id": u, "instance_id": i,
                    "labels": {"peaks": {"peaks": json.dumps(a)}}} for u, i, a in answers]
    return ExportContext(config={}, annotations=annotations, items={}, schemas=schemes,
                         output_dir=create_test_directory("peak_export"))


ANSWER = {"viewer": "spectrum", "rejected": [7.26],
          "items": [{"kind": "peak", "x": 2.04, "y": 3010.0, "source": "auto", "width": 0.003,
                     "fields": {"assignment": "CH3CO", "x": "clash"}},
                    {"kind": "peak", "x": 1.26, "y": 1510.0, "source": "manual"},
                    {"kind": "region", "from": 1.98, "to": 2.10, "integral": 30.0},
                    {"kind": "region", "from": 4.05, "to": 4.19, "integral": 20.0,
                     "fields": {"label": "OCH2"}}]}


class TestPeakExporter:
    def test_rows_csv_and_jsonl(self):
        from potato.export.peak_exporter import PeakTableExporter
        exp = PeakTableExporter()
        ctx = _context([("ann1", "item1", ANSWER)])
        assert exp.can_export(ctx) == (True, "")
        out = os.path.join(ctx.output_dir, "peaks")
        result = exp.export(ctx, out)
        assert result.success, result.errors
        assert result.stats == {"peaks": 2, "regions": 2, "rejected": 1, "accepted_suggestions": 1}
        rows = [json.loads(line) for line in open(os.path.join(out, "peaks.jsonl"))]
        assert rows[0] == {"user_id": "ann1", "instance_id": "item1", "schema": "peaks", "kind": "peak",
                           "x": 2.04, "y": 3010.0, "width": 0.003, "source": "auto",
                           "label": "CH3CO / clash", "assignment": "CH3CO", "field_x": "clash"}
        assert rows[1]["source"] == "manual" and rows[1]["label"] == ""
        assert rows[2]["relative"] == 1.0 and rows[3]["relative"] == pytest.approx(20 / 30, rel=1e-5)
        assert rows[3]["label"] == "OCH2"
        assert rows[4] == {"user_id": "ann1", "instance_id": "item1", "schema": "peaks",
                           "kind": "rejected", "x": 7.26, "source": "auto"}
        import csv
        with open(os.path.join(out, "peaks.csv"), newline="") as f:
            table = list(csv.DictReader(f))
        assert [r["kind"] for r in table] == ["peak", "peak", "region", "region", "rejected"]
        assert table[0]["field_x"] == "clash" and table[1]["width"] == ""

    def test_nothing_to_export(self):
        from potato.export.peak_exporter import PeakTableExporter
        ctx = _context([("ann1", "item1", {"viewer": "spectrum", "items": []})])
        result = PeakTableExporter().export(ctx, os.path.join(ctx.output_dir, "none"))
        assert not result.success and "No peak_picking answers" in result.errors[0]
        assert PeakTableExporter().can_export(_context([], schemes=[{"name": "r", "annotation_type": "radio"}]))[0] is False

    def test_format_option(self):
        from potato.export.peak_exporter import PeakTableExporter
        ctx = _context([("ann1", "item1", ANSWER)])
        out = os.path.join(ctx.output_dir, "csv_only")
        assert PeakTableExporter().export(ctx, out, {"format": "csv"}).files_written == [
            os.path.join(out, "peaks.csv")]
        assert not PeakTableExporter().export(ctx, out, {"format": "xlsx"}).success

    def test_registered(self):
        from potato.export.registry import export_registry
        assert export_registry.get("peak_table") is not None

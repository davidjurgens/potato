"""Write the synthetic spectra the spectrum tests read.

    python tests/data/spectra/make_fixtures.py

Every file here is invented: Lorentzian lines at chosen positions, no
measured data. The JCAMP-DX files are compressed by hand-rolled SQZ/DIF/DUP
encoding (``encode_asdf``) so the reader's decoder is checked against an
independent encoder rather than against itself.
"""

import base64
import math
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))

_SQZ_POS = "@ABCDEFGHI"
_SQZ_NEG = "@abcdefghi"
_DIF_POS = "%JKLMNOPQR"
_DIF_NEG = "%jklmnopqr"
_DUP = "STUVWXYZs"


def _sqz(v, pos, neg):
    s = str(abs(v))
    return (pos if v >= 0 else neg)[int(s[0])] + s[1:]


def _dup(count):
    s = str(count)
    return _DUP[int(s[0]) - 1] + s[1:]


def encode_asdf(values, per_line=10, firstx=0.0, deltax=1.0, xfactor=1.0):
    """(X++(Y..Y)) lines in DIFDUP form with the Y-check value on each line."""
    lines = []
    i = 0
    n = len(values)
    while i < n:
        chunk = values[i:i + per_line]
        x = round((firstx + i * deltax) / xfactor)
        out = [str(x), _sqz(chunk[0], _SQZ_POS, _SQZ_NEG)]
        diffs = [b - a for a, b in zip(chunk, chunk[1:])]
        j = 0
        while j < len(diffs):
            k = j
            while k + 1 < len(diffs) and diffs[k + 1] == diffs[j]:
                k += 1
            out.append(_sqz(diffs[j], _DIF_POS, _DIF_NEG))
            if k > j:
                out.append(_dup(k - j + 1))
            j = k + 1
        lines.append("".join(out))
        # The next line starts with the last value again (the Y-check).
        i += per_line - 1 if i + per_line < n else per_line
    return lines


def lorentz(x, centre, height, hwhm):
    return height / (1 + ((x - centre) / hwhm) ** 2)


def nmr_points():
    """Ethyl acetate-like 1H spectrum at 400.13 MHz, 0-10 ppm, 16384 points.

    A quartet at 4.12 (2H), a singlet at 2.04 (3H), a triplet at 1.26 (3H),
    J = 7.1 Hz, plus a small CHCl3 line at 7.26. Equal line widths, so the
    areas follow the heights: 2 : 3 : 3.
    """
    n = 16384
    j = 7.1 / 400.13
    lines = [(4.12 - 1.5 * j, 250), (4.12 - 0.5 * j, 750), (4.12 + 0.5 * j, 750), (4.12 + 1.5 * j, 250),
             (2.04, 3000),
             (1.26 - j, 750), (1.26, 1500), (1.26 + j, 750),
             (7.26, 300)]
    hwhm = 0.6 / 400.13
    xs = [10.0 - i * 10.0 / (n - 1) for i in range(n)]      # high to low, like a real file
    ys = [int(round(sum(lorentz(x, c, h, hwhm) for c, h in lines) + 10)) for x in xs]
    return xs, ys


def write_nmr_jdx(path):
    xs, ys = nmr_points()
    n = len(xs)
    obs = 400.13
    firstx_hz, lastx_hz = xs[0] * obs, xs[-1] * obs
    deltax = (lastx_hz - firstx_hz) / (n - 1)
    head = [
        "##TITLE= Synthetic ethyl acetate 1H NMR (invented data)",
        "##JCAMP-DX= 5.01",
        "##DATA TYPE= NMR SPECTRUM",
        "##DATA CLASS= XYDATA",
        "##ORIGIN= Potato test fixture",
        "##OWNER= public domain",
        "##.OBSERVE FREQUENCY= %.2f" % obs,
        "##.OBSERVE NUCLEUS= ^1H",
        "##XUNITS= HZ",
        "##YUNITS= ARBITRARY UNITS",
        "##XFACTOR= 1.0",
        "##YFACTOR= 1.0",
        "##FIRSTX= %.6f" % firstx_hz,
        "##LASTX= %.6f" % lastx_hz,
        "##DELTAX= %.6f" % deltax,
        "##NPOINTS= %d" % n,
        "##FIRSTY= %d" % ys[0],
        "##XYDATA= (X++(Y..Y))  $$ DIFDUP",
    ]
    body = encode_asdf(ys, per_line=12, firstx=firstx_hz, deltax=deltax, xfactor=1.0)
    with open(path, "w") as f:
        f.write("\n".join(head + body + ["##END="]) + "\n")


def ir_points():
    """A carbonyl-compound-like IR transmittance spectrum, 4000-400 cm-1."""
    n = 1801
    bands = [(2980, 35, 18), (2935, 20, 15), (1742, 75, 10), (1373, 40, 8),
             (1240, 70, 14), (1047, 50, 12)]
    xs = [4000 - i * 2.0 for i in range(n)]
    ys = []
    for x in xs:
        absorb = sum(lorentz(x, c, d, w) for c, d, w in bands)
        ys.append(round(max(2.0, 96.0 - absorb), 2))
    return xs, ys


def write_ir_jdx(path):
    xs, ys = ir_points()
    n = len(xs)
    # AFFN with YFACTOR, eight values per line, plus a peak table block.
    head = [
        "##TITLE= Synthetic ester IR spectrum (invented data)",
        "##JCAMP-DX= 4.24",
        "##DATA TYPE= INFRARED SPECTRUM",
        "##XUNITS= 1/CM",
        "##YUNITS= TRANSMITTANCE",
        "##XFACTOR= 1.0",
        "##YFACTOR= 0.01",
        "##FIRSTX= 4000",
        "##LASTX= 400",
        "##NPOINTS= %d" % n,
        "##XYDATA= (X++(Y..Y))",
    ]
    body = []
    for i in range(0, n, 8):
        chunk = ys[i:i + 8]
        body.append("%d %s" % (xs[i], " ".join(str(int(round(v * 100))) for v in chunk)))
    with open(path, "w") as f:
        f.write("\n".join(head + body + ["##END="]) + "\n")


def write_ms_jdx(path):
    peaks = [(29, 18.0), (43, 100.0), (45, 15.5), (61, 12.0), (70, 9.0), (88, 6.5)]
    text = "\n".join([
        "##TITLE= Synthetic EI mass spectrum (invented data)",
        "##JCAMP-DX= 4.24",
        "##DATA TYPE= MASS SPECTRUM",
        "##DATA CLASS= PEAK TABLE",
        "##XUNITS= M/Z",
        "##YUNITS= RELATIVE ABUNDANCE",
        "##NPOINTS= %d" % len(peaks),
        "##PEAK TABLE= (XY..XY)",
        " ".join("%d,%.1f" % p for p in peaks[:3]),
        " ".join("%d,%.1f" % p for p in peaks[3:]),
        "##END=",
    ])
    with open(path, "w") as f:
        f.write(text + "\n")


def write_csv(path):
    xs, ys = ir_points()
    with open(path, "w") as f:
        f.write("wavenumber (cm-1),transmittance (%T)\n")
        for x, y in zip(xs, ys):
            f.write("%g,%g\n" % (x, y))


def _b64(values):
    return base64.b64encode(struct.pack("<%dd" % len(values), *values)).decode()


def write_mzml(path):
    scans = [
        (1, 1, [101.07, 147.11, 175.12, 262.15, 333.19], [1200, 5400, 9800, 2100, 760], True),
        (2, 2, [120.08, 136.08, 244.17, 391.23], [3100, 800, 4400, 1500], True),
    ]
    spectra = []
    for index, (scan, level, mz, inten, centroid) in enumerate(scans):
        arrays = []
        for name, acc, values in (("m/z array", "MS:1000514", mz),
                                  ("intensity array", "MS:1000515", inten)):
            data = _b64([float(v) for v in values])
            arrays.append(
                f'<binaryDataArray encodedLength="{len(data)}">'
                f'<cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>'
                f'<cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>'
                f'<cvParam cvRef="MS" accession="{acc}" name="{name}" value=""/>'
                f'<binary>{data}</binary></binaryDataArray>')
        kind = ('<cvParam cvRef="MS" accession="MS:1000127" name="centroid spectrum" value=""/>'
                if centroid else
                '<cvParam cvRef="MS" accession="MS:1000128" name="profile spectrum" value=""/>')
        spectra.append(
            f'<spectrum index="{index}" id="controllerType=0 controllerNumber=1 scan={scan}" '
            f'defaultArrayLength="{len(mz)}">'
            f'<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="{level}"/>'
            f'{kind}<binaryDataArrayList count="2">{"".join(arrays)}</binaryDataArrayList></spectrum>')
    text = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0">\n'
        '<cvList count="1"><cv id="MS" fullName="PSI-MS" version="4.1.0" '
        'URI="https://raw.githubusercontent.com/HUPO-PSI/psi-ms-CV/master/psi-ms.obo"/></cvList>\n'
        '<run id="synthetic"><spectrumList count="%d">\n%s\n</spectrumList></run>\n</mzML>\n'
        % (len(spectra), "\n".join(spectra)))
    with open(path, "w") as f:
        f.write(text)


if __name__ == "__main__":
    write_nmr_jdx(os.path.join(HERE, "ethyl_acetate_1h.jdx"))
    write_ir_jdx(os.path.join(HERE, "ester_ir.jdx"))
    write_ms_jdx(os.path.join(HERE, "ei_ms.jdx"))
    write_csv(os.path.join(HERE, "ester_ir.csv"))
    write_mzml(os.path.join(HERE, "two_scans.mzML"))
    print("wrote fixtures to", HERE)

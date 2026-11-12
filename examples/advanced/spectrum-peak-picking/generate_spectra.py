"""Write the synthetic spectra for the spectrum-peak-picking example.

    python examples/advanced/spectrum-peak-picking/generate_spectra.py

Every spectrum here is invented: sums of Lorentzian lines at textbook
positions, not measurements. The two 1H NMR spectra are JCAMP-DX files with
their XYDATA in DIFDUP compression (the form most NMR software writes); the
IR spectrum is a plain two-column CSV.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "media", "spectra")
MHZ = 400.13

_SQZ = ("@ABCDEFGHI", "@abcdefghi")
_DIF = ("%JKLMNOPQR", "%jklmnopqr")
_DUP = "STUVWXYZs"


def _code(v, table):
    s = str(abs(v))
    return (table[0] if v >= 0 else table[1])[int(s[0])] + s[1:]


def difdup_lines(values, firstx, deltax, per_line=12):
    lines, i, n = [], 0, len(values)
    while i < n:
        chunk = values[i:i + per_line]
        out = [str(round(firstx + i * deltax)), _code(chunk[0], _SQZ)]
        diffs = [b - a for a, b in zip(chunk, chunk[1:])]
        j = 0
        while j < len(diffs):
            k = j
            while k + 1 < len(diffs) and diffs[k + 1] == diffs[j]:
                k += 1
            out.append(_code(diffs[j], _DIF))
            if k > j:
                s = str(k - j + 1)
                out.append(_DUP[int(s[0]) - 1] + s[1:])
            j = k + 1
        lines.append("".join(out))
        i += per_line - 1 if i + per_line < n else per_line   # Y-check value
    return lines


def lorentz(x, centre, height, hwhm):
    return height / (1 + ((x - centre) / hwhm) ** 2)


def multiplet(centre, n_h, pattern, j_hz=7.1, unit=1000):
    """Lines of a first-order multiplet: pattern 1 (s), 2 (d), 3 (t), 4 (q)."""
    weights = {1: [1], 2: [1, 1], 3: [1, 2, 1], 4: [1, 3, 3, 1]}[pattern]
    total = sum(weights)
    j = j_hz / MHZ
    first = centre - j * (len(weights) - 1) / 2
    return [(first + k * j, unit * n_h * w / total) for k, w in enumerate(weights)]


def write_nmr(name, title, lines, n=16384, hwhm_hz=0.6):
    hwhm = hwhm_hz / MHZ
    xs = [10.0 - i * 10.0 / (n - 1) for i in range(n)]
    ys = [int(round(sum(lorentz(x, c, h, hwhm) for c, h in lines) + 12)) for x in xs]
    firstx, lastx = xs[0] * MHZ, xs[-1] * MHZ
    deltax = (lastx - firstx) / (n - 1)
    head = [
        f"##TITLE= {title}",
        "##JCAMP-DX= 5.01",
        "##DATA TYPE= NMR SPECTRUM",
        "##DATA CLASS= XYDATA",
        "##ORIGIN= Potato example (synthetic, invented data)",
        "##OWNER= public domain",
        f"##.OBSERVE FREQUENCY= {MHZ:.2f}",
        "##.OBSERVE NUCLEUS= ^1H",
        "##.SOLVENT NAME= CDCl3",
        "##XUNITS= HZ",
        "##YUNITS= ARBITRARY UNITS",
        "##XFACTOR= 1.0",
        "##YFACTOR= 1.0",
        f"##FIRSTX= {firstx:.6f}",
        f"##LASTX= {lastx:.6f}",
        f"##DELTAX= {deltax:.6f}",
        f"##NPOINTS= {n}",
        f"##FIRSTY= {ys[0]}",
        "##XYDATA= (X++(Y..Y))",
    ]
    with open(os.path.join(OUT, name), "w") as f:
        f.write("\n".join(head + difdup_lines(ys, firstx, deltax) + ["##END="]) + "\n")


def write_ir_csv(name):
    bands = [(3065, 8, 20), (2980, 30, 18), (2938, 18, 14), (1724, 80, 9), (1602, 22, 6),
             (1452, 25, 8), (1275, 72, 12), (1110, 55, 11), (712, 60, 7)]
    with open(os.path.join(OUT, name), "w") as f:
        f.write("# Synthetic aromatic ester IR spectrum (invented data)\n")
        f.write("wavenumber (cm-1),transmittance (%T)\n")
        for i in range(1801):
            x = 4000 - 2 * i
            t = 96.0 - sum(lorentz(x, c, d, w) for c, d, w in bands)
            f.write(f"{x},{max(2.0, t):.2f}\n")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    write_nmr("ethyl_acetate_1h.jdx", "Ethyl acetate, 1H, CDCl3 (synthetic)",
              multiplet(4.12, 2, 4) + multiplet(2.04, 3, 1) + multiplet(1.26, 3, 3)
              + [(7.26, 120)])
    write_nmr("ethanol_1h.jdx", "Ethanol, 1H, CDCl3 (synthetic)",
              multiplet(3.69, 2, 4) + multiplet(1.22, 3, 3) + [(2.61, 260)] + [(7.26, 120)])
    write_ir_csv("ethyl_benzoate_ir.csv")
    print("wrote", sorted(os.listdir(OUT)))

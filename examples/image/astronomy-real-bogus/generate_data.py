"""Write the synthetic FITS cutouts and light curves for this example.

Run from the repository root (needs astropy: pip install 'potato-annotation[astro]'):

    python examples/image/astronomy-real-bogus/generate_data.py

Every candidate gets a 96 x 96 science, reference and difference image on
one pixel grid, with a minimal TAN WCS at 1 arcsec per pixel, plus a light
curve CSV. Nothing here is real data. The noise is seeded, so the files come
out the same each run.

  cand-001  a point source on the outskirts of a disk galaxy (a supernova)
  cand-002  a star that moved half a pixel between epochs: a dipole residual
  cand-003  one hot pixel in the science image (a cosmic ray)
  cand-004  a point source with nothing in the reference (hostless)
"""

import csv
import json
import os

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "media")
SIDE = 96
SKY, NOISE = 1000.0, 12.0


def wcs_header(ra, dec):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [SIDE / 2 + 0.5, SIDE / 2 + 0.5]
    w.wcs.cdelt = [-1 / 3600.0, 1 / 3600.0]      # 1 arcsec/pixel, east to the left
    w.wcs.radesys = "ICRS"
    return w.to_header()


def gaussian(x0, y0, flux, sigma):
    y, x = np.mgrid[0:SIDE, 0:SIDE]
    return flux / (2 * np.pi * sigma ** 2) * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2 * sigma ** 2))


def galaxy(x0, y0, flux, a, b, theta):
    y, x = np.mgrid[0:SIDE, 0:SIDE]
    c, s = np.cos(theta), np.sin(theta)
    u = (x - x0) * c + (y - y0) * s
    v = -(x - x0) * s + (y - y0) * c
    r = np.sqrt((u / a) ** 2 + (v / b) ** 2)
    profile = np.exp(-1.68 * r)                    # an exponential disk
    return flux * profile / profile.sum()


def write(name, data, header, mjd, band, gz=False):
    hdr = header.copy()
    hdr["MJD-OBS"] = (mjd, "synthetic epoch")
    hdr["FILTER"] = band
    hdr["BUNIT"] = "adu"
    hdr["OBJECT"] = name.split("_")[0]
    hdr["COMMENT"] = "Synthetic data generated for the Potato astronomy example."
    hdu = fits.PrimaryHDU(np.round(data).astype(np.int16), header=hdr)
    path = os.path.join(MEDIA, "cutouts", name + (".fits.gz" if gz else ".fits"))
    hdu.writeto(path, overwrite=True)
    return os.path.relpath(path, MEDIA)


def light_curve(name, rows):
    path = os.path.join(MEDIA, "lightcurves", name + ".csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mjd", "band", "mag", "magerr", "limit"])
        for row in rows:
            w.writerow(row)
    return os.path.relpath(path, MEDIA)


def sn_rows(rng, t0, peak_g, peak_r, start, stop, step):
    rows = []
    for t in np.arange(start, stop, step):
        for band, peak, shift in (("g", peak_g, 0.0), ("r", peak_r, 1.5)):
            dt = t + shift - t0
            if dt < -18:
                rows.append([round(t + shift, 3), band, "", "", 21.3])     # upper limit
                continue
            mag = peak + (0.012 * dt ** 2 if dt < 0 else 0.035 * dt)
            err = 0.03 + 0.02 * max(0.0, mag - 18.5)
            if mag > 21.3:
                rows.append([round(t + shift, 3), band, "", "", 21.3])
            else:
                rows.append([round(t + shift, 3), band, round(mag + rng.normal(0, err), 3),
                             round(err, 3), ""])
    return rows


def main():
    rng = np.random.default_rng(20261027)
    os.makedirs(os.path.join(MEDIA, "cutouts"), exist_ok=True)
    os.makedirs(os.path.join(MEDIA, "lightcurves"), exist_ok=True)
    mjd_sci, mjd_ref = 60612.31, 60250.12
    c = SIDE / 2 - 0.5                              # 0-based centre of the grid
    items = []

    specs = [
        ("cand-001", 150.11920, 2.20583, "r"),
        ("cand-002", 150.20410, 2.31027, "g"),
        ("cand-003", 150.05570, 2.15012, "r"),
        ("cand-004", 149.98730, 2.27741, "g"),
    ]
    for n, (name, ra, dec, band) in enumerate(specs):
        header = wcs_header(ra, dec)
        sky_sci = SKY + rng.normal(0, NOISE, (SIDE, SIDE))
        sky_ref = SKY + rng.normal(0, NOISE * 0.6, (SIDE, SIDE))   # a deeper stack
        neighbour = gaussian(c + 30, c - 26, 40000, 1.6)          # a field star in every image
        sci, ref = sky_sci + neighbour, sky_ref + neighbour
        if name == "cand-001":
            host = galaxy(c - 6, c + 4, 260000, 11, 5, 0.6)
            sci, ref = sci + host, ref + host
            sci = sci + gaussian(c, c, 52000, 1.6)               # the transient, at the centre
            lc = sn_rows(rng, 60612.0, 18.9, 18.7, 60570.0, 60640.0, 3.0)
        elif name == "cand-002":
            sci = sci + gaussian(c + 0.6, c + 0.3, 90000, 1.6)    # the star, moved
            ref = ref + gaussian(c, c, 90000, 1.6)
            lc = [[60612.31, band, 19.42, 0.08, ""]]
        elif name == "cand-003":
            sci = sci.copy()
            sci[int(c), int(c)] += 2600                           # one hot pixel
            sci[int(c), int(c) + 1] += 700
            lc = [[60612.31, band, 20.81, 0.21, ""], [60609.30, band, "", "", 21.2],
                  [60615.28, band, "", "", 21.1]]
        else:
            sci = sci + gaussian(c, c, 30000, 1.6)
            lc = sn_rows(rng, 60606.0, 19.6, 19.5, 60580.0, 60640.0, 4.0)
        diff = sci - ref + rng.normal(0, 2.0, (SIDE, SIDE))
        gz = name == "cand-004"
        files = {
            "science": write(f"{name}_sci", sci, header, mjd_sci, band, gz=gz),
            "reference": write(f"{name}_ref", ref, header, mjd_ref, band, gz=gz),
            "difference": write(f"{name}_diff", diff, header, mjd_sci, band, gz=gz),
        }
        candidate = dict(files)
        if name == "cand-003":
            # A position in FITS pixels (the first pixel is 1) instead of ra/dec.
            candidate.update({"x": SIDE / 2, "y": SIDE / 2})
        else:
            candidate.update({"ra": ra, "dec": dec})
        candidate["size"] = 48 if name != "cand-004" else "40 arcsec"
        candidate["light_curve"] = light_curve(name, lc)
        if name == "cand-001":
            # The host is bright, so zscale saturates it: the two direct
            # images of this item use a percentile interval and an asinh
            # stretch instead (a panel given as a mapping).
            for key in ("science", "reference"):
                candidate[key] = {"path": files[key], "interval": "percentile",
                                  "stretch": "asinh"}
        items.append({
            "id": name,
            "summary": f"{name}: ra {ra:.5f}, dec {dec:+.5f}, band {band}",
            "candidate": candidate,
        })

    with open(os.path.join(HERE, "data", "candidates.json"), "w") as f:
        json.dump(items, f, indent=2)
        f.write("\n")
    print(f"wrote {len(items)} candidates under {MEDIA}")


if __name__ == "__main__":
    main()

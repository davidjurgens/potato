# Astronomical images (FITS cutouts)

The `fits_cutout` display shows FITS images from the media directory: one image for morphology work, or the science, reference and difference cutouts that transient surveys use to vet candidates, side by side, with the candidate's light curve underneath. The server reads the FITS files, cuts out the region around the item's position, scales it and sends a PNG; the browser gets a description of the WCS with it, so the readout under the pointer gives RA and Dec.

The display only shows the data. The question is asked with an ordinary scheme, usually a `radio` with real / bogus / unsure on keyboard shortcuts.

## Overview

- **Reading:** astropy (BSD-3-Clause) on the server. Install it with `pip install 'potato-annotation[astro]'`. A config that uses `fits_cutout` without astropy installed fails at startup with that command in the message. astropy is imported when the first FITS file is read, not at boot.
- **Formats:** `.fits`, `.fit`, `.fts`, and the same names gzipped (`.fits.gz`). The first HDU holding a 2-D (or larger) image is used, or the one named with `hdu`. Of a cube, the first plane is shown.
- **Cutouts:** around a position in FITS pixels (`x`, `y`) or in sky coordinates (`ra`, `dec`, degrees or sexagesimal), with a size in pixels or as an angle (`"40 arcsec"`). Only the rows of the cutout are read from an uncompressed file.
- **Scaling:** an interval (`minmax`, `zscale`, `percentile`) and a stretch (`linear`, `sqrt`, `log`, `asinh`), set for the display, for one panel, for one item, or for one image of one item.
- **Caching:** each converted cutout is written to `<task_dir>/.potato_cache/fits/` as a PNG and a JSON file, keyed by the file's path, size, modification time and the scaling options. An unchanged file is converted once; an edited file or a new stretch makes a new entry. The cache keeps the 4,000 most recently used entries.
- **Viewer:** the panels share zoom, pan and one crosshair. North and east arrows come from the WCS. Blank (NaN) pixels and the part of a cutout that falls off the image edge are transparent and show as a checkerboard.
- **Light curve:** drawn with Plotly (MIT, already shipped with Potato, loaded only for items that have one). Magnitudes run brighter-up; upper limits are open downward triangles; the science image's `MJD-OBS` is marked as "this image". The points are also in a table below the plot.
- **Offline:** nothing is fetched from outside the Potato server.

## Configuration

```yaml
media_directory: media

instance_display:
  fields:
    - key: candidate
      type: fits_cutout
      label: "Cutouts"
      display_options:
        size: 48                 # default cutout size when an item gives none
        interval: zscale
        stretch: linear
        panels:
          - key: science
            label: Science
          - key: reference
            label: Reference
          - key: difference
            label: Difference

annotation_schemes:
  - annotation_type: radio
    name: vetting
    description: "Is this a real astrophysical transient?"
    labels:
      - name: "Real"
        key_value: "r"
      - name: "Bogus"
        key_value: "b"
      - name: "Unsure"
        key_value: "u"
    label_requirement:
      required: true
```

An item:

```json
{
  "id": "cand-001",
  "candidate": {
    "science": "cutouts/cand-001_sci.fits",
    "reference": "cutouts/cand-001_ref.fits",
    "difference": "cutouts/cand-001_diff.fits",
    "ra": 150.11920, "dec": 2.20583,
    "size": 48,
    "light_curve": "lightcurves/cand-001.csv"
  }
}
```

A field holding just a path shows one image (for morphology classification):

```json
{"id": "gal-17", "image": "galaxies/gal-17.fits"}
```

### Display options

| Option | Default | Meaning |
|---|---|---|
| `panels` | science, reference, difference (those the item has), else `image` | List of `{key, label}`: which keys of the item's mapping to show, in order. A panel may also set any scaling option below. At most 6. |
| `size` | none | Cutout size when the item gives none: pixels (`48`) or an angle (`"30 arcsec"`, `"0.5 arcmin"`, `"0.01 deg"`). With a position and no size anywhere, 64 pixels. |
| `interval` | `zscale` | `minmax`, `zscale` (IRAF's zscale, as in ds9) or `percentile`. |
| `percentile` | `99.5` | Share of pixels kept inside the limits with `interval: percentile`. |
| `stretch` | `linear` | `linear`, `sqrt`, `log` or `asinh`. |
| `asinh_a` | `0.1` | The `a` parameter of the asinh stretch (smaller is more compressed). |
| `log_a` | `1000` | The `a` parameter of the log stretch. |
| `invert` | `false` | Dark sources on a light background. |
| `hdu` | first image HDU | HDU number (0 is the primary) or `EXTNAME`. |
| `max_file_mb` | `100` | Largest FITS file read, compressed or not. |
| `max_image_pixels` | `25000000` | Largest image shown whole (no position given). Larger images need a position and size. A whole image over 1,024 pixels on a side is block-averaged down. |
| `light_curve` | `true` | Draw the item's light curve when it has one. |
| `light_curve_columns` | detected | Column names by role: `time`, `mag`, `err`, `band`, `limit`. Without it the columns are found by common names (`mjd`/`time`/`jd`, `mag`/`flux`, `magerr`/`err`, `band`/`filter`, `limit`/`diffmaglim`). |
| `light_curve_units` | `mag` | `mag` (brighter is up) or `flux`. |
| `light_curve_height` | `260` | Plot height in pixels. |
| `time_label` | `MJD` | Time axis title. |
| `crosshair` | `true` | Show the shared crosshair. |
| `compass` | `true` | Show north and east arrows. |
| `panel_size` | `18rem` (one panel: `30rem`) | Largest width of a panel, as a CSS length. |

All values are checked when the server starts; an unknown option or a bad value stops it with a message naming the key.

### Item keys

| Key | Meaning |
|---|---|
| `science`, `reference`, `difference`, `image`, or any key a `panels` entry names | A FITS path in the media directory, or a mapping `{path: ..., stretch: ..., interval: ...}` to scale that image differently. |
| `ra`, `dec` | Cutout centre in degrees, or as sexagesimal text (`"10:00:28.6"`, `"+02:12:21"`). Read as ICRS and converted to the image's own frame (FK5, galactic) when it differs. |
| `x`, `y` | Cutout centre in FITS pixels: the centre of the first pixel is `(1, 1)`, as in ds9 and in `CRPIX`. |
| `size` | Cutout size, as for the display option. |
| `stretch`, `interval`, `percentile`, `asinh_a`, `log_a`, `invert`, `hdu` | Scaling for this item's images. |
| `light_curve` | A CSV, TSV or JSON file in the media directory, or a list of points (`[{"mjd": ..., "band": "g", "mag": ..., "magerr": ...}]`). |
| `epoch` | Time to mark on the light curve, instead of the science image's `MJD-OBS`. |

Precedence, lowest first: display options, the `panels` entry, the item, the item's mapping for that image.

### Light curve files

```csv
mjd,band,mag,magerr,limit
60600.0,g,20.21,0.07,
60603.0,g,19.37,0.05,
60570.0,r,,,21.3
```

A row with a value is a detection. A row with no value and a `limit` is an upper limit. Rows with no usable time are skipped and counted. Files over 2 MB, or past 20,000 rows, are refused or cut.

## Viewer controls

| Action | Effect |
|---|---|
| Move the pointer over a cutout | Crosshair on every panel; readout of RA, Dec (sexagesimal and degrees), the FITS pixel of the original image, and the panel |
| Click or tap | Pins the crosshair (click again, or Escape, to release) |
| **+** / **−** / **Reset** buttons | Zoom all panels together, or return to 1× |
| Ctrl/Cmd + wheel, or a trackpad pinch | Zoom at the pointer |
| Drag (when zoomed) | Pan all panels together |
| Tab to a cutout, then arrow keys | Move the crosshair one pixel; **+**, **−** zoom; **0** resets |

The annotation keys (here R, B, U) keep working while a cutout has focus. Arrow keys move the crosshair only while a cutout has focus; elsewhere they move between items as usual.

When the panels are not on one pixel grid (different sizes, or centres more than half a pixel apart on the sky), a note says so and the crosshair is placed by sky position, using each panel's linear TAN WCS.

## The WCS sent to the browser

For each cutout the server sends the PNG's URL and a WCS description: the cutout's `CRPIX`, `CRVAL` and CD matrix, the pixel scale, the north and east directions, and a grid of sky positions (as unit vectors) sampled every 16 output pixels across the cutout. The readout interpolates that grid, so it follows any projection astropy reads, SIP distortion included. Interpolating unit vectors rather than RA and Dec keeps the readout continuous across RA 0/360 and near the poles. Galactic images are labelled `l` and `b`.

## Decision trees (Galaxy Zoo style)

A morphology tree is a set of questions gated with [display logic](../../configuration/conditional_logic.md). A hidden question keeps its answer, and a question's visibility does not depend on whether the question it follows is visible. So each condition must name the whole path from the first question, joined with `all`; otherwise changing an early answer leaves later questions on screen.

```yaml
annotation_schemes:
  - annotation_type: radio
    name: shape
    description: "Is the galaxy simply smooth and rounded, with no sign of a disk?"
    humanize_labels: false
    labels: ["Smooth", "Features or a disk", "Star or artefact"]

  - annotation_type: radio
    name: edge_on
    description: "Could this be a disk viewed edge-on?"
    labels: ["Yes", "No"]
    display_logic:
      show_when:
        - schema: shape
          operator: equals
          value: "Features or a disk"

  - annotation_type: radio
    name: bulge_edge_on
    description: "Does the galaxy have a bulge at its centre? If so, what shape?"
    humanize_labels: false
    labels: ["Rounded", "Boxy", "No bulge"]
    display_logic:
      show_when:
        - all:
            - schema: shape
              operator: equals
              value: "Features or a disk"
            - schema: edge_on
              operator: equals
              value: "Yes"

  - annotation_type: radio
    name: spiral
    description: "Is there any sign of a spiral arm pattern?"
    labels: ["Yes", "No"]
    display_logic:
      show_when:
        - all:
            - schema: shape
              operator: equals
              value: "Features or a disk"
            - schema: edge_on
              operator: equals
              value: "No"
```

Quote `"Yes"` and `"No"`: unquoted, YAML reads them as booleans. The example project below has a tree of this kind for the host of each real candidate. A Zooniverse workflow with branching tasks can be imported instead; see [Coming from Zooniverse](../../guides/coming-from-zooniverse.md).

## Export

The display stores nothing. Answers are those of the schemes on the page (the radio's label, the tree's answers) and export as usual. Hidden tree questions that were answered and then hidden are kept and marked stale, as described in the display logic page.

## Example

`examples/image/astronomy-real-bogus/` has four synthetic candidates (a supernova in a disk galaxy, a subtraction dipole, a cosmic ray, a hostless point source), each with three 96 × 96 FITS images on one TAN WCS at 1″/pixel and a light curve. `generate_data.py` rewrites them.

```bash
pip install 'potato-annotation[astro]'
python potato/flask_server.py start examples/image/astronomy-real-bogus/config.yaml -p 8000
```

## Troubleshooting

| Message | Cause |
|---|---|
| `fits_cutout reads FITS files with astropy, which is not installed` | Run `pip install 'potato-annotation[astro]'`. |
| `... has no image HDU, so there is nothing to draw. Its HDUs: ...` | The file holds only tables or an empty primary HDU. The message lists each HDU; set `hdu` if the image is in one of them under another shape. |
| `... is not in the media directory` | Paths are relative to `media_directory`. Paths outside it, and URLs, are refused. |
| `The cutout position ... is outside ...` | The position does not fall on this image. Check that `ra`/`dec` are in degrees (or sexagesimal text) and that `x`/`y` count from 1. |
| `... has no celestial WCS, so a position in ra/dec cannot be found` | Give `x` and `y`, or fix the header's WCS keywords. |
| `... over the 100 MB limit (max_file_mb)` | Cut the image down first, or raise `max_file_mb`. |
| `... more than the 25,000,000 pixel limit for showing a whole image` | Give a position and a size, or raise `max_image_pixels`. |
| A panel looks saturated | zscale is meant for faint sources. Try `interval: percentile` with `stretch: asinh` for that panel or item. |
| A cutout shows a checkerboard on one side | The cutout runs off the image edge, or those pixels are NaN or `BLANK`. The status line under the panels says which. |

The cache can be deleted at any time (`rm -r .potato_cache/fits` in the task directory); entries are rebuilt on the next page view.

## Related

- [Astronomy guide](../../guides/astronomy.md): transient vetting and morphology tasks end to end
- [Conditional logic](../../configuration/conditional_logic.md)
- [Instance display](../instance_display.md)
- [Genome loci](genome_loci.md), another viewer display with the same real/artifact pattern

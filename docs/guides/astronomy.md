# Astronomy: Vetting Transients and Classifying Morphology

This guide covers two image tasks: deciding whether a transient candidate from a difference-imaging pipeline is real or bogus, and classifying galaxy morphology with a branching question tree. Both use the [`fits_cutout`](../annotation-types/science/astronomy.md) display, which reads FITS files on the server, so the annotator's browser only receives PNG cutouts and the coordinates that go with them.

Install the FITS reader first:

```bash
pip install 'potato-annotation[astro]'
```

## Preparing the files

Put the FITS files under the project's `media/` folder. Plain and gzipped files (`.fits`, `.fit`, `.fts`, `.fits.gz`) both work.

- **Cutouts or full frames.** Either give Potato small stamps that are already centred on the candidate, or full images plus a position per item; the server cuts out the region. Only the rows of the cutout are read from an uncompressed file, so full frames up to `max_file_mb` (100 MB by default) are fine.
- **Triplets on one grid.** Survey pipelines warp the reference onto the science image before subtracting, so the three images share a pixel grid. Keep them that way and the crosshair marks the same pixel in each. When they are not aligned, the display says so and places the crosshair by sky position.
- **WCS.** The RA/Dec readout, the north and east arrows and positions given as `ra`/`dec` all need a celestial WCS in the header. Without one, positions must be given as FITS pixels (`x`, `y`, counting from 1) and the readout shows pixels only.
- **Survey alert stamps.** Alert streams that carry their stamps as gzipped FITS bytes can be written out as `.fits.gz` files unchanged.
- **Light curves.** One CSV per candidate with a time column, a band, a magnitude, its error, and an upper limit for non-detections:

```csv
mjd,band,mag,magerr,limit
60598.0,r,20.81,0.21,
60601.0,r,19.40,0.06,
60570.0,g,,,21.3
```

Make the data file one row per candidate:

```json
{
  "id": "cand-001",
  "summary": "cand-001: ra 150.11920, dec +2.20583, band r",
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

## Transient vetting

```yaml
media_directory: media
data_files: [data/candidates.json]
item_properties: {id_key: id, text_key: summary}

instance_display:
  fields:
    - key: summary
      type: text
      label: "Candidate"
    - key: candidate
      type: fits_cutout
      label: "Cutouts"
      display_options:
        size: 48
        interval: zscale
        stretch: linear

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

  - annotation_type: multiselect
    name: bogus_reason
    description: "What makes it bogus? (select all that apply)"
    humanize_labels: false
    labels:
      - "Subtraction residual (dipole)"
      - "Cosmic ray or hot pixel"
      - "Satellite or asteroid trail"
      - "Bad column or image edge"
      - "Other"
    display_logic:
      show_when:
        - schema: vetting
          operator: equals
          value: "Bogus"
```

What the annotator looks for:

| In the difference image | Usually |
|---|---|
| A round source with the image's PSF, present in the science image and absent in the reference | Real |
| A positive and a negative lobe side by side | Bogus: misaligned subtraction of a star or galaxy core |
| A single sharp pixel or a few pixels, narrower than the PSF | Bogus: cosmic ray or hot pixel |
| A streak | Bogus: satellite, aircraft or a fast mover |
| A source on a column defect or at the image edge | Bogus |

The light curve helps: a rise and decline over days to weeks in several bands points to a real transient; a single detection between upper limits is weaker evidence. The epoch of the science image is marked on the plot.

Zoom and the crosshair are shared by the three panels. Hover (or tap on a phone) to read RA, Dec and the FITS pixel; Ctrl/Cmd + wheel zooms at the pointer; drag pans when zoomed. After answering with R, B or U, the arrow keys or the Next button move to the next candidate.

### Scaling

The default, zscale with a linear stretch, suits faint point sources on sky noise. It saturates bright hosts: for a candidate in a bright galaxy, set a percentile interval and an asinh stretch for the direct images of that item only.

```json
"science":   {"path": "cutouts/cand-001_sci.fits", "interval": "percentile", "stretch": "asinh"},
"reference": {"path": "cutouts/cand-001_ref.fits", "interval": "percentile", "stretch": "asinh"},
"difference": "cutouts/cand-001_diff.fits"
```

The same keys at the top of the item apply to all its images; under a `panels` entry in the config they apply to that panel for every item.

## Morphology classification

For morphology, each item is one galaxy image:

```yaml
instance_display:
  fields:
    - key: image
      type: fits_cutout
      label: "Galaxy"
      display_options:
        interval: percentile
        percentile: 99.5
        stretch: asinh
        size: "40 arcsec"
```

```json
{"id": "gal-17", "image": {"image": "galaxies/gal-17.fits", "ra": 185.7286, "dec": 15.8222}}
```

The questions form a tree, as in Galaxy Zoo: each answer opens the next question. Build it with [display logic](../configuration/conditional_logic.md), and write each condition as the full path from the first question, joined with `all`. A question that is hidden keeps its answer, and visibility does not cascade, so a condition that names only its parent leaves a later question showing after an earlier answer changes. The [astronomy display page](../annotation-types/science/astronomy.md#decision-trees-galaxy-zoo-style) has a worked tree.

Galaxy Zoo projects run on Zooniverse can be brought across with the Zooniverse importer: branching tasks become display logic. See [Coming from Zooniverse](coming-from-zooniverse.md).

## Results

The display records nothing itself; the answers are those of the schemes. With `export_annotation_format: jsonl` each line has the candidate id and, for example, `vetting: Real`, the bogus reasons, and the host tree answers. To compute agreement between annotators on the real/bogus call, see the IAA pages in the admin dashboard.

## Example project

`examples/image/astronomy-real-bogus/` has four synthetic candidates, a triplet and a light curve for each, and the host tree. Run it from the repository root:

```bash
python potato/flask_server.py start examples/image/astronomy-real-bogus/config.yaml -p 8000
```

## Not included

The display shows FITS images converted on the server. It does not draw HiPS surveys or catalogue overlays in the browser (an Aladin Lite viewer may be added once a stable non-beta 3.9 release exists), and it does not edit FITS files.

## Related

- [FITS cutout display](../annotation-types/science/astronomy.md): every option
- [Conditional logic](../configuration/conditional_logic.md)
- [Coming from Zooniverse](coming-from-zooniverse.md)
- [Genomics variant review](genomics-variant-review.md): the same real/artifact pattern on reads

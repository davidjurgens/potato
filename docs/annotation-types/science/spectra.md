# Spectra and peak picking

The `spectrum` display draws one NMR, IR, Raman, UV-Vis or mass spectrum per item. The `peak_picking` scheme records the peaks an annotator picks on it, the regions they integrate, and which automatic suggestions they accepted or rejected.

## Overview

- **Engine:** Plotly 2.27.0 (MIT), committed with Potato at `potato/static/vendor/plotly-2.27.0.min.js`. It is loaded only on pages with a spectrum. It draws SVG, so it does not need WebGL.
- **Files are parsed on the server.** The browser receives at most `max_points` points (4,000 by default). Each bucket of the original keeps its lowest and highest point, so narrow lines keep their full height. When the annotator zooms in, the page fetches every point in the visible range from `/api/spectrum/range`.
- **Formats:** JCAMP-DX (`.jdx`, `.dx`, `.jcamp`, read by Potato itself), mzML (`.mzML`, through pyteomics, an optional extra), and two-column text (`.csv`, `.tsv`, `.txt`, `.xy`). A spectrum can also be written inline in the item.
- **Axis conventions:** NMR chemical shift and IR wavenumber axes run high to low, left to right. NMR spectra stored in Hz are converted to ppm using the file's `.OBSERVE FREQUENCY`.
- **Offline:** nothing is fetched from outside the Potato server. A spectrum named by URL is refused.

NMRium and ChemSpectra are not used. NMRium's dependencies carry CC BY-NC-SA terms, and ChemSpectra's npm and repository licences disagree.

## Annotating

The toolbar above the plot has three modes:

| Mode | Click | Drag |
|---|---|---|
| **Pick** (default) | Picks the peak under the pointer. Clicking a picked peak removes it, and clicking a suggestion accepts it. | Zooms to the dragged box |
| **Pan** | Nothing | Moves along the spectrum |
| **Integrate** (NMR by default) | Removes the region under the pointer | Integrates the dragged x range |

Double-click the plot, or press **Reset view**, to zoom back out. On a touch screen, a tap works like a click.

With `snap: true` (the default), a click picks the local maximum within a few pixels of the pointer, or the local minimum for a transmittance spectrum, so the annotator does not have to hit the top of a line exactly. Zoom in to separate the lines of a multiplet before picking them.

Below the plot, the `peak_picking` scheme lists:

- **Suggested peaks**, drawn as open orange triangles, each with **Accept** and **Reject**, plus **Accept all** and **Reject all**. Rejected suggestions appear as small buttons with a ↺ mark; pressing one restores the suggestion.
- **Peaks**, with position, intensity, source (*suggested* or *added*), one input per configured field (an assignment, a multiplicity), and **Remove**. Picked peaks are drawn as filled triangles, labelled on the plot with their field values.
- **Integrals**, with range, integral, the value relative to the first region (which reads 1.00), and the region fields.
- **Add a peak at**: type a position and press Enter. This picks a peak without the mouse; a position that matches a suggestion accepts it.

All controls are buttons and form fields, so a review can be done entirely from the keyboard.

## Configuration

```yaml
media_directory: media

instance_display:
  fields:
    - key: spectrum                # item field naming the file
      type: spectrum
      label: "Spectrum"
      display_options:
        prepick:                   # suggested peaks; off unless set
          method: detect
          prominence: 0.05
          max_peaks: 30
        integrate: auto            # on for NMR

annotation_schemes:
  - annotation_type: peak_picking
    name: peaks
    description: "Pick the peaks and describe each one"
    viewer_field: spectrum         # the spectrum field above
    peak_fields:
      - name: assignment
        type: text
        placeholder: "e.g. OCH2, C=O"
      - name: multiplicity
        type: choice
        options: [s, d, t, q, m, br]
    region_fields:
      - name: protons
        label: "nH"
    min_peaks: 1
    require_review: true
```

### Display options (`type: spectrum`)

| Option | Default | Description |
|---|---|---|
| `spectrum_type` | `auto` | `nmr`, `ir`, `raman`, `uv`, `ms` or `other`. `auto` reads the JCAMP-DX `DATA TYPE` or infers it from the x units. |
| `x_reversed` | `auto` | `true` draws x high to low. `auto` reverses NMR (ppm, Hz) and IR (cm⁻¹). |
| `x_label`, `y_label` | from units | Axis titles. The defaults come from the file's units, for example "Chemical shift (ppm)" or "Wavenumber (cm⁻¹)". |
| `mode` | `auto` | `line` or `sticks`. `auto` draws a JCAMP-DX peak table or a centroided mzML scan as sticks. |
| `peak_direction` | `auto` | `max` or `min`. `auto` uses `min` for transmittance and reflectance. |
| `integrate` | `auto` | Offers Integrate mode. `auto` turns it on for NMR line spectra. |
| `prepick` | off | `true`, or a mapping with `method`, `prominence`, `max_peaks` and `min_distance` (see below). |
| `snap` | `true` | A click picks the nearby extreme rather than the exact pointer position. |
| `max_points` | `4000` | Points sent to the browser (200 to 100,000). |
| `max_file_mb` | `50` | Spectrum files larger than this are refused (at most 500). |
| `scan`, `index` | none | Which spectrum of an mzML run to show, for every item. An item can set its own. |
| `block` | none | Which block of a compound JCAMP-DX file to show (0-based, counting blocks that hold data). |
| `height` | `380` | Plot height (pixels or a CSS length). |

`prepick` settings:

| Key | Default | Description |
|---|---|---|
| `method` | `auto` | `detect` runs peak detection. `file` uses the JCAMP-DX `PEAK TABLE`. `item` uses the item's own `peaks` list. `auto` picks `item`, then `file`, then `detect`, using the first that is available. |
| `prominence` | `0.05` | For `detect`: how far a peak must stand above its surroundings, as a fraction of the y range. For sticks it is the minimum height as a fraction of the tallest. |
| `max_peaks` | `40` | At most this many suggestions, keeping the most prominent. |
| `min_distance` | none | For `detect`: minimum spacing between suggestions, in x units. |

Detection uses `scipy.signal.find_peaks` with a prominence threshold, run on the full-resolution data. scipy is a core dependency, so no extra install is needed. Suggestions are off by default because they can anchor annotators. Turn them on when that matters less than the time they save, or when you are measuring acceptance rates.

### Scheme options (`annotation_type: peak_picking`)

| Option | Default | Description |
|---|---|---|
| `viewer_field` | required | The `instance_display` field of the `spectrum` display. |
| `peak_fields` | one text field, `label` | Inputs per peak: `{name, type: text \| choice, options, required, placeholder, label}`. `[]` gives none. |
| `region_fields` | one text field, `label` | The same, per integrated region. |
| `min_peaks` | none | The item counts as incomplete until this many peaks are picked. Enforced when the scheme is required (`label_requirement: {required: true}`). |
| `max_peaks` | none | Picking more is refused, with a message. |
| `require_review` | `false` | The item counts as incomplete until every suggestion has been accepted or rejected. Enforced when the scheme is required (`label_requirement: {required: true}`). |
| `allow_manual` | `true` | `false` allows peaks to come only from the suggestions, and removes **Add a peak at**. |

A field with `required: true` must be filled in for every peak (or region) before the item counts as complete.

## Data format

The item field names a file in the media directory, or holds the spectrum:

```json
{"id": "e1", "spectrum": "spectra/ethyl_acetate_1h.jdx"}
{"id": "r7", "spectrum": {"file": "runs/sample1.mzML", "scan": 1043}}
{"id": "e2", "spectrum": {"file": "spectra/e2.jdx", "peaks": [4.12, {"x": 2.04, "label": "CH3CO"}]}}
{"id": "s1", "spectrum": {"x": [0.5, 1.0, 1.5], "y": [3, 40, 2], "x_units": "PPM", "kind": "nmr"}}
```

A mapping takes `file` (or `path`), `scan`, `index` and `block` (selection), `peaks` (suggestions, used with `prepick: true`), or inline `x`, `y`, `x_units`, `y_units`, `kind`, `title` and `sticks`.

### JCAMP-DX

Potato reads the following itself, without any library:

- `##XYDATA=(X++(Y..Y))` in every ASDF form: AFFN and PAC numbers, and SQZ, DIF and DUP compression. The DIF Y-check value is verified and dropped, and a failed check is reported as corrupt data.
- `##XYPOINTS=(XY..XY)` and `##PEAK TABLE=(XY..XY)` or `(XYW..XYW)`. A file holding only a peak table (most mass spectra) is drawn as sticks. A peak table next to XYDATA is the file's peak list, which `prepick: {method: file}` offers as suggestions.
- `##NTUPLES` files with a `##DATA TABLE=(X++(R..R)), XYDATA` page, as written by Bruker and MestReNova. Only the real page is read.
- Compound files (`##BLOCKS=`), where `block` picks one.
- `XFACTOR`, `YFACTOR`, `FIRSTX`, `LASTX`, `NPOINTS` and `DELTAX`, and `.OBSERVE FREQUENCY` for the Hz to ppm conversion.

Not read: FIDs without an abscissa, 2D NMR, and JCAMP-CS structures.

### mzML

mzML needs the `spectra` extra:

```bash
pip install 'potato-annotation[spectra]'
```

This installs pyteomics (Apache-2.0) and psims (Apache-2.0; pyteomics 5 needs it to read PSI formats), plus lxml. One spectrum is shown per item, chosen by `index` (its 0-based position in the run) or `scan` (the `scan=N` part of the native id). With neither, the first spectrum is shown. A centroided scan is drawn as sticks and a profile scan as a line. A file that declares a DOCTYPE or entities is refused before parsing; mzML does not use either.

### CSV

Two columns, x then y, separated by commas, tabs, semicolons or spaces. Lines starting with `#` are comments. A header row is optional, and its parentheses set the units: `shift (ppm)`, `wavenumber (cm-1)`, `transmittance (%T)`.

## Stored answer

The scheme stores the display's selection as JSON in one hidden input:

```json
{"viewer": "spectrum",
 "items": [{"kind": "peak", "x": 2.0399, "y": 3003, "source": "auto", "width": 0.0031,
            "fields": {"assignment": "CH3CO", "multiplicity": "s"}},
           {"kind": "peak", "x": 7.26, "y": 132, "source": "manual"},
           {"kind": "region", "from": 1.969, "to": 2.120, "integral": 15.77,
            "fields": {"protons": "3"}}],
 "rejected": [4.1464]}
```

`source` is `auto` for an accepted suggestion and `manual` for a peak the annotator added. `width` is the full width at half prominence of a detected peak, in x units. `rejected` lists the positions of suggestions the annotator turned down, so an unreviewed suggestion can be told apart from a rejected one. `integral` is a trapezoid integral over every original point between `from` and `to`, with no baseline correction.

## Export

```bash
python -m potato.export --config config.yaml --format peak_table --output out/
```

This writes `peaks.csv` and `peaks.jsonl`; `--option format=csv` or `--option format=jsonl` writes only one. There is one row per peak, region and rejected suggestion:

| Column | Description |
|---|---|
| `user_id`, `instance_id`, `schema` | Who, which item, which scheme |
| `kind` | `peak`, `region` or `rejected` |
| `x`, `y`, `width` | Peak position, intensity and width (when detected) |
| `from`, `to`, `integral`, `relative` | Region range, integral, and integral relative to the first region |
| `source` | `auto` (accepted suggestion) or `manual` |
| `label` | The fields joined with " / " |
| one column per field | `assignment`, `multiplicity`, ... (prefixed `field_` if a name clashes with a column above) |

## Spectroscopy tasks

For structure correction, name to structure and atom marking, see the [chemistry guide](../../guides/chemistry.md).

- **1H NMR:** keep `integrate: auto`, add a `multiplicity` choice field and an `nH` region field, and ask annotators to integrate each multiplet. Integrals are relative to the first region, so say which signal to integrate first if you want a fixed reference. Integrals include the baseline, so a region drawn wider than its multiplet reads high.
- **13C NMR, IR:** a text field for the assignment is usually enough. Set `prepick: {method: detect}` with a higher `prominence` (0.1 or more) for noisy IR spectra.
- **MS:** a JCAMP-DX peak table or a centroided mzML scan is drawn as sticks, and a click picks the nearest stick. Use `prepick: {method: file, max_peaks: 20}` to suggest the tallest ions.
- **Checking a model's peak list:** put the model's peaks in the item (`{"file": ..., "peaks": [...]}`) with `prepick: true`, `require_review: true` and, if annotators should not add peaks, `allow_manual: false`. The export's `source` and `rejected` rows then give the acceptance rate per peak.
- **Peak to atom assignment** with a molecule display beside the spectrum is planned. The spectrum's selection API (`window.potatoViewers[field].getSelection()`, `setSelection()`, `onSelectionChange()`) is what it will build on.

## Example

```bash
python potato/flask_server.py start examples/advanced/spectrum-peak-picking/config.yaml -p 8000
```

The example has two synthetic 1H NMR spectra as DIFDUP-compressed JCAMP-DX and one IR spectrum as CSV, with detected suggestions and `require_review` on. `generate_spectra.py` in the example directory regenerates them. The data is invented.

## Troubleshooting

- **"is not in the media directory"**: name the file relative to `media_directory`. Paths that leave the media directory are refused.
- **"is a URL"**: Potato does not download spectra. Copy the file into the media directory.
- **"Reading mzML needs pyteomics and psims"**: install the `spectra` extra.
- **"Y-check failed"**: the JCAMP-DX compressed data is corrupt or was cut short.
- **Only every few points are drawn**: this is expected for large spectra. Zoom in and the page fetches every point in the visible range.
- **No suggestions**: `prepick` is off unless set. With it on, lower `prominence`.

## Related

- [Protein structures](protein_structures.md) and [genome loci](genome_loci.md) use the same viewer selection API.
- [Chemistry guide](../../guides/chemistry.md) covers the structure editor and the molecule display.
- [Instance display](../instance_display.md) lists every display type.

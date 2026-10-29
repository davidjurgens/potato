# Bioacoustics: Reviewing Raven, Audacity and BirdNET Boxes

This guide covers checking and correcting time-frequency boxes on recordings
when the boxes come from Raven, Audacity or BirdNET-Analyzer. You import the
tables with their recordings, annotators correct the boxes on a spectrogram in
a [`spectrogram_annotation`](../annotation-types/multimedia/spectrogram_annotation.md)
scheme, and you export the corrected boxes back to Raven or Audacity.

## Import

```bash
# A folder of Raven selection tables with the recordings beside them
potato import -i recordings/ -o review-project/

# BirdNET-Analyzer output, keeping detections with confidence 0.5 or more
potato import -i birdnet-output/ -f birdnet --min-confidence 0.5 -o review-project/

# One Audacity label file (site3_0612.txt next to site3_0612.wav)
potato import -i site3_0612.txt -f audacity_labels -o review-project/
```

`-i` is one table or a folder of them. The format is detected from the
content; pass `-f raven`, `-f audacity_labels` (or `-f audacity`) or
`-f birdnet` to choose explicitly.

Each recording becomes one item. The recording is copied into the project's
`media/` folder, and every row of its table becomes a box pre-annotation, so
annotators open the clip with the boxes drawn. A table is matched to its
recording by name: `site3_0612.Table.1.selections.txt`,
`site3_0612.BirdNET.selection.table.txt`, `site3_0612.BirdNET.results.csv` and
`site3_0612.txt` all belong to `site3_0612.wav` (or `.flac`, `.mp3`, `.ogg`,
`.m4a`, `.aac`, `.opus`, `.webm`). A table that covers several recordings
names them in a `Begin File`, `Begin Path` or `File` column, and its rows are
split by that column. A recording that cannot be found is reported, and its
item has no audio.

The generated scheme's labels are the labels found in the tables. Add the
rest of your species or call-type list to `labels` in `config.yaml`, so
annotators can label calls the source missed.

### Raven selection tables

| Raven column | Potato |
|---|---|
| `Begin Time (s)`, `End Time (s)` | `start_s`, `end_s` |
| `Low Freq (Hz)`, `High Freq (Hz)` | `low_hz`, `high_hz` |
| `Selection`, `View` | Rows with the same selection number (Raven writes one per view, such as `Waveform 1` and `Spectrogram 1`) become one box; the `Spectrogram` row is used |
| `Channel` | Kept on the box when it is not 1 |
| `Begin File` / `Begin Path`, `File Offset (s)` | The recording, and the start time within it, in a multi-file table |
| `Confidence` | Kept on the box; `--min-confidence` filters on it |
| `Box Source` | Kept as an attribute of the box; written by Potato's own `raven` export. The box is still an import in the new project |
| An annotation column | The label |

The label comes from `--label-column NAME` when given. Otherwise it comes from
the first of `Annotation`, `Species`, `Label`, `Class`, `Scientific Name`,
`Common Name`, `Species Code`, `Call Type`, `Type` and `Sound Type` that the
table has, and failing that, from the first column that is not one of Raven's
measurement columns. A row with an empty label is labelled `call`.

### Audacity label tracks

Each line is `start<TAB>end<TAB>label`. A label with a spectral selection is
followed by a line that starts with a backslash: `\<TAB>low<TAB>high`. Labels
without that line, including point labels, become boxes over all frequencies
(`low_hz` and `high_hz` are `null`).

### BirdNET-Analyzer output

Both of BirdNET-Analyzer's table formats are read:

- the Raven selection table (`*.BirdNET.selection.table.txt`): the Raven
  columns above, with `Common Name`, `Species Code` and `Confidence`. The
  label is the `Scientific Name` column when the table has one, otherwise
  `Common Name`;
- the CSV (`*.BirdNET.results.csv`): `Start (s)`, `End (s)`,
  `Scientific name`, `Common name`, `Confidence`, and in newer versions
  `File`. The label is the scientific name. These rows have no frequency
  range, so they import as boxes over all frequencies.

Use `--label-column "Common name"` (CSV) or `--label-column "Common Name"`
(Raven table) for common names. Rows below `--min-confidence` (default 0.1)
are left out, and the import summary says how many. BirdNET 2.4 writes a
`nocall` row for a file with no detections; those rows are left out and
counted too, so `nocall` never becomes a label. BirdNET boxes are stored
with `"source": "ai"`, `"ai_model": "BirdNET"` and their confidence, and the
page draws them with a dashed border until an annotator changes them.

### Rows that cannot be read

A row whose time is not a number, such as `3,5` written with a decimal comma
or a word, is left out. The import summary counts these rows, and a warning
names the file, the line and the value. A row whose end time comes before its
start is kept with the two times swapped, and also gets a warning. A negative
frequency is refused: the box keeps its times and loses that frequency, and a
warning names the row. An Audacity file in which most lines are not label
lines is not imported; the error names the file and the first bad line.

Potato reads BirdNET's output files only. The BirdNET models are licensed
CC BY-NC-SA and are not distributed with Potato; run BirdNET-Analyzer
yourself and import what it writes.

## Review

```bash
python potato/flask_server.py start review-project/config.yaml -p 8000
```

Annotators move, resize, relabel and delete boxes, and draw the calls that
were missed. See [Spectrogram Annotation](../annotation-types/multimedia/spectrogram_annotation.md)
for the controls. An imported box gets `"edited": true` once it is changed,
so the export can tell boxes a reviewer accepted from boxes they corrected.
Clicking Next on a clip without changing anything saves its imported boxes as
the reviewer's answer, as boxes accepted unchanged.

## Export

```bash
python -m potato.export -c review-project/config.yaml -f raven -o export/
python -m potato.export -c review-project/config.yaml -f audacity_labels -o export/
```

`raven` writes one selection table per recording with the columns
`Selection`, `View`, `Channel`, `Begin Time (s)`, `End Time (s)`,
`Low Freq (Hz)`, `High Freq (Hz)`, the label column (`Annotation`, or
`--option label_column=Species`) and, when any box has one, `Confidence`.
`Confidence` is the detector's score only on a box the reviewer kept
unchanged. A box they drew or changed gets 1.0, as in the MegaDetector
export, so a confidence threshold applied later keeps every reviewed box.
When the boxes record where they came from, a `Box Source` column says
which is which: `ai`, `ai (edited)`, `import`, `import (edited)` or `human`.
A box with no frequency range is written from 0 Hz to the recording's
Nyquist frequency, which comes from the item's `sample_rate` (the importer
records it for WAV files) or from the WAV file's header. For other audio
formats, set `max_freq` on the scheme; otherwise `High Freq (Hz)` is left
empty and the export warns.
`audacity_labels` writes one label file per recording, with a spectral line
for every box that has a frequency range. Both name the file after the
recording, so with the audio beside them they open in Raven or Audacity and
can be imported into Potato again. With several annotators the annotator's
name is added (`site3_0612.anna.selections.txt`); `--option annotator=anna`
exports one person.

## Example

`examples/audio/bioacoustics-boxes/` has two synthetic 6-second recordings
with tones and frequency sweeps at known times and frequencies, imported from
the Raven tables in its `source/` folder. The tables have two mistakes to
fix: one recording is missing a downsweep, and in the other a trill is
labelled a whistle.

```bash
python potato/flask_server.py start examples/audio/bioacoustics-boxes/config.yaml -p 8000
```

## Related

- [Spectrogram Annotation](../annotation-types/multimedia/spectrogram_annotation.md)
- [Camera traps](camera-traps.md)
- [Import CLI](../tools/import_cli.md)

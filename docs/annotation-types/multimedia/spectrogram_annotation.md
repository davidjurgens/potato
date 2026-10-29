# Spectrogram Annotation

A `spectrogram_annotation` scheme shows a spectrogram of the item's audio.
Annotators draw time-frequency boxes on it and give each box a label from the
scheme's list, such as species or call types. The scheme is meant for
bioacoustics: bird, bat, frog and marine-mammal calls, where a call is
described by when it starts and ends and by its frequency range.

[`audio_annotation`](audio_annotation.md) marks segments in time only. Use
`spectrogram_annotation` when the frequency range of each event matters, or
when you import boxes from Raven, Audacity or BirdNET-Analyzer
(see [Bioacoustics](../../guides/bioacoustics.md)).

The spectrogram is computed in the browser: the page decodes the audio with
Web Audio and runs a short-time Fourier transform with one column per pixel
of the drawing. No third-party library is loaded, and the server needs no
audio tools.

## Configuration

```yaml
item_properties:
  id_key: id
  text_key: recording

annotation_schemes:
  - annotation_type: spectrogram_annotation
    name: calls
    description: Draw a box around every call and label it
    source_field: audio_url
    labels:
      - name: Turdus migratorius
        color: "#2563eb"
      - name: Cardinalis cardinalis
        color: "#dc2626"
      - unknown
    max_freq: 12000
```

```json
{"id": "site3_0612", "recording": "site3_0612.wav", "audio_url": "/media/site3_0612.wav"}
```

`source_field` names the item field that holds the audio URL. Files in the
project's `media/` folder are served at `/media/<name>`. Any format the
browser can decode works (WAV, FLAC, MP3, Ogg, M4A). For a WAV file the page
reads the sample rate from the file header, so the frequency axis ends at the
recording's own Nyquist frequency. For other formats, give the rate in an
item field named `sample_rate`; without it the browser's own rate is used.

### Options

| Key | Default | Description |
|---|---|---|
| `labels` | (required) | Label names, or `{name, color, key_value}` objects. Labels 1 to 9 get the keys `1`–`9` unless `key_value` sets another key. Quote names that YAML would read as `true`, `false` or a number |
| `source_field` | `audio_url` | Item field holding the audio URL |
| `min_freq` | `0` | Lowest frequency shown, in Hz |
| `max_freq` | Nyquist frequency | Highest frequency shown, in Hz |
| `fft_size` | `1024` | FFT window length in samples: 256, 512, 1024, 2048 or 4096. Larger windows resolve frequency more finely and time more coarsely |
| `colormap` | `viridis` | `viridis`, `magma` or `grayscale` (dark = loud) |
| `height` | `280` | Height of the spectrogram in pixels |
| `min_boxes` | `0` | Boxes required before the item counts as done |
| `max_boxes` | none | Most boxes allowed on one item |
| `instructions` | none | Text shown under the description |
| `label_requirement` | none | `required: true` makes the scheme count as unanswered until the annotator has saved it once. Saving with no boxes counts as an answer; use `min_boxes` to require boxes |

## Using it

| Action | Mouse or touch | Keyboard (focus in the widget) |
|---|---|---|
| Draw a box | Drag on empty spectrogram | `N` adds a box at the play position |
| Choose the label for new boxes | Click a label button | `1`–`9` |
| Relabel a box | Select it, then click a label button, or use the box's menu in the list | Select it, then `1`–`9` |
| Select a box | Click it | `Tab` to it |
| Move a box | Drag it | Arrow keys |
| Resize a box | Drag its top-left or bottom-right corner | `Shift` + arrow keys (right/left: end time, up/down: top frequency) |
| Delete a box | Delete in the list | `Delete` or `Backspace` |
| Deselect | Click empty spectrogram | `Escape` |
| Play or pause | Play button | `Space` |
| Play one box | Play in the list | `P` |
| Move the play position | Click empty spectrogram | |
| Zoom in time | `+` and `−` buttons (up to 16×), then scroll sideways | |

An arrow key moves a box by 1% of the visible time span, or by 2% of the
frequency range. The list under the spectrogram shows every box with its
times and frequencies, a label menu, and Play and Delete buttons. A box
imported from a detector is drawn with a dashed border and its confidence
next to the label until someone changes it.

## Stored answer

The answer is one JSON list in the scheme's hidden input:

```json
[{"start_s": 0.5, "end_s": 1.1, "low_hz": 2900.0, "high_hz": 3100.0, "label": "whistle"},
 {"start_s": 3.0, "end_s": 3.8, "low_hz": 5900.0, "high_hz": 6600.0, "label": "trill",
  "source": "import", "import_format": "raven", "edited": true}]
```

Times are seconds from the start of the file and frequencies are Hz.
`low_hz` and `high_hz` are `null` for a box that covers all frequencies,
which is what an Audacity label without a spectral selection or a BirdNET CSV
row imports as. Boxes the annotator draws get `"source": "human"`. Imported
boxes keep `source`, `ai_model`, `confidence` and `import_format`, and get
`"edited": true` once they are moved, resized or relabelled.

Pre-annotations use the same list, under the scheme name in the
`pre_annotation` field:

```yaml
pre_annotation:
  enabled: true
  field: predictions
```

```json
{"id": "site3_0612", "audio_url": "/media/site3_0612.wav",
 "predictions": {"calls": [{"start_s": 1.2, "end_s": 1.9, "low_hz": 2500, "high_hz": 6200,
                            "label": "Turdus migratorius", "source": "ai", "ai_model": "BirdNET",
                            "confidence": 0.82}]}}
```

A pre-filled box counts as the annotator's answer. If they click Next without
touching a clip, the pre-filled boxes are saved as their reviewed answer, and
each box keeps `source` (`ai` or `import`) and gets no `edited` flag, so a
review study can count them as accepted unchanged. Entries that are not
boxes (a bare string such as `"a"`, or an object without numeric `start_s`
and `end_s`) are dropped before the page is drawn and logged as a warning, so
they never reach a stored answer. Reversed times are swapped.

## Export

| Format | Output |
|---|---|
| `raven` | One Raven selection table per recording (`<recording>.selections.txt`). The label goes in an `Annotation` column (`--option label_column=Species` renames it) and `Confidence` is written when a box has one: the detector's score on a box kept unchanged, 1.0 on one a reviewer drew or changed. A `Box Source` column (`ai`, `ai (edited)`, `human`, ...) is added when the boxes record where they came from. A box with no frequency range is written from 0 Hz to the Nyquist frequency (from the item's `sample_rate`, or the header of a WAV file in the media directory) or to `max_freq`. Without any of these, `High Freq (Hz)` is left empty and the export warns |
| `audacity_labels` | One Audacity label file per recording (`<recording>.labels.txt`), with a spectral line under each box that has a frequency range |
| `jsonl`, `csv` and the other general formats | The JSON list as the scheme's value |

When more than one person annotated a recording, the file names carry the
annotator (`<recording>.<annotator>.selections.txt`). `--option
annotator=<user>` exports one person only.

```bash
python -m potato.export -c config.yaml -f raven -o export/
python -m potato.export -c config.yaml -f audacity_labels -o export/
```

## Troubleshooting

- **"This item has no audio in its "audio_url" field."** The item has no
  value under `source_field`, or the field holds something other than a
  string.
- **"Could not load the audio (HTTP 404)."** The URL does not resolve. Files
  in `media/` are served at `/media/<name>`; check the name and its case.
- **Empty band at the top of the spectrogram.** The file is not a WAV and the
  item has no `sample_rate`, so the browser decoded it at its own rate. Add
  `sample_rate` to the item or set `max_freq`.
- **Long recordings.** The whole file is decoded in the browser, and the
  spectrogram has at most 4096 columns, so a long recording is drawn coarsely
  in time. Cut recordings into clips of a few minutes or less; zooming
  stretches the drawing rather than recomputing it.

## Related

- [Bioacoustics guide](../../guides/bioacoustics.md): importing Raven,
  Audacity and BirdNET output, and exporting the corrected boxes
- [Audio annotation](audio_annotation.md): time segments on a waveform
- Example: `examples/audio/bioacoustics-boxes/`

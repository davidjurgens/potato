# Time series: signals and interval labels

The `time_series` display draws a multi-channel signal (EEG, polysomnography,
ECG, accelerometers, a light curve) and the `interval_label` scheme labels it:
drag across the plot to label an interval, click to mark a point event, or
step through fixed-length epochs and label each one with a key.

The browser does not download the recording. For the range on screen it asks the
server for at most two values per pixel per channel, so an 8-hour, 10-channel
recording opens about as fast as a 30-second one.

## Quick start

```yaml
instance_display:
  fields:
    - key: signal            # the item field holding the file name
      type: time_series
      label: "Signal"
      display_options:
        window: 30           # seconds on screen

annotation_schemes:
  - annotation_type: interval_label
    name: segments
    description: "Mark artefacts and arousals"
    signal_field: signal     # the time_series field above
    labels:
      - name: artefact
        key_value: "1"
      - name: arousal
        key_value: "2"
        kind: event          # a point, marked by clicking
```

Run the example from the repository root:

```bash
python potato/flask_server.py start examples/advanced/time-series-intervals/config.yaml -p 8000
# sleep staging in 30 s epochs:
python potato/flask_server.py start examples/advanced/time-series-intervals/config-epochs.yaml -p 8000
```

## Item data

The item field named by the display's `key` holds either a file reference or a
small inline object.

### A file

```json
{"id": "night-01", "signal": "psg/night-01.edf"}
```

The reference is resolved like other media: inside `media_directory` first
(`media/` and `/media/` prefixes are accepted), then relative to `task_dir`.
Absolute paths, `..` escapes and URLs are refused. The extension picks the
reader:

| Extension | Format | Reader | Needs |
|---|---|---|---|
| `.edf` | EDF, EDF+ (continuous and discontinuous) | built in, memory-mapped | nothing |
| `.bdf` | BioSemi BDF, BDF+ (24-bit) | built in, memory-mapped | nothing |
| `.hea` | WFDB record (header plus its `.dat` files) | `wfdb` library, read a window at a time | `signals` extra |
| `.csv`, `.tsv` | time column plus one column per channel | pandas, loaded whole | nothing |
| `.parquet`, `.pq` | the same, as Parquet | pyarrow, loaded whole | `signals` extra |
| `.json` | the inline object below, in a file | built in | nothing |

```bash
pip install 'potato-annotation[signals]'    # wfdb and pyarrow
```

### Inline JSON (small signals)

```json
{"id": "demo", "signal": {
  "sampling_rate": 100,
  "start_time": "2024-01-01T22:00:00",
  "channels": [
    {"name": "Fz", "unit": "uV", "data": [0.1, 0.4, 0.2]},
    {"name": "Resp", "unit": "a.u.", "sampling_rate": 10, "data": [0.0, 0.3]}
  ],
  "annotations": {"intervals": [{"start": 0, "end": 30, "label": "W", "channel": null}],
                  "events": []}
}}
```

| Key | Meaning |
|---|---|
| `sampling_rate` | samples per second, for every channel without its own |
| `t0` | time of the first sample (default 0), top level or per channel |
| `time` | instead of a rate: one time per sample (irregular series such as light curves), top level or per channel |
| `start_time` | ISO 8601 wall-clock time of t = 0, used by `time_format: clock` |
| `channels` | `[{name, unit, data, sampling_rate?, time?, t0?}]`; `null` in `data` is a missing sample |
| `annotations` | pre-annotations in the stored shape (below) |

Inline data is limited to 500,000 samples in all; put anything larger in a file.

### Times

Times are seconds from the start of the recording for EDF, BDF, WFDB and
inline data with a `sampling_rate`. For CSV and Parquet they are the values of
the time column as written (seconds, days, MJD); a date-time column becomes
seconds since its first row. Stored labels use the same time base.

## Format notes

**EDF+ annotations.** The "EDF Annotations" signal is not drawn. Each
annotation with a duration becomes a pre-annotated interval, each one without
becomes a point event, both on all channels (`channel: null`).

**EDF+D (discontinuous).** Each data record is placed at the onset its
timekeeping annotation gives. Records that follow on are joined; the space
between them is a gap, drawn as a break in the line, and times stay real
(seconds since the recording started). A record with no timekeeping annotation
is placed straight after the one before it, with a warning shown under the plot.

**Damaged EDF files.** A header that does not parse, an impossible signal count
or header size, or a file over `max_file_mb` gives an error in place of the plot
naming the field at fault. A file shorter than its header says is read up to its
last complete record, with a warning.

**WFDB.** Name the record by its `.hea` file. The signal files the header lists
must be in the same directory; a header naming a file anywhere else is refused
before `wfdb` opens it. Channels with several samples per frame are read at the
frame rate. Multi-segment records are not supported (join them first). When
`<record>.atr` exists (see `annotation_extension`), beat and event annotations
become point events labelled with their symbol (`N`, `V`, ...), and rhythm
annotations (`+` with an aux note such as `(AFIB`) become intervals labelled
`AFIB`, running to the next rhythm change.

**CSV and Parquet.** The time column is `time_column`, else the first column
named `time`, `t`, `timestamp`, `seconds`, `sec`, `time_s`, `datetime`, `mjd`
or `jd`, else the first column. Every other numeric column is a channel; a unit
in the header (`ax (g)`, `ay [m/s^2]`) becomes the channel's unit. When every
time step is within 0.1% of the median, the series is treated as regularly
sampled; otherwise each sample keeps its own time. Rows must be in time order.
These files are loaded whole, so they are limited to 256 MB; convert larger
ones to EDF.

**BIDS events.** A `*_events.tsv` named by `preannotation_field` is read as
pre-annotations: the label is `trial_type`, else `value`, else `event`;
duration 0 or `n/a` makes a point event; a `channel` column names the channel.

## Display options (`type: time_series`)

| Option | Default | Meaning |
|---|---|---|
| `window` | `30` | seconds shown at first, and the step of the next/previous buttons |
| `channels` | all | channels to show, in order: names, or `{name, label, range: [low, high], color}` |
| `layout` | `stacked` | `stacked`: one lane per channel; `overlay`: all channels on one y axis with a legend |
| `draw` | `line` | `line` or `points` (for sparse, irregular series) |
| `amplitude` | `recording` | lane scaling: `recording` uses each channel's range over the whole file (0.5th to 99.5th percentile of block extremes), so amplitudes compare across windows; `window` rescales to what is on screen. A channel's `range` overrides both |
| `lane_height` | `56` | pixels per lane in the stacked layout |
| `height` | from the lanes | plot height in pixels (80 to 4000) |
| `time_format` | `auto` | `elapsed` (h:mm:ss), `clock` (wall time from `start_time`), `number`; `auto` is `elapsed` for seconds, else `number` |
| `time_unit` | `s` | the time column's unit, for CSV/Parquet data in days or MJD |
| `invert_y` | `false` | flip the y axis in the overlay layout (astronomical magnitudes) |
| `time_column` | auto | CSV/Parquet time column |
| `annotation_extension` | `atr` | WFDB annotator read as pre-annotations; `null` for none |
| `max_file_mb` | `2048` | refuse signal files larger than this |
| `overview` | `true` | the strip under the plot: the whole recording (first channel's envelope), the labelled stretches, and the current window; click or drag it to move |

Options may be written under `display_options` or directly on the field.

### Controls

| Control | Action |
|---|---|
| ‹‹ / ›› buttons, `[` / `]`, Page Up / Page Down | previous / next window (epoch in epoch mode) |
| − / + / All | zoom out, zoom in, whole recording (hidden in epoch mode) |
| A− / A+ | lower / raise the amplitude of every lane |
| With the plot focused: ← / → | previous / next window; Shift+← / → pans by a tenth |
| With the plot focused: + / −, Home / End | zoom; first / last window |
| Ctrl (⌘) + wheel, Shift + wheel | zoom at the pointer, pan |
| Overview strip | click or drag to move the window |

Arrow keys move between items elsewhere in Potato; on the focused plot they
move the window instead.

## The `interval_label` scheme

| Option | Default | Meaning |
|---|---|---|
| `signal_field` | required | the `key` of the `time_series` field to label |
| `labels` | required | names, or `{name, key_value, color, kind, tooltip}`; `kind` is `interval` (default) or `event` |
| `mode` | `free` | `free`: drag and click; `epoch`: label fixed windows in sequence |
| `epoch_length` | `30` | seconds per epoch |
| `channel_scope` | `all` | `all`: labels apply to every channel; `channel`: to the lane where the drag started; `either`: a toggle |
| `auto_advance` | `true` | epoch mode: move to the next epoch after a label key |
| `allow_overlap` | `true` free, `false` epoch | when false, a new interval replaces the overlapped part of others on the same channel |
| `next_key` / `previous_key` | `]` / `[` | keys that move the window |
| `pre_annotations` | `true` | start from the file's own annotations (EDF+, WFDB `.atr`, inline) |
| `preannotation_field` | none | item field holding a BIDS `events.tsv` path, or annotations in the stored shape |
| `preannotation_labels` | none | rename file labels to scheme labels; a label mapped to `null` is dropped. After renaming, a file annotation is kept only if the scheme declares its label with the same kind (interval or event) |
| `require_all_epochs` | `false` | epoch mode: Next stays blocked until every epoch has a label. Enforced when the scheme is required (`label_requirement: {required: true}`) |
| `min_annotations` | none | Next stays blocked until this many intervals and events exist. Enforced when the scheme is required |
| `instructions` | none | text shown above the labels |

Labels without `key_value` get `1`–`9`, then `q`–`p`.

### Free mode

Press a label key (or click a label button), then drag across the plot to
label an interval, or click to mark a point if the label is an event label.
With an interval label picked, a click selects the interval or event under
the pointer; a label key then relabels it, Delete removes it, Escape
deselects. Every entry is listed under the plot with Show and Delete buttons,
which is also the way to review and remove labels without a mouse.

### Epoch mode

The recording is cut into `epoch_length` windows from its start. A label key
labels the current epoch and moves on; `[` / `]` move without labelling;
"Clear this epoch" removes the label. The overview strip shows every labelled
epoch in its label's colour. Event labels still mark points by clicking.

To mark stretches inside epochs (apnoeas, arousals) on the same plot, add a
second `interval_label` scheme in free mode with the same `signal_field`, as
`config-epochs.yaml` does. Pointer gestures go to the scheme whose label was
picked last; each scheme draws its own overlays; give the two schemes
different keys.

### Pre-annotations

When an item has no saved answer, the file's annotations (and
`preannotation_field`) are shown dashed, with a note. They are saved with the
annotator's first change, or by "Keep these"; "Discard them" clears them. In
epoch mode, an all-channel interval from the file (a hypnogram stretch) is
cut into the epochs it covers by at least half. Entries that came from the
file and were not changed keep `"source": "file"`.

### Stored value

One JSON object per item:

```json
{"intervals": [{"start": 30.0, "end": 60.0, "label": "N2", "channel": null},
               {"start": 41.2, "end": 43.0, "label": "artefact", "channel": "EOG"}],
 "events":    [{"time": 52.25, "label": "arousal", "channel": null, "source": "file"}]}
```

`channel` is a channel name, or `null` for all channels. Times are in the
recording's time base (see [Times](#times)).

## Export

| Format | Output |
|---|---|
| `interval_label` | `intervals.csv` and `intervals.jsonl`: one row per interval or event with `user_id, instance_id, schema, kind, start, end, duration, label, channel, source` (events have `start == end`, duration 0) |
| `bids_events` | `<annotator>/<instance>_events.tsv` per annotator and item with `onset, duration, trial_type, channel` (point events have duration 0; `n/a` for all channels), plus an `events.json` sidecar; with several schemes, one folder per scheme |

The generic CSV and JSONL exports also carry the answer, as one JSON cell per
scheme.

```bash
python -m potato.export -c config.yaml -f bids_events -o exports/bids
```

## How the drawing library was chosen

uPlot 1.6.32 (MIT, 51 KB) and dygraphs 2.2.2 (MIT, 130 KB) were compared on a
synthetic 10-channel, 256 Hz recording, stacked into lanes, in headless
Chromium on an Apple-silicon laptop. Render is the time to construct the chart
and draw it once; frame is one pan (a new x range) redrawn; memory is the
JavaScript heap the chart holds beyond the sample arrays.

| Data on the page | Points | uPlot render | uPlot frame (median / max) | dygraphs render | dygraphs frame (median / max) | dygraphs heap |
|---|---|---|---|---|---|---|
| min/max envelope, 1600 px (what Potato sends) | 32,000 | 2.9 ms | 0.4 / 0.8 ms | 6.5 ms | 0.9 / 2.7 ms | 5.6 MB |
| raw 30 s epoch | 76,800 | 6.4 ms | 0.8 / 1.4 ms | 10.3 ms | 1.5 / 3.9 ms | 13.5 MB |
| raw 10 min | 1.5 million | 17 ms | 3.7 / 7.9 ms | 99 ms | 25 / 59 ms | 268 MB |
| raw 1 hour | 9.2 million | 59 ms | 14 / 18 ms | 617 ms | 164 / 318 ms | 1,629 MB |
| raw 8 hours, one channel | 7.4 million | 41 ms | 9.5 / 17 ms | 755 ms | 158 / 406 ms | 2,438 MB |

uPlot draws from the typed arrays it is given; its own heap use was under
0.1 MB in every case. dygraphs needs the data as an array of rows, which is
where its memory goes. Both are fast enough on the envelope Potato sends;
uPlot was chosen for the margin when a window holds raw samples, the smaller
file, and the lower memory on long sessions. Neither library's built-in
annotations are used: overlays are drawn by Potato on uPlot's canvas.

The whole 8-hour recording would be 73.7 million samples (590 MB as 64-bit
floats), which is why the page only ever gets windows. On the server, with an
8-hour, 10-channel, 256 Hz EDF (148 MB):

| Step | Time |
|---|---|
| open (header and annotation scan) | 63 ms |
| first 8-hour overview (builds the min/max pyramid for all channels) | 0.23 s |
| any later window (30 s, 10 min, 1 h, 8 h), 1600 px | 11–19 ms |

A 1600-pixel window of 10 channels is about 500 KB of JSON. Windows are cached
on the server (256 entries) and by the browser (five minutes), and the page
keeps the last 40 it fetched.

## Routes

| Route | Returns |
|---|---|
| `GET /api/signals/window?instance_id=&field=&start=&end=&px=[&channels=a,b]` | per channel either `{name, t, v}` (raw samples, when the window holds at most `2 × px`) or `{name, t, lo, hi}` (per-pixel minimum and maximum), optional `gaps: [[from, to]]`, plus `ranges` (each channel's whole-recording range). `px` is capped at 4000 |
| `GET /api/signals/preannotations?instance_id=&field=&schema=` | the pre-annotations for one `interval_label` scheme |

Both need a signed-in annotator assigned to the item, and read the file from
the item's own field; a request cannot name a path.

## Browser API

Other schemes and displays can draw on the plot:

```js
PotatoTimeSeries.whenReady('signal', function (plot) {
  plot.getView();                       // {start, end}
  plot.setView(60, 90);
  plot.setOverlays({intervals: [{start: 10, end: 12, color: '#D55E00', label: 'x', channel: null}],
                    events: []}, 'my-layer');
  plot.on('brush', function (b) { /* {start, end, channel} */ });
  plot.on('click', function (c) { /* {time, channel} */ });
});
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| "Cannot show this signal: signal file '...' was not found" | the path is not under `media_directory` or `task_dir`; name it relative to `media_directory` |
| "... is outside the task directory; refused" | the reference uses `..` or a symlink leaving the project |
| "Reading WFDB records needs the wfdb library" | `pip install 'potato-annotation[signals]'` |
| "EDF header field '...' is not a number" | the file is not EDF/BDF, or its header is damaged; check it in another EDF reader |
| A warning under the plot about data records | the file is shorter than its header says, or EDF+D records lack timekeeping annotations |
| Flat lanes, or one lane drowning the others | set `amplitude: window`, give the channel a `range`, or use A− / A+ |
| Config validation fails with "signal_field '...' does not name a time_series display field" | `signal_field` must equal the `key` of a `time_series` field in `instance_display`; the server will not start until it does. The error lists the `time_series` fields it found |
| Label keys also tick a checkbox | another scheme on the page uses the same key; give one of them a different `key_value` |

## Related

- [Instance display](../instance_display.md)
- [Genome loci](genome_loci.md) and [Protein structures](protein_structures.md), the other viewer displays
- [Export formats](../../data-export/export_formats.md)

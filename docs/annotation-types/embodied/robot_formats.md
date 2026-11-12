# Robot Dataset Formats

Every robot-learning dataset stores the same thing — synchronized video plus
per-frame signals — and no two agree on how. Potato reads four layouts into one
shape, [`Episode`](episodes.md), and everything downstream speaks only that.

| Format | Needs | Detected by |
|---|---|---|
| Potato episode manifest | nothing | `episode.json` with `streams` or `series` |
| LeRobot v2 | `pyarrow` | `meta/info.json` |
| HDF5 (RoboMimic / ALOHA) | `h5py` | `.h5` / `.hdf5` |
| RLDS / TFDS (Open X-Embodiment) | `tensorflow_datasets` | by dataset **name**, not path |

Detection is by content and layout, not extension: `.h5` is claimed by half of
scientific computing, and a LeRobot dataset is a directory with no
distinguishing suffix at all.

## What is deliberately not normalized

**Units and semantics.** The reader records what the file said — a field name,
a stated unit — and does not convert. A joint angle in radians and one in
degrees look identical to a normalizer and differ by 57× to an annotator, so
guessing is worse than carrying the label through and letting the config say.

## Potato's own manifest

The one that needs no dependency. Use it for your own logs, or convert into it.

```json
{
  "episode_id": "pick_place_0007",
  "fps": 20,
  "num_frames": 240,
  "instruction": "pick up the red block and put it in the bowl",
  "streams": [{"name": "wrist", "url": "video/wrist.webm", "kind": "wrist"}],
  "series": [{"name": "gripper", "unit": "m", "values": [0.06, 0.058, ...]}]
}
```

`num_frames` may be omitted and is then taken from the longest series — the
frame count is a property of the data, and repeating it is one more thing to
get out of step.

Stream URLs are resolved relative to the manifest and served through `/media`.
Absolute URLs are left alone.

## LeRobot v2

The de-facto standard, and the format most new datasets ship in.

```
meta/info.json                          fps, features, path templates
meta/tasks.jsonl                        task_index -> language instruction
data/chunk-000/episode_000000.parquet   one row per frame
videos/chunk-000/observation.images.wrist/episode_000000.mp4
```

Potato reads the **path templates** out of `info.json` rather than assuming the
layout. Chunk size is configurable, and a dataset with more than `chunks_size`
episodes really does put the next one in `chunk-001`; a hardcoded path reads the
right file for episode 0 and nothing after it.

Vector columns are flattened to one series per component, named from
`features[col]["names"]` where the dataset provides them — `joint_0` tells an
annotator nothing, `shoulder_pan` tells them where to look. Index columns
(`frame_index`, `episode_index`, `timestamp`, `task_index`) get no lane: they
are straight lines by construction and would waste the only vertical space
there is.

Pointing an item at one episode:

```yaml
# in your data file
{"id": "ep_0", "episode": "lerobot_ds", "episode_index": 0}
```

```yaml
# in the schema
source_field: episode
episode_field: episode_index
```

## HDF5

Two conventions dominate and they disagree about almost everything, so the
reader detects which it is rather than requiring you to say.

**ALOHA / ACT** — one file per episode:

```
/observations/qpos          (T, 14)
/observations/images/<cam>  (T, H, W, 3)
/action                     (T, 14)
```

**RoboMimic** — one file for a whole dataset:

```
/data/demo_0/obs/<key>      (T, ...)
/data/demo_0/actions        (T, A)
/data/demo_0/rewards        (T,)
```

Demo keys sort **numerically**, so `demo_10` does not come between `demo_1` and
`demo_2`, and they are treated as keys rather than indices — a filtered dataset
has holes, and indexing would read the wrong demonstration.

**Frames stay in the file.** ALOHA stores raw RGB arrays; extracting 500 frames
into an MP4 is an ffmpeg job with its own failure modes, and doing it inside a
reader would make opening an episode arbitrarily slow with no progress shown.
The episode reports which image datasets exist and the timeline draws the
series lanes.

## RLDS / TFDS

The Open X-Embodiment collection, and the heaviest to read.

TensorFlow is hundreds of megabytes and pulls CUDA on many platforms, which
would triple Potato's install for a format most projects never touch. So it is
imported inside the reader, never at module scope, and its absence produces a
message naming the install command **and the offline alternative**:

> Reading RLDS/TFDS datasets needs tensorflow_datasets, which Potato does not
> install by default… Or convert: many Open X-Embodiment datasets are also
> published in LeRobot v2 form on the HuggingFace hub, which Potato reads with
> pyarrow alone.

RLDS says an observation is a dict; it does not say what is in it. So the
reader takes whatever numeric per-step fields it finds and names them by their
path, rather than looking for a fixed set and returning an empty episode when
the dataset does not use those names.

**Frame rate is a parameter, not data.** RLDS records steps, not time, and most
Open X-Embodiment datasets do not state their control frequency anywhere
machine-readable. The default of 10 Hz is documented as a guess, and the
episode's metadata carries `fps_is_assumed: true`. A timeline built on a wrong
frame rate is still correctly *ordered*, which is what phase annotation needs —
but the exported frame indices would be wrong, so set it if you know it.

## Adding a format

A `detect` and a `read` in a new module, and one line in
`potato/episodes/registry.py`. The same shape as the importer, exporter, schema
and display registries, so someone who has added one of those already knows how.

## Related documentation

- [Episode annotation](episodes.md)
- [Format matrix](../../data-export/format_matrix.md)

# Embodied Episode Annotation

Runnable example: `examples/embodied/lerobot-episode/`.

A robot demonstration is several synchronized camera streams plus several
numeric time series — joint positions, gripper state, force-torque, reward —
all indexed by frame. The questions worth asking about one are all temporal:
*when* did the grasp start, *when* did it fail, *how well* was it going at each
moment.

So the interface is a timeline: streams above it, the arm's own signals as lanes
beneath it, and every annotation layer drawn onto the same time axis.

```yaml
annotation_schemes:
  - annotation_type: episode_annotation
    name: episode_review
    description: "Mark the phases, judge the outcome, and draw the progress."
    source_field: episode
    layers: [phases, outcome, reward]
    phases:
      - {name: reach,     color: "#4ECDC4", key_value: "1"}
      - {name: grasp,     color: "#FFD93D", key_value: "2"}
      - {name: transport, color: "#6C8AE4", key_value: "3"}
    outcomes: [success, partial, failure]
    failure_causes: [missed grasp, object slipped, collision]
    reward_range: [0.0, 1.0]
    series_shown: [gripper, wrist_force]
```

## Four layers, because they answer different questions

| Layer | Question | Stored as |
|---|---|---|
| `phases` | What was the robot doing, and when? | Temporal segments over your taxonomy |
| `outcome` | Did it work? | One label per episode, plus a failure cause |
| `reward` | How well was it going at each moment? | A scalar curve along the timeline |
| `instruction` | What was it asked to do? | Text, optionally aligned to a segment |

Each is independently enableable because they cost very different amounts of
annotator time. Dense reward is minutes per episode; phase segmentation is
seconds.

**Three outcomes, not two.** "Partial" is the modal result in real robot data,
and forcing it into success-or-failure destroys the signal that makes the
dataset worth annotating.

## Controls

| Action | Result |
|---|---|
| `p` then drag on the phase lane | Draw a phase segment |
| `1`–`5` (or your `key_value`s) | Pick a phase class |
| `r` then drag on the reward lane | Draw the progress curve |
| Click anywhere else on the timeline | Seek |
| Drag a phase edge | Move that boundary only |
| `Space` | Play / pause every stream together |
| `←` / `→` | Step one **frame** |
| `Delete` | Remove the selected phase |

Phases are a **segmentation**: at any instant the robot was doing one thing. A
new segment truncates whatever it overlaps, and one that covers another
entirely removes it. Overlap would make "what was it doing at *t*?" ambiguous
and would silently break the temporal-IoU agreement, which assumes a partition.

Dragging one edge deliberately does not push its neighbour — the point of the
gesture is aligning one boundary against the signal behind it, and shoving the
next segment along would undo an alignment you had already made.

## Time on screen, frames on disk

Everything you see is in seconds, because that is what the video element
exposes and what a person reads. Everything stored is in seconds too, so the
agreement statistics need no conversion.

The **export** converts to frame indices, because that is what a training
pipeline joins on: `dataset[i]` is a frame. Doing it once, with the fps the
episode manifest actually carried, removes a conversion the consumer would
otherwise do against an fps they have to go and find.

The transport shows both, live.

## Series lanes

| Option | Default | Effect |
|---|---|---|
| `series_shown` | — | Draw these channels, by name, in this order |
| `max_lanes` | `8` | Cap when `series_shown` is not set |

A fourteen-joint arm with velocities is twenty-eight channels. Drawing them all
makes each lane twelve pixels tall and none of them legible, so the rest are
dropped — and the status line **says how many**, because silently dropping half
the signals is how an annotator concludes the data does not contain something
it does.

Series are downsampled for transport, min/max-preserving. A one-frame force
spike is the most diagnostic event in a manipulation log, and plain striding
drops it: a collision would become invisible in the very lane drawn to show it.

## Agreement

An episode annotation is three kinds of answer, so it gets three measures.
Blending them would hide which one the annotators disagreed about, and they
have completely different remedies.

| Layer | Measure |
|---|---|
| phases | Temporal IoU, through the same matching the video segments use |
| outcome | Krippendorff's α, nominal |
| reward | ICC(2,1) and Pearson *r*, on a common grid |

"They agree it failed but not when the grasp started" and "they agree on the
phases but not on whether it worked" are different problems.

**The reward curves are resampled** onto a common grid before comparison — two
annotators drag at different rates and their samples never line up — and only
over the range **both** of them drew. Comparing a region one labelled against
one they did not is comparing a judgement to an absence. The report includes
`reward_coverage` for that reason: a high correlation over 5% of a timeline is
not evidence about the other 95%.

Outside the drawn range the curve is **nothing**, not zero. "Did not say" and
"said zero" are different, and a reward model trained on the second when the
first was true learns that unlabelled regions are bad.

## Export

`episode_jsonl` writes one row per frame:

```json
{"episode_id": "episode_0000", "frame_index": 34, "timestamp": 1.7,
 "phase": "grasp", "progress_reward": 0.42,
 "outcome": "success", "failure_cause": null}
```

A **sidecar**, not a rewrite. The dataset you annotated is usually read-only —
a public HuggingFace repo, a shared mount, a tree nobody wants a second copy
of. `potato.episodes.export.append_to_lerobot` will add the columns to the
source parquet when the dataset really is yours, and is deliberately not the
default.

Rows are emitted for **every** frame, including unannotated ones, with nulls.
A sidecar with holes forces every consumer to decide what a missing frame
means, and they will not all decide the same thing.

## Troubleshooting

**"No episode for this item"** — the item has no field by the name
`source_field` gives. The path is looked up in the item's own data, not on the
page, because an episode path is a data field and `text_key` usually points at
something human-readable.

**"needs pyarrow" / "needs h5py"** — the format needs an optional dependency and
the message names it. See [robot formats](robot_formats.md).

**Lanes but no video** — normal for a state-only dataset, and for one whose
frames were never downloaded. Each missing stream says so under its own
placeholder rather than collapsing to nothing.

**The lanes disagree about where a frame is** — the status line reports a
ragged series (`series 'x' has 380 samples but the episode has 400 frames`).
That is a defect in the source log, not in the reader, and it is reported
rather than raised because the episode is still mostly usable.

## Related documentation

- [Robot dataset formats](robot_formats.md) — LeRobot, HDF5, RLDS, and Potato's own manifest
- [Video annotation](../multimedia/video_annotation.md) — for single-stream video
- [Geometry agreement](../../advanced/geometry_agreement.md) — the matching the phase measure reuses

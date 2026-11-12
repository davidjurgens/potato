# Robot episode review

Annotate a robot demonstration: two synchronized camera views, the arm's own
signals as lanes, and one timeline through all of it.

```bash
python potato/flask_server.py start examples/embodied/lerobot-episode/config.yaml -p 8000
```

## What to do

1. Press **Play**, or click anywhere on the timeline to seek.
2. Press `p` (or click **Phase**), pick a phase, and drag across the phase lane
   to mark when it happened.
3. Press `r` and drag across the reward lane to draw how well the attempt was
   going.
4. Say whether it worked.

## The two episodes differ in one way that matters

`episode_0000` succeeds. `episode_0001` closes the gripper on nothing.

That failure is visible in the **`gripper` and `wrist_force` lanes** before it
is obvious in the video: the gripper closes to 2 mm instead of the block's
28 mm, and the force trace stays flat where episode 0 shows a contact spike.
That is the case dense time-series annotation exists for, and it is why the
lanes sit next to the video rather than behind a tab.

## Regenerating the data

```bash
python examples/embodied/lerobot-episode/generate_episode.py
```

Video is written as **WebM/VP9** when ffmpeg is on PATH. Chromium ships without
an H.264 decoder, so an MP4 example shows a black rectangle in exactly the
browser most people test in, with no error anywhere. Without ffmpeg the
episodes are written state-only, which is a normal kind of robot dataset and is
what the timeline degrades to.

## Other formats

These episodes are in Potato's own manifest format, which needs no extra
dependency. LeRobot v2 (`pyarrow`), RoboMimic/ALOHA HDF5 (`h5py`) and RLDS
(`tensorflow_datasets`) load through the same `source_field` — see
[robot formats](../../../docs/annotation-types/embodied/robot_formats.md).

## Related

- [Episode annotation documentation](../../../docs/annotation-types/embodied/episodes.md)

# Track through an occlusion

Draw the object once. Press **Track forward**. SAM 2 follows it through the
rest of the clip, including the stretch where it disappears behind a bar.

## Running it

```bash
potato download-models sam2_video_tiny          # 181 MB, once per install
python examples/video/mask-propagation/make_clip.py   # needs ffmpeg
python potato/flask_server.py start \
    examples/video/mask-propagation/config.yaml -p 8000
```

## What to do

1. Pick the **disc** label and press **+ Track**.
2. Draw a box around the red disc on frame 0.
3. Press **Track forward**.

Scrub through the result. The disc should be masked on every frame it is
visible, and the frames where the bar covers it should come back empty rather
than filled with a guess.

## Why the clip looks like that

It is synthetic so you can check the answer. The disc follows a path you can
see, there is a stationary green blob to make "track the thing that moves" too
easy an answer, and the bar in the middle hides the disc completely for a few
frames.

That occlusion is the part worth watching. A tracker that carries a mask
forward by re-prompting the next frame usually latches onto the bar or the
distractor and never recovers. SAM 2 keeps a memory of what the object looked
like on earlier frames, so it can pick the disc up again on the far side, and
it decides for itself when the object is hidden.

## What it costs

Roughly 1.3 seconds per frame on a CPU, faster on a GPU. This runs on the
server: the model is five graphs, you pay the cost once per frame, and the
video file is already there. A run stops at `propagation.max_frames` and says
so when it does.

Measured on a moving object against known ground truth: per-frame IoU between
0.974 and 0.979, with no decay from the first frame to the last.

## Correcting it

Every propagated frame lands as a keyframe. Redraw any that are wrong; the
keyframes you draw are indistinguishable from the ones you would have drawn by
hand, and the model's are marked so a later pass can tell them apart.

## See also

- [Video annotation](../../../docs/annotation-types/multimedia/video_annotation.md)
- [The model zoo](../../../docs/ai-intelligence/model_zoo.md)

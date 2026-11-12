# Polygon Tracking

Tracking an object across video frames with **polygons**, not just boxes.

```bash
python potato/flask_server.py start examples/video/polygon-tracking/config.yaml -p 8000
```

The clip is bundled (`media/clip.webm`), so this runs offline. It is WebM
because bundled Chromium — which the Playwright tests use — has no H.264
decoder.

## What to try

1. Press `t` to start a track, pick the **subject** label.
2. Trace the moving shape with the polygon tool at frame 0.
3. Step forward with `.` about a second, and trace it again.
4. Scrub back through the span: the outline interpolates between your two
   traces.
5. Press `<` and `>` to jump between your keyframes.
6. On any in-between frame, press `Ctrl/Cmd+K` to pin the interpolated outline
   as a real keyframe, then adjust it.

## The bit worth looking at

On step 3, **start tracing from a different point on the outline** — the top on
one keyframe, the side on the next. The interpolation still behaves, because
both outlines are resampled to equal fractions of their perimeter and aligned
to the offset that matches best.

Interpolating vertex-to-vertex instead is the obvious implementation and it
turns the shape inside out halfway between keyframes. It also *looks correct*
whenever the annotator happens to trace both frames the same way, which is why
it survives casual testing.

## Masks are held, not blended

If you paint a mask keyframe instead, in-between frames show the nearest
keyframe's mask with a hollow circle marker rather than a blend. Averaging two
rasters produces ghost regions where the object was and where it will be, with
holes between — a shape that is neither frame. Holding is honest; the marker
says which frames are real.

## Related

- [Video annotation](../../../docs/annotation-types/multimedia/video_annotation.md)
- [Video formats](../../../docs/annotation-types/multimedia/video_formats.md)

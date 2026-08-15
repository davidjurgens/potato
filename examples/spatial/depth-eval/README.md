# Depth prediction review

Review a monocular depth prediction: the RGB frame, the predicted depth over
it, and a readout of the distance under the cursor in metres.

```bash
python potato/flask_server.py start examples/spatial/depth-eval/config.yaml -p 8000
```

## What to do

1. Drag the **near** and **far** fields until the corridor's structure is
   legible. They start at the 2nd and 98th percentile of the valid pixels.
2. Move the pointer over the image. The line under it reports the depth in
   **metres**.
3. Answer the three questions on the right.

## What is wrong with these scenes, deliberately

The depth is synthetic, and the failures a real monocular model makes are
injected on purpose so there is something to find:

| Scene | Failure | How you would catch it |
|---|---|---|
| Both | **Flying pixels** — a halo of interpolated depth around the near box's silhouette | Visible in the picture, at the edge |
| Both | **A hole** where the dark far box returned nothing | Magenta, so it cannot be read as near or far depth |
| 2 only | **A 30% scale error** on the back wall | **Invisible in the picture.** The window rescales and the wall is still the far end. Only the metre readout shows it. |

That third one is the point of the example. A depth display without a value
readout would render scene 2 as a perfectly plausible image, and every
annotator would pass it.

## Regenerating the data

```bash
python examples/spatial/depth-eval/generate_depth.py
```

The generator writes 16-bit PNGs in **millimetres**, which `depth_scale: 0.001`
in the config converts back to metres. The file itself does not record its unit
— no depth format does — so that value is a claim the config makes and the
readout is how you check it.

## Related

- [Depth map documentation](../../../docs/annotation-types/spatial/depth_maps.md)
- [Point cloud annotation](../kitti-cuboids/) — the 3D viewer unprojected depth feeds

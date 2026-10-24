# Camera-trap review

Eight synthetic camera-trap frames from two cameras, with the MegaDetector
batch-output file they were imported from (`source/md_output.json`). Each
image opens with:

- `triage` (empty / animal / person / vehicle) set from the most confident
  detection;
- `detections`: the detector's boxes, labelled with the species
  classification where the file has one (`Odocoileus virginianus`,
  `Procyon lotor`) and with the detector category otherwise;
- `species`: the species of those boxes.

Every frame also has a detection at confidence 0.08 on a tree, which the
default `--md-threshold` of 0.2 leaves out.

```bash
python potato/flask_server.py start examples/image/camera-trap-review/config.yaml -p 8000
```

To rebuild the project from the source file:

```bash
potato import -i examples/image/camera-trap-review/source/md_output.json \
    --image-url-prefix /media -o examples/image/camera-trap-review
```

Add `--sequences` for one item per sequence (`cam01-s1`, `cam01-s2`, ...),
shown as a gallery. See `docs/guides/camera-traps.md` for the exports
(`megadetector`, `camtrap_dp`, `darwin_core`).

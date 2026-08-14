# Media Ingest

Annotating files a browser cannot display: TIFF stacks, HEIC photos, camera
RAW, ProRes and MKV.

Without this, such a file produces a blank canvas or an empty video player and
**no error** — from the page's point of view nothing went wrong, so the
annotator concludes the tool is broken. Potato transcodes these on first
request, caches the result, and when it genuinely cannot, says so with the
command to run instead.

## How it works

Reference the file through `/media/proxy/` instead of `/media/`:

```json
{"id": "scan_001", "image_url": "/media/proxy/scan_001.tif"}
```

Files browsers already display (`.jpg`, `.png`, `.webp`, `.mp4`, `.webm`) pass
straight through un-re-encoded, so a mixed corpus needs no special handling —
point everything at the proxy.

Results are cached under `<output_annotation_dir>/.media_cache/`. The cache key
includes the source's size and mtime, so editing a source file produces a new
key and the stale render is never served. Deleting the directory costs a
re-render and nothing else.

## Supported formats

### Images

| Format | Needs | Notes |
|---|---|---|
| TIFF (`.tif`, `.tiff`) | Pillow | Multi-page and 16-bit supported |
| HEIC / HEIF | `pip install pillow-heif` | iPhone photos |
| Camera RAW (`.dng`, `.cr2`, `.cr3`, `.nef`, `.arw`, `.orf`, `.rw2`, `.raf`) | `pip install rawpy` | |
| JPEG 2000, PPM/PGM/PBM | Pillow | |

Output is WebP.

### Video

| Format | Notes |
|---|---|
| `.mov` | QuickTime, often ProRes or HEVC |
| `.mkv` | Not supported by Safari or iOS |
| `.avi`, `.wmv`, `.flv`, `.mxf` | Legacy or broadcast containers |
| `.mts`, `.m2ts` | AVCHD camera formats |

Output is WebM/VP9, via **ffmpeg** — which is not a Python package. Install it
with your system package manager (`brew install ffmpeg`,
`apt install ffmpeg`).

## 16-bit windowing

This is the part that matters for scientific imagery, and the reason a naive
conversion is worse than useless.

A 16-bit microscopy or medical TIFF holds values a display cannot show. The
obvious conversion — an 8-bit cast — divides by 256, so a scan whose structure
lives between 1200 and 1800 becomes **4 grey levels apart out of 255**.
The image looks uniformly black, and it reads as a corrupt file rather than a
windowing problem.

Potato instead applies a **percentile stretch** by default, clipping the
extreme tails. On a test scan with content at 1200/1800 plus one hot pixel at
65535, the difference is measured:

| Conversion | Background | Signal | Separation |
|---|---|---|---|
| Full-range cast (the naive default) | 3 | 7 | **4 / 255** |
| Percentile window (Potato's default) | 0 | 254 | **254 / 255** |

A single hot pixel is enough to make a min/max stretch useless, which is why
the default clips percentiles rather than extrema.

### Controlling the window

```
/media/proxy/scan.tif?window_min=1200&window_max=1800&gamma=1.2
```

| Parameter | Meaning |
|---|---|
| `window_min` / `window_max` | Source values mapped to black and white |
| `gamma` | Applied after windowing; `>1` brightens midtones |
| `page` | Page index for multi-page TIFFs |

Each combination is cached separately, so two windows of the same scan coexist
rather than evicting each other.

### Finding a sensible range

```
GET /media/info/scan.tif
```

```json
{"kind": "image", "width": 200, "height": 150, "mode": "I;16",
 "pages": 1, "high_depth": true,
 "value_min": 1200, "value_max": 65535,
 "suggested_window": {"min": 1200.0, "max": 1800.0}}
```

Note that `suggested_window.max` is 1800, not 65535: the hot pixel is visible
in `value_max` but excluded from the suggestion. "This is 16-bit" is not
actionable; "values run 1200–1800" is.

## Multi-page TIFF

`/media/info/` reports the page count and `?page=N` selects one. Silently
showing page 0 would present a 40-slice stack as a single image and lose the
rest without saying anything, so an out-of-range page is an error rather than a
fallback.

To annotate every slice, generate one item per page:

```json
{"id": "stack_p0", "image_url": "/media/proxy/stack.tif?page=0"}
{"id": "stack_p1", "image_url": "/media/proxy/stack.tif?page=1"}
```

## When a dependency is missing

Nothing here is required, and no absence produces a broken player. Each one
reports the specific fix:

- no Pillow → *"This image format needs Pillow… `pip install Pillow`"*
- no `pillow-heif` → *"HEIC images need the pillow-heif decoder…"* (saying
  "install Pillow" would be unhelpful when Pillow is already there)
- no `rawpy` → the install command, plus the `dcraw` alternative
- no ffmpeg → the exact conversion command:

```
ffmpeg -i clip.mov -c:v libvpx-vp9 -crf 30 -b:v 0 -c:a libopus output.webm
```

These come back as HTTP **415** with a JSON `error`, not a 500 — the file is
fine, we cannot render it, and a 500 would suggest a bug and bury the
actionable message.

## Long videos

A feature-length ProRes master will not transcode inside a web request.
Transcoding is bounded (10 minutes by default) and, on timeout, tells you to
convert ahead of time rather than leaving the request hanging.

For a large video corpus, convert once up front:

```bash
for f in *.mov; do
  ffmpeg -i "$f" -c:v libvpx-vp9 -crf 30 -b:v 0 -c:a libopus "${f%.mov}.webm"
done
```

## Cache management

The cache is bounded (2 GiB by default) and evicts least-recently-used entries.
Eviction is never data loss — every entry can be regenerated.

```bash
rm -rf <output_annotation_dir>/.media_cache/
```

## Configuration

```yaml
task_dir: .
media_directory: media          # where source files live
output_annotation_dir: output   # .media_cache/ goes here
```

Both `/media/` and `/media/proxy/` resolve against `media_directory` with the
same path-traversal guard, so the proxy cannot reach outside it.

## Not yet supported

DICOM, NIfTI and whole-slide (SVS) formats are **not** handled. The 16-bit
windowing here is the on-ramp for them, but medical imaging brings regulatory
and workflow requirements that deserve their own design rather than being
bolted on.

## Related

- [Image annotation](image_annotation.md)
- [Video annotation](video_annotation.md)
- [Import CLI](../../tools/import_cli.md)

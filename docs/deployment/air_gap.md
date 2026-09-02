# Air-Gapped and Offline Deployment

Potato is often run on networks with no outbound internet access — secure
research environments, clinical settings, field deployments, or simply a machine
behind a strict proxy.

**Status: supported.** Every stylesheet, script, font and icon Potato serves
comes from `potato/static/`. A machine with no route to the internet renders the
same interface as one with a fast connection — the annotator pages and the
admin dashboard alike.

The admin dashboard is worth naming, because it was the last thing to get
there: an air-gap claim that covers only the pages annotators see is not an
air-gap claim.

## What is served locally

| Asset | Where |
|-------|-------|
| **Fabric.js** (image annotation canvas) | `vendor/fabric-5.3.1.min.js` |
| **jQuery 3.6.0** | `vendor/jquery-3.6.0.min.js` |
| **Bootstrap 5.3.3** (CSS + JS bundle, Popper included) | `vendor/bootstrap-5.3.3.*` |
| **Font Awesome 6.7.2** (CSS + webfonts) | `vendor/font-awesome-6.7.2/` |
| **Outfit** (the interface typeface) | `vendor/outfit/` |
| three.js (point cloud viewer) | `vendor/three-0.160.0.min.js` |
| OpenSeadragon (deep zoom) | `vendor/openseadragon-5.0.1.min.js` |
| d3 7.9.0 (solo-mode charts) | `vendor/d3-7.9.0.min.js` |
| Bootstrap 4.1.3/4.4.1 + slim jQuery + Popper (legacy pages) | `vendor/bootstrap-4.*`, `vendor/jquery-3.4.1.slim.min.js`, `vendor/popper-1.16.0.umd.min.js` |
| Peaks.js (audio/video waveforms) | `static/peaks.min.js` |
| PDF.js | `vendor/pdfjs/` |
| Plotly 2.27.0 (admin embedding plot) | `vendor/plotly-2.27.0.min.js` |
| All of Potato's own CSS and JavaScript | `static/` |

Two of these were load-bearing rather than cosmetic. Without **jQuery**, span
(text) annotation does not work at all. Without **Fabric.js**, the image canvas
never initializes, so the drawing tools render but nothing can be drawn.

### The font was also a privacy leak

`styles.css` opened with an `@import` of the Outfit family from Google Fonts.
Beyond breaking offline, that sent every annotator's IP address and User-Agent
to a third party on every page load — from a tool people self-host precisely so
their data does not leave their infrastructure. The family is now vendored
under `vendor/outfit/` (SIL Open Font License 1.1).

It survived the earlier air-gap work because the guard read `<script src>` and
`<link href>` in templates, and an `@import` inside a stylesheet is neither.
There is now a test for that too.

### PDF.js and Plotly

Both were in `vendor/` and neither was loaded from there. Two features reached
for a CDN with the local copy already on disk:

- **PDF.js.** `static/js/pdf-viewer.js` hardcoded cdnjs, while
  `static/pdf-link-mode.js` beside it used a local-first loader with the CDN
  only as a fallback. Two copies of the same job, one of them wrong. There is
  now a single shared loader (`static/js/pdfjs-loader.js`) that both call.
- **Plotly.** `templates/admin.html` loaded it from `cdn.plot.ly`, so the
  embedding visualisation died with no network. It is now vendored, loaded
  local-first.

Both survived the earlier air-gap work for the same reason: the guards read the
*annotator* template, and one of these was in an admin page while the other was
in a JavaScript file rather than a template. `tests/unit/test_offline_assets.py`
now checks every hand-written source file under `static/` and `templates/`, and
fails if a CDN reference is not preceded by the local path.

### Legacy pages kept their old versions

`header.html` and the Simple-Likert example template run on Bootstrap 4 with
slim jQuery, and they load *two* different Bootstrap 4 JS builds. All of it is
vendored at the versions those pages already used. Vendoring is an air-gap fix,
not a migration: changing a major version under a legacy layout is how you break
it without noticing.

## What is checked automatically

Four guards, each catching a different failure:

| Test | Catches |
|---|---|
| `tests/unit/test_no_new_cdn_assets.py` | A new external asset in the main template, a stale allowlist entry, and — since the Google Fonts import — a stylesheet that `@import`s or `url()`s from the network |
| `tests/unit/test_air_gap_assets.py` | A template referencing a static file that is **not in the tree**, a truncated vendored bundle, and a new external host in *any* source template |
| `tests/server/test_air_gap_page.py` | A rendered page referencing a local asset the server does not actually serve |
| `tests/unit/test_offline_assets.py` | A vendored library loaded from its CDN *first*, anywhere under `static/` or `templates/` — including admin pages and plain `.js` files, which the template-shaped guards above do not read. Also fails when a "local-first" path points at a file that is not on disk |

The third is the strongest and the only one that catches an asset which is
vendored, committed and referenced but never enabled by
`FRONTEND_ASSET_MARKERS` for the schema in question — a failure invisible to any
static scan, and visible only to the project type that triggers it.

## Managing vendored assets

`scripts/vendor_assets.py` is the manifest and the tool:

```bash
python scripts/vendor_assets.py --check    # verify committed files against pinned hashes
python scripts/vendor_assets.py            # download anything missing
python scripts/vendor_assets.py --force    # re-download everything
```

Every download is verified against the CDN's published Subresource Integrity
hash and is **refused** on mismatch. These files are committed to the
repository, so an unverified download would ship to every user.

## Adding a new frontend dependency

Vendor it. `tests/unit/test_no_new_cdn_assets.py` fails the build if a new
external `<script>` or `<link>` appears in the main template, so this is
enforced rather than remembered.

Both allowlists (`ALLOWED_EXTERNAL` and `ALLOWED`) are now **empty**, and the
guards fail if an entry stops matching anything, so they cannot quietly become
permanent exemptions. If a dependency genuinely cannot be vendored, add its host
with a note explaining why and a consequence recorded on this page — then treat
it as work with a deadline. The last three entries sat there long enough that
this page had to warn people off deploying offline.

## Model weights are not vendored

The frontend guards above cover scripts and stylesheets. Optional features that
run a machine-learning model fetch their weights the first time you use them,
and those are too large to ship in the package:

| Feature | Fetches | Staging it offline |
|---|---|---|
| `potato transcripts --transcribe` | A Whisper model from Hugging Face | Pass `--asr-model` a local CTranslate2 model directory |
| `potato transcripts --diarize` | Two ONNX models (~47 MB) | Set `POTATO_MODEL_CACHE`, or pass `--diarize-segmentation-model` and `--diarize-embedding-model` |
| [Think-Aloud](../advanced/think_aloud.md) | A Whisper model on the first recording | Set `thinkaloud.model` to a local model directory |

Run each once on a connected machine, then copy the cache directory across.
Nothing else in a default Potato install reaches the network at runtime.

## Related

- [Deployment overview](../deployment/reverse-proxy.md)
- [Image annotation](../annotation-types/multimedia/image_annotation.md)

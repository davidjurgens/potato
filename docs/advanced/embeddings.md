# Embeddings and the Corpus Map

Potato embeds your items once, and everything that needs vectors uses that one
embedder: the corpus map, diverse item ordering, near-duplicate detection,
cluster-based gold seeding.

By default it works out what your corpus is made of and picks a model to match.
You can override every part of that.

## The short version

Nothing to configure for text. For a project whose items look like this:

```json
{"id": "img_01", "image_url": "media/cat.jpg"}
```

Potato detects an image corpus, encodes `image_url` with CLIP, and the corpus
map shows a map of your images.

## Configuration

```yaml
embeddings:
  backend: auto          # auto | text | image | audio | video | custom
  model: null            # backend default when omitted
  source_field: null     # which item field to embed; detected when omitted
  cache_dir: null        # defaults to <output_annotation_dir>/.embeddings
  media_root: null       # prefix for relative media references
```

| Backend | Default model | Reads | Needs |
|---|---|---|---|
| `text` | `all-MiniLM-L6-v2` | the configured `text_key` | `sentence-transformers` |
| `image` | `clip-ViT-B-32` | `image_url`, `image`, … | `sentence-transformers`, `pillow` |
| `audio` | `laion/clap-htsat-unfused` | `audio_url`, `audio`, … | `transformers`, `soundfile` or `librosa` |
| `video` | `clip-ViT-B-32` over sampled frames | `video_url`, `video`, … | the image deps, plus `ffmpeg` on PATH |
| `custom` | yours | whatever you point it at | whatever it needs |

Image and video share CLIP on purpose: one shared image/text space means a
region crop can later be compared against a class name with no second model.

### How detection decides

It reads a sample of your items and looks for two things: field names that
name a modality (`image_url`, `audio_url`, `video_url`, …) and file extensions
in the values. **Media wins over text when an item has both** — in a vision
task the text field is usually a prompt repeated on every item, and a
projection of one repeated sentence is a single blob. Set `source_field` to
override.

If nothing usable is found, Potato says so rather than embedding something
arbitrary. It used to fall back to "the item's first string value", which on a
media corpus is the instance id — so the corpus map was a projection of
`img_01`, `img_02`, … and looked perfectly normal.

Whatever it settles on is shown next to the map (backend, model and field) and
logged once at startup.

### Video

Each clip becomes a handful of evenly spaced frames, embedded and averaged:

```yaml
embeddings:
  backend: video
  frames: 4
```

This has no sense of motion. It groups clips by scene, subject and setting,
which is what a map is for; it will not separate two clips of the same room
that differ only in what happens.

### Audio

CLAP, at 48 kHz. Recordings at another rate are resampled when `librosa` is
installed; with only `soundfile` they are skipped rather than fed to the model
at the wrong speed.

```yaml
embeddings:
  backend: audio
  max_seconds: 30      # per clip
```

## Bringing your own encoder

A pathology encoder, a bird-song model, a fine-tuned CLIP — anything that turns
references into vectors. Either call it in-process:

```yaml
embeddings:
  backend: custom
  modality: image          # what the UI should call it
  source_field: slide_url
  entrypoint: "mylab.encoders:embed_batch"    # (list[str]) -> list[list[float]]
```

or over HTTP:

```yaml
embeddings:
  backend: custom
  modality: audio
  source_field: recording_url
  endpoint: "http://localhost:8900/embed"
  headers: {Authorization: "Bearer ..."}
  batch_size: 32
```

The endpoint receives `{"inputs": [...]}` and may reply with `{"embeddings":
[[...]]}` or an OpenAI-shaped `{"data": [{"embedding": [...]}]}`. A reply with
the wrong number of vectors is an error, not a partial map.

## The corpus map

`embedding_visualization.enabled: true` turns it on. It no longer requires
`diversity_ordering` — it embeds for itself when it has to, bounded by
`sample_size`.

```yaml
embedding_visualization:
  enabled: true
  sample_size: 2000
  include_all_annotated: true
  label_source: majority
```

Points are previewed with what was embedded: the image, the clip, the recording
or the text. Hovering a point on a media project shows the media.

## Caching

Vectors are cached on disk under `<output_annotation_dir>/.embeddings`, keyed
by backend, model and reference — so changing the model does not silently reuse
the old vectors, and restarting does not re-encode a corpus.

## Troubleshooting

**"nothing to embed"** — no media field and no usable `text_key`. Name the
field: `embeddings.source_field: my_field`.

**The map is one dense blob** — you are probably embedding a field that is the
same on every item. Check the backend and field reported beside the map.

**Points but no pictures** — the reference is relative and the server cannot
resolve it. Set `embeddings.media_root`.

**Everything is slow the first time** — models download on first use and
vectors are cached afterwards. `potato download-models` pre-fetches the
segmentation models; embedding models are fetched by their own libraries.

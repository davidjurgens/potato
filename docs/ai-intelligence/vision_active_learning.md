# Vision Active Learning

Rank unlabeled images by how much annotating them would teach the model, so
annotators spend their time where it counts.

**CVAT has no active learning at all**, so the goal here is not to match a
competitor's model stage — it is to be the only self-hostable annotation tool
with real active learning over images.

## How little had to change

Potato's active learning was already mature: uncertainty, diversity, BADGE,
BALD, hybrid ranking, background training, persistence. It was text-bound
through exactly one call — `item.get_text()`.

Every `QueryStrategy` already took a *vectorizer* and called
`vectorizer.transform(items)`. So images needed **one new vectorizer**, not a
parallel pipeline:

| Component | Text | Images |
|---|---|---|
| Vectorizer | `SentenceTransformerVectorizer` | `ImageEmbeddingVectorizer` |
| Feature | `item.get_text()` | the item's image reference |
| Uncertainty / diversity / BADGE / BALD / hybrid | unchanged | **unchanged** |

Those two rows are the whole change: a strategy that works on text works on images.

## Setup

```bash
pip install sentence-transformers Pillow
```

Both are optional. Their absence produces a message naming the install command
— never a silent fallback to random ordering, which would look like active
learning while being nothing of the kind.

```yaml
active_learning:
  enabled: true
  query_strategy: uncertainty  # or diversity, badge, bald, hybrid
  vectorizer:
    name: image                # alias: clip; the default is TF-IDF over text
    hyperparameters:
      model_name: clip-ViT-B-32
      cache_dir: annotation_output   # optional; turns on the embedding cache
      image_root: data/images        # optional; prefix for relative references
```

`vectorizer` must be a mapping with a `name`; a bare `vectorizer: image` fails
config validation. `model_name` defaults to `clip-ViT-B-32`, `cache_dir` is
unset by default, and `image_root` defaults to `task_dir`.

With an image vectorizer, every scheme gets the item's image reference as its
feature, not only `image_annotation` and `video_annotation`. A `radio` or
`multiselect` scheme over images (image classification) is ranked by its
images.

## Why CLIP rather than DINOv2

DINOv2 gives slightly better pure-vision features. CLIP embeds **text into the
same space**, which makes cross-modal checks free once the model is loaded:

```python
vectorizer.embed_text(["a photo of a cat", "a photo of a dog"])
```

An annotated crop that sits far from its own class name is a candidate
mislabel. That is dataset QA neither V7 nor CVAT offers, from a model we need
anyway.

## The embedding cache

Embedding is the expensive step and the corpus does not change. Active learning
re-ranks after **every batch** of annotations, so an uncached embedder would
re-encode the entire unlabeled pool each time — minutes of GPU-less compute,
repeated for nothing.

The cache exists only when `cache_dir` is set under
`vectorizer.hyperparameters`. Without it, nothing is cached and every re-rank
re-encodes the pool. With it, embeddings are stored under
`<cache_dir>/.embeddings/<model>/`, one `.npy` per image, keyed by **file
content**:

- renaming or moving an image does **not** force a re-encode
- editing an image **does**
- two models never share entries, because their vectors are in different spaces
  and mixing them silently would make every distance meaningless

The cache is disposable — delete the directory and it rebuilds.

```python
from potato.vision_features import EmbeddingCache
EmbeddingCache(cache_dir).clear()
```

## Image references

The feature for an item is the first non-empty value among the scheme's
`source_field`, then the item fields `image_url`, `image`, `image_path`,
`file_name`, `video_url` and `url`. When none is set, the item's text (the
`text_key` field) is used, so `text_key: image_url` also works. A
`/media/...` reference, the URL the annotation page serves images from, is
read from `media_directory` (`<task_dir>/media` by default). Other references
are tried as given, then under `image_root`.

An image that cannot be read is embedded as a zero vector, and a warning names
how many training images that happened to. If more than half of the training
images cannot be read, the retrain fails with an error and the queue keeps its
previous order, because a model fitted on blank vectors would rank it on
nothing.

**Remote URLs are skipped, not fetched.** Active learning ranks a whole
unlabeled pool from a background thread; fetching would fire thousands of
requests. Serve images locally, or set `image_root` to where they live on disk.
Skipped references are recorded in `vectorizer.failures` so a partial ranking
can be reported honestly rather than presented as complete.

An unreadable image still occupies its row in the output, as a zero vector.
That is deliberate: callers index results against the input list, so dropping a
row would misalign every ranking after the gap — and a misranking looks like a
model quirk rather than a bug.

## What is not here

**Detector training is out of scope.** Model training
([Model training](model_training.md)) fits image *classifiers*: the
`sklearn-text` trainer uses CLIP embeddings when a radio or multiselect scheme's
items name image files. It does not train detectors or segmenters.
Pre-labelling for boxes and masks comes from SAM
(see [Interactive segmentation](../annotation-types/multimedia/segmentation.md))
and the existing YOLO endpoint, not from a detector Potato trains.

## Related

- [Active learning guide](active_learning_guide.md)
- [Model training](model_training.md)
- [Interactive segmentation](../annotation-types/multimedia/segmentation.md)
- [Geometry agreement](../advanced/geometry_agreement.md)

# Model Training

Model training fits a classifier on the study's own annotations, from the admin
Training page at `/admin/training`. Each run resolves the annotations to one
label per item, splits the items into train, val and test, fits the model in a
separate process, and records what it trained on and which items it held out.
A run's predictions can then be written back to items as prelabels, which the
[model review](model_review.md) workflow serves least-confident first.

The labeling engine uses the same trainers. [Distillation](../labeling-engine/configuration.md#distill)
fits one on the engine's labels, and a `trained` source loads a fitted model's
directory (`artifact_dir`).

---

## Quick start

```yaml
model_training:
  enabled: true
```

Restart the server, open `/admin/training`, pick a trainer and a scheme, and
click **Train now**. Nothing is shown to annotators until you name schemes
under `writeback.schemas`.

---

## Configuration

All keys sit under `model_training`:

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Registers the `/admin/training` routes and the training manager. Without it the routes do not exist. |
| `retain_runs` | `5` | Finished runs kept in the run ledger. Older runs are dropped from it unless their predictions are still stored. The run directories stay on disk. |
| `grace_seconds` | `20` | After a cancel, seconds the run gets to exit before it is killed. |
| `split_seed` | `0` | Seeds the split assignment. Keep it fixed: changing it moves held-out items into training. |
| `splits` | `{train: 0.7, val: 0.15, test: 0.15}` | Split fractions, normalized to sum to 1. Use the names `train`, `val` and `test`: predictions are made for `val` and `test` (and for unlabelled items with `writeback.include_unlabeled`). |
| `aggregation` | `consensus` | How several annotators' labels become one. `consensus` is Dawid-Skene when there is more than one annotator (falling back to majority vote if it fails); `majority` is majority vote. |
| `max_wall_seconds` | unset | Time limit for one run. The server stops a run that exceeds it. The check runs each time the run reports an event. |
| `max_ram_mb` | unset | Address-space limit for the training process (`setrlimit`). Where the platform does not support the limit, the run logs a warning and continues. |
| `device` | `auto` | `auto`, `cpu`, `cuda` or `mps`, passed to the trainer. `sklearn-text` does not use it. |
| `num_threads` | unset | Sets `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `OPENBLAS_NUM_THREADS` for the run, unless they are already set. |
| `auto_retrain` | off | Retrain as annotations arrive. See below. |
| `writeback` | none | Publish predictions as prelabels. See below. |

### `auto_retrain`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Check for a retrain after every annotation save. |
| `trainer` | none | Trainer name. Required. |
| `schemas` | none | Schemes to train. Required. |
| `min_interval_s` | `600` | Seconds since the last run finished before another starts. |
| `update_frequency` | `25` | New annotations since the last automatic run before another starts. |
| `params` | `{}` | Trainer parameters, as in the `params` of an API run. |

When a check decides not to start a run, the reason ("waiting for 3 more
annotation(s)", "a run is already in progress") is in the `skip_reason` field
of `GET /admin/training/api/status`.

### `writeback`

| Key | Default | Meaning |
|---|---|---|
| `schemas` | `[]` | Schemes whose predictions are shown to annotators. Empty means none. |
| `min_confidence` | `0.0` | Predictions below this confidence are not published. A prediction with no confidence passes. |
| `field` | `predictions` | Item field the prelabels are written to. |
| `include_unlabeled` | `false` | Also predict on the items nobody has labelled yet, and prelabel them. Without it a run predicts only on its held-out `val` and `test` items. |

### Example

```yaml
model_training:
  enabled: true
  retain_runs: 5
  split_seed: 0
  splits: {train: 0.7, val: 0.15, test: 0.15}
  aggregation: consensus
  max_wall_seconds: 1800
  max_ram_mb: 4096
  num_threads: 4
  auto_retrain:
    enabled: true
    trainer: sklearn-text
    schemas: [sentiment]
    min_interval_s: 600
    update_frequency: 25
    params:
      classifier: sklearn.linear_model.LogisticRegression
      classifier_kwargs: {max_iter: 1000}
  writeback:
    schemas: [sentiment]
    min_confidence: 0.8
    include_unlabeled: true
```

---

## The `sklearn-text` trainer

The one built-in trainer. It needs no optional install for text, because
scikit-learn is a core dependency.

- **Kinds:** `nominal` (`radio`, `select`), `ordinal` (`likert`) and
  `multilabel` (`multiselect`). A multilabel target is trained as one class per
  combination of labels. Other kinds (sliders, spans, free text, geometry) have
  no trainer, and the Training page greys them out.
- **Modalities:** `text` and `image`.
- **One scheme per run.** The page sends one scheme. The API accepts a list,
  but the trainer fits only the first scheme named.

Parameters, set through `params` on an API run or under
`auto_retrain.params`. The **Train now** button sends none, so a run started
from the page uses the defaults.

| Parameter | Default | Meaning |
|---|---|---|
| `classifier` | `sklearn.linear_model.LogisticRegression` | Dotted path to any scikit-learn-API estimator. An `SVC` gets `probability: true` so it can report confidence. |
| `classifier_kwargs` | `{}` | Passed to the estimator's constructor. |
| `vectorizer` | `sklearn.feature_extraction.text.TfidfVectorizer` | A dotted path, `sentence-transformers`, or `clip` (also `image`) for images. On an image corpus the default is `clip`; see below. |
| `vectorizer_kwargs` | `{}` | For a dotted path, passed to the constructor (`ngram_range` may be a list). For `sentence-transformers`, `model_name` (default `all-MiniLM-L6-v2`). For `clip`, `model_name` (default `clip-ViT-B-32`), `cache_dir` and `image_root`. |
| `calibrate` | `true` | Calibrate the confidences, and keep the calibrated model only if it did not cost more than 0.05 training accuracy. Skipped below 50 training items, or when the smallest class has fewer than 2. Platt scaling below 1000 items, isotonic from there. |
| `min_instances` | `10` | Refuse to fit with fewer items in the train split. |

The classifier and vectorizer take dotted paths only. The short names that
[active learning](active_learning_guide.md) accepts (`tfidf`, `logistic`) are
not expanded here: a name that cannot be imported falls back to the default
with a warning in the run's log.

A text vectorizer always reads the item's text (the `text_key` field), never a
media or URL field. The run's `model_card.json` records `input: text` or
`input: media`, and prediction feeds the model the same input it was fitted on.

`sentence-transformers` and `clip` need `pip install sentence-transformers`
(`clip` also needs `pillow`). When they are missing, the run fails with the
install command.

---

## Image classification

A `radio` or `multiselect` scheme whose items name image files trains as an
image classifier. When at least 80% of the labelled items carry an image
reference ending in `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`, `.tif`, `.tiff`
or `.gif`, the bundle is marked as an image corpus and `sklearn-text` uses
CLIP image embeddings unless the run names a vectorizer.

```bash
pip install sentence-transformers pillow
```

```yaml
item_properties:
  id_key: id
  text_key: image_url

annotation_schemes:
  - annotation_type: radio
    name: species
    description: Which animal is in the photo?
    labels: [cat, dog, bird]

model_training:
  enabled: true
```

```json
{"id": "img_001", "image_url": "data/images/img_001.jpg"}
```

Where the image reference comes from: the scheme's `source_field` if set,
otherwise the first non-empty item field among `image_url`, `image`,
`image_path`, `file_name`, `audio_url`, `audio`, `audio_path`, `video_url`,
`video`, `video_path`, `url` and `path`.

**Images must be local files.** A relative path is resolved against
`task_dir`, and a URL-style path such as `/media/img_001.jpg` (what the
annotation page uses) against the task's `media_directory`; the file is linked
into the run's bundle. Remote `http(s)` URLs are not downloaded. An image run
leaves out every row whose image is remote or missing, and the run log says
how many; the model gives no prediction for such items. Download remote images
into `media_directory` to train on them.

To train an image corpus on text instead, name a text vectorizer in `params`.

---

## Write-back

After a successful run, its predictions are stored, and the ones that pass
these checks are written into the item's `predictions` field (or
`writeback.field`) as prelabels. The checks run in this order, and each skip is
counted in the run's write-back report (the `writeback` field of
`/admin/training/api/status`):

1. **Train-split items are never prelabelled.** A model is confident about its
   own training data for reasons that say nothing about new data.
2. **Only schemes in `writeback.schemas`** are published. The list is empty by
   default, so turning training on changes nothing annotators see.
3. **Pairs a reviewer rejected are skipped.** An `(item, scheme)` pair with a
   `reject` verdict in [model review](model_review.md) is not shown again.
4. **The confidence floor.** Below `min_confidence`, the prediction is stored
   but not published.

Write-back does not change human labels. Predictions go into item data;
annotations live in user state, which write-back does not address.

By default a run predicts only on the items in its `val` and `test` splits,
which already have a resolved human label, so items nobody has labelled get no
prediction. Set `writeback.include_unlabeled: true` to predict on those items
too: the run's bundle then carries them as an `unlabeled` file that the model
predicts on but is never trained or scored on, and their predictions pass the
same checks. This is the setting for using prelabels to speed up annotation
(with [model review](model_review.md) serving them least-confident first).
Prelabels anchor annotators, so turn it on once the held-out score supports
it.

One prediction is kept per item and scheme: a newer run replaces an older
one. At startup, the stored predictions for the schemes in
`writeback.schemas` are written back into item data, so prelabels survive a
restart. The replay applies the same checks as above, so a training item, a
rejected pair or a prediction under the floor stays off after a restart too.

To withdraw a run's prelabels, send `DELETE /admin/training/api/runs/<run_id>/predictions`.
This removes the stored predictions. Prelabels already written into item data
stay until the server restarts.

---

## Routes

All routes are under `/admin/training` and need admin access (an admin
session, or `X-API-Key`). POST and DELETE requests from a browser must be
same-origin.

| Route | Purpose |
|---|---|
| `GET /admin/training` | The Training page: start a run, the run list, the trainers. |
| `GET /admin/training/runs/<run_id>` | One run: status, metrics, events, the split of each item. |
| `GET /admin/training/api/trainers` | Every trainer, its kinds, modalities, licence and whether it is installed. |
| `GET /admin/training/api/schemas` | The study's schemes, their kind and the trainers that fit each. |
| `GET /admin/training/api/status` | The current or last run: state, step, progress, metrics, warnings, `skip_reason`, `writeback`. |
| `GET /admin/training/api/runs` | Run history (`?limit=`, default 50, at most 500). |
| `GET /admin/training/api/runs/<run_id>` | One run's record, plus `review`: precision from review verdicts on its predictions. |
| `GET /admin/training/api/runs/<run_id>/events` | The run's event log (`?limit=`, default 200). |
| `POST /admin/training/api/runs` | Start a run. |
| `POST /admin/training/api/runs/<run_id>/cancel` | Cancel the run in progress. `400` if no run is in progress. |
| `DELETE /admin/training/api/runs/<run_id>/predictions` | Withdraw the run's stored predictions. |

Starting a run:

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/admin/training/api/runs \
  -d '{"trainer": "sklearn-text", "schemas": ["species"],
       "params": {"vectorizer": "clip",
                  "vectorizer_kwargs": {"model_name": "clip-ViT-B-32"}}}'
```

The body takes `trainer`, `schemas` (a list, or one name as a string),
`params`, and `accept_licence`. A missing trainer or scheme is a `400`. A
trainer whose licence needs acknowledging returns `400` with
`needs_licence_ack: true` until the request sets `accept_licence: true`
(`sklearn-text` does not need it). One run at a time: a start while a run is in
progress returns `409`.

On the Training page, the Runs table's score column shows `accuracy` when the
trainer reports it and `train_accuracy` otherwise. `sklearn-text` reports only
`train_accuracy`, the accuracy on the data it was fitted on, so for it the
column overstates how the model does on new items. The `review` figures on
`/api/runs/<run_id>` are measured on predictions a human looked at.

---

## Where runs are stored

Each run has a directory under
`<task_dir>/<output_annotation_dir>/training/runs/<run_id>/`:

| Path | Contents |
|---|---|
| `bundle/` | The training data: `train.jsonl`, `val.jsonl`, `test.jsonl`, `unlabeled.jsonl` (with `include_unlabeled`), `labels.json`, `manifest.json`, and `media/` (symlinks to the images, or copies where symlinks are unavailable). |
| `artifacts/` | `model.pkl`, `model_card.json`, `predictions.jsonl`. |
| `spec.json` | What the run was asked to do. |
| `events.jsonl`, `stdout.log`, `stderr.log` | The run's progress events and output. |

The ledger (runs, each item's split per run, stored predictions) is in the
project database, `<task_dir>/project.sqlite`, in the tables `training_runs`,
`training_run_items` and `training_predictions`.

Set `POTATO_MODEL_CACHE` to a directory to have the training process use it
for `HF_HOME`, `TRANSFORMERS_CACHE` and `SENTENCE_TRANSFORMERS_HOME`, unless
those are already set. On an air-gapped machine, put the sentence-transformers
and CLIP models there in advance.

---

## Troubleshooting

**`/admin/training` returns 404.** `model_training.enabled` is not `true`. The
routes are registered only when it is.

**"Only N items in the train split; this trainer needs at least 10."**
Annotate more items, or lower `min_instances` in `params`. The train split is
70% of the labelled items by default.

**"Schema 'x' has 1 distinct label(s) in the data."** A classifier needs at
least two labels in use.

**"No resolved annotations to train on."** The scheme named in the run does
not match the scheme being annotated, or nothing has been annotated.

**The run was killed and the message says the machine ran out of memory.** The
process exited on SIGKILL, usually the out-of-memory killer. Use a smaller
model, fewer items, or set `max_ram_mb` so the run fails inside its own limit.

**The run published no prelabels.** Read the `writeback` report in
`/admin/training/api/status`. "Write-back is not enabled for any schema" means
`writeback.schemas` is empty; the skip counts say how many predictions each
check removed.

**An image run trained on file names.** No item field named the image (see
[Image classification](#image-classification)), so the bundle was not marked as
an image corpus, or the run's `params` named a text vectorizer.

**An image run left out most of its rows.** The run log says "Left out N ...
row(s) with no local image file": the images are remote URLs or the files are
not where the reference points. Store them under `media_directory` (or give
paths relative to `task_dir`).

---

## Related documentation

- [Reviewing Model Output](model_review.md): the review queue that prelabels feed
- [Active Learning Guide](active_learning_guide.md) and
  [Vision Active Learning](vision_active_learning.md): ordering items by model uncertainty
- [Labeling engine distillation](../labeling-engine/configuration.md#distill):
  a trained model as the first tier of the engine's cascade

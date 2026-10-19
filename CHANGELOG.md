# Changelog

All notable changes to the Potato annotation platform are documented in this file.

## [Unreleased]

### Features

- **Plugins.** A package can add annotation and display types by declaring a
  `potato.plugins` entry point, and a project turns it on with
  `plugins: [name]`. Only listed plugins load, by entry-point name, never a
  path. A collision with a built-in or another plugin's type, or an error
  inside the plugin, registers nothing. A plugin's scripts and styles are
  served at `/plugin-static/<plugin>/` and loaded on the project's pages.
  `potato plugins` lists installed plugins; the MCP server gains
  `list_plugins` and a `plugin` field on its type listings. An installable
  example is in `examples/plugins/counter/`. See *Plugins*.
- **Langfuse step scores and score configs.** Write-back sends a score per
  step for step-level trace schemes (`process_reward` and the other trace
  types), on the step's own Langfuse observation. With
  `writeback.langfuse.score_configs: true`, each score carries a Langfuse
  score config built from the scheme's labels or scale, attached only where
  every value Potato can send fits it. See *Trace Score Write-Back*.
- **Google Cloud Storage and Azure Blob sources, prefixes, and live object
  stores.** `data_sources` gains `type: gcs` and `type: azure_blob`, and S3,
  GCS and Azure take `prefix` (every JSON, JSONL, CSV and TSV object under it)
  as well as `key`. In prefix mode, `live_ingestion` picks up new objects
  while the study runs, resuming part-way through an object when a batch
  stops there. Live ingestion was database-only. The list of source types now
  comes from one place (the loader's enum). Install with the `s3`, `gcs` or
  `azure` extra. See *Remote Data Sources*.
- **Throughput tab in the admin dashboard.** Items per active hour and the
  median active time per item, for the project, per annotator and per day,
  from each annotator's own interaction events (idle gaps capped at five
  minutes; only saved items count). With the review workflow on, each
  annotator also gets first-pass approval and rework rates.
  `/admin/api/throughput` serves the same report. See *Admin Dashboard*.
- **Memo threads and issues, including issues on image regions.** Notes in
  the Notes panel can be answered: replies sit under the note, take its
  visibility, and follow it if it changes. A note can be raised as an issue,
  open or resolved, with an optional assignee; the author, the assignee or an
  adjudicator resolves it, and the issue records who did and when. With a
  shape selected on an image, a note can be attached to that shape, and its
  badge selects the shape again. The admin overview counts open and resolved
  issues (`/admin/api/memo_issues` lists them); `/api/memos` gains
  `POST /<id>/reply`, `status` and `assignee` on `PATCH`, and
  `GET /issues?status=&assignee=me`. Existing project databases gain the
  thread table on first use. See *Memos*.
- **Trace score write-back to Langfuse and LangSmith.** With
  `trace_ingestion.writeback`, a trace ingested from Langfuse or LangSmith gets
  its merged answer back once `min_annotators` people have judged it (or after
  adjudication, with `trigger: adjudicated`): a Langfuse score or a LangSmith
  feedback per scheme, named `potato.<scheme>`, with the annotator count, the
  distribution of answers and the pairwise agreement in its comment and
  metadata. Delivery runs from a SQLite queue with retries; a changed answer
  replaces the earlier score and an unchanged one is not re-sent.
  `/admin/api/trace_writeback` reports the queue. See *Trace Score Write-Back*.
- **Citable project snapshots.** `potato snapshot create|list|show|diff|tag|verify`
  freezes a project's config, data, annotations and databases under an id
  like `20261019-120000-335ae51e`, with a content hash over the config, data
  and answers, read-only files, and Paper Mode's agreement summary. `create`
  writes nothing when nothing changed; `diff` reports items, annotators and
  answers added, removed or changed and the change in alpha; `verify`
  re-hashes a snapshot from its own bundle. The publish page has a Snapshots
  card (`/admin/api/snapshots`), and every publish freezes a snapshot and
  names it in the dataset card's citation section. See *Project Snapshots*.
- **FiftyOne annotation backend.** `view.annotate(..., backend="potato")`
  writes a FiftyOne view out as a Potato project for several annotators
  (`annotations_per_item`), with any existing labels as pre-annotations.
  `dataset.load_annotations()` brings back one merged label per sample
  (majority class; boxes matched by overlap and averaged; an adjudicator's
  decision where there is one), optionally each person's labels in
  `<field>_<username>`, and stores Krippendorff's alpha and the geometry
  agreement report in `dataset.info["potato_agreement"]`. Classification,
  classifications, detections, polygons and polylines on images. Install with
  `pip install "potato-annotation[fiftyone]"`. See *FiftyOne Annotation
  Backend*.
- **Measure whether AI assistance changes the answers.**
  `ai_support.holdout: {fraction, salt}` withholds every assistance surface
  (pre-annotations, hints, option highlights, visual AI, critique, chat, the
  inline judge, PRM pre-labels) from a random, stable share of (annotator, item)
  pairs, using the same checks as the labeling engine's blind items. A new
  **AI influence** admin tab (`/admin/api/ai_influence`) compares the groups per
  scheme: agreement with the model's answer, gold accuracy and alpha within
  each group, with a bootstrap interval on the difference. See *Measuring AI
  Influence* and `examples/ai-assisted/assist-holdout/`.
- **Grid labeling.** `grid_view: {enabled, scheme, page_size}` serves
  `/annotate/grid`, a page of tiles for one radio or multiselect scheme: select
  tiles by click, Shift-click, Ctrl/Cmd-click or arrow keys, apply a label by
  button or number key, and save the page. Items come from the annotator's own
  assignment and saves go through `/updateinstance`, so assignment, the
  per-item cap, quality control and agreement count grid labels like any
  others. Attention checks and gold items are placed among the tiles at the
  configured frequency and scored as on the normal page. See *Grid Labeling*
  and `examples/classification/grid-view/`.
- **Per-object attributes, with agreement over them.** An `image_annotation`
  scheme can declare `attributes`: typed fields (`select`, `multi`, `text`,
  `number`, `bool`) that the annotator sets for each shape in a panel under the
  image, with per-label scoping, defaults, `show_if` conditions and `required`
  (Next is refused, and the banner says how many shapes still need one).
  `/admin/iaa` reports Krippendorff's alpha per attribute over the objects two
  annotators drew in the same place (nominal for select and bool, interval for
  number, MASI for multi) with raw percent agreement beside it. COCO export
  writes them under `attributes` and the COCO importer reads them back; the
  CVAT, KITTI, MOT and Darwin exporters already wrote them. See *Per-Object
  Attributes* and `examples/image/object-attributes/`.
- **Label Studio and Argilla projects import whole.** `potato import` reads a
  Label Studio JSON export (with its labeling config XML via `--ls-config`)
  and an Argilla 2.x dataset (a `to_disk` folder, a `to_hub` snapshot, or
  `-f argilla --hf-dataset <repo>`). Questions become annotation schemes, model
  suggestions become pre-annotations with the model and score kept in a
  `prediction_sources` column, and with `--keep-annotators` each source
  annotator's answers become that person's saved work, so agreement between
  them is reported as soon as the server starts. Label Studio spans are
  converted from UTF-16 offsets to code points. Unsupported questions (Label
  Studio Pairwise, Ranker, Taxonomy, BrushLabels, relations; Argilla ranking)
  are left out and counted. Argilla's `records.json` does not record whether a
  response was submitted, so a `to_disk` import keeps every response and says
  so; a `to_hub` import keeps only submitted ones. With `--keep-annotators` the
  generated project closes enrolment to the imported names and starts
  passwordless, since the source tools' passwords are not exported. See
  *Coming from Label Studio* and *Coming from Argilla* in the guides.
- New deploy preflight finding D022 (error, public deployments): annotator
  accounts that hold saved work but have no password, on a study that does not
  require one. Anyone who knows such a name could sign in as that person.

### Validation

- **`potato validate` now checks the keys on each annotation scheme against
  its type.** A key the type does not read, such as `totally_made_up: 3` on a
  radio, `default_low` on a range_slider or `lables` for `labels`, used to load
  silently and pass `--strict`. It is now reported as an unrecognized key, with
  a suggestion when one is close, and `--strict` fails on it. Schemes in phase
  page files (`phases.<name>.file`, JSON, JSONL or YAML) are checked as well as
  inline ones. The check found 14 such keys in the shipped example configs, 20
  unread `id` keys in their phase files, and 22 in docs snippets, all removed or
  corrected:
  - The slider snippets in the schema gallery and configuration guide used
    `min`, `max` and `default`. A slider requires `min_value`, `max_value` and
    `starting_value`, so the snippets failed validation as written.
  - `docs/agent-evaluation/web_agent_annotation.md` described `per_step: true`
    as giving a scheme one answer per trace step. Nothing implements it; the
    page now says so and points to `process_reward`.
  - `hierarchical_multiselect` documented `expand_depth`, which nothing reads.
    The tree always starts collapsed.
  - Also removed: `horizontal` and `single_select` on multiselect, `colors` on
    span (use a `color` on each label), `slider_min`/`slider_max` on
    confidence (`min_value`/`max_value`), and `title`, `display_config`,
    `dynamic_labels` and `sequential_key_binding` on types that do not read
    them.
- Four keys the code reads were missing from the registry and are now
  declared: `ai_support` and `keybinding_strategy` on every scheme type,
  `propagation` on video_annotation, and `option_randomization` on multirate.
- A display option whose value is not the type its default is, such as
  `screenshot_max_height: tall` on a web_agent_trace, is now a validation
  warning. It used to fail only at render time, when the page fell back to
  plain text.
- An enabled `labeling_engine` with `contracts: []` is now a warning. It
  validated clean and then accepted no machine label.
- The validation report has a `notes` list carrying the deprecation notes for
  `pre_annotation`, `icl_labeling` and `judge_calibration`. The CLI printed
  them only to stderr, once per process, so the MCP `validate_config` tool
  never returned them. Notes never fail `--strict`.
- New `validation.acknowledge`: a list of warning texts a study expects, so
  `--strict` stops failing on them. A warning containing an entry is listed as
  acknowledged and not counted. Entries shorter than 12 characters are
  refused, and an entry that matches no warning is reported. The running
  server ignores the block and still logs the warnings.

### Fixes

- **The Langfuse poller ingested nothing.** It was started without the
  callback that adds a trace to the project, so every trace it fetched was
  dropped; it also read the trace list's observation ids as observations. It
  now adds each trace as an item, and reads Langfuse v4's Observations API,
  which self-hosted Langfuse v4 requires and Langfuse Cloud will require from
  2026-11-16, falling back to the older traces API on servers without it. A
  trace is taken once its run has finished (its root span has arrived), so a
  long LLM call is not cut off. New source keys: `lookback_hours`,
  `settle_seconds` and `max_trace_seconds`. Checked end to end against a
  self-hosted Langfuse 4.63.
- **`potato validate` now checks survey-phase question files.** A phase file
  with an unknown `annotation_type` passed validation and stopped the server
  at boot; validation and boot now run the same check.

- AI-assistant usage telemetry recorded the scheme as its position ("0",
  "1", ...) instead of its name, so the save path never matched an event to
  the annotator's final answer. It now records the name.

- **A deploy button backed up every deployment to the author's storage.**
  `potato deploy button --hf-backup-repo` wrote the author's dataset into
  `potato.deploy.yaml` with `restore_on_boot` on. A deployer without write
  access to it got failing backups, one with write access sent their
  annotations there, and a new deployment could restore the author's
  annotators. Each deployer now names their own destination at deploy time:
  `POTATO_BACKUP_HF_REPO`, or `POTATO_BACKUP_S3_BUCKET` with optional
  `POTATO_BACKUP_S3_REGION` and `POTATO_BACKUP_S3_ENDPOINT`. Heroku and
  Render ask for these with no default, and the AWS template takes them as
  required stack parameters. `button` ignores `--hf-backup-repo`, `--hf-token`,
  `--s3-bucket`, `--s3-region` and `--s3-endpoint` and says so. Regenerate an
  existing button with `--force`. The Railway steps now warn that a template
  shares the author's backup storage.
- A backup sink whose dataset or bucket comes from an unset `${VAR}` logs an
  error naming the variable instead of trying to back up to the literal text.
- `potato deploy up --provider huggingface` without huggingface_hub said to
  install `potato-annotation[deploy]`, which does not include it. It now says
  `potato-annotation[huggingface]`.
- **Imported per-object attributes were lost on the first save.** The CVAT,
  KITTI, MOT, Darwin and VIA importers put each shape's attributes (CVAT
  `<attribute>` elements, KITTI truncation and occlusion, MOT track id and
  visibility) on the object, but the image annotation page rebuilt every
  restored shape without them. Saving an imported item wrote the shapes back
  bare, and a CVAT or KITTI export lost those values with no warning. Restored
  shapes and masks now keep `attributes` through edits and saves.
- `potato import -i annotations.xml` rejected every single-file CVAT and
  Pascal VOC export as "neither JSON nor newline-delimited JSON". Only the
  directory form worked. An XML file now goes to the XML importers, with or
  without `-f`. A JSON file that starts with a UTF-8 byte-order mark also
  imports now, instead of failing to parse.

## [2.11.1] - Debug Without --host, Image Classifiers and Prelabels After a Restart

This release restores `--debug` on the default bind, which 2.8.2 through
2.11.0 refused. It also adds image classifiers to model training, lets a run
prelabel items nobody has labelled yet, and fixes prelabels that were lost on
every restart.

```bash
pip install --upgrade potato-annotation
```

### Image classification

- **Model training trains image classifiers.** A radio or multiselect scheme
  whose items name image files is now treated as an image corpus, and the
  `sklearn-text` trainer fits it on CLIP embeddings unless the run names a
  vectorizer. It used to fit TF-IDF on the file paths. `/media/...`
  references resolve against `media_directory`, and rows whose image is
  remote or missing are left out of training with a warning instead of
  becoming blank embeddings, and get no prediction. A text item that also
  carries a remote `image_url` is still a text item. The saved model does not
  contain the CLIP weights.
- **Image active learning works as documented.** `vectorizer: {name: image}`
  (or `clip`) builds the CLIP vectorizer, and every scheme, radio and
  multiselect included, gets the item's image. `image` was not a name the
  manager could build, so such a study was ranked by TF-IDF over file paths.
  `/media/...` references are read from `media_directory` and `image_root`
  defaults to `task_dir`; a retrain where most training images cannot be
  read fails with an error instead of ranking the queue on blank vectors.
- **The labeling engine distils image classifiers.** On an image study
  (`labeling_engine.distill.modality`, default `auto`; `image_field`) the
  distilled tier is a CLIP-embedding classifier and abstains on images it
  cannot read. A new tier is trained when the accepted labels have doubled
  since the last one.
- **Prelabels for unlabelled items.** `model_training.writeback.include_unlabeled:
  true` makes a run predict on the items nobody has labelled yet, and
  prelabel them under the usual write-back checks. A run used to predict only
  on its held-out val and test items, which are already labelled, so
  write-back never reached the items a prelabel is for.
- **Write-back prelabels show without a `pre_annotation` block.** They used to
  render only when an enabled `pre_annotation` block named the same `field`.
  A prelabel an earlier run left on an item a newer run trained on is taken
  down, and withdrawing a run's predictions takes its prelabels off the items
  at once rather than at the next restart.
- New page: [Model Training](docs/ai-intelligence/model_training.md).

### Fixes

- **`--debug` starts again without `--host`.** Since 2.8.2 a debug server
  on the default `0.0.0.0` bind refused to start unless `--host 127.0.0.1`
  was given, so `potato start config.yaml --debug` failed. It now starts on
  any bind and other machines can reach it. The admin-key bypass applies to
  requests from the machine the server runs on (loopback, no proxy
  forwarding header), on a `127.0.0.1` bind too, where 2.11.0 also let
  forwarded requests through. The media endpoints that fetch a caller's URL
  answer without a login only to those requests as well. The Werkzeug
  interactive debugger is still served only on a `127.0.0.1` bind.
  `POTATO_ALLOW_REMOTE_DEBUG` is no longer read. `--debug` alone keeps the
  login page; `--debug-phase` signs every visitor in as `debug_user`.
- **A text model trained on URLs.** Items with a `url`, `path` or `file_name`
  field gave the trainer that value instead of the text. A text vectorizer now
  always reads the text, and the model card records which input a model was
  fitted on.
- **Password resets failed under SSO.** With `method: oauth` and
  `allow_local_login`, the admin reset link, `/reset/<token>` and
  `potato reset-password` raised for every account. Local accounts can now be
  reset. For an SSO identity the admin routes answer 409, no reset link is
  issued, and the CLI says the provider manages the password.
- **`ai_support` refused OpenRouter.** `endpoint_type: openrouter` (and
  `open_router`, as the docs show) is accepted.
- **Prelabels did not survive a restart.** The startup replay of stored
  predictions ran before any item was loaded, so it failed on the first one
  ("Could not restore model predictions") and the model review queue emptied
  on every restart. It now runs after the items load, and applies the same
  checks as write-back: the leak guard, the confidence floor and reviewer
  rejections (it applied only the scheme check, and every prediction is
  stored, a run's training items included).
- **CSS lengths with units.** `max_height: "50vh"` and similar became
  `50vhpx` in the text, PDF, code, spreadsheet and live and web agent
  displays. A unit is now kept; a bare number still means pixels. The web
  agent trace display raised on any string `screenshot_max_height` and the
  page showed the item's text field instead.
- `labeling_engine.distill.image_field` must be a field name.
- The embedding vectorizers declare scikit-learn tags, which scikit-learn
  1.8 will require.

### Documentation

A review of the docs against the code for the 2.9 to 2.11 releases. It
corrected wrong commands (`potato export`, the export CLI's flags), wrong
URLs (curation routes, `/go_to`), wrong defaults and response shapes, stale
counts (now checked by tests), keys documented in the wrong place, the debug
`--host` requirement, the Hugging Face Spaces and backup pages, and SSO
behaviour, and added successor notes pointing older machine-labeling
features to the labeling engine.

## [2.11.0] - The Labeling Engine

Potato can now label a dataset with models and use people to measure how
often the models are wrong. You declare what the finished labels must
satisfy; the engine asks people for a blind random sample, tests the machine
labels against it, accepts what the test supports and sends the rest to
people. The result is the dataset plus a certificate that says what was
tested and on how many human labels.

```bash
pip install --upgrade potato-annotation
```

### The labeling engine

Turn it on with a `labeling_engine` block and `assignment_strategy: engine`.
See [the documentation](docs/labeling-engine/overview.md).

- **Sources.** LLMs, vision-language models, decision models (Laya, and any
  `/v1/systemone` server such as Jev or OpenJev), YOLO detectors, LLM judges
  (with a label-order swap), juries, models trained on the study's own
  labels, and labels you already have. Sources are tried in cascade order;
  people come after the last.
- **Confidence.** Verbalized, k-sample agreement, or token log probabilities
  (one call, usually the best calibrated, on vLLM and OpenAI-compatible
  servers).
- **Contracts.** `selective_risk` (at most a stated share of accepted machine
  labels wrong, with stated confidence; Learn-then-Test on held-out labels),
  `ppi` (prevalence or mean intervals corrected for the machine's error,
  valid whatever its quality), `no_worse_than_human` (the alternative
  annotator test), `budget_first` (what a human budget buys),
  `distributional` (closeness to how people split on subjective items, with a
  split-half noise ceiling) and `threshold_legacy` (for translated configs).
- **Modalities.** One-of-N, ordinal, numeric and multi-label schemes; image
  regions; audio, video, temporal-grounding and tiered segments; 3D objects;
  and agent-trace step labels. Regions, segments, 3D objects and traces are
  scored with the measures the agreement report uses.
- **People.** Team, crowd (Prolific; a dry run unless live spend is turned on
  and `budgets.human_usd` is set) and solo pools. Calibration requests are
  random with recorded inclusion probabilities, and blind: while a person
  holds one, and after they have answered it, the page shows no
  pre-annotation, inline judge or AI help, and the AI routes answer 403.
  Contested items go to adjudication. When every item has a label or the
  human budget is spent, annotators reach the completion page (and a crowd
  completion code) instead of waiting.
- **Acceptance.** A machine label is accepted only when every
  `selective_risk` and `threshold_legacy` contract on its scheme is met. When none can be (a
  contract is infeasible, or nothing more is being sampled), the remaining
  items go to people within the budget.
- **Audits** watch accepted labels with an anytime-valid confidence sequence.
  A breach stops acceptance on that scheme (`features.drift`, on by default),
  and certifying again starts a new sequence.
- **Runs** are resumable and repeat no model call after a kill. Every call is
  logged with tokens, latency, cost and cache hits; prompts and replies are
  stored as hashes. Model and human-label budgets stop spending before they
  are exceeded. Optional PII masking for third-party APIs.
- **Distillation and optimization.** Train a cheap model on the study's
  labels and put it first in the cascade (cert and audit items never go into
  the training set); report cheaper cascades and better prompts, scored on
  dev labels only.
- **Interfaces.** `potato label run|status|certify|certificate|export|calls|
  distill|optimize|migrate-config` (`certify --retest` to test a rule that
  only dev labels changed; each test spends part of the error budget, so
  checking progress spends none); `/api/engine/v1`; five `engine_*` MCP
  tools; `potato.labeling_engine.sdk.Study`; and an admin page
  (`/admin/labeling-engine`) with contract status, the error-against-coverage
  curve, reliability per source, requests and the call log.
- **Exports.** `potato label export` writes labels with provenance, the
  certificate (JSON, Markdown, HTML), a dataset card and the call log. CSV,
  Parquet and Hugging Face exports gain `engine_purpose` and
  `engine_request` columns. Publishing and Paper Mode leave machine raters
  out of gold labels and agreement figures.

Older keys keep working. `icl_labeling`, `judge_calibration` and
`pre_annotation` print a note naming their engine equivalent;
`potato label migrate-config` writes it. Solo Mode and judge alignment are
not deprecated, and mirror their predictions into the engine when it is on.

Three examples under `examples/labeling-engine/` cover text sentiment,
images (boxes and a has-person label) and agent-trace judging.

### Solo Mode and LLM labeling (since 2.10.3)

- `solo_mode.suggestions` withholds the LLM's label on all items or a
  sample, and the handoff reads agreement on the blind items, since a shown
  suggestion anchors the person checking it.
- `ai_budget.cap_usd` is checked before labeling starts and before each
  batch, with spend recorded for each model called.
- A response cache (`solo_mode.cache`), a gold set with prompt trials
  (`solo_mode.gold`), a prompt-sensitivity check, a labeling jury
  (`solo_mode.jury`) and curriculum ordering
  (`instance_selection.curriculum`).
- Decision-model endpoints: `systemone` (hosted Jev, OpenJev on vLLM, Laya's
  server) and `laya` (in-process). `GET /admin/api/alt-test` runs the
  alternative annotator test on a declared machine annotator.
- Edge-case fields are now part of the response schema. Guided decoding on
  vLLM never returned them, so edge-case discovery during labeling did
  nothing.

### Agreement

- `/admin/iaa` now reports `spatial_annotation`, `temporal_grounding`,
  `tiered_annotation` and the agent-trace schemas (`process_reward`,
  `trajectory_eval`, `tool_call_review`, `failure_attribution`,
  `gui_trajectory`). They were skipped as unsupported. Temporal grounding
  (`{"events": ...}`) and tiered annotation (`{"annotations": {tier: ...}}`)
  are read in the shapes their widgets store.
- `/admin/api/agreement` no longer reports structured schemes (agent traces,
  segments, regions, 3D objects). Reduced to label names, every annotator
  agreed perfectly; it points to `/admin/iaa`, which matches the structures.
- Two identical zero-length segments (instants) now count as agreeing; they
  scored as complete disagreement.
- Paper Mode and the agreement module compute Cohen's kappa through the same
  function as `/admin/iaa`.

### Fixes that affect 2.10 studies

- **An image page saved a prefilled answer on its own.** On an
  `image_annotation` scheme with `pre_annotation`, the canvas re-laying itself
  out after load saved the prefilled shapes as the annotator's answer before
  they touched anything, so an untouched item counted as answered. Only an
  edit saves now.
- **Solo Mode's "Generate prompt" never called a model.** Setup stored the
  task description wrapped in a sentence. It now asks the revision model to
  write the first prompt, and falls back to the description, saying so, when
  there is none.
- **Refusals over `potato mcp connect` looked like successes.** A refused tool
  call (a missing permission, a bad parameter) came back with `isError:
  false`; it is now a tool error carrying the server's message.
- **The full-study skeleton example had a dead key.**
  `training.feedback.enabled` is not a key; the example now sets
  `feedback.show_explanations`.
- **Images on hosts without CORS headers did not load.** The canvas asked
  for every image with CORS, and a host that sends no
  `Access-Control-Allow-Origin` header (cocodataset.org is one) refused, so
  the page showed "Failed to load image". It now loads such an image again
  without CORS. Drawing works; region fill and SAM and text-prompt
  segmentation, which read the image's pixels, say why they cannot.
- **A pre-annotated shape without a `color` was dropped.** The item showed
  "Annotations: 0" with no warning. The shape now takes its label's colour.
- **Idle sessions were never signed out.** The idle-timeout check was
  registered on an app object that `potato start` discards, so
  `session_timeout_minutes` had no effect.
  It now runs on the app that serves requests: a session idle for 8 hours
  (the default) is cleared and the next request goes to the login page.
  Kiosks and shared lab machines that stay signed in overnight will start
  seeing sign-outs; raise `session_timeout_minutes` where that matters.

### Bug fixes

- **Persistence committed other threads' transactions.** `get_db` re-ran the
  migration script on every cached call, which committed whatever another
  thread had open on the same connection.
- **Adjudication counted machine raters.** `try_enqueue_item` let machine
  annotators trigger adjudication, ignored `min_human_annotations`, and
  crashed formatting a missing agreement score.
- **Prolific auto-scaling counted machines and ignored per-item caps.** The
  number of places to open now counts only human annotations against each
  item's cap.
- **LF extraction failed on endpoints that return parsed JSON.** vLLM,
  Ollama and OpenRouter return an already-parsed reply, so labeling-function
  extraction never produced a function on those backends.
- **Annotation, admin and adjudication pages.** Fixes from a UI audit
  include a leftover keydown logger that echoed every key an annotator
  pressed to the browser console, span highlights that left the text under
  them at about 2:1 contrast (now about 12:1), agent-trace panes clipped at
  500px, and an adjudication confidence that started filled in and was lost
  when a decided item was reopened.
- **Deploy checks passed with a missing extra.** `potato deploy check` now
  reports BLOCKED (`ok: false` with `--json`) and `up --dry-run` refuses,
  instead of passing and then failing at create time. Every deploy target
  now defaults to the image tag of the installed version, not `:latest`.
- **Registering an existing account.** `/register` with a known username
  says "already exists. Log in instead." Its error pages now render with the
  task's title, password field and SSO buttons.
- `potato/user_config.json`, three 2020 test accounts read by nothing, is
  removed.

## [2.10.3] - Agreement, Deploy Button and Pyodide Fixes

Three fixes for bugs found in 2.10.2 after it was published.

```bash
pip install --upgrade potato-annotation
```

### Bug fixes

- **`/admin/api/agreement` when everyone agrees.** If every annotator gave
  the same answer on every item, the schema came back as
  `{"error": "float division by zero"}`. Chance agreement is 1 in that case,
  so alpha and both kappas are undefined. The route now reports them as
  `null`, with `percent_agreement` 1.0 and the same note `/admin/iaa` gives.
  `overall` leaves the schema out of its averages.
- **`potato deploy button --dry-run` stays offline.** Without
  `--hf-backup-repo`, the dry run asked HuggingFace who the token belonged
  to, and a bad token ended in a traceback. The dry run now uses the
  placeholder `<hf-account>/<name>-annotations`, as `potato deploy up
  --dry-run` does. A real run reports a rejected token as an error message.
- **Importing Potato no longer hashes a password.** `potato.authentication`
  computed a PBKDF2 hash at import, used to make failed logins for unknown
  usernames take as long as real ones. That cost every process 100,000
  PBKDF2 iterations at startup, CLI tools included, and broke the import
  under Pyodide, whose `hashlib` has no `pbkdf2_hmac`. The hash is now made
  the first time an unknown username tries to log in.

## [2.10.2] - Security, MySQL, Agreement and Packaging Fixes

This release fixes features that did not work from a pip install or the
published Docker image, closes several ways to sign in as someone else,
makes the MySQL backend work, and corrects agreement statistics that could
be wrong in reported results. Upgrade if you install Potato with pip,
deploy it with `potato deploy`, use SSO or MySQL, or report agreement
numbers from Potato.

```bash
pip install --upgrade potato-annotation
```

If you published agreement numbers from an earlier version, recompute them:
see [Agreement statistics](#agreement-statistics) below.

### Security

- **SSO accounts could be signed into with any password.** On a task with
  OAuth, the password form accepted any password for an account a provider
  had registered. SSO identities now never authenticate by password, local
  accounts (`allow_local_login`) cannot take an SSO user's name, an SSO-only
  task shows only the provider buttons, and `/register` answers 403.
- **Losing `user_config.json` let a stranger take over an annotator.** With
  the MySQL backend, anyone could register an existing annotator's username
  and inherit their work. Registration now checks the database.
- Potato now also refuses cross-site requests to the admin crowdsourcing
  routes, such as worker payments, usernames that are paths, dashboard viewers taking over accounts, debug
  mode on a public address, access to other users' live-agent and
  coding-agent sessions, MCP exports written outside the exports folder, and a Clerk
  session for a different username.

### pip and Docker

- **`ai_support` failed at startup.** The wheel left out `potato/ai/prompt/`,
  so the server stopped with "Default annotation directory does not exist".
- **Survey instruments stopped the server.** The wheel left out
  `potato/survey_instruments/`, so a study with an instrument such as `tipi`
  in a pre- or post-study phase failed with "Failed to load phase", even
  though `potato validate` passed it.
- **pip installed a top-level `tests` package.** Potato's own test suite went
  into site-packages beside `potato`, where `import tests` in your project
  could pick it up.
- **Every Docker boot logged a gunicorn error.** gunicorn 26 opens a control
  socket under `$HOME/.gunicorn/`. A container run as a user with no home
  directory logged "Control server error: Permission denied: '/.gunicorn'".
  Potato now turns the socket off. The server worked either way.
- **Containers left ten subsystems off.** Containers and every `potato deploy`
  target start the server through `create_app()`, which skipped chat support,
  MACE, active learning, the ICL labeler, diversity ordering, the embedding
  view, expertise routing, the directory watcher, agent sessions and OAuth.
  A deployed study with chat support showed the sidebar and answered 404.
  The default image now includes Authlib, so an OAuth study no longer exits
  at boot.

A test now checks that every tracked file under `potato/`, apart from design
notes, ships in the package.

### MySQL

- **The MySQL backend never turned on.** A swallowed circular import sent
  every MySQL config to the file backend. A missing driver or unreachable
  server now stops startup, and `pip install potato-annotation[mysql]`
  installs the driver.
- **Tools found no annotations on a MySQL study.** Export, Paper Mode,
  auto-export, model training, `potato repair`, annotation filtering, the
  admin data archive, `potato deploy pull` and backups read only the file
  backend. They now read the database. A MySQL study always pulls over
  HTTPS.
- **Backups restored over a live MySQL study on every boot.** Restore now
  runs only when both the output directory and the database are empty.
- **File-backend work is imported at boot.** A file study switched to
  MySQL, or a restored backup, used to leave its `user_state.json` files
  unread. Annotators the database does not hold are imported; the database
  copy wins when both exist.
- Offline tools now expand `${VAR}` in the database password, as the server
  does.

### Deployment and configuration

- VM providers show an update plan on re-run, refuse changes to settings
  they cannot change in place, and rewrite the systemd unit before
  restarting. Render mounts its disk at `/app`, refuses a free plan with a
  disk, and redeploys the new image, as Railway now does too. ECS destroy
  removes every parameter. Unknown prices show as "not estimated", not $0.
- `num_annotators_per_item: 0` means unlimited, `${secret}` references are
  substituted, the rooms schema validates, and `failure_action:
  repeat_training` restarts training as documented.
- Install hints in the AI endpoints, SAM and the sklearn trainer name
  extras that exist.

### Agreement statistics

59 fixes, each checked against a reference implementation (scipy, sklearn,
statsmodels, `krippendorff`, pycocotools, pygamma-agreement) or a
simulation with known truth.

- **An undefined coefficient is now reported as undefined, with a note,
  not 1.0.** This covers one label used throughout, nothing comparable, and
  a tied vote, in Fleiss and Cohen kappa, Paper Mode, span token kappa and
  adjudication.
- **MACE** scored pure spammers at about 0.35 competence; they now fit at
  about 0.01. It also misread multiselect, free-text and dict-written
  answers.
- **Krippendorff's ordinal alpha** used neither the ordinal nor the interval
  metric. It now matches the `krippendorff` package.
- **Results changed after a restart.** Geometry, rollout and span-gamma
  chance baselines followed per-process hash order. KS tests scored
  identical samples as different.
- **Pairwise means paired the wrong items** under uneven coverage for
  ordinal, continuous and ranking answers. `kendall_tau` correlated item
  names, not ranks; weighted kappa dropped unused scale points; Fleiss kappa
  depended on rater order.
- Hungarian matching applied its threshold after assignment, and keypoints, 2D cuboids and freeform shapes scored 0
  against themselves.
- IBWS left about 13% of items unshown per round,
  `plackett_luce` was Bradley-Terry, BWS Bradley-Terry counted each
  judgment twice, and gold auto-promotion promoted ties.

### Annotation data

- Readers of stored answers (adjudication, required follow-ups, attention
  checks, psychometrics, admin question stats, code co-occurrence) misread
  what the annotation page saves.
- The crowd tab counted no completed or in-progress workers, and time on
  task was always 0.
- Span offsets and labels with entities, tags or doubled spaces, and a
  cleared last checkbox, now survive the save and restore. Delimited data
  files keep cell text verbatim, and `data_sources` load the same items as
  `data_files`.
- Saved user-state fields, the IBWS round and attention-check blocks
  survive a restart.
- YOLO, Pascal VOC and CoNLL exports, filtering by prior annotation, and
  published survey keys are fixed.

### Point clouds

- **Clouds in map coordinates keep their precision.** A LAS file in UTM
  coordinates was drawn, and annotated, on a grid as coarse as 0.5 m.
  Potato now serves such clouds relative to a local origin and adds it back
  when saving, so annotations and exports stay in the file's coordinates.
  You don't need to re-centre files yourself.
- A dark point in a 16-bit LAS file is no longer shown near white.

## [2.10.1] - Deploy Dry Runs and Price Fixes

Fixes in `potato deploy` found after 2.10.0: dry runs that passed for deploys
`up` then refused, a wrong Jetstream2 flavor in the plan, `--demo` offered on
hosts where it cannot work, and two wrong prices.

```bash
pip install --upgrade potato-annotation
```

### Bug fixes

- **A dry run passed for a deploy that `up` refused.** Heroku or ECS without
  `--backup`, Render or Railway with no backup storage to upload the project
  to, and Fly with a project too large to send inline and no backup storage,
  all printed a clean plan and exited 0, then `up` failed. The plan and `up`
  now run the same check: both print `REFUSED: <reason>` and exit 2.
- **`--demo` was offered where it cannot work.** Render, Railway and ECS
  Express upload your project to the backup's storage, so they need
  `--backup hf` or `--backup s3` even for a disposable study. Their errors say
  so, and the D011 preflight warning offers `--demo` only for Heroku and
  HuggingFace.
- **`--cloud jetstream2` planned the wrong flavor.** The dry run showed
  `m1.small` while `up` created an `m3.small`. The Jetstream2 service-unit
  note no longer appears for other OpenStack clouds.
- **Two prices were wrong.** `potato deploy providers` and the docs said about
  $16/month for `aws-ec2` and about $7 for `fly`; the plans print $18.31 (the
  30 GB root disk adds $2.40) and $5.85. Both now say about $18 and about $6.
- **`backup: {enabled: false}` did not turn backup off** when the config still
  had a `huggingface_backup:` block. The new block wins.
- `potato deploy button` errors read "A aws button…" and mentioned Lightsail
  for every target. Each target has its own message.

### Documentation

- [Render](docs/deployment/deploy-render.md): the free-tier section suggested
  `--plan starter --volume-gb 1` without `--backup`, which Render deployments
  refuse. Both options now include a backup.
- [Backups](docs/deployment/deploy-backups.md) said every ephemeral host restarts
  daily. Only Heroku does; the page now gives when each host loses its disk.

## [2.10.0] - Eight Hosting Platforms, Backups and Text as Image

`potato deploy` gains eight hosting platforms: AWS (three ways), Heroku, Fly,
Railway, Hetzner, Vultr, Linode and OpenStack, including Jetstream2. Data on
hosts whose disk does not last is now backed up to a HuggingFace dataset or an
S3 bucket and restored when the server starts. A new install guide covers
running Potato on your own machine and in the cloud. Separately,
`text_as_image` shows each item's text as a picture, so annotators cannot copy
it into a chatbot.

```bash
pip install --upgrade potato-annotation
```

### Installing and deploying

[Installing and running Potato](docs/deployment/installation.md) is the new
starting point. It covers pip, source and Docker on your own machine, then
suggests a host for each situation:

| Situation | Command |
|---|---|
| Trying it out | `potato start config.yaml`, then `potato share` |
| You have an AWS account | `potato deploy up config.yaml --provider aws` (Lightsail, $12/month) |
| US researcher with an ACCESS allocation | `--provider openstack --cloud jetstream2` (no charge) |
| Cheapest VM | `--provider hetzner` |
| No server to look after | `--provider fly` or `--provider railway` |

#### New targets

- **AWS, three ways.** `--provider aws` creates a Lightsail instance: flat
  price, IPv4 included, and only `lightsail:*` permissions. `aws-ec2` is for
  accounts where Lightsail is turned off. `aws-ecs` runs the container on ECS
  Express Mode behind an AWS-managed HTTPS address. It costs more, requires a
  backup, and Potato makes deploys stop the old task before starting the new
  one, so two tasks do not write the same study. Credentials come from the
  usual AWS chain, SSO included.
  See [AWS](docs/deployment/deploy-aws.md).
- **Heroku.** One Basic dyno on the container stack. Heroku wipes the disk
  daily, so Potato refuses to deploy without `--backup` or `--demo`. See
  [Heroku](docs/deployment/deploy-heroku.md).
- **Fly** and **Railway**, each with a persistent volume. See
  [Fly](docs/deployment/deploy-fly.md) and [Railway](docs/deployment/deploy-railway.md).
- **Hetzner, Vultr and Linode.** VMs with a Let's Encrypt certificate for the
  IP address, as on DigitalOcean. See [VM providers](docs/deployment/deploy-vps.md).
- **OpenStack**, with a Jetstream2 preset. Jetstream2 gives the instance a DNS
  name, so it gets an ordinary certificate. Campus clouds and EGI work too.
  See [Jetstream2 and OpenStack](docs/deployment/deploy-openstack.md).

New extras: `deploy-aws` and `deploy-openstack`. The VM targets now share one
base, so DigitalOcean, Lightsail, EC2, Hetzner, Vultr, Linode and OpenStack
provision, update, pull and report logs the same way.

#### Deploy buttons

`potato deploy button config.yaml --target heroku|render|aws|railway` writes
the files for a "Deploy to Heroku", "Deploy to Render" or AWS "Launch Stack"
button into your repository and prints the README badge. Other people can then
run your task in their own accounts. No secrets are written. See
[Deploy buttons](docs/deployment/deploy-buttons.md).

### Backup and restore

A new `backup:` block mirrors the annotation output and snapshots of the
SQLite stores to a HuggingFace dataset, an S3-compatible bucket (S3, R2, B2),
or both. When the server starts with an empty task directory and the backup
holds data, it restores before loading anything, so annotators continue where
they left off after a restart. Pass `--backup hf`, `--backup s3` or
`--backup hf,s3` to `potato deploy up`. The old `huggingface_backup:` block is
read as a `backup:` block with one sink. See
[Backups](docs/deployment/deploy-backups.md).

### Text as image

`text_as_image: true` renders each item's text to a PNG on the server and
removes the words from the page, the embedded item record and the JSON
endpoints, so an annotator has nothing to select, copy or paste. It raises the
cost of the shortcut but does not remove it: an annotator can still retype the
text or run OCR on a screenshot. Potato refuses to start when the feature is
combined with a span scheme, Pocket Mode, Rooms, or audio and video text. See
[Text as Image](docs/advanced/text_as_image.md). (#169, Eyecatch3r)

### Bug fixes

- **Render deploys started without the project.** The service ran the bare
  image, which exited with "config file not found". The container now
  downloads the project at start, checks its sha256, and never overwrites
  collected data.
- **The HuggingFace backup only worked on HuggingFace Spaces.** On Render and
  DigitalOcean, `--hf-token` set a variable that nothing read.
- **The backup did nothing in the published image**, which did not include
  `huggingface_hub`. The image now installs the new `hosting` extra
  (`huggingface_hub`, `boto3`).
- **A restart on a host without a persistent disk lost earlier work.** The
  server started empty, and a returning annotator's new state overwrote the
  backed-up copy. Restore on start fixes this.
- **DigitalOcean with `--volume-gb` kept annotations on the root disk**, not
  on the volume. The output and the SQLite stores now live on `/data`.
- The Let's Encrypt contact email could not be set. Use `--acme-email`.
- The container can start as root and drops to the `potato` user, so hosts
  that mount root-owned volumes work.

### Compatibility

- Python 3.9 or later is now declared. A core dependency already required it,
  so 3.7 and 3.8 could not install; pip now says so before installing.

## [2.9.4] - Password Reset Fix and Phone Usability

A security fix for `/forgot-password`, which anyone could use to take over a
password account. Upgrade now if your server is reachable by people you do not
trust. This release also makes the annotate page usable on phones, adds
declared machine annotators, and fixes several reverse-proxy and deploy bugs.

### Security

- **`/forgot-password` gave a reset link to whoever asked**
  ([GHSA-43v4-43pw-4rp2](https://github.com/davidjurgens/potato/security/advisories/GHSA-43v4-43pw-4rp2)).
  The form needed no login. It created a reset token for any username
  submitted and showed the `/reset/<token>` link on the page, so anyone who
  could reach the server could take over any password account, admin-role
  accounts included. The form now creates no token and returns the same page
  for every username; that page tells the annotator to ask the
  administrator. Reset links come only from `POST /admin/create_reset_token` (admin key or RBAC
  admin) and the `potato reset-password` CLI. There is no setting to bring the
  old behaviour back: Potato sends no email, so it has no safe way to deliver a
  self-service link. Reported, with a patch, by HDEF (hdef-devteam).

### Phones

A sweep of 20 task types on an iPhone 13 found pages that fit on the screen but
were hard to use. On phones and other touch screens:

- The task scrolls with the page, not inside a box within it. That box came
  from the card height limit on image tasks and the 500px dialogue field.
- The header is two rows instead of three.
- The "desktop recommended" banner scrolls away instead of sticking, and shows
  only when a task has a scheme not known to work by touch (span linking still
  shows it).
- Radio and checkbox rows, Likert and semantic-differential buttons, ranking
  arrows, the slider and the image toolbar are at least 44px tall.
- Multirate becomes a list of labelled rows instead of a table cut off at the
  right edge.
- Likert end labels stay inside the card, keyboard-shortcut hints are hidden,
  and text inputs are at least 16px so iOS does not zoom in on focus.
- **Span highlighting works by touch.** Long-press to select text, and a
  "Highlight as" button appears at the bottom of the screen.
- A long task name no longer pushes the page wider than the screen.

Desktop is unchanged: size rules apply only to touch screens, layout rules only
to narrow windows. See "Phones without Pocket Mode" in
[Pocket Mode](docs/advanced/pocket_mode.md).

### Machine annotators

A study can list the raters that are programs (annotation tools, detectors,
LLMs) under a `machine_annotators` block. Before this they were either
pre-annotations in the item data, out of reach of agreement and adjudication,
or simulator users counted as people. With the declaration:

- `/admin/iaa` reports human–human, machine–machine and pooled agreement, with
  human-only headline figures; `/admin/api/agreement` and MACE leave machines
  out.
- Psychometrics can model tool ability, and adjudication can queue machine
  raters. Machine consensus never promotes gold on its own.
- csv, tsv, parquet, HuggingFace and publish-bundle exports gain
  `annotator_origin` and `annotator_origin_detail` columns when any record came
  from a machine; all-human studies export as before.
- `require_declaration` refuses writes from anyone neither declared nor on the
  roster.

See [Machine annotators](docs/advanced/machine_annotators.md) and the example in
`examples/advanced/machine-annotators/`.

### Bug fixes

- **Two studies on one host shared one session cookie.** Behind a reverse
  proxy serving `/app1` and `/app2`, logging in to one logged you out of the
  other. The cookie is now scoped to the URL prefix. Annotators do not need to
  clear cookies. (#172, Eyecatch3r)
- **Adjudication did not work behind a URL prefix.** Its API calls went to the
  bare host. Its header also lost the Logout button to a long task name, and
  the queue scrolled the page sideways below 768px.
- The phone-to-Pocket redirect, three redirects in Rooms and one on the
  codebook page dropped the URL prefix.
- **Redeploying to an existing HuggingFace Space failed with 402.**
  HuggingFace bills the create call even when the Space exists; `potato deploy
  up` now skips it for an existing Space.
- The nominal IAA report declared `percent_agreement` and `cohen_kappa` but
  emitted neither. Cohen's kappa is now computed per pair on shared items.
- The simulator CLI overwrote `user_count`, `strategy`, `parallel_users` and
  `output_dir` from its defaults, so a config file could not set them.
- On Windows, `docs/llms-full.txt` came out with every page twice (#173) and
  the config reference was written in the locale encoding (#174). Both from
  Eyecatch3r.

## [2.9.3] - AI Toolbar Fixes

Fixes two layout problems that 2.9.2 brought into the image and video AI
toolbar, and two edge cases in stylesheet caching.

### Bug fixes

- **The AI buttons ran off the side of the screen on phones.** 2.9.2 laid the
  button group out as a single row that could not wrap. At 390px, Review sat
  outside the card and tapping Hint scrolled the image sideways. The buttons
  wrap again.
- **An empty bar sat above the image on text-prompt pages.** That toolbar has
  no AI buttons, only suggestion controls and a loading indicator that start
  hidden, and 2.9.2 gave it a background and border. It is now hidden until
  one of them shows.
- **A byte range past the end of a stylesheet file was refused.** A stylesheet
  served with hashed references is longer than the file on disk, so a range
  starting between the two lengths got 416. It now gets the whole stylesheet
  with 200, as other ranges on a rewritten stylesheet already did.
- **A comment left open at the end of a stylesheet** had its `url()`
  references read as real ones. The comment now runs to the end of the file,
  as it does in the browser.

## [2.9.2] - Faster Navigation Between Items

Moving between items is faster: scripts and stylesheets stay cached, and Next
takes fewer round trips. The image and video AI panel works, and a text edit
made just before Next is saved.

### Changed

- **`chat_support.endpoint_type` accepts `openai_vision`, `anthropic_vision`
  and `ollama_vision`**, so chat can share a server and model with
  `ai_support` on an image task. The chat is still sent the instance text
  only, never the image.
- **Scripts and stylesheets are cached between instances.** Each one's URL now
  carries a hash of its contents and is served `immutable` with a one-year
  lifetime while the hash matches. Pages used to revalidate all ~40 of them on
  every Next, one round trip each. Fonts and `@import`ed stylesheets are
  covered too. An edited file gets a new hash, so it is never served stale.
  Static responses no longer carry the session cookie: a signed-in user's
  cookie is re-signed on every response, and the `Vary: Cookie` that came with
  it made browsers drop the cached files after a restart.
- **Next, Previous and go-to take fewer round trips.** The navigation request
  gets a short JSON reply instead of a full page that the browser discarded
  before loading the page again, and the 100 ms pause before loading is gone.
  The loading screen no longer waits for `/api/current_instance` or keyword
  highlights. Over a link with 80 ms round trips, Next on a radio-button
  task took about 2.6 s and now takes about 0.8 s.

### Bug fixes

- **Four feature bundles loaded on every page.** The PDF-link viewer, the
  web-agent recorder, the live coding-agent viewer and per-label visibility
  were detected by markers that also appear in the page template's own script
  tags or comments, so every task loaded them. The scan now ignores comments
  and script elements. An inline script that only looks an element up no
  longer counts as the element. The turn-annotation, multi-agent-discussion,
  audio-dialogue, run-tree and entity-linking scripts, which had no condition
  at all, now load only on pages that use them.
- **The image and video AI suggestion panel did nothing.**
  `visual_ai_assistant.js` re-declared `aiTextToSafeHtml`, which
  `ai_assistant_manager.js` already defines on every page, and that is a syntax
  error between two classic scripts, so the file never ran on an image or video
  project with AI support or text prompting. The panel also adopted the
  toolbar the server renders but not its tooltip container, so hints,
  classifications and errors were requested and then never shown, and the
  buttons had no styles.
- **Clearing a text box and pressing Next straight away kept the old text.**
  Text and number boxes update the answer after a one-second pause, and a save
  inside that second sent the value from before the edit. Every save now
  applies pending edits first.
- **Next went back to the same item on a page opened with `?instance_id=`.**
  The page reloaded its own URL after moving, and the parameter moved the
  annotator back.
- **A go-to value that is not a number returned a server error.** `/annotate`
  and `/go_to` now answer 400.
- **Span selection listeners could be bound twice.** The span manager retried
  initialization after one second if the first run had not finished, which
  over a slow connection it had not. The two runs attached the text-selection
  handlers twice.

## [2.9.1] - Chat and Gemini Fixes

Chat works again on six endpoint types, Gemini requests go through, and
OpenRouter requests can no longer hang.

### Upgrading

OpenRouter requests now time out after 30 seconds. A model that takes longer
used to succeed eventually; set `ai_config.timeout` for it.

### Bug fixes

- **Chat failed on six endpoint types.** `huggingface`, `gemini`,
  `openrouter`, `openai_vision`, `anthropic_vision` and `ollama_vision` had no
  chat method of their own. The shared fallback called their `query()` without
  the output format it requires, so every message failed before a request was
  sent and the annotator saw "Sorry, I encountered an error." Through
  `chat_support` this hit the first three; the coding-agent proxy and the
  simulator hit all six. It dates from the chat sidebar's first commit
  (81d252bf, 2026-03-09). Each endpoint now sends the conversation natively as
  plain text, with the system prompt where the provider expects it.
- **Every Gemini request failed.** `query()` passed `generation_config=` to
  google-genai's `generate_content`, which has no such parameter. It now
  passes `config=`, with the response schema as `response_json_schema`.
- **OpenRouter requests had no timeout**, so a stalled provider held the
  request open indefinitely. They now use `ai_config.timeout`, default 30
  seconds, as the other endpoints do.

## [2.9.0] - Importers, Local Transcription and Provenance

Potato can now import projects from brat, doccano, Prodigy, CoNLL and REFI-QDA,
and transcribe and diarize audio locally. Exports record whether an image shape
was drawn by a person, proposed by a model or imported, and which room a vote
was cast in.

Most of the release is bug fixes, listed in full below. Several change what a
config or request that worked under 2.8.2 does, so read **Upgrading** before you
install.

### Thanks

- **Aldo Costa ([@Eyecatch3r](https://github.com/Eyecatch3r))** sent two pull
  requests.
  [#168](https://github.com/davidjurgens/potato/pull/168) lets Potato run below
  a path prefix behind a reverse proxy. It covers static files, client-side
  fetch and media URLs, and every standalone page: admin, dashboards, session
  review and the legacy v1 pages.
  [#171](https://github.com/davidjurgens/potato/pull/171) fixed the
  dynamic-labels example reported in #170.
- **[@ruthenian8](https://github.com/ruthenian8)** reported
  [#170](https://github.com/davidjurgens/potato/issues/170): every checkbox in
  the `check-box-dynamic-labels` example rendered blank. The report traced it to
  the item's `labels` field colliding with `Item.labels` and proposed the fix.

### Upgrading

Run `potato validate --strict` on each config before upgrading. These changes
can make a working 2.8.2 study refuse to start or behave differently:

- **Duplicate scheme names in one phase are refused**, including two different
  types sharing a name. They used to share a single stored answer. The same name
  in different phases is still allowed.
- **`min_annotators_per_instance` is now an alias for the per-item cap.** Set on
  its own, items retire at that number. Set alongside a different
  `num_annotators_per_item` or `max_annotations_per_item`, the config is
  refused. `icl_labeling.example_selection.min_annotators_per_instance` is
  unaffected.
- **`require_fully_annotated: true` is enforced.** It was ignored. Schemes with
  `required: false` stay optional.
- **`/updateinstance` returns 400 when no key in the payload can be read**, such
  as the nested `{"schema": {"label": ...}}` shape, which stored nothing and
  answered 200. Any refused save now returns an HTTP error instead of 200.
- **A phase that fails to load aborts the boot** instead of being dropped.
- **CLI defaults no longer overwrite YAML.** `persist_sessions`, `customjs`,
  `customjs_hostname`, `verbose` and `very_verbose` from the config now take
  effect, and `persist_sessions: true` without a `secret_key` is refused.
- **The codebook force-locks for every `crowdsourcing.provider` except
  `expert`**, including unrecognised names and an empty value, and
  `search.annotator_claim` is refused alongside it.
- **Also refused now:**
  - `number` with min greater than max
  - a `constant_sum` minimum that cannot be met
  - `bws` without `bws_config`
  - `category_assignment: {dynamic: true}`
  - YAML booleans in a label list (`[Yes, No]`)
  - unknown `display_options` keys
  - an `event_annotation` label missing from its span schema
  - a malformed `ai_budget.prices`
  - an unbuildable `classifier` name
  - malformed automation rules
- **`--strict` also fails on:**
  - a second annotation phase, which is never served
  - undefined phase names
  - empty data directories
  - unreadable label colours
  - unknown `failure_handling` keys
  - gold `mode: training`
  - rooms or Pocket Mode misconfiguration
  - assignment keys that do nothing
  - top-level `llm_labeling`
- **Defaults that changed:**
  - Solo mode `timeout` now uses each endpoint's own default (30, 60 or 120
    seconds) instead of 60.
  - Sessions expire after 8 idle hours (`session_timeout_minutes`).
  - The Anthropic and Gemini default models are now `claude-haiku-4-5-20251001`
    and `gemini-2.5-flash`.
  - `select`, `range_slider` and `ranking` start unanswered.
  - Markdown in `annotation_instructions` is rendered and sanitized.
- **Recorded data that changed:**
  - `min_response_time` is measured on the server.
  - Pocket Mode likert answers store `3`, not `scale_3`.
  - Span offsets are code points, not UTF-16 units. This matters only for text
    with emoji or other characters outside the Basic Multilingual Plane.
  - Agreement values for set-valued, order-valued, matrix and labelled ordinal
    schemes change and should be recomputed.
  - Registrations are stored, salted and hashed. A username that owns
    annotations but is not in the roster is refused.

### New features

**Import and export**

- Importers for brat, doccano, Prodigy, CoNLL-2003/CoNLL-U and REFI-QDA
  `.qdpx`, and a `.qdpx` exporter. Offsets follow the QDPX spec's inclusive-end
  convention, and `flatten_subcodes` handles ATLAS.ti's single subcode level.
- Provenance in exports:
  - **Rooms:** votes cast in a multiplayer room carry the room, role, initial
    vote, whether it changed after the reveal and the voter count, as `_room` in
    JSON and `{schema}._room_id` / `{schema}._room` in tabular exports.
  - **Image shapes:** each shape records whether a person drew it or a model
    proposed it (`source`, `ai_model`, `confidence`, `edited`, `carried_over`,
    `import_format`).
  - **Confidence:** COCO, MOT, OpenImages and KITTI confidence all land on one
    top-level `confidence` key.
- Span exports:
  - csv, jsonl and parquet include the covered text.
  - `spans.parquet` adds `target_field`, `title`, `span_id`, `format_coords`,
    `additional_parts` and three `kb_*` columns, and warns about any stored key
    with no column.
- `potato export --format adjudication`, and an "adopt an answer" adjudication
  control for every schema type (only radio and likert had one).

**Audio, video and transcripts**

- Local transcription and speaker diarization with faster-whisper and
  sherpa-onnx, no PyTorch and no Hugging Face token. Install
  `potato-annotation[transcribe]`, then run
  `potato transcripts <dir> --transcribe --diarize --num-speakers N -o out.json`.
  `--asr-no-vad` turns off voice-activity detection, which can drop quiet
  speech.
- Per-segment questions for audio and video: `segment_schemes` renders any
  annotation type inside a segment (it was accepted and ignored). See
  `examples/audio/segment-questions/`.

**Agreement, quality and assignment**

- Agreement over time, joined against codebook revisions, with a re-calibration
  trigger on `/admin/iaa`.
- Option order is shuffled from a fixed seed, so a reload no longer reshuffles
  it, and presentation order is recorded whether or not randomisation is on.
- A model-output review mode that includes the empty-prediction slice, so
  recall can be computed.
- Near-duplicate detection for consecutive video frames.
- `/admin/api/mace/overview` returns a `reliability` block per schema, warning
  about too few items, label skew and constant-response annotators.
- Expertise scores persist to `expertise_scores.json`, and
  `GET /admin/api/expertise` shows the counts behind each score.
- `/admin/api/overview` reports items that collected more annotations than
  their cap.
- The page an annotator sees when there is no work names the cause (no data,
  zero quota, not in a batch group, no qualifying category, or the study is
  full) and tells them what to report.

**AI and model assistance**

- Cost estimates and a spend cap (`ai_budget.cap_usd`) that refuses to start a
  run instead of stopping it halfway.
- `ai_budget.prices` sets per-model rates in the config, so a new model can be
  priced without waiting for a release.
- `pre_annotation.predictions_file` works, taking an `{id: predictions}`
  mapping or a list of records.
- `ai_support` records `final_annotation`, what the annotator actually saved,
  and `pre_annotation_seeds` records what the model answered first, so
  acceptance rates can be measured from your own data.
- `ai_support.image_key` / `item_properties.image_key` send an item's image
  together with its text to a vision endpoint, and vision requests report
  `image_attached`.
- Judge calibration results at `/judge_calibration/results`, and position-swap
  consistency on the judge eval card.
- AI rationales render markdown.

**Annotation interface**

- `card_sort` works without a mouse: pick up a card with Enter or a tap, drop it
  on a focused group, or press a number key. Moves are announced to screen
  readers.
- `tree_annotation` renders any annotation type inside a node.
- `gallery` plays video.
- `spreadsheet` accepts `header_row: true` for list-of-lists data.
- `resizable`, `max_height` and `min_height` work on every display type, and
  lengths accept `400`, `"400px"`, `"50vh"` or `calc()`.
- `text.collapsed_by_default` and `dialogue.max_height` are implemented.
- Markdown renders in `annotation_instructions`, and codebook markdown supports
  images.
- With `codebook: true`, each label's `color` and `description` seed its code,
  and the annotation-page tray shows each code's definition.
- `keyword_highlights_file` reads CSV/TSV with a header, one-per-line, JSON,
  JSONL and YAML.
- `live_coding_agent` accepts `task_field` to seed its task box from an item
  field.
- Training questions accept `category`, `categories` or the configured
  `category_key`.

**Deployment and tooling**

- Reverse-proxy and path-prefix support on every page (#168, Aldo Costa).
- `potato --version` reports the source and installed versions separately,
  names an editable install, and flags a directory shadowing the package.
- The README points Claude Code, Codex and Cursor users at the
  [potato-skill](https://github.com/davidjurgens/potato-skill) plugin.

### Bug fixes

**Saving and annotation widgets**

- A `select` preselected its first label, so walking past an item stored it,
  and `required` on a select could never fail.
- Chrome carried a select's choice over to the next item and saved it there.
- Returning to a ranked item replaced the saved ranking with the config order,
  and an unranked item showed the previous item's order.
- `constant_sum` let annotators advance under the total, and `soft_label` could
  store 160/100 when `min_per_label` blocked redistribution.
- `range_slider` drew a default range it never stored.
- An answered required slider blocked Next after navigating back.
- Survey pages did not restore slider or ranking answers, so resubmitting could
  overwrite the stored answer with the default.
- `triage` buttons sat off the card and could not be clicked.
- `tree_annotation` stored nothing under any configuration.
- `conjoint`:
  - with `profiles_field` and no `attributes`, it drew three blank cards
  - it padded short profile sets with a selectable blank option and dropped
    extra profiles
- `pairwise` showed no candidates from `items_key` or a `{left, right}` pair,
  hid the question text with `items_key`, and wrapped cells onto two lines.
- `event_annotation` arcs were invisible under `instance_display`, and every
  trigger showed as "?".
- One click satisfied `required` on `agent_scorecard`, `failure_attribution`,
  `consensus_tracking` and `context_attribution`. The message now names what is
  missing.
- `handoff_review` stored an unrated handoff as `quality: 0` on a 1–5 scale.
- `tool_contention` asked about an agent overlapping with itself.
- A save the server refused returned 200, so the page treated it as saved, and
  the session-timeout check never ran.
- `/updateinstance` kept only the schema half of a `schema:label` key, losing
  answers posted as `{"s:Yes": "on"}`.
- The error panel's Retry rebuilt the form from the original render, blanking
  saved answers.
- `option_randomization` and `dynamic_options` did nothing on multiselect.
- Option order reshuffled on every server restart.
- Fourteen schema types ignored their `layout:` block, and `layout.breakpoints`
  had no effect on `layout.groups`.
- The progress counter:
  - read N/N for every annotator after the first
  - went past its total when QC items were injected
  - showed on the post-study page
- A data column named `labels`, `span_annotations`, `metadata` or `item_data`
  rendered blank in templates (#170, reported by @ruthenian8, fixed by Aldo
  Costa in #171).
- Accessibility:
  - navbar status pills failed contrast
  - bold terms in `<legend>` text were invisible
  - the taxonomy tree's expand control was unreachable by keyboard
  - memo and codebook panels opened over the Next button

**Spans and keyword highlights**

- Span offsets were sent as UTF-16 units, so one emoji shifted every later span
  in the export.
- A selection starting at the end of an existing span, or ending at the start
  of one, was refused, so partly overlapping spans could not be made.
- A span on the last paragraph of a `document` field was not recorded, and
  restored spans came back shifted.
- With several span schemes, spans were saved under the wrong scheme.
- Spans on a `dialogue` field exported with empty text, and exported shifted
  when `show_turn_numbers` was written directly on the field. Written that way,
  `show_turn_numbers` also did nothing.
- Inline label `color` never reached the browser, and `rgb(...)` colours
  rendered as `rgbrgb(...)`.
- Coreference mentions could not be selected and chains were never saved. When
  saved, chains took the first entity type rather than the mentions' label.
- `span_link`'s Link Builder showed another task's labels.
- `pre_annotation` ignored span schemes, and a categorical prelabel carrying a
  confidence value crashed the annotation page.
- Keyword highlights never drew on `instance_display` pages, scanned only
  `text_key`, and a hex colour in the first CSV column made the row read as a
  comment.

**Agreement**

- `/admin/api/agreement` never produced a number. It also compared stored
  values instead of label names, so every categorical schema showed perfect
  agreement.
- Multiselect agreement crashed when annotators ticked different numbers of
  boxes, and one multiselect annotator counted as two.
- Set- and order-valued types reported agreement of 1.0 whatever was chosen.
- Ordinal measures ranked word labels alphabetically, so a labelled likert's
  ordinal alpha was really nominal.
- `mean_jaccard` paired annotators by position, so a skipped item misaligned
  everything after it.
- Matrix types reported `n_annotators: 0`, and `constant_sum` and `soft_label`
  scored only their first option.
- Two empty geometry answers scored as perfect agreement.
- Detection AP scored an exact match as 0.0.
- Annotators who had finished failed to load at the next boot, emptying
  agreement, the adjudication queue and the per-item cap.
- Annotations written over MCP never counted toward agreement, progress or the
  cap.

**Assignment**

- The second annotator on a two-per-item study was sent to the done page, and
  every answer they then gave was lost.
- The disagreement score was always 0, so `max_diversity` never prioritised
  anything and `adaptive_boost` never fired.
- A watched data directory gave annotators a completion code while unassigned
  items waited.
- Expertise routing compared form markers instead of labels, so every
  annotator agreed.
- Uncertainty sampling (and Badge, BALD and hybrid) threw on every run and
  scored everything 0.5, and `classifier: {name: logistic}` trained the
  fallback.
- `category_assignment: {dynamic: true}` crashed the server at boot, and
  training questions written with `categories` were uncategorized.
- New warnings for settings that do nothing: a `per_annotator_quota.default`
  that makes `max_annotations_per_user` unreachable, batch groups outside
  `assignment_strategy: batch`, and `category_based` with no training block.

**Quality control and training**

- `min_response_time` trusted the time the client reported, and could never
  fire because it measured network latency. It is now measured on the server.
- The save on Next erased `min_response_time` violations.
- Attention checks failed every answer posted as `{"schema:Label": "on"}`.
  Labels were split on the first colon, so `schema:::label` answers failed too.
- Two annotators giving opposite answers could promote an item to gold as
  "unanimous".
- Gold feedback was never shown, `accuracy.min_threshold` was checked only when
  feedback was on, and changing an answer on a gold item counted as extra gold
  items.
- QC results were lost on restart, so annotators blocked for failing QC were
  let back in.
- An undefined phase at the start of `phases.order` made every request fail.
- `failure_action: move_to_done` told a failed annotator they had completed the
  task and gave them the completion code, and training results were never saved
  after grading.
- Pocket Mode never received attention checks or gold items.

**Pocket Mode**

- A size-based likert stored `scale_3` instead of `3`, and `min_label` and
  `max_label` were not shown.
- Saves carried no response time, a refused save retried forever, and the done
  screen said "all caught up" with saves still queued.
- Text schemes were treated as desktop-only.

**Export and import**

- COCO dropped images an annotator reviewed and left empty (confirmed negative
  examples).
- `--seed-user` imports skipped items with no annotations.
- CV exports:
  - ignored `source_field`, putting every box at the origin
  - wrote `width: 0, height: 0` in COCO and ten other exporters
  - exported EXIF-rotated JPEGs on swapped axes
  - did not report items missing from the output
- Parquet:
  - exported a labelled likert as an all-null column
  - exported textboxes as a Python dict
  - aborted on a mixed numeric/text scale
  - ignored `export_include_phase_data`
  - dropped any column missing from the first row
- `quotation_report` exported empty columns, codebook export missed codes added
  at `/codebook`, and arena preferences could not become DPO pairs.
- `coding_eval` said "Export successful!" over an empty directory.
- The adjudication exporter could read another project's decisions.
- The transcription cache ignored model settings and duplicated items, and an
  empty diarization options dict skipped diarization.

**AI and model assistance**

- A truncated reply was reported only for OpenAI. On other providers a cut-off
  structured reply showed "No rationales available", the same as a dead
  endpoint.
- A vision request with no image attached ran as text-only without a warning.
- A model's refusal or negation highlighted the "No" label as a suggestion, and
  suggestions that match no label are now dropped.
- AI suggestions were about the wrong item under every assignment strategy
  except `fixed_order`.
- The LLM judge was sent the item id instead of its text.
- Model hint text was inserted unescaped in text, image and video studies.
- The spend table charged a whole projected batch when a run stopped early,
  blocking later runs.
- The price table was checked against vendor pages on 2026-09-05. Opus was
  priced three times too high, `gpt-4.1-nano` at twenty times its rate, and the
  Anthropic and Gemini default models were unpriced, so `cap_usd` did not bind
  them. A price taken from a model-family row now says so.
- `image_key` pointing at local media was refused, and vision prompts left out
  the item's text.
- A judge eval card with no data said "trustworthy".
- An agent reply with a string `action` killed the agent thread, and
  `live_agent` did not seed its starting URL from the item.

**Security and access**

- `crowdsourcing.provider`, the documented spelling, did not lock the codebook,
  so crowd workers could edit it. An empty provider value also left it open.
  `login.type: url_direct` with an open codebook now warns.
- Sign-ups were never saved under the default in-memory config, so after a
  restart anyone could claim an existing username with any password.
- `document` display fields ran raw HTML from the corpus.
- `show_annotator_names: false` still sent annotator emails through the API.
- A room's export revealed other members' votes during the blind phase.
- `annotation_instructions` are sanitized, and `javascript:` URLs in codebook
  images are refused.
- A request with a wrong admin key created the admin key file.
- A task name containing `/` crashed the boot and could write outside the
  generated-templates directory.

**Images and media**

- The image canvas was about 104px taller than its box, so the bottom of every
  image was unreachable, and Fit always returned 100%.
- With `tools: [brush]` alone, the brush could not paint.
- `source_field` did nothing without an `instance_display` block for audio,
  image and video.
- `image_annotation` did not find images in `instance_display` fields.
- `gui_trajectory` with `coord_space: pixels` drew no marker.
- `audio_dialogue` played the wrong recording when each utterance had its own
  file. The shared player is now removed in that case.
- `.m4a` and `.flac` were served with types Chrome rejects, and `Accept-Ranges`
  was never sent.
- `gallery` entries written as `{url: ...}` and `web_agent_trace` screenshots
  ignored `media_directory`.
- Waveforms for `/media/...` URLs always fell back to browser decoding.

**Displays**

- Dicts and lists showed as Python syntax in 17 of 24 displays.
- Trace displays dropped `{role, content}` turns and showed tool output as the
  final answer. `process_reward` printed raw JSON, and `cot_segmentation`
  labelled every step "Observation".
- `spreadsheet` dropped columns that first appear after row 0.
- `max_height: "220px"` became `220pxpx`.
- The default PDF display showed an empty box, and Plotly loaded from a CDN, so
  the admin plot failed on an air-gapped install. It is now vendored.
- A null or numeric text crashed the boot.
- The display registry hid 44 working options, including `speaker_key`.
- `failure_attribution` and `agent_scorecard` left out agents seen in the data.
- Demographics instruments used a nonexistent type and could not load.

**Data loading and ingestion**

- The directory watcher could not parse pretty-printed JSON arrays, and search
  was not reindexed after startup.
- A `data_directory` with nothing loadable booted an empty study without a
  warning.
- Automation rules never ran on the loaded corpus.
- `trace_ingestion` rejected its documented `X-API-Key`.

**Codebook**

- "Paste markdown" threw away the pasted text when the target section was
  empty.
- The tray showed stale definitions and collapsed the code list to one row.
- `/admin/catalog/api/search` ignored `k`.

**Adjudication**

- `require_notes_on_override` and `require_confidence` were never enforced, and
  confidence defaulted to "medium".
- Composite schemes all scored 1.0 agreement and never reached the adjudicator.
- Types other than radio and likert showed "Form not available".

**Multiplayer rooms**

- `rooms.enabled: true` with no votable scheme validated, then `/rooms` returned
  404.

**Solo mode**

- `timeout: 60` could not be set; writing it gave the endpoint's default.
- An empty low-confidence pool absorbed `low_confidence_weight` without a
  warning.
- `InstanceSelector.configure()` turned off the `llm_predicted` pool.

**Reverse proxy**

- The login form, `/done`, `/logout`, `/pocket`, the password-reset forms and
  admin redirects ignored the path prefix, and media `poster`, `srcset` and
  `track` URLs were not prefixed.

**MCP and coding agent**

- `submit_annotation` stored the widget type as the label and wrote into
  consent pages.
- The audit log recorded attempts rather than outcomes, and live tools
  published no argument schemas.
- Coding-agent containers leaked on Stop and on SIGTERM, and the SIGTERM
  handler never installed on a live server.
- `agent_proxy` with `enabled: false` still loaded, and it ignored `ai_config`.

**Config validation**

- `labels: [Yes, No]`, which YAML reads as booleans, passed `--strict`.
- A phase that failed to build was dropped without a message, and `validate`
  did not check instrument questions.
- An empty `annotation_schemes:` crashed validation.
- `ui_language: en` failed `--strict`, and `potato validate` now runs the
  server's path checks.
- The packaged config schema lagged behind the one in `docs/`.

**[Full Release Notes →](docs/releasenotes/v2.9.0.md)**

---

## [2.8.2] - The Fixes 2.8.1 Said It Had

**2.8.1 did not contain the SSRF or debug-mode fixes its release notes and
advisories claimed.** The code was never written; the release notes were. If you
upgraded to 2.8.1 for either of those, you were not protected. Upgrade to 2.8.2.

The RCE fix (the agent sandbox), the admin config read authorization and the
trace-ingestion webhook fix were real in 2.8.1 and are unchanged here.

**Unauthenticated SSRF, now actually fixed.** `/api/audio/proxy`,
`/api/waveform/generate`, `/api/video/waveform/generate` and
`/api/video/metadata` require a login, and every caller-supplied URL goes
through one shared guard. It resolves the host and refuses loopback, private,
link-local, reserved, multicast, CGNAT and cloud-metadata addresses; rejects a
host that resolves to any blocked address, since a mixed answer is a rebinding
primitive; connects to the address it validated rather than re-resolving the
name; re-validates every redirect hop; and caps the response. It fails closed on
a name that will not resolve, where the old `web_proxy` validator allowed it.
The proxy no longer sends `Access-Control-Allow-Origin: *`. Local paths handed
to waveform generation resolve inside `task_dir`, closing a file-existence
oracle.

**Debug mode, now actually hardened.** The admin bypass applies only on a
loopback bind. The server refuses to start with `debug: true` on any other
interface unless `POTATO_ALLOW_REMOTE_DEBUG=1` is set. The Werkzeug interactive
debugger is never served off loopback, override or not. The admin dashboard
echoes the admin key only to a caller who already presented it, so the debug
bypass and RBAC roles no longer disclose it. Local debugging on 127.0.0.1 is
unchanged.

Also: `potato preview` binds its throwaway server to loopback.

**[Full Release Notes →](docs/releasenotes/v2.8.2.md)**

---

## [2.8.1] - Security Fixes (partly incomplete — see 2.8.2)

> **Correction:** this entry claimed five fixes. Two of them, the SSRF and the
> debug-mode hardening, were not in the release. They shipped in 2.8.2. The
> descriptions below are left as published, with this note, rather than
> rewritten.

Closes three security issues, and claimed two more that were not included.

**Unauthenticated SSRF** through `/api/audio/proxy` and the two waveform
endpoints, which fetched any URL a caller supplied and, for the proxy, returned
the body, reaching cloud metadata services, internal APIs and anything else on
the host's network. All four now require a login and share one URL guard that
blocks private and metadata addresses, pins the resolved address against DNS
rebinding, and re-checks redirects.

**Unauthenticated remote code execution** through the live coding agent, whose
routes had no login check at all and whose replay endpoint executed
caller-supplied tool calls with `shell=True` on the host. The sandbox meant to
contain this did not: `sandbox_mode: docker` was never implemented and silently
fell back to no isolation, and the default `worktree` is a git worktree on the
same host as the same user. Rebuilt as a ladder that never falls back and checks at startup:
`container` (Docker or Podman, no network, read-only root, unprivileged,
optionally gVisor or Kata), `bubblewrap`, or `trusted` with an explicit
acknowledgement.

**Admin config readable without the admin key**: the endpoint authorized its
write branch and not its read branch. Found because the test harness had been
exercising the debug bypass rather than the real check.

**Trace-ingestion webhook accepted everyone** when no `api_key` was configured,
so enabling the feature disabled its authentication. Now fails closed.

**Debug mode on a reachable interface** no longer grants admin, no longer puts
the admin key in the rendered HTML, and no longer hands Flask's interactive
debugger to a non-loopback bind.

**Breaking:** `sandbox_mode` defaults to `container`, and `worktree`/`direct`
map to `trusted` and require `acknowledge_untrusted_code_execution: true`.
Existing live-coding-agent configs will not start until they choose a rung.
`output_annotation_format` is deprecated in favour of `export_annotation_format`
and folds automatically.

Also: server-side sidebar gating, quality-control items no longer eating an
annotator's quota, a required-but-hidden scheme no longer blocking saving,
sixteen schema types landing in their configured `layout.groups` group, an MCP
server and browser-backed `potato preview --screenshot`, and
`potato deploy local` / `potato deploy share`.

**[Full Release Notes →](docs/releasenotes/v2.8.1.md)**

---

## [2.8.0] - Vision, and the Statistics to Check It

Potato's image, video, 3D, embodied and world-model surfaces were rebuilt from a
thin layer over the text machinery into the main body of the tool, and the
agreement statistics were extended to cover them. **Chance-corrected agreement
over geometry and over time** — detection, localization, classification, a
geometry scale reported as σ and a KS test, STAPLE for latent mask consensus, and
temporal boundary agreement reported as a tolerance sweep rather than at one
threshold. This also fixed adjudication, which compared annotation *keys* and so
scored every image pair at 1.0: two annotators who agreed on nothing looked
unanimous and no image was ever routed for review.

Everything under it: five new geometry primitives (`polyline`, `keypoint_set`,
`ellipse`, `cuboid_2d`, `tubelet`) plus instance-keyed masks; **interactive
segmentation in the browser** with vendored ONNX Runtime Web, so a default
install segments with no GPU and no network; **text prompting** via Grounding
DINO and **SAM 2 video mask propagation** (measured at 0.974–0.979 IoU per frame
with no decay), behind a single model zoo; **deep zoom** with masks at the
source's full resolution; 15 importers and 29 exporters with a format matrix a
test keeps honest; media ingest for TIFF, HEIC, RAW, HEVC and ProRes; **point
clouds** with octree LOD, calibration and 2D projection, **depth maps**, and
orthographic slab views; **embodied episodes** (LeRobot v2, RLDS,
HDF5); **world-model rollout evaluation** with break-point agreement; and **VLM
grounding, pointing and region captioning**.

Also: threaded conversation rendering and ConvoKit import/export both ways;
opt-in keystroke logging with composed/transcribed/pasted detection; live
database ingestion ([#166](https://github.com/davidjurgens/potato/issues/166));
machine-checkable config and OpenAPI specs generated from the registries, with CI
failing on drift; the admin Instances tab de-quadratified (15.1 s → 23 ms at
2,000 items) with two columns that had never worked; every frontend asset
vendored, closing an offline break and a per-page-load IP leak to Google; and the
packaging fix from [#164](https://github.com/davidjurgens/potato/pull/164) —
**wheels from 2.7.1 and earlier were missing every template in a subdirectory**,
breaking solo mode, the admin pages, judge calibration and the corpus map for
anyone who installed from PyPI.

Single-select schemas no longer persist every value clicked
([#167](https://github.com/davidjurgens/potato/issues/167)), with
`potato repair-annotations` for already-corrupted state.

**Breaking:** image annotation keyboard shortcuts now follow V7 conventions by
default. Set `keybinding_profile: legacy` to keep the old table.

**[Full Release Notes →](docs/releasenotes/v2.8.0.md)**

---

## [2.7.1] - Transcripts In, Without the Reformatting

Direct support for speech that was transcribed elsewhere: **21 transcript and subtitle input formats** (up from 6) spanning ASR output (Whisper, WhisperX, whisper.cpp, Whisper TSV, AWS Transcribe, Deepgram, AssemblyAI, Rev.ai, SPoRC), subtitles and captions (SRT, WebVTT, ASS/SSA, TTML/DFXP, YouTube json3 and srv1/srv2/srv3), and forced-alignment import (CTM, Praat TextGrid, ELAN EAF — so tiered annotations now round-trip). Transcripts can live in **sidecar files** beside the media instead of being inlined into the data file, a `potato transcripts` CLI converts a directory of ASR output into a ready-to-annotate data file, and all four transcript-consuming schemas share one format vocabulary. Word-level timings and confidence are preserved. New reference and guide pages, plus a six-format example. Pure stdlib, no new dependencies, fully back-compatible. Also fixes a `user_input()` ReferenceError thrown by the instance-jump input in the base templates.

**[Full Release Notes →](docs/releasenotes/v2.7.1.md)**

---

## [2.7.0] - Seven New Ways to Annotate

The largest release yet: seven opt-in features built around the idea that an annotation tool should measure *how* judgments come to be, not just collect them — Psychometrics (live IRT, labels with error bars), Multiplayer Rooms (instrumented norming sessions), Boundary Lab (counterfactual probes), Truth Serum (surprisingly-popular scoring), Think-Aloud Mode (local voice rationales), Paper Mode (methods section from your data), and Pocket Mode (phone annotation). None requires an LLM. Plus cross-document event annotation, turn-level annotation, CoT process-reward labeling, PDF cross-page linking, a living-document codebook, RBAC roles with per-cohort schemas, localized dashboards in 10 languages, an ACL 2026 demo-track paper with `CITATION.cff`, and a much lighter core install (lazy AI SDK imports).

**[Full Release Notes →](docs/releasenotes/v2.7.0.md)**

---

## [2.6.2] - Agent-Evaluation Differentiation + Multi-Agent & Multimodal Annotation

13 new annotation schemas pushing Potato beyond parity with LangSmith/LabelBox: multi-agent team annotation (clickable `agent_interaction_graph`, `failure_attribution`, `handoff_review`, `agent_scorecard`, `tool_contention`, `emergent_behavior`) and multimodal-agent annotation (`gui_trajectory`, `voice_interaction`, `temporal_grounding`, `speech_transcript`, `multimodal_reasoning`, `tool_call_review`, `table_grid`). Plus new evaluators (`rubric_dag`, `rag_triad`, `agent_as_judge`), judge bias/robustness eval cards (verbosity, position-swap, ECE), statistical rigor (bootstrap CIs, Wilson intervals, paired significance, Dawid–Skene), an Elo/Bradley–Terry model arena with DPO export, failure-mode discovery, LLM-cheating detection, perspectivist export, and reward/active-sampling/metric-induction/prompt-optimization. Fixes to `agent_interaction_graph`, `trajectory_eval`, and `table_grid`, plus an example-integrity guard. 53 schema types total.

**[Full Release Notes →](docs/releasenotes/v2.6.2.md)**

---

## [2.6.1] - Agentic Evaluation Suite (G1–G10)

A full agent-evaluation loop on top of the annotation core: programmatic evaluators (`potato.evaluators`), versioned datasets & experiments, the `potato_trace` tracing SDK with OpenTelemetry export, an automation-rules engine, a CI pytest plugin with threshold gating, automated judge calibration with span/free-text judging, `eval_trace` span annotation, semantic curation (Catalog), and a provider-agnostic multi-model arena — capture → automate → curate → evaluate → gate → calibrate.

**[Full Release Notes →](docs/releasenotes/v2.6.1.md)**

---

## [2.6.0] - QDA Mode, LLM-as-Judge Calibration & Trajectory Editing

Interactive Qualitative Data Analysis (QDA) Mode (universal persistence, memos, FTS5 search, a living codebook with cases, in-vivo coding, and retroactive curation), an LLM-as-judge calibration/alignment workflow with a signal-based triage queue, `trajectory_edit`/`trajectory_correction` schemas for SFT/DPO data, the `eval_trace` three-pane display, relicensing to GPL-3.0-or-later, and a large robustness wave (F-022–F-051).

**[Full Release Notes →](docs/releasenotes/v2.6.0.md)**

---

## [2.5.0] - Qualitative-Coding Wave

Cohen's and Fleiss' kappa for inter-annotator agreement, `codebook` and `quotation_report` exporters, and code co-occurrence/crosstab admin analytics endpoints.

**[Full Release Notes →](docs/releasenotes/v2.5.0.md)**

---

## [2.4.5] - Validated Refinement, Config Validator & Stability

Pluggable validated-refinement framework for solo-mode guideline improvement, a config-validator CLI, a path-traversal security fix (GHSA-q9m2-fhv9-3jcf), documentation reorganization, and a broad set of navigation, Prolific, and solo-mode fixes.

**[Full Release Notes →](docs/releasenotes/v2.4.5.md)**

---

## [2.4.4] - Span Annotation Fixes & UX Improvements

Fixed span overlay misalignment (overlays rendering on wrong line of text), text-node offset pollution from overlay labels, and fragile indexOf-based positioning. Added auto-selection of single span labels on page load.

**[Full Release Notes →](docs/releasenotes/v2.4.4.md)**

---

## [2.4.3] - Coding Agent Annotation, Localization & Stability

Live coding agent mode with 3 backends and checkpoint/rollback, 15 new schema types, expanded localization with RTL support, modernized CLI, auto-export, and numerous bug fixes.

**[Full Release Notes →](docs/releasenotes/v2.4.3.md)**

---

## [2.4.1] - Bug Fixes

Fixed non-annotation pages stuck on loading screen and solo mode stability improvements.

**[Full Release Notes →](docs/releasenotes/v2.4.1.md)**

---

## [2.4.0] - Agent Evaluation, AI-Assisted Annotation & Enterprise Integration

Web agent annotation, live agent evaluation, LLM chat sidebar, advanced active learning, webhook system, HuggingFace ecosystem integration, LangChain callback handler, SSO/OAuth, and 200+ new tests.

**[Full Release Notes →](docs/releasenotes/v2.4.0.md)**

---

## [2.3.0] - Solo Mode, Agent Workflows & Security Hardening

Solo annotation mode with cascaded confidence escalation, agentic workflow evaluation with 6 trace converters, SSO/OAuth authentication, Parquet export, 12 critical security fixes, and 85 solo mode tests.

**[Full Release Notes →](docs/releasenotes/v2.3.0.md)**

---

## [2.2.0] - Comprehensive Annotation & Export Platform

9 new annotation schemas, MACE annotator competence estimation, diversity ordering, pluggable export system with 8 formats, extended remote data sources, standard survey instruments, and annotation navigation.

**[Full Release Notes →](docs/releasenotes/v2.2.0.md)**

---

## [2.1.0] - Adjudication & Multi-Modal Annotation

Complete adjudication workflow, flexible instance display system, multi-field span annotation, span linking, and visual AI support.

**[Full Release Notes →](docs/releasenotes/v2.1.0.md)**

---

## [2.0.0] - Backend Refactor

Major architectural overhaul with new state management, AI support, active learning, training phase, database backend, enhanced admin dashboard, and security enhancements.

**[Full Release Notes →](docs/releasenotes/v2.0.0.md)**

---

## Migration

See [MIGRATION.md](MIGRATION.md) for detailed instructions on upgrading from v1.x to v2.0.0.

## New Features Guide

See the [v2.0.0 release notes](docs/releasenotes/v2.0.0.md) for detailed documentation on new features.

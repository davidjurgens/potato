# Changelog

All notable changes to the Potato annotation platform are documented in this file.

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
orthographic slab views; **embodied episodes** (LeRobot v2, RLDS, HDF5, ROS
bags); **world-model rollout evaluation** with break-point agreement; and **VLM
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

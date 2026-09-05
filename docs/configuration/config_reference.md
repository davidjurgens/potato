# Configuration Reference

> **Auto-generated** from the codebase by `scripts/generate_config_reference.py`.
> Do not edit manually — regenerate with: `python scripts/generate_config_reference.py`

This is a complete reference of all recognized configuration keys in Potato.
For a tutorial-style guide, see [Configuration Guide](configuration.md).

## Table of Contents

- [Core / Required](#core-required)
- [Data Sources](#data-sources)
- [Annotation](#annotation)
- [Authentication / Login](#authentication-login)
- [Server](#server)
- [Quality Control](#quality-control)
- [AI Support](#ai-support)
- [Qualitative Coding (QDA)](#qualitative-coding-qda)
- [Advanced Features](#advanced-features)
- [UI & Layout](#ui-layout)
- [Content](#content)
- [Annotation Features](#annotation-features)
- [Media](#media)
- [External Integrations](#external-integrations)
- [Publishing & Export](#publishing-export)
- [Debug / Logging](#debug-logging)
- [Agent](#agent)
- [Agent Evaluation Suite](#agent-evaluation-suite)
- [Workflow & Phases](#workflow-phases)
- [Assignment & Sessions](#assignment-sessions)
- [Annotation Types](#annotation-types)
- [Label Structure](#label-structure)

## Core / Required

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `annotation_task_description` |  | string |  | Longer task description; falls back to task_description when absent |  |
| `annotation_task_name` | Yes | string |  | Display name for the task, shown in the browser title and the header |  |
| `item_properties` | Yes | object |  | Maps the fields of your data file onto the roles Potato needs: which field is the identifier and which holds the text to annotate | `category_key`, `id_key`, `image_key`, `kwargs`, `text_key` |
| `output_annotation_dir` | Yes | string |  | Directory annotations, user state and exports are written to |  |
| `output_annotation_format` |  | string | `""` | Deprecated, and read as `export_annotation_format` at load time with a warning (`json` becomes `jsonl`, since no exporter is called `json`). It will stop being read in a later release, so rename it. Annotations are stored as `<output_annotation_dir>/<user>/user_state.json` whatever it says; this key never changed that |  |
| `task_description` |  | string |  | Short description of the task, shown to annotators |  |
| `task_dir` | Yes | string |  | Root directory every other relative path in this config resolves against, and the boundary path validation refuses to escape |  |

## Data Sources

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `data_cache` |  | object |  | Cache for remote data sources | `enabled`, `max_size_mb`, `ttl_seconds` |
| `data_directory` |  | string |  | Load every data file in a directory instead of listing them |  |
| `data_directory_encoding` |  | string | `utf-8` | Text encoding used to read files under data_directory |  |
| `data_files` | Yes | array |  | Input data files. JSON, JSONL, CSV and TSV are all accepted; JSON may be either an array of objects or one object per line |  |
| `data_sources` |  | array |  | Remote or live inputs (url, s3, huggingface, google_sheets, database, google_drive, dropbox, file), optionally polled for new rows |  |
| `item_store` |  | object |  | Where item payloads live. `backend` is memory (the default) or paged; paged writes to `path` -- .item_cache.sqlite under the output directory when unset -- and keeps `cache_size` items resident. An unknown backend warns and falls back to memory rather than refusing to start | `backend`, `cache_size`, `path` |
| `media_directory` |  | string | `media` | Directory served at /media/, so data files can reference local images, audio and video by relative path instead of an external URL |  |
| `partial_loading` |  | object |  | Load items lazily rather than reading every file at startup |  |
| `watch_data_directory` |  | boolean | `False` | Rescan data_directory while the server runs and pick up new files |  |
| `watch_poll_interval` |  | number | `5.0` | Seconds between rescans when watch_data_directory is on |  |

## Annotation

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `annotation_schemes` |  | array |  | The questions annotators answer. Each entry needs an annotation_type from the schema registry plus a name and description |  |
| `phases` |  | array or object |  | Per-phase configuration (consent, instructions, training, annotation, post-study). Either a list of phase objects or a mapping with an `order` key. Phase-level annotation_schemes replace the top-level list rather than adding to it |  |
| `pre_annotation` |  | object |  | Seed annotations to show as a starting point for each item | `agreement_metrics`, `allow_modification`, `enabled`, `field`, `highlight_low_confidence`, `predictions_file`, `show_confidence` |
| `surveyflow` |  | object |  | Survey pages shown before and after annotation |  |
| `training` |  | object |  | Qualification phase annotators must pass before real items | `allow_retry`, `annotation_schemes`, `data_file`, `enabled`, `failure_action`, `feedback`, `passing_criteria` |

## Authentication / Login

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `admin_api_key` |  | string |  | Shared key for the admin API, sent as the X-API-Key header. Generated and persisted to {task_dir}/admin_api_key.txt when unset |  |
| `authentication` |  | object |  | Identity provider settings for SSO and database-backed accounts | `allow_local_login`, `allowed_domain`, `allowed_domains`, `allowed_org`, `auto_register`, `database_url`, `method`, `providers`, `user_config_path`, `user_identity_field` |
| `login` |  | object |  | Login mode. type: password, url_direct, or none | `type`, `url_argument` |
| `rbac` |  | object |  | Role assignments and SSO role mapping | `enabled`, `roles`, `sso_role_mapping`, `user_role_assignments` |
| `require_no_password` |  | boolean |  | Accept a username with no password |  |
| `require_password` |  | boolean |  | Require a password at login |  |
| `secret_key` |  | string |  | Flask session signing key. Set this for any deployment that must keep sessions valid across restarts |  |
| `user_config` |  | object |  | Who may log in | `allow_all_users`, `users` |
| `user_roles` |  | object |  | Per-user quota and role overrides |  |

## Server

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `base_html_template` |  | string |  | Base template every page extends |  |
| `credentials` |  | object |  | How credentials in the config are resolved before use | `env_file`, `env_substitution` |
| `customjs` |  | boolean |  | Enable custom JavaScript injection |  |
| `customjs_hostname` |  | string |  | Hostname custom JavaScript is served from |  |
| `host` |  | string | `localhost` | Interface to bind. 0.0.0.0 exposes the server beyond localhost |  |
| `persist_sessions` |  | boolean | `False` | Keep annotator sessions across a server restart |  |
| `port` |  | integer | `8000` | Port to listen on. The -p flag overrides this |  |
| `server` |  | object |  | Nested port/host/debug block, an alternative to the top-level keys | `debug`, `host`, `port` |
| `session_lifetime_days` |  | integer | `2` | Days before a persisted session expires |  |
| `session_timeout_minutes` |  | integer | `480` | How long a signed-in session may sit idle before the server clears it. The clock restarts on every request, so it bounds inactivity, not the length of a shift |  |
| `site_dir` |  | string |  | Directory holding the HTML templates for this task |  |
| `site_file` |  | string |  | Specific template file to render the annotation page with |  |

## Quality Control

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `adjudication` |  | object |  | Resolve disagreements through an adjudication queue | `adjudicator_users`, `agreement_threshold`, `enabled`, `error_taxonomy`, `fast_decision_warning_ms`, `min_annotations`, `output_subdir`, `require_confidence`, `require_notes_on_override`, `show_agreement_scores`, `show_all_items`, `show_annotator_names`, `show_timing_data`, `similarity` |
| `agreement_metrics` |  | object |  | Which inter-annotator agreement measures the admin pages compute | `enabled`, `min_overlap`, `refresh_interval` |
| `attention_checks` |  | object |  | Insert items with a known answer to detect inattentive annotators | `enabled`, `failure_handling`, `frequency`, `geometry_iou_tolerance`, `items_file`, `min_response_time`, `probability` |
| `calibration` |  | object |  | Agreement drift tracking and the re-calibration prompt on /admin/iaa. Agreement is scored per time window so a fall in recent work is visible, instead of averaging into one whole-project number | `drop_threshold`, `enabled`, `window_by`, `windows` |
| `gold_standards` |  | object |  | Items with known labels, used to score annotators | `accuracy`, `auto_promote`, `enabled`, `feedback`, `frequency`, `geometry_iou_tolerance`, `items_file`, `mode` |
| `gold_standards_file` |  | string |  | Gold items file, the flat alternative to the gold_standards block |  |
| `quality_control` |  | object |  | Aggregate quality thresholds and actions |  |
| `require_fully_annotated` |  | boolean |  | Refuse to advance until every scheme on the page has an answer |  |

## AI Support

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `active_learning` |  | object |  | Order items by model uncertainty | `annotation_routing`, `bald_params`, `calibrate_probabilities`, `classifier`, `classifier_params`, `cold_start_strategy`, `confidence_method`, `database`, `enabled`, `hybrid_weights`, `icl_ensemble_params`, `llm`, `max_instances_to_reorder`, `min_annotations_per_instance`, `min_instances_for_training`, `model_persistence`, `query_strategy`, `random_sample_percent`, `resolution_strategy`, `routing_thresholds`, `schema_names`, `update_frequency`, `use_icl_ensemble`, `vectorizer`, `vectorizer_params` |
| `ai_budget` |  | object |  | Cost estimate and spend cap for AI actions. The complaint about commercial platforms is not the price but the surprise -- credits consumed by auto-labelling and discovered at export time | `cap_usd` |
| `ai_support` |  | object |  | Model-backed label suggestions shown alongside each item | `ai_config`, `ai_config_file`, `cache_config`, `enabled`, `endpoint_type`, `features`, `image_key`, `option_highlighting` |
| `chat_support` |  | object |  | In-task chat with a model | `ai_config`, `enabled`, `endpoint_type`, `system_prompt`, `ui` |
| `icl_labeling` |  | object |  | In-context-learning labeler that builds few-shot prompts from high-confidence annotations already collected. Configured in four nested blocks, not as flat keys | `enabled`, `example_selection`, `llm_labeling`, `persistence`, `verification` |

## Qualitative Coding (QDA)

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `annotation_ui` |  | object |  | Annotation-surface toggles that are not gated on QDA mode | `memos`, `visibility` |
| `cases` |  | object |  | Group instances into units of analysis -- a participant, an interview -- so codes can be counted per case rather than per item | `attributes`, `auto_detect`, `enabled`, `key` |
| `codebook` |  | object |  | The shared label set a scheme opts into with a scheme-level `codebook: true`, edited from /codebook and stored per project | `distiller`, `enabled`, `mode` |
| `codebook_invivo_key` |  | string | `i` | Key that opens the in-vivo 'code from selection' composer while text is selected in a codebook-backed span scheme. Only the first character is used |  |
| `codebook_mode` |  | string |  | Top-level shorthand for codebook.mode, and the value that wins when both are set. Unset it resolves to open under qda_mode/solo_mode and fixed otherwise; a crowdsourcing backend force-locks fixed |  |
| `qda_mode` |  | object |  | Qualitative data analysis mode. Turning it on moves the defaults for memos, the codebook and case grouping together, rather than each being switched on separately | `codebook`, `enabled`, `memos` |
| `search` |  | object |  | Full-text search over loaded items, backed by SQLite FTS5. Admin search is read-only and always available; annotator search-and-claim is a separate opt-in | `annotator_claim`, `backend`, `enabled`, `max_instances` |

## Advanced Features

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `analytics` |  | object |  | Cost and latency analytics over ingested traces: optional per-model pricing, and the thresholds that raise a regression alert | `pricing`, `thresholds` |
| `annotation_telemetry` |  | object |  | The drawing-process analogue of keystroke_logging: content-blind telemetry on geometry schemas -- when someone draws, zooms, revises and accepts AI suggestions, never what or where -- and the rubber-stamping screening built on it | `detection`, `disclose_to_annotators`, `disclosure_text`, `enabled`, `exclude_schemas`, `fidelity`, `flush_interval_ms`, `idle_ms`, `include_schemas`, `store_events` |
| `annotator_dashboard` |  | boolean or object | `False` | Read-only progress page at /progress. Shows project totals and the requesting annotator's own stats, never another annotator's identity. A bare `true` is accepted as shorthand for `{enabled: true}` | `enabled`, `show_active_annotators`, `show_personal_progress`, `show_project_progress` |
| `boundary_probing` |  | object |  | Boundary Lab. After a label is chosen, shows counterfactual edits of the item and asks whether they flip it -- which maps the decision boundary and exports as a contrast set | `ai_support`, `debounce_ms`, `enabled`, `include_invariance`, `precomputed_key`, `probes_per_item`, `rationale_on_flip`, `schema`, `sources` |
| `bws_config` |  | object |  | Best-worst scaling. Builds the tuples annotators compare and scores the results into a ranking. Its presence is what enables BWS | `min_item_appearances`, `num_tuples`, `scoring`, `seed`, `tuple_size` |
| `category_assignment` |  | object |  | Route items to annotators by the item's category, optionally gated on a qualification the annotator earned in training | `category_key`, `dynamic`, `enabled`, `fallback`, `qualification` |
| `corpus_map` |  | object |  | Multi-document corpus map: embed, cluster, project with UMAP and build a KNN graph, then give annotators a 2D navigation surface at /corpus. The heavy compute is lazy and never runs at boot | `build_on_start`, `cluster_labeling`, `clustering`, `embedding_model`, `enabled`, `knn`, `sample_size`, `umap` |
| `diversity_ordering` |  | object |  | Embed and cluster the corpus, then serve items round-robin across clusters so an annotator sees the range of the data early | `auto_clusters`, `batch_size`, `cache_dir`, `enabled`, `items_per_cluster`, `model_name`, `num_clusters`, `prefill_count`, `preserve_visited`, `recluster_threshold`, `trigger_ai_prefetch` |
| `embedding_visualization` |  | object |  | 2D embedding scatter of the corpus on the admin dashboard, coloured by label | `embedding_model`, `enabled`, `image_embedding_model`, `include_all_annotated`, `label_source`, `sample_size`, `umap` |
| `embeddings` |  | object |  | The project-wide embedder shared by the corpus map, diversity ordering and duplicate detection. `backend` (auto by default), plus `model`, `source_field`, `cache_dir`, `media_root`; anything else is passed through to the backend. A custom backend needs `entrypoint` ('module.path:callable') or `endpoint` (an HTTP URL) |  |
| `event_template` |  | object |  | Cross-document event registry: admin-defined slots that annotators fill with evidence drawn from many documents | `allow_annotator_create`, `enabled`, `name`, `seed_events`, `slots` |
| `ibws_config` |  | object |  | Iterative best-worst scaling: re-generates tuples each round, concentrating comparisons where the ranking is still uncertain | `max_rounds`, `scoring_method`, `seed`, `tuple_size`, `tuples_per_item_per_round` |
| `keystroke_logging` |  | object |  | Content-blind typing dynamics on free-text fields -- when someone pauses, revises or pastes, never which keys -- and the composed/transcribed/pasted detection built on them | `classify_paste_source`, `detection`, `disclose_to_annotators`, `disclosure_text`, `enabled`, `exclude_schemas`, `fidelity`, `flush_interval_ms`, `idle_session_ms`, `include_schemas`, `pause_thresholds_ms`, `store_events` |
| `mace` |  | object |  | MACE competence estimation: infers per-annotator reliability and a predicted label per item from the disagreement pattern alone | `enabled`, `min_annotations_per_item`, `min_items`, `num_iters`, `num_restarts`, `trigger_every_n` |
| `pocket` |  | object |  | Pocket Mode: the phone-sized annotation surface at /pocket, served as a PWA with an offline queue | `auto_redirect`, `batch_size`, `enabled` |
| `psychometrics` |  | object |  | Live IRT. Fits item difficulty and annotator ability as labels arrive, so labels carry error bars and confident items can stop early | `confidence_threshold`, `cost_per_judgment`, `discrimination_flag_threshold`, `enabled`, `min_annotators_per_item`, `min_observations`, `refit_interval`, `schema` |
| `rooms` |  | object |  | Multiplayer rooms at /rooms: live norming sessions, adjudication huddles and shadowing over a shared event log | `enabled`, `max_members`, `persist_votes`, `poll_interval_ms`, `schema`, `who_can_create` |
| `thinkaloud` |  | object |  | Think-aloud mode: local speech-to-text over spoken rationales, plus rule-based detection of spoken label phrases | `chunk_seconds`, `enabled`, `fillers`, `language`, `model`, `require_spoken_label`, `schema`, `stems`, `stt` |
| `truth_serum` |  | object |  | Surprisingly-popular scoring. Each annotator also predicts how many others will pick the same label, and an answer that beats its own predicted popularity wins over the majority | `enabled`, `min_annotators`, `question`, `schema` |

## UI & Layout

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `base_css` |  | string |  | Extra stylesheet to load |  |
| `format_handling` |  | object |  | How rich text and markup in item fields are rendered | `default_format`, `enabled`, `pdf`, `spreadsheet` |
| `hide_navbar` |  | boolean |  | Hide the top navigation bar |  |
| `horizontal_key_bindings` |  | boolean |  | Lay keyboard shortcut hints out horizontally |  |
| `instance_display` |  | object |  | How each item is rendered: one entry per field, with a type drawn from the display registry (text, image, audio, video, ...) | `fields`, `layout`, `resizable` |
| `jumping_to_id_disabled` |  | boolean |  | Remove the jump-to-item control |  |
| `layout` |  | object |  | How the annotation questions are arranged on the page: a grid, collapsible groups, an explicit order, and responsive breakpoints. Without it every scheme stacks full-width in config order | `breakpoints`, `grid`, `groups`, `order`, `styling` |
| `list_as_text` |  | object |  | How a list-valued field is laid out. Sub-keys: text_list_prefix_type (alphabet, number, bullet or none), horizontal, alternating_shading. `true` turns it on with the defaults | `alternating_shading`, `horizontal`, `text_list_prefix_type` |
| `task_layout` |  | string |  | Custom HTML for the annotation form area |  |
| `ui` |  | object |  | Interface toggles |  |
| `ui_config` |  | object |  | Additional interface settings |  |
| `ui_language` |  | string | `en` | Interface language code | `_base`, `adjudicate`, `admin_btn_computing`, `admin_btn_generate_scores`, `admin_btn_reload`, `admin_btn_save_changes`, `admin_err_annotators`, `admin_err_behavioral`, `admin_err_config`, `admin_err_crowdsourcing`, `admin_err_instances`, `admin_err_mace_load`, `admin_err_mace_trigger`, `admin_err_overview`, `admin_err_questions`, `admin_filter_all`, `admin_filter_completed`, `admin_filter_incomplete`, `admin_hint_unlimited`, `admin_label_assignment_strategy`, `admin_label_max_per_item`, `admin_label_max_per_user`, `admin_login_help`, `admin_login_key_label`, `admin_login_key_placeholder`, `admin_login_submit`, `admin_login_title`, `admin_mace_predicted_help`, `admin_mace_run_predictions`, `admin_mode_badge`, `admin_ok_config_saved`, `admin_opt_color_mace`, `admin_opt_color_majority`, `admin_opt_per_page`, `admin_opt_scoring_counting`, `admin_opt_strat_active_learning`, `admin_opt_strat_fixed_order`, `admin_opt_strat_least_annotated`, `admin_opt_strat_llm_confidence`, `admin_opt_strat_max_diversity`, `admin_opt_strat_random`, `admin_order_asc`, `admin_order_desc`, `admin_page_title`, `admin_section_ai_usage`, `admin_section_bws_scores`, `admin_section_competence`, `admin_section_predicted_labels`, `admin_section_quality`, `admin_section_system_config`, `admin_section_system_info`, `admin_sort_annotations`, `admin_sort_avg_time`, `admin_sort_completion`, `admin_sort_disagreement`, `admin_sort_id`, `admin_tab_annotators`, `admin_tab_behavioral`, `admin_tab_bws`, `admin_tab_configuration`, `admin_tab_crowdsourcing`, `admin_tab_datasets`, `admin_tab_embeddings`, `admin_tab_instances`, `admin_tab_mace`, `admin_tab_overview`, `admin_tab_questions`, `admin_th_ai_accept_rate`, `admin_th_ai_requests`, `admin_th_annotations`, `admin_th_annotator`, `admin_th_annotators`, `admin_th_appearances`, `admin_th_assignment_id`, `admin_th_avg_time`, `admin_th_avg_time_per_annotation`, `admin_th_avg_time_s`, `admin_th_best_count`, `admin_th_changes`, `admin_th_competence`, `admin_th_completion`, `admin_th_completion_pct`, `admin_th_disagreement`, `admin_th_instance`, `admin_th_instance_id`, `admin_th_instances`, `admin_th_interactions`, `admin_th_item_id`, `admin_th_last_activity`, `admin_th_max_instances`, `admin_th_most_frequent_label`, `admin_th_num_ai_used`, `admin_th_phase`, `admin_th_predicted_label`, `admin_th_rank`, `admin_th_reliability`, `admin_th_score`, `admin_th_session_id`, `admin_th_speed`, `admin_th_speed_per_hour`, `admin_th_status`, `admin_th_suspicion`, `admin_th_text`, `admin_th_text_preview`, `admin_th_time`, `admin_th_uncertainty`, `admin_th_user_id`, `admin_th_worker_id`, `admin_th_working_time`, `admin_th_worst_count`, `arena_empty`, `arena_enter_prompt`, `arena_error_prefix`, `arena_export`, `arena_export_title`, `arena_failed`, `arena_heading`, `arena_lb_note`, `arena_leaderboard_heading`, `arena_lede`, `arena_models_label`, `arena_ms`, `arena_no_dpo_pairs`, `arena_page_title`, `arena_pick_as_best`, `arena_picked`, `arena_prompt_heading`, `arena_prompt_placeholder`, `arena_responses_heading`, `arena_run`, `arena_running`, `arena_sent_to`, `arena_th_bt`, `arena_th_comparisons`, `arena_th_elo`, `arena_th_model`, `arena_th_win_rate`, `arena_th_wins`, `audio_to_annotate`, `automation_actions_error`, `automation_actions_ok`, `automation_actions_skipped`, `automation_activity`, `automation_col_action`, `automation_col_actions`, `automation_col_detail`, `automation_col_enabled`, `automation_col_item`, `automation_col_rule`, `automation_col_sample_rate`, `automation_col_status`, `automation_configured_rules`, `automation_heading`, `automation_items_processed`, `automation_latest`, `automation_lede_1`, `automation_lede_2`, `automation_lede_3`, `automation_no`, `automation_no_actions`, `automation_no_rules`, `automation_page_title`, `automation_recent_outcomes`, `automation_reload`, `automation_rules_fired`, `automation_snapshot_title`, `automation_yes`, `catalog_all_placeholder`, `catalog_anchor_label`, `catalog_anchor_placeholder`, `catalog_build_index`, `catalog_clusters_label`, `catalog_discover_button`, `catalog_discover_desc`, `catalog_discover_heading`, `catalog_embeddings_warn_1`, `catalog_embeddings_warn_2`, `catalog_heading`, `catalog_index_heading`, `catalog_items_indexed`, `catalog_lede_1`, `catalog_lede_2`, `catalog_lede_3`, `catalog_lede_slices`, `catalog_lede_what`, `catalog_more_traces_suffix`, `catalog_no_matches`, `catalog_no_slices`, `catalog_page_title`, `catalog_prompt_curate_prefix`, `catalog_prompt_curate_suffix`, `catalog_query_text_label`, `catalog_query_text_placeholder`, `catalog_resolve_button`, `catalog_save_slice_button`, `catalog_search_button`, `catalog_search_heading`, `catalog_slice_name_label`, `catalog_slice_query_label`, `catalog_slice_query_placeholder`, `catalog_slice_threshold_label`, `catalog_slices_heading`, `catalog_status_building`, `catalog_status_candidate_modes`, `catalog_status_clustering`, `catalog_status_curating`, `catalog_status_failed`, `catalog_status_imported_mid`, `catalog_status_imported_prefix`, `catalog_status_imported_suffix`, `catalog_status_indexed_prefix`, `catalog_status_indexed_suffix`, `catalog_status_matching_instances`, `catalog_status_name_required`, `catalog_status_results_suffix`, `catalog_status_saved`, `catalog_status_searching`, `catalog_th_actions`, `catalog_th_instance`, `catalog_th_query_anchor`, `catalog_th_similarity`, `catalog_th_slice`, `catalog_th_threshold`, `catalog_threshold_label`, `catalog_to_dataset_button`, `catalog_topk_label`, `catalog_traces_suffix`, `catalog_unlabeled`, `choose_username_placeholder`, `cite_us`, `codebook`, `continue_button`, `create_password_placeholder`, `dash_assigned_completed`, `dash_back_to_annotating`, `dash_error`, `dash_items_started_pct`, `dash_loading`, `dash_no_items_assigned`, `dash_no_items_project`, `dash_project_progress`, `dash_readonly`, `dash_stat_active_annotators`, `dash_stat_annotated`, `dash_stat_annotations`, `dash_stat_assigned`, `dash_stat_complete`, `dash_stat_items_started`, `dash_stat_total_items`, `dash_subtitle`, `dash_your_progress`, `datasets_annotation_process`, `datasets_assignment_active`, `datasets_assignment_paused`, `datasets_col_cmp`, `datasets_col_created`, `datasets_col_dataset`, `datasets_col_examples`, `datasets_col_experiment`, `datasets_col_scores`, `datasets_col_version`, `datasets_compare_selected`, `datasets_create_dataset_btn`, `datasets_created`, `datasets_creating`, `datasets_dataset_label`, `datasets_datasets_heading`, `datasets_description_label`, `datasets_done`, `datasets_evaluators_label`, `datasets_example_label`, `datasets_examples_label`, `datasets_experiments_heading`, `datasets_failed`, `datasets_heading`, `datasets_lede`, `datasets_llm_judge_note`, `datasets_loading_status`, `datasets_name_hint`, `datasets_name_label`, `datasets_new_dataset`, `datasets_no_datasets`, `datasets_no_experiments`, `datasets_optional_placeholder`, `datasets_page_title`, `datasets_pause_assignment`, `datasets_pick_dataset_evaluator`, `datasets_resume_assignment`, `datasets_run_btn`, `datasets_run_experiment`, `datasets_running`, `datasets_select_dataset`, `datasets_select_label`, `datasets_stat_annotated`, `datasets_stat_annotators`, `datasets_stat_datasets`, `datasets_stat_experiments`, `datasets_stat_ingested`, `datasets_stat_instances`, `datasets_stat_multi_annotated`, `datasets_stat_remaining`, `datasets_status_unavailable`, `datasets_version_label`, `datasets_versions_label`, `dsdetail_back_link`, `dsdetail_col_created`, `dsdetail_col_examples`, `dsdetail_col_experiment`, `dsdetail_col_id`, `dsdetail_col_inputs`, `dsdetail_col_note`, `dsdetail_col_reference`, `dsdetail_col_scores`, `dsdetail_col_split`, `dsdetail_col_tags`, `dsdetail_col_version`, `dsdetail_examples_heading`, `dsdetail_examples_subtitle`, `dsdetail_experiments_heading`, `dsdetail_export_dpo`, `dsdetail_export_dpo_title`, `dsdetail_export_sft`, `dsdetail_export_sft_title`, `dsdetail_import_instances`, `dsdetail_import_instances_title`, `dsdetail_import_traces`, `dsdetail_import_traces_title`, `dsdetail_include_annotations`, `dsdetail_no_examples`, `dsdetail_no_experiments`, `dsdetail_no_versions`, `dsdetail_status_import_failed`, `dsdetail_status_imported`, `dsdetail_status_imported_suffix`, `dsdetail_status_importing`, `dsdetail_tag_button`, `dsdetail_tag_input_label`, `dsdetail_tag_placeholder`, `dsdetail_versions_heading`, `error_heading`, `evalanalytics_alerts_heading`, `evalanalytics_col_avg_latency`, `evalanalytics_col_cost`, `evalanalytics_col_errors`, `evalanalytics_col_model`, `evalanalytics_col_tokens`, `evalanalytics_col_traces`, `evalanalytics_empty`, `evalanalytics_lede_after`, `evalanalytics_lede_before`, `evalanalytics_lede_tail`, `evalanalytics_permodel_aria`, `evalanalytics_permodel_heading`, `evalanalytics_stat_avg_latency`, `evalanalytics_stat_error_rate`, `evalanalytics_stat_p95_latency`, `evalanalytics_stat_total_cost`, `evalanalytics_stat_total_tokens`, `evalanalytics_stat_traces`, `evalanalytics_title`, `expcompare_back_link`, `expcompare_baseline`, `expcompare_ci_label`, `expcompare_col_metric`, `expcompare_empty`, `expcompare_heading`, `expcompare_lede_part1`, `expcompare_lede_part2`, `expcompare_lede_strong`, `expcompare_not_significant`, `expcompare_page_title`, `expcompare_row_examples`, `expcompare_sig_title`, `expcompare_significant`, `forgot_password`, `go_button`, `html_dir`, `html_lang`, `iaa_admin_dashboard`, `iaa_agreement`, `iaa_annotators`, `iaa_at_cap`, `iaa_band_fair`, `iaa_band_moderate`, `iaa_band_poor`, `iaa_band_strong`, `iaa_band_substantial`, `iaa_band_weak`, `iaa_drift_approx`, `iaa_drift_baseline`, `iaa_drift_below_baseline`, `iaa_drift_codebook_changes`, `iaa_drift_note`, `iaa_drift_recalibrate`, `iaa_drift_sparse`, `iaa_drift_th_window`, `iaa_drift_title`, `iaa_drift_untimed`, `iaa_empty_state`, `iaa_fully_aligned_items`, `iaa_items`, `iaa_meta_scored`, `iaa_na`, `iaa_overlap_sample`, `iaa_per_item_breakdown`, `iaa_scale_correlation_label`, `iaa_scale_correlation_note`, `iaa_scale_coverage_label`, `iaa_scale_coverage_note`, `iaa_scale_distribution_label`, `iaa_scale_distribution_note`, `iaa_scale_kappa_label`, `iaa_scale_lower_label`, `iaa_scale_lower_note`, `iaa_scale_raw_label`, `iaa_scale_raw_note`, `iaa_scale_span_label`, `iaa_scale_span_note_post`, `iaa_scale_span_note_pre`, `iaa_sweep_headline`, `iaa_sweep_note`, `iaa_sweep_title`, `iaa_th_annotators`, `iaa_th_cap`, `iaa_th_instance`, `iaa_th_metric`, `iaa_th_value`, `iaa_title`, `iaa_title_overlap_sample`, `in_progress_badge`, `instructions_heading`, `integrity_annotators_suffix`, `integrity_col_annotator`, `integrity_col_ca_score`, `integrity_col_flags`, `integrity_col_items`, `integrity_col_llm_alignment`, `integrity_col_residual`, `integrity_col_suspicion`, `integrity_correlated_agreement`, `integrity_heading`, `integrity_lede`, `integrity_lede_ca_desc`, `integrity_lede_residual_desc`, `integrity_lede_with_low`, `integrity_lede_without_ground_truth`, `integrity_llm_alignment`, `integrity_llm_labels_available`, `integrity_no_annotations`, `integrity_no_llm_labels`, `integrity_page_title`, `integrity_residual`, `judge_above`, `judge_agreement`, `judge_autocalibrate`, `judge_autocalibrate_intro_1`, `judge_autocalibrate_intro_2`, `judge_autocalibrate_intro_3`, `judge_autocalibrate_intro_4`, `judge_autocalibrate_intro_5`, `judge_bias_robustness`, `judge_chars`, `judge_cohens_kappa`, `judge_col_conf`, `judge_col_human`, `judge_col_instance`, `judge_col_judge`, `judge_col_reasoning`, `judge_compared_n`, `judge_confusion_caption`, `judge_confusion_caption_2`, `judge_confusion_label`, `judge_corrected`, `judge_current_paren`, `judge_current_prompt_version`, `judge_disagreements`, `judge_empty_1`, `judge_empty_2`, `judge_empty_3`, `judge_eval_cards`, `judge_eval_cards_intro`, `judge_heading`, `judge_human_vs_judge`, `judge_intro`, `judge_length_bias`, `judge_mean_kappa`, `judge_mean_kappa_drift`, `judge_over_versions`, `judge_page_title`, `judge_predictions`, `judge_prompt_versions`, `jump_next_unannotated`, `jump_prev_unannotated`, `labeled_badge`, `loading`, `login_subtitle_password`, `login_subtitle_username`, `login_title`, `logout`, `next_button`, `not_labeled_badge`, `or_divider`, `password_label`, `powered_by`, `previous_button`, `progress_label`, `register_button`, `register_tab`, `retry_button`, `sign_in_button`, `sign_in_tab`, `sign_in_with`, `submit_button`, `text_to_annotate`, `triage_col_annotations`, `triage_col_assigned`, `triage_col_instance`, `triage_col_priority`, `triage_col_reason`, `triage_empty_queue`, `triage_flagged`, `triage_heading`, `triage_intro_before`, `triage_intro_served`, `triage_intro_signal`, `triage_items_remaining`, `triage_no`, `triage_not_enabled_after`, `triage_not_enabled_before`, `triage_not_enabled_rank`, `triage_page_title`, `triage_priority_label`, `triage_summary_aria`, `triage_table_caption`, `triage_yes`, `username_label`, `username_placeholder`, `video_to_annotate` |

## Content

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `annotation_codebook_url` |  | string |  | Link to an external codebook, shown to annotators |  |
| `annotation_instructions` |  | string |  | Instructions shown on every annotation page, as inline text; a filename here renders as that filename |  |
| `completion_code` |  | string |  | Code shown when an annotator finishes, for crowdsourcing payout |  |
| `custom_footer_html` |  | string |  | HTML appended to every page |  |
| `header_file` |  | string |  | Ignored. The header template path is no longer configurable, and nothing reads this key -- `potato validate` reports it |  |
| `header_logo` |  | string |  | Logo image shown in the header |  |
| `highlight_linebreaks` |  | boolean |  | Make line breaks visible in item text |  |
| `keyword_highlight_settings` |  | object |  | Styling for keyword highlights |  |
| `keyword_highlights_file` |  | string |  | File of keywords to highlight in item text. A CSV or TSV with a `keyword` header column (plus optional label, schema, color) is the documented form; one keyword per line, and JSON/JSONL/YAML holding a keyword list, an object list or a {keyword: label} map, are read too. A `*` in a keyword matches any run of word characters. See docs/administration/productivity.md |  |

## Annotation Features

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `allow_phase_back_navigation` |  | boolean | `False` | Let annotators go back to an earlier workflow phase. Off by default, so consent and training cannot be revisited and re-answered |  |
| `auto_export_interval` |  | integer | `60` | Seconds between automatic exports |  |
| `auto_redirect_delay` |  | integer | `5000` | Milliseconds on the completion page before that redirect fires |  |
| `auto_redirect_on_completion` |  | boolean | `False` | Send annotators to the crowd platform's completion URL when they finish, instead of leaving them on the done page |  |
| `export_annotation_format` |  | array or string | `[]` | Formats the periodic auto-export writes, as a list (a bare string is accepted). Empty means no auto-export |  |
| `export_include_annotation_changes` |  | boolean | `False` | Write annotation_changes.csv, the timestamped record of every answer revision. Off by default: it is far larger than the annotations and carries interaction detail not every study wants to distribute |  |
| `export_include_phase_data` |  | boolean | `False` | Include consent, instruction and survey responses in exports. Off by default: survey answers are usually where the PII is |  |

## Media

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `audio_annotation` |  | object |  | Server-side waveform service backing audio_annotation schemes. Only read when the task actually has one | `client_fallback_max_duration`, `waveform_cache_dir`, `waveform_cache_max_size`, `waveform_look_ahead` |

## External Integrations

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `agent_proxy` |  | object |  | Run an agent as the subject of annotation. This block only configures the backend -- to put the chat on the page, add an `instance_display` field of `type: interactive_chat`, which renders the panel the annotator talks to. Connection settings (api_key, base_url, model) may be written directly in the block or under `ai_config` inside it, as the other model-backed blocks take them; a `base_url` pointing at an OpenAI-compatible server needs no key. Set `enabled: false` to turn it off without deleting the block |  |
| `crowdsourcing` |  | object |  | Crowd platform integration (Prolific, MTurk and others) |  |
| `database` |  | object |  | Database connection for item or user storage | `connection_string`, `database`, `host`, `password`, `pool_size`, `pool_timeout`, `port`, `type`, `username` |
| `huggingface_backup` |  | object |  | Mirror the annotation directory to a Hugging Face dataset repo on a schedule. Needs `enabled` and `repo_id`; the token comes from `token` (env substitution is applied) or HF_TOKEN, and `schedule_minutes` sets the cadence. A misconfiguration logs an error and lets the server run |  |
| `mcp` |  | object |  | Model Context Protocol control surface, letting an agent query and control this running task. Off unless every tool is named explicitly | `allow_debug`, `audit_log`, `auth`, `destructive`, `enabled`, `scope`, `tools` |
| `mturk` |  | object |  | Amazon Mechanical Turk. Needs `enabled: true` and `config_file_path` pointing at the credentials YAML, plus boto3 installed. MTurk closed to new customers in July 2026 and the loader says so on startup |  |
| `prolific` |  | object |  |  | `completion_code`, `config_file_path`, `max_concurrent_sessions`, `sandbox_mode`, `study_id`, `token`, `workload_checker`, `workload_checker_period` |
| `trace_ingestion` |  | object |  | Accept agent traces posted to /api/traces/* | `allow_unauthenticated`, `api_key`, `enabled`, `notify_annotators`, `sources` |
| `webhooks` |  | object |  | Post task events to external URLs as they happen | `enabled`, `endpoints` |

## Publishing & Export

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `dataset_metadata` |  | object |  | Descriptive metadata for the generated dataset card and Zenodo deposit: license, authors, citation, keywords, version, funding, related_links, tags, task_categories. Title and description fall back to the task's own name and description |  |
| `publish` |  | object |  | Dataset publishing options: `default_target` (archive, huggingface or zenodo) and an `options` block covering which splits are included, aggregation, min_annotators, PII scrubbing, media bundling and file format. Publishing works with none of this set |  |

## Debug / Logging

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `debug` |  | boolean | `False` | Run in debug mode. This disables admin authentication and skips login entirely, so it must never be set on a deployed server |  |
| `debug_log` |  | string |  | Which halves of the debug logging to turn on: all, ui, server or none. The --debug-log flag writes this key |  |
| `debug_phase` |  | string |  | Jump straight to a workflow phase, for UI debugging |  |
| `server_debug` |  | boolean | `False` | Backend debug logging. Note that only the phase pages (consent, instructions, surveys) read this key; the annotation page asks the logging module, which is driven by debug_log/verbose/debug |  |
| `ui_debug` |  | boolean | `False` | Print browser-side debug logging to the console |  |
| `verbose` |  | boolean | `False` | Raise the log level. --verbose writes this key |  |
| `very_verbose` |  | boolean | `False` | Raise the log level further; equivalent to debug for logging purposes, without debug's effect on authentication. --veryVerbose writes this key |  |

## Agent

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `live_agent` |  | object |  | Run a live agent inside the annotation page, so annotators judge a conversation as it happens rather than a recorded trace. Its presence enables the feature, and an instance_display field of type live_agent renders it |  |
| `live_coding_agent` |  | object |  | Same idea for a coding agent: runs the agent against a repository and streams its tool calls into a live_coding_agent display field | `acknowledge_untrusted_code_execution`, `ai_config`, `backend_type`, `container_cli`, `container_runtime`, `max_turns`, `sandbox_cpus`, `sandbox_image`, `sandbox_memory`, `sandbox_mode`, `sandbox_network`, `sandbox_pids_limit`, `sandbox_root`, `sandbox_user`, `system_prompt`, `working_dir` |

## Agent Evaluation Suite

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `arena` |  | object |  | Multi-model arena: send one prompt to several providers and collect side-by-side preferences | `enabled`, `models` |
| `automation` |  | object |  | Rules engine over incoming items: filter, sample, then act | `enabled`, `rules` |
| `cot_segmentation` |  | object |  | Split a long chain-of-thought string into labelable steps once, at load time, so the cot_trace display and the process_reward scheme read the same cached list | `llm_max_chars`, `markers`, `max_steps`, `min_step_chars`, `sentences_per_step`, `source_key`, `strategy`, `target_key` |
| `curation` |  | object |  | Semantic curation (the Catalog): an embedding index over items, similarity search, and saved slices that stay live as data arrives | `embed_on_ingest`, `enabled`, `model_name`, `text_key` |
| `datasets` |  | object |  | Versioned evaluation datasets and experiment runs, served at /datasets | `enabled`, `storage` |
| `judge_alignment` |  | object |  | LLM-as-judge alignment: score items with a judge, compare against the humans, and track the agreement across prompt versions | `ai_support`, `enabled`, `few_shot`, `inline`, `schemas` |
| `judge_calibration` |  | object |  | Judge calibration: auto-label a sample with one or more judges, have humans re-label the same items blind, and report the agreement and calibration curve | `calibration`, `enabled`, `fraction`, `human`, `k_samples`, `max_items`, `models`, `output`, `prompt`, `sampling`, `schemas`, `state_dir` |

## Workflow & Phases

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `prestudy` |  | object |  | Legacy pre-study screening block. The only code that reads it is an unreferenced method, so it has no effect -- configure the screening phase through `phases` or `surveyflow` with `type: prestudy` |  |
| `review_mode` |  | object |  | Hotkey review queue. Once the current item is complete the page moves on by itself, which turns keyboard-labelled schemes into press-key-and-advance | `advance_on`, `auto_advance`, `delay_ms`, `enabled` |
| `review_workflow` |  | object |  | Reviewer routing and the kanban board at /admin/review. Keeps its own state per instance (pending, in_review, needs_second, adjudication, done) alongside the annotations | `auto_enroll`, `enabled`, `reviewers`, `routing` |
| `triage` |  | object |  | Rank items by a priority signal so failures, thumbs-down feedback and low scores get annotated first. Scoring runs as items are added, so it covers traces ingested at runtime as well as loaded files | `default_priority`, `enabled`, `invert_signal`, `order`, `rules`, `show_badge`, `signal_field` |

## Assignment & Sessions

| Key | Required | Type | Default | Description | Sub-keys |
|-----|----------|------|---------|-------------|----------|
| `alert_time_each_instance` |  | integer | `10000000` | Seconds an annotator may spend on one item before being warned. The default is effectively no limit |  |
| `assignment_strategy` |  | string (one of: random, fixed_order, active_learning, llm_confidence, max_diversity, least_annotated, category_based, diversity_clustering, batch, priority, psychometric, model_review) | `fixed_order` | How items are handed out: random, fixed_order, active_learning, llm_confidence, max_diversity, least_annotated, category_based, diversity_clustering, batch, priority, or psychometric |  |
| `automatic_assignment` |  | object |  | Assign items to annotators automatically as they arrive |  |
| `batch_assignment` |  | object |  | Split items into named groups and assign whole batches | `annotator_key`, `auto_assign_annotators`, `groups` |
| `instance_reclaim` |  | object |  | Take assignments back from annotators who abandoned them so the items can go out again. `enabled` (false) and `timeout_hours` (24), plus optional `stale`, `manual`, `quality_control` and `prolific` sections each carrying `preserve_completed_annotations` |  |
| `max_annotations_per_item` |  | integer | `-1` | Cap on how many annotators may label one item. -1 means unlimited |  |
| `max_annotations_per_user` |  | integer | `-1` | Cap on how many dataset items one annotator may receive. Left unset, the cap is the number of items loaded, so every annotator is offered the whole corpus; -1 is explicit unlimited, which is what a dynamic data source needs for items added after boot to be assignable. Injected attention checks and gold items do not count against it |  |
| `max_session_seconds` |  | integer |  | Hard limit on one annotation session |  |
| `min_annotators_per_instance` |  | integer |  | Floor on annotators per item before it counts as done |  |
| `num_annotators_per_item` |  | integer or object | `3` | Target annotators per item. Either a plain count or a mapping carrying `default` plus overlap-sampling and adaptive-boost rules |  |
| `per_annotator_quota` |  | object |  | Per-annotator workload caps: `default`, plus `by_user` and `by_user_role` overrides. Any other sub-key is rejected at load rather than ignored |  |
| `random_seed` |  | integer |  | Seed for assignment shuffling, so an ordering can be reproduced |  |
| `scheme_sets` |  | object |  | Named, reusable lists of annotation schemes. A batch_assignment group names one in its `schemes` key to give that cohort its own questions |  |
| `sessions` |  | object |  | Group items into sessions by session_id or thread_id and score the whole session at /sessions. Schemes opt in with `session_level: true` | `attributes`, `enabled`, `key` |
| `solo_mode` |  | object |  | Single-coder loop. An LLM labels the corpus, you review where it is least sure, and the prompt is refined from your corrections | `batches`, `confidence_routing`, `confusion_analysis`, `edge_case_rules`, `embedding`, `enabled`, `instance_selection`, `labeling_functions`, `labeling_models`, `prompt_optimization`, `refinement_loop`, `revision_models`, `state_dir`, `thresholds`, `uncertainty` |

## Annotation Types

All supported `annotation_type` values and their required/optional fields.
Set via `annotation_schemes[].annotation_type` in your config.

| Type | Required Fields | Optional Fields | Description | Example |
|------|----------------|-----------------|-------------|---------|
| `agent_interaction_graph` | (none beyond name/description) | `steps_key`, `agent_key` | Clickable agent-interaction graph: mark critical-path nodes + flag problematic edges | `examples/agent-traces/interaction-graph/config.yaml` |
| `agent_scorecard` | (none beyond name/description) | `steps_key`, `agent_key`, `agents`, `agent_dimensions`, `team_dimensions`, `milestones`, `scale` | Per-agent + per-team scorecard with optional milestones (MultiAgentBench-style) | `examples/agent-traces/agent-scorecard/config.yaml` |
| `audio_annotation` | (none beyond name/description) | `mode`, `labels`, `segment_schemes`, `min_segments`, `max_segments`, `zoom_enabled`, `playback_rate_control`, `waveform`, `spectrogram`, `spectrogram_options`, `source_field` | Audio segmentation and annotation with waveform visualization | `examples/audio/audio-annotation/config.yaml` |
| `bws` | (none beyond name/description) | `best_description`, `worst_description`, `tuple_size`, `sequential_key_binding`, `label_requirement` | Best-Worst Scaling: select the best and worst item from a set | `examples/classification/iterative-bws/config.yaml` |
| `card_sort` | (none beyond name/description) | `mode`, `groups`, `items_field`, `allow_empty_groups`, `allow_multiple` | Drag-and-drop card sorting into predefined or user-created groups | `examples/classification/card-sort/config.yaml` |
| `code_review` | (none beyond name/description) | `comment_categories`, `verdict_options`, `file_rating_dimensions` | GitHub PR-style code review with inline comments and file ratings | `examples/agent-traces/coding-agent-review/config.yaml` |
| `confidence` | (none beyond name/description) | `target_schema`, `scale_type`, `scale_points`, `labels`, `min_value`, `max_value`, `step`, `left_label`, `right_label` | Confidence rating meta-annotation for any primary annotation | `examples/classification/confidence-calibrated/config.yaml` |
| `conjoint` | (none beyond name/description) | `profiles_per_set`, `attributes`, `show_none_option`, `profiles_field` | Discrete choice conjoint analysis with side-by-side profile comparison | `examples/classification/conjoint/config.yaml` |
| `consensus_tracking` | (none beyond name/description) | `turns_key`, `acts`, `linked_acts`, `hint` | Tag discussion acts per turn (proposal/agreement/disagreement/decision/concession) with cross-turn links to referenced proposals | `examples/agent-traces/debate-judging/config.yaml` |
| `constant_sum` | `labels` | `total_points`, `min_per_item`, `input_type` | Allocate a fixed budget of points across categories | `examples/classification/constant-sum/config.yaml` |
| `context_attribution` | (none beyond name/description) | `turns_key`, `acts`, `linked_acts`, `hint` | Tag how each turn uses earlier context (used correctly / hallucinated / ignored) with links to the source turn | `examples/agent-traces/context-attribution/config.yaml` |
| `coreference` | `span_schema` | `entity_types`, `allow_singletons`, `visual_display` | Coreference chain annotation for grouping mentions of the same entity | `examples/span/coreference/config.yaml` |
| `emergent_behavior` | (none beyond name/description) | `steps_key`, `agent_key`, `behaviors`, `allow_note` | Cross-lane emergent-behavior tagging: mark turn-sets for collusion/groupthink/cascade/role-drift | `examples/agent-traces/emergent-behavior/config.yaml` |
| `episode_annotation` | (none beyond name/description) | `source_field`, `episode_field`, `layers`, `phases`, `outcomes`, `failure_causes`, `reward_range`, `series_shown`, `max_lanes`, `min_phases`, `max_phases` | Embodied robot episode: synchronized video streams and time-series lanes with phase, outcome and dense-reward annotation | `examples/embodied/lerobot-episode/config.yaml` |
| `error_span` | `error_types` | `severities`, `show_score`, `max_score`, `source_field` | MQM-style error span annotation with typed severity for quality evaluation | `examples/classification/error-span/config.yaml` |
| `event_annotation` | `event_types`, `span_schema` | `visual_display` | N-ary event annotation with triggers and typed arguments | `examples/span/event-annotation/config.yaml` |
| `extractive_qa` | (none beyond name/description) | `question_field`, `passage_field`, `allow_unanswerable`, `highlight_color` | SQuAD-style extractive question answering with answer span highlighting | `examples/classification/extractive-qa/config.yaml` |
| `failure_attribution` | (none beyond name/description) | `steps_key`, `agent_key`, `agents` | Multi-agent failure attribution: responsible agent + decisive step + reason | `examples/agent-traces/failure-attribution/config.yaml` |
| `grounding_eval` | (none beyond name/description) | `region_type`, `expression_source`, `expressions_field`, `caption_field`, `predictions_field`, `label`, `verdicts`, `require_all` | Grounding evaluation: bind referring expressions to image regions or points, with an explicit not-present answer | `examples/ai-assisted/grounding-eval/config.yaml` |
| `gui_trajectory` | (none beyond name/description) | `steps_key`, `screenshot_key`, `action_key`, `coord_space`, `verdict_options` | Computer-use/GUI agent step review: per-step screenshot + action correctness + click grounding | `examples/agent-traces/gui-trajectory/config.yaml` |
| `handoff_review` | (none beyond name/description) | `steps_key`, `agent_key`, `flags`, `quality_scale` | Annotate agent-to-agent handoffs: inter-agent misalignment flags + quality | `examples/agent-traces/handoff-review/config.yaml` |
| `hierarchical_multiselect` | `taxonomy` | `auto_select_children`, `auto_select_parent`, `show_search`, `max_selections`, `taxonomy_preset`, `tooltips` | Hierarchical tree-structured multi-label selection | `examples/classification/hierarchical-multiselect/config.yaml` |
| `image_annotation` | `tools`, `labels` | `zoom_enabled`, `pan_enabled`, `min_annotations`, `max_annotations`, `freeform_brush_size`, `freeform_simplify`, `brush_size`, `eraser_size`, `mask_opacity`, `fill_mode`, `fill_tolerance`, `fill_max_pixels`, `source_field`, `ai_support`, `keybinding_profile`, `carry_over`, `viewer`, `tiles`, `segmentation`, `instance_masks`, `text_prompt`, `skeletons`, `mask_mode` | Image annotation with bounding boxes, polygons, freeform drawing, and landmarks | `examples/image/image-annotation/config.yaml` |
| `likert` | `min_label`, `max_label`, `size` | `label_requirement`, `labels`, `displaying_score`, `bad_text_label`, `sequential_key_binding` | Likert scale rating | `examples/classification/likert/config.yaml` |
| `multi_document_event` | `slots` | `allow_annotator_create`, `template_name` | Cross-document event annotation: template slots filled with evidence from many documents | `examples/advanced/multi-document-events/config.yaml` |
| `multimodal_reasoning` | (none beyond name/description) | `steps_key`, `type_key`, `verdict_options` | Interleaved text/image/tool reasoning trace: per-step coherence + visual-hallucination rating | `examples/agent-traces/multimodal-reasoning/config.yaml` |
| `multirate` | `options`, `labels` | `label_requirement`, `options_from_data`, `display_config`, `arrangement`, `randomize_order` | Rate multiple items on a scale | `examples/classification/multirate/config.yaml` |
| `multiselect` | `labels` | `display_config`, `label_requirement`, `sequential_key_binding`, `video_as_label`, `has_free_response`, `option_randomization`, `dynamic_options`, `dynamic_options_field`, `codebook`, `randomize_order` | Multiple-choice checkbox selection | `examples/classification/check-box/config.yaml` |
| `number` | (none beyond name/description) | `min`, `max`, `step`, `label_requirement`, `min_value`, `max_value`, `custom_css`, `tooltip`, `tooltip_file` | Numeric input field | `examples/advanced/all-annotation-types/config.yaml` |
| `pairwise` | (none beyond name/description) | `mode`, `items_key`, `items`, `show_labels`, `labels`, `allow_tie`, `tie_label`, `sequential_key_binding`, `scale`, `label_requirement`, `dimensions`, `justification`, `randomize_order` | Pairwise comparison of two items (binary selection or scale rating) | `examples/classification/pairwise-scale/config.yaml` |
| `process_reward` | (none beyond name/description) | `steps_key`, `step_text_key`, `mode`, `allow_neutral`, `inline_with_trace`, `ai_prelabel`, `require_verification`, `reward_labels` | Per-step process reward signals for PRM training | `examples/agent-traces/cot-process-reward/config.yaml` |
| `pure_display` | (none beyond name/description) | `labels`, `allow_html` | Display-only content (instructions, headers) | `examples/advanced/all-annotation-types/config.yaml` |
| `radio` | `labels` | `horizontal`, `label_requirement`, `sequential_key_binding`, `has_free_response`, `option_randomization`, `dynamic_options`, `dynamic_options_field`, `codebook`, `randomize_order` | Single-choice radio button selection | `examples/classification/single-choice/config.yaml` |
| `range_slider` | (none beyond name/description) | `min_value`, `max_value`, `step`, `left_label`, `right_label`, `show_values` | Dual-thumb slider for selecting an acceptable range | `examples/classification/range-slider/config.yaml` |
| `ranking` | `labels` | `allow_ties` | Drag-and-drop ranking of items by preference or relevance | `examples/classification/ranking/config.yaml` |
| `region_caption` | (none beyond name/description) | `placeholder`, `min_length`, `max_length`, `require_all`, `agreement_distance` | Region captioning: a free-text description per region drawn on the image, with caption agreement over matched regions | `examples/image/region-captioning/config.yaml` |
| `rollout_evaluation` | (none beyond name/description) | `streams`, `manifest_field`, `prompt_field`, `intervention_field`, `intervention_time_field`, `fps`, `layers`, `violation_types`, `severities`, `cf_verdicts`, `rubric`, `blind`, `shuffle`, `require_clean`, `max_violations` | World-model rollout evaluation: frame-locked video panels with temporal violation localization, preference and counterfactual plausibility | `examples/agent-traces/world-model-rollouts/config.yaml` |
| `rubric_eval` | `criteria` | `scale_points`, `scale_labels`, `show_overall` | Multi-criteria rubric evaluation grid for LLM and text quality assessment | `examples/classification/rubric-eval/config.yaml` |
| `select` | `labels` | `label_requirement`, `option_randomization`, `dynamic_options`, `dynamic_options_field`, `use_predefined_labels`, `codebook`, `randomize_order` | Dropdown selection | `examples/advanced/all-annotation-types/config.yaml` |
| `semantic_differential` | `pairs` | `scale_points` | Bipolar adjective scales for measuring connotative meaning | `examples/classification/semantic-differential/config.yaml` |
| `slider` | `min_value`, `max_value`, `starting_value` | `step`, `label_requirement`, `labels`, `show_labels`, `maxTick` | Slider for selecting a value in a range | `examples/classification/slider/config.yaml` |
| `soft_label` | `labels` | `total`, `min_per_label`, `show_distribution_chart` | Probability distribution across labels via constrained sliders | `examples/classification/soft-label/config.yaml` |
| `span` | `labels` | `sequential_key_binding`, `bad_text_label`, `title`, `allow_discontinuous`, `entity_linking`, `show_span_labels`, `target_field`, `columns`, `displaying_score`, `codebook` | Text span annotation/highlighting with optional entity linking to knowledge bases | `examples/span/span-labeling/config.yaml` |
| `span_link` | `link_types`, `span_schema` | `visual_display` | Create relationships/links between spans (e.g., PERSON works_for ORGANIZATION) | `examples/span/span-linking/config.yaml` |
| `spatial_annotation` | `tools`, `labels` | `source_field`, `calibration_field`, `color_mode`, `point_size`, `max_points`, `lod`, `point_budget`, `min_screen_size`, `max_loaded_nodes`, `mpr`, `slab_thickness`, `default_box_height`, `fit_box_height`, `min_annotations`, `max_annotations` | 3D point cloud annotation with oriented cuboids, points, polylines, and per-point segments | `examples/spatial/kitti-cuboids/config.yaml` |
| `speech_transcript` | (none beyond name/description) | `segments_key`, `audio_key`, `error_types`, `allow_correction`, `turns_key`, `speaker_key`, `text_key` | Aligned-transcript speech-error annotation: per-segment ASR/TTS error tags + correction | `examples/agent-traces/speech-transcript/config.yaml` |
| `table_grid` | (none beyond name/description) | `image_key`, `rows_key`, `cols_key`, `default_rows`, `default_cols`, `roles` | Table-cell structure annotation: rows x cols grid + per-cell role (header/data/empty) | `examples/agent-traces/table-grid/config.yaml` |
| `temporal_grounding` | (none beyond name/description) | `video_key`, `events_key`, `duration` | Video temporal grounding: mark gold event intervals with live IoU vs predicted | `examples/agent-traces/temporal-grounding/config.yaml` |
| `text` | (none beyond name/description) | `label_requirement`, `placeholder`, `rows`, `labels`, `multiline`, `textarea`, `cols`, `min_chars`, `show_char_count`, `collapsible`, `target_schema`, `display_config`, `allow_paste` | Free-form text input | `examples/classification/text-box/config.yaml` |
| `text_edit` | (none beyond name/description) | `source_field`, `show_diff`, `show_edit_distance`, `allow_reset` | Inline text editing with diff tracking for post-editing and correction tasks | `examples/classification/text-edit/config.yaml` |
| `tiered_annotation` | `tiers`, `source_field` | `media_type`, `tier_height`, `show_tier_labels`, `collapsed_tiers`, `zoom_enabled`, `playback_rate_control`, `overview_height`, `transcript_field`, `transcript_tier`, `audio_key`, `turns_key`, `speaker_key`, `text_key` | Hierarchical multi-tier annotation for audio/video (ELAN-style) | `examples/audio/tiered-annotation/config.yaml` |
| `tool_call_review` | (none beyond name/description) | `steps_key`, `verdict_options` | Per-tool-call correctness review (right tool / args / ordering) | `examples/agent-traces/tool-call-review/config.yaml` |
| `tool_contention` | (none beyond name/description) | `calls_key`, `agent_key`, `resource_key`, `contention_labels` | Tool/resource-contention timeline: per-agent lanes + shared-resource collision classification | `examples/agent-traces/tool-contention/config.yaml` |
| `trajectory_edit` | (none beyond name/description) | `steps_key`, `step_text_key`, `editable_fields`, `show_diff`, `show_edit_distance`, `allow_reset`, `require_reason_on_edit`, `edit_final_answer`, `final_answer_key` | Per-step trajectory correction/editing for SFT/DPO training data | `examples/agent-traces/trajectory-correction/config.yaml` |
| `trajectory_eval` | (none beyond name/description) | `steps_key`, `step_text_key`, `correctness_options`, `error_types`, `severities`, `show_score`, `max_score` | Per-step trajectory evaluation with error taxonomy and severity scoring | `examples/agent-traces/trajectory-evaluation/config.yaml` |
| `tree_annotation` | (none beyond name/description) | `node_scheme`, `path_selection`, `branch_comparison` | Annotation of conversation tree nodes with path selection | `examples/span/conversation-tree/config.yaml` |
| `triage` | (none beyond name/description) | `accept_label`, `reject_label`, `skip_label`, `auto_advance`, `show_progress`, `accept_key`, `reject_key`, `skip_key` | Binary accept/reject triage for rapid data curation | `examples/advanced/triage/config.yaml` |
| `vas` | (none beyond name/description) | `left_label`, `right_label`, `min_value`, `max_value`, `show_value`, `precision` | Continuous visual analog scale for fine-grained magnitude estimation | `examples/classification/vas/config.yaml` |
| `video` | `video_path` | `autoplay`, `loop`, `muted`, `controls`, `custom_css`, `fallback_text`, `additional_sources` | Video player display | `examples/video/video-player/config.yaml` |
| `video_annotation` | `labels` | `mode`, `segment_schemes`, `min_segments`, `max_segments`, `timeline_height`, `overview_height`, `zoom_enabled`, `playback_rate_control`, `frame_stepping`, `show_timecode`, `video_fps`, `tracking_options`, `ai_support`, `source_field` | Video annotation with temporal segments, frame classification, keyframes, and object tracking | `examples/video/video-frame-annotation/config.yaml` |
| `voice_interaction` | (none beyond name/description) | `turns_key`, `audio_key`, `speaker_key`, `user_speakers`, `overlap_labels`, `rating_scale`, `text_key` | Voice/full-duplex turn-taking: dual-track timeline + barge-in/overlap classification | `examples/agent-traces/voice-interaction/config.yaml` |

## Label Structure

Labels in annotation schemes can be either simple strings or structured objects.
Both forms are supported across radio, multiselect, span, ranking, and other label-based types.

### Simple String Labels

```yaml
labels:
  - "Positive"
  - "Negative"
  - "Neutral"
```

### Structured Label Objects

```yaml
labels:
  - name: positive            # Internal identifier (used in annotations)
    text: "Positive Sentiment" # Display text shown to annotators
    tooltip: "Select if the text expresses a positive opinion"
    key_value: "p"             # Keyboard shortcut
    abbreviation: "POS"        # Short form for compact displays (e.g., span labels)
    color: "#4CAF50"           # Custom color for this label
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Internal identifier used in stored annotations |
| `text` | No | Display text (defaults to a humanized `name` if omitted). `label` and `displayed_label` are accepted spellings of the same thing; `displayed_label` wins, then `text`, then `label` |
| `tooltip` | No | Help text shown on hover |
| `key_value` | No | Single-key keyboard shortcut for this label |
| `abbreviation` | No | Short text for compact display (span overlays) |
| `color` | No | CSS color for label-specific styling |

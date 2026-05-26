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
- [Advanced Features](#advanced-features)
- [UI & Layout](#ui-layout)
- [Content](#content)
- [Annotation Features](#annotation-features)
- [Media](#media)
- [External Integrations](#external-integrations)
- [Debug / Logging](#debug-logging)
- [Agent](#agent)
- [Assignment & Sessions](#assignment-sessions)
- [Annotation Types](#annotation-types)
- [Label Structure](#label-structure)

## Core / Required

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `item_properties` | Yes | object | `category_key`, `id_key`, `kwargs`, `text_key` |
| `data_files` | Yes |  |  |
| `task_dir` | Yes |  |  |
| `output_annotation_dir` | Yes |  |  |
| `output_annotation_format` |  |  |  |
| `annotation_task_name` | Yes |  |  |
| `task_description` |  |  |  |
| `annotation_task_description` |  |  |  |

## Data Sources

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `data_directory` |  |  |  |
| `data_directory_encoding` |  |  |  |
| `data_sources` |  |  |  |
| `data_cache` |  | object | `enabled`, `max_size_mb`, `ttl_seconds` |
| `watch_data_directory` |  | boolean |  |
| `watch_poll_interval` |  |  |  |
| `partial_loading` |  |  |  |

## Annotation

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `annotation_schemes` |  |  |  |
| `phases` |  |  |  |

## Authentication / Login

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `authentication` |  | object | `allow_local_login`, `allowed_domain`, `allowed_domains`, `allowed_org`, `auto_register`, `database_url`, `method`, `providers`, `user_config_path`, `user_identity_field` |
| `login` |  | object | `auto_redirect_delay`, `auto_redirect_on_completion`, `type`, `url_argument` |
| `user_config` |  | object | `allow_all_users`, `users` |
| `require_password` |  | boolean |  |
| `require_no_password` |  | boolean |  |
| `secret_key` |  |  |  |

## Server

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `server` |  | object | `debug`, `host`, `port` |
| `port` |  |  |  |
| `host` |  |  |  |
| `customjs` |  | boolean |  |
| `customjs_hostname` |  |  |  |
| `site_dir` |  |  |  |
| `site_file` |  |  |  |
| `persist_sessions` |  | boolean |  |
| `session_lifetime_days` |  |  |  |
| `base_html_template` |  |  |  |

## Quality Control

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `attention_checks` |  | object | `enabled`, `failure_handling`, `frequency`, `items_file`, `min_response_time`, `probability` |
| `gold_standards` |  | object | `accuracy`, `auto_promote`, `enabled`, `frequency`, `items_file`, `mode` |
| `gold_standards_file` |  |  |  |
| `pre_annotation` |  | object | `agreement_metrics`, `allow_modification`, `enabled`, `field`, `highlight_low_confidence`, `predictions_file`, `show_confidence` |
| `agreement_metrics` |  | object | `enabled`, `min_overlap`, `refresh_interval` |
| `quality_control` |  |  |  |

## AI Support

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `ai_support` |  | object | `ai_config`, `ai_config_file`, `cache_config`, `enabled`, `endpoint_type`, `features`, `option_highlighting` |
| `chat_support` |  | object | `ai_config`, `enabled`, `endpoint_type`, `ui` |

## Advanced Features

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `training` |  | object | `annotation_schemes`, `data_file`, `enabled`, `failure_action`, `feedback`, `passing_criteria` |
| `active_learning` |  | object | `annotation_routing`, `bald_params`, `calibrate_probabilities`, `classifier`, `classifier_params`, `cold_start_strategy`, `confidence_method`, `database`, `enabled`, `hybrid_weights`, `icl_ensemble_params`, `llm`, `max_instances_to_reorder`, `min_annotations_per_instance`, `min_instances_for_training`, `model_persistence`, `query_strategy`, `random_sample_percent`, `resolution_strategy`, `routing_thresholds`, `schema_names`, `update_frequency`, `use_icl_ensemble`, `vectorizer`, `vectorizer_params` |
| `category_assignment` |  | object | `category_key`, `dynamic`, `enabled`, `fallback`, `qualification` |
| `diversity_ordering` |  | object | `auto_clusters`, `batch_size`, `cache_dir`, `enabled`, `items_per_cluster`, `model_name`, `num_clusters`, `prefill_count`, `preserve_visited`, `recluster_threshold`, `trigger_ai_prefetch` |
| `diversity_config` |  |  |  |
| `embedding_visualization` |  | object | `embedding_model`, `enabled`, `image_embedding_model`, `include_all_annotated`, `label_source`, `sample_size`, `umap` |
| `adjudication` |  | object | `adjudicator_users`, `agreement_threshold`, `enabled`, `error_taxonomy`, `fast_decision_warning_ms`, `min_annotations`, `output_subdir`, `require_confidence`, `require_notes_on_override`, `show_agreement_scores`, `show_all_items`, `show_annotator_names`, `show_timing_data`, `similarity` |
| `database` |  | object | `connection_string`, `database`, `host`, `password`, `pool_size`, `pool_timeout`, `port`, `type`, `username` |
| `bws_config` |  | object | `min_item_appearances`, `num_tuples`, `scoring`, `seed`, `tuple_size` |
| `ibws_config` |  | object | `max_rounds`, `scoring_method`, `seed`, `tuple_size`, `tuples_per_item_per_round` |
| `mace` |  | object | `enabled`, `min_annotations_per_item`, `min_items`, `num_iters`, `num_restarts`, `trigger_every_n` |
| `icl_labeling` |  |  |  |
| `llm_labeling` |  |  |  |

## UI & Layout

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `ui` |  |  |  |
| `ui_config` |  |  |  |
| `layout` |  | object | `breakpoints`, `grid`, `groups`, `order`, `styling` |
| `instance_display` |  | object | `fields`, `layout`, `resizable` |
| `format_handling` |  | object | `default_format`, `enabled`, `pdf`, `spreadsheet` |
| `ui_language` |  | object | `adjudicate`, `audio_to_annotate`, `choose_username_placeholder`, `cite_us`, `codebook`, `continue_button`, `create_password_placeholder`, `error_heading`, `forgot_password`, `go_button`, `html_dir`, `html_lang`, `in_progress_badge`, `instructions_heading`, `labeled_badge`, `loading`, `login_subtitle_password`, `login_subtitle_username`, `login_title`, `logout`, `next_button`, `not_labeled_badge`, `or_divider`, `password_label`, `powered_by`, `previous_button`, `progress_label`, `register_button`, `register_tab`, `retry_button`, `sign_in_button`, `sign_in_tab`, `sign_in_with`, `submit_button`, `text_to_annotate`, `username_label`, `username_placeholder`, `video_to_annotate` |
| `base_css` |  |  |  |
| `ui_debug` |  |  |  |
| `hide_navbar` |  |  |  |
| `task_layout` |  |  |  |

## Content

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `annotation_instructions` |  |  |  |
| `annotation_codebook_url` |  |  |  |
| `custom_footer_html` |  |  |  |
| `header_file` |  |  |  |
| `header_logo` |  |  |  |

## Annotation Features

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `keyword_highlight_settings` |  |  |  |
| `keyword_highlights_file` |  |  |  |
| `highlight_linebreaks` |  | boolean |  |
| `list_as_text` |  | object | `alternating_shading`, `horizontal`, `text_list_prefix_type` |
| `jumping_to_id_disabled` |  | boolean |  |
| `horizontal_key_bindings` |  |  |  |
| `completion_code` |  |  |  |
| `allow_phase_back_navigation` |  |  |  |
| `require_fully_annotated` |  | boolean |  |
| `export_include_phase_data` |  |  |  |
| `export_annotation_format` |  |  |  |
| `auto_export_interval` |  |  |  |

## Media

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `audio_annotation` |  | object | `client_fallback_max_duration`, `waveform_cache_dir`, `waveform_cache_max_size`, `waveform_look_ahead` |
| `spectrogram` |  |  |  |
| `media_directory` |  |  |  |
| `default_video_fps` |  |  |  |

## External Integrations

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `mturk` |  |  |  |
| `prolific` |  | object | `completion_code`, `config_file_path`, `max_concurrent_sessions`, `sandbox_mode`, `study_id`, `token`, `workload_checker_period` |
| `webhooks` |  | object | `enabled`, `endpoints` |
| `trace_ingestion` |  | object | `api_key`, `enabled`, `notify_annotators`, `sources` |
| `huggingface_backup` |  |  |  |

## Debug / Logging

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `debug` |  |  |  |
| `debug_phase` |  |  |  |
| `server_debug` |  |  |  |
| `verbose` |  |  |  |
| `very_verbose` |  |  |  |
| `debug_log` |  |  |  |

## Agent

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `live_agent` |  |  |  |
| `live_coding_agent` |  |  |  |
| `agent_proxy` |  |  |  |

## Assignment & Sessions

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `random_seed` |  | integer |  |
| `max_annotations_per_user` |  | integer |  |
| `max_annotations_per_item` |  | integer |  |
| `num_annotators_per_item` |  | integer |  |
| `min_annotators_per_instance` |  | integer |  |
| `solo_mode` |  | object | `batches`, `enabled`, `instance_selection`, `labeling_models`, `revision_models`, `state_dir`, `thresholds`, `uncertainty` |
| `admin_api_key` |  |  |  |
| `alert_time_each_instance` |  | integer |  |
| `assignment_strategy` |  | string (one of: random, fixed_order, active_learning, llm_confidence, max_diversity, least_annotated, category_based, diversity_clustering) |  |
| `reclaim_stale_assignments` |  |  |  |
| `instance_reclaim` |  |  |  |
| `max_session_seconds` |  | integer |  |
| `env_substitution` |  |  |  |

## Annotation Types

All supported `annotation_type` values and their required/optional fields.
Set via `annotation_schemes[].annotation_type` in your config.

| Type | Required Fields | Optional Fields | Description |
|------|----------------|-----------------|-------------|
| `audio_annotation` | (none beyond name/description) | `mode`, `labels`, `segment_schemes`, `min_segments`, `max_segments`, ... | Audio segmentation and annotation with waveform visualization |
| `bws` | (none beyond name/description) | `best_description`, `worst_description`, `tuple_size`, `sequential_key_binding`, `label_requirement` | Best-Worst Scaling: select the best and worst item from a set |
| `card_sort` | (none beyond name/description) | `mode`, `groups`, `items_field`, `allow_empty_groups`, `allow_multiple` | Drag-and-drop card sorting into predefined or user-created groups |
| `code_review` | (none beyond name/description) | `comment_categories`, `verdict_options`, `file_rating_dimensions` | GitHub PR-style code review with inline comments and file ratings |
| `confidence` | (none beyond name/description) | `target_schema`, `scale_type`, `scale_points`, `labels`, `min_value`, ... | Confidence rating meta-annotation for any primary annotation |
| `conjoint` | (none beyond name/description) | `profiles_per_set`, `attributes`, `show_none_option`, `profiles_field` | Discrete choice conjoint analysis with side-by-side profile comparison |
| `constant_sum` | `labels` | `total_points`, `min_per_item`, `input_type` | Allocate a fixed budget of points across categories |
| `coreference` | `span_schema` | `entity_types`, `allow_singletons`, `visual_display` | Coreference chain annotation for grouping mentions of the same entity |
| `error_span` | `error_types` | `severities`, `show_score`, `max_score` | MQM-style error span annotation with typed severity for quality evaluation |
| `event_annotation` | `event_types`, `span_schema` | `visual_display` | N-ary event annotation with triggers and typed arguments |
| `extractive_qa` | (none beyond name/description) | `question_field`, `passage_field`, `allow_unanswerable`, `highlight_color` | SQuAD-style extractive question answering with answer span highlighting |
| `hierarchical_multiselect` | `taxonomy` | `auto_select_children`, `auto_select_parent`, `show_search`, `max_selections` | Hierarchical tree-structured multi-label selection |
| `image_annotation` | `tools`, `labels` | `zoom_enabled`, `pan_enabled`, `min_annotations`, `max_annotations`, `freeform_brush_size`, ... | Image annotation with bounding boxes, polygons, freeform drawing, and landmarks |
| `likert` | `min_label`, `max_label`, `size` | `label_requirement` | Likert scale rating |
| `multirate` | `options`, `labels` | `label_requirement` | Rate multiple items on a scale |
| `multiselect` | `labels` | `display_config`, `label_requirement`, `sequential_key_binding`, `video_as_label`, `has_free_response`, ... | Multiple-choice checkbox selection |
| `number` | (none beyond name/description) | `min`, `max`, `step`, `label_requirement` | Numeric input field |
| `pairwise` | (none beyond name/description) | `mode`, `items_key`, `items`, `show_labels`, `labels`, ... | Pairwise comparison of two items (binary selection or scale rating) |
| `process_reward` | (none beyond name/description) | `steps_key`, `step_text_key`, `mode` | Binary per-step process reward signals for PRM training |
| `pure_display` | (none beyond name/description) | `labels`, `allow_html` | Display-only content (instructions, headers) |
| `radio` | `labels` | `horizontal`, `label_requirement`, `sequential_key_binding`, `has_free_response`, `option_randomization`, ... | Single-choice radio button selection |
| `range_slider` | (none beyond name/description) | `min_value`, `max_value`, `step`, `left_label`, `right_label`, ... | Dual-thumb slider for selecting an acceptable range |
| `ranking` | `labels` | `allow_ties` | Drag-and-drop ranking of items by preference or relevance |
| `rubric_eval` | `criteria` | `scale_points`, `scale_labels`, `show_overall` | Multi-criteria rubric evaluation grid for LLM and text quality assessment |
| `select` | `labels` | `label_requirement`, `option_randomization`, `dynamic_options`, `dynamic_options_field` | Dropdown selection |
| `semantic_differential` | `pairs` | `scale_points` | Bipolar adjective scales for measuring connotative meaning |
| `slider` | `min_value`, `max_value`, `starting_value` | `step`, `label_requirement` | Slider for selecting a value in a range |
| `soft_label` | `labels` | `total`, `min_per_label`, `show_distribution_chart` | Probability distribution across labels via constrained sliders |
| `span` | `labels` | `sequential_key_binding`, `bad_text_label`, `title`, `allow_discontinuous`, `entity_linking`, ... | Text span annotation/highlighting with optional entity linking to knowledge bases |
| `span_link` | `link_types`, `span_schema` | `visual_display` | Create relationships/links between spans (e.g., PERSON works_for ORGANIZATION) |
| `text` | (none beyond name/description) | `label_requirement`, `placeholder`, `rows` | Free-form text input |
| `text_edit` | (none beyond name/description) | `source_field`, `show_diff`, `show_edit_distance`, `allow_reset` | Inline text editing with diff tracking for post-editing and correction tasks |
| `tiered_annotation` | `tiers`, `source_field` | `media_type`, `tier_height`, `show_tier_labels`, `collapsed_tiers`, `zoom_enabled`, ... | Hierarchical multi-tier annotation for audio/video (ELAN-style) |
| `trajectory_eval` | (none beyond name/description) | `steps_key`, `step_text_key`, `correctness_options`, `error_types`, `severities`, ... | Per-step trajectory evaluation with error taxonomy and severity scoring |
| `tree_annotation` | (none beyond name/description) | `node_scheme`, `path_selection`, `branch_comparison` | Annotation of conversation tree nodes with path selection |
| `triage` | (none beyond name/description) | `accept_label`, `reject_label`, `skip_label`, `auto_advance`, `show_progress`, ... | Binary accept/reject triage for rapid data curation |
| `vas` | (none beyond name/description) | `left_label`, `right_label`, `min_value`, `max_value`, `show_value` | Continuous visual analog scale for fine-grained magnitude estimation |
| `video` | `video_path` | `autoplay`, `loop`, `muted`, `controls`, `custom_css`, ... | Video player display |
| `video_annotation` | (none beyond name/description) | `mode`, `labels`, `segment_schemes`, `min_segments`, `max_segments`, ... | Video annotation with temporal segments, frame classification, keyframes, and object tracking |

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
| `text` | No | Display text (defaults to `name` if omitted) |
| `tooltip` | No | Help text shown on hover |
| `key_value` | No | Single-key keyboard shortcut for this label |
| `abbreviation` | No | Short text for compact display (span overlays) |
| `color` | No | CSS color for label-specific styling |

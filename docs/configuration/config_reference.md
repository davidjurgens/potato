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
- [Other](#other)
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
| `rbac` |  | object | `enabled`, `roles`, `sso_role_mapping`, `user_role_assignments` |
| `user_roles` |  |  |  |

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

## Qualitative Coding (QDA)

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `qda_mode` |  | object | `codebook`, `enabled`, `memos` |
| `codebook` |  | object | `enabled`, `mode` |
| `codebook_mode` |  |  |  |
| `codebook_invivo_key` |  |  |  |
| `annotation_ui` |  | object | `memos`, `visibility` |
| `cases` |  | object | `attributes`, `auto_detect`, `enabled`, `key` |
| `search` |  | object | `annotator_claim`, `backend`, `enabled`, `max_instances` |

## Advanced Features

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `training` |  | object | `allow_retry`, `annotation_schemes`, `data_file`, `enabled`, `failure_action`, `feedback`, `passing_criteria` |
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
| `psychometrics` |  | object | `confidence_threshold`, `cost_per_judgment`, `discrimination_flag_threshold`, `enabled`, `min_annotators_per_item`, `min_observations`, `refit_interval`, `schema` |
| `boundary_probing` |  | object | `ai_support`, `debounce_ms`, `enabled`, `include_invariance`, `precomputed_key`, `probes_per_item`, `rationale_on_flip`, `schema`, `sources` |
| `event_template` |  | object | `allow_annotator_create`, `enabled`, `name`, `seed_events`, `slots` |
| `corpus_map` |  | object | `build_on_start`, `cluster_labeling`, `clustering`, `embedding_model`, `enabled`, `knn`, `sample_size`, `umap` |
| `rooms` |  | object | `enabled`, `max_members`, `persist_votes`, `poll_interval_ms`, `schema`, `who_can_create` |
| `truth_serum` |  | object | `enabled`, `min_annotators`, `question`, `schema` |
| `thinkaloud` |  | object | `chunk_seconds`, `enabled`, `fillers`, `language`, `model`, `require_spoken_label`, `schema`, `stems`, `stt` |
| `pocket` |  | object | `auto_redirect`, `batch_size`, `enabled` |
| `analytics` |  | object | `pricing`, `thresholds` |
| `annotator_dashboard` |  | object | `enabled`, `show_active_annotators`, `show_personal_progress`, `show_project_progress` |
| `keystroke_logging` |  | object | `classify_paste_source`, `detection`, `disclose_to_annotators`, `disclosure_text`, `enabled`, `exclude_schemas`, `fidelity`, `flush_interval_ms`, `idle_session_ms`, `include_schemas`, `pause_thresholds_ms`, `store_events` |
| `annotation_telemetry` |  | object | `detection`, `disclose_to_annotators`, `disclosure_text`, `enabled`, `exclude_schemas`, `fidelity`, `flush_interval_ms`, `idle_ms`, `include_schemas`, `store_events` |

## UI & Layout

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `ui` |  |  |  |
| `ui_config` |  |  |  |
| `layout` |  | object | `breakpoints`, `grid`, `groups`, `order`, `styling` |
| `instance_display` |  | object | `fields`, `layout`, `resizable` |
| `format_handling` |  | object | `default_format`, `enabled`, `pdf`, `spreadsheet` |
| `ui_language` |  | object | `_base`, `adjudicate`, `admin_btn_computing`, `admin_btn_generate_scores`, `admin_btn_reload`, `admin_btn_save_changes`, `admin_err_annotators`, `admin_err_behavioral`, `admin_err_config`, `admin_err_crowdsourcing`, `admin_err_instances`, `admin_err_mace_load`, `admin_err_mace_trigger`, `admin_err_overview`, `admin_err_questions`, `admin_filter_all`, `admin_filter_completed`, `admin_filter_incomplete`, `admin_hint_unlimited`, `admin_label_assignment_strategy`, `admin_label_max_per_item`, `admin_label_max_per_user`, `admin_login_help`, `admin_login_key_label`, `admin_login_key_placeholder`, `admin_login_submit`, `admin_login_title`, `admin_mace_predicted_help`, `admin_mace_run_predictions`, `admin_mode_badge`, `admin_ok_config_saved`, `admin_opt_color_mace`, `admin_opt_color_majority`, `admin_opt_per_page`, `admin_opt_scoring_counting`, `admin_opt_strat_active_learning`, `admin_opt_strat_fixed_order`, `admin_opt_strat_least_annotated`, `admin_opt_strat_llm_confidence`, `admin_opt_strat_max_diversity`, `admin_opt_strat_random`, `admin_order_asc`, `admin_order_desc`, `admin_page_title`, `admin_section_ai_usage`, `admin_section_bws_scores`, `admin_section_competence`, `admin_section_predicted_labels`, `admin_section_quality`, `admin_section_system_config`, `admin_section_system_info`, `admin_sort_annotations`, `admin_sort_avg_time`, `admin_sort_completion`, `admin_sort_disagreement`, `admin_sort_id`, `admin_tab_annotators`, `admin_tab_behavioral`, `admin_tab_bws`, `admin_tab_configuration`, `admin_tab_crowdsourcing`, `admin_tab_datasets`, `admin_tab_embeddings`, `admin_tab_instances`, `admin_tab_mace`, `admin_tab_overview`, `admin_tab_questions`, `admin_th_ai_accept_rate`, `admin_th_ai_requests`, `admin_th_annotations`, `admin_th_annotator`, `admin_th_annotators`, `admin_th_appearances`, `admin_th_assignment_id`, `admin_th_avg_time`, `admin_th_avg_time_per_annotation`, `admin_th_avg_time_s`, `admin_th_best_count`, `admin_th_changes`, `admin_th_competence`, `admin_th_completion`, `admin_th_completion_pct`, `admin_th_disagreement`, `admin_th_instance`, `admin_th_instance_id`, `admin_th_instances`, `admin_th_interactions`, `admin_th_item_id`, `admin_th_last_activity`, `admin_th_max_instances`, `admin_th_most_frequent_label`, `admin_th_num_ai_used`, `admin_th_phase`, `admin_th_predicted_label`, `admin_th_rank`, `admin_th_reliability`, `admin_th_score`, `admin_th_session_id`, `admin_th_speed`, `admin_th_speed_per_hour`, `admin_th_status`, `admin_th_suspicion`, `admin_th_text`, `admin_th_text_preview`, `admin_th_time`, `admin_th_uncertainty`, `admin_th_user_id`, `admin_th_worker_id`, `admin_th_working_time`, `admin_th_worst_count`, `arena_empty`, `arena_enter_prompt`, `arena_error_prefix`, `arena_export`, `arena_export_title`, `arena_failed`, `arena_heading`, `arena_lb_note`, `arena_leaderboard_heading`, `arena_lede`, `arena_models_label`, `arena_ms`, `arena_no_dpo_pairs`, `arena_page_title`, `arena_pick_as_best`, `arena_picked`, `arena_prompt_heading`, `arena_prompt_placeholder`, `arena_responses_heading`, `arena_run`, `arena_running`, `arena_sent_to`, `arena_th_bt`, `arena_th_comparisons`, `arena_th_elo`, `arena_th_model`, `arena_th_win_rate`, `arena_th_wins`, `audio_to_annotate`, `automation_actions_error`, `automation_actions_ok`, `automation_actions_skipped`, `automation_activity`, `automation_col_action`, `automation_col_actions`, `automation_col_detail`, `automation_col_enabled`, `automation_col_item`, `automation_col_rule`, `automation_col_sample_rate`, `automation_col_status`, `automation_configured_rules`, `automation_heading`, `automation_items_processed`, `automation_latest`, `automation_lede_1`, `automation_lede_2`, `automation_lede_3`, `automation_no`, `automation_no_actions`, `automation_no_rules`, `automation_page_title`, `automation_recent_outcomes`, `automation_reload`, `automation_rules_fired`, `automation_snapshot_title`, `automation_yes`, `catalog_all_placeholder`, `catalog_anchor_label`, `catalog_anchor_placeholder`, `catalog_build_index`, `catalog_clusters_label`, `catalog_discover_button`, `catalog_discover_desc`, `catalog_discover_heading`, `catalog_embeddings_warn_1`, `catalog_embeddings_warn_2`, `catalog_heading`, `catalog_index_heading`, `catalog_items_indexed`, `catalog_lede_1`, `catalog_lede_2`, `catalog_lede_3`, `catalog_lede_slices`, `catalog_lede_what`, `catalog_more_traces_suffix`, `catalog_no_matches`, `catalog_no_slices`, `catalog_page_title`, `catalog_prompt_curate_prefix`, `catalog_prompt_curate_suffix`, `catalog_query_text_label`, `catalog_query_text_placeholder`, `catalog_resolve_button`, `catalog_save_slice_button`, `catalog_search_button`, `catalog_search_heading`, `catalog_slice_name_label`, `catalog_slice_query_label`, `catalog_slice_query_placeholder`, `catalog_slice_threshold_label`, `catalog_slices_heading`, `catalog_status_building`, `catalog_status_candidate_modes`, `catalog_status_clustering`, `catalog_status_curating`, `catalog_status_failed`, `catalog_status_imported_mid`, `catalog_status_imported_prefix`, `catalog_status_imported_suffix`, `catalog_status_indexed_prefix`, `catalog_status_indexed_suffix`, `catalog_status_matching_instances`, `catalog_status_name_required`, `catalog_status_results_suffix`, `catalog_status_saved`, `catalog_status_searching`, `catalog_th_actions`, `catalog_th_instance`, `catalog_th_query_anchor`, `catalog_th_similarity`, `catalog_th_slice`, `catalog_th_threshold`, `catalog_threshold_label`, `catalog_to_dataset_button`, `catalog_topk_label`, `catalog_traces_suffix`, `catalog_unlabeled`, `choose_username_placeholder`, `cite_us`, `codebook`, `continue_button`, `create_password_placeholder`, `dash_assigned_completed`, `dash_back_to_annotating`, `dash_error`, `dash_items_started_pct`, `dash_loading`, `dash_no_items_assigned`, `dash_no_items_project`, `dash_project_progress`, `dash_readonly`, `dash_stat_active_annotators`, `dash_stat_annotated`, `dash_stat_annotations`, `dash_stat_assigned`, `dash_stat_complete`, `dash_stat_items_started`, `dash_stat_total_items`, `dash_subtitle`, `dash_your_progress`, `datasets_annotation_process`, `datasets_assignment_active`, `datasets_assignment_paused`, `datasets_col_cmp`, `datasets_col_created`, `datasets_col_dataset`, `datasets_col_examples`, `datasets_col_experiment`, `datasets_col_scores`, `datasets_col_version`, `datasets_compare_selected`, `datasets_create_dataset_btn`, `datasets_created`, `datasets_creating`, `datasets_dataset_label`, `datasets_datasets_heading`, `datasets_description_label`, `datasets_done`, `datasets_evaluators_label`, `datasets_example_label`, `datasets_examples_label`, `datasets_experiments_heading`, `datasets_failed`, `datasets_heading`, `datasets_lede`, `datasets_llm_judge_note`, `datasets_loading_status`, `datasets_name_hint`, `datasets_name_label`, `datasets_new_dataset`, `datasets_no_datasets`, `datasets_no_experiments`, `datasets_optional_placeholder`, `datasets_page_title`, `datasets_pause_assignment`, `datasets_pick_dataset_evaluator`, `datasets_resume_assignment`, `datasets_run_btn`, `datasets_run_experiment`, `datasets_running`, `datasets_select_dataset`, `datasets_select_label`, `datasets_stat_annotated`, `datasets_stat_annotators`, `datasets_stat_datasets`, `datasets_stat_experiments`, `datasets_stat_ingested`, `datasets_stat_instances`, `datasets_stat_multi_annotated`, `datasets_stat_remaining`, `datasets_status_unavailable`, `datasets_version_label`, `datasets_versions_label`, `dsdetail_back_link`, `dsdetail_col_created`, `dsdetail_col_examples`, `dsdetail_col_experiment`, `dsdetail_col_id`, `dsdetail_col_inputs`, `dsdetail_col_note`, `dsdetail_col_reference`, `dsdetail_col_scores`, `dsdetail_col_split`, `dsdetail_col_tags`, `dsdetail_col_version`, `dsdetail_examples_heading`, `dsdetail_examples_subtitle`, `dsdetail_experiments_heading`, `dsdetail_export_dpo`, `dsdetail_export_dpo_title`, `dsdetail_export_sft`, `dsdetail_export_sft_title`, `dsdetail_import_instances`, `dsdetail_import_instances_title`, `dsdetail_import_traces`, `dsdetail_import_traces_title`, `dsdetail_include_annotations`, `dsdetail_no_examples`, `dsdetail_no_experiments`, `dsdetail_no_versions`, `dsdetail_status_import_failed`, `dsdetail_status_imported`, `dsdetail_status_imported_suffix`, `dsdetail_status_importing`, `dsdetail_tag_button`, `dsdetail_tag_input_label`, `dsdetail_tag_placeholder`, `dsdetail_versions_heading`, `error_heading`, `evalanalytics_alerts_heading`, `evalanalytics_col_avg_latency`, `evalanalytics_col_cost`, `evalanalytics_col_errors`, `evalanalytics_col_model`, `evalanalytics_col_tokens`, `evalanalytics_col_traces`, `evalanalytics_empty`, `evalanalytics_lede_after`, `evalanalytics_lede_before`, `evalanalytics_lede_tail`, `evalanalytics_permodel_aria`, `evalanalytics_permodel_heading`, `evalanalytics_stat_avg_latency`, `evalanalytics_stat_error_rate`, `evalanalytics_stat_p95_latency`, `evalanalytics_stat_total_cost`, `evalanalytics_stat_total_tokens`, `evalanalytics_stat_traces`, `evalanalytics_title`, `expcompare_back_link`, `expcompare_baseline`, `expcompare_ci_label`, `expcompare_col_metric`, `expcompare_empty`, `expcompare_heading`, `expcompare_lede_part1`, `expcompare_lede_part2`, `expcompare_lede_strong`, `expcompare_not_significant`, `expcompare_page_title`, `expcompare_row_examples`, `expcompare_sig_title`, `expcompare_significant`, `forgot_password`, `go_button`, `html_dir`, `html_lang`, `iaa_admin_dashboard`, `iaa_agreement`, `iaa_annotators`, `iaa_at_cap`, `iaa_band_fair`, `iaa_band_moderate`, `iaa_band_poor`, `iaa_band_strong`, `iaa_band_substantial`, `iaa_band_weak`, `iaa_empty_state`, `iaa_fully_aligned_items`, `iaa_items`, `iaa_meta_scored`, `iaa_na`, `iaa_overlap_sample`, `iaa_per_item_breakdown`, `iaa_scale_correlation_label`, `iaa_scale_correlation_note`, `iaa_scale_coverage_label`, `iaa_scale_coverage_note`, `iaa_scale_distribution_label`, `iaa_scale_distribution_note`, `iaa_scale_kappa_label`, `iaa_scale_lower_label`, `iaa_scale_lower_note`, `iaa_scale_raw_label`, `iaa_scale_raw_note`, `iaa_scale_span_label`, `iaa_scale_span_note_post`, `iaa_scale_span_note_pre`, `iaa_sweep_headline`, `iaa_sweep_note`, `iaa_sweep_title`, `iaa_th_annotators`, `iaa_th_cap`, `iaa_th_instance`, `iaa_th_metric`, `iaa_th_value`, `iaa_title`, `iaa_title_overlap_sample`, `in_progress_badge`, `instructions_heading`, `integrity_annotators_suffix`, `integrity_col_annotator`, `integrity_col_ca_score`, `integrity_col_flags`, `integrity_col_items`, `integrity_col_llm_alignment`, `integrity_col_residual`, `integrity_col_suspicion`, `integrity_correlated_agreement`, `integrity_heading`, `integrity_lede`, `integrity_lede_ca_desc`, `integrity_lede_residual_desc`, `integrity_lede_with_low`, `integrity_lede_without_ground_truth`, `integrity_llm_alignment`, `integrity_llm_labels_available`, `integrity_no_annotations`, `integrity_no_llm_labels`, `integrity_page_title`, `integrity_residual`, `judge_above`, `judge_agreement`, `judge_autocalibrate`, `judge_autocalibrate_intro_1`, `judge_autocalibrate_intro_2`, `judge_autocalibrate_intro_3`, `judge_autocalibrate_intro_4`, `judge_autocalibrate_intro_5`, `judge_bias_robustness`, `judge_chars`, `judge_cohens_kappa`, `judge_col_conf`, `judge_col_human`, `judge_col_instance`, `judge_col_judge`, `judge_col_reasoning`, `judge_compared_n`, `judge_confusion_caption`, `judge_confusion_caption_2`, `judge_confusion_label`, `judge_corrected`, `judge_current_paren`, `judge_current_prompt_version`, `judge_disagreements`, `judge_empty_1`, `judge_empty_2`, `judge_empty_3`, `judge_eval_cards`, `judge_eval_cards_intro`, `judge_heading`, `judge_human_vs_judge`, `judge_intro`, `judge_length_bias`, `judge_mean_kappa`, `judge_mean_kappa_drift`, `judge_over_versions`, `judge_page_title`, `judge_predictions`, `judge_prompt_versions`, `jump_next_unannotated`, `jump_prev_unannotated`, `labeled_badge`, `loading`, `login_subtitle_password`, `login_subtitle_username`, `login_title`, `logout`, `next_button`, `not_labeled_badge`, `or_divider`, `password_label`, `powered_by`, `previous_button`, `progress_label`, `register_button`, `register_tab`, `retry_button`, `sign_in_button`, `sign_in_tab`, `sign_in_with`, `submit_button`, `text_to_annotate`, `triage_col_annotations`, `triage_col_assigned`, `triage_col_instance`, `triage_col_priority`, `triage_col_reason`, `triage_empty_queue`, `triage_flagged`, `triage_heading`, `triage_intro_before`, `triage_intro_served`, `triage_intro_signal`, `triage_items_remaining`, `triage_no`, `triage_not_enabled_after`, `triage_not_enabled_before`, `triage_not_enabled_rank`, `triage_page_title`, `triage_priority_label`, `triage_summary_aria`, `triage_table_caption`, `triage_yes`, `username_label`, `username_placeholder`, `video_to_annotate` |
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
| `prolific` |  | object | `completion_code`, `config_file_path`, `max_concurrent_sessions`, `sandbox_mode`, `study_id`, `token`, `workload_checker`, `workload_checker_period` |
| `webhooks` |  | object | `enabled`, `endpoints` |
| `trace_ingestion` |  | object | `api_key`, `enabled`, `notify_annotators`, `sources` |
| `huggingface_backup` |  |  |  |
| `crowdsourcing` |  |  |  |

## Publishing & Export

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `publish` |  |  |  |
| `dataset_metadata` |  |  |  |

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

## Agent Evaluation Suite

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `datasets` |  | object | `enabled`, `storage` |
| `automation` |  | object | `enabled`, `rules` |
| `curation` |  | object | `embed_on_ingest`, `enabled`, `model_name`, `text_key` |
| `arena` |  | object | `enabled`, `models` |
| `judge_alignment` |  | object | `ai_support`, `enabled`, `few_shot`, `inline`, `schemas` |
| `judge_calibration` |  | object | `calibration`, `enabled`, `fraction`, `human`, `k_samples`, `max_items`, `models`, `output`, `prompt`, `sampling`, `schemas`, `state_dir` |
| `cot_segmentation` |  | object | `llm_max_chars`, `markers`, `max_steps`, `min_step_chars`, `sentences_per_step`, `source_key`, `strategy`, `target_key` |

## Workflow & Phases

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `surveyflow` |  |  |  |
| `prestudy` |  |  |  |
| `triage` |  | object | `default_priority`, `enabled`, `invert_signal`, `order`, `rules`, `show_badge`, `signal_field` |
| `review_mode` |  | object | `advance_on`, `auto_advance`, `delay_ms`, `enabled` |
| `review_workflow` |  | object | `auto_enroll`, `enabled`, `reviewers`, `routing` |

## Assignment & Sessions

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `random_seed` |  | integer |  |
| `max_annotations_per_user` |  | integer |  |
| `max_annotations_per_item` |  | integer |  |
| `num_annotators_per_item` |  |  |  |
| `min_annotators_per_instance` |  | integer |  |
| `solo_mode` |  | object | `batches`, `confidence_routing`, `confusion_analysis`, `edge_case_rules`, `embedding`, `enabled`, `instance_selection`, `labeling_functions`, `labeling_models`, `prompt_optimization`, `refinement_loop`, `revision_models`, `state_dir`, `thresholds`, `uncertainty` |
| `admin_api_key` |  |  |  |
| `alert_time_each_instance` |  | integer |  |
| `assignment_strategy` |  | string (one of: random, fixed_order, active_learning, llm_confidence, max_diversity, least_annotated, category_based, diversity_clustering, batch, priority, psychometric) |  |
| `reclaim_stale_assignments` |  |  |  |
| `instance_reclaim` |  |  |  |
| `max_session_seconds` |  | integer |  |
| `env_substitution` |  |  |  |
| `automatic_assignment` |  |  |  |
| `batch_assignment` |  | object | `annotator_key`, `auto_assign_annotators`, `groups` |
| `per_annotator_quota` |  |  |  |
| `scheme_sets` |  |  |  |
| `sessions` |  | object | `attributes`, `enabled`, `key` |

## Other

Recognized keys not yet sorted into a category above. They are valid configuration; the grouping simply has not caught up.

| Key | Required | Type | Sub-keys |
|-----|----------|------|----------|
| `export_include_annotation_changes` |  |  |  |
| `item_store` |  | object | `backend`, `cache_size`, `path` |

## Annotation Types

All supported `annotation_type` values and their required/optional fields.
Set via `annotation_schemes[].annotation_type` in your config.

| Type | Required Fields | Optional Fields | Description |
|------|----------------|-----------------|-------------|
| `agent_interaction_graph` | (none beyond name/description) | `steps_key`, `agent_key` | Clickable agent-interaction graph: mark critical-path nodes + flag problematic edges |
| `agent_scorecard` | (none beyond name/description) | `steps_key`, `agent_key`, `agents`, `agent_dimensions`, `team_dimensions`, ... | Per-agent + per-team scorecard with optional milestones (MultiAgentBench-style) |
| `audio_annotation` | (none beyond name/description) | `mode`, `labels`, `segment_schemes`, `min_segments`, `max_segments`, ... | Audio segmentation and annotation with waveform visualization |
| `bws` | (none beyond name/description) | `best_description`, `worst_description`, `tuple_size`, `sequential_key_binding`, `label_requirement` | Best-Worst Scaling: select the best and worst item from a set |
| `card_sort` | (none beyond name/description) | `mode`, `groups`, `items_field`, `allow_empty_groups`, `allow_multiple` | Drag-and-drop card sorting into predefined or user-created groups |
| `code_review` | (none beyond name/description) | `comment_categories`, `verdict_options`, `file_rating_dimensions` | GitHub PR-style code review with inline comments and file ratings |
| `confidence` | (none beyond name/description) | `target_schema`, `scale_type`, `scale_points`, `labels`, `min_value`, ... | Confidence rating meta-annotation for any primary annotation |
| `conjoint` | (none beyond name/description) | `profiles_per_set`, `attributes`, `show_none_option`, `profiles_field` | Discrete choice conjoint analysis with side-by-side profile comparison |
| `consensus_tracking` | (none beyond name/description) | `turns_key`, `acts`, `linked_acts`, `hint` | Tag discussion acts per turn (proposal/agreement/disagreement/decision/concession) with cross-turn links to referenced proposals |
| `constant_sum` | `labels` | `total_points`, `min_per_item`, `input_type` | Allocate a fixed budget of points across categories |
| `context_attribution` | (none beyond name/description) | `turns_key`, `acts`, `linked_acts`, `hint` | Tag how each turn uses earlier context (used correctly / hallucinated / ignored) with links to the source turn |
| `coreference` | `span_schema` | `entity_types`, `allow_singletons`, `visual_display` | Coreference chain annotation for grouping mentions of the same entity |
| `emergent_behavior` | (none beyond name/description) | `steps_key`, `agent_key`, `behaviors`, `allow_note` | Cross-lane emergent-behavior tagging: mark turn-sets for collusion/groupthink/cascade/role-drift |
| `episode_annotation` | (none beyond name/description) | `source_field`, `episode_field`, `layers`, `phases`, `outcomes`, ... | Embodied robot episode: synchronized video streams and time-series lanes with phase, outcome and dense-reward annotation |
| `error_span` | `error_types` | `severities`, `show_score`, `max_score` | MQM-style error span annotation with typed severity for quality evaluation |
| `event_annotation` | `event_types`, `span_schema` | `visual_display` | N-ary event annotation with triggers and typed arguments |
| `extractive_qa` | (none beyond name/description) | `question_field`, `passage_field`, `allow_unanswerable`, `highlight_color` | SQuAD-style extractive question answering with answer span highlighting |
| `failure_attribution` | (none beyond name/description) | `steps_key`, `agent_key`, `agents` | Multi-agent failure attribution: responsible agent + decisive step + reason |
| `grounding_eval` | (none beyond name/description) | `region_type`, `expression_source`, `expressions_field`, `caption_field`, `predictions_field`, ... | Grounding evaluation: bind referring expressions to image regions or points, with an explicit not-present answer |
| `gui_trajectory` | (none beyond name/description) | `steps_key`, `screenshot_key`, `action_key`, `coord_space`, `verdict_options` | Computer-use/GUI agent step review: per-step screenshot + action correctness + click grounding |
| `handoff_review` | (none beyond name/description) | `steps_key`, `agent_key`, `flags`, `quality_scale` | Annotate agent-to-agent handoffs: inter-agent misalignment flags + quality |
| `hierarchical_multiselect` | `taxonomy` | `auto_select_children`, `auto_select_parent`, `show_search`, `max_selections` | Hierarchical tree-structured multi-label selection |
| `image_annotation` | `tools`, `labels` | `zoom_enabled`, `pan_enabled`, `min_annotations`, `max_annotations`, `freeform_brush_size`, ... | Image annotation with bounding boxes, polygons, freeform drawing, and landmarks |
| `likert` | `min_label`, `max_label`, `size` | `label_requirement` | Likert scale rating |
| `multi_document_event` | `slots` | `allow_annotator_create`, `template_name` | Cross-document event annotation: template slots filled with evidence from many documents |
| `multimodal_reasoning` | (none beyond name/description) | `steps_key`, `type_key`, `verdict_options` | Interleaved text/image/tool reasoning trace: per-step coherence + visual-hallucination rating |
| `multirate` | `options`, `labels` | `label_requirement` | Rate multiple items on a scale |
| `multiselect` | `labels` | `display_config`, `label_requirement`, `sequential_key_binding`, `video_as_label`, `has_free_response`, ... | Multiple-choice checkbox selection |
| `number` | (none beyond name/description) | `min`, `max`, `step`, `label_requirement` | Numeric input field |
| `pairwise` | (none beyond name/description) | `mode`, `items_key`, `items`, `show_labels`, `labels`, ... | Pairwise comparison of two items (binary selection or scale rating) |
| `process_reward` | (none beyond name/description) | `steps_key`, `step_text_key`, `mode`, `allow_neutral`, `inline_with_trace` | Per-step process reward signals for PRM training |
| `pure_display` | (none beyond name/description) | `labels`, `allow_html` | Display-only content (instructions, headers) |
| `radio` | `labels` | `horizontal`, `label_requirement`, `sequential_key_binding`, `has_free_response`, `option_randomization`, ... | Single-choice radio button selection |
| `range_slider` | (none beyond name/description) | `min_value`, `max_value`, `step`, `left_label`, `right_label`, ... | Dual-thumb slider for selecting an acceptable range |
| `ranking` | `labels` | `allow_ties` | Drag-and-drop ranking of items by preference or relevance |
| `region_caption` | (none beyond name/description) | `placeholder`, `min_length`, `max_length`, `require_all`, `agreement_distance` | Region captioning: a free-text description per region drawn on the image, with caption agreement over matched regions |
| `rollout_evaluation` | (none beyond name/description) | `streams`, `manifest_field`, `prompt_field`, `intervention_field`, `intervention_time_field`, ... | World-model rollout evaluation: frame-locked video panels with temporal violation localization, preference and counterfactual plausibility |
| `rubric_eval` | `criteria` | `scale_points`, `scale_labels`, `show_overall` | Multi-criteria rubric evaluation grid for LLM and text quality assessment |
| `select` | `labels` | `label_requirement`, `option_randomization`, `dynamic_options`, `dynamic_options_field` | Dropdown selection |
| `semantic_differential` | `pairs` | `scale_points` | Bipolar adjective scales for measuring connotative meaning |
| `slider` | `min_value`, `max_value`, `starting_value` | `step`, `label_requirement` | Slider for selecting a value in a range |
| `soft_label` | `labels` | `total`, `min_per_label`, `show_distribution_chart` | Probability distribution across labels via constrained sliders |
| `span` | `labels` | `sequential_key_binding`, `bad_text_label`, `title`, `allow_discontinuous`, `entity_linking`, ... | Text span annotation/highlighting with optional entity linking to knowledge bases |
| `span_link` | `link_types`, `span_schema` | `visual_display` | Create relationships/links between spans (e.g., PERSON works_for ORGANIZATION) |
| `spatial_annotation` | `tools`, `labels` | `source_field`, `calibration_field`, `color_mode`, `point_size`, `max_points`, ... | 3D point cloud annotation with oriented cuboids, points, polylines, and per-point segments |
| `speech_transcript` | (none beyond name/description) | `segments_key`, `audio_key`, `error_types`, `allow_correction` | Aligned-transcript speech-error annotation: per-segment ASR/TTS error tags + correction |
| `table_grid` | (none beyond name/description) | `image_key`, `rows_key`, `cols_key`, `default_rows`, `default_cols`, ... | Table-cell structure annotation: rows x cols grid + per-cell role (header/data/empty) |
| `temporal_grounding` | (none beyond name/description) | `video_key`, `events_key`, `duration` | Video temporal grounding: mark gold event intervals with live IoU vs predicted |
| `text` | (none beyond name/description) | `label_requirement`, `placeholder`, `rows` | Free-form text input |
| `text_edit` | (none beyond name/description) | `source_field`, `show_diff`, `show_edit_distance`, `allow_reset` | Inline text editing with diff tracking for post-editing and correction tasks |
| `tiered_annotation` | `tiers`, `source_field` | `media_type`, `tier_height`, `show_tier_labels`, `collapsed_tiers`, `zoom_enabled`, ... | Hierarchical multi-tier annotation for audio/video (ELAN-style) |
| `tool_call_review` | (none beyond name/description) | `steps_key`, `verdict_options` | Per-tool-call correctness review (right tool / args / ordering) |
| `tool_contention` | (none beyond name/description) | `calls_key`, `agent_key`, `resource_key`, `contention_labels` | Tool/resource-contention timeline: per-agent lanes + shared-resource collision classification |
| `trajectory_edit` | (none beyond name/description) | `steps_key`, `step_text_key`, `editable_fields`, `show_diff`, `show_edit_distance`, ... | Per-step trajectory correction/editing for SFT/DPO training data |
| `trajectory_eval` | (none beyond name/description) | `steps_key`, `step_text_key`, `correctness_options`, `error_types`, `severities`, ... | Per-step trajectory evaluation with error taxonomy and severity scoring |
| `tree_annotation` | (none beyond name/description) | `node_scheme`, `path_selection`, `branch_comparison` | Annotation of conversation tree nodes with path selection |
| `triage` | (none beyond name/description) | `accept_label`, `reject_label`, `skip_label`, `auto_advance`, `show_progress`, ... | Binary accept/reject triage for rapid data curation |
| `vas` | (none beyond name/description) | `left_label`, `right_label`, `min_value`, `max_value`, `show_value` | Continuous visual analog scale for fine-grained magnitude estimation |
| `video` | `video_path` | `autoplay`, `loop`, `muted`, `controls`, `custom_css`, ... | Video player display |
| `video_annotation` | (none beyond name/description) | `mode`, `labels`, `segment_schemes`, `min_segments`, `max_segments`, ... | Video annotation with temporal segments, frame classification, keyframes, and object tracking |
| `voice_interaction` | (none beyond name/description) | `turns_key`, `audio_key`, `speaker_key`, `user_speakers`, `overlap_labels`, ... | Voice/full-duplex turn-taking: dual-track timeline + barge-in/overlap classification |

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

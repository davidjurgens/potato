"""Bundled UI-language catalog loading and resolution.

Potato localizes its interface through a single flat ``ui_lang`` dict that a
Flask context processor injects into every template (see
``flask_server.py`` -> ``inject_template_context``). Historically the only way
to translate the UI was to hand-write a full ``ui_language:`` dict inline in a
project's config YAML. This module adds *bundled* translation catalogs so a
user can simply write ``ui_language: es`` and get a complete localized UI.

Resolution is layered, lowest precedence first:

    English defaults  <  bundled catalog (by code)  <  inline per-key overrides

which keeps the legacy inline-dict form a strict subset of the new behavior
(fully backward compatible).

Accepted ``ui_language`` config shapes:

* ``"es"``                              -> load ``potato/i18n/es.yaml``
* ``{"next_button": "Weiter", ...}``    -> legacy: English defaults + these keys
* ``{"_base": "es", "next_button": ...}`` -> defaults + es catalog + overrides

All failure modes degrade gracefully to English and only ever ``warning`` —
never raise — so a bad language code can never take down a deployment.
"""

import re
from functools import lru_cache
from pathlib import Path

import yaml

from potato.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# English UI string defaults — the single source of truth for the key universe.
#
# The Flask context processor merges these under an optional bundled catalog and
# inline overrides. The config whitelist and the catalog key-filter are BOTH
# derived from these keys (see config_module.KNOWN_CONFIG_KEYS['ui_language'] and
# ``_ui_language_whitelist`` below), so adding a localizable string is a
# one-line change here — no separate whitelist edit needed.
# ---------------------------------------------------------------------------
UI_LANG_DEFAULTS = {
    # Navigation & controls
    'next_button': 'Next',
    'previous_button': 'Previous',
    'submit_button': 'Submit',
    'go_button': 'Go',
    'retry_button': 'Retry',
    'logout': 'Logout',
    'jump_prev_unannotated': 'Previous unannotated',
    'jump_next_unannotated': 'Next unannotated',
    # Status indicators
    'labeled_badge': 'Labeled',
    'in_progress_badge': 'In Progress',
    'not_labeled_badge': 'Not labeled',
    'progress_label': 'Progress',
    'loading': 'Loading annotation interface...',
    'error_heading': 'Error',
    # Annotation interface
    'adjudicate': 'Adjudicate',
    'codebook': 'Codebook',
    'instructions_heading': 'Instructions',
    'text_to_annotate': 'Text to Annotate:',
    'video_to_annotate': 'Video to Annotate:',
    'audio_to_annotate': 'Audio to Annotate:',
    # Login / registration page
    'login_title': 'Annotation Platform',
    'login_subtitle_password': 'Sign in to continue',
    'login_subtitle_username': 'Enter your username to continue',
    'sign_in_tab': 'Sign In',
    'register_tab': 'Register',
    'username_label': 'Username',
    'password_label': 'Password',
    'sign_in_button': 'Sign In',
    'continue_button': 'Continue',
    'register_button': 'Register',
    'forgot_password': 'Forgot Password?',
    'username_placeholder': 'Enter your username',
    'choose_username_placeholder': 'Choose a username',
    'create_password_placeholder': 'Create a password',
    'sign_in_with': 'Sign in with',
    'or_divider': 'or',
    # Footer
    'powered_by': 'Powered by',
    'cite_us': 'Cite Us',
    # Annotator progress dashboard (annotator_dashboard.html)
    'dash_subtitle': 'Your annotation progress',
    'dash_your_progress': 'Your progress',
    'dash_project_progress': 'Project progress',
    'dash_stat_annotated': 'Annotated',
    'dash_stat_assigned': 'Assigned',
    'dash_stat_complete': 'Complete',
    'dash_stat_total_items': 'Total items',
    'dash_stat_items_started': 'Items started',
    'dash_stat_annotations': 'Annotations',
    'dash_stat_active_annotators': 'Active annotators',
    'dash_loading': 'Loading…',
    'dash_error': 'Could not load progress right now.',
    'dash_back_to_annotating': 'Back to annotating',
    'dash_readonly': 'Read-only view',
    # {n}/{total}/{started}/{pct} are substituted client-side
    'dash_no_items_assigned': 'No items assigned to you yet',
    'dash_assigned_completed': '{n} of {total} assigned items completed',
    'dash_no_items_project': 'No items in this project yet',
    'dash_items_started_pct': '{started} of {total} items started ({pct}%)',
    # Admin dashboard (admin.html, admin_login.html)
    'admin_mode_badge': 'Admin Mode',
    'admin_page_title': 'Admin Dashboard',
    'admin_tab_overview': 'Overview',
    'admin_tab_annotators': 'Annotators',
    'admin_tab_instances': 'Instances',
    'admin_tab_questions': 'Questions',
    'admin_tab_behavioral': 'Behavioral',
    'admin_tab_crowdsourcing': 'Crowdsourcing',
    'admin_tab_bws': 'BWS Scoring',
    'admin_tab_mace': 'MACE',
    'admin_tab_embeddings': 'Embeddings',
    'admin_tab_datasets': 'Datasets & Experiments',
    'admin_tab_configuration': 'Configuration',
    'admin_section_system_info': 'System Information',
    'admin_section_ai_usage': 'AI Assistance Usage',
    'admin_section_quality': 'Quality Indicators',
    'admin_section_bws_scores': 'BWS Item Scores',
    'admin_section_competence': 'Annotator Competence',
    'admin_err_overview': 'Failed to load overview data',
    'admin_err_annotators': 'Failed to load annotators data',
    'admin_err_instances': 'Failed to load instances data',
    'admin_err_questions': 'Failed to load questions data',
    'admin_err_crowdsourcing': 'Failed to load crowdsourcing data',
    'admin_err_behavioral': 'Failed to load behavioral data',
    'admin_err_mace_load': 'Failed to load MACE data',
    'admin_err_mace_trigger': 'Failed to trigger MACE',
    'admin_err_config': 'Failed to update configuration',
    'admin_ok_config_saved': 'Configuration updated successfully',
    'admin_btn_computing': 'Computing…',
    'admin_btn_generate_scores': 'Generate Scores',
    'admin_login_title': 'Admin Access',
    'admin_login_key_label': 'Admin API key',
    'admin_login_key_placeholder': 'Admin API key',
    'admin_login_submit': 'Access Dashboard',
    'admin_login_help': 'The admin API key is stored in admin_api_key.txt in your task directory.',
    # Admin dashboard — table headers, filters, and config (admin.html body)
    'admin_th_user_id': 'User ID',
    'admin_th_phase': 'Phase',
    'admin_th_annotations': 'Annotations',
    'admin_th_working_time': 'Working Time',
    'admin_th_avg_time_per_annotation': 'Avg Time/Annotation',
    'admin_th_speed_per_hour': 'Speed (per hour)',
    'admin_th_completion_pct': 'Completion %',
    'admin_th_max_instances': 'Max Instances',
    'admin_th_last_activity': 'Last Activity',
    'admin_opt_per_page': '{n} per page',
    'admin_sort_annotations': 'Sort by Annotations',
    'admin_sort_completion': 'Sort by Completion',
    'admin_sort_disagreement': 'Sort by Disagreement',
    'admin_sort_id': 'Sort by ID',
    'admin_sort_avg_time': 'Sort by Avg Time',
    'admin_order_desc': 'Descending',
    'admin_order_asc': 'Ascending',
    'admin_filter_all': 'All Instances',
    'admin_filter_completed': 'Completed Only',
    'admin_filter_incomplete': 'Incomplete Only',
    'admin_th_instance_id': 'Instance ID',
    'admin_th_text_preview': 'Text Preview',
    'admin_th_most_frequent_label': 'Most Frequent Label',
    'admin_th_disagreement': 'Disagreement',
    'admin_th_avg_time': 'Avg Time',
    'admin_th_annotators': 'Annotators',
    'admin_th_num_ai_used': 'Num AI Used',
    'admin_th_instances': 'Instances',
    'admin_th_avg_time_s': 'Avg Time (s)',
    'admin_th_interactions': 'Interactions',
    'admin_th_changes': 'Changes',
    'admin_th_ai_requests': 'AI Requests',
    'admin_th_ai_accept_rate': 'AI Accept Rate',
    'admin_th_suspicion': 'Suspicion',
    'admin_opt_color_mace': 'Color by MACE Labels',
    'admin_opt_color_majority': 'Color by Majority Vote',
    'admin_opt_scoring_counting': 'Counting',
    'admin_th_rank': 'Rank',
    'admin_th_item_id': 'Item ID',
    'admin_th_text': 'Text',
    'admin_th_score': 'Score',
    'admin_th_best_count': 'Best Count',
    'admin_th_worst_count': 'Worst Count',
    'admin_th_appearances': 'Appearances',
    'admin_th_annotator': 'Annotator',
    'admin_th_competence': 'Competence',
    'admin_th_reliability': 'Reliability',
    'admin_section_predicted_labels': 'Predicted Labels',
    'admin_mace_predicted_help': "MACE's best estimate of the true label for each item, weighted by annotator competence.",
    'admin_mace_run_predictions': 'Run MACE to see predictions.',
    'admin_section_system_config': 'System Configuration',
    'admin_label_max_per_user': 'Max Annotations per User',
    'admin_label_max_per_item': 'Max Annotations per Item',
    'admin_hint_unlimited': 'Use -1 for unlimited',
    'admin_label_assignment_strategy': 'Assignment Strategy',
    'admin_opt_strat_random': 'Random',
    'admin_opt_strat_fixed_order': 'Fixed Order',
    'admin_opt_strat_least_annotated': 'Least Annotated',
    'admin_opt_strat_max_diversity': 'Max Diversity',
    'admin_opt_strat_active_learning': 'Active Learning',
    'admin_opt_strat_llm_confidence': 'LLM Confidence',
    'admin_btn_save_changes': 'Save Changes',
    'admin_btn_reload': 'Reload',
    # Admin dashboard — JS-built crowdsourcing/MACE detail tables
    'admin_th_worker_id': 'Worker ID',
    'admin_th_time': 'Time',
    'admin_th_speed': 'Speed',
    'admin_th_completion': 'Completion',
    'admin_th_status': 'Status',
    'admin_th_session_id': 'Session ID',
    'admin_th_assignment_id': 'Assignment ID',
    'admin_th_instance': 'Instance',
    'admin_th_predicted_label': 'Predicted Label',
    'admin_th_uncertainty': 'Uncertainty',
    # Admin sub-pages (templates/admin/*.html)
    'iaa_title': 'Inter-Annotator Agreement',
    'iaa_title_overlap_sample': 'Overlap Sample',
    'iaa_admin_dashboard': 'Admin Dashboard',
    'iaa_overlap_sample': 'Overlap sample',
    'iaa_at_cap': 'at cap.',
    'iaa_meta_scored': 'Each schema is scored with the metrics appropriate to its annotation type.',
    'iaa_empty_state': 'No overlap-sample items have reached their cap yet. Once the sample items have been annotated by the configured number of annotators, IAA will appear here.',
    'iaa_scale_kappa_label': 'κ-family scale (κ, α, γ):',
    'iaa_band_poor': 'poor',
    'iaa_band_fair': 'fair',
    'iaa_band_moderate': 'moderate',
    'iaa_band_substantial': 'substantial',
    'iaa_band_strong': 'strong',
    'iaa_scale_correlation_label': 'Correlation / ICC:',
    'iaa_scale_correlation_note': 'ranges −1 to 1; closer to 1 is stronger agreement.',
    'iaa_scale_raw_label': 'Raw agreement (% agreement, Jaccard):',
    'iaa_scale_raw_note': '0 to 1; no chance correction.',
    'iaa_scale_span_label': 'Span F1 / token κ:',
    'iaa_scale_span_note_pre': '0 to 1 (κ can be negative);',
    'iaa_scale_span_note_post': 'is the conventional reporting metric.',
    'iaa_scale_lower_label': 'MAE / RMSE / Spearman footrule:',
    'iaa_scale_lower_note': 'lower is better; 0 means perfect agreement.',
    'iaa_th_metric': 'Metric',
    'iaa_th_value': 'Value',
    'iaa_na': 'n/a',
    'iaa_band_weak': 'weak',
    'iaa_agreement': 'agreement',
    'iaa_items': 'items',
    'iaa_annotators': 'annotators',
    'iaa_fully_aligned_items': 'fully-aligned items',
    'iaa_per_item_breakdown': 'Per-item breakdown',
    'iaa_th_instance': 'Instance',
    'iaa_th_cap': 'Cap',
    'iaa_th_annotators': 'Annotators',
    'judge_page_title': 'LLM-Judge ↔ Human Alignment',
    'judge_heading': 'LLM-Judge ↔ Human Alignment',
    'judge_intro': "How well does the configured LLM judge agree with human gold labels? Cohen's κ and the confusion matrix are computed over instances that have both a human label and a judge verdict. Inspect disagreements, edit the judge rubric, and re-run to calibrate.",
    'judge_current_prompt_version': 'Current prompt version:',
    'judge_prompt_versions': 'Prompt versions',
    'judge_mean_kappa_drift': 'Mean κ drift:',
    'judge_over_versions': 'over {n} versions',
    'judge_mean_kappa': 'mean κ',
    'judge_predictions': 'prediction(s)',
    'judge_current_paren': '(current)',
    'judge_eval_cards': 'Judge eval cards',
    'judge_bias_robustness': '(bias & robustness)',
    'judge_eval_cards_intro': 'Beyond agreement (κ): does the judge favor longer outputs, is its confidence calibrated, is it order-robust? A portable certificate to ship with the eval.',
    'judge_length_bias': 'length bias',
    'judge_chars': 'chars',
    'judge_autocalibrate': 'Auto-calibrate',
    'judge_autocalibrate_intro_1': 'Close the loop automatically: the instances where a human',
    'judge_corrected': 'corrected',
    'judge_autocalibrate_intro_2': 'the judge (human label ≠ judge label) are its most informative examples.',
    'judge_autocalibrate_intro_3': 'POST to',
    'judge_autocalibrate_intro_4': 'to re-run the judge with those corrections injected as few-shot examples (leakage-guarded — an instance never sees its own correction), creating a new prompt version whose mean κ is compared against the baseline. Optional body:',
    'judge_autocalibrate_intro_5': 'The new version appears in',
    'judge_above': 'above.',
    'judge_empty_1': 'No judge predictions yet. Configure',
    'judge_empty_2': 'and POST to',
    'judge_empty_3': 'to generate verdicts.',
    'judge_cohens_kappa': "Cohen's κ",
    'judge_agreement': 'Agreement',
    'judge_compared_n': 'Compared (n)',
    'judge_disagreements': 'Disagreements',
    'judge_confusion_label': 'Confusion (rows = human, columns = judge)',
    'judge_confusion_caption': 'Confusion matrix for',
    'judge_confusion_caption_2': 'rows are human gold labels, columns are judge labels.',
    'judge_human_vs_judge': 'human ＼ judge',
    'judge_col_instance': 'Instance',
    'judge_col_human': 'Human',
    'judge_col_judge': 'Judge',
    'judge_col_conf': 'Conf.',
    'judge_col_reasoning': 'Judge reasoning',
    'integrity_page_title': 'Annotation integrity',
    'integrity_heading': 'Annotation integrity',
    'integrity_lede': 'Flags annotators who likely echoed an LLM or answered with little effort —',
    'integrity_lede_without_ground_truth': 'without ground truth',
    'integrity_correlated_agreement': 'Correlated Agreement',
    'integrity_lede_ca_desc': "is each annotator's same-item minus cross-item agreement with peers (low ⇒ random/low effort). When reference LLM labels are available,",
    'integrity_llm_alignment': 'LLM alignment',
    'integrity_lede_with_low': 'with low',
    'integrity_residual': 'residual',
    'integrity_lede_residual_desc': '(independent agreement on items where they diverge from the LLM) is the covert-LLM tell. Treat as triage signals to review, not proof.',
    'integrity_no_annotations': 'No annotations to analyze yet.',
    'integrity_col_annotator': 'Annotator',
    'integrity_col_items': 'Items',
    'integrity_col_suspicion': 'Suspicion',
    'integrity_col_ca_score': 'CA score',
    'integrity_col_llm_alignment': 'LLM alignment',
    'integrity_col_residual': 'Residual',
    'integrity_col_flags': 'Flags',
    'integrity_annotators_suffix': 'annotator(s).',
    'integrity_llm_labels_available': 'Reference LLM labels were available (LLM-echo signal active).',
    'integrity_no_llm_labels': 'No reference LLM labels — Correlated-Agreement signal only; run the judge to enable LLM-echo detection.',
    'triage_page_title': 'Triage Queue',
    'triage_heading': 'Triage Queue',
    'triage_intro_before': 'Remaining items ranked by their',
    'triage_priority_label': 'triage priority',
    'triage_intro_signal': 'the quality signal (agent error, negative feedback, low score, or a custom field) assigned at load/ingestion time. With',
    'triage_intro_served': 'annotators are served the highest-priority items first. Ordering:',
    'triage_not_enabled_before': 'Triage is not enabled. Add a',
    'triage_not_enabled_after': 'block to the config (and optionally',
    'triage_not_enabled_rank': 'to rank the queue.',
    'triage_summary_aria': 'Triage summary',
    'triage_items_remaining': 'Items remaining',
    'triage_flagged': 'Flagged',
    'triage_table_caption': 'Items ranked by triage priority, highest first.',
    'triage_col_instance': 'Instance',
    'triage_col_priority': 'Priority',
    'triage_col_reason': 'Reason',
    'triage_col_annotations': 'Annotations',
    'triage_col_assigned': 'Assigned',
    'triage_yes': 'yes',
    'triage_no': 'no',
    'triage_empty_queue': 'No items in the queue.',
    'catalog_page_title': 'Catalog · Semantic Curation',
    'catalog_heading': 'Catalog',
    'catalog_lede_1': 'Find',
    'catalog_lede_what': 'what to review',
    'catalog_lede_2': 'by similarity. Build an embedding index over your items, search for traces like a given query or example, and save',
    'catalog_lede_slices': 'dynamic slices',
    'catalog_lede_3': '— semantic + metadata filters that auto-include new matching traces and can be curated into a dataset.',
    'catalog_embeddings_warn_1': 'Embeddings are unavailable — install',
    'catalog_embeddings_warn_2': '(or configure an embedder) to build the index.',
    'catalog_index_heading': 'Index',
    'catalog_items_indexed': 'item(s) indexed',
    'catalog_build_index': 'Build index',
    'catalog_search_heading': 'Similarity search',
    'catalog_query_text_label': 'Query text',
    'catalog_query_text_placeholder': 'e.g. agent failed to call the tool',
    'catalog_anchor_label': '…or anchor instance id',
    'catalog_anchor_placeholder': 'instance id',
    'catalog_topk_label': 'Top-k',
    'catalog_threshold_label': 'Threshold',
    'catalog_search_button': 'Search',
    'catalog_discover_heading': 'Discover failure modes',
    'catalog_discover_desc': 'Cluster the indexed traces and let the judge propose a candidate failure-mode label per cluster (a project-specific taxonomy you then confirm or edit).',
    'catalog_clusters_label': 'Clusters (k)',
    'catalog_discover_button': 'Discover',
    'catalog_slices_heading': 'Dynamic slices',
    'catalog_slice_name_label': 'Name',
    'catalog_slice_query_label': 'Query',
    'catalog_slice_query_placeholder': 'semantic query (optional)',
    'catalog_slice_threshold_label': 'Threshold',
    'catalog_save_slice_button': 'Save slice',
    'catalog_th_slice': 'Slice',
    'catalog_th_query_anchor': 'Query / anchor',
    'catalog_th_threshold': 'Threshold',
    'catalog_th_actions': 'Actions',
    'catalog_all_placeholder': '(all)',
    'catalog_resolve_button': 'Resolve',
    'catalog_to_dataset_button': '→ Dataset',
    'catalog_no_slices': 'No slices saved yet.',
    'catalog_th_instance': 'Instance',
    'catalog_th_similarity': 'Similarity',
    'catalog_status_building': 'Building…',
    'catalog_status_indexed_prefix': 'Indexed ',
    'catalog_status_indexed_suffix': ' item(s).',
    'catalog_status_failed': 'Failed.',
    'catalog_status_searching': 'Searching…',
    'catalog_status_results_suffix': ' result(s)',
    'catalog_no_matches': 'No matches.',
    'catalog_status_name_required': 'Name required.',
    'catalog_status_saved': 'Saved.',
    'catalog_status_matching_instances': 'matching instance(s)',
    'catalog_prompt_curate_prefix': "Curate slice '",
    'catalog_prompt_curate_suffix': "' into which dataset?",
    'catalog_status_curating': 'Curating…',
    'catalog_status_imported_prefix': 'Imported ',
    'catalog_status_imported_mid': " into '",
    'catalog_status_imported_suffix': "'.",
    'catalog_status_clustering': 'Clustering & labeling…',
    'catalog_status_candidate_modes': 'candidate failure mode(s)',
    'catalog_unlabeled': '(unlabeled — add a code)',
    'catalog_traces_suffix': 'trace(s)',
    'catalog_more_traces_suffix': 'more trace(s)',
    'datasets_page_title': 'Datasets & Experiments',
    'datasets_heading': 'Datasets & Experiments',
    'datasets_lede': 'Versioned collections of evaluation examples and the experiment runs scored against them. Curate examples from traces or annotations, pin a version with a tag, then run evaluators (trajectory match, tool-use, LLM-judge, …) and compare results over time. Storage backend:',
    'datasets_annotation_process': 'Annotation process',
    'datasets_loading_status': 'Loading status…',
    'datasets_new_dataset': 'New dataset',
    'datasets_name_label': 'Name',
    'datasets_name_hint': 'Letters, numbers, hyphens, underscores.',
    'datasets_description_label': 'Description',
    'datasets_optional_placeholder': 'Optional',
    'datasets_create_dataset_btn': 'Create dataset',
    'datasets_run_experiment': 'Run experiment',
    'datasets_dataset_label': 'Dataset',
    'datasets_select_dataset': 'Select a dataset…',
    'datasets_evaluators_label': 'Evaluators',
    'datasets_llm_judge_note': 'LLM-judge evaluators call your configured AI endpoint and may take a while on large datasets.',
    'datasets_run_btn': 'Run',
    'datasets_datasets_heading': 'Datasets',
    'datasets_version_label': 'version',
    'datasets_versions_label': 'version(s)',
    'datasets_example_label': 'example',
    'datasets_examples_label': 'example(s)',
    'datasets_no_datasets': 'No datasets yet. Create one above to get started.',
    'datasets_experiments_heading': 'Experiments',
    'datasets_compare_selected': 'Compare selected',
    'datasets_col_cmp': 'cmp',
    'datasets_col_experiment': 'Experiment',
    'datasets_col_dataset': 'Dataset',
    'datasets_col_version': 'Version',
    'datasets_col_examples': 'Examples',
    'datasets_col_scores': 'Scores',
    'datasets_col_created': 'Created',
    'datasets_select_label': 'Select',
    'datasets_no_experiments': 'No experiments yet. Select a dataset and evaluators above, then Run.',
    'datasets_creating': 'Creating…',
    'datasets_created': 'Created.',
    'datasets_failed': 'Failed.',
    'datasets_pick_dataset_evaluator': 'Pick a dataset and ≥1 evaluator.',
    'datasets_running': 'Running…',
    'datasets_done': 'Done.',
    'datasets_stat_instances': 'Instances',
    'datasets_stat_annotated': 'Annotated',
    'datasets_stat_multi_annotated': '≥2 annotators',
    'datasets_stat_remaining': 'Remaining',
    'datasets_stat_ingested': 'Ingested traces',
    'datasets_stat_annotators': 'Annotators',
    'datasets_stat_datasets': 'Datasets',
    'datasets_stat_experiments': 'Experiments',
    'datasets_assignment_paused': 'Assignment paused',
    'datasets_assignment_active': 'Assignment active',
    'datasets_resume_assignment': 'Resume assignment',
    'datasets_pause_assignment': 'Pause assignment',
    'datasets_status_unavailable': 'Status unavailable.',
    'dsdetail_back_link': 'Datasets & Experiments',
    'dsdetail_export_sft': 'Export SFT',
    'dsdetail_export_sft_title': 'Download SFT fine-tuning data (prompt/completion)',
    'dsdetail_export_dpo': 'Export DPO',
    'dsdetail_export_dpo_title': 'Download DPO preference data (prompt/chosen/rejected)',
    'dsdetail_import_instances': 'Import loaded instances',
    'dsdetail_import_instances_title': "Add the live task's loaded instances as examples",
    'dsdetail_import_traces': 'Import ingested traces',
    'dsdetail_import_traces_title': 'Add only runtime-ingested traces (webhook / Langfuse) as examples',
    'dsdetail_include_annotations': 'include human annotations as references',
    'dsdetail_versions_heading': 'Versions',
    'dsdetail_col_version': 'Version',
    'dsdetail_col_examples': 'Examples',
    'dsdetail_col_note': 'Note',
    'dsdetail_col_created': 'Created',
    'dsdetail_col_tags': 'Tags',
    'dsdetail_tag_placeholder': 'tag…',
    'dsdetail_tag_input_label': 'Tag',
    'dsdetail_tag_button': 'Tag',
    'dsdetail_no_versions': 'No versions yet.',
    'dsdetail_examples_heading': 'Examples',
    'dsdetail_examples_subtitle': '(latest version, showing up to 50)',
    'dsdetail_col_id': 'ID',
    'dsdetail_col_inputs': 'Inputs',
    'dsdetail_col_reference': 'Reference',
    'dsdetail_col_split': 'Split',
    'dsdetail_no_examples': 'No examples in the latest version.',
    'dsdetail_experiments_heading': 'Experiments on this dataset',
    'dsdetail_col_experiment': 'Experiment',
    'dsdetail_col_scores': 'Scores',
    'dsdetail_no_experiments': 'No experiments run on this dataset yet.',
    'dsdetail_status_importing': 'Importing…',
    'dsdetail_status_imported': 'Imported ',
    'dsdetail_status_imported_suffix': ' example(s).',
    'dsdetail_status_import_failed': 'Import failed.',
    'arena_page_title': 'Model Arena',
    'arena_heading': 'Model Arena',
    'arena_lede': "Send one prompt to every configured model side by side, compare the responses, and pick the best — building a Bradley-Terry & Elo leaderboard and exportable DPO preference data. Models are provider-agnostic (any of Potato's LLM endpoints).",
    'arena_prompt_heading': 'Prompt',
    'arena_sent_to': 'Sent to',
    'arena_models_label': 'model(s):',
    'arena_prompt_placeholder': 'Ask the models something…',
    'arena_run': 'Run',
    'arena_responses_heading': 'Responses',
    'arena_leaderboard_heading': 'Leaderboard',
    'arena_export_title': 'Download arena preferences as DPO (chosen/rejected) pairs',
    'arena_export': 'Export DPO',
    'arena_lb_note': 'Ranked by <strong>Bradley-Terry</strong> score (accounts for opponent strength), with <strong>Elo</strong> ratings. Win rate shown for reference.',
    'arena_th_model': 'Model',
    'arena_th_bt': 'BT score',
    'arena_th_elo': 'Elo',
    'arena_th_wins': 'Wins',
    'arena_th_comparisons': 'Comparisons',
    'arena_th_win_rate': 'Win rate',
    'arena_no_dpo_pairs': 'No DPO pairs yet',
    'arena_enter_prompt': 'Enter a prompt.',
    'arena_running': 'Running…',
    'arena_failed': 'Failed.',
    'arena_ms': 'ms',
    'arena_error_prefix': 'Error: ',
    'arena_empty': '(empty)',
    'arena_pick_as_best': 'Pick as best',
    'arena_picked': '✓ Picked',
    'automation_page_title': 'Automation Rules',
    'automation_heading': 'Automation Rules',
    'automation_lede_1': 'Rules run',
    'automation_lede_2': 'over every item entering Potato (loaded or runtime-ingested), closing the production→eval loop. Rules are configured in the',
    'automation_lede_3': "block of your config; this page inspects what's configured and what has fired.",
    'automation_activity': 'Activity',
    'automation_snapshot_title': 'This page is a snapshot from page load',
    'automation_reload': 'Reload to refresh',
    'automation_items_processed': 'Items processed',
    'automation_rules_fired': 'Rules fired',
    'automation_actions_ok': 'Actions ok',
    'automation_actions_error': 'Actions error',
    'automation_actions_skipped': 'Actions skipped',
    'automation_configured_rules': 'Configured rules',
    'automation_col_rule': 'Rule',
    'automation_col_sample_rate': 'Sample rate',
    'automation_col_actions': 'Actions',
    'automation_col_enabled': 'Enabled',
    'automation_yes': 'yes',
    'automation_no': 'no',
    'automation_no_rules': 'No rules configured.',
    'automation_recent_outcomes': 'Recent outcomes',
    'automation_latest': 'latest',
    'automation_col_item': 'Item',
    'automation_col_action': 'Action',
    'automation_col_status': 'Status',
    'automation_col_detail': 'Detail',
    'automation_no_actions': 'No actions have fired yet.',
    'evalanalytics_title': 'Trace analytics',
    'evalanalytics_lede_before': 'Operational metrics aggregated across',
    'evalanalytics_lede_after': 'ingested trace(s): token usage, latency, error rate, and (when pricing is configured) cost. Append',
    'evalanalytics_lede_tail': 'to flag regressions of the latest N traces against the rest.',
    'evalanalytics_empty': 'No ingested traces yet. Send traces via the webhook or the tracing SDK.',
    'evalanalytics_stat_traces': 'Traces',
    'evalanalytics_stat_total_tokens': 'Total tokens',
    'evalanalytics_stat_total_cost': 'Total cost',
    'evalanalytics_stat_error_rate': 'Error rate',
    'evalanalytics_stat_avg_latency': 'Avg latency',
    'evalanalytics_stat_p95_latency': 'p95 latency',
    'evalanalytics_alerts_heading': 'Regression alerts',
    'evalanalytics_permodel_aria': 'Per-model breakdown',
    'evalanalytics_permodel_heading': 'By model',
    'evalanalytics_col_model': 'Model',
    'evalanalytics_col_traces': 'Traces',
    'evalanalytics_col_tokens': 'Tokens',
    'evalanalytics_col_cost': 'Cost',
    'evalanalytics_col_errors': 'Errors',
    'evalanalytics_col_avg_latency': 'Avg latency',
    'expcompare_page_title': 'Compare experiments',
    'expcompare_back_link': 'Datasets & Experiments',
    'expcompare_heading': 'Compare experiments',
    'expcompare_lede_part1': 'Aggregate evaluator scores side by side. The first experiment is the baseline; deltas and the best value per metric are highlighted so regressions stand out. Each delta carries a',
    'expcompare_lede_strong': 'paired-bootstrap',
    'expcompare_lede_part2': 'significance badge and 95% CI — so you can tell a real change from noise.',
    'expcompare_empty': 'Select at least two experiments to compare.',
    'expcompare_col_metric': 'Metric',
    'expcompare_baseline': 'baseline',
    'expcompare_sig_title': 'Paired bootstrap vs baseline',
    'expcompare_significant': 'significant',
    'expcompare_not_significant': 'n.s.',
    'expcompare_ci_label': '95% CI',
    'expcompare_row_examples': 'Examples',
    # Language / direction
    'html_lang': 'en',
    'html_dir': 'ltr',
}

# Catalogs live in potato/i18n/<code>.yaml. This file is potato/server_utils/,
# so the package root is one directory up.
CATALOG_DIR = Path(__file__).resolve().parent.parent / "i18n"

# A language code must look like a BCP-47-ish tag (e.g. "es", "zh", "pt-br").
# This is the *only* gate between a config-supplied string and a filesystem
# path, so it doubles as path-traversal protection — never build a path from an
# unvalidated code.
_CODE_RE = re.compile(r"^[a-z]{2,3}(-[a-z]{2,4})?$")


def _ui_language_whitelist():
    """Return the set of allowed ui_lang keys.

    Derived from ``UI_LANG_DEFAULTS`` — the single source of truth for the key
    universe. ``_base`` is a control key, not a UI string, so it is never a
    valid catalog key.
    """
    return set(UI_LANG_DEFAULTS)


def is_valid_language_code(code) -> bool:
    """True if ``code`` is a syntactically valid, non-traversing language code."""
    return isinstance(code, str) and bool(_CODE_RE.match(code))


@lru_cache(maxsize=None)
def load_catalog(code: str):
    """Load a bundled translation catalog by language code.

    Returns a dict of whitelisted UI strings, or ``None`` if the code is
    invalid, the file is missing, or the file is malformed. Cached because
    catalogs are static package data.
    """
    if not is_valid_language_code(code):
        logger.warning(
            "Ignoring invalid ui_language code %r (expected a code like 'es', "
            "'zh', 'pt-br').", code,
        )
        return None

    path = CATALOG_DIR / f"{code}.yaml"
    if not path.is_file():
        available = ", ".join(sorted(available_language_codes())) or "(none)"
        logger.warning(
            "No bundled translation catalog for ui_language %r "
            "(looked for %s). Falling back to English. Available: %s",
            code, path.name, available,
        )
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.warning(
            "Failed to read translation catalog %s: %s. Falling back to English.",
            path.name, e,
        )
        return None

    if not isinstance(data, dict):
        logger.warning(
            "Translation catalog %s did not parse to a mapping; ignoring it.",
            path.name,
        )
        return None

    # Filter to whitelisted keys so a stale catalog can never inject arbitrary
    # template variables. Drop non-string values defensively.
    whitelist = _ui_language_whitelist()
    catalog = {}
    dropped = []
    for key, value in data.items():
        if key in whitelist and isinstance(value, str):
            catalog[key] = value
        else:
            dropped.append(key)
    if dropped:
        logger.debug(
            "Catalog %s: ignored %d non-whitelisted/non-string key(s): %s",
            path.name, len(dropped), ", ".join(sorted(dropped)),
        )
    return catalog


def available_language_codes():
    """Return the set of language codes with a bundled catalog on disk."""
    if not CATALOG_DIR.is_dir():
        return set()
    return {
        p.stem
        for p in CATALOG_DIR.glob("*.yaml")
        if is_valid_language_code(p.stem)
    }


def resolve_ui_language(ui_lang_config, defaults):
    """Resolve the effective ``ui_lang`` dict from config + English defaults.

    Args:
        ui_lang_config: The raw ``ui_language`` config value — a language-code
            string, a dict (optionally containing ``_base``), or None.
        defaults: The English ``ui_lang_defaults`` dict (the merge base).

    Returns:
        A new dict: ``{**defaults, **catalog, **overrides}``.
    """
    merged = dict(defaults)

    base_code = None
    overrides = {}

    if isinstance(ui_lang_config, str):
        base_code = ui_lang_config.strip() or None
    elif isinstance(ui_lang_config, dict):
        raw_base = ui_lang_config.get("_base")
        if isinstance(raw_base, str):
            base_code = raw_base.strip() or None
        # Everything except the control key is a per-key override.
        overrides = {
            k: v for k, v in ui_lang_config.items() if k != "_base"
        }
    elif ui_lang_config is not None:
        logger.warning(
            "Ignoring ui_language of unexpected type %s; expected a language "
            "code string or a mapping.", type(ui_lang_config).__name__,
        )

    if base_code:
        catalog = load_catalog(base_code)
        if catalog:
            merged.update(catalog)

    merged.update(overrides)
    return merged

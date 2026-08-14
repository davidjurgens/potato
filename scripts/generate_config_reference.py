#!/usr/bin/env python3
"""
Auto-generate a configuration reference from the codebase.

Reads KNOWN_CONFIG_KEYS, the schema registry, and optional field type
definitions to produce a Markdown reference page that stays in sync
with the code.

Usage:
    python scripts/generate_config_reference.py
    # Writes to docs/configuration/config_reference.md
"""

import re
import sys
import os
import unicodedata

# Add project root to path so we can import potato modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from potato.server_utils.config_module import (
    KNOWN_CONFIG_KEYS,
    _OPTIONAL_INT_FIELDS,
    _OPTIONAL_BOOL_FIELDS,
    _VALID_ASSIGNMENT_STRATEGIES,
)
from potato.server_utils.schemas.registry import schema_registry


def slugify(text):
    """
    Build the same heading anchor MkDocs will.

    This has to match Python-Markdown's `toc` slugify exactly, because the
    table-of-contents links generated here point at headings MkDocs renders. An
    ad-hoc version that only substituted separators left punctuation in place,
    so "Qualitative Coding (QDA)" produced `#qualitative-coding-(qda)` while the
    rendered heading id was `qualitative-coding-qda` — a link that silently
    landed readers at the top of the page.
    """
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


# Required top-level fields
REQUIRED_FIELDS = {
    "item_properties", "data_files", "task_dir",
    "output_annotation_dir", "annotation_task_name",
}

# Human-readable category labels for grouping
CATEGORY_ORDER = [
    ("Core / Required", [
        "item_properties", "data_files", "task_dir",
        "output_annotation_dir", "output_annotation_format",
        "annotation_task_name", "task_description", "annotation_task_description",
    ]),
    ("Data Sources", [
        "data_directory", "data_directory_encoding", "data_sources", "data_cache",
        "watch_data_directory", "watch_poll_interval", "partial_loading",
    ]),
    ("Annotation", [
        "annotation_schemes", "phases",
    ]),
    ("Authentication / Login", [
        "authentication", "login", "user_config",
        "require_password", "require_no_password", "secret_key",
        "rbac", "user_roles",
    ]),
    ("Server", [
        "server", "port", "host", "customjs", "customjs_hostname",
        "site_dir", "site_file", "persist_sessions", "session_lifetime_days",
        "base_html_template",
    ]),
    ("Quality Control", [
        "attention_checks", "gold_standards", "gold_standards_file",
        "pre_annotation", "agreement_metrics", "quality_control",
    ]),
    ("AI Support", [
        "ai_support", "chat_support",
    ]),
    ("Qualitative Coding (QDA)", [
        "qda_mode", "codebook", "codebook_mode", "codebook_invivo_key",
        "annotation_ui", "cases", "search",
    ]),
    ("Advanced Features", [
        "training", "active_learning", "category_assignment",
        "diversity_ordering", "diversity_config", "embedding_visualization",
        "adjudication", "database", "bws_config", "ibws_config", "mace",
        "icl_labeling", "llm_labeling",
        "psychometrics", "boundary_probing", "event_template", "corpus_map",
        "rooms", "truth_serum", "thinkaloud", "pocket",
        "analytics", "annotator_dashboard", "keystroke_logging",
        "annotation_telemetry",
    ]),
    ("UI & Layout", [
        "ui", "ui_config", "layout", "instance_display", "format_handling",
        "ui_language", "base_css", "ui_debug", "hide_navbar", "task_layout",
    ]),
    ("Content", [
        "annotation_instructions", "annotation_codebook_url",
        "custom_footer_html", "header_file", "header_logo",
    ]),
    ("Annotation Features", [
        "keyword_highlight_settings", "keyword_highlights_file",
        "highlight_linebreaks", "list_as_text", "jumping_to_id_disabled",
        "horizontal_key_bindings", "completion_code",
        "allow_phase_back_navigation", "require_fully_annotated",
        "export_include_phase_data", "export_annotation_format",
        "auto_export_interval",
    ]),
    ("Media", [
        "audio_annotation", "spectrogram", "media_directory", "default_video_fps",
    ]),
    ("External Integrations", [
        "mturk", "prolific", "webhooks", "trace_ingestion", "huggingface_backup",
        "crowdsourcing",
    ]),
    ("Publishing & Export", [
        "publish", "dataset_metadata",
    ]),
    ("Debug / Logging", [
        "debug", "debug_phase", "server_debug", "verbose", "very_verbose", "debug_log",
    ]),
    ("Agent", [
        "live_agent", "live_coding_agent", "agent_proxy",
    ]),
    ("Agent Evaluation Suite", [
        "datasets", "automation", "curation", "arena",
        "judge_alignment", "judge_calibration", "cot_segmentation",
    ]),
    ("Workflow & Phases", [
        "surveyflow", "prestudy", "triage", "review_mode", "review_workflow",
    ]),
    ("Assignment & Sessions", [
        "random_seed", "max_annotations_per_user", "max_annotations_per_item",
        "num_annotators_per_item", "min_annotators_per_instance",
        "solo_mode", "admin_api_key", "alert_time_each_instance",
        "assignment_strategy", "reclaim_stale_assignments", "instance_reclaim",
        "max_session_seconds", "env_substitution",
        "automatic_assignment", "batch_assignment", "per_annotator_quota",
        "scheme_sets", "sessions",
    ]),
]

# Internal plumbing rather than user-facing configuration: set by the loader, not
# written in a config file. Excluded from the reference and from the completeness
# check in tests/unit/test_config_reference_completeness.py.
INTERNAL_KEYS = {"__config_file__", "config_file", "_bws_pool_items"}


def get_type_hint(key):
    """Get a type hint string for a key based on validation metadata."""
    if key in _OPTIONAL_INT_FIELDS:
        desc, allow_neg = _OPTIONAL_INT_FIELDS[key]
        return "integer"
    if key in _OPTIONAL_BOOL_FIELDS:
        return "boolean"
    if key == "assignment_strategy":
        return f"string (one of: {', '.join(_VALID_ASSIGNMENT_STRATEGIES)})"
    # Infer from KNOWN_CONFIG_KEYS structure
    val = KNOWN_CONFIG_KEYS.get(key)
    if isinstance(val, (set, dict)):
        return "object"
    return ""


def format_subkeys(subkeys):
    """Format sub-keys as a bullet list. Handles both set-valued keys and
    dict-valued keys (KNOWN_CONFIG_KEYS uses dicts when sub-key names are
    known but their own values aren't enumerated, e.g. qda_mode/cases)."""
    if isinstance(subkeys, set):
        return ", ".join(f"`{k}`" for k in sorted(subkeys))
    if isinstance(subkeys, dict):
        return ", ".join(f"`{k}`" for k in sorted(subkeys))
    return ""


def generate_reference():
    lines = []
    lines.append("# Configuration Reference")
    lines.append("")
    lines.append("> **Auto-generated** from the codebase by `scripts/generate_config_reference.py`.")
    lines.append("> Do not edit manually — regenerate with: `python scripts/generate_config_reference.py`")
    lines.append("")
    lines.append("This is a complete reference of all recognized configuration keys in Potato.")
    lines.append("For a tutorial-style guide, see [Configuration Guide](configuration.md).")
    lines.append("")

    # Table of contents
    lines.append("## Table of Contents")
    lines.append("")
    for category, _ in CATEGORY_ORDER:
        anchor = slugify(category)
        lines.append(f"- [{category}](#{anchor})")
    if set(KNOWN_CONFIG_KEYS) - {k for _, keys in CATEGORY_ORDER for k in keys} - INTERNAL_KEYS:
        lines.append("- [Other](#other)")
    lines.append("- [Annotation Types](#annotation-types)")
    lines.append("- [Label Structure](#label-structure)")
    lines.append("")

    # Config key sections
    covered_keys = set()
    for category, keys in CATEGORY_ORDER:
        anchor = slugify(category)
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Key | Required | Type | Sub-keys |")
        lines.append("|-----|----------|------|----------|")
        for key in keys:
            if key not in KNOWN_CONFIG_KEYS:
                continue
            covered_keys.add(key)
            required = "Yes" if key in REQUIRED_FIELDS else ""
            type_hint = get_type_hint(key)
            subkeys_val = KNOWN_CONFIG_KEYS[key]
            subkeys_str = format_subkeys(subkeys_val)
            lines.append(f"| `{key}` | {required} | {type_hint} | {subkeys_str} |")
        lines.append("")

    # Catch-all. CATEGORY_ORDER is hand-maintained, so a newly recognized config
    # key belongs to no category until someone remembers to add it — and this
    # page claims to be complete. Thirty-five keys had drifted out that way,
    # including whole subsystems (rooms, psychometrics, rbac, crowdsourcing,
    # publish). Emitting the remainder here means a new key is merely
    # uncategorized rather than undocumented.
    uncategorized = sorted(
        set(KNOWN_CONFIG_KEYS) - covered_keys - INTERNAL_KEYS
    )
    if uncategorized:
        lines.append("## Other")
        lines.append("")
        lines.append(
            "Recognized keys not yet sorted into a category above. "
            "They are valid configuration; the grouping simply has not caught up."
        )
        lines.append("")
        lines.append("| Key | Required | Type | Sub-keys |")
        lines.append("|-----|----------|------|----------|")
        for key in uncategorized:
            required = "Yes" if key in REQUIRED_FIELDS else ""
            lines.append(
                f"| `{key}` | {required} | {get_type_hint(key)} | "
                f"{format_subkeys(KNOWN_CONFIG_KEYS[key])} |"
            )
        lines.append("")

    # Annotation types section from registry
    lines.append("## Annotation Types")
    lines.append("")
    lines.append("All supported `annotation_type` values and their required/optional fields.")
    lines.append("Set via `annotation_schemes[].annotation_type` in your config.")
    lines.append("")
    lines.append("| Type | Required Fields | Optional Fields | Description |")
    lines.append("|------|----------------|-----------------|-------------|")
    for schema_info in schema_registry.list_schemas():
        name = schema_info["name"]
        req = ", ".join(f"`{f}`" for f in schema_info["required_fields"] if f not in ("name", "description"))
        opt = ", ".join(f"`{f}`" for f in schema_info["optional_fields"][:5])  # Limit for readability
        if len(schema_info["optional_fields"]) > 5:
            opt += ", ..."
        desc = schema_info["description"]
        lines.append(f"| `{name}` | {req or '(none beyond name/description)'} | {opt or '—'} | {desc} |")
    lines.append("")

    # Label structure section
    lines.append("## Label Structure")
    lines.append("")
    lines.append("Labels in annotation schemes can be either simple strings or structured objects.")
    lines.append("Both forms are supported across radio, multiselect, span, ranking, and other label-based types.")
    lines.append("")
    lines.append("### Simple String Labels")
    lines.append("")
    lines.append("```yaml")
    lines.append("labels:")
    lines.append('  - "Positive"')
    lines.append('  - "Negative"')
    lines.append('  - "Neutral"')
    lines.append("```")
    lines.append("")
    lines.append("### Structured Label Objects")
    lines.append("")
    lines.append("```yaml")
    lines.append("labels:")
    lines.append("  - name: positive            # Internal identifier (used in annotations)")
    lines.append('    text: "Positive Sentiment" # Display text shown to annotators')
    lines.append('    tooltip: "Select if the text expresses a positive opinion"')
    lines.append('    key_value: "p"             # Keyboard shortcut')
    lines.append('    abbreviation: "POS"        # Short form for compact displays (e.g., span labels)')
    lines.append('    color: "#4CAF50"           # Custom color for this label')
    lines.append("```")
    lines.append("")
    lines.append("| Field | Required | Description |")
    lines.append("|-------|----------|-------------|")
    lines.append("| `name` | Yes | Internal identifier used in stored annotations |")
    lines.append("| `text` | No | Display text (defaults to `name` if omitted) |")
    lines.append("| `tooltip` | No | Help text shown on hover |")
    lines.append("| `key_value` | No | Single-key keyboard shortcut for this label |")
    lines.append("| `abbreviation` | No | Short text for compact display (span overlays) |")
    lines.append("| `color` | No | CSS color for label-specific styling |")
    lines.append("")

    return "\n".join(lines)


def main():
    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs", "configuration"
    )
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "config_reference.md")

    content = generate_reference()
    with open(output_path, "w") as f:
        f.write(content)

    print(f"Generated config reference: {output_path}")
    print(f"  - {len(KNOWN_CONFIG_KEYS)} config keys documented")
    print(f"  - {len(schema_registry.list_schemas())} annotation types documented")


if __name__ == "__main__":
    main()

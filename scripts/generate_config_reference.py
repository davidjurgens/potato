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


from potato.server_utils.config_key_docs import UNSET, get_key_doc
from potato.server_utils.schema_examples import example_source_for
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

# Human-readable category labels. This list now decides the *order* sections
# print in; which keys land in each comes from CONFIG_KEY_DOCS[key].category,
# falling back to the membership spelled out here for keys the docs table has
# not reached yet. Owning membership in one place is what stops a new key from
# silently drifting into "Other".
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
        "auto_redirect_on_completion", "auto_redirect_delay",
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


_LEGACY_CATEGORY_OF = {
    key: category for category, keys in CATEGORY_ORDER for key in keys
}


def get_type_hint(key):
    """Get a type hint string for a key based on validation metadata."""
    if key in _OPTIONAL_INT_FIELDS:
        return "integer"
    if key in _OPTIONAL_BOOL_FIELDS:
        return "boolean"
    if key == "assignment_strategy":
        return f"string (one of: {', '.join(_VALID_ASSIGNMENT_STRATEGIES)})"
    # The docs table knows the types the two coercion tables above don't cover.
    doc = get_key_doc(key)
    if doc is not None and doc.type != "any":
        # "integer|object" reads better in a table than JSON Schema's list form.
        return doc.type.replace("|", " or ")
    # Infer from KNOWN_CONFIG_KEYS structure
    val = KNOWN_CONFIG_KEYS.get(key)
    if isinstance(val, (set, dict)):
        return "object"
    return ""


def get_summary(key):
    """One-line description of a key, or an empty cell."""
    doc = get_key_doc(key)
    if doc is None:
        return ""
    # Pipes would end the Markdown table cell early.
    return doc.summary.replace("|", "\\|")


def get_default(key):
    """Rendered default for a key, or an empty cell."""
    doc = get_key_doc(key)
    if doc is None or doc.default is UNSET:
        return ""
    if isinstance(doc.default, str):
        # An empty default rendered as an empty code span, which reads as
        # "no default" rather than "the empty string".
        return '`""`' if doc.default == "" else f"`{doc.default}`"
    return f"`{doc.default!r}`"


def category_of(key):
    """Category a key belongs to.

    CONFIG_KEY_DOCS owns this now. CATEGORY_ORDER below is only the print order
    plus the grandfathered membership for keys the docs table has not reached;
    a documented key lands in its declared category without anyone editing two
    lists.
    """
    doc = get_key_doc(key)
    if doc is not None:
        return doc.category
    return _LEGACY_CATEGORY_OF.get(key)


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
    # Ask the same question the "Other" section below asks -- does any key have
    # no category at all -- rather than only consulting CATEGORY_ORDER. A key
    # that gets its category from CONFIG_KEY_DOCS is categorized even though
    # CATEGORY_ORDER has never heard of it, and listing "Other" for those left a
    # table-of-contents link pointing at a section that was never printed.
    if any(category_of(k) is None for k in KNOWN_CONFIG_KEYS if k not in INTERNAL_KEYS):
        lines.append("- [Other](#other)")
    lines.append("- [Annotation Types](#annotation-types)")
    lines.append("- [Label Structure](#label-structure)")
    lines.append("")

    # Config key sections. Membership comes from CONFIG_KEY_DOCS where the key
    # is documented and from CATEGORY_ORDER otherwise; CATEGORY_ORDER decides
    # the order the sections print in either way.
    def row(key):
        required = "Yes" if key in REQUIRED_FIELDS else ""
        return (
            f"| `{key}` | {required} | {get_type_hint(key)} | {get_default(key)} | "
            f"{get_summary(key)} | {format_subkeys(KNOWN_CONFIG_KEYS[key])} |"
        )

    header = "| Key | Required | Type | Default | Description | Sub-keys |"
    divider = "|-----|----------|------|---------|-------------|----------|"

    grouped = {}
    for key in KNOWN_CONFIG_KEYS:
        if key in INTERNAL_KEYS:
            continue
        category = category_of(key)
        if category:
            grouped.setdefault(category, []).append(key)

    covered_keys = set()
    for category, _legacy_keys in CATEGORY_ORDER:
        keys = sorted(grouped.get(category, []))
        if not keys:
            continue
        lines.append(f"## {category}")
        lines.append("")
        lines.append(header)
        lines.append(divider)
        for key in keys:
            covered_keys.add(key)
            lines.append(row(key))
        lines.append("")

    # A documented key may name a category CATEGORY_ORDER does not list.
    for category in sorted(set(grouped) - {c for c, _ in CATEGORY_ORDER}):
        keys = sorted(grouped[category])
        lines.append(f"## {category}")
        lines.append("")
        lines.append(header)
        lines.append(divider)
        for key in keys:
            covered_keys.add(key)
            lines.append(row(key))
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
        lines.append(header)
        lines.append(divider)
        for key in uncategorized:
            lines.append(row(key))
        lines.append("")

    # Annotation types section from registry
    lines.append("## Annotation Types")
    lines.append("")
    lines.append("All supported `annotation_type` values and their required/optional fields.")
    lines.append("Set via `annotation_schemes[].annotation_type` in your config.")
    lines.append("")
    lines.append("| Type | Required Fields | Optional Fields | Description | Example |")
    lines.append("|------|----------------|-----------------|-------------|---------|")
    for schema_info in schema_registry.list_schemas():
        name = schema_info["name"]
        req = ", ".join(f"`{f}`" for f in schema_info["required_fields"] if f not in ("name", "description"))
        # Every optional field, not the first five. The truncated list read as
        # complete, so a field past the cutoff did not exist as far as anyone
        # reading this page — or generating a config from it — could tell.
        opt = ", ".join(f"`{f}`" for f in schema_info["optional_fields"])
        desc = schema_info["description"]
        # The example column is the fastest route from "which type is this?" to
        # a config that actually runs; the path is extracted from the reference
        # table in schemas_and_templates.md, not maintained a second time here.
        source = example_source_for(name)
        example_cell = f"`{source}`" if source else "—"
        lines.append(
            f"| `{name}` | {req or '(none beyond name/description)'} | "
            f"{opt or '—'} | {desc} | {example_cell} |"
        )
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

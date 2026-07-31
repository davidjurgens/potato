"""
Suggesting a starter Potato config from a ConvoKit corpus.

Most ConvoKit corpora already carry annotations — ``conversation_has_personal_attack``
on Conversations Gone Awry, DAMSL ``tag`` on Switchboard, ``Binary`` on the
politeness corpora. Those existing fields are the best available description of
what people annotate on this data, so they make a good first draft of an
annotation task: re-annotation, adjudication, and agreement studies all start from
exactly there.

This module reads the corpus and emits a config whose schemes mirror those fields.
It is opt-in (``--emit-config`` / ``--print-config``) and the output says plainly
at the top that it is a starting point.

Why the types are sampled, not read
-----------------------------------

``index.json`` records a type per field, and it cannot be trusted. In
``conversations-gone-awry-corpus`` the field ``toxicity`` is indexed as
``<class 'int'>`` while its actual values are floats like ``0.078140646`` — a
slider built from the index would have a range of ``0..1`` with integer steps and
be useless. So the index is used only to enumerate fields and to skip binary ones;
the shape of each scheme comes from observing real values.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .items import ItemOptions
from .reader import Corpus

logger = logging.getLogger(__name__)

__all__ = ["SchemeSuggestion", "SuggestOptions", "generate_config", "suggest_schemes"]

#: How many objects to sample when inferring a field's shape.
DEFAULT_SAMPLE_SIZE = 1000

#: At most this many distinct string values still makes a radio.
RADIO_MAX_CARDINALITY = 5

#: Above radio but at or below this makes a dropdown.
SELECT_MAX_CARDINALITY = 12


@dataclass
class SuggestOptions:
    sample_size: int = DEFAULT_SAMPLE_SIZE
    max_categorical: int = SELECT_MAX_CARDINALITY
    include_utterance_meta: bool = True
    include_conversation_meta: bool = True


@dataclass
class SchemeSuggestion:
    """One suggested annotation scheme, plus why it came out that way."""

    scheme: Dict[str, Any]
    source_field: str
    obj_type: str          # "utterance" | "conversation"
    rationale: str
    turn_level: bool = False


@dataclass
class _FieldProfile:
    """What sampling actually observed for one metadata field."""

    name: str
    total: int = 0
    non_null: int = 0
    kinds: Counter = field(default_factory=Counter)
    values: Counter = field(default_factory=Counter)
    numeric_min: Optional[float] = None
    numeric_max: Optional[float] = None
    #: Set when values are unhashable (dict/list) so we never try to count them.
    complex_only: bool = False

    def observe(self, value: Any) -> None:
        self.total += 1
        if value is None:
            self.kinds["null"] += 1
            return
        self.non_null += 1

        if isinstance(value, bool):
            self.kinds["bool"] += 1
            self.values[value] += 1
        elif isinstance(value, (int, float)):
            self.kinds["number"] += 1
            numeric = float(value)
            self.numeric_min = numeric if self.numeric_min is None else min(self.numeric_min, numeric)
            self.numeric_max = numeric if self.numeric_max is None else max(self.numeric_max, numeric)
        elif isinstance(value, str):
            self.kinds["str"] += 1
            if len(self.values) <= 500:      # bounded: some fields are free text
                self.values[value] += 1
        else:
            self.kinds["complex"] += 1
            self.complex_only = True

    @property
    def dominant_kind(self) -> Optional[str]:
        interesting = {k: n for k, n in self.kinds.items() if k != "null"}
        if not interesting:
            return None
        return max(interesting, key=lambda k: interesting[k])


def _profile(
    objects: Iterable[Dict[str, Any]], sample_size: int
) -> Dict[str, _FieldProfile]:
    profiles: Dict[str, _FieldProfile] = {}
    for seen, meta in enumerate(objects):
        if seen >= sample_size:
            break
        if not isinstance(meta, dict):
            continue
        for key, value in meta.items():
            name = str(key)
            profile = profiles.get(name)
            if profile is None:
                profile = profiles[name] = _FieldProfile(name=name)
            profile.observe(value)
    return profiles


def _round_out(low: float, high: float) -> Tuple[float, float]:
    """Widen a numeric range outward to friendly bounds."""
    import math

    if low == high:
        return (min(0.0, low), max(1.0, high))
    span = high - low
    if span <= 1.0:
        return (math.floor(low * 10) / 10, math.ceil(high * 10) / 10)
    return (float(math.floor(low)), float(math.ceil(high)))


def _scheme_for(
    profile: _FieldProfile, obj_type: str, opts: SuggestOptions
) -> Optional[Tuple[Dict[str, Any], str]]:
    """Pick a scheme shape for one profiled field, or explain why we cannot."""
    kind = profile.dominant_kind
    safe_name = profile.name.strip().replace(" ", "_").replace("-", "_")

    if profile.complex_only or kind == "complex":
        return None, f"values are nested structures ({profile.non_null} sampled)"
    if kind is None:
        return None, "every sampled value was null"

    if kind == "bool":
        return (
            {
                "annotation_type": "radio",
                "name": safe_name,
                "description": f"{profile.name}?",
                "labels": ["true", "false"],
            },
            f"boolean over {profile.non_null} sampled values",
        )

    if kind == "number":
        low, high = _round_out(profile.numeric_min or 0.0, profile.numeric_max or 1.0)
        return (
            {
                "annotation_type": "slider",
                "name": safe_name,
                "description": profile.name,
                "min_value": low,
                "max_value": high,
                "starting_value": round((low + high) / 2, 4),
            },
            f"numeric, observed range {profile.numeric_min}..{profile.numeric_max}",
        )

    if kind == "str":
        distinct = len(profile.values)
        if distinct > opts.max_categorical:
            return (
                None,
                f"{distinct} distinct values in a {profile.total}-object sample — "
                "too many for a label list (raise --max-categorical to include it)",
            )
        labels = [v for v, _ in profile.values.most_common()]
        annotation_type = "radio" if distinct <= RADIO_MAX_CARDINALITY else "select"
        return (
            {
                "annotation_type": annotation_type,
                "name": safe_name,
                "description": profile.name,
                "labels": labels,
            },
            f"{distinct} distinct string values in a {profile.total}-object sample",
        )

    return None, f"unhandled value kind '{kind}'"


def suggest_schemes(
    corpus: Corpus,
    item_opts: ItemOptions,
    opts: Optional[SuggestOptions] = None,
) -> Tuple[List[SchemeSuggestion], List[Tuple[str, str, str]]]:
    """Suggest schemes from a corpus's existing metadata.

    Returns ``(suggestions, skipped)`` where ``skipped`` is
    ``(obj_type, field, reason)`` — every skipped field is reported rather than
    silently dropped, so the emitted config can explain the omissions.
    """
    opts = opts or SuggestOptions()
    suggestions: List[SchemeSuggestion] = []
    skipped: List[Tuple[str, str, str]] = []

    # Conversation-level metadata -> instance-level schemes (only meaningful when
    # the item *is* a conversation).
    if opts.include_conversation_meta and item_opts.unit == "conversation":
        profiles = _profile(
            (c.meta for c in corpus.conversations.values()), opts.sample_size
        )
        for name in sorted(profiles):
            if corpus.index.is_binary("conversation", name):
                skipped.append(("conversation", name, "stored in a pickle sidecar"))
                continue
            scheme, rationale = _scheme_for(profiles[name], "conversation", opts)
            if scheme is None:
                skipped.append(("conversation", name, rationale))
                continue
            scheme["sequential_key_binding"] = True
            suggestions.append(
                SchemeSuggestion(scheme, name, "conversation", rationale, turn_level=False)
            )

    if opts.include_utterance_meta:
        profiles = _profile((u.meta for u in corpus.utterances.values()), opts.sample_size)
        for name in sorted(profiles):
            if corpus.index.is_binary("utterance", name):
                skipped.append(("utterance", name, "stored in a pickle sidecar"))
                continue
            scheme, rationale = _scheme_for(profiles[name], "utterance", opts)
            if scheme is None:
                skipped.append(("utterance", name, rationale))
                continue

            if item_opts.unit == "conversation":
                # One item holds many utterances, so this has to bind per turn.
                scheme["turn_level"] = True
                scheme["turn_binding"] = {"field": item_opts.field_name}
                suggestions.append(
                    SchemeSuggestion(scheme, name, "utterance", rationale, turn_level=True)
                )
            else:
                # One item is one utterance, so an instance-level scheme is right.
                scheme["sequential_key_binding"] = True
                suggestions.append(
                    SchemeSuggestion(scheme, name, "utterance", rationale, turn_level=False)
                )

    return suggestions, skipped


# --------------------------------------------------------------------------- #
# YAML emission
# --------------------------------------------------------------------------- #

def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    # Quote anything that could be misread as another YAML type.
    needs_quotes = (
        not text
        or text.strip() != text
        or text[0] in "-?:,[]{}#&*!|>'\"%@`"
        or text.lower() in ("true", "false", "null", "yes", "no", "on", "off", "~")
        or _looks_numeric(text)
        or ": " in text
    )
    if needs_quotes:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _emit_scheme(suggestion: SchemeSuggestion, indent: str = "  ") -> List[str]:
    lines = [
        f"{indent}# from ConvoKit {suggestion.obj_type} metadata "
        f"'{suggestion.source_field}' ({suggestion.rationale})"
    ]
    scheme = suggestion.scheme
    first = True
    for key, value in scheme.items():
        prefix = f"{indent}- " if first else f"{indent}  "
        first = False
        if isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            for entry in value:
                lines.append(f"{indent}    - {_yaml_scalar(entry)}")
        elif isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            for sub_key, sub_value in value.items():
                lines.append(f"{indent}    {sub_key}: {_yaml_scalar(sub_value)}")
        else:
            lines.append(f"{prefix}{key}: {_yaml_scalar(value)}")
    return lines


def generate_config(
    corpus: Corpus,
    item_opts: ItemOptions,
    data_file: str,
    *,
    task_name: Optional[str] = None,
    suggest_opts: Optional[SuggestOptions] = None,
    threaded_display: bool = True,
) -> str:
    """Render a starter ``config.yaml`` for an imported corpus.

    The result is deliberately a *draft*: the schemes mirror whatever the corpus
    already annotates, which is a reasonable place to start and almost never the
    task someone actually wants to run.
    """
    suggestions, skipped = suggest_schemes(corpus, item_opts, suggest_opts)
    has_turn_level = any(s.turn_level for s in suggestions)
    task_name = task_name or f"ConvoKit: {corpus.name}"

    lines: List[str] = [
        "# yaml-language-server: $schema=https://potatoannotator.readthedocs.io/en/latest/schemas/potato-config.schema.json",
        f"# Starter config generated by 'potato convokit' from {corpus.name}.",
        "#",
        "# The annotation schemes below mirror metadata the corpus already carries,",
        "# which makes them a reasonable starting point for re-annotation, adjudication,",
        "# or an agreement study. They are almost certainly NOT the task you want to run",
        "# as-is: rename them, cut the ones you do not need, and write your own.",
        "#",
        f"# Corpus: {corpus.name}"
        + (f" (version {corpus.version})" if corpus.version is not None else ""),
        f"# {len(corpus.utterances)} utterances, {len(corpus.conversations)} conversations, "
        f"{len(corpus.speakers)} speakers",
    ]
    if corpus.legacy:
        lines.append("# Read using the legacy key names (user/root/users.json).")
    if corpus.dropped_meta_fields:
        lines.append(f"# Dropped metadata: {', '.join(sorted(corpus.dropped_meta_fields))}")
    if corpus.skipped_binary_fields:
        lines.append(
            f"# Skipped binary metadata: {', '.join(sorted(corpus.skipped_binary_fields))}"
        )
    lines.append("")
    lines.append(f"annotation_task_name: {_yaml_scalar(task_name)}")
    lines.append("")
    lines.append("data_files:")
    lines.append(f"  - {_yaml_scalar(data_file)}")
    lines.append("")
    lines.append("item_properties:")
    lines.append("  id_key: id")
    lines.append(f"  text_key: {item_opts.text_field}")
    lines.append("")
    lines.append("task_dir: .")
    lines.append("output_annotation_dir: annotation_output")
    lines.append("output_annotation_format: json")
    lines.append("")

    # --- instance display -------------------------------------------------- #
    lines.append("instance_display:")
    lines.append("  layout:")
    lines.append("    direction: vertical")
    lines.append("    gap: 16px")
    lines.append("")
    lines.append("  fields:")
    if item_opts.convo_meta_field:
        lines.append(f"    - key: {item_opts.convo_meta_field}")
        lines.append("      type: text")
        lines.append('      label: "Conversation metadata"')
        lines.append("")
    lines.append(f"    - key: {item_opts.field_name}")
    lines.append("      type: dialogue")
    lines.append('      label: "Conversation"')
    if has_turn_level:
        # Turn slots inject widget text into the field's textContent, which is
        # what span offsets are measured against — Potato's own validator warns
        # about combining the two. Suggest the safe arrangement and say why.
        lines.append("      # span_target is deliberately off: this field carries turn-level")
        lines.append("      # widgets, whose text shifts the offsets spans are measured against.")
        lines.append("      # To annotate spans too, add a second dialogue field without")
        lines.append("      # turn bindings and point span_target at that one.")
    else:
        lines.append("      span_target: true")
    lines.append("      display_options:")
    lines.append("        show_turn_numbers: true")
    if threaded_display:
        lines.append("        indent_replies: true")
        lines.append("        show_timestamps: true")
    if item_opts.tree_field:
        lines.append("")
        lines.append(f"    # A second, threaded view of the same turns. Node ids match the")
        lines.append(f"    # flat view's turn ids, so both annotate the same utterances.")
        lines.append(f"    # - key: {item_opts.tree_field}")
        lines.append("    #   type: conversation_tree")
        lines.append('    #   label: "Thread"')
    lines.append("")

    # --- schemes ----------------------------------------------------------- #
    lines.append("annotation_schemes:")
    if not suggestions:
        lines.append("  # No metadata fields were suitable to suggest a scheme from.")
        lines.append("  - annotation_type: radio")
        lines.append("    name: label")
        lines.append('    description: "Your label"')
        lines.append("    labels:")
        lines.append("      - yes")
        lines.append("      - no")
        lines.append("    sequential_key_binding: true")
    else:
        for i, suggestion in enumerate(suggestions):
            if i:
                lines.append("")
            lines.extend(_emit_scheme(suggestion))

    if skipped:
        lines.append("")
        lines.append("  # Not suggested:")
        for obj_type, name, reason in skipped:
            lines.append(f"  #   {obj_type}.{name} — {reason}")

    lines.append("")
    lines.append("user_config:")
    lines.append("  allow_all_users: true")
    lines.append("")
    return "\n".join(lines)

"""
Turn-Level Annotation Framework.

Lets any supported annotation scheme be applied *per turn* (or per step) of a
turn-based display (dialogue, agent_trace, multi_agent_discussion) instead of
once per instance. Schemes opt in with ``turn_level: true`` and declare which
turns they attach to via a declarative ``turn_binding`` filter:

.. code-block:: yaml

    annotation_schemes:
      - annotation_type: multiselect
        name: turn_errors
        description: "Errors in this turn"
        labels: [hallucination, wrong_tool, bad_handoff]
        turn_level: true
        turn_binding:
          field: conversation        # instance_display field key to attach to
          speakers: ["Assistant"]    # optional; matches turn speaker
          agents: ["researcher"]     # optional; matches turn agent_id
          step_types: [action]       # optional; normalized step type
          tools: [search]            # optional; tool name of the call
          runs: [run-abc]            # optional; run-tree node id (sub-agent)
          turn_range: [0, 50]        # optional; inclusive normalized index range
          placement: inline          # inline (default) | drawer (click-to-open)

Architecture (persistence contract — see internal/annotation-persistence.md):

* The **anchor**: each turn-level scheme contributes one compact block to the
  annotation form layout containing a single hidden
  ``annotation-data-input`` (``name={schema}``).  That input is the *only*
  real annotation input — it round-trips through the standard ``_data``
  pipeline (``saveAnnotations`` -> ``/updateinstance`` ->
  ``Label(schema, "_data")`` -> BeautifulSoup restore with
  ``data-server-set``).  Zero server-side storage changes.
* The **slots**: displays that support turn annotation call
  :func:`render_turn_slot` once per rendered turn.  Slot widgets are
  *display-only proxies* — buttons/chips/plain elements that deliberately do
  NOT carry the ``annotation-input`` class or ``schema``/``label_name``
  attributes, so the four global persistence functions in annotation.js
  (syncAnnotationsFromDOM / saveAnnotations / clearAllFormInputs /
  populateInputValues) never see them.
* The **frontend**: potato/static/turn-annotations.js seeds its state from
  the server-restored hidden value on load (never from hardcoded defaults —
  the IIFE-overwrite bug pattern), paints the proxies, and serializes user
  interaction back into the hidden input.

Stored JSON value format (versioned)::

    {"v": 1, "schema_type": "multiselect",
     "turns": {"t3": {"values": ["hallucination"],
                      "speaker": "Assistant", "step_type": "action"}}}

Turn ids are the explicit ``turn_id``/``step_id`` from the data when present,
else ``t{index}`` over the display's normalized turn sequence.  Each stored
turn entry snapshots ``speaker``/``step_type`` (and ``agent_id`` when known)
so exports can detect drift if the underlying trace is later edited.
"""

import html
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Schema types that can be bound per-turn. These map onto compact inline
#: proxy widgets. Complex interactive schemas (span, image_annotation, ...)
#: remain trace-level only.
TURN_LEVEL_SUPPORTED_TYPES = {
    "radio",
    "multiselect",
    "likert",
    "slider",
    "select",
    "text",
    "number",
}

#: Keys accepted inside a ``turn_binding`` block (validated in config_module).
TURN_BINDING_KEYS = {
    "field",
    "speakers",
    "agents",
    "step_types",
    "tools",
    "runs",
    "turn_range",
    "placement",
}

_TOOL_CALL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\(")


# ---------------------------------------------------------------------------
# Scheme discovery / binding resolution
# ---------------------------------------------------------------------------

def is_turn_level_scheme(scheme: Dict[str, Any]) -> bool:
    """True if this annotation scheme is bound per-turn."""
    return bool(scheme.get("turn_level"))


def get_turn_level_schemes(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Collect all turn-level annotation schemes from the config.

    Handles both top-level ``annotation_schemes`` and phase-based configs.
    """
    schemes: List[Dict[str, Any]] = []
    if "annotation_schemes" in config:
        schemes = list(config.get("annotation_schemes") or [])
    elif "phases" in config:
        phases = config["phases"]
        iterable = phases if isinstance(phases, list) else [
            p for name, p in phases.items() if name != "order" and isinstance(p, dict)
        ]
        for phase in iterable:
            schemes.extend(phase.get("annotation_schemes", []) or [])
    return [s for s in schemes if isinstance(s, dict) and is_turn_level_scheme(s)]


def schemes_for_field(schemes: List[Dict[str, Any]], field_key: str) -> List[Dict[str, Any]]:
    """Filter turn-level schemes down to those bound to a display field.

    A scheme with no ``turn_binding.field`` binds to every turn-capable field
    (the common single-conversation case).
    """
    out = []
    for scheme in schemes:
        binding = scheme.get("turn_binding") or {}
        bound_field = binding.get("field")
        if bound_field is None or bound_field == field_key:
            out.append(scheme)
    return out


def extract_tool_name(turn: Dict[str, Any]) -> str:
    """Best-effort tool name extraction from a normalized turn/step dict."""
    tool = turn.get("tool")
    if tool:
        return str(tool)
    tool_calls = turn.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        first = tool_calls[0]
        if isinstance(first, dict):
            return str(first.get("name") or first.get("tool") or "")
    if _turn_step_type(turn) == "action":
        m = _TOOL_CALL_RE.match(str(turn.get("text", "")))
        if m:
            return m.group(1)
    return ""


def _turn_step_type(turn: Dict[str, Any]) -> str:
    """Normalized step type of a turn, inferring from speaker if absent."""
    step_type = turn.get("type") or turn.get("step_type")
    if step_type:
        return str(step_type)
    from .displays._trace_normalize import infer_type_from_speaker
    return infer_type_from_speaker(str(turn.get("speaker", "")))


def turn_matches_binding(turn: Dict[str, Any], index: int, binding: Dict[str, Any]) -> bool:
    """Does a normalized turn match a ``turn_binding`` filter?

    All present filters AND together; an omitted filter matches everything.

    Args:
        turn: normalized turn/step dict (speaker/text plus optional
            type/agent_id/tool keys)
        index: the turn's index in the display's normalized sequence
        binding: the scheme's ``turn_binding`` dict (may be empty)
    """
    if not binding:
        return True

    speakers = binding.get("speakers")
    if speakers is not None and str(turn.get("speaker", "")) not in speakers:
        return False

    agents = binding.get("agents")
    if agents is not None and str(turn.get("agent_id", "")) not in agents:
        return False

    step_types = binding.get("step_types")
    if step_types is not None and _turn_step_type(turn) not in step_types:
        return False

    tools = binding.get("tools")
    if tools is not None and extract_tool_name(turn) not in tools:
        return False

    runs = binding.get("runs")
    if runs is not None and str(turn.get("run_id", "")) not in runs:
        return False

    turn_range = binding.get("turn_range")
    if turn_range is not None:
        try:
            lo, hi = int(turn_range[0]), int(turn_range[1])
        except (TypeError, ValueError, IndexError):
            return True  # malformed range validated at config load; be lenient here
        if not (lo <= index <= hi):
            return False

    return True


def turn_id_for(turn: Dict[str, Any], index: int) -> str:
    """Stable id for a turn: explicit turn_id/step_id if present, else t{index}."""
    explicit = turn.get("turn_id") or turn.get("step_id")
    if explicit:
        return str(explicit)
    return f"t{index}"


def build_turn_index(
    turns: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build the precomputed turn index over a normalized turn sequence.

    Each record carries the stable id plus the snapshot fields used for
    binding filters and drift detection. Used by exports and tests; the
    display render path filters turns directly via
    :func:`turn_matches_binding`.
    """
    records = []
    for i, turn in enumerate(turns):
        records.append({
            "turn_id": turn_id_for(turn, i),
            "index": i,
            "speaker": str(turn.get("speaker", "")),
            "agent_id": str(turn.get("agent_id", "")),
            "role": str(turn.get("role", "")),
            "addressee": str(turn.get("addressee", "")),
            "step_type": _turn_step_type(turn),
            "tool": extract_tool_name(turn),
            "run_id": str(turn.get("run_id", "")),
        })
    return records


# ---------------------------------------------------------------------------
# Rendering: per-turn slots (proxy widgets)
# ---------------------------------------------------------------------------

def render_turn_slot(
    schemes: List[Dict[str, Any]],
    turn: Dict[str, Any],
    index: int,
    field_key: str,
) -> str:
    """Render the annotation slot for one turn.

    Returns "" when no scheme matches this turn. The returned HTML contains
    only proxy widgets (no ``annotation-input`` classed elements) — the real
    state lives in each scheme's hidden anchor input (see module docstring).
    """
    matching = [s for s in schemes if turn_matches_binding(turn, index, s.get("turn_binding") or {})]
    if not matching:
        return ""

    tid = turn_id_for(turn, index)
    esc_tid = html.escape(tid, quote=True)
    esc_field = html.escape(str(field_key), quote=True)
    speaker = html.escape(str(turn.get("speaker", "")), quote=True)
    step_type = html.escape(_turn_step_type(turn), quote=True)
    agent_id = html.escape(str(turn.get("agent_id", "")), quote=True)

    widgets = []
    any_drawer = False
    for scheme in matching:
        placement = (scheme.get("turn_binding") or {}).get("placement", "inline")
        widget = _render_widget(scheme, tid)
        if placement == "drawer":
            any_drawer = True
            widget = (
                f'<div class="ta-drawer" data-ta-schema="{html.escape(scheme["name"], quote=True)}"'
                f' data-turn-id="{esc_tid}" style="display:none;">{widget}</div>'
            )
        widgets.append(widget)

    drawer_toggle = ""
    if any_drawer:
        drawer_toggle = (
            f'<button type="button" class="ta-drawer-toggle" data-turn-id="{esc_tid}"'
            f' aria-expanded="false" title="Annotate this turn">&#9998; annotate</button>'
        )

    return (
        f'<div class="turn-anno-slot" data-turn-id="{esc_tid}" data-turn-index="{index}"'
        f' data-field-key="{esc_field}" data-speaker="{speaker}"'
        f' data-step-type="{step_type}" data-agent-id="{agent_id}">'
        f'{drawer_toggle}{"".join(widgets)}'
        f'</div>'
    )


def _render_widget(scheme: Dict[str, Any], tid: str) -> str:
    """Render the compact proxy widget for one scheme on one turn."""
    name = scheme["name"]
    ann_type = scheme["annotation_type"]
    esc_name = html.escape(name, quote=True)
    esc_tid = html.escape(tid, quote=True)
    label_text = html.escape(str(scheme.get("turn_label", scheme.get("description", name))))

    common = f'data-ta-schema="{esc_name}" data-turn-id="{esc_tid}"'
    body = ""

    if ann_type in ("radio", "multiselect"):
        multi = "true" if ann_type == "multiselect" else "false"
        chips = []
        for label in _scheme_labels(scheme):
            esc_label = html.escape(str(label), quote=True)
            chips.append(
                f'<button type="button" class="ta-chip" {common}'
                f' data-value="{esc_label}" data-multi="{multi}">{html.escape(str(label))}</button>'
            )
        body = f'<span class="ta-chips">{"".join(chips)}</span>'

    elif ann_type == "likert":
        size = int(scheme.get("size", len(_scheme_labels(scheme)) or 5))
        min_label = html.escape(str(scheme.get("min_label", "")))
        max_label = html.escape(str(scheme.get("max_label", "")))
        chips = []
        for v in range(1, size + 1):
            chips.append(
                f'<button type="button" class="ta-chip ta-likert" {common}'
                f' data-value="{v}" data-multi="false" title="{v}">{v}</button>'
            )
        lo = f'<span class="ta-scale-label">{min_label}</span>' if min_label else ""
        hi = f'<span class="ta-scale-label">{max_label}</span>' if max_label else ""
        body = f'{lo}<span class="ta-chips">{"".join(chips)}</span>{hi}'

    elif ann_type == "slider":
        min_v = scheme.get("min_value", 0)
        max_v = scheme.get("max_value", 100)
        body = (
            f'<input type="range" class="ta-range" {common}'
            f' min="{html.escape(str(min_v), quote=True)}" max="{html.escape(str(max_v), quote=True)}"'
            f' value="{html.escape(str(min_v), quote=True)}" data-ta-armed="false">'
            f'<span class="ta-range-value" {common}></span>'
        )

    elif ann_type == "select":
        opts = ['<option value="">--</option>']
        for label in _scheme_labels(scheme):
            esc_label = html.escape(str(label), quote=True)
            opts.append(f'<option value="{esc_label}">{html.escape(str(label))}</option>')
        body = f'<select class="ta-select" {common}>{"".join(opts)}</select>'

    elif ann_type in ("textbox", "text"):
        body = (
            f'<textarea class="ta-text" {common} rows="1"'
            f' placeholder="{label_text}"></textarea>'
        )

    elif ann_type == "number":
        body = f'<input type="number" class="ta-number" {common}>'

    else:  # pragma: no cover - blocked by config validation
        logger.warning("turn_level not supported for annotation_type=%s", ann_type)
        return ""

    return (
        f'<span class="turn-anno-widget" data-ta-schema="{esc_name}" data-ta-type="{ann_type}">'
        f'<span class="ta-widget-label">{label_text}</span>{body}'
        f'</span>'
    )


def _scheme_labels(scheme: Dict[str, Any]) -> List[str]:
    """Flatten scheme labels (which may be strings or {name: ...} dicts)."""
    labels = []
    for label in scheme.get("labels", []) or []:
        if isinstance(label, dict):
            labels.append(label.get("name", ""))
        else:
            labels.append(label)
    return labels


# ---------------------------------------------------------------------------
# Rendering: the form-area anchor (real hidden input)
# ---------------------------------------------------------------------------

def generate_turn_level_anchor_layout(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    """Generate the annotation-form block for a turn-level scheme.

    This is what appears in the schema layout instead of the scheme's normal
    full-size form: a legend, a live progress counter, and the single hidden
    ``annotation-data-input`` that carries all per-turn values through the
    standard ``_data`` persistence pipeline.

    Returns (html, keybindings) like every schema generator; keybindings are
    always suppressed for turn-level schemes (widgets repeat per turn, so a
    single key cannot address them).
    """
    name = annotation_scheme["name"]
    esc_name = html.escape(name, quote=True)
    description = html.escape(str(annotation_scheme.get("description", name)))
    binding = annotation_scheme.get("turn_binding") or {}

    config_json = html.escape(json.dumps({
        "schema_type": annotation_scheme["annotation_type"],
        "field": binding.get("field"),
        "placement": binding.get("placement", "inline"),
    }), quote=True)

    layout = f"""
    <form id="{esc_name}" class="annotation-form turn-level-anchor"
          action="javascript:void(0)" data-annotation-type="turn_level"
          data-schema-name="{esc_name}">
        <fieldset schema="{esc_name}">
            <legend>{description}</legend>
            <div class="ta-anchor-note">
                Annotated inline on each matching turn
                <span class="ta-progress" data-ta-schema="{esc_name}"></span>
            </div>
            <input type="hidden" class="annotation-data-input turn-anno-hidden"
                   name="{esc_name}" id="turn-anno-{esc_name}"
                   data-schema-name="{esc_name}" data-ta-config="{config_json}"
                   value="">
        </fieldset>
    </form>
    """
    logger.info("Generated turn-level anchor layout for %s", name)
    return layout, []


# ---------------------------------------------------------------------------
# Per-agent rollups (admin analytics)
# ---------------------------------------------------------------------------

def compute_agent_rollup(item_state_manager, user_state_manager, config) -> Dict[str, Any]:
    """Aggregate turn-level annotations per agent across the whole dataset.

    Returns::

        {"schemas": {schema_name: {
            "agents": {agent_id: {
                "annotated_turns": int,
                "mean": float | None,          # over numeric values
                "value_counts": {label: int},  # over categorical values
            }},
        }},
        "n_annotators": int}

    Turn entries with no ``agent_id`` snapshot roll up under ``""``
    (surfaced as "(unattributed)" in the UI).
    """
    scheme_names = {s["name"] for s in get_turn_level_schemes(config)}
    result: Dict[str, Any] = {"schemas": {}, "n_annotators": 0}
    if not scheme_names:
        return result

    annotators = set()
    for iid, annotator_ids in getattr(item_state_manager, "instance_annotators", {}).items():
        for uid in annotator_ids:
            ustate = user_state_manager.get_user_state(uid)
            if ustate is None:
                continue
            labels_by_key = ustate.get_label_annotations(iid) or {}
            for lbl, value in labels_by_key.items():
                schema = getattr(lbl, "schema", None)
                name = getattr(lbl, "name", None)
                if schema not in scheme_names or name != "_data" or not value:
                    continue
                rows = flatten_turn_annotation(schema, value)
                if not rows:
                    continue
                annotators.add(uid)
                bucket = result["schemas"].setdefault(schema, {"agents": {}})
                for row in rows:
                    agent = str(row.get("agent_id", "") or "")
                    stats = bucket["agents"].setdefault(agent, {
                        "annotated_turns": 0, "_numeric": [], "value_counts": {},
                    })
                    stats["annotated_turns"] += 1
                    values = row.get("values")
                    if values is None and "value" in row:
                        values = [row["value"]]
                    for v in values or []:
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            stats["_numeric"].append(v)
                        else:
                            key = str(v)
                            stats["value_counts"][key] = stats["value_counts"].get(key, 0) + 1

    # Finalize numeric means
    for schema_stats in result["schemas"].values():
        for stats in schema_stats["agents"].values():
            numeric = stats.pop("_numeric")
            stats["mean"] = (sum(numeric) / len(numeric)) if numeric else None

    result["n_annotators"] = len(annotators)
    return result


# ---------------------------------------------------------------------------
# Export flattening
# ---------------------------------------------------------------------------

def flatten_turn_annotation(
    schema_name: str,
    raw_value: Any,
) -> List[Dict[str, Any]]:
    """Flatten one stored turn-level ``_data`` JSON blob into per-turn rows.

    Returns rows of the form::

        {"schema": name, "turn_id": "t3", "value"/"values": ...,
         "speaker": ..., "step_type": ..., "agent_id": ...}

    Unknown/legacy formats return an empty list (callers keep the raw JSON in
    the standard output regardless, so nothing is lost).
    """
    if isinstance(raw_value, str):
        try:
            raw_value = json.loads(raw_value)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw_value, dict) or "turns" not in raw_value:
        return []

    rows = []
    for tid, entry in (raw_value.get("turns") or {}).items():
        if not isinstance(entry, dict):
            continue
        row = {"schema": schema_name, "turn_id": tid}
        for key in ("value", "values", "speaker", "step_type", "agent_id"):
            if key in entry:
                row[key] = entry[key]
        rows.append(row)
    return rows

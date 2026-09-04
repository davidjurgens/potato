"""
World-model and generative-video rollout evaluation.

Several videos of the same scenario — the real recording, one or more model
rollouts, sometimes a counterfactual under an intervention — on one frame-locked
timeline, with three questions asked of them.

## The primitive is a break-point, not a score

Rating a generated video 3/5 for "physical plausibility" produces a number that
cannot be checked, cannot be localised, and cannot be used to fix anything. The
annotation that *can* is: **the frame at which the world stops making sense**,
plus why. It is checkable against the tensor, it localises the failure to a
moment a researcher can look at, and — because it is a point in time — two
annotators' answers can be compared with a real agreement statistic
(:mod:`potato.server_utils.iaa.rollouts`).

Nobody measures whether human judgements about generated video are reliable.
That is what makes this worth building rather than another rating scale.

## Three layers, because they are three different questions

| Layer | Question | Shape |
|---|---|---|
| `violations` | Where does it break, and why? | Point in time, per stream, typed and graded |
| `preference` | Which rollout is better? | A winner, a confidence, optional rubric dimensions |
| `counterfactual` | Is the divergence plausible *given* the intervention? | A verdict plus where the divergence starts |

The counterfactual layer is the one that separates a world model from a video
generator: a model that produces a beautiful continuation which ignores the
intervention has failed at the thing world models are for, and no plausibility
rating detects that, because the video is plausible.

## "No violations" is an answer, not an absence

A stream with no marks is ambiguous — did the annotator watch it and find
nothing, or never get to it? Detection agreement cannot be computed across that
ambiguity, so marking a stream **clean** is an explicit act, and the interface
will not accept a submission that leaves a stream neither marked nor cleared.
This is the same line the episode reward curve draws between "did not say" and
"said zero".

## Blinding and order

Handled entirely server-side, in :mod:`potato.rollouts.routes`. The schema only
declares whether it wants them; the client never receives the generator names
under blinding, and never chooses the panel order. See that module for why.

## Storage

One JSON blob under a single ``_data`` key, as every other blob schema uses:

    {"violations": [{"stream": "gen_a", "t": 3.42, "type": "interpenetration",
                     "severity": 2, "note": ""}],
     "clean": ["real"],
     "preference": {"winner": "gen_a", "confidence": 2, "rubric": {}},
     "counterfactual": {"verdict": "plausible", "t": 2.10, "note": ""}}

Times are **seconds**, matching every other temporal schema, so the agreement
code needs no conversion. Frames are displayed, never stored — the frame rate
is a declaration and a stored frame index would be wrong the moment it changed.
"""

import json
import logging

from .identifier_utils import escape_html_content, safe_generate_layout, generate_layout_attributes
from .image_annotation import DEFAULT_COLORS, _process_labels

logger = logging.getLogger(__name__)

#: The annotation layers a schema may enable.
VALID_LAYERS = ("violations", "preference", "counterfactual")

#: The physics / consistency taxonomy.
#:
#: Each carries a one-line definition, and that is not decoration: an annotator
#: who cannot tell `rigid_body_violation` from `implausible_deformation` will
#: pick whichever is first in the list, and the category agreement measured over
#: their answers will be about the list order rather than about the video.
DEFAULT_VIOLATION_TYPES = [
    {"name": "object_permanence",
     "description": "An object vanishes, or appears, with nothing causing it."},
    {"name": "rigid_body_violation",
     "description": "A solid object bends, stretches or changes size."},
    {"name": "interpenetration",
     "description": "Two solid objects pass through each other."},
    {"name": "gravity_violation",
     "description": "Something floats, falls upward, or stands unsupported."},
    {"name": "causality_violation",
     "description": "An effect happens before, or without, its cause."},
    {"name": "identity_flicker",
     "description": "An object swaps identity or category between frames."},
    {"name": "appearance_drift",
     "description": "Texture, colour or shape drifts with no event to explain it."},
    {"name": "implausible_deformation",
     "description": "A deformable object deforms in a way its material would not."},
    {"name": "agent_intent_break",
     "description": "An agent abandons or reverses a goal it was clearly pursuing."},
    {"name": "affordance_violation",
     "description": "An object is used in a way its form does not permit."},
]

#: How bad it is. Three points, not five: annotators do not reliably
#: distinguish five grades of physical implausibility, and the extra
#: resolution buys noise rather than signal.
DEFAULT_SEVERITIES = [
    {"value": 1, "name": "subtle", "description": "Visible on a second look."},
    {"value": 2, "name": "clear", "description": "Obvious on first viewing."},
    {"value": 3, "name": "breaks the scene",
     "description": "Nothing after this point is worth judging."},
]

#: Counterfactual verdicts. "unclear" is present because forcing a binary here
#: manufactures decisions: a rollout can diverge in a way that is neither
#: obviously consistent with the intervention nor obviously not, and recording
#: that as "implausible" is a false negative that looks like data.
DEFAULT_CF_VERDICTS = [
    {"name": "plausible",
     "description": "The divergence follows from the intervention."},
    {"name": "implausible",
     "description": "The divergence contradicts the intervention, or ignores it."},
    {"name": "unchanged",
     "description": "The rollout ignored the intervention entirely."},
    {"name": "unclear", "description": "Cannot tell from this rollout."},
]

#: Keyboard shortcuts.
#:
#: Every one of these is the *only* way to do the thing it does for a keyboard
#: user, so the set is chosen before the pointer affordances rather than fitted
#: around them. `,`/`.` step frames because that is what a video editor binds;
#: `m` marks because that is what every NLE binds for a marker.
TOOL_KEYS = {
    "play": " ",
    "prev_frame": ",",
    "next_frame": ".",
    "mark": "m",
    "prev_violation": "[",
    "next_violation": "]",
    "clean": "c",
}


def generate_rollout_evaluation_layout(annotation_scheme):
    """
    Generate HTML for a world-model rollout evaluation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - streams: List of ``{field, name, role}`` naming the item fields
              that hold each rollout's video URL. Required unless
              ``manifest_field`` is set.
            - manifest_field: Item field holding a path to a rollout manifest,
              for datasets shipped as directories
            - prompt_field / intervention_field / intervention_time_field:
              Item fields carrying the scenario text (defaults: ``prompt``,
              ``intervention``, ``intervention_t``)
            - fps: Declared frame rate. Without it, frame numbers are omitted
              rather than guessed — see potato/rollouts/registry.py
            - layers: Which of violations / preference / counterfactual
            - violation_types: The taxonomy, as strings or
              ``{name, description, color, key_value}``
            - severities: The severity scale
            - cf_verdicts: Counterfactual verdicts
            - rubric: Optional ``{dimension: description}`` scored per winner
            - blind: Hide generator names (default true)
            - shuffle: Permute panel order per annotator (default true)
            - require_clean: Refuse a submission that leaves a stream neither
              marked nor cleared (default true)
            - max_violations: Cap per item

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme):
    # The grid reads data-grid-columns; without this the scheme's
    # `layout:` block is silently discarded and it renders at one column.
    layout_attrs = generate_layout_attributes(annotation_scheme)
    schema_name = annotation_scheme.get("name", "rollout_evaluation")
    logger.debug("Generating rollout evaluation layout for schema: %s",
                 schema_name)

    layers = annotation_scheme.get("layers", list(VALID_LAYERS))
    if not isinstance(layers, list) or not layers:
        raise ValueError(f"layers must be a non-empty list in schema: "
                         f"{schema_name}")
    invalid = [layer for layer in layers if layer not in VALID_LAYERS]
    if invalid:
        raise ValueError(
            f"Invalid layers: {invalid}. Valid layers are: "
            f"{list(VALID_LAYERS)}")

    if (not annotation_scheme.get("streams")
            and not annotation_scheme.get("manifest_field")):
        raise ValueError(
            f"Schema '{schema_name}' needs either a 'streams' list naming the "
            f"item fields that hold each rollout's video, or a "
            f"'manifest_field' naming the field that holds a rollout manifest "
            f"path.")

    violation_types = _process_types(
        annotation_scheme.get("violation_types", DEFAULT_VIOLATION_TYPES))
    severities = _process_severities(
        annotation_scheme.get("severities", DEFAULT_SEVERITIES))
    verdicts = _process_types(
        annotation_scheme.get("cf_verdicts", DEFAULT_CF_VERDICTS))
    rubric = annotation_scheme.get("rubric") or {}
    if not isinstance(rubric, dict):
        raise ValueError(
            f"rubric must be a mapping of dimension to description in schema: "
            f"{schema_name}")

    escaped_name = escape_html_content(schema_name)
    description = escape_html_content(annotation_scheme.get("description", ""))

    config = {
        "schema": schema_name,
        "layers": layers,
        "violationTypes": violation_types,
        "severities": severities,
        "cfVerdicts": verdicts,
        "rubric": {str(k): str(v) for k, v in rubric.items()},
        "requireClean": annotation_scheme.get("require_clean", True) is not False,
        "maxViolations": annotation_scheme.get("max_violations"),
        "toolKeys": TOOL_KEYS,
    }

    html = f"""
    <div class="rollout-eval-container annotation-form" data-schema="{escaped_name}" data-annotation-type="rollout_evaluation" data-schema-name="{escaped_name}" {layout_attrs}>
        <fieldset>
            <legend>{description}</legend>

            <p class="rollout-prompt" hidden></p>
            <p class="rollout-intervention" hidden></p>

            <!-- The panels. Built by the client from the server's manifest,
                 because the order and the captions are decided per annotator
                 and must not be in the page source. -->
            <div class="rollout-panels" id="rollout-panels-{escaped_name}"
                 role="group" aria-label="Rollout panels"></div>

            <div class="rollout-transport" role="toolbar"
                 aria-label="Playback and marking">
                <button type="button" class="rollout-play"
                        aria-pressed="false" title="Play or pause (space)">
                    <span aria-hidden="true">&#9654;</span> Play
                </button>
                <button type="button" class="rollout-step" data-step="-1"
                        title="Back one frame (,)">
                    <span aria-hidden="true">&#9664;&#124;</span>
                    <span class="visually-hidden">Back one frame</span>
                </button>
                <button type="button" class="rollout-step" data-step="1"
                        title="Forward one frame (.)">
                    <span aria-hidden="true">&#124;&#9654;</span>
                    <span class="visually-hidden">Forward one frame</span>
                </button>
                <span class="rollout-time">0.00 s</span>
                <span class="rollout-frame"></span>
                {_mark_controls(layers)}
            </div>

            <!-- One lane per stream, marks drawn where the annotator said the
                 world broke. The intervention, when there is one, is a line
                 across every lane: a violation before it is about the model,
                 a violation after it is about the model's response to it. -->
            <div class="rollout-timeline"
                 id="rollout-timeline-{escaped_name}"></div>

            {_violation_form(escaped_name, violation_types, severities)
             if "violations" in layers else ""}

            {_preference_block(escaped_name, rubric)
             if "preference" in layers else ""}

            {_counterfactual_block(escaped_name, verdicts)
             if "counterfactual" in layers else ""}

            <p class="rollout-help">
                <kbd>space</kbd> play &middot;
                <kbd>,</kbd> <kbd>.</kbd> step a frame &middot;
                <kbd>1</kbd>&ndash;<kbd>9</kbd> choose a panel &middot;
                <kbd>m</kbd> mark a break &middot;
                <kbd>c</kbd> mark the panel clean &middot;
                <kbd>[</kbd> <kbd>]</kbd> move between marks &middot;
                <kbd>&larr;</kbd> <kbd>&rarr;</kbd> nudge the selected mark
            </p>

            <!-- How much of the task is left. Not decoration: an unanswered
                 panel is invisible otherwise, and the difference between
                 "watched it, nothing wrong" and "never got to it" is what the
                 detection agreement is computed over. NOT a live region — it
                 is rewritten on every edit, and a live region that talks on
                 every keystroke is one people turn off. -->
            <p class="rollout-progress"></p>

            <p class="rollout-status" id="rollout-status-{escaped_name}"
               aria-live="polite"></p>
            <p class="rollout-announce" role="status" aria-live="polite"></p>

            <input type="hidden"
                   name="{escaped_name}"
                   id="input-{escaped_name}"
                   class="annotation-data-input"
                   value="">
        </fieldset>
    </div>

    <script>
        (function() {{
            function initWhenReady() {{
                if (typeof RolloutEvaluationManager === 'undefined') {{
                    setTimeout(initWhenReady, 100);
                    return;
                }}
                var container = document.querySelector(
                    '.rollout-eval-container[data-schema="{escaped_name}"]');
                if (!container || container.annotationManager) return;

                var manager = new RolloutEvaluationManager(
                    '{escaped_name}', {json.dumps(config)});
                container.annotationManager = manager;
                try {{
                    manager.init();
                }} catch (err) {{
                    // The manager is attached before init so a re-entrant call
                    // cannot build a second one, which means a throw in init
                    // leaves a half-built manager that every readiness check
                    // still accepts. Surfacing it turns a silently dead panel
                    // grid into one that says why.
                    var status = document.getElementById(
                        'rollout-status-{escaped_name}');
                    if (status) {{
                        status.textContent =
                            'Rollout viewer failed to start: ' + err.message;
                        status.setAttribute('data-kind', 'error');
                    }}
                    console.error('[rollout] init failed', err);
                }}
            }}
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', initWhenReady);
            }} else {{
                initWhenReady();
            }}
        }})();
    </script>
    """

    return html, _keybindings(layers)


def _mark_controls(layers):
    """
    The two buttons that write to the violations layer.

    Both are disabled until a panel is chosen, because "mark a break" with no
    panel selected has no meaning — a break belongs to *one* rollout, and
    guessing which would silently attribute it to the wrong model.
    """
    if "violations" not in layers:
        return ""
    return (
        '<button type="button" class="rollout-mark" disabled '
        'title="Mark a break at this frame (m)">'
        '<span aria-hidden="true">&#9873;</span> Mark break</button>\n'
        '<button type="button" class="rollout-clean-btn" disabled '
        'aria-pressed="false" title="This rollout has no breaks (c)">'
        '<span aria-hidden="true">&#10003;</span> No breaks</button>')


def _violation_form(escaped_name, violation_types, severities):
    """
    The editor for the selected break.

    Present and disabled rather than absent until something is selected: a
    control that materialises on selection reflows the page under the pointer,
    and the annotator loses the place they were looking at — which on this
    surface is a specific frame they may not be able to find again.
    """
    type_options = "\n".join(
        f'<option value="{escape_html_content(str(t["name"]))}" '
        f'title="{escape_html_content(str(t.get("description") or ""))}">'
        f'{escape_html_content(str(t["name"]).replace("_", " "))}</option>'
        for t in violation_types)
    severity_options = "\n".join(
        f'<option value="{int(s["value"])}" '
        f'title="{escape_html_content(str(s.get("description") or ""))}">'
        f'{escape_html_content(str(s["name"]))}</option>'
        for s in severities)

    return f"""
            <div class="rollout-violation-form" role="group"
                 aria-label="Selected break">
                <span class="rollout-violation-where">No break selected</span>
                <label class="rollout-field">
                    <span>What broke</span>
                    <select class="rollout-violation-type"
                            id="rollout-vtype-{escaped_name}" disabled>
                        {type_options}
                    </select>
                </label>
                <label class="rollout-field">
                    <span>How bad</span>
                    <select class="rollout-violation-severity"
                            id="rollout-vsev-{escaped_name}" disabled>
                        {severity_options}
                    </select>
                </label>
                <label class="rollout-field rollout-field-wide">
                    <span>Note</span>
                    <input type="text" class="rollout-violation-note"
                           id="rollout-vnote-{escaped_name}" disabled
                           placeholder="optional">
                </label>
                <button type="button" class="rollout-violation-delete" disabled>
                    Delete
                </button>
                <p class="rollout-violation-hint"></p>
            </div>
    """


def _preference_block(escaped_name, rubric):
    """
    Which rollout is better, and how sure.

    The winner options are built by the client from the manifest, because under
    blinding the labels are positional and the server decided the positions.
    Rendering them here would either leak the generator names into the page
    source or hard-code an order the server is free to permute.
    """
    rubric_rows = "\n".join(
        f"""<div class="rollout-rubric-row">
                <span class="rollout-rubric-name"
                      title="{escape_html_content(str(text))}">
                    {escape_html_content(str(name))}
                </span>
                <span class="rollout-rubric-scale"
                      data-dimension="{escape_html_content(str(name))}"
                      role="radiogroup"
                      aria-label="{escape_html_content(str(name))}"></span>
            </div>"""
        for name, text in rubric.items())

    return f"""
            <div class="rollout-preference" role="group"
                 aria-label="Which rollout is better">
                <span class="rollout-block-legend">Preferred rollout</span>
                <div class="rollout-winner"
                     id="rollout-winner-{escaped_name}"
                     role="radiogroup"
                     aria-label="Preferred rollout"></div>
                <label class="rollout-field">
                    <span>How sure</span>
                    <select class="rollout-confidence"
                            id="rollout-conf-{escaped_name}">
                        <option value="">&mdash;</option>
                        <option value="1">a slight preference</option>
                        <option value="2">a clear preference</option>
                        <option value="3">no contest</option>
                    </select>
                </label>
                {f'<div class="rollout-rubric">{rubric_rows}</div>'
                 if rubric else ''}
            </div>
    """


def _counterfactual_block(escaped_name, verdicts):
    """
    Whether the divergence follows from the intervention.

    Shown only when the item actually carries an intervention — the client
    hides this block otherwise. Asking "is the divergence plausible?" about a
    set with nothing to diverge from produces an answer to a question that was
    not asked.
    """
    options = "\n".join(
        f'<label class="rollout-cf-option" '
        f'title="{escape_html_content(str(v.get("description") or ""))}">'
        f'<input type="radio" name="rollout-cf-{escaped_name}" '
        f'value="{escape_html_content(str(v["name"]))}"> '
        f'{escape_html_content(str(v["name"]))}</label>'
        for v in verdicts)

    return f"""
            <div class="rollout-counterfactual" role="group"
                 aria-label="Counterfactual plausibility" hidden>
                <span class="rollout-block-legend">
                    Given the intervention, is the divergence plausible?
                </span>
                {options}
                <label class="rollout-field rollout-field-wide">
                    <span>Why</span>
                    <input type="text" class="rollout-cf-note"
                           id="rollout-cfnote-{escaped_name}"
                           placeholder="optional">
                </label>
            </div>
    """


def _process_types(entries):
    """Normalise a taxonomy to ``{name, description, color, key_value}``."""
    processed = _process_labels(entries)
    for index, entry in enumerate(entries):
        if isinstance(entry, dict):
            processed[index]["description"] = entry.get("description", "")
        else:
            processed[index].setdefault("description", "")
    return processed


def _process_severities(entries):
    """
    Normalise the severity scale, keeping its numeric values.

    Severity is *ordinal* and its numbers carry meaning — the agreement code
    treats the difference between 1 and 3 as larger than between 1 and 2 — so
    unlike the taxonomies this cannot be collapsed to names.
    """
    out = []
    for index, entry in enumerate(entries):
        if isinstance(entry, dict):
            value = entry.get("value", index + 1)
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"severity {entry.get('name', index)!r} has a non-numeric "
                    f"value {entry.get('value')!r}; severities are ordinal and "
                    f"their values are compared as numbers.")
            out.append({
                "value": value,
                "name": str(entry.get("name", value)),
                "description": str(entry.get("description", "")),
                "color": entry.get("color",
                                   DEFAULT_COLORS[index % len(DEFAULT_COLORS)]),
            })
        else:
            out.append({"value": index + 1, "name": str(entry),
                        "description": "",
                        "color": DEFAULT_COLORS[index % len(DEFAULT_COLORS)]})
    if not out:
        raise ValueError("severities must not be empty")
    return out


def _keybindings(layers):
    """
    The shortcut table shown in the sidebar.

    Panel selection (`1`-`9`) is deliberately not listed per panel: the number
    of panels is a property of the item, not of the schema, and a table
    promising four panels on an item that has two is worse than a range.
    """
    bindings = [
        {"key": "space", "description": "Play / pause every panel"},
        {"key": ", / .", "description": "Step one frame"},
        {"key": "1-9", "description": "Choose a panel"},
    ]
    if "violations" in layers:
        bindings.extend([
            {"key": TOOL_KEYS["mark"],
             "description": "Mark a break at this frame"},
            {"key": TOOL_KEYS["clean"],
             "description": "Mark the chosen panel as having no breaks"},
            {"key": "[ / ]", "description": "Previous / next break"},
            {"key": "← / →", "description": "Nudge the selected break a frame"},
        ])
    return bindings

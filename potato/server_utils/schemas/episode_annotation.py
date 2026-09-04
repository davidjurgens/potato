"""
Embodied Episode Annotation

A robot demonstration is several synchronized video streams plus several
numeric time series, and the questions worth asking about it are all temporal:
*when* did the grasp start, *when* did it fail, *how well* was it going at each
moment. So this schema is a timeline with the streams above it and the series
drawn as lanes beneath, and every annotation layer writes onto that timeline.

## Four layers, because they answer different questions

| Layer | Question | Shape |
|---|---|---|
| `phases` | What was the robot doing, and when? | Temporal segments over a taxonomy |
| `outcome` | Did it work? | One label per episode, plus a failure cause |
| `reward` | How well was it going at each moment? | A scalar drawn along the timeline |
| `instruction` | What was it asked to do? | Text, optionally aligned to a segment |

Each is independently enableable, because they cost very different amounts of
annotator time and a project rarely wants all four. Dense reward in particular
is minutes per episode; phase segmentation is seconds.

## Why not the tiered_annotation schema

`tiered_annotation` is the right tool for ELAN-style linguistic tiers over
audio, and it is built on Peaks.js — a waveform widget. An episode has no
audio, has several video streams rather than one, and has numeric lanes that a
waveform view has no concept of. What transfers is the *interaction* — drag to
create a segment, tiers with constraints — and that is reused as a pattern
rather than as an implementation.

## Storage

One JSON blob under a single `_data` key, as image and spatial annotation use:

    {"phases": [{"start": 0.0, "end": 1.8, "label": "reach"}, ...],
     "outcome": {"result": "failure", "cause": "slipped"},
     "reward": [{"t": 0.0, "value": 0.0}, ...],
     "instructions": [{"text": "...", "start": null, "end": null}]}

Times are **seconds**, matching the temporal segment convention the video and
audio schemas already use, so `iaa/geometry.temporal_iou` scores phase
boundaries with no conversion. The frame index is recoverable exactly from
`round(t * fps)`, which is why the episode manifest carries fps.
"""

import json
import logging

from .identifier_utils import escape_html_content, safe_generate_layout, generate_layout_attributes
from .image_annotation import DEFAULT_COLORS, _process_labels

logger = logging.getLogger(__name__)

#: The annotation layers a schema may enable.
VALID_LAYERS = ("phases", "outcome", "reward", "instruction")

#: A starting taxonomy for manipulation. Deliberately a *default*, not a fixed
#: list: a navigation or locomotion episode has entirely different phases, and
#: a schema that forced these on them would be unusable.
DEFAULT_PHASES = [
    {"name": "reach", "color": "#4ECDC4"},
    {"name": "grasp", "color": "#FFD93D"},
    {"name": "transport", "color": "#6C8AE4"},
    {"name": "place", "color": "#95E1A3"},
    {"name": "retract", "color": "#C9A0DC"},
]

#: Outcome labels. Three, not two: "partial" is the modal result in real robot
#: data and forcing it into success or failure destroys the signal that makes
#: the dataset worth annotating.
DEFAULT_OUTCOMES = ["success", "partial", "failure"]

#: Why it failed. From the failure taxonomies used across manipulation
#: benchmarks; a project can replace it wholesale.
DEFAULT_FAILURE_CAUSES = [
    "missed grasp",
    "object slipped",
    "collision",
    "wrong object",
    "wrong placement",
    "timeout / stalled",
    "unsafe motion",
    "other",
]

#: Keyboard shortcuts. Chosen not to collide with the media keys the timeline
#: binds (space, arrows) or with the shared `h` / `Shift+H` class-visibility
#: keys that label-visibility.js owns.
TOOL_KEYS = {
    "phase": "p",
    "reward": "r",
    "select": "v",
}


def generate_episode_annotation_layout(annotation_scheme):
    """
    Generate HTML for an embodied-episode annotation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - source_field: Item field holding the episode path
              (default: "episode")
            - episode_field: Item field selecting within a multi-episode
              source — an index for LeRobot, a demo key for HDF5
              (default: "episode_index")
            - layers: Which of phases / outcome / reward / instruction
            - phases: Phase taxonomy, as strings or {name, color, key_value}
            - outcomes: Outcome labels (default success/partial/failure)
            - failure_causes: Cause taxonomy for a non-success outcome
            - reward_range: [min, max] for the reward curve (default [0, 1])
            - series_shown: Which series lanes to draw, by name. Omit for all.
            - max_lanes: Cap on drawn lanes (default 8) — a 14-joint arm plus
              velocities is 28 lanes and none of them is legible
            - min_phases / max_phases

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme):
    # The grid reads data-grid-columns; without this the scheme's
    # `layout:` block is silently discarded and it renders at one column.
    layout_attrs = generate_layout_attributes(annotation_scheme)
    schema_name = annotation_scheme.get("name", "episode_annotation")
    logger.debug("Generating episode annotation layout for schema: %s",
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

    phases = _process_labels(annotation_scheme.get("phases", DEFAULT_PHASES))
    outcomes = annotation_scheme.get("outcomes", DEFAULT_OUTCOMES)
    causes = annotation_scheme.get("failure_causes", DEFAULT_FAILURE_CAUSES)

    reward_range = annotation_scheme.get("reward_range", [0.0, 1.0])
    if (not isinstance(reward_range, (list, tuple))
            or len(reward_range) != 2
            or float(reward_range[1]) <= float(reward_range[0])):
        raise ValueError(
            f"reward_range must be [min, max] with max > min in schema: "
            f"{schema_name}")

    escaped_name = escape_html_content(schema_name)
    description = escape_html_content(annotation_scheme.get("description", ""))

    config = {
        "schema": schema_name,
        "sourceField": annotation_scheme.get("source_field", "episode"),
        "episodeField": annotation_scheme.get("episode_field",
                                              "episode_index"),
        "layers": layers,
        "phases": phases,
        "phaseKeys": {p["name"]: p.get("key_value") for p in phases},
        "outcomes": list(outcomes),
        "failureCauses": list(causes),
        "rewardRange": [float(reward_range[0]), float(reward_range[1])],
        "seriesShown": annotation_scheme.get("series_shown"),
        "maxLanes": int(annotation_scheme.get("max_lanes", 8)),
        "minPhases": annotation_scheme.get("min_phases", 0),
        "maxPhases": annotation_scheme.get("max_phases"),
        "toolKeys": TOOL_KEYS,
    }

    html = f"""
    <div class="episode-annotation-container annotation-form" data-schema="{escaped_name}" data-annotation-type="episode_annotation" data-schema-name="{escaped_name}" {layout_attrs}>
        <fieldset>
            <legend>{description}</legend>

            <p class="episode-instruction" id="episode-instruction-{escaped_name}"></p>

            <!-- Video streams. Several, synchronized: a wrist camera shows the
                 grasp and an overhead shows whether the arm was anywhere near
                 the object, and a phase boundary is often only visible in one
                 of them. -->
            <div class="episode-streams" id="episode-streams-{escaped_name}"
                 role="group" aria-label="Camera streams"></div>

            <div class="episode-transport" role="toolbar"
                 aria-label="Playback and annotation tools">
                <button type="button" class="episode-play" aria-pressed="false">
                    <span aria-hidden="true">▶</span> Play
                </button>
                <span class="episode-time" aria-live="off">0.00 s</span>
                <span class="episode-frame"></span>
                {_tool_buttons(layers)}
            </div>

            <!-- The timeline: phase lanes, the reward curve, and one lane per
                 numeric series, all on the same time axis as the video. -->
            <div class="episode-timeline"
                 id="episode-timeline-{escaped_name}"></div>

            {_outcome_block(escaped_name, outcomes, causes)
             if "outcome" in layers else ""}

            {_instruction_block(escaped_name)
             if "instruction" in layers else ""}

            <p class="episode-status" id="episode-status-{escaped_name}"
               aria-live="polite"></p>

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
                if (typeof EpisodeAnnotationManager === 'undefined') {{
                    setTimeout(initWhenReady, 100);
                    return;
                }}
                var container = document.querySelector(
                    '.episode-annotation-container[data-schema="{escaped_name}"]');
                if (!container || container.annotationManager) return;

                var manager = new EpisodeAnnotationManager(
                    '{escaped_name}', {json.dumps(config)});
                container.annotationManager = manager;
                try {{
                    manager.init();
                }} catch (err) {{
                    // The manager is attached before init so a re-entrant call
                    // cannot build a second one, which means a throw in init
                    // leaves a half-built manager that every readiness check
                    // still accepts. Surfacing it turns a silently dead
                    // timeline into one that says why.
                    var status = document.getElementById(
                        'episode-status-{escaped_name}');
                    if (status) {{
                        status.textContent =
                            'Episode timeline failed to start: ' + err.message;
                        status.setAttribute('data-kind', 'error');
                    }}
                    console.error('[episode] init failed', err);
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

    return html, _keybindings(phases, layers, schema_name)


def _tool_buttons(layers):
    """
    Tool buttons for the layers that have a drawing mode.

    `outcome` and `instruction` are forms, not tools — they have no timeline
    gesture — so they get no button. A disabled-looking button for something
    that is not a mode is worse than no button.
    """
    out = []
    if "phases" in layers:
        out.append(
            '<button type="button" class="tool-btn" data-tool="phase" '
            'aria-pressed="false" title="Draw a phase segment (p)">'
            '<span aria-hidden="true">▭</span> Phase</button>')
    if "reward" in layers:
        out.append(
            '<button type="button" class="tool-btn" data-tool="reward" '
            'aria-pressed="false" title="Draw the reward curve (r)">'
            '<span aria-hidden="true">📈</span> Reward</button>')
    out.append(
        '<button type="button" class="tool-btn" data-tool="select" '
        'aria-pressed="false" title="Select and edit (v)">'
        '<span aria-hidden="true">▣</span> Select</button>')
    return "\n".join(out)


def _outcome_block(escaped_name, outcomes, causes):
    """
    The per-episode outcome form.

    The failure-cause select is present but disabled until a non-success
    outcome is picked, rather than appearing on selection: a control that
    materialises changes the layout under the pointer, and the annotator has to
    re-find where they were.
    """
    outcome_inputs = "\n".join(
        f'<label class="episode-outcome-option">'
        f'<input type="radio" name="episode-outcome-{escaped_name}" '
        f'value="{escape_html_content(str(o))}"> '
        f'{escape_html_content(str(o))}</label>'
        for o in outcomes)
    cause_options = "\n".join(
        f'<option value="{escape_html_content(str(c))}">'
        f'{escape_html_content(str(c))}</option>' for c in causes)

    return f"""
            <div class="episode-outcome" role="group"
                 aria-label="Episode outcome">
                <span class="episode-outcome-legend">Outcome</span>
                {outcome_inputs}
                <label class="episode-cause-label">
                    <span>Cause</span>
                    <select class="episode-cause"
                            id="episode-cause-{escaped_name}" disabled>
                        <option value="">—</option>
                        {cause_options}
                    </select>
                </label>
            </div>
    """


def _instruction_block(escaped_name):
    """
    Hindsight relabelling: what the robot *actually* did.

    The single most valuable annotation for robot data after the phases, and
    the cheapest: a failed attempt at "put the block in the bowl" is a perfect
    demonstration of "push the block to the left", and relabelling turns a
    discarded episode into training data. The dataset's own instruction stays
    visible above, unedited — overwriting it would destroy the pairing that
    makes the relabel informative.

    The range fields are filled from the selected phase rather than typed. An
    annotator asked to enter two timestamps by hand will either guess or go and
    read them off the transport, and both are slower and worse than a button.
    """
    return f"""
            <div class="episode-instruction-edit" role="group"
                 aria-label="Hindsight relabelling">
                <label for="episode-relabel-{escaped_name}">
                    What did the robot actually do? (optional)
                </label>
                <textarea id="episode-relabel-{escaped_name}"
                          class="episode-relabel" rows="2"
                          placeholder="e.g. pushed the block to the left"
                          ></textarea>
                <div class="episode-relabel-range">
                    <button type="button" class="episode-relabel-align">
                        Align to selected phase
                    </button>
                    <span class="episode-relabel-span" aria-live="polite"
                          >whole episode</span>
                </div>
            </div>
    """


def _keybindings(phases, layers, schema_name):
    """
    Shortcuts, with tool keys taking precedence over phase keys.

    A phase whose ``key_value`` collides with a tool key keeps its binding and
    the collision is logged — the project convention is to warn and continue,
    because a dropped shortcut is discovered by an annotator mid-task.
    """
    bindings = []
    taken = set()

    if "phases" in layers:
        bindings.append({"key": TOOL_KEYS["phase"], "description": "Phase tool"})
        taken.add(TOOL_KEYS["phase"])
    if "reward" in layers:
        bindings.append({"key": TOOL_KEYS["reward"],
                         "description": "Reward tool"})
        taken.add(TOOL_KEYS["reward"])
    bindings.append({"key": TOOL_KEYS["select"], "description": "Select"})
    taken.add(TOOL_KEYS["select"])

    if "phases" in layers:
        for phase in phases:
            key = phase.get("key_value")
            if not key:
                continue
            if key in taken:
                logger.warning(
                    "Schema '%s': phase '%s' uses key '%s', which is already a "
                    "tool shortcut. The phase keeps the binding; press the "
                    "tool button instead.", schema_name, phase["name"], key)
            taken.add(key)
            bindings.append({"key": key,
                             "description": f'Select {phase["name"]}'})

    return bindings

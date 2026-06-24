# Multimodal-Agent Annotation

Agents increasingly act in modalities beyond text and static images — they drive
GUIs, watch video, hold spoken conversations. These schemas (the M-series,
multimodal half) give human raters surfaces purpose-built for those traces, beyond
Potato's existing [image](../image_annotation.md), [audio](../audio_annotation.md),
[video](../video_annotation.md), and [web-agent](agent_traces.md) displays.

## GUI / computer-use trajectory (`gui_trajectory`)

Evaluate a computer-use / GUI / OS agent step by step (OSWorld, NeurIPS 2024;
ScreenSpot-Pro; AndroidWorld). Each step shows the **screenshot** the agent saw and
the **action** it took; the annotator judges the action (correct / wrong element /
wrong action / hallucinated) and, when the step carries click coordinates, sees a
grounding marker on the screenshot to check whether the click landed on the right
element. Generalizes the web-agent display to any pixel/DOM GUI agent.

```yaml
annotation_schemes:
  - annotation_type: gui_trajectory
    name: gui_review
    description: "For each step: was the action correct and did the click land right?"
    steps_key: steps
    screenshot_key: screenshot   # field on each step holding an image URL / data-URI
    action_key: action           # field holding the action text
    coord_space: normalized      # normalized (0..1) | pixels — for the x/y grounding marker
    verdict_options: [correct, wrong_element, wrong_action, hallucinated]
```

Each step may provide `screenshot`, `action`, and optional `x`/`y` (or a nested
`click: {x, y}`) for the grounding marker. Stored as a list of
`{index, step, verdict, notes}`, keyed by `index`. Example:
`examples/agent-traces/gui-trajectory/` (uses self-contained inline-SVG screenshots).

## Related documentation

- [Multi-Agent Team Annotation](multi_agent_annotation.md) — team-structure schemas
- [Agent Traces](agent_traces.md) — the base trace displays
- [Trajectory Evaluation](trajectory_eval.md) — per-step error annotation

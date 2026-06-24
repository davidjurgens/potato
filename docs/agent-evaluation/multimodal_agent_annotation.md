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

## Voice / full-duplex interaction (`voice_interaction`)

Annotate a spoken human↔agent conversation for turn-taking and barge-in handling
(Full-Duplex-Bench v1–v3, 2503.04721…; τ-Voice, 2603.13686). A **dual-track
timeline** (user lane + agent lane) places each turn by its start/end time and
highlights **overlap regions** where both speakers talk at once; the annotator
classifies each overlap (agent should respond / should resume / backchannel /
uncertain) and rates the overall turn-taking. The source audio plays inline when an
`audio` URL is provided.

```yaml
annotation_schemes:
  - annotation_type: voice_interaction
    name: turn_taking
    description: "Classify each barge-in/overlap and rate the overall turn-taking."
    turns_key: turns           # list of {speaker, start, end, text} (seconds)
    speaker_key: speaker
    user_speakers: [user, human, caller]   # everything else is treated as the agent
    overlap_labels: [agent_should_respond, agent_should_resume, backchannel, uncertain]
    rating_scale: 5
    # audio_key: audio         # optional per-instance audio URL to enable the player
```

Overlaps between turns of different speakers are computed at render time (no manual
setup). Stored as `{"overlaps": {idx: label}, "rating": int}`. Example:
`examples/agent-traces/voice-interaction/`.

## Interleaved multimodal reasoning (`multimodal_reasoning`)

Rate an interleaved **text ↔ image ↔ tool ↔ action** reasoning trace step by step
(Multimodal RewardBench 2, 2512.16899; Zebra-CoT). Each step is a typed block,
rendered in-line by its type; the annotator judges each step's coherence — does the
reasoning follow from the image and prior steps, or is the visual *hallucinated*?

```yaml
annotation_schemes:
  - annotation_type: multimodal_reasoning
    name: reasoning_review
    description: "Judge each step: coherent reasoning and grounded visuals?"
    steps_key: steps
    type_key: type     # each step's 'type': text | image | tool | action (inferred if absent)
    verdict_options: [coherent, incoherent, visual_hallucination, uncertain]
```

Each step may carry `text`/`content`, `image`/`image_url` (+`caption`), or
`tool`/`args`. Stored as a list of `{index, step, type, verdict, notes}`, keyed by
`index`. Example: `examples/agent-traces/multimodal-reasoning/` (uses inline-SVG
images, including a deliberate visual-hallucination case to annotate).

## Aligned-transcript speech errors (`speech_transcript`)

Annotate a time-aligned speech transcript segment by segment for ASR/TTS and
speech-quality errors (Speak&Improve 2025, 2412.11986; NVSpeech). Each segment
`{start, end, text, speaker?}` is a card showing its timestamp and text; the
annotator tags errors (ASR error / TTS artifact / mispronunciation / disfluency …)
and can type the corrected transcript. Segment-level complement to the turn-taking
view in [`voice_interaction`](#voice--full-duplex-interaction-voice_interaction).

```yaml
annotation_schemes:
  - annotation_type: speech_transcript
    name: speech_errors
    description: "Tag speech errors on each segment and correct the transcript where needed."
    segments_key: segments       # list of {start, end, text, speaker?}
    error_types: [asr_error, tts_artifact, mispronunciation, disfluency]
    allow_correction: true
    # audio_key: audio           # optional per-item audio URL to enable the player
```

Stored as a list of `{index, start, end, errors, correction}`, keyed by `index`.
Example: `examples/agent-traces/speech-transcript/`.

## Related documentation

- [Multi-Agent Team Annotation](multi_agent_annotation.md) — team-structure schemas
- [Agent Traces](agent_traces.md) — the base trace displays
- [Trajectory Evaluation](trajectory_eval.md) — per-step error annotation

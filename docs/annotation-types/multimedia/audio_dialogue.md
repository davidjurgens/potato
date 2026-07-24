# Audio Dialogue (Podcast Turn Annotation)

The `audio_dialogue` **display type** renders a spoken, multi-speaker transcript
as a chat of colored speaker bubbles synced to an audio file. Each turn carries a
start/end time and a ▶ button that plays *just that turn*; a sticky transport bar
plays the whole episode and highlights / auto-scrolls the active turn.

It is designed for podcast, interview, meeting, and call-center annotation where
you want to combine:

- **per-turn ratings** (e.g. "what is the category of this turn?"),
- **whole-conversation ratings** (e.g. overall quality),
- **span highlighting inside turns** (e.g. "highlight the questions"),
- **cross-turn linking** (e.g. link each answer to the question it answers), and
- **speaker assignment** for undiarized transcripts (the annotator picks the
  speaker, which recolors and repositions the bubble).

`audio_dialogue` is a display, so it lives under `instance_display.fields` and
composes with ordinary annotation schemes — it does not replace them.

## Quick start

```bash
python potato/flask_server.py start examples/audio/audio-dialogue/config.yaml -p 8000
```

## Data format

The field value is a dict with an `audio` URL/path and a `turns` list:

```json
{
  "id": "ep_001",
  "title": "Episode 1",
  "conversation": {
    "audio": "https://example.com/ep1.mp3",
    "turns": [
      {"turn_id": "t0", "speaker": "host",  "start": 0.0,  "end": 6.5,  "text": "Welcome back."},
      {"turn_id": "t1", "speaker": "guest", "start": 6.5,  "end": 12.0, "text": "Glad to be here."},
      {"turn_id": "t2",                      "start": 12.0, "end": 18.0, "text": "Undiarized — annotator assigns."}
    ]
  }
}
```

A turn with no `speaker` renders as **Unassigned**. Click any turn's speaker name
to open a menu and assign (or reassign) it — including an **＋ Add speaker…**
action, so annotators aren't limited to a fixed roster.

### Accepted transcript shapes

The transcript is normalized on render by
`potato/server_utils/transcript_ingest.py`, so `turns` may instead be supplied as:

| Shape | How it's recognized | Speaker |
|-------|---------------------|---------|
| **Native turn JSON** | `{"turns": [{speaker, start, end, text}]}` | as given |
| **WhisperX / diarized JSON** | `{"segments": [{start, end, text, speaker}]}` | diarization label |
| **Plain Whisper JSON** | `{"segments": [{start, end, text}]}` | none → undiarized |
| **WebVTT** | a string starting with `WEBVTT` | `<v Name>` tag or `Name:` prefix, else none |
| **SRT** | a SubRip string | `Name:` prefix, else none |
| **SPoRC** | speaker-turn rows (`turn_text`, `start_time`, `end_time`, `speaker` list) | `inferred_speaker_name` / `inferred_speaker_role` (`neither`→undiarized) |

**SPoRC** ([Structured Podcast Research Corpus](https://huggingface.co/datasets/blitt/SPoRC))
turn rows ingest directly, in both the JSONL (camelCase: `turnText`/`startTime`/
`endTime`/`mp3url`/`inferredSpeakerName`/`inferredSpeakerRole`) and parquet
(snake_case: `turn_text`/`start_time`/…) forms. The `speaker` list is unwrapped, the
audio source falls back to `mp3url`, and `neither`/`NO_INFERRED_SPEAKER`/
`NO_INFERRED_ROLE` sentinels render as undiarized. Set
`speaker_key: inferredSpeakerName` (or `inferredSpeakerRole`) so bubbles show real
host/guest labels; unlabeled turns become undiarized for the annotator to assign.
SPoRC is gated — accept its terms, then export an episode's turns with the `sporc`
package or `huggingface_hub`/`datasets` + a token (e.g. `speakerTurnDataSample.jsonl.gz`).
`examples/audio/audio-dialogue-sporc/` is a **real** episode (real recorded audio +
SPoRC's own transcript/timings); note SPoRC diarization is coarse — real turns can be
multi-minute and include sub-second boundary fragments.

Timestamps may be numbers (seconds) or `HH:MM:SS[.,]mmm` strings. A stable
`turn_id` is assigned to every turn (`t{index}` when absent) — it is the key
used to persist per-turn ratings and speaker assignments, so keep it stable
across re-ingests.

> ASR and diarization (Whisper, WhisperX, pyannote) run **upstream** of Potato.
> Potato ingests their output; it does not transcribe or diarize.

## Configuration

```yaml
instance_display:
  fields:
    - key: conversation
      type: audio_dialogue
      label: "Transcript"
      span_target: true              # enable span highlighting inside turns
      display_options:
        audio_key: audio             # sub-key of the field value holding the audio URL
        turns_key: turns             # sub-key holding the turn list
        speaker_key: speaker         # per-turn speaker key
        text_key: text               # per-turn text key
        scroll_height: 460px         # fixed-height scroll pane
        show_timestamps: true
        playback_rates: [1, 1.25, 1.5, 2]
        speakers:                    # roster: stable color + side per speaker
          - {id: host,  name: Host,  color: "#7c3aed", side: left}
          - {id: guest, name: Guest, color: "#059669", side: right}
```

| Option | Default | Description |
|--------|---------|-------------|
| `audio_key` | `audio` | Sub-key of the field value holding the audio URL/path. |
| `turns_key` | `turns` | Sub-key holding the turn list (also accepts `segments`). |
| `speaker_key` / `text_key` | `speaker` / `text` | Per-turn keys. |
| `speakers` | `[]` | Roster: `{id, name, color, side}`. Unlisted speakers get a deterministic color and alternating side. |
| `allow_speaker_assignment` | `auto` | `auto` enables click-to-assign whenever there are undiarized turns to label or a roster to correct; `true` forces it on, `false` off. Annotators can always add new speakers. |
| `scroll_height` | `480px` | Height of the scrollable transcript pane. |
| `show_timestamps` | `true` | Show `mm:ss–mm:ss` per turn. |
| `playback_rates` | `[1, 1.25, 1.5, 2]` | Options in the speed selector. |

### Per-turn ratings

Any turn-capable scheme (`radio`, `multiselect`, `likert`, `slider`, `select`,
`textbox`, `number`) can be attached per turn with `turn_level: true` and a
`turn_binding.field` pointing at the display field:

```yaml
annotation_schemes:
  - annotation_type: radio
    name: turn_category
    description: "Category of this turn"
    labels: [claim, question, answer, aside]
    turn_level: true
    turn_binding:
      field: conversation
```

See [instance_display.md](../instance_display.md) and the turn-level framework
for the full set of `turn_binding` filters (speakers, step types, ranges, …).

### Whole-conversation ratings

Ordinary (non-`turn_level`) schemes render in the form panel and apply to the
whole instance:

```yaml
  - annotation_type: likert
    name: overall_quality
    description: "Overall conversation quality"
    size: 5
```

### Span highlighting + cross-turn linking

Set `span_target: true` on the field, then add `span` and (optionally)
`span_link` schemes. Because span ids are global per instance, a link can
connect a span in one turn to a span in another (e.g. answer → question):

```yaml
  - annotation_type: span
    name: highlights
    description: "Highlight questions and answers"
    target_field: conversation
    labels:
      - {name: question, key_value: "q"}
      - {name: answer,   key_value: "a"}

  - annotation_type: span_link
    name: qa_links
    description: "Link each answer to the question it answers"
    span_schema: highlights
    link_types:
      - {name: answers, directed: true,
         allowed_source_labels: [answer], allowed_target_labels: [question]}
```

## Controls

| Control | Action |
|---------|--------|
| ▶ on a turn | Play only that turn (stops at the turn's end). |
| ▶ / ⏸ in the bar | Play / pause the whole episode. |
| ■ in the bar | Stop and rewind to the start. |
| Scrubber | Seek anywhere in the episode. |
| Speed | Change playback rate. |
| Click a speaker name | Open the speaker menu to assign / reassign the turn, or **＋ Add speaker…**; the bubble recolors and repositions live. Added speakers persist and appear for other turns. |

During playback the current turn is highlighted and auto-scrolled into view;
scrolling the pane yourself pauses auto-scroll for a few seconds.

## How annotations are stored

- **Timing offsets are input, not output** — they come from the transcript and
  are never written back.
- **Per-turn ratings** and **speaker assignments** persist as versioned JSON in a
  hidden input, keyed by the stable `turn_id`
  (`{"v":1,"schema_type":...,"turns":{"t3":{...}}}`). Speaker assignments are
  stored under the schema name `{field_key}_speakers`.
- **Spans** persist as `[span_dict, value]` pairs with the field key and character
  offsets; **links** persist via `SpanLink`.

> **Span-offset stability.** Span offsets are computed over the transcript text.
> Speaker assignment only changes CSS (color, position, avatar/name via
> pseudo-content) and never the transcript text or DOM order, so spans stay
> aligned across assignment and reload. Prefer `radio`/`multiselect`/`select`
> for per-turn schemes on a span-target field; a per-turn `slider`'s live value
> readout adds mutable text and can shift offsets on very long transcripts.

## Related

- [Instance Display](../instance_display.md)
- [Audio Annotation (waveform segmentation)](audio_annotation.md)
- [Span Linking](../text/span_linking.md)

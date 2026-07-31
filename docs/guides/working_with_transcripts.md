# Working with Transcripts

You have speech, and you have a transcript of it — from Whisper, from a cloud ASR API, or downloaded alongside a video. This guide takes you from those files to a running annotation task.

Two starting points are covered. They converge once the transcript is in Potato:

- **[Path A](#path-a-you-ran-whisper)** — you ran an ASR model over audio you have.
- **[Path B](#path-b-you-have-subtitle-files)** — you have subtitle or caption files.

For the format-by-format reference, see [Transcript Format Support](../annotation-types/multimedia/transcript_formats.md).

!!! note "Potato does not transcribe"
    ASR and diarization run upstream. Potato ingests their output. This guide tells you which upstream options matter, but the transcription itself happens before Potato sees anything.

---

## Path A: you ran Whisper

### Keep the right output file

Whisper writes several files, and the choice matters more than it looks:

```bash
whisper interview_01.mp3 --model medium --output_format json --word_timestamps True
```

| File | Contains | Useful? |
|------|----------|---------|
| `.json` | Segments with start/end times, optionally per-word timings | **Yes — use this** |
| `.srt` / `.vtt` | Segments with timings, no metadata | Yes, works fine |
| `.tsv` | Start/end in milliseconds plus text | Yes |
| `.txt` | Text only, **no timings** | No — nothing to sync to audio |

If you only kept the `.txt`, you cannot recover the alignment without re-running. That is the single most common reason a transcript arrives in Potato as one undifferentiated block.

### Decide about diarization

Plain Whisper does not label speakers. Every turn arrives unassigned, which is fine for content annotation and painful for anything speaker-related.

To get speakers, run [WhisperX](https://github.com/m-bain/whisperX), which wraps Whisper with pyannote diarization:

```bash
whisperx interview_01.mp3 --model medium --diarize --output_format json
```

Its output has a `speaker` field per segment (`SPEAKER_00`, `SPEAKER_01`, …) and Potato reads it directly.

If you skip diarization, annotators can assign speakers in the interface instead. That is a reasonable trade for a small corpus, and often more accurate than automatic diarization on messy audio.

### Build the data file

Point the CLI at your output folder:

```bash
potato transcripts ./whisper_out --media-dir ./audio -o data/interviews.json
```

Transcripts are paired to media by basename — `interview_01.json` finds `interview_01.mp3` — and item ids come from the filename, with Whisper's doubled `interview_01.mp3.json` extension handled correctly.

Check what it understood before committing to it:

```bash
potato transcripts ./whisper_out --dry-run
```

```
Scanned 3 file(s):
  interview_01.json      Whisper JSON      42 turns    891.4s  undiarized
  interview_02.json      WhisperX JSON     51 turns   1120.8s  2 speaker(s): SPEAKER_00, SPEAKER_01
  interview_03.json      Whisper JSON      38 turns    754.2s  undiarized

3 item(s), 131 turn(s).
```

If a file reports `plain text` or zero turns, that is your problem file — see [Troubleshooting](../annotation-types/multimedia/transcript_formats.md#troubleshooting).

Skip to [Setting up the task](#setting-up-the-task).

---

## Path B: you have subtitle files

### Getting captions

[`yt-dlp`](https://github.com/yt-dlp/yt-dlp) downloads subtitles with or without the media:

```bash
# Human-written subtitles, if the uploader provided any
yt-dlp --write-subs --sub-langs en --skip-download <URL>

# Auto-generated captions
yt-dlp --write-auto-subs --sub-langs en --sub-format vtt --skip-download <URL>
```

Potato reads `vtt`, `srt`, `json3`, `ttml`, and the `srv1`/`srv2`/`srv3` variants, so any `--sub-format` works.

### Know what you're getting

Human-written subtitles and auto-captions are very different inputs:

| | Human subtitles | Auto-captions |
|---|---|---|
| Punctuation | Yes | No, or unreliable |
| Sentence boundaries | Meaningful | Arbitrary |
| Speakers | Sometimes (`<v Name>` tags) | Never |
| Word timings | No | Yes (in `json3`) |
| Verbatim | Often condensed for reading | Closer to verbatim |

The practical consequence: **do not design a sentence-level annotation scheme over auto-captions.** Their cue boundaries fall wherever the caption window filled up, not where a sentence ended. Annotate the caption windows as-is, or re-segment upstream.

### About the media

Subtitles are small and easy to redistribute; the video usually is not. Two options:

```bash
# Media hosted somewhere your annotators can reach
potato transcripts ./captions --media-url-prefix https://cdn.example.org/video -o data/talks.json

# Media downloaded locally
yt-dlp -f 'ba' -x --audio-format mp3 -o './audio/%(id)s.%(ext)s' <URL>
potato transcripts ./captions --media-dir ./audio -o data/talks.json
```

Transcripts without media still annotate fine — annotators just read instead of listening. If that is the plan, say so in your instructions, because annotators otherwise assume the missing player is a bug.

Check your rights before redistributing anything you did not create.

---

## Setting up the task

Both paths land here. The generated data file looks like this:

```json
{
  "id": "interview_01",
  "conversation": {
    "audio": "audio/interview_01.mp3",
    "turns": [
      {"turn_id": "t0", "speaker": "SPEAKER_00", "start": 0.0, "end": 6.5,
       "text": "Welcome back."}
    ]
  }
}
```

A matching config (`potato transcripts --emit-config` prints this for you):

```yaml
annotation_task_name: "Interview Annotation"
task_dir: .
data_files:
  - data/interviews.json

item_properties:
  id_key: id
  text_key: conversation

instance_display:
  fields:
    - key: conversation
      type: audio_dialogue
      label: "Transcript"
      span_target: true
      display_options:
        show_timestamps: true
        allow_speaker_assignment: auto

annotation_schemes:
  - annotation_type: span
    name: topics
    description: "Highlight topic mentions"
    target_field: conversation
    labels:
      - name: policy
      - name: personal
```

Run it:

```bash
python potato/flask_server.py start config.yaml -p 8000
```

### Skipping the conversion step

You do not have to run the CLI at all. A data file can point straight at sidecar files:

```json
{"id": "int_001", "conversation": {"audio": "media/int_001.mp3",
                                   "transcript": "media/int_001.srt"}}
```

Potato reads the file, detects the format, and normalizes it on render. This keeps your transcripts as files you can diff and re-export, rather than baking them into a data blob.

---

## Choosing a display

| Use it when | Type | What it gives you |
|---|---|---|
| Annotating dialogue turns | `audio_dialogue` display | Speaker bubbles, per-turn playback, per-turn schemes, spans, speaker assignment |
| Checking transcription accuracy | `speech_transcript` scheme | Segment cards with error tags and a correction box |
| Studying overlap and interruption | `voice_interaction` scheme | Dual-track timeline, barge-in and overlap marking |
| Multi-layer time-aligned coding | `tiered_annotation` scheme | ELAN-style tiers, seedable from the transcript |
| Marking regions on the waveform | `audio_annotation` scheme | Waveform segmentation, independent of any transcript |

All of them accept every supported transcript format.

## Assigning speakers by hand

When turns arrive undiarized, each bubble renders as *Unassigned* with a picker. Choosing a speaker recolors and repositions the bubble, and the assignment persists with the annotations.

Define a roster so speakers get stable names and colors:

```yaml
display_options:
  allow_speaker_assignment: auto
  speakers:
    - id: interviewer
      name: "Interviewer"
      color: "#7c3aed"
      side: left
    - id: participant
      name: "Participant"
      color: "#059669"
      side: right
```

Set `allow_speaker_assignment: true` to allow reassignment even when the source did label speakers — useful for correcting diarization errors.

## Annotating across turns

Spans work over the whole transcript, so a highlight can start mid-turn and the offsets stay stable when speakers are reassigned. Add `span_link` to connect spans across turns, such as an answer to the question that prompted it:

```yaml
  - annotation_type: span_link
    name: qa_links
    description: "Link each answer to its question"
    span_schema: highlights
    link_types:
      - name: answers
        directed: true
```

Per-turn schemes attach a question to every turn:

```yaml
  - annotation_type: radio
    name: turn_type
    description: "What is this turn doing?"
    labels: [question, answer, aside]
    turn_level: true
    turn_binding:
      field: conversation
```

## Getting the annotations back out

Standard JSON/JSONL/CSV export works as usual. For speech work, EAF and TextGrid keep the time alignment:

```bash
python -m potato.export --config config.yaml --format eaf --output ./out/
python -m potato.export --config config.yaml --format textgrid --output ./out/
```

Both round-trip: annotate in Potato, refine in ELAN or Praat, and re-ingest the result.

## Related documentation

- [Transcript Format Support](../annotation-types/multimedia/transcript_formats.md) — every format, in detail
- [Audio Dialogue](../annotation-types/multimedia/audio_dialogue.md) — the speaker-bubble display
- [Audio Annotation](../annotation-types/multimedia/audio_annotation.md) — waveform segmentation
- [Tiered Annotation](../annotation-types/multimedia/tiered_annotation.md) — multi-tier timelines
- [Export Formats](../data-export/export_formats.md) — EAF, TextGrid, and the rest

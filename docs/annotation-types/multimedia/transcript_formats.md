# Transcript Format Support

Potato reads transcripts from ASR pipelines, subtitle files, and forced aligners, and normalizes all of them into one turn model before display. This page is the reference for which formats work, how each one is detected, and what each contributes.

For the task-oriented walkthrough — running Whisper, downloading YouTube captions, and getting either into an annotation project — see [Working with Transcripts](../../guides/working_with_transcripts.md).

## Where transcription happens

ASR and diarization run **upstream** of Potato. Potato ingests their output; it does not transcribe or diarize. Run Whisper, WhisperX, pyannote, or a cloud API first, then point Potato at the result.

(The one exception is unrelated: [Think-Aloud](../../advanced/think_aloud.md) runs local faster-whisper to capture spoken rationales from annotators. That is a recording feature, not transcript ingestion.)

## Supported formats

Detection is based on **content**, not file extension, so the same data works inlined into a data file or read from a sidecar.

### ASR output

| Format | Detected by | Speakers | Word timings |
|--------|-------------|----------|--------------|
| Whisper JSON | `segments` array | No | Yes, with `--word_timestamps` |
| WhisperX / diarized JSON | `segments` with `speaker` | Yes | Yes |
| whisper.cpp JSON | `transcription` array | No | No |
| Whisper TSV | `start`/`end`/`text` header | No | No |
| AWS Transcribe | `results.items` or `results.audio_segments` | Yes | Yes |
| Deepgram | `results.channels` or `results.utterances` | Yes, with `diarize=true` | Yes |
| AssemblyAI | `text` plus `words`/`utterances` | Yes, with `speaker_labels` | Yes |
| Rev.ai | `monologues` array | Yes | Yes |
| SPoRC | `turn_text`/`turnText` rows | Yes, inferred | No |

### Subtitles and captions

| Format | Detected by | Speakers |
|--------|-------------|----------|
| SubRip (`.srt`) | Cue arrows, `,mmm` separator | From a `Name:` prefix |
| WebVTT (`.vtt`) | `WEBVTT` header | From `<v Name>` tags or a `Name:` prefix |
| SubStation Alpha (`.ass`, `.ssa`) | `[Script Info]` / `Dialogue:` | From the `Name` field |
| TTML / DFXP | `<tt>` root element | From a `speaker`/`agent` attribute |
| YouTube srv1/srv2/srv3 | `<transcript><text>` XML | From a `Name:` prefix |
| YouTube json3 | `events` array | None (auto-captions have no speakers) |

### Alignment and linguistic annotation

| Format | Detected by | Speakers |
|--------|-------------|----------|
| NIST CTM | Whitespace columns, numeric start/duration | From the channel field |
| Praat TextGrid | `File type = "ooTextFile"` | One tier per speaker |
| ELAN EAF | `ANNOTATION_DOCUMENT` root | From `PARTICIPANT`, else the tier id |

Both long and short TextGrid serializations are handled. EAF resolves `ALIGNABLE_ANNOTATION` and `REF_ANNOTATION` against the `TIME_ORDER` table, and reads the media reference out of the header.

### Everything else

A bare list of `{speaker, start, end, text}` dicts, a `{"audio": ..., "turns": [...]}` object, and a plain untimed paragraph (rendered as one bubble) all work.

## Not supported

No parser exists for these. Convert them first.

- SAMI (`.smi`), MicroDVD (`.sub`), SubViewer (`.sbv`)
- Transcriber (`.trs`), EXMARaLDA, CHAT/CHILDES (`.cha`)
- Montreal Forced Aligner and Gentle native output (export CTM or TextGrid instead)
- Azure Speech, Google Speech-to-Text, Whisper API `verbose_json` with unusual wrappers
- Speaker diarization files (RTTM) as a standalone input

Word-level confidence is preserved where the source provides it, but Potato does not currently display it.

## The normalized turn model

Everything above becomes:

```json
{
  "audio": "media/interview_01.mp3",
  "turns": [
    {
      "turn_id": "t0",
      "speaker": "host",
      "start": 0.0,
      "end": 6.5,
      "text": "Welcome back.",
      "words": [{"word": "Welcome", "start": 0.0, "end": 0.4, "confidence": 0.99}],
      "confidence": 0.97
    }
  ]
}
```

`words` and `confidence` appear only when the source carried them. `speaker` is `null` for undiarized turns, which render as *Unassigned* with a speaker picker.

`turn_id` is the persistence key for per-turn annotations and speaker assignments. It comes from an explicit string `turn_id`/`step_id` in the source, otherwise `t{index}`. It is deterministic: the same file always produces the same ids, so annotations survive reloads.

!!! warning "Time units differ between tools"
    Whisper and Deepgram use float seconds; AssemblyAI, whisper.cpp offsets, and Whisper's TSV use integer milliseconds. Potato converts at the boundary so everything downstream is seconds. If your own preprocessing mixes these up, timings come out 1000× wrong.

## Sidecar files

A field value that is a short single-line path ending in a known transcript extension is read from disk rather than treated as content:

```json
{
  "id": "int_001",
  "conversation": {
    "audio": "media/int_001.mp3",
    "transcript": "media/int_001.srt"
  }
}
```

Paths resolve relative to `task_dir` and go through the same path-security validation as every other configured path, so a data file cannot read outside the project.

Recognized extensions: `.srt` `.vtt` `.webvtt` `.json` `.json3` `.srv1` `.srv2` `.srv3` `.ttml` `.dfxp` `.xml` `.ass` `.ssa` `.tsv` `.ctm` `.TextGrid` `.eaf` `.txt`

Override the heuristic when your data genuinely holds one-line inline transcripts:

```yaml
display_options:
  transcript_is_path: auto   # auto (default) | true | false
```

## Configuration

### Display: `audio_dialogue`

```yaml
instance_display:
  fields:
    - key: conversation
      type: audio_dialogue
      label: "Transcript"
      span_target: true
      display_options:
        audio_key: audio
        turns_key: turns
        speaker_key: speaker
        text_key: text
        transcript_is_path: auto
        show_timestamps: true
        allow_speaker_assignment: auto
        scroll_height: 460px
```

### Schemes

`speech_transcript`, `voice_interaction`, and `tiered_annotation` read a transcript from the instance record and accept every format on this page.

```yaml
annotation_schemes:
  - annotation_type: speech_transcript
    name: transcript_review
    description: "Mark transcription errors"
    segments_key: segments       # record field holding the transcript

  - annotation_type: voice_interaction
    name: barge_in
    description: "Mark overlaps and barge-in"
    turns_key: turns
```

Tiered annotation can pre-populate a tier from a transcript, so annotators correct an existing alignment instead of re-segmenting speech by hand:

```yaml
  - annotation_type: tiered_annotation
    name: tiers
    source_field: audio_url
    media_type: audio
    transcript_field: asr_output   # opt-in; omit to start from a blank timeline
    transcript_tier: utterance     # defaults to the first tier
    tiers:
      - name: utterance
        labels:
          - name: speech
            color: "#7c3aed"
```

Seeded annotations are not saved until the annotator makes a real edit, so nothing is attributed to someone who only looked at the instance.

## Building a data file: `potato transcripts`

Convert a folder of transcripts into a ready-to-annotate data file:

```bash
# Pair transcripts to media by basename
potato transcripts ./whisper_out --media-dir ./audio -o data/interviews.json

# Media served from elsewhere
potato transcripts './captions/*.vtt' \
  --media-url-prefix https://cdn.example.org/audio -o data/talks.json

# What did it detect? Writes nothing.
potato transcripts ./whisper_out --dry-run
```

| Option | Purpose |
|--------|---------|
| `-o`, `--output` | Where to write. Required unless `--dry-run`. |
| `--format` | `json` (default) or `jsonl`. |
| `--media-dir` | Directory of media to pair by basename. |
| `--media-url-prefix` | Base URL for media instead of local files. |
| `--field` | Item field the transcript goes under (default `conversation`). |
| `--id-prefix` | String prepended to every generated id. |
| `--speaker-key` | Source key holding the speaker label. |
| `-r`, `--recursive` | Recurse into subdirectories. |
| `--dry-run` | Report detected format and turn count per file. |
| `--emit-config` | Also print a matching `config.yaml` fragment. |

Item ids come from the filename, with a trailing media extension stripped — Whisper's `interview_01.mp3.json` becomes `interview_01`, not `interview_01.mp3`.

## Exporting back out

Annotations export to [ELAN EAF and Praat TextGrid](../../data-export/export_formats.md), so a transcript can round-trip: ingest, annotate in Potato, export, refine in ELAN, and re-ingest.

```bash
python -m potato.export --config config.yaml --format eaf --output ./out/
python -m potato.export --config config.yaml --format textgrid --output ./out/
```

## Troubleshooting

### Everything is one big bubble

The format was not recognized and fell through to the plain-paragraph fallback. Run `potato transcripts <file> --dry-run` — if it reports `plain text`, the timings were never parsed. Usually this means the file is a Whisper `.txt` (which has no timings at all) rather than the `.json` or `.srt`.

### No speakers, everything is "Unassigned"

The source has no speaker labels. Whisper alone does not diarize, and neither do YouTube auto-captions. Either run diarization upstream (WhisperX, pyannote, or a cloud API with `diarize=true`), or let annotators assign speakers in the interface — `allow_speaker_assignment: auto` turns the picker on automatically when turns arrive undiarized.

### Timings are 1000× off

Something upstream mixed seconds and milliseconds. whisper.cpp `offsets`, AssemblyAI, and Whisper TSV are all milliseconds. If you preprocessed the file yourself, check the conversion.

### The transcript path shows up as the transcript text

The sidecar file could not be read, so the path was displayed as content. Check that it resolves relative to `task_dir` and does not point outside the project. Server logs record the specific reason.

### A one-line inline transcript is being read as a filename

Set `transcript_is_path: false` on the display field.

## Example project

`examples/audio/transcript-formats/` renders six formats side by side — SubRip, WebVTT, Whisper JSON, YouTube json3, Praat TextGrid, and Deepgram — each loaded from a sidecar file.

```bash
python potato/flask_server.py start examples/audio/transcript-formats/config.yaml -p 8000
```

## Related documentation

- [Working with Transcripts](../../guides/working_with_transcripts.md) — the end-to-end walkthrough
- [Audio Dialogue](audio_dialogue.md) — the speaker-bubble display
- [Audio Annotation](audio_annotation.md) — waveform segmentation
- [Tiered Annotation](tiered_annotation.md) — ELAN-style multi-tier timelines
- [Export Formats](../../data-export/export_formats.md) — EAF and TextGrid export

# Think-Aloud Mode: Voice Rationales, Zero LLM

Before LLMs, the gold standard for understanding judgment was the think-aloud protocol —
and it never survived contact with annotation tooling. Think-Aloud Mode lets annotators
just *talk* while they work. The verbatim transcript is stored as the rationale
(deliberately un-summarized: paraphrasing a think-aloud protocol would contaminate the
very artifact you're collecting), and labels can be committed by voice using a set
phrasing detected by a **rule-based parser** — no LLM anywhere in the pipeline.

Speech-to-text runs **fully locally** via faster-whisper (CPU real-time with the 39 MB
`tiny.en` model). No cloud APIs, no per-token cost, nothing leaves the machine.

## How it works

1. The annotator taps **🎤 Think aloud** (bottom-center pill) and speaks freely.
   Recording carries across Next/Previous — tap once and keep talking for the
   whole session; only **Stop** ends it. The chunk in progress when they
   navigate is flushed rather than dropped.
2. Audio is captured in complete ~6-second chunks and transcribed locally.
3. To commit a label by voice, they use one of the accepted phrasings:
   - *"I label this **Polite**"* / *"I'd call it **neutral**"*
   - *"My answer is **impolite**"*
   - *"Final answer: **polite**"* / *"I go with **neutral**"*
4. Detection auto-selects the matching option in the UI (the normal save pipeline
   fires), and the pill confirms: **Heard: Impolite ✓**. Saying a new phrase later
   changes the label — last commitment wins, including when the correction reuses
   the same phrasing ("I label this polite. I label this neutral.").
5. With `require_spoken_label: on`, pressing **Next** with no committed label triggers
   a one-time nudge showing the expected phrasing (a second Next passes through, and
   clicking labels always works).

Everything mentioned while *thinking* is ignored — "this seems polite, but…" commits
nothing. Only the set phrasings commit, which is what makes rule-based parsing
sufficient. Mishearings are absorbed by fuzzy label matching ("in polite" → *Impolite*).

## What you get

- **Verbatim rationale streams** aligned to each (annotator, instance), with the label
  phrase separated out — the transcript minus the commitment phrase is the rationale.
- **Deterministic hesitation signals**: silent-chunk counts and filler-word counts
  (configurable lexicon), computed with arithmetic, not models.
- **A review page** (`/thinkaloud/review`, admin) with every session's transcript,
  voice-committed label, confidence, and hesitation stats.
- Hands-free annotation as a side effect — including genuine accessibility and
  RSI relief.

## Setup

```bash
pip install faster-whisper   # local STT; first recording downloads the model (~39 MB)
python potato/flask_server.py start examples/advanced/think-aloud/config.yaml -p 8000 --debug
```

The browser needs microphone permission (localhost counts as a secure context).

## Configuration

```yaml
thinkaloud:
  enabled: true
  schema: politeness          # scheme whose labels can be spoken (default: first radio)
  stt: auto                   # faster_whisper | mock | auto
  model: tiny.en              # whisper size: tiny.en is CPU real-time; base.en is sturdier
  chunk_seconds: 6            # recording chunk length
  require_spoken_label: true  # nudge on Next without a committed label
  # stems:                    # override accepted phrasing regexes (advanced)
  # fillers: [um, uh, hmm, i guess, maybe]
  # language: en
```

| Option | Default | Description |
|--------|---------|-------------|
| `stt` | `auto` | `faster_whisper` (local), `mock` (tests/dev; echoes a provided text field), `auto` picks faster_whisper and errors helpfully if missing. |
| `model` | `tiny.en` | Any faster-whisper model id. |
| `chunk_seconds` | `6` | Each chunk is a complete audio file (MediaRecorder restarts per chunk — continuation fragments are not independently decodable). |
| `stems` | built-ins | Regex stems for accepted phrasings; each captures the words that follow. |
| `fillers` | um, uh, hmm, … | Lexicon for the hesitation counter. |
| `require_spoken_label` | `true` | One-time Next-button nudge when nothing was committed. |

## Data and API

Transcripts persist to `{output_annotation_dir}/thinkaloud/transcripts.jsonl`
(append-only, one record per chunk).

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/thinkaloud/api/chunk` | POST | session | Multipart audio chunk → transcript + detection |
| `/thinkaloud/api/text` | POST | session | Text chunk (no-audio path: tests, degraded input) |
| `/thinkaloud/api/state` | GET | session | Session aggregate for an instance |
| `/thinkaloud/review` | GET | admin | Transcript review page |
| `/thinkaloud/api/export` | GET | admin | All sessions as JSON |

## Design notes

- The parser runs over a rolling window of the last two chunks, so phrases that
  straddle a chunk boundary ("my answer …" / "… is neutral") still detect.
- Label matching is exact → prefix → `difflib` (≥ 0.8), preferring exact matches and
  higher similarity, so "polite" never fuzzy-collides with "Impolite".
- Adding an STT backend (e.g. Vosk) means subclassing `STTBackend` in
  `potato/thinkaloud/stt.py` and registering it in `create_stt`.

## Related documentation

- [Quality Control](../workflow/quality_control.md) — hesitation signals complement attention checks
- [Behavioral Tracking](../administration/behavioral_tracking.md) — timing analytics

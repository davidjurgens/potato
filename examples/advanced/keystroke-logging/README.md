# Keystroke Logging Example

Records **how** annotators write their free-text responses — pauses, bursts,
revisions, pastes — without ever recording **what** they type. Lets you tell a
composed response from one that was transcribed or pasted in from an LLM.

```bash
python potato/flask_server.py start examples/advanced/keystroke-logging/config.yaml -p 8000
```

## What this example shows

Three free-text prompts about contested decisions, with a radio recommendation
and two rationale textareas. Every free-text field is instrumented.

## Try it yourself

1. **Type** a rationale normally, at a human pace, pausing to think.
2. **Paste** a paragraph from another application into the second box.
3. Switch to another tab for ~15 seconds, come back, and paste again.
4. Click **Next**, then **Previous** — navigation flushes the typing session.

Then look at what was recorded:

```bash
sqlite3 examples/advanced/keystroke-logging/project.sqlite "
  SELECT schema_name, keystrokes, final_chars, paste_events,
         round(pasted_fraction,2) AS pasted,
         round(silent_insert_ratio,2) AS silent,
         round(iki_log_cv,3) AS rhythm_cv,
         max_blur_before_insert_ms AS away_before_insert,
         json_extract(flags,'\$.flag_names') AS flags
  FROM typing_sessions;"
```

You should see:

| Behaviour | What shows up |
|---|---|
| Typed normally | `silent ≈ 0`, healthy `rhythm_cv`, no flags |
| Pasted | `pasted ≈ 1`, `silent ≈ 1`, `paste_dominant` + `silent_insertion` |
| Away, then pasted | Also `offscreen_composition`, with `away_before_insert ≈ 15000` |

Copying **the passage itself** into your answer is deliberately *not* flagged —
that is ordinary annotator behaviour, and the paste is classified as
`instance_text` rather than `external`.

## The admin view

Open `/admin`, go to the **Behavioral** tab, and scroll to **Writing Process**.
Each flagged session lists the evidence behind it, not just a verdict.

## Exporting

```bash
# Summary features alongside the annotations (needs export_include_typing_dynamics: true)
python -m potato.export.cli examples/advanced/keystroke-logging/config.yaml --format csv

# Raw content-blind event streams
python -m potato.export.cli examples/advanced/keystroke-logging/config.yaml --format keystrokes
```

## Before using this on real participants

Typing dynamics are behavioural data about identifiable people, and the
detection flags have innocent explanations (fast typists, mobile keyboards,
dictation, assistive technology).

Read [the ethics guide](../../../docs/advanced/keystroke_logging_ethics.md) and
the [false positives section](../../../docs/advanced/writing_process_detection.md#false-positives)
first. Flags are evidence for human review — never wire them to automatic
rejection.

## Documentation

- [Keystroke Logging](../../../docs/advanced/keystroke_logging.md)
- [Writing-Process Detection](../../../docs/advanced/writing_process_detection.md)
- [Keystroke Logging Ethics](../../../docs/advanced/keystroke_logging_ethics.md)

# Longitudinal & Multi-Session Studies

Patterns for running studies where the same participants return — across
browser sessions within one study, or across multiple studies over time.

## Resuming within a study

Potato keys all state to the participant ID from the URL (`PROLIFIC_PID` or
your platform's parameter), not to the browser session. A participant who
closes their browser and clicks the study link again:

1. Is logged back into the same account (same URL parameter value).
2. Keeps their exact item assignment and ordering.
3. Keeps every annotation they already submitted.

Nothing needs to be configured for this — it is how URL-direct login works.
Annotations are saved to the server on every change (debounced), and the done
page performs a final server-side flush before offering the return-to-platform
redirect, so completion can never race the last save.

## Joining output with platform records

Each participant's `user_state.json` in your `output_annotation_dir` includes
a `crowd_metadata` block captured at arrival:

```json
{
  "crowd_metadata": {
    "provider": "prolific",
    "worker_id": "5f8a...",
    "session_id": "61b2...",
    "study_id": "60d0..."
  }
}
```

Use `session_id` to join with Prolific's submission export (it is the
submission ID), and `study_id` to distinguish waves when several studies point
at the same Potato server.

## Multi-wave studies on Prolific

The standard pattern (also used by other tools):

1. **One Prolific study per wave**, all pointing at the same Potato server (or
   one server per wave if the task differs).
2. Recruit wave 2 only from wave-1 completers: in Prolific, use a custom
   allowlist (Participants → previous study → invite to new study) or a
   participant group.
3. Because Potato keys accounts to `PROLIFIC_PID`, the same participant gets
   the same identity in every wave. If each wave should annotate different
   items, run separate task directories (one config + output dir per wave) so
   assignments don't carry over.
4. Record `study_id` per wave (captured automatically in `crowd_metadata`) to
   separate waves in analysis.

## Failure and screen-out codes

If you use [attention checks](../workflow/quality_control.md) with a block
threshold, participants who get blocked see the provider's failure code on the
done page instead of the success code:

```yaml
crowdsourcing:
  provider: prolific
  prolific:
    completion:
      code: "C1SUCCESS"
      failed_code: "C1FAILED"     # configure as a screen-out code on Prolific
```

On Prolific, create the failure code as a second completion code with a
screen-out action so those submissions are routed appropriately (and paid a
screen-out reward if you use fixed screen-out payments).

## Related documentation

- [Prolific integration](prolific_integration.md)
- [Crowdsourcing setup](crowdsourcing.md)
- [Quality control](../workflow/quality_control.md)

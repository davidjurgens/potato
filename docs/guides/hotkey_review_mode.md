# Hotkey Review Mode

Turn any annotation task into a keyboard-driven rapid review queue: schemas
keep their key bindings, and `review_mode` auto-advances to the next instance
the moment the current one is complete — press a key, the page moves on.

Use it for high-volume verdict passes over agent traces, judge spot-checks,
or triage sweeps where mouse round-trips dominate annotation time.

## Configuration

```yaml
review_mode:
  enabled: true
  auto_advance: true      # default true when enabled
  advance_on: complete    # complete (default) | required
  delay_ms: 350           # pause before advancing so the selection is visible
```

| Option | Values | Meaning |
|--------|--------|---------|
| `enabled` | bool | master switch |
| `auto_advance` | bool | navigate to the next instance when complete |
| `advance_on` | `complete` | every annotation schema on the page has a value |
| | `required` | all schemas with required validation are filled (use when optional note fields exist) |
| `delay_ms` | int | delay before advancing (default 350ms) |

Pair it with keyboard-bound schemas:

```yaml
annotation_schemes:
  - annotation_type: radio
    name: verdict
    description: "Verdict (1/2/3)"
    labels: [good, acceptable, bad]
    sequential_key_binding: true    # 1 = good, 2 = acceptable, 3 = bad
```

## Example

```bash
python potato/flask_server.py start examples/advanced/hotkey-review/config.yaml -p 8000
```

Press `1`/`2`/`3` — the annotation saves and the queue advances.

## Notes

- Auto-advance never skips validation: with `advance_on: required`, the page
  only advances when the same check that gates the Next button passes.
- Annotations save through the normal debounced pipeline before navigation
  (the navigation handler flushes pending saves).
- The `triage` schema's own `auto_advance` option remains independent; use
  `review_mode` for multi-schema pages.

## Related Documentation

- [Signal-Based Triage Queue](../agent-evaluation/triage_queue.md)
- [Agent Task Recipes](../agent-evaluation/agent_task_recipes.md)

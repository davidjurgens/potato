# Trajectory Correction → SFT/DPO training data

Let annotators **edit** an agent trace — rewrite a wrong reasoning step, fix a typo'd tool
call, or strengthen a weak final answer — and export the `(original, corrected)` pair as
supervised fine-tuning (SFT) targets and DPO preference pairs.

This is the editing counterpart to [Trajectory Evaluation](../trajectory-evaluation/) (which
*scores* steps). It mirrors Labelbox's "Agent Trajectory Editor" and Datadog's "edited outputs":
the dominant workflow for turning agent eval into training data.

![Trajectory correction editor](../../../docs/img/screenshots/trajectory_edit.png)

## Run it

```bash
python potato/flask_server.py start examples/agent-traces/trajectory-correction/config.yaml -p 8000
# or, skipping login, straight to annotation:
python potato/flask_server.py start examples/agent-traces/trajectory-correction/config.yaml -p 8000 --debug --debug-phase annotation
```

Each step shows the **Original** text and an editable **Corrected** box pre-filled with it. As you
type, a live word/character diff highlights what changed and an "✎ edited" flag appears. "Reset"
restores the original. The final answer is editable too.

## Data format

Each instance has an `id`, `task_description`, a `steps` list (each step has `action` and
`thought`), and a `final_answer`:

```json
{
  "id": "traj_001",
  "task_description": "Find the current weather in San Francisco.",
  "steps": [
    {"thought": "I should look up the weather.", "action": "web_search(queyr='SF weather')"},
    {"thought": "Open the first result.", "action": "open_url(results[0])"}
  ],
  "final_answer": "It is sunny."
}
```

The schema reads steps from `steps_key` (here `steps`) and edits the fields in `editable_fields`
(here `action`). Set `editable_fields: [action, thought]` to also edit reasoning, and
`edit_final_answer: true` to edit the final answer.

## Export SFT / DPO data

After annotating, export with the `trajectory_correction` format. It writes three files to the
output directory:

- **`trajectory_corrections.json`** — every record: `original_trace`, reconstructed
  `corrected_trace`, and per-field `edits` (with edit distances and reasons).
- **`trajectory_sft.jsonl`** — one line per *edited* trace:
  `{"prompt": <task>, "completion": <corrected_trace>}`.
- **`trajectory_dpo.jsonl`** — one line per *edited* trace:
  `{"prompt": <task>, "chosen": <corrected_trace>, "rejected": <original_trace>}`.

Unedited traces are counted but never produce SFT/DPO records (no point training on an unchanged
trajectory) — the skipped count is reported in the export stats/warnings.

## Configuration reference

| Option | Default | Description |
|--------|---------|-------------|
| `steps_key` | `steps` | Instance field holding the step list. |
| `step_text_key` | `action` | Default editable field per step. |
| `editable_fields` | `[step_text_key]` | Which step fields get an editor (e.g. `[action, thought]`). |
| `show_diff` | `true` | Show the live word-level diff. |
| `show_edit_distance` | `true` | Show words/chars changed. |
| `allow_reset` | `true` | Show a per-field "Reset to original" button. |
| `require_reason_on_edit` | `false` | Add a per-field "reason for edit" input. |
| `edit_final_answer` | `false` | Add an editor for the final answer. |
| `final_answer_key` | `final_answer` | Instance field holding the final answer. |

## Related

- [Trajectory Correction guide](../../../docs/agent-evaluation/trajectory_correction.md)
- [Trajectory Evaluation](../trajectory-evaluation/) — per-step scoring/error taxonomy
- [Three-Pane Trace Eval](../continuous-eval/) — read-only reasoning | calls | answer view

# Single-Select Answer Integrity

Schemas that hold exactly one answer — `radio`, `likert` and `confidence` — are
guaranteed to persist exactly one value per instance (and per survey page). This page
explains the guarantee, how to recover the revision history, and how to repair data
collected with Potato 2.7.1 or earlier.

## The guarantee

Annotations are stored keyed by `(schema, label_name)`. A `radio`, `likert` or
`confidence` schema renders one input per option, each with its own `label_name`, so
changing an answer writes a **different** key rather than overwriting the previous one.
Potato now removes the superseded entry as part of the write, in every workflow phase:

| Phase | Storage |
|---|---|
| Annotation | `instance_id_to_label_to_value[<instance>]` |
| Consent, instructions, training, prestudy, poststudy | `phase_to_page_to_label_to_value[<phase>][<page>]` |

The rule is enforced in three places, so no code path can bypass it:

1. `POST /updateinstance` clears the schema before re-writing (both the current and
   legacy payload formats), as does the deprecated `POST /submit_annotation`.
2. `UserState.add_label_annotation()` drops older entries for the same single-select
   schema and logs a warning naming the superseded value.
3. The exporters resolve any duplicates that already exist on disk.

### Which types are affected

Exclusivity comes from the schema registry's `single_select` flag, not a hardcoded
list. Exactly three types set it:

```python
from potato.server_utils.schemas.registry import schema_registry
schema_registry.get_single_select_types()   # ['confidence', 'likert', 'radio']
```

Other types are deliberately excluded:

- `select`, `slider`, `number`, `vas`, `ranking` and the JSON-blob types emit a single
  fixed `label_name` (`"select-one"`, `"slider"`, `"_data"`, …), so re-answering
  already overwrites the same key.
- `multiselect`, `multirate`, `semantic_differential`, `constant_sum`, `range_slider`,
  `soft_label` and `rubric_eval` legitimately store several labels per schema.
- `pairwise` and `bws` store their answers in hidden inputs that the client does not
  unconditionally re-send, so clearing them could drop real data.

### `free_response` is preserved

A `radio` or `multiselect` schema configured with `has_free_response` stores a second
label, `free_response`, on the *same* schema. That is a separate answer, not a
competing option, and it survives the purge. A likert's `bad_text_label` option does
**not** — it is a genuine member of the radio group, so selecting it replaces the scale
point.

## Recovering the revision history

Enforcing one stored answer does not discard the fact that an annotator changed their
mind. Every change is recorded in the behavioral trail, which Potato writes to
`user_state.json` under `instance_id_to_behavioral_data[*].annotation_changes`:

```json
{
  "timestamp": 1785513168.42,
  "schema_name": "confidence",
  "old_label": "5", "old_value": "5",
  "label_name": "4", "new_value": "4",
  "action": "select",
  "source": "user",
  "phase": "annotation", "page": null
}
```

`phase` and `page` are stamped server-side, so changes made on survey pages — which all
share the `__phase_page__` instance id — remain attributable to the page they happened
on.

To export the trail as CSV alongside your annotations:

```yaml
export_include_annotation_changes: true
```

This writes `annotation_changes.csv` with one row per change:

```csv
user_id,instance_id,phase,page,timestamp,schema,old_label,old_value,new_label,new_value,action,source
u1,b1_035,annotation,,1785513168.42,confidence,5,5,4,4,select,user
```

It is off by default: the trail is considerably larger than the annotations and carries
fine-grained interaction detail that not every study wants to distribute.

## Exported columns

`phase_responses.csv` gains a `sequence` column giving each response's position within
its page, so ordering is documented rather than implied by row layout:

```csv
user_id,phase,page,sequence,schema,label_name,value
69fc7c57,prestudy,prestudy,0,concept_familiarity,Eher vertraut,Eher vertraut
```

If a single-select schema is found holding more than one value (only possible in data
written before this fix), the export does not silently emit an ambiguous row:

- `annotations.csv` keeps the per-label columns **and** adds a canonical `{schema}`
  column with the resolved final answer.
- `phase_responses.csv` tags each row with `superseded: True`/`False`.
- The export result carries a warning naming every affected user, instance and schema.

## Repairing data collected before the fix

Potato 2.7.1 and earlier could persist every option an annotator clicked. Use the
repair tool to rewrite affected state files:

```bash
# Report what would change; nothing is written
potato repair-annotations path/to/config.yaml

# Apply, keeping a user_state.json.bak beside each rewritten file
potato repair-annotations path/to/config.yaml --apply

# Apply without backups
potato repair-annotations path/to/config.yaml --apply --no-backup
```

Sample output:

```
Single-select schemas: confidence, native_language, nlp_familiarity, veracity

Single-select annotation repair — DRY RUN (nothing written)
  Users scanned    : 15
  Users repaired   : 11
  Values collapsed : 37
     from timestamps: 34
     from order     : 3

  Detail:
    [annotation] u1 / b1_035 / confidence: kept '4', dropped ['5'] (behavioral)
    [prestudy] u2 / prestudy / concept_familiarity: kept 'No', dropped ['Yes'] (order)  <-- heuristic
```

### Why "last value wins" is not enough

`instance_id_to_label_to_value` is a dictionary keyed by label. It serializes in
**first-touch** order and updates in place, so its last entry is not necessarily the
final answer. A click sequence of 5 → 4 → 5 → 4 → 5 persists as `["5", "4"]`: reading
the last entry gives `4`, but the annotator settled on `5`.

The repair tool therefore resolves each group from the **timestamped**
`annotation_changes` trail wherever it exists (reported as `behavioral`), and only falls
back to persisted order (`order`) when no trail is available. Every fallback is listed
individually and summarised in a closing warning, so you can review those rows rather
than trusting them silently. Interaction tracking is unconditional, so the trail is
present for most studies.

## Related documentation

- [Export Formats](export_formats.md) — all supported output formats
- [Behavioral Tracking](../advanced/behavioral_tracking.md) — what else the interaction
  trail records
- [Configuration](../configuration/configuration.md) — full config reference

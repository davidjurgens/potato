# Per-Cohort Schema Assignment

Different annotator cohorts can be shown **different annotation schemes** (or a
subset), defined once and bound to the cohorts you already use for
[batch assignment](task_assignment.md). This answers the question "can different
users get different questions?" — yes, without running separate projects.

The global `annotation_schemes` list remains the default and fallback, so
existing single-schema configs are unchanged.

## Concepts

- **Cohort** — a batch-assignment group (`batch_assignment.groups`), identified
  by `name`. Cohorts already scope *which items* a user annotates; per-cohort
  schemes extend them to scope *which schemes* a user sees.
- **Scheme set** — a named, reusable list of schemes (`scheme_sets`) you can bind
  to multiple cohorts.
- **Binding** — a group's `schemes` field. It may be:
  - a **scheme-set name** (`schemes: minimal`),
  - a **list of global scheme names** (a subset: `schemes: [sentiment, topic]`),
    or
  - a **list of inline scheme dicts** (or a mix of names and inline dicts).

## Configuration

```yaml
# Global schemes: the default/fallback for anyone not in a cohort with its own set.
annotation_schemes:
  - {annotation_type: radio, name: sentiment, description: "Sentiment", labels: [pos, neg]}
  - {annotation_type: radio, name: topic,     description: "Topic",     labels: [a, b]}
  - {annotation_type: radio, name: quality,   description: "Quality",   labels: [good, bad]}

# Optional: named, reusable scheme sets (reference global scheme names or inline dicts).
scheme_sets:
  minimal: [sentiment]

assignment_strategy: batch
batch_assignment:
  groups:
    - name: cohortA
      annotators: [alice@example.com]
      data_file: cohortA.csv
      schemes: minimal                     # named scheme-set -> only "sentiment"
    - name: cohortB
      annotators: [bob@example.com]
      data_file: cohortB.csv
      schemes: [sentiment, topic]          # subset of global schemes by name
    - name: cohortC
      data_file: cohortC.csv               # no `schemes` -> global fallback
```

With this config:

- **alice** (cohortA) sees only `sentiment`.
- **bob** (cohortB) sees `sentiment` and `topic`.
- anyone in **cohortC** or in no cohort sees the full global set.

### Auto-assigned cohorts

Per-cohort schemes also work with `auto_assign_annotators: true`. **Give each
group a `name`** so the schema binding resolves — unnamed auto-groups fall back
to the global schemes.

## How it works

At startup, Potato bakes one annotation page template per cohort that binds its
own scheme set (plus the default). At request time, a user's cohort is resolved
from their batch-group membership (explicit `annotators` list or auto-assign
pin), and they are served their cohort's page and schemes. Submission validation
and the AI-assistant lookups also resolve against the user's cohort schemes.

## Adjudication

Adjudicators review every cohort, so the adjudication interface renders the
**union** of all cohort scheme sets (deduplicated by scheme name).

## Edge cases

- **No cohort / unknown cohort** → global `annotation_schemes` and the default
  page.
- **Overlapping scheme names across cohorts** → each cohort resolves
  independently; the adjudicator union keeps the first definition of a given
  name.
- **Custom `task_layout`** → a single custom layout is shared by all cohorts and
  is not differentiated per cohort (a warning is logged). Use auto-generated
  layouts to differentiate cohort schemes.
- **API-key-only admins** (no logged-in username) → see the global/default page.

## Validation

Invalid bindings are rejected at config load: an unknown scheme name, an unknown
scheme-set name, or a malformed inline scheme all raise a clear
`ConfigValidationError`.

## Related

- [Task Assignment](task_assignment.md)
- [Roles & Permissions](../auth-users/roles_and_permissions.md)
- [Heterogeneous Coverage](heterogeneous_coverage.md)
- [Conditional Logic](../configuration/conditional_logic.md) (show/hide schemes by prior answers)

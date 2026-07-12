# Psychometrics: Labels with Error Bars

Potato can treat your annotation study as what it actually is — a measurement
instrument. The psychometrics layer fits an item response theory (IRT) model
**live**, as annotations stream in, jointly estimating:

- the **true label of every item as a probability** (not a raw vote count),
- every **annotator's ability** (with a standard error),
- every **item's difficulty**, and
- a per-item **discrimination diagnostic** that flags likely codebook bugs.

No gold labels are needed, and no LLM is involved anywhere: the model
(a multiclass generalization of GLAD, Whitehill et al. 2009) bootstraps
everything from the pattern of agreement itself, the same way standardized
tests learn which questions are hard without anyone decreeing it. Fits are
deterministic and take milliseconds at annotation-study scale.

On top of the model sit four tools:

| Tool | Where |
|------|-------|
| Adaptive routing (serve each label where it buys the most information) | `assignment_strategy: psychometric` |
| Live dashboard (abilities, difficulty, codebook flags, savings) | `/psychometrics/dashboard` |
| Enriched export (every label with a posterior probability + interval) | `/psychometrics/api/export` |
| Study designer (power analysis before you spend) | `python -m potato.psychometrics.design` |

## Quick start

```bash
python potato/flask_server.py start examples/advanced/psychometrics/config.yaml -p 8000 --debug
# annotate a bit (or point the simulator at it), then open:
#   http://localhost:8000/psychometrics/dashboard
```

## Configuration

```yaml
# Adaptive routing is opt-in via the standard assignment strategy key.
# Omit this line to keep your existing strategy and use psychometrics as
# a pure analytics layer.
assignment_strategy: psychometric

# Give items a redundancy target so early-stopped items translate into
# concrete saved judgments on the dashboard.
num_annotators_per_item: 4

psychometrics:
  enabled: true
  schema: sarcasm            # scheme to model; default: first radio/likert scheme
  refit_interval: 5          # refit after this many new labels (fits are ~ms)
  min_observations: 20       # cold-start gate before adaptive routing engages
  min_annotators_per_item: 2 # never early-stop an item below this many annotators
  confidence_threshold: 0.95 # posterior at which an item counts as resolved
  cost_per_judgment: 0.08    # optional: expresses savings in currency
  discrimination_flag_threshold: -0.2  # codebook-bug flag sensitivity
```

Supported schemes are single-choice categorical: `radio` and `likert`
(likert points are treated as nominal categories). Multi-select schemes are
not modeled.

## What the model gives you

### Labels with error bars

Instead of `sarcastic (2 of 3 votes)`, the export says
`sarcastic, p = 0.94 [0.88 – 0.97]`. The probability is the model posterior —
which weighs *who* voted, not just how many — and the interval is a ±1
standard-error sensitivity band over the ability estimates. Downstream you
can train on soft labels, filter evaluation sets to high-confidence items,
or treat low-probability items as genuinely ambiguous rather than as noise.

### Annotator ability, honestly presented

Ability θ is estimated from agreement patterns: 1.0 is the prior for a new
annotator, 0 means the annotator's labels carry no information, and negative
values mean systematically wrong. Every estimate ships with a standard
error — an annotator with 12 labels has a wide whisker, and the dashboard
says so. **Never make personnel decisions from a wide whisker**; the
standard errors are approximate (Fisher information at the mode) and mildly
optimistic by construction.

### Difficulty and the codebook-bug detector

Item difficulty is estimated jointly with ability. The more useful signal is
**discrimination**: the correlation between annotator ability and answer
correctness on each item. When it is strongly *negative* — your best
annotators disagreeing with the crowd consensus — the guideline is usually
wrong or ambiguous for that item, not the annotators. The dashboard surfaces
these items in a "Likely codebook bugs" section; fix the instructions, then
revisit.

### Adaptive routing

With `assignment_strategy: psychometric`, when an annotator asks for work
the remaining items are ranked by the **exact one-step expected information
gain** of *that annotator* labeling *that item* — high-uncertainty items go
to high-ability annotators first, and items whose posterior already exceeds
`confidence_threshold` (with at least `min_annotators_per_item` annotators)
stop consuming budget. Compared with a fixed N-per-item design, the saved
judgments are counted on the dashboard (and priced, if you set
`cost_per_judgment`).

Two operational notes:

- **Cold start.** Until `min_observations` labels exist, assignment falls
  back to random — the model needs overlapping annotators before it can
  separate ability from difficulty. The dashboard shows a warming-up meter
  during this phase.
- **Batching.** Assignment happens when a user's queue tops up. Ranking is
  freshest when queues are short; very large per-user batches dilute
  adaptivity.

## Study designer: power analysis before you spend

Every annotation project guesses at "how many annotators per item?" The
designer answers it with a seeded Monte Carlo simulation using statistical
synthetic annotators:

```bash
python -m potato.psychometrics.design --items 500 --accuracy 0.75 \
    --classes 3 --target-ci 0.10 --cost 0.08
```

```
ann/item   alpha     95% interval   width  majority acc  judgments       cost
       2   0.392 [ 0.330,  0.439]   0.109         0.751       1000      80.00
       3   0.388 [ 0.338,  0.431]   0.093         0.864       1500     120.00  <- recommended
       ...
```

The recommendation is the smallest redundancy whose 95% interval on
Krippendorff's α is narrower than `--target-ci` — the cheapest design that
still yields a defensibly precise agreement estimate. The `--accuracy`
input is best measured with a small pilot. The same analysis is available
interactively on the dashboard, and as an admin API
(`GET /psychometrics/api/design`).

## Endpoints

All endpoints require admin access (RBAC `VIEW_ADMIN_DASHBOARD`; debug mode
and the shared admin API key pass):

| Endpoint | Purpose |
|----------|---------|
| `GET /psychometrics/dashboard` | Live dashboard |
| `GET /psychometrics/api/stats` | Dashboard aggregates (forces a fresh fit) |
| `GET /psychometrics/api/export` | Enriched export: posteriors, bands, abilities |
| `GET /psychometrics/api/design` | Power analysis (params: `items`, `accuracy`, `classes`, `target_ci`, `max_annotators`, `sims`, `cost`) |

## Relationship to MACE

Potato also ships [MACE](mace.md), which estimates annotator competence and
predicted labels as post-hoc analytics. The two are cousins from the same
literature, with different jobs:

| | MACE | Psychometrics |
|---|------|---------------|
| Annotator model | knowing-vs-guessing competence | continuous ability with standard errors |
| Item model | none | difficulty + discrimination (codebook-bug flags) |
| When it runs | batch analytics after N annotations | live, in the assignment loop |
| Drives assignment | no | yes — expected-information-gain routing + early stopping |
| Uncertainty on labels | entropy | posterior probability + sensitivity interval |
| Pre-study planning | no | Monte Carlo power analysis |

Use MACE for a quick competence readout on any categorical scheme (it also
covers `multiselect`); use psychometrics when you want difficulty-aware
measurement that acts on the study while it runs.

## Troubleshooting

- **Dashboard says "warming up" forever** — the model needs at least two
  distinct labels and overlapping annotators. With one annotator or
  unanimous labels the fit is degenerate by design; add annotators or lower
  `min_observations`.
- **`assignment_strategy: psychometric` but routing looks random** — that is
  the cold-start fallback; check the dashboard's warming-up meter and
  `min_observations`.
- **Abilities all near 1.0 with big whiskers** — not enough overlap yet;
  abilities separate as annotators accumulate shared items.
- **404 on `/psychometrics/...`** — the `psychometrics.enabled: true` block
  is missing from the config.

## Related documentation

- [MACE annotator competence](mace.md)
- [Task assignment strategies](task_assignment.md)
- [Quality control](../workflow/quality_control.md)
- [Crowdsourcing](../deployment/crowdsourcing.md)

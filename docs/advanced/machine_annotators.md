# Machine Annotators

A machine annotator is a rater that is a program rather than a person: an
annotation pipeline, a detector, a language model. Declaring one lets Potato
measure it as a rater — computing agreement between tools, routing their
conflicts to a human, estimating each one's reliability — without counting it
as a person in statistics that describe people.

This matters when several automated systems label the same data and no ground
truth exists to say which is right. Benchmarks of genome annotation pipelines,
OCR engines, ASR systems and LLM extractors all have that shape: the tools
disagree, the disagreement is measurable, and the question of who was right on
any given item goes unanswered.

## Why a declaration is needed

Without a declaration, machine output reaches Potato by one of two paths, and
neither measures it as a rater.

The importers refuse to write machine output into a user state at all, because
a fabricated user "would make machine output indistinguishable from human work
and fabricate agreement between annotators who never touched the item."
Imported predictions live in item data as pre-annotations, where no agreement,
adjudication or psychometric code can reach them.

The simulator does the opposite. It registers over HTTP, authenticates and
saves through the ordinary route, so an LLM-driven annotator gets a real user
state — and is counted as a person by `/admin/iaa`, MACE and the IRT engine,
because nothing on the state says it is not one.

A declaration fixes both. The importers' guard is against machine output posing
as a person, and a declared rater is a machine rater on the record.

## Configuration

```yaml
machine_annotators:
  enabled: true
  annotators:
    - id: prokka                  # the user id this rater annotates under
      kind: tool                  # tool | llm
      tool: prokka
      version: "1.14.6"
      database_version: "2023-05"
      run_date: "2024-11-03"

    - id: gpt4o_judge
      kind: llm
      endpoint_type: openai
      model: gpt-4o
      version: "2024-08-06"
```

| Field | Meaning |
|---|---|
| `id` | The user id the rater annotates under. This is the join key between the declaration and the state on disk. |
| `kind` | `tool` or `llm`. Anything else is accepted, logged, and treated as a machine — not being human is what the metrics depend on. |
| `tool`, `model`, `endpoint_type` | Which program produced the answers. |
| `version`, `database_version`, `run_date` | Which *version* of it, and when. |

Fill in the version fields. A benchmark of four genome annotation
tools could not analyse how annotations drifted between releases because the
prior annotation's date was never recorded: a re-run that finds 139 more
features cannot be told apart from a reference database that gained them.

### Absent means human

A participant with no declaration is a person. Every user state written before
this feature existed loads as human, so adding the block changes nothing for
raters you do not name, and a study with no `machine_annotators` block produces
the same output it produced before.

Disabling the block stops new stamping. It does not unmake origins already
written to disk, because a rater that was a tool last week was still a tool.

## Effects on the measurement surfaces

### Agreement

`/admin/iaa` reports three partitions instead of one:

| Partition | What it measures |
|---|---|
| `human_human` | Inter-human reliability. This is the headline. |
| `machine_machine` | Whether the tools agree with each other. |
| `pooled` | Everyone in one matrix. |

The headline figures cover humans only. The top-level number is read as
inter-human reliability, so if it pooled everyone, a run of the LLM simulator
against a live study would change it with nothing on the page to say why.

The pooled figure is still reported, under a name that says what it mixes. A
coefficient over a mixed human/machine reliability matrix is not an estimate of
either group's reliability — two groups that are each perfectly self-consistent
can pool to worse than chance, because the number is then describing the
distance between them.

The admin page says which raters were excluded and which versions produced
them, so an admin can see why the annotator count dropped.

`/admin/api/agreement` excludes machine raters for the same reason and lists
them under `machine_annotators_excluded`.

### MACE

MACE estimates per-annotator competence, and its output is used to decide whose
labels to trust. Declared machines are excluded with no opt-in: a competence
score for an annotation pipeline is a different claim from a competence score
for a person, and mixing them puts a tool's number beside a colleague's.

### Psychometrics (IRT)

The IRT engine is the exception, because modelling a tool's ability is the
point:

```yaml
psychometrics:
  enabled: true
  schema: sentiment
  include_machine_annotators: true
```

Off by default, so an existing study's estimates do not move when a machine
annotator is declared. On, the model fits an ability per rater and a difficulty
per item from the disagreement pattern alone, with no gold labels — which is
how you get a reliability estimate per tool on a corpus that has no ground
truth. Annotator rows carry an `origin` label for machine raters.

!!! warning "Correlated error"

    GLAD assumes raters err independently given the true label. Tools that
    share a reference database do not: they make the same mistake together,
    which inflates the apparent ability of whichever cluster is largest. An
    ability estimate over machine raters needs someone who knows which tools
    share evidence before it is published.

### Gold auto-promotion

Machine raters never count toward `gold_standards.auto_promote`, and no setting
lets them. Gold is what later annotators are graded against, and agreement
between tools that share evidence is correlated error. Enough people agreeing
still promotes an item, whatever the tools answered.

### Adjudication

```yaml
adjudication:
  enabled: true
  adjudicator_users: [curator]
  include_machine_annotators: true
  min_human_annotations: 0
```

Machines stay out of the queue unless `include_machine_annotators` is set,
which extends the exclusion the queue already applies to adjudicators.

`min_human_annotations` is a floor on *people*, counted separately from the
participant total. Zero is allowed: several tools and no human
annotator is a valid queue, because the adjudicator is the person in that
design.

Queue items carry `annotator_origins`, so a curator choosing between two labels
can see that one came from a tool and which version produced it. Decisions
record `source_origins` at the moment they are made, so a later config edit
cannot change what a past decision appears to have meant.

The final dataset distinguishes who agreed. A study with no machine rater still
writes `source: "unanimous"`; one with machine raters writes
`unanimous_machine` or `unanimous_mixed` where they apply, because several
tools agreeing is not the same as several people agreeing.

### Export

Every annotation record carries `_origin`, beside `_room` and `_typing`. Like
its siblings it is kept out of flattened columns by the tabular exporters.

## Getting machine output in

### From a run you already have

Import the predictions and declare the seeded rater:

```bash
python -m potato.importers \
  --input-format coco --input predictions.json \
  --output-dir myproject \
  --seed-user prokka --as-machine-annotator tool
```

The seeded state then carries an origin. Declare the same id under
`machine_annotators` in the project config so the server keeps the declaration
when it reloads that state.

Without `--as-machine-annotator`, `--seed-user` still fabricates an
undeclared annotator and still warns that its rows must be kept out of
agreement analysis.

### From a model running against the server

The simulator's `llm` and `agent` strategies drive a real endpoint. Declare the
user ids it will use:

```yaml
machine_annotators:
  enabled: true
  annotators:
    - {id: sim_user_0000, kind: llm, model: my-model}
    - {id: sim_user_0001, kind: llm, model: my-model}
```

The simulator warns at startup when a model-backed strategy is selected,
naming the ids that should be declared. It cannot fix the problem itself — the
roster lives in the target server's config, not the simulator's.

## Requiring every participant to be declared

By default an undeclared participant is treated as a person, which is what
makes the feature safe to add to a running study. A study that wants the
stronger guarantee can refuse annotations from anyone it does not recognise:

```yaml
machine_annotators:
  enabled: true
  require_declaration: true
  annotators:
    - {id: prokka, kind: tool, version: "1.14.6"}

user_config:
  allow_all_users: false
  users: [alice, bob]
```

A write is refused when the participant is neither declared under
`machine_annotators.annotators` nor on the human roster, and the annotator is
told to ask the administrator rather than being left with a save that silently
did nothing.

Two deliberate limits:

**It is checked where annotations are written, not at login, and never from a
request header.** A header asserting "I am a machine" is supplied by the
caller, so honouring one would let anybody opt out of the human count — the
opposite of the guarantee. Only the study's config can declare an origin.

**It requires a roster to compare against, and says so at load.** Under open
registration every username that registers becomes a valid account, so the
setting would have nothing to refuse, so the config is rejected at startup unless
`user_config.allow_all_users` is false and a roster is named — inline under
`user_config.users`, or as a file at `authentication.user_config_path`.

Consent, instruction and survey pages are exempt. Those are not dataset
annotations, and a rater that never reaches an item has nothing to contaminate.

## Prioritising what the tools disagree about

Cross-tool disagreement is a per-item number, so it drives the existing triage
queue with no new machinery. Compute it when the data is built, put it on the
item, and point `triage` at the field:

```yaml
triage:
  enabled: true
  signal_field: tool_disagreement

assignment_strategy: priority
```

`signal_field` is read as items are added, before any annotation exists, so it
works for a batch import: the contested items are served first and a human never opens the ones every tool already agreed on.

## Related

- [Heterogeneous Coverage](heterogeneous_coverage.md) — overlap samples, adaptive boost, and the agreement report
- [Psychometrics](psychometrics.md) — the IRT model and adaptive routing
- [MACE](mace.md) — competence estimation over human annotators
- [Task Assignment](task_assignment.md) — assignment strategies including `priority`

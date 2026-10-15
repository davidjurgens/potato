# Labeling engine

The labeling engine labels a dataset with models and uses people to measure
how often the models are wrong. You declare what the finished labels must
satisfy (a *contract*, such as "at most 5% of accepted machine labels are
wrong, with 90% confidence"). The engine asks people for the labels it needs
to test that claim, accepts the machine labels the test supports, and sends
the rest to people. You get the dataset and a certificate that says what was
tested and on how many human labels.

It is available from Potato 2.11. It works with the annotation server, the
`potato label` command line, the REST API, the MCP server and a Python SDK,
all over the same `engine.sqlite` file in the task directory.

## When to use it

- You have more items than people can label, and a model that is right most
  of the time.
- You need to report how good the labels are, not only that a model made
  them: a paper, a dataset release, a training set someone else will use.
- You are evaluating a model or an agent with an LLM judge and need to know
  whether the judge can stand in for people.

If every item will be labeled by people anyway, the engine adds nothing; use
an ordinary assignment strategy.

## From predictions to certified labels

```
items ──► sources (models), in cascade order ──► predictions (append-only)
                                                      │
             people ◄── requests (blind random sample) │
                │                                      ▼
                └──────► human labels ──► contracts ──► accepted / sent to people
                                                      │
                                                      ▼
                                          labels + certificate
```

1. **Sources** are the models. A source can be an LLM, a vision-language
   model, a decision model (Laya, Jev/OpenJev), an object detector, an LLM
   judge, a model trained on this study's labels, a jury of other sources, or
   labels you already have. Each source records a confidence with every
   prediction.
2. The **cascade** orders the sources. An item goes to the first source; if
   the contract will not accept that answer, the next source is tried, and
   after the last one the item goes to a person.
3. **Requests** are what the engine asks people to do. Each one records why
   it was made (calibration, certification, verification, audit, ...), the
   probability that the item was sampled, and whether the person could see a
   machine answer. Calibration requests are drawn at random and are always
   blind.
4. **Contracts** test the machine labels against the human labels on the
   random sample. Half of that sample (the *dev* split) chooses the
   acceptance rule; the other half (the *cert* split) tests it. A contract is
   `met`, `insufficient` (more labels needed, with an estimate of how many),
   `infeasible`, `violated` or `stale`.
5. **Resolution** gives every item its final label: a machine label accepted
   under a met contract, a person's label, or pending.
6. The **certificate** records each contract's result, the cascade with model
   and prompt versions, how many human labels went to each purpose, the model
   spend, and a digest of the call log.

## Guarantees and their limits

The guarantees are statistical statements about the random sample people
labeled. They hold because of how the sample is drawn and used:

- **Blind means blind.** While a person holds a calibration, certification or
  audit request, the server withholds every machine answer for that item:
  pre-annotations, the inline judge, the AI assistant (`403`) and AI help
  buttons. A label given after seeing the machine's answer is not an
  independent check of it.
- **Selection and testing use different labels.** Thresholds are chosen on
  dev labels and tested on cert labels. Each new test on the cert labels is
  run at a stricter level, so re-certifying until a test passes does not
  inflate the confidence.
- **Only people certify.** Machine annotators may take part in final-label
  inference, never in the labels a contract tests against.
- **A change makes the certificate stale.** Changing a source, a prompt, a
  threshold or the scheme marks the contracts on the schemes it affects
  `stale` and moves their accepted labels to `pending_recert` until they are
  tested again. Contracts on other schemes are untouched, and the human labels
  are kept.
- **Machines never take a person's place.** Engine predictions do not count
  against per-item annotator caps.

The engine does not check that the human labels are right. Every
contract measures the machines against the people who labeled the sample. If
those people are unreliable, the contract certifies agreement with
unreliable people. Use [quality control](../workflow/quality_control.md),
overlap (`humans.overlap`) and the `no_worse_than_human` contract to check
the people too.

## A first study

The three examples under `examples/labeling-engine/` cover text, images and
agent traces:

| Example | Sources | Contracts |
|---|---|---|
| `text-certified-sentiment/` | Laya (decision model), an Ollama LLM | selective risk at 10%, PPI prevalence |
| `image-objects-and-people/` | YOLOv8n detector, an Ollama vision model | selective risk on boxes (IoU) and on a has-person label |
| `agent-trace-judge/` | an LLM judge with label-order swap | selective risk, no-worse-than-human, PPI task success |

```bash
# Label every item with the cascade and draw the first blind sample
potato label run examples/labeling-engine/text-certified-sentiment/config.yaml

# Serve the sample to people
python potato/flask_server.py start examples/labeling-engine/text-certified-sentiment/config.yaml -p 8000

# After people have labeled the sample
potato label certify examples/labeling-engine/text-certified-sentiment/config.yaml
potato label certificate examples/labeling-engine/text-certified-sentiment/config.yaml --format md
```

A minimal config:

```yaml
assignment_strategy: engine

labeling_engine:
  enabled: true
  sources:
    - id: gemma
      kind: llm
      endpoint_type: vllm
      model: google/gemma-4-12B-it-qat-w4a16-ct
      base_url: http://localhost:8001/v1
      confidence: {method: logprob}
  contracts:
    - id: accuracy
      kind: selective_risk
      schema: sentiment
      error: 0.1
      confidence: 0.9
  budgets:
    human_labels: 400
```

See [Configuration](configuration.md) for every key and
[Contracts](contracts.md) for what each contract tests.

## The annotation page

With `assignment_strategy: engine`, annotators are served the engine's
requests, highest priority first: adjudication, certification, calibration,
extra raters for distributional contracts, items no machine could label,
verification, audits. Calibration requests are served in a fixed random
order; dev and cert requests are interleaved. A person is given every open request on an item
at once, one per scheme, and never two requests for the same scheme on the
same item. A short note above the item says what kind of request it is; on a
page with several questions it names the question:

- **Blind:** "Label this one yourself. Suggestions are off for this item." An
  item stays blind for that person after they save it, on reload and on
  Back.
- **Verify:** the machine's answer is filled in, and the note says to keep it
  if it is right and change it if it is not. The page records the prefilled
  answer, so you can measure how often people accept it. Nothing is saved
  until the person acts: a page left open does not answer for them. Schemes
  whose answers the page cannot prefill (time segments, 3D objects, agent
  traces) are served blind instead.
- **Resolve:** no machine label could be accepted, so the person's answer is
  the label.

A request someone holds without answering for `runtime.hold_minutes`
(default 60) goes back to the pool and leaves their page. Saving a label for
an item the engine did not serve that person never closes someone else's
request; it is kept as an organic label.

When a new certification accepts machine labels, open verify and resolve
requests on items it now covers are cancelled. Requests a person already
holds stay with them, and their answer replaces the machine label.

The progress counter counts the requests a person can still take, not the
corpus. When there is nothing to do yet, the annotator stays on a short
waiting page and is served new requests when the planner opens them. When
nothing more will come (every item has a label, the human-label budget is
spent, or the person's own cap is reached), their part ends as usual, with
the post-study pages and, on a crowd platform, the completion code. Nobody is
finished before the planner's first pass.

Pocket Mode (where phones land) serves engine requests too, a full batch at
a time, and asks for more before it says "All caught up". It never shows a
machine answer, so a verify request served there is recorded as blind,
unless the desktop page had already shown the answer to that person. On
resolve and adjudicate cards it shows the same note as the desktop page.

## The admin page

The admin dashboard links to **Labeling engine** (`/admin/labeling-engine`)
when the engine is on. Every chart on it also has a table view. It shows:

- each contract's status, coverage, look number and how many more labels it
  needs, with the full statement it makes (an unmet contract states its
  target, not a guarantee);
- the intervals of each `ppi` contract, beside the people-only intervals;
- a warning for a source whose last run failed or whose every answer was an
  error;
- the error-against-coverage curve for the last cascade tier, with the
  guaranteed upper bound and the target;
- a reliability diagram per tier (stated confidence against the share
  correct on human labels), with ECE and Brier score; bins with few labels
  are paler;
- the audits of accepted labels: errors against the target, and whether
  there are too few audits to tell;
- human requests by purpose and status;
- the model-call log, newest first, with tokens, latency and cost;
- buttons to run a planner pass, certify now, and open the certificate.

Opened without an admin session, the page goes to the dashboard's key form;
with the engine off, it says so and names the key that turns it on.

## Related documentation

- [Configuration](configuration.md): every `labeling_engine` key
- [Contracts](contracts.md): the six contract kinds
- [Command line, API and SDK](cli-and-api.md)
- [Migrating from older AI keys](migration.md)
- [Solo Mode](../solo-mode/solo_mode.md): one expert working with an LLM
- [MCP server](../tools/mcp_server.md): the `engine_*` tools

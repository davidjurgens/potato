# Truth Serum: Surprisingly-Popular Scoring

Majority vote fails exactly where annotation is hard: when a confident crowd is wrong
and an informed minority is right. Truth Serum adds one micro-question after each label:

> *You chose **Sarcastic**. What percentage of other annotators will choose the same
> label as you?*

One slider, one click. Those predictions power the **surprisingly popular** principle
(Prelec 2004, *A Bayesian Truth Serum for Subjective Data*; Prelec, Seung & McCoy 2017,
*A solution to the single-question crowd wisdom problem*, Nature): the label whose actual
popularity most exceeds its predicted popularity is the best available estimate of the
truth — **no gold labels required**. The intuition: people who hold a correct minority
view typically *know* they're a minority, so their answer ends up more popular than
anyone predicted.

Potato is, to our knowledge, the first annotation tool to ship peer-prediction scoring.

## What you get

1. **Item verdicts that beat majority vote on hard items.** The dashboard's
   *"Where the crowd is likely wrong"* queue lists every instance whose
   surprisingly-popular label differs from its majority label — review these first,
   or route them to [adjudication](../administration/adjudication.md).
2. **Annotator calibration scores.** How far each annotator's predicted agreement is
   from the agreement they actually got from peers. Overconfident and miscalibrated
   annotators surface without any gold questions.
3. **SP-alignment.** How often each annotator's label matches the surprisingly-popular
   verdict — a proxy for being "informed" rather than merely agreeable.

## Quick start

```bash
python potato/flask_server.py start examples/advanced/truth-serum/config.yaml -p 8000 --debug --debug-phase annotation
```

Pick a label and the prediction card appears bottom-left. The dashboard lives at
`/truth_serum/dashboard` (admin access; debug mode passes automatically).

## Configuration

```yaml
truth_serum:
  enabled: true
  schema: sarcasm            # scheme to collect predictions for (default: first radio)
  min_annotators: 3          # predictions per item before a verdict is computed
  # question: "What percentage of other annotators will choose the same label as you?"
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Master switch. |
| `schema` | first radio scheme | Which scheme's labels get popularity predictions. |
| `question` | see above | Prompt shown above the slider. |
| `min_annotators` | `3` | Minimum predictions per item before a surprisingly-popular verdict is computed (floor: 2). |

## Method notes (read before citing)

- This is the **simplified own-answer-prediction variant**: each annotator predicts the
  popularity of the label they chose, rather than a full distribution over all labels.
  A label's predicted popularity is the mean prediction of its supporters; its surprise
  is `actual % − predicted %`; the SP verdict is the most-surprising voted label.
- Verdicts are only computed with `min_annotators`+ predictions; small-N verdicts are
  noisy, and 3 is a floor, not a recommendation — 5+ is better.
- Calibration error compares each prediction against agreement among the *other*
  annotators on that item (self excluded).
- Annotators can revise: the latest (label, prediction) per instance wins.

## Data and API

Predictions persist to `{output_annotation_dir}/truth_serum/predictions.jsonl`
(append-only; latest record per annotator+instance wins).

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/truth_serum/api/predict` | POST | session | Record label + predicted % |
| `/truth_serum/api/mine` | GET | session | This annotator's prediction (widget restore) |
| `/truth_serum/dashboard` | GET | admin | Verdicts + calibration dashboard |
| `/truth_serum/api/stats` | GET | admin | Dashboard aggregates |
| `/truth_serum/api/export` | GET | admin | Full JSON export (verdicts + raw predictions) |

## Related documentation

- [Quality Control](../workflow/quality_control.md) — attention checks and gold standards
- [MACE](mace.md) — competence estimation; composes with Truth Serum's calibration view
- [Adjudication](../administration/adjudication.md) — route SP-flagged items to experts

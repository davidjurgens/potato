# Sensitive Questions: List Experiments and Randomized Response

Asking people directly whether they have cheated, evaded tax or driven
drunk under-reports how common it is. Two survey designs let a participant
answer without revealing their own answer, and still let the study estimate
the prevalence:

| `annotation_type` | Design |
|---|---|
| `list_experiment` | The item count technique: "How many of these apply to you?", with the sensitive statement in the treatment group's list only |
| `randomized_response` | A private random rule decides whether the participant answers truthfully (`forced_response`), or the participant only says whether two statements agree (`crosswise`) |

Both work on survey pages and on annotation items. The
`survey_experiments` export computes the estimates.

## List experiment

```yaml
conditions:
  factors:
    list_group: [control, treatment]

annotation_schemes:          # or on a survey page
  - annotation_type: list_experiment
    name: lists
    description: How many of these have you done in the last year?
    items:
      - Gone to a live music concert
      - Bought a book in a shop
      - Volunteered for a local group
    sensitive_item: Driven a car after drinking alcohol
    treatment: {factor: list_group, level: treatment}
```

Participants in the `treatment` level of `list_group` see four statements;
everyone else sees three. The sensitive statement is removed from the page
on the server for the control group, so it is not in their HTML. The
participant answers with a number.

The estimate is the treatment group's mean count minus the control group's
(the difference-in-means estimator), with a Welch standard error and a 95%
interval. It assumes the sensitive statement does not change how people
answer the other statements, and that nobody lies about the count.

| Key | Default | Meaning |
|---|---|---|
| `items` | required | The control statements (at least two) |
| `sensitive_item` | required | The statement only the treatment group sees |
| `treatment` | required | `{factor, level}`: who sees it. The factor must be in `conditions.factors` |
| `sensitive_position` | last | Where in the list it goes, from 0 |
| `count_prompt` | "Number of statements:" | The label of the number box |

Choose control statements that few people would answer all yes or all no
to. If the control list's count is at its maximum, a yes to the sensitive
statement becomes visible from the count.

## Randomized response: forced response

```yaml
  - annotation_type: randomized_response
    name: tax
    method: forced_response
    description: This question uses a private random rule.
    question: In the last five years, have you left income off a tax return on purpose?
```

The page tells the participant to think of the month their mother was born
in: January or February, answer Yes; March or April, answer No; any other
month, answer the question truthfully. Birth months are close to uniform,
so the answer is truthful with probability 2/3, forced Yes 1/6 and forced
No 1/6. To use another rule, give `randomizer` (the text the participant
reads) and `p_truth`, `p_yes` and `p_no` (summing to 1).

With λ the share answering Yes, the prevalence is π = (λ − p_yes) / p_truth,
with SE = √(λ(1 − λ)/n) / p_truth.

## Randomized response: crosswise

```yaml
  - annotation_type: randomized_response
    name: cheating
    method: crosswise
    description: Read both statements. Do not say which is true.
    question: I have copied someone else's work and handed it in as my own.
    nonsensitive_statement: My mother was born in January, February or March.
    nonsensitive_prevalence: 0.25
```

The participant answers only "Both statements are true, or neither is" or
"Exactly one statement is true" (Yu, Tian & Tang 2008). With λ the share
giving the first answer and p
the non-sensitive statement's prevalence, π = (λ + p − 1)/(2p − 1), with
SE = √(λ(1 − λ)/n) / |2p − 1|. The design needs p away from 0.5; values
within 0.05 of it are refused.

## Export

```bash
python -m potato.export --config config.yaml --format survey_experiments --output ./export/
```

`survey_experiments.csv`, one row per scheme: the design, the estimate, its
standard error and 95% interval, and the counts it rests on. For a list
experiment, the group sizes and means, and `excluded`: how many answers
were not a whole number from 0 to the number of statements the participant
saw (non-numeric answers count here too). The input on the page allows one
more than a control participant sees, and answers are stored as sent, so
the export does this check. Estimates are not clipped to 0–1: a value outside that
range means the sample is too small or an assumption does not hold.

## Related

- [Experiment flow](../../workflow/experiment_flow.md) (conditions)
- [Survey pages](../../workflow/surveyflow.md)

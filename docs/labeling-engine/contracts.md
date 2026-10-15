# Labeling engine contracts

A contract is a claim about the finished labels that the engine tests against
human labels on a random sample. Each contract names one annotation scheme
(`schema`) and has a `confidence` (default 0.9): the probability that the
claim holds, so `confidence: 0.9` allows a 10% chance that a met contract is
wrong.

| Kind | Claim | For |
|---|---|---|
| `selective_risk` | At most `error` of the accepted machine labels are wrong | Datasets and training sets where each label must be usable |
| `ppi` | An interval for each label's prevalence (or a mean score) that is valid whatever the machine's quality | Reporting rates: "12% of posts are toxic [10.5, 13.6]" |
| `no_worse_than_human` | The machine agrees with people at least as well as a person does | Replacing annotators or an LLM judge |
| `budget_first` | What a human-label budget can buy | Planning before you spend |
| `distributional` | The machine's label distribution is close to how people split | Subjective tasks where disagreement is data |
| `threshold_legacy` | None: accept above a fixed confidence | Translated configs only |

## Status

| Status | Meaning |
|---|---|
| `met` | The test passed on the current cascade. |
| `insufficient` | Not enough human labels yet, with an estimate of how many more are needed. When that estimate is more than the corpus has left to sample, the status says the target is not reachable with this corpus. |
| `infeasible` | Enough labels, but no acceptance rule passes (for example, the machine's confidence does not separate right from wrong answers). |
| `violated` | Audits of accepted labels show the error rate is above target (with `features.drift`, on by default). |
| `stale` | A source, prompt or the scheme changed since the last test. Accepted labels wait in `pending_recert`. |

A machine label is accepted only when every `selective_risk` (and
`threshold_legacy`) contract on its scheme is met and accepts it: the
contracts are what the labels must satisfy, so an unmet one blocks
acceptance rather than being skipped. Until then the status, the admin page
and the certificate say which contract is not met. When no rule can be in
force and nothing more is being sampled (a contract is infeasible, the
calibration sample is finished, or nothing could be projected), the items
still without a label go to people, within `budgets.human_labels`.

## Dev and cert splits

Calibration requests are drawn at random with a recorded inclusion
probability and are always blind. Each one is put at random into one of two
splits:

- **dev** (`humans.dev_fraction`, default half): fits calibrators and chooses
  thresholds.
- **cert**: tests the chosen rule, and nothing else reads it.

### Looks

Every new test of a contract runs at a stricter level: look k gets
`(1 - confidence) * 6 / (pi^2 k^2)` of the error budget, which sums to the
whole budget over every possible look (the first look gets 61% of it).
Testing again as labels arrive therefore does not inflate the confidence.

- Looks are counted per contract across every cascade it has been tested
  under, and a renamed contract keeps the looks of its old id. Trying prompts
  or models until one passes costs a look each time. Going back to an earlier
  cascade is a new look too; its earlier result is not restored.
- Re-testing the same data is not a new look: the same cert labels, the same
  predictions and the same rule chosen on dev give back the stored result. A
  test that could not be run (no cert labels in a class, for example) spends
  nothing.
- `potato label certify` (and the REST, MCP and SDK equivalents) tests new
  cert labels and new predictions at once. When only dev labels changed, it
  returns the stored result with a note that dev now picks another rule;
  `--retest` tests that rule, at the next look.
- The planner certifies on its own as labels arrive. A met `selective_risk`
  contract stays met for its cascade, and audits watch it. A contract that
  is not met is tested again once its labels have grown by a quarter (and by
  at least 10). `ppi`, `distributional` and `no_worse_than_human` results are
  estimates rather than pass/fail tests, so they are re-estimated at the same
  milestones, and once more when the calibration sample is complete.
- An edited cert label (an annotator changing their answer) is new data, but
  it costs no more than new labels do. Edited back to a state already tested,
  that test's result returns. If none of the stored result's tests sees more
  errors after the edit, the result and its look stand. Otherwise the planner waits for the labels
  to grow by a quarter from the first edit, so a burst of corrections becomes
  one test, and accepted labels stay accepted meanwhile, with a note on the
  contract; when no more labels are coming, it tests at once. An explicit
  certify tests it at the next look.

Labels people gave after seeing a machine answer (verify requests) and labels
given outside the engine's requests are never used to certify or estimate.
They can train a distilled model.

## selective_risk

```yaml
- id: accuracy
  kind: selective_risk
  schema: sentiment
  error: 0.05          # required: largest tolerated error among accepted labels
  confidence: 0.9
  per_class: true      # test each predicted class separately
  tolerance: 0.5       # graded families only: loss at or below this counts as correct
```

The rule is a confidence threshold for each cascade tier (and each predicted
class with `per_class`). For every tier but the last, the threshold is chosen
on dev and tested once on cert. The last tier tries thresholds from the dev
choice toward more lenient ones, testing each in turn and stopping at the
first that fails (fixed-sequence Learn-then-Test). Each test is a one-sided
binomial test that the error among accepted labels is above `error`, with the
level split across tiers and classes. A tier that fails accepts nothing, and
its items go to people.

"Correct" depends on the scheme:

| Scheme family | Loss | Default `tolerance` |
|---|---|---|
| One-of-N (`radio`, `select`) | 0 if the same label | 0 |
| Ordinal (`likert`) | distance on the scale / (points - 1) | 0 |
| Continuous (`slider`, `number`) | distance / (max - min) | 0.05 |
| Multi-label (`multiselect`) | 1 - Jaccard overlap | 0 |
| Image regions (`image_annotation`) | 1 - mean IoU over matched shapes | 0.5 |
| Audio/video segments, `temporal_grounding`, `tiered_annotation` | 1 - mean temporal IoU | 0.5 |
| 3D objects (`spatial_annotation`) | 1 - mean 3D IoU | 0.5 |
| Agent traces (`process_reward`, `trajectory_eval`, ...) | share of shared steps labeled differently | 0 |

The losses for regions, segments, 3D objects and traces are the ones the
agreement report (`/admin/iaa`) uses, so a machine is scored against a person
the way two people are scored against each other. Free text and pairwise
schemes have no family yet; the certificate lists them as unsupported.

The test needs each tested group of cert items to be a uniform sample. A
group whose items were sampled with unequal probabilities is not tested, and
the result names it.

On the last tier a threshold is chosen on dev only where dev's error is at
most half the target and enough cert labels are expected to pass a first
test. The projection of how many more labels are needed counts only
thresholds that could be chosen that way. When cert already has the labels
the projection asked for and the test still fails, the next projection uses
the error rate dev and cert show together, not dev's alone. When the lowest
dev error is under the target but above half of it, nothing is tested and
nothing is projected; the result says so and names the error, since more
labels only help if the error turns out lower.

`metrics.accepted_by_tier` is the rule's coverage of the whole population,
calibration items included, not a count of delivered machine labels; the
certificate's "Machine labels accepted, by source" line counts those.

The trace loss compares the steps both sides labeled, so a person who marked
only some steps is compared on those. Steps nobody labeled are not checked:
a person who labels step 0 alone and agrees with the judge there counts as
agreeing with the whole trace label. Where every step must be checked, ask
people to label every step.

## ppi

```yaml
- id: prevalence
  kind: ppi
  schema: sentiment
  estimand: prevalence   # or mean, for numeric scores
  by: language           # optional: an interval per value of this item field (copied from the items when they are registered)
  confidence: 0.95
  max_width: 0.05        # optional: met once every interval is at most this wide
```

Prediction-powered inference (Angelopoulos et al., 2023) corrects the
machine's estimate with its error on the human-labeled sample. The interval
is valid whatever the machine's quality: a good machine makes it narrower
than people alone could, and a bad one makes it no wider. With equal
inclusion probabilities the engine uses PPI++ with a tuned weight. With
unequal ones (stratified or uncertainty-driven sampling) it uses the
Horvitz-Thompson difference estimator. The machine label used is the one the
cascade would deliver.

Without `max_width` the contract is met as soon as it has enough labels to
report.

## no_worse_than_human

```yaml
- id: replaces-a-person
  kind: no_worse_than_human
  schema: verdict
  epsilon: 0.1
```

The alternative annotator test (Calderon, Reichart and Dror, 2025): leaving
each person out in turn, does the machine agree with the remaining people at
least as often as the left-out person does, up to `epsilon`? The machine
passes when it wins against at least half of the people, with the false
discovery rate across people controlled. It needs items labeled by several
people: set `humans.overlap` (share of the sample) and `humans.overlap_k`
(people per item, at least 3). The test asks for 3 or more annotators with 30
or more items each.

Use it when a fixed accuracy target would mostly measure annotator noise: if
two careful people agree 85% of the time, no labeler can be shown to be 95%
"right".

## budget_first

```yaml
- id: plan
  kind: budget_first
  schema: sentiment
  human_labels: 500      # or human_usd, priced at the crowd reward
```

A projection from the dev labels collected so far: for each error target on a
grid, the share of the corpus the machines could be certified to label with
this budget, and how wide each prevalence interval would be. It is `met` once
there are enough dev labels to project from. It promises nothing about the
labels; `selective_risk` and `ppi` do that once the labels are in.

## distributional

```yaml
- id: disagreement
  kind: distributional
  schema: offensiveness
  max_distance: 0.15     # optional
  groups_by: age_band    # optional: a prestudy question whose answer groups the annotators
```

For subjective tasks, where people disagree for reasons that belong in the
data. Each item labeled by several people (`humans.distribution_k`, default
5) has a human label distribution. The contract reports the mean
Jensen-Shannon distance between the machine's distribution and the people's,
with a bootstrap interval, and a noise ceiling: the same distance between two
random halves of the people on each item. A machine closer to the people than
they are to each other is as close as the data allows. With `groups_by`, the
same numbers are reported per annotator group.

The machine's distribution is its probabilities where the source gives them
(decision models, `k_sample`, `logprob`), or its label as a one-hot vector.
It is met when the interval's upper end is at most `max_distance`, or, with no
`max_distance`, once there are 20 items labeled by 3 or more people. When the
interval's lower end is above `max_distance`, it is `infeasible`: more items
narrow the interval around a distance that is too large. With `groups_by`,
each group's distribution on an item is built from that group's people
only, read from their answers to the named prestudy question; if nobody
answered it, the contract says so.

## threshold_legacy

```yaml
- id: old-rule
  kind: threshold_legacy
  schema: sentiment
  threshold: 0.8
```

Accepts machine labels above a fixed confidence with no statistical test.
`potato label migrate-config` writes it for `icl_labeling`, at the old
`confidence_threshold`, so a translated config behaves as before; it can also
be written by hand.
The certificate marks these labels uncertified and reports their measured
error on the calibration labels, and the export gives them the status
`accepted_uncertified`.

## Results from the example studies

From the three examples under `examples/labeling-engine/`, with the LLM,
judge and vision sources pointed at Gemma 12B on a vLLM server instead of
the Ollama models the committed configs use. Each example's README shows the
source block that was changed; with the Ollama defaults the numbers will
differ.

- **Text sentiment** (481 reviews; Gemma 12B with logprob confidence as the
  last tier): `selective_risk` at 10% / 0.9 was met on 165 human labels, and
  316 machine labels were accepted. Their measured error against the true
  labels was 7.6%. The PPI intervals covered the true prevalence of all three
  labels.
- **Images** (128 COCO images; YOLOv8n and Gemma 12B as the vision model): a has-person label was certified at 10%. The
  box contract was insufficient: YOLOv8n's boxes were wrong on 32% of the dev
  images at IoU 0.5.
- **Agent traces** (288 traces, Gemma 12B as the judge): the judge was right on 80%, but
  its confidence was 1.0 throughout, so `selective_risk` was infeasible. The
  alt-test was insufficient (machine 0.82 against the people's 0.93). PPI
  estimated task success at 0.66 [0.57, 0.76]; the true value was 0.60, and
  the judge alone said 0.76.

## Related documentation

- [Overview](overview.md)
- [Configuration](configuration.md)
- [Machine annotators](../advanced/machine_annotators.md): machine raters in the agreement report

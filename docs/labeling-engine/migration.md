# Migrating to the labeling engine

Potato's older machine-labeling features keep working in 2.11. Nothing in an
existing config stops working, and nothing changes behaviour until you add a
`labeling_engine` block. Two keys now print an informational message at
boot pointing to the engine; they are planned for removal in 3.0:

| Older key | Engine equivalent |
|---|---|
| `icl_labeling` | an `llm` source, with a `threshold_legacy` contract for the old rule and a `selective_risk` contract beside it |
| `judge_calibration` | `judge` sources with `k_sample` confidence; its blind sample becomes calibration requests |

`pre_annotation` is not deprecated. It shows a model's or an import's answers
as an editable starting point, and the importers write it for that. The
engine's `static` source is different: its labels are accepted only where a
contract certifies them. `migrate-config` still translates `pre_annotation` to
a `static` source if that is what you want.

[Solo Mode](../solo-mode/solo_mode.md), judge alignment and the interactive
AI assistant (`ai_support`) are not deprecated. Solo Mode is one expert
working with an LLM through its own interface; judge alignment is a report.
Both now also write their model predictions into the engine's store when the
engine is on, so the engine can calibrate and certify them.

## `potato label migrate-config`

```bash
potato label migrate-config config.yaml --out config-engine.yaml
```

The command reads the YAML (no data is loaded), adds an equivalent
`labeling_engine` block, and writes the result with a header of notes that
explain each translation. The block is written with `enabled: false`: read
the notes, check the sources and contracts, then set `enabled: true` and
`assignment_strategy: engine`.

It exits with an error when the config already has a `labeling_engine`
block, or when there is nothing to translate.

## Translation table

| Older block | Sources | Contracts | Humans |
|---|---|---|---|
| `solo_mode` with `confidence_routing.tiers` | one source per tier, in tier order | `selective_risk` per one-of-N scheme, `error: 1 - end_human_annotation_agreement` | `pools: [solo]` |
| `solo_mode` with `labeling_models` | one source per model; the first is the cascade | as above | `pools: [solo]` |
| `solo_mode.jury` | one source per juror, plus a `jury` source as the cascade | as above | |
| `icl_labeling` | the `ai_support` endpoint as an `llm` source | `threshold_legacy` at the old `confidence_threshold`, and `selective_risk` at 10% | `calibration_rate` = the old verification `sample_rate` |
| `judge_alignment` | the judge endpoint as a `judge` source (with the rubric when there is one scheme) | `no_worse_than_human`, `epsilon: 0.15`, per judged scheme | `overlap: 0.3` |
| `judge_calibration` | each model as a `judge` source with `k_sample` confidence | | `sampling.sample_size` → `budgets.human_labels` |
| `pre_annotation` with `field` or `predictions_file` | a `static` source, first in the cascade | | |
| `active_learning.llm` | an `llm` source | | |
| `ai_budget.cap_usd` | | | `budgets.model_usd` |

## Behaviour changes after migration

The engine treats the human labels differently from the older features, and
the notes in the translated config say where:

- **Fixed thresholds become tested ones.** Solo Mode's routing thresholds and
  `icl_labeling`'s confidence threshold accepted machine labels above a fixed
  number. `selective_risk` chooses the threshold on dev labels and accepts
  only what passes a test on held-out labels. Expect fewer labels accepted at
  first, and a stated error bound on the ones that are.
- **Verification samples become uniform.** `icl_labeling` verified the
  least-confident predictions first. That finds errors quickly but gives a
  biased accuracy estimate. Engine calibration requests are a random sample
  with recorded inclusion probabilities.
- **Inline judging becomes blind.** `judge_alignment.inline` showed the
  judge's verdict while people labeled, so agreement was measured on anchored
  labels. Engine calibration requests never show a machine answer.
- **Pre-annotations are tested before they are trusted.** A `static` source's
  labels are accepted only where a contract certifies them; elsewhere people
  see them on verify requests.

## Related documentation

- [Overview](overview.md)
- [Configuration](configuration.md)
- [Contracts](contracts.md)

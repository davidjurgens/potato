# Belief elicitation (`belief_elicitation`)

Asks for a belief about an uncertain event: the probability that it happens
(`mode: point`), or a distribution of 100 points over a set of bins
(`mode: bins`). Reports are paid by the binarized scoring rule once the true
outcome is known. See the
[`bsr` incentive rule](../../advanced/incentives.md#bsr).

## Configuration

A probability:

```yaml
annotation_schemes:
  - annotation_type: belief_elicitation
    name: forecast
    description: How likely is it that this happens?
    mode: point
    left_label: Certainly not
    right_label: Certainly
    label_requirement: {required: true}
```

A distribution:

```yaml
  - annotation_type: belief_elicitation
    name: rainfall
    description: How much rain will fall next week?
    mode: bins
    bins: ["0-9 mm", "10-19 mm", "20-29 mm", "30 mm or more"]
    label_requirement: {required: true}
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `mode` | `point` | `point` (a probability) or `bins` (a distribution). |
| `bins` | none | `bins` mode: the bin labels, at least two, all different. |
| `step` | `1` | `point` mode: slider step in percentage points. |
| `left_label`, `right_label` | `Certainly not`, `Certainly` | `point` mode: words under the two ends of the slider. |
| `instructions` | none | Text shown under the question. |
| `label_requirement` | none | `{required: true}` refuses Next until the report is complete. |

## Using it

**Point.** Move the slider to a probability from 0 to 100%. The thumb starts
hollow at 50% and fills once moved or clicked, so an untouched slider is not
read as a report of 50%.

**Bins.** Type a whole number of points for each bin. The bar next to each
bin shows its share, and the total under the bins reads, for example,
"Total: 80 of 100 — 20 left to place" (amber), "120 of 100 — 20 too many"
(red), or "100 of 100 — complete" (green). Until the total is exactly 100 the
question reports itself incomplete, and with `required: true` the Next button
refuses with "allocate exactly 100 points (now 80)".

## Data format

```json
{"report": 70}
```

```json
{"bins": [10, 40, 35, 15]}
```

Empty bins are stored as 0.

## The outcome

Payment needs the event's outcome, which the incentive rule reads from an item
field (`outcome_field`) or from the rule itself (`outcome`). For a point
report it is 1 or 0 (true/false, yes/no); for bins it is the label of the bin
that happened, or its 0-based index. Potato never sends the `outcome_field`
to the page. Leave it empty in the data file while the study runs, and fill it
in once the events have happened, before you compute payments.

## Troubleshooting

- **`mode: bins needs bins`**: list the bin labels.
- **A distribution is not paid**: its points do not sum to 100. The `note`
  column of `bonuses.csv` gives the sum.

## Related

- [Incentive payments](../../advanced/incentives.md)
- [Price list](price_list.md), [BDM bid](bdm.md)
- [Constant sum](constant_sum.md), for allocations that are not paid
- Example: `examples/advanced/incentivized-elicitation/`

# BDM bid (`bdm`)

Asks for the most a participant would pay for something: "What is the most
you would pay for X?" The bid is paid by the Becker-DeGroot-Marschak
procedure: a price is drawn after the study, and a bid at or above the price
buys at the price. See the
[`bdm` incentive rule](../../advanced/incentives.md#bdm).

## Configuration

```yaml
annotation_schemes:
  - annotation_type: bdm
    name: voucher
    description: What is the most you would pay for a voucher worth $3.00?
    min: 0
    max: 5
    step: 0.05
    input: number
    instructions: >-
      You have $5.00 to spend. A price between $0.00 and $5.00 is drawn after
      the study. If your bid is at least the price, you buy the voucher and pay
      the price, not your bid; otherwise you keep the $5.00.
    label_requirement: {required: true}
```

The draw range and the endowment live in the incentive rule, not in the
scheme. Write the same numbers into `instructions` so the participant knows
the rule they are bidding under.

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `max` | required | The largest bid allowed. |
| `min` | `0` | The smallest bid allowed. |
| `step` | `0.01` | Increment of the slider, and the precision a typed bid is rounded to (at least cents). |
| `input` | `number` | `number` for a typed amount, `slider` for a slider between `min` and `max`. |
| `currency` | `$` | Symbol printed before amounts. |
| `bid_label` | `Your bid` | Label of the input. |
| `instructions` | none | Text shown under the question. |
| `label_requirement` | none | `{required: true}` refuses Next until a valid bid is entered. |

## Using it

With `input: number`, type the amount. An amount outside the range is not
saved; the message under the field gives the allowed range. With
`input: slider`, the thumb starts hollow at the midpoint and fills once the
participant moves it or clicks it, so an untouched slider is not read as a
bid.

## Data format

```json
{"bid": 2.75}
```

## Troubleshooting

- **`min and max must be numbers with 0 <= min < max`**: check the range.
- **A bid shows in the field but the question still reads as unanswered**:
  the amount is outside `min`..`max`.

## Related

- [Incentive payments](../../advanced/incentives.md)
- [Price list](price_list.md), [Belief elicitation](belief_elicitation.md)
- Example: `examples/advanced/incentivized-elicitation/`

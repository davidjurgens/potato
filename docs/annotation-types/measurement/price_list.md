# Price list (`price_list`)

A multiple price list: a column of rows, each with two options, A and B. The
participant picks one option in every row. Price lists measure risk attitudes
(choices between lotteries) and time preferences (an amount now against a
larger amount later). Payment is handled by the
[`mpl_random_row` incentive rule](../../advanced/incentives.md#mpl_random_row).

## Configuration

The Holt & Laury (2002) list, with at most one switch point:

```yaml
annotation_schemes:
  - annotation_type: price_list
    name: risk
    description: For each decision, choose the option you prefer.
    preset: holt_laury
    single_switch: true
    label_requirement: {required: true}
```

The preset has ten rows. Option A pays $2.00 with probability p and $1.60
otherwise; option B pays $3.85 with probability p and $0.10 otherwise;
p = 0.1, 0.2, ..., 1.0. `scale: 10` pays ten times those amounts.

A time-preference list:

```yaml
  - annotation_type: price_list
    name: patience
    description: Which would you rather receive?
    preset: time_preference
    amount_now: 10
    amounts_later: [10, 10.5, 11, 12, 13, 15]
    delay_label: in 4 weeks
```

Rows written by hand. `a_pays` and `b_pays` are what the incentive rule pays:
a number for a sure amount, or `[[probability, amount], ...]` for a lottery.
Without them the list can be shown but not paid.

```yaml
  - annotation_type: price_list
    name: insurance
    description: Choose one option in each row.
    rows:
      - {a: "$5 for sure", b: "50% chance of $12, otherwise $0",
         a_pays: 5, b_pays: [[0.5, 12], [0.5, 0]]}
      - {a: "$6 for sure", b: "50% chance of $12, otherwise $0",
         a_pays: 6, b_pays: [[0.5, 12], [0.5, 0]]}
```

Leave out `a` or `b` and the text is written from the payoffs
("50% chance of $12.00, 50% chance of $0.00").

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `preset` | none | `holt_laury` or `time_preference`. Give either `preset` or `rows`. |
| `rows` | none | List of `{a, b, a_pays, b_pays, a_after, b_after}`, at least two. `a_after` / `b_after` name a payment delay, such as `in 4 weeks`. |
| `scale` | `1` | Multiplies every amount of a preset. Not allowed with `rows`; write the amounts into the rows instead. |
| `currency` | `$` | Symbol printed before amounts. |
| `single_switch` | `false` | Keep at most one switch from A to B (see below). |
| `option_labels` | `[Option A, Option B]` | Column headings. |
| `amount_now`, `amounts_later` | none | `time_preference` only: the sure amount now, and one later amount per row. |
| `delay_label`, `now_label` | `in 4 weeks`, `today` | `time_preference` only: wording for when each option pays. |
| `instructions` | none | Text shown under the question. |
| `label_requirement` | none | `{required: true}` refuses Next until every row is answered. |

## Using it

Click (or tap) an option to choose it. Each row is one radio group: Tab moves
between rows, the left and right arrow keys choose A or B, and the up and down
arrow keys move to the same option in the row above or below. The line under
the list counts the decisions made and, once every row is answered, says
where the participant switches to B.

With `single_switch: true`, choosing B in a row also chooses B in every later
row, and choosing A also chooses A in every earlier row. The rows filled in
this way flash briefly, so the participant sees what changed. The list can
then hold at most one switch, from A to B.

Without it, every row is independent and a participant can switch several
times. The answer records how many times.

## Data format

One hidden input holding JSON:

```json
{"choices": ["A", "A", "A", "A", "B", "B", "B", "B", "B", "B"], "switches": 1, "multiple_switching": false}
```

Unanswered rows are `null`. In a Holt & Laury list the number of A choices is
the usual summary of risk attitude; a risk-neutral participant chooses A in
the first four rows. The `incentives` export recounts the switches from the
stored choices and marks a list with more than one switch.

## Troubleshooting

- **`needs exactly one of preset ... or rows`**: give one, not both.
- **`rows ... have no payoffs`** from `potato validate`: an incentive rule
  pays this list, so every row needs `a_pays` and `b_pays`.
- **The list is long on a phone**: the Holt & Laury rows wrap to three or four
  lines at phone width. Every row stays usable, but a shorter list (fewer
  rows) reads better on a small screen.

## Related

- [Incentive payments](../../advanced/incentives.md)
- [BDM bid](bdm.md), [Belief elicitation](belief_elicitation.md)
- Example: `examples/advanced/incentivized-elicitation/`

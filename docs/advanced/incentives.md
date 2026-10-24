# Incentive payments

Potato can pay participants according to their answers, the way experimental
economics studies do. Three schemes collect the answers:

- [`price_list`](../annotation-types/measurement/price_list.md): a multiple price list (option A or B in each row)
- [`bdm`](../annotation-types/measurement/bdm.md): the most a participant would pay for something
- [`belief_elicitation`](../annotation-types/measurement/belief_elicitation.md): a probability, or a distribution over bins

The `incentives:` block says how each scheme is paid. After a participant
finishes, Potato draws the random numbers, works out the payoff, and writes a
bonus file in Prolific's bulk format. It never pays anyone by itself.

## When the draws happen

Nothing is drawn while the participant answers. The page never sees a price,
a drawn row or a threshold, so none of them can influence an answer. The draws
happen when you run the `incentives` export or open the admin route, and only
for participants who have finished the study (see `only_finished`).

Each draw uses a seed built from the user id, the word `incentives` and the
rule name (`order_seed(user, "incentives", rule)`), combined with the item or
page the answer belongs to and the private `incentives.seed`. Running the
computation again on the same answers gives the same draws. Adding an item
leaves the draws for the other items unchanged. Every draw is written to
`bonuses.csv`.

## Configuration

```yaml
incentives:
  enabled: true
  currency: USD
  seed: "a private string, kept out of the repository"
  pay: one_random_item            # one_random_item | all | sum
  max_bonus: 6.00
  only_finished: true
  rules:
    - scheme: risk                # a price_list scheme
      method: mpl_random_row
    - scheme: voucher             # a bdm scheme
      method: bdm
      endowment: 5.00
      item_value: 3.00
      draw: {min: 0, max: 5, step: 0.25}
    - scheme: forecast            # a belief_elicitation scheme
      method: bsr
      prize: 2.00
      outcome_field: outcome
```

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Turns on the `incentives` export and the admin route. |
| `currency` | `USD` | Label written to `bonuses.csv`. Prolific pays in the study's own currency, so set this to match it. |
| `seed` | none | Private text mixed into every draw. Without it the draws depend only on the user id and the rule name, and anyone with the code could compute them before answering. The export warns when it is missing. The export and `potato validate` also warn while it is still the example's `CHANGE-ME-this-example-seed-is-public`. |
| `pay` | `one_random_item` | `one_random_item` pays one decision drawn at random from all of a participant's answered decisions, including any whose outcome is not filled in yet, so filling one in later does not change which decision is paid. `all` pays the sum of every decision; `sum` is another name for `all`. |
| `max_bonus` | none | Upper limit on one participant's bonus. A capped total is marked `capped` in `bonuses.csv`. |
| `only_finished` | `true` | Draw and pay only for participants who reached the end of the study. Rows for the others say `not finished; nothing drawn`. |
| `rules` | required | One entry per paid scheme. Each needs `scheme` (the scheme's `name`) and `method`. `name` is optional and defaults to the scheme name; give it when two rules pay the same scheme. |

A rule can name a scheme in `annotation_schemes` (answered once per item) or
one on a phase page such as `poststudy` (answered once). `potato validate`
checks that the scheme exists and has the right type for the method.

### `mpl_random_row`

Pays a `price_list` scheme and takes no extra keys. One row of the participant's price list is drawn at random,
each row equally likely. The option they chose in that row is then played: a
second draw `u` in [0, 1) picks the outcome of the lottery, with outcomes laid
end to end in the order listed (for Holt & Laury row 3, option B pays $3.85
when `u < 0.3` and $0.10 otherwise). A list with an unanswered row is not
paid. A list with more than one switch is paid and marked
`multiple switching` in the `note` column.

Every row of a paid price list needs payoffs. The presets have them; hand-written
`rows` need `a_pays` and `b_pays` (see [price_list](../annotation-types/measurement/price_list.md)).

### `bdm`

Pays a `bdm` scheme by the Becker, DeGroot & Marschak (1964) procedure.

| Key | Description |
|-----|-------------|
| `endowment` | Money the participant holds for this decision. Default 0. With `draw` it must be at least `draw.max`, so a purchase never costs more than the participant was given. |
| `draw` | `{min, max}` for a price drawn uniformly, rounded to cents; add `step` to draw one of `min, min + step, ..., max`, each equally likely. |
| `price_field` | Instead of `draw`: an item field holding a price fixed in advance. |
| `item_value` / `value_field` | What the object is worth in money to the participant who buys it, as a number or as an item field. Default 0 (for a physical object handed over separately). |

A bid at or above the price buys at the price, not at the bid:
payoff = endowment − price + item value. A lower bid does not buy:
payoff = endowment. Because the price does not depend on the bid, bidding
anything other than the object's value to you never helps and sometimes
costs: a lower bid can miss a price you would have paid, and a higher bid can
buy at a price above what the object is worth to you. The participant needs to understand this
rule before bidding; say it in the scheme's `instructions`.

### `bsr`

Pays a `belief_elicitation` scheme by the binarized scoring rule of Hossain & Okui (2013).

| Key | Description |
|-----|-------------|
| `prize` | The amount paid on a win. |
| `outcome_field` | The item field that holds what happened: 1/0 (or true/false, yes/no) for a point report; a bin label, or a 0-based bin index, for a bins report. |
| `outcome` | Instead of `outcome_field`: one value for a question answered once, such as one on a phase page. |

The prize is paid when the quadratic loss of the report is below a threshold
`U` drawn uniformly from [0, K]:

- point report `p` (the slider value divided by 100) on a binary event:
  loss = (1{event} − p)², K = 1
- bins report `p_1 ... p_n` (points divided by 100): loss = Σ_b (1{bin b happened} − p_b)², K = 2

The chance of winning is 1 − loss / K. A participant who wants to maximise
their chance of winning the prize does best by reporting what they believe,
whatever their attitude to risk, because the only payoffs are the prize and
nothing.

The true outcome must be supplied before you compute payments. Put it in the
data file under `outcome_field`, or fill it in once the events have happened
and the study has closed. Potato strips the `outcome_field` and `price_field`
fields from the item data sent to the page. Do not also show them in the item
text. A report whose outcome is missing is not paid and is marked
`no outcome for <item>`. If the decision drawn for payment is one of these,
the participant is listed as pending (`pending` in the dry run, with the
reason `pending: <item> has no outcome yet`) and left out of the Prolific
rows until the outcome is filled in.

## Auditing

`bonuses.csv` has one row per paid-for decision:

| Column | Contents |
|--------|----------|
| `user_id`, `prolific_id`, `finished` | Who, their Prolific id if one was recorded at login, and whether they finished. |
| `rule`, `method`, `scheme`, `decision` | Which rule paid which answer. `decision` is the item id, or `<phase>/<page>` for a phase page. |
| `seed` | The rule's `order_seed(user, "incentives", rule)`. |
| `draws` | Every random number used, as JSON: `row`, `choice` and `u` for a price list; `u`, `price` and `bought` for a bid; `loss`, `U`, `K`, `outcome` and `won` for a belief report. The paid decision also carries `paid_decision` and `of` under `one_random_item`. |
| `payoff`, `paid` | This decision's payoff, and whether it counts towards the bonus. |
| `pay_after` | The delay label when the chosen option pays later (a time-preference list). |
| `note` | Why a decision was not paid, or a flag such as multiple switching. |
| `total`, `capped`, `currency` | The participant's bonus after `max_bonus`, and whether the cap applied. |

To check a payment by hand, read the draws and recompute the payoff from the
rules above. To reproduce the draws themselves you need the same answers, the
same rule names and the same `incentives.seed`.

## Paying via Prolific

Participants need a Prolific id. Log them in from the study URL, with
either `login: {type: url_direct, url_argument: PROLIFIC_PID}` or
`crowdsourcing: {provider: prolific}`. A `url_direct` login with any other
`url_argument` records no Prolific id. See
[Prolific integration](../deployment/prolific_integration.md).

**From the export.** Run

```bash
python -m potato.export --config config.yaml --format incentives --output ./bonuses/
```

and upload `bonuses_prolific.csv` in Prolific's bulk bonus dialog. Each line is
`<participant_id>,<amount>` with two decimals and no header. Left out of the
file, each with a warning: participants owed nothing, participants without a
Prolific id, participants who have not finished (with `only_finished`), and
participants whose paid choice pays later.

**From the admin API.** With a Prolific token configured (`prolific.token` or
`crowdsourcing.prolific.token`):

```bash
# Dry run: nothing is sent to Prolific
curl -H "X-API-Key: $KEY" http://localhost:8000/admin/api/crowd/incentive_bonuses

# Pay: echo the dry run's prolific_total
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"pay": true, "expected_total": "12.40", "study_id": "<study id>"}' \
     http://localhost:8000/admin/api/crowd/incentive_bonuses
```

The dry run lists each participant's bonus, the rows that would be paid, and
`prolific_total`. Paying needs `"pay": true` and an `expected_total` equal to
that `prolific_total`. If an answer changed since the dry run, the totals
differ and the request is refused with status 409. The payment goes through
the same code as `POST /admin/api/crowd/study/<id>/bonus`: the rows are
checked with Prolific's bonus validation, a bulk bonus is set up, then paid.

Each paid batch is recorded in `<task_dir>/incentive_payments.json`, with
the Prolific bulk bonus id, the rows and the time. Sending the same rows
again, or rows that include a participant an earlier batch paid, is refused
with status 409, and the error names the earlier batch. A double click
sends the same rows twice. A second payment run after more participants
finish includes the first group again, and without the check it would pay
them twice. To pay only the participants no
recorded batch has paid, add `"skip_paid": true` and set `expected_total` to
the dry run's `unpaid_total`; the dry run also lists `already_paid`. To pay
a recorded batch a second time on purpose, add `"repeat": true` instead.

## Example

```bash
python potato/flask_server.py start examples/advanced/incentivized-elicitation/config.yaml -p 8000
```

Four belief questions (one per item, paid by `bsr` from each item's
`outcome`), then a post-study page with a Holt & Laury price list and a BDM
bid for a voucher worth $3.00.

## Troubleshooting

- **`incentives.rules[0]: scheme 'x' is not defined`**: the rule's `scheme`
  must match a scheme `name` in `annotation_schemes` or on a phase page.
- **`endowment (4) is below draw.max (5)`**: raise `endowment` or lower
  `draw.max`. Otherwise a participant who buys at a high price ends up with
  less than nothing.
- **A participant is missing from `bonuses_prolific.csv`**: check the
  warnings printed by the export and the `note` column of `bonuses.csv`.
- **`incentives.seed is not set`**: add a private `seed` before paying anyone.
- **`These participants were already paid`** (status 409): see
  `incentive_payments.json` in the task directory. Delete the file only if
  none of the batches it lists was paid.

## References

- Becker, G. M., DeGroot, M. H., & Marschak, J. (1964). Measuring utility by a single-response sequential method. *Behavioral Science*, 9(3), 226–232.
- Holt, C. A., & Laury, S. K. (2002). Risk aversion and incentive effects. *American Economic Review*, 92(5), 1644–1655.
- Hossain, T., & Okui, R. (2013). The binarized scoring rule. *Review of Economic Studies*, 80(3), 984–1001.

## Related

- [Price list](../annotation-types/measurement/price_list.md), [BDM bid](../annotation-types/measurement/bdm.md), [Belief elicitation](../annotation-types/measurement/belief_elicitation.md)
- [Prolific integration](../deployment/prolific_integration.md)
- [Export formats](../data-export/export_formats.md)

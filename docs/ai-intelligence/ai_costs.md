# AI Cost Estimates and Spend Caps

Users of the commercial annotation platforms complain less about the price than
about finding out too late: credits consumed by auto-labelling and discovered
at export time, when the work is done and the bill is already owed.

Potato's bring-your-own-key model avoids the lock-in and used to reproduce that
exactly. The bill was unbounded and invisible until the provider sent it.

---

## Quick start

Ask what the next judge run would cost, before running it:

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/admin/api/ai-cost
```

```json
{
  "next_judge_run": {
    "n_items": 400,
    "total_tokens": 486400,
    "model": "gpt-4o",
    "cost_usd": 3.1,
    "priced": true,
    "as_of": "2026-08",
    "summary": "400 item(s), about 486,400 tokens, roughly $3.10 at 2026-08
                prices. An estimate, not a quote."
  },
  "spent": { "cost_usd": 0.42, "n_runs": 3, "cap_usd": 25.0 }
}
```

Set a ceiling:

```yaml
ai_budget:
  cap_usd: 25.0
```

---

## The cap refuses before it starts

A run projected to cross the cap is refused before the first model call, and
the endpoint returns `402` with `"ran": false`:

```json
{
  "ran": false,
  "cap_usd": 25.0,
  "spent_usd": 24.80,
  "error": "This run is projected to cost $3.10, which would take the project
            to $27.90 against a cap of $25.00 ($24.80 already spent). Nothing
            has been run. Raise ai_budget.cap_usd, or run fewer items."
}
```

Halting halfway leaves a part-labelled dataset and a bill for it, so refusing
up front is the refusal that saves money.

Money already spent counts toward the cap. Otherwise the cap applies per run,
which caps nothing.

Currently enforced on:

- the judge batch (`/admin/api/judge-alignment/run`)
- the [position-bias probe](../advanced/presentation_order.md)
  (`/admin/api/judge-position-bias`)

---

## Token and price assumptions

Two choices make it lean pessimistic rather than flattering.

**Output is counted at the configured maximum**, not an average. Estimates that
assume short answers are the ones that surprise you.

**Prompt overhead is charged per item.** The rubric, the label list and the
JSON instruction ride along with every single item, and leaving them out
understates a short-text project by more than the items themselves.

Token counts come from a characters-per-token rule of thumb. Real tokenizers
vary by 20–30% and by language, so this is for deciding whether a run is
affordable, never for reconciling an invoice.

### Actions that call more than once

The position-bias probe judges every item twice. Its estimate says so:

```json
"notes": ["This action queries the model 2 times per item."]
```

### An unknown price reports as unknown

A model absent from the price table reports its token count and
`cost_usd: null`.

"Free" and "unknown" are different, and only one is safe to budget against. A
guessed price would be believed.

An unpriced model does not block a capped run either. The cap is a dollar
ceiling with no dollar figure to compare against, so Potato logs a warning
saying so and lets the run proceed.

### Self-hosted models

vLLM, Ollama and the local vision models report `cost_usd: 0` and
`local: true`. The marginal cost of a local call is electricity.

The token count is still reported, since it predicts how long the run takes.

### The price table goes stale

Every estimate carries `as_of`. A stale price still gives you the order of
magnitude; presented as a quote it would not. The table lives in
`potato/ai/cost.py`.

---

## The running total

```json
"spent": {
  "cost_usd": 0.42,
  "total_tokens": 138400,
  "n_runs": 3,
  "n_unpriced_runs": 1,
  "cap_usd": 25.0,
  "note": "1 run(s) used a model with no price on record and are not in the
           dollar total."
}
```

Unpriced runs are counted apart from the dollar total. Folding them in as zero
would report a project using an unpriced model as having spent nothing.

Each run records whether its figure was estimated or measured, so the total can
be checked against an invoice — which is how anyone finds out an estimate was
wrong.

---

## Configuration

| Key | Type | Default | What it does |
|---|---|---|---|
| `ai_budget.cap_usd` | number | none | Dollar ceiling. A run projected to cross it is refused before it starts |

---

## Related

- [AI Support](ai_support.md) — configuring an endpoint
- [Presentation Order](../advanced/presentation_order.md) — the most expensive
  action in Potato
- [Judge Calibration](judge_calibration.md)

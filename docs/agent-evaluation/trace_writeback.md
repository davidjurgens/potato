# Trace Score Write-Back

Langfuse and LangSmith have annotation queues of their own, with one reviewer
per trace. Potato can take the same traces in (the trace webhook, or the
Langfuse poller), have several people judge each one blind, and then send the
result back to the trace: a Langfuse score or a LangSmith feedback holding the
merged answer, the number of annotators, and how far they agreed. The team
sees it next to the trace, in the tool it already uses.

## Configuration

```yaml
trace_ingestion:
  enabled: true
  api_key: ingest-secret
  sources:
    - type: langfuse
      api_url: https://cloud.langfuse.com
      public_key: pk-lf-...
      secret_key: sk-lf-...
  writeback:
    trigger: fully_annotated   # or: adjudicated
    min_annotators: 2
    score_prefix: potato
```

| Key | Default | Meaning |
|---|---|---|
| `trigger` | `fully_annotated` | `fully_annotated` sends once `min_annotators` people have answered. `adjudicated` waits for an adjudication decision. An adjudication is sent in either mode |
| `min_annotators` | the study's per-item cap, or 2 | How many people must answer before a trace is sent |
| `score_prefix` | `potato` | Scores are named `<score_prefix>.<scheme name>`, for example `potato.outcome` |
| `langfuse.host` | the langfuse source's `api_url`, else `https://cloud.langfuse.com` | Langfuse base URL |
| `langfuse.public_key_env`, `langfuse.secret_key_env` | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | Environment variables holding the keys. Without them, the langfuse source's keys are used |
| `langsmith.api_url` | `https://api.smith.langchain.com` | LangSmith API base URL |
| `langsmith.api_key_env` | `LANGSMITH_API_KEY` | Environment variable holding the key |

Keys are read from the environment, not from the config, so they stay out of
the project folder and out of [snapshots](../tools/snapshots.md).

## Eligible traces

Only traces Potato ingested from one of the two services. The webhook receiver
and the Langfuse poller record where each trace came from in its item data
(`metadata.source` is `langfuse` or `langsmith`, and `metadata.original_id` is
the trace or root run id), and write-back sends to that trace. Items from data
files, and traces posted to the generic webhook, are never sent.

## Score values

One score per scheme:

| Scheme type | Value | Data type |
|---|---|---|
| radio, select | The answer most annotators chose. A tie is held, not sent (see below) | Categorical |
| multiselect | The classes more than half of the annotators chose, comma-separated, or `none` | Categorical |
| likert (without `labels`) | The median point | Numeric |
| slider, number | The mean | Numeric |

Text answers are not sent. The comment says how the value was reached, for
example `Potato: 2 of 3 annotator(s) chose success`. The metadata holds the
annotator count, the distribution of answers, the share of annotator pairs who
agreed (or the standard deviation, for numbers), and Potato's item id. An
adjudicated value replaces the vote, with the comment `Potato: adjudicated` and
the adjudicator in the metadata.

In LangSmith a numeric value goes in `score` and a categorical one in `value`,
with the comment and metadata on the feedback (`feedback_source.type: api`).

### Fields sent

Only these fields are sent:

- the trace or run id, the score name and value
- the comment
- in the metadata: the annotator count, the count of each answer (or the
  numeric values, for sliders and numbers), the pairwise agreement or standard
  deviation, whether the value was adjudicated, Potato's item id, and
  `source: potato`

Nothing names a person. Usernames and the adjudicator's name are not sent,
and neither is any free-text answer, since text schemes are not sent at all.
Labels are sent as written in the config.

### Ties

A tied vote on a radio, select or labelled likert scheme sends nothing,
because neither answer is the group's. The trace shows up as `held` in
`/admin/api/trace_writeback`, with the reason, for example
`tie: fail 1, pass 1; adjudicate to send`. An adjudication decision, or a
later answer that breaks the tie, sends it.

## Delivery

Sending happens in the background, from a queue in
`<task_dir>/trace_writeback.sqlite`. An annotator's save never waits on
Langfuse or LangSmith, and a service that is down loses nothing.

- A failure the service might recover from (a network error, HTTP 408, 429 or
  5xx) is retried with growing delays, up to 8 attempts.
- A rejection (any other 4xx, missing keys, or a Langfuse 207 partial accept)
  is not retried. Langfuse asks clients not to retry a 207.
- Each trace and scheme has a fixed id. When an answer changes (another
  annotator saves, or an adjudicator decides), the new value replaces the old
  one: Langfuse overwrites a score with the same id, name and date, and
  LangSmith feedback is updated in place. A value identical to the one already
  sent is not sent again.
- Langfuse servers older than the batch scores API reject a list; the score is
  then sent again as a single object.

`GET /admin/api/trace_writeback` (admin API key) reports how many scores are
pending, sent, failed and held, the latest errors, and why each held trace is
waiting:

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/admin/api/trace_writeback
```

## Troubleshooting

**Nothing is sent.** Look at `held` in `/admin/api/trace_writeback`: a tied
vote waits there with its reason. Otherwise check that the trace has
`metadata.source` set to `langfuse` or `langsmith` (the generic webhook sets
`webhook`), and that it has `min_annotators` answers.

**Why `trigger` and not `on`.** YAML reads a bare `on:` key as the boolean
`true`, so the key has a name YAML leaves alone.

**`no Langfuse keys` in the errors.** Set `LANGFUSE_PUBLIC_KEY` and
`LANGFUSE_SECRET_KEY`, or name other variables with `public_key_env` and
`secret_key_env`, then restart the server. A failed trace is queued again the
next time anyone saves an answer on it.

**A Langfuse score appears twice.** Langfuse overwrites a score only when its
id, name and date all match, so a trace whose answer changes on a later day
gets a second score dated that day.

## Related

- [Three-Pane Agent Trace Evaluation](eval_trace.md)
- [Adjudication](../administration/adjudication.md)
- [Tracing SDK](../integrations/tracing_sdk.md)

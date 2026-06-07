# QDA Mode Example

A composed qualitative-coding workspace: one config that turns on the
**codebook**, **memos**, **cases**, and **search** together via
`qda_mode.enabled: true`.

```bash
python potato/flask_server.py start \
  examples/advanced/qda-mode-example/config.yaml -p 8000
```

The data is ten short healthcare-interview excerpts across three
participants (`participant_id`), each tagged with a `condition`
(`rural` / `urban`).

## What to try in the UI

- **Codebook tray** (right edge): see the shared codes; add a code with
  the composer. Codes are usable immediately on the current item.
- **In-vivo coding**: select a phrase in the `codes` span scheme, press
  **`i`**, and mint a code from the selection (near-duplicate codes are
  suggested so you reuse instead of fragmenting).
- **Notes** (right edge): write an analytic memo on the instance or a
  text selection; choose Private or Shared.
- **Find** (left edge): full-text search the corpus (e.g. `copay`,
  `transit`) and **Claim** a matching excerpt into your queue.
- **Cases**: excerpts are auto-grouped by `participant_id`; the admin
  code crosstab can tabulate codes by `condition`.

## Export

```bash
python -m potato.export examples/advanced/qda-mode-example/config.yaml \
  --format quotation_report --option include_memos=true -o quotations.csv
python -m potato.export examples/advanced/qda-mode-example/config.yaml \
  --format codebook -o codebook.csv
```

See [docs/advanced/qda.md](../../../docs/advanced/qda.md) for the full guide.

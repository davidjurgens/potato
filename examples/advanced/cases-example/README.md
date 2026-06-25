# Cases Example

Demonstrates **cases**: grouping instances into units of analysis. Each
excerpt carries a `participant_id`; auto-detection groups excerpts by
participant and lifts `condition` (`treatment` / `control`) onto the
case so the admin code crosstab can tabulate codes by a participant-level
variable that isn't repeated on every excerpt.

```bash
python potato/flask_server.py start \
  examples/advanced/cases-example/config.yaml -p 8000
```

## What to try

- Inspect the cases via the API:

  ```bash
  curl -b cookies.txt http://localhost:8000/api/cases
  curl -b cookies.txt http://localhost:8000/api/cases/instance/1
  ```

- As admin, the **code crosstab** (`/admin/api/code_crosstab`) falls back
  to the case-level `condition` when an instance has no such field —
  letting you cross codes against the per-participant variable.

See [docs/advanced/cases.md](../../../docs/advanced/cases.md).

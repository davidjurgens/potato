# Reviewer Routing + Kanban Board

Production annotation runs on process, not just labels: who reviews what,
what needs a second opinion, what's stuck in adjudication. The **review
workflow** adds a Braintrust-style kanban board over your instances — a
*parallel* state store that never changes what annotators are served, it
tracks the review process on top.

States: `pending → in_review → needs_second → adjudication → done`. Every
item can carry an assignee and a priority; every state change is
audit-logged with its actor.

## Configuration

```yaml
review_workflow:
  enabled: true
  reviewers: [alice, bob]     # assignment pool
  auto_enroll: true           # enroll all loaded instances at startup (default)
  routing:                    # optional; first matching rule wins
    - when:                   # shared condition grammar (same as automation rules)
        - {field: "status", equals: "error"}
      state: in_review
      round_robin: true       # spread across `reviewers` (least-loaded first)
      priority: 10
    - when:
        - {field: "metadata.confidence", lt: 0.5}
      state: needs_second
      assign_to: alice        # ...or pin an explicit reviewer
      priority: 5
```

Items matching no rule enroll as unassigned `pending`. Enrollment is
idempotent — restarts never duplicate or reset board state (it persists in
`project.sqlite`).

### Routing runtime-ingested traces

Items that arrive after startup (webhook/Langfuse/directory watching) enroll
via the `enroll_review` [automation action](automation_rules.md):

```yaml
automation:
  enabled: true
  rules:
    - name: enroll-new-traces
      when: []
      actions:
        - type: enroll_review    # applies review_workflow.routing
```

## The board

Admins open `/admin/review`: one column per state, cards show the instance
preview, priority, an assignee dropdown, and move buttons. Cards in the
**adjudication** column deep-link into the [adjudication UI](../administration/adjudication.md)
(`/adjudicate?instance=<id>`) — resolving the disagreement there, then moving
the card to done, is the intended handoff.

Reviewers (plain logged-in users) can pull their open assignments:

```bash
curl -b cookies localhost:8000/api/review/my_queue
# {"queue": [{"instance_id": "rt-2", "state": "in_review", "priority": 10, ...}]}
```

## API summary

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/review` | Kanban board page (admin) |
| GET | `/admin/api/review/board` | `{states, board: {state: [items]}}` |
| POST | `/admin/api/review/move` | `{instance_id, state, note?}` |
| POST | `/admin/api/review/assign` | `{instance_id, assignee, priority?}` |
| GET | `/api/review/my_queue` | Current reviewer's open assignments |

Admin endpoints accept the shared `X-API-Key` or an RBAC admin session.

## Design note

The workflow deliberately does **not** touch assignment internals
(`ItemStateManager`): annotators keep getting items exactly as before, and
the board is a coordination layer for the humans running the review. To
*prioritize* what annotators see, combine it with the
[triage queue](triage_queue.md) or the `add_to_queue` automation action.

## Example

`examples/advanced/review-workflow/`:

```bash
python potato/flask_server.py start examples/advanced/review-workflow/config.yaml -p 8000
```

## Related

- [Automation Rules](automation_rules.md) — the shared condition grammar + `enroll_review`
- [Adjudication](../administration/adjudication.md) — the adjudication-column handoff
- [Judge Alignment](judge_alignment.md) — disagreement deep links use the same pattern

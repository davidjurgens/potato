# Expert Annotators (Upwork, Fiverr, and Direct Contracts)

Expert marketplaces (Upwork, Fiverr, Toptal, specialist networks) have no
participant-ID/completion-code protocol like Prolific — you hire someone and
communicate through the platform. Potato supports this workflow with
**expert invite links**.

## The workflow

1. Hire your expert on the marketplace (or directly).
2. Generate an invite token per expert and add it to your config (below).
3. Send each expert their personal link through the contract chat:
   `https://your-server.com/?invite=k3J9mQ2xLp8v`
4. The expert clicks the link and lands directly in the annotation task under
   the display name you assigned — no account creation, no password.
5. Payment stays on the marketplace (hourly or fixed contract). Use Potato's
   admin dashboard (annotation counts, time on task per user) as the work
   report when verifying invoices.

Unlike `url_direct` login with an open parameter (where any visitor who
guesses the URL self-registers), invite tokens are **pre-authorized**: unknown
tokens are rejected. This is the right posture for paid expert engagements.

## Configuration

```yaml
login:
  type: url_direct
  url_argument: invite

crowdsourcing:
  provider: expert
  expert:
    invites:                          # token -> expert display name
      k3J9mQ2xLp8v: "med-expert-1"
      Zt5wRq7nB4cd: "med-expert-2"
    # Or keep tokens out of the config (recommended for shared configs):
    # invites_file: configs/expert_invites.yaml   # YAML mapping or one token per line
    completion:
      message: "Thank you! Your work has been recorded. You can invoice per your contract."
```

Generate tokens with any random source, e.g.:

```bash
python -c "import secrets; print(secrets.token_urlsafe(12))"
```

## Work reports for invoicing

The admin dashboard's crowdsourcing view lists, per expert: total
annotations, time on task, annotations per hour, and completion percentage.
Export annotation output per expert from `output_annotation_dir/<name>/`.

## What about the Upwork API?

Upwork exposes a GraphQL API (OAuth 2.0, requires app approval) for job
posting and contract management. It does not provide an external-task
protocol, so Potato doesn't call it — the invite-link pattern above works for
every contracting platform without any API dependency.

## Related documentation

- [Choosing a crowdsourcing platform](crowdsourcing-platforms.md)
- [Admin dashboard](../administration/admin_dashboard.md)

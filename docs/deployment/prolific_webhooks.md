# Prolific Webhooks

Instead of polling the Prolific API, Potato can receive Prolific's webhook
events in real time. When a participant returns, times out, or is rejected,
their unannotated items are reclaimed immediately — no polling delay. (No
other annotation or experiment tool consumes Prolific webhooks as of this
writing.)

## Requirements

- Your Potato server must be reachable over **public HTTPS** (Prolific will
  not deliver to plain HTTP). Behind a reverse proxy is fine; for local
  testing use a tunnel such as ngrok.
- A webhook secret for your Prolific workspace (created via the hooks API —
  `POST /api/v1/hooks/secrets/` — or from workspace settings).

## Configuration

```yaml
crowdsourcing:
  provider: prolific
  prolific:
    token: "your-api-token"        # or via prolific.config_file_path
    study_id: "your-study-id"
    webhooks:
      enabled: true
      secret: "your-workspace-webhook-secret"
      auto_approve: false          # approve submissions as they hit AWAITING REVIEW
```

This activates `POST /webhooks/prolific`. There is no session auth on the
endpoint — every delivery is verified with HMAC-SHA256 over
`timestamp + body` against your secret (`X-Prolific-Request-Signature` /
`X-Prolific-Request-Timestamp`), and deliveries are deduplicated by
`X-Event-Id` (Prolific retries up to 13 times over 48 hours).

## Subscribing

Use the admin endpoint to subscribe your server to the standard events:

```bash
curl -X POST https://your-server.com/admin/api/crowd/webhooks/register \
  -H "X-API-Key: your-admin-key" -H "Content-Type: application/json" \
  -d '{"workspace_id": "<workspace-id>", "public_url": "https://your-server.com"}'
```

This creates subscriptions for `submission.status.change`,
`study.status.change`, `study.progress.change`, and
`study.has_high_return_rate` (skipping ones that already exist).

## What each event does

| Event | Potato's reaction |
|-------|-------------------|
| `submission.status.change` → RETURNED / TIMED-OUT / REJECTED | Reclaims the participant's unannotated item assignments immediately (respects `instance_reclaim` retention policies). |
| `submission.status.change` → AWAITING REVIEW | Auto-approves via the API if `auto_approve: true`. |
| `study.status.change`, `study.progress.change` | Recorded for the admin dashboard. |
| `study.has_high_return_rate` | Logged as a warning. |

## Polling as fallback

If you also enable the polling workload monitor
(`prolific.workload_checker: true`), Potato slows it to a reconciliation
interval (≥ 10 minutes) when webhooks are on — the poller only catches
events a delivery might have missed.

## Troubleshooting

- **All deliveries 401**: the configured `secret` doesn't match the workspace
  webhook secret. Check the delivery log via
  `GET /api/v1/hooks/subscriptions/<id>/events/`.
- **No deliveries at all**: subscription not confirmed or target not public
  HTTPS. Re-run the register endpoint and check the subscription status.
- **Prolific disabled the subscription**: persistent failures (e.g. your
  server was down > 48h) disable it; re-register.

## Related documentation

- [Prolific integration](prolific_integration.md)
- [Reverse proxy setup](reverse-proxy.md)

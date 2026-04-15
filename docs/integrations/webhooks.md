# Webhooks

Potato can send outgoing webhook notifications when annotation events occur, enabling integration with external pipelines, Slack alerts, and custom automation.

## Configuration

Add a `webhooks` section to your YAML config:

```yaml
webhooks:
  enabled: true
  endpoints:
    - name: "my_pipeline"
      url: "https://hooks.example.com/potato"
      secret: "your-hmac-secret"
      events:
        - annotation.created
        - item.fully_annotated
        - task.completed
      active: true
      timeout_seconds: 10

    - name: "quality_alerts"
      url: "https://hooks.slack.com/services/T00/B00/xxx"
      secret: ""
      events:
        - quality.attention_check_failed
      active: true
```

### Endpoint Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | string | `"unnamed"` | Human-readable endpoint name |
| `url` | string | *required* | HTTPS URL to receive POST requests |
| `secret` | string | `""` | HMAC-SHA256 secret for signing (recommended) |
| `events` | list | `[]` | Event types to subscribe to (`"*"` for all) |
| `active` | bool | `true` | Set `false` to disable without removing |
| `timeout_seconds` | int | `10` | HTTP request timeout |

## Event Types

| Event | Trigger |
|-------|---------|
| `annotation.created` | User submits an annotation |
| `annotation.updated` | User updates an existing annotation |
| `item.fully_annotated` | Item reaches required annotator count |
| `task.completed` | User completes all assigned items |
| `user.phase_completed` | User advances to next workflow phase |
| `quality.attention_check_failed` | User fails an attention check (and is blocked) |
| `webhook.test` | Sent via admin API test endpoint |

### Wildcard Subscription

Use `"*"` to receive all event types:

```yaml
events: ["*"]
```

## Payload Format

All webhooks are sent as `POST` requests with a JSON body:

```json
{
  "event": "annotation.created",
  "timestamp": "2026-03-14T12:00:00.000000Z",
  "data": {
    "user_id": "annotator@example.com",
    "instance_id": "item_42",
    "annotations": {"sentiment": {"Positive": 1}}
  }
}
```

## HMAC Signature Verification

When a `secret` is configured, Potato signs webhooks using the [Standard Webhooks](https://www.standardwebhooks.com/) specification:

### Headers

| Header | Description |
|--------|-------------|
| `webhook-id` | Unique delivery identifier |
| `webhook-timestamp` | Unix timestamp of delivery |
| `webhook-signature` | `v1,<base64-hmac-sha256>` |

### Verification (Python)

```python
import hashlib
import hmac
import base64

def verify_webhook(secret, webhook_id, timestamp, body_bytes, signature):
    to_sign = f"{webhook_id}.{timestamp}.".encode() + body_bytes
    expected = hmac.new(
        secret.encode(), to_sign, hashlib.sha256
    ).digest()
    expected_sig = "v1," + base64.b64encode(expected).decode()
    return hmac.compare_digest(expected_sig, signature)

# Usage in a Flask endpoint:
@app.route("/webhook", methods=["POST"])
def handle_webhook():
    is_valid = verify_webhook(
        secret="your-hmac-secret",
        webhook_id=request.headers["webhook-id"],
        timestamp=request.headers["webhook-timestamp"],
        body_bytes=request.get_data(),
        signature=request.headers["webhook-signature"],
    )
    if not is_valid:
        return "Invalid signature", 401

    payload = request.get_json()
    print(f"Received: {payload['event']}")
    return "OK", 200
```

### Verification (Node.js)

```javascript
const crypto = require('crypto');

function verifyWebhook(secret, webhookId, timestamp, bodyBuffer, signature) {
  const toSign = Buffer.concat([
    Buffer.from(`${webhookId}.${timestamp}.`),
    bodyBuffer,
  ]);
  const expected = crypto
    .createHmac('sha256', secret)
    .update(toSign)
    .digest('base64');
  return signature === `v1,${expected}`;
}
```

## Retry Behavior

Failed deliveries are retried with exponential backoff:

| Attempt | Delay |
|---------|-------|
| 1 | Immediate |
| 2 | 5 seconds |
| 3 | 30 seconds |
| 4 | 2 minutes |
| 5 | 10 minutes |
| 6 | 1 hour |

After 6 failed attempts, the delivery is permanently dropped. Failed deliveries are stored in a SQLite database (`{output_dir}/.webhooks/webhook_retries.db`) so they survive server restarts.

Webhook delivery is fully non-blocking — annotation requests are never delayed by webhook calls.

## Admin API

### Get Webhook Status

```bash
curl -H "X-API-Key: your-admin-key" \
  http://localhost:8000/admin/api/webhooks
```

Response:

```json
{
  "enabled": true,
  "endpoints": [
    {
      "name": "my_pipeline",
      "url": "https://hooks.example.com/potato",
      "events": ["annotation.created", "item.fully_annotated"],
      "active": true,
      "has_secret": true,
      "timeout_seconds": 10
    }
  ],
  "stats": {
    "endpoints": 1,
    "active_endpoints": 1,
    "total_emitted": 42,
    "total_dropped": 0,
    "pending_retries": 0
  }
}
```

### Send Test Webhook

```bash
curl -X POST \
  -H "X-API-Key: your-admin-key" \
  http://localhost:8000/admin/api/webhooks/test
```

## Troubleshooting

**Webhooks not firing?**
- Verify `webhooks.enabled: true` in your config
- Check that at least one endpoint has `active: true`
- Ensure event types in `events` list match (use `"*"` to catch all)

**Signature verification failing?**
- Ensure you're using the raw request body bytes, not re-serialized JSON
- Check that secrets match exactly (no trailing whitespace)
- Verify timestamp is read from `webhook-timestamp` header as a string

**Retries accumulating?**
- Check that your endpoint URL is reachable from the server
- Verify the endpoint returns `2xx` status codes on success
- Monitor via `GET /admin/api/webhooks` for retry counts

## Related Documentation

- [Quality Control](../workflow/quality_control.md) - Attention checks that trigger `quality.attention_check_failed`
- [Admin Dashboard](../administration/admin_dashboard.md) - Monitoring and management

# SONA Systems Integration Guide

[SONA Systems](https://www.sona-systems.com/) manages university participant
pools (students participating for course credit). Potato integrates with
SONA's web-study workflow, including **automatic server-side credit granting**.

## How it works

1. In SONA, create a web study and set the study URL to your Potato server
   with the `%SURVEY_CODE%` placeholder:

   ```
   https://your-server.com/?sona_code=%SURVEY_CODE%
   ```

   SONA replaces `%SURVEY_CODE%` with a unique per-participant code, which
   becomes the participant's identity in Potato.

2. The participant annotates in Potato.

3. On completion, Potato calls SONA's `WebstudyCredit` API **server-side** to
   grant the credit automatically — the participant doesn't need to do
   anything, and the grant succeeds even if they close the tab. If the
   server-side call fails, the done page falls back to SONA's client-side
   credit link.

Credit grants are idempotent: reloading the done page never double-credits.

## Configuration

Find your experiment ID and credit token in SONA's study information page
(the client-side completion URL shown there contains both).

```yaml
login:
  type: url_direct
  url_argument: sona_code

crowdsourcing:
  provider: sona
  sona:
    hostname: yourdept.sona-systems.com
    experiment_id: 123
    credit_token: 9185d436e5f94b1581b0918162f6d7e8
    # id_param: sona_code            # default; must match login.url_argument
```

## Testing locally

```bash
python potato/flask_server.py start examples/crowdsourcing/sona-example/config.yaml -p 8000
# then visit:
# http://localhost:8000/?sona_code=TESTCODE1
```

The credit-grant call will fail against a fake hostname — the done page then
shows the client-side credit link, which is the expected fallback behavior.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| "Missing required URL parameter: sona_code" | The SONA study URL lacks `?sona_code=%SURVEY_CODE%`, or `login.url_argument` doesn't match `id_param`. |
| Credit not granted automatically | Check server logs for the WebstudyCredit request; verify `experiment_id` and `credit_token`. Participants can still use the fallback link. |
| Credit granted twice | Cannot happen from Potato — grants are recorded per participant and skipped on re-render. |

## Related documentation

- [Choosing a crowdsourcing platform](crowdsourcing-platforms.md)
- [Crowdsourcing setup](crowdsourcing.md)

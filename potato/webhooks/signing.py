"""
Webhook HMAC-SHA256 Signing

Implements the Standard Webhooks signing spec:
  - webhook-id: unique delivery ID
  - webhook-timestamp: Unix timestamp
  - webhook-signature: HMAC-SHA256(secret, "{id}.{timestamp}.{body}")

See https://www.standardwebhooks.com/ for the full specification.
"""

import hashlib
import hmac
import time
import uuid


def sign_payload(secret, webhook_id, timestamp, payload_bytes):
    """Compute HMAC-SHA256 signature per Standard Webhooks spec.

    Args:
        secret: HMAC secret string.
        webhook_id: Unique delivery identifier.
        timestamp: Unix timestamp (int or str).
        payload_bytes: Raw payload bytes to sign.

    Returns:
        Base64-encoded HMAC-SHA256 signature prefixed with "v1,".
    """
    import base64

    to_sign = f"{webhook_id}.{timestamp}.".encode() + payload_bytes
    sig = hmac.new(
        secret.encode("utf-8"),
        to_sign,
        hashlib.sha256,
    ).digest()
    return "v1," + base64.b64encode(sig).decode()


def verify_signature(secret, webhook_id, timestamp, payload_bytes, signature):
    """Verify a Standard Webhooks signature.

    Args:
        secret: HMAC secret string.
        webhook_id: Delivery ID from webhook-id header.
        timestamp: Timestamp from webhook-timestamp header.
        payload_bytes: Raw body bytes.
        signature: Signature from webhook-signature header.

    Returns:
        True if signature is valid.
    """
    expected = sign_payload(secret, webhook_id, timestamp, payload_bytes)
    return hmac.compare_digest(expected, signature)


def build_headers(secret, payload_bytes, webhook_id=None, timestamp=None):
    """Build Standard Webhooks headers for a delivery.

    Args:
        secret: HMAC secret. If empty/None, returns headers without signature.
        payload_bytes: Raw JSON payload bytes.
        webhook_id: Optional delivery ID. Generated if not provided.
        timestamp: Optional Unix timestamp. Uses current time if not provided.

    Returns:
        Dict with webhook-id, webhook-timestamp, and (if secret) webhook-signature.
    """
    if webhook_id is None:
        webhook_id = f"msg_{uuid.uuid4().hex[:24]}"
    if timestamp is None:
        timestamp = int(time.time())

    headers = {
        "webhook-id": webhook_id,
        "webhook-timestamp": str(timestamp),
        "Content-Type": "application/json",
    }

    if secret:
        sig = sign_payload(secret, webhook_id, timestamp, payload_bytes)
        headers["webhook-signature"] = sig

    return headers

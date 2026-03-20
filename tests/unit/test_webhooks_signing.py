"""Tests for webhook HMAC-SHA256 signing."""

import pytest

from potato.webhooks.signing import sign_payload, verify_signature, build_headers


class TestSignPayload:
    def test_produces_v1_prefixed_signature(self):
        sig = sign_payload("secret", "msg_123", 1700000000, b'{"test": true}')
        assert sig.startswith("v1,")

    def test_deterministic(self):
        args = ("secret", "msg_abc", 1700000000, b'{"data": 1}')
        assert sign_payload(*args) == sign_payload(*args)

    def test_different_secrets_differ(self):
        common = ("msg_abc", 1700000000, b'{}')
        sig1 = sign_payload("secret1", *common)
        sig2 = sign_payload("secret2", *common)
        assert sig1 != sig2

    def test_different_payloads_differ(self):
        sig1 = sign_payload("secret", "msg_1", 100, b'{"a": 1}')
        sig2 = sign_payload("secret", "msg_1", 100, b'{"a": 2}')
        assert sig1 != sig2


class TestVerifySignature:
    def test_valid_signature(self):
        secret = "test-secret"
        webhook_id = "msg_test123"
        ts = 1700000000
        body = b'{"event": "test"}'
        sig = sign_payload(secret, webhook_id, ts, body)
        assert verify_signature(secret, webhook_id, ts, body, sig) is True

    def test_invalid_signature(self):
        assert verify_signature("secret", "msg_1", 100, b'{}', "v1,bad") is False

    def test_wrong_secret(self):
        body = b'{"x": 1}'
        sig = sign_payload("correct", "msg_1", 100, body)
        assert verify_signature("wrong", "msg_1", 100, body, sig) is False


class TestBuildHeaders:
    def test_includes_required_headers(self):
        headers = build_headers("secret", b'{}')
        assert "webhook-id" in headers
        assert "webhook-timestamp" in headers
        assert "webhook-signature" in headers
        assert headers["Content-Type"] == "application/json"

    def test_no_signature_without_secret(self):
        headers = build_headers("", b'{}')
        assert "webhook-id" in headers
        assert "webhook-signature" not in headers

    def test_custom_id_and_timestamp(self):
        headers = build_headers("s", b'{}', webhook_id="msg_custom", timestamp=42)
        assert headers["webhook-id"] == "msg_custom"
        assert headers["webhook-timestamp"] == "42"

    def test_signature_verifies(self):
        """Round-trip: build headers then verify the signature."""
        body = b'{"test": true}'
        secret = "round-trip-secret"
        headers = build_headers(secret, body, webhook_id="msg_rt", timestamp=999)
        assert verify_signature(
            secret,
            headers["webhook-id"],
            headers["webhook-timestamp"],
            body,
            headers["webhook-signature"],
        )

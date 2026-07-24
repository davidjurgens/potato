"""
Unit tests for Prolific webhook signature verification and idempotency.
"""

import base64
import hashlib
import hmac

import pytest

from potato.crowdsourcing.webhooks import (
    _mark_seen,
    clear_seen_events,
    verify_prolific_signature,
)


def sign(secret, timestamp, body):
    digest = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class TestSignatureVerification:
    SECRET = 'whsec_test'
    BODY = b'{"event_type": "submission.status.change"}'
    TS = '1752700000'

    def test_valid_signature(self):
        signature = sign(self.SECRET, self.TS, self.BODY)
        assert verify_prolific_signature(self.BODY, self.TS, signature, self.SECRET)

    def test_wrong_secret_rejected(self):
        signature = sign('other-secret', self.TS, self.BODY)
        assert not verify_prolific_signature(self.BODY, self.TS, signature, self.SECRET)

    def test_tampered_body_rejected(self):
        signature = sign(self.SECRET, self.TS, self.BODY)
        assert not verify_prolific_signature(b'{"evil": 1}', self.TS, signature, self.SECRET)

    def test_tampered_timestamp_rejected(self):
        """The timestamp is part of the MAC — replaying with a new ts fails."""
        signature = sign(self.SECRET, self.TS, self.BODY)
        assert not verify_prolific_signature(self.BODY, '1752799999', signature, self.SECRET)

    def test_garbage_and_missing_inputs(self):
        assert not verify_prolific_signature(self.BODY, self.TS, 'not-base64!!', self.SECRET)
        assert not verify_prolific_signature(self.BODY, '', 'sig', self.SECRET)
        assert not verify_prolific_signature(self.BODY, self.TS, '', self.SECRET)
        assert not verify_prolific_signature(self.BODY, self.TS, 'sig', '')


class TestIdempotency:
    def setup_method(self):
        clear_seen_events()

    def test_first_delivery_not_duplicate(self):
        assert _mark_seen('evt_1') is False

    def test_redelivery_is_duplicate(self):
        _mark_seen('evt_1')
        assert _mark_seen('evt_1') is True

    def test_missing_event_id_never_duplicate(self):
        assert _mark_seen(None) is False
        assert _mark_seen(None) is False

    def test_cache_is_bounded(self):
        from potato.crowdsourcing import webhooks
        for i in range(webhooks._SEEN_MAX + 50):
            _mark_seen(f'evt_{i}')
        assert len(webhooks._seen_event_ids) <= webhooks._SEEN_MAX
        # Oldest entries evicted, newest retained
        assert _mark_seen(f'evt_{webhooks._SEEN_MAX + 49}') is True
        assert _mark_seen('evt_0') is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

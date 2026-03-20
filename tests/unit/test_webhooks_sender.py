"""Tests for webhook delivery queue and retry logic."""

import json
import os
import sqlite3
import time
import pytest
from unittest.mock import patch, MagicMock

from potato.webhooks.sender import WebhookDeliveryQueue, RETRY_SCHEDULE, MAX_RETRIES


@pytest.fixture
def tmp_output_dir(tmp_path):
    """Provide a temporary directory for retry DB."""
    return str(tmp_path / "webhook_output")


class TestWebhookDeliveryQueue:
    def test_enqueue_returns_true(self):
        q = WebhookDeliveryQueue()
        result = q.enqueue("https://example.com", "secret", b'{"test": true}')
        assert result is True

    def test_enqueue_with_full_queue(self):
        q = WebhookDeliveryQueue()
        q._queue.maxsize = 1
        # Fill the queue
        q.enqueue("https://example.com", "", b'{}')
        # Next should fail
        result = q.enqueue("https://example.com", "", b'{}')
        assert result is False

    def test_start_stop(self):
        q = WebhookDeliveryQueue()
        q.start()
        assert q._running is True
        assert q._thread is not None
        assert q._thread.is_alive()
        q.stop()
        assert q._running is False

    def test_stop_without_start(self):
        q = WebhookDeliveryQueue()
        q.stop()  # Should not raise


class TestRetryStore:
    def test_db_created(self, tmp_output_dir):
        q = WebhookDeliveryQueue(output_dir=tmp_output_dir)
        assert os.path.exists(q._db_path)

    def test_store_and_retrieve_retry(self, tmp_output_dir):
        q = WebhookDeliveryQueue(output_dir=tmp_output_dir)
        delivery = {
            "id": "msg_test1",
            "url": "https://example.com",
            "secret": "",
            "payload_bytes": b'{"x": 1}',
            "attempt": 0,
        }
        q._store_retry(delivery, 1, time.time() - 1, "connection error")

        # Should be retrievable
        conn = sqlite3.connect(q._db_path)
        cursor = conn.execute("SELECT id, attempt FROM webhook_retries")
        rows = cursor.fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "msg_test1"
        assert rows[0][1] == 1

    def test_remove_retry(self, tmp_output_dir):
        q = WebhookDeliveryQueue(output_dir=tmp_output_dir)
        delivery = {
            "id": "msg_rm",
            "url": "https://example.com",
            "secret": "",
            "payload_bytes": b'{}',
        }
        q._store_retry(delivery, 1, time.time(), "error")
        q._remove_retry("msg_rm")

        conn = sqlite3.connect(q._db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM webhook_retries")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_get_retry_count(self, tmp_output_dir):
        q = WebhookDeliveryQueue(output_dir=tmp_output_dir)
        assert q.get_retry_count() == 0

        delivery = {"id": "msg_c1", "url": "u", "secret": "", "payload_bytes": b'{}'}
        q._store_retry(delivery, 1, time.time(), "err")
        assert q.get_retry_count() == 1

    def test_get_retry_count_without_db(self):
        q = WebhookDeliveryQueue()
        assert q.get_retry_count() == 0


class TestDelivery:
    @patch("potato.webhooks.sender.urlopen")
    def test_successful_delivery(self, mock_urlopen, tmp_output_dir):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_urlopen.return_value = mock_resp

        q = WebhookDeliveryQueue(output_dir=tmp_output_dir)
        delivery = {
            "id": "msg_ok",
            "url": "https://example.com/hook",
            "secret": "test-secret",
            "payload_bytes": b'{"event": "test"}',
            "attempt": 0,
        }
        q._deliver(delivery)

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "POST"
        assert req.full_url == "https://example.com/hook"

    @patch("potato.webhooks.sender.urlopen")
    def test_failed_delivery_stores_retry(self, mock_urlopen, tmp_output_dir):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")

        q = WebhookDeliveryQueue(output_dir=tmp_output_dir)
        delivery = {
            "id": "msg_fail",
            "url": "https://example.com/hook",
            "secret": "",
            "payload_bytes": b'{}',
            "attempt": 0,
        }
        q._deliver(delivery)

        assert q.get_retry_count() == 1

    @patch("potato.webhooks.sender.urlopen")
    def test_max_retries_exhausted(self, mock_urlopen, tmp_output_dir):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("timeout")

        q = WebhookDeliveryQueue(output_dir=tmp_output_dir)
        delivery = {
            "id": "msg_exhaust",
            "url": "https://example.com",
            "secret": "",
            "payload_bytes": b'{}',
            "attempt": MAX_RETRIES,  # Already at max
        }
        q._deliver(delivery)

        # Should NOT be stored for retry since max is exceeded
        assert q.get_retry_count() == 0


class TestRetrySchedule:
    def test_schedule_has_entries(self):
        assert len(RETRY_SCHEDULE) > 0

    def test_schedule_is_increasing(self):
        for i in range(1, len(RETRY_SCHEDULE)):
            assert RETRY_SCHEDULE[i] >= RETRY_SCHEDULE[i - 1]

    def test_max_retries_matches_schedule(self):
        assert MAX_RETRIES == len(RETRY_SCHEDULE) - 1

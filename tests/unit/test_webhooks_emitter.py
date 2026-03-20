"""Tests for webhook emitter event dispatch and fan-out."""

import json
import pytest
from unittest.mock import patch, MagicMock

from potato.webhooks.emitter import WebhookEmitter, WebhookEndpoint


@pytest.fixture
def mock_delivery_queue():
    """Patch WebhookDeliveryQueue to capture enqueue calls."""
    with patch("potato.webhooks.emitter.WebhookDeliveryQueue") as MockQueue:
        instance = MockQueue.return_value
        instance.enqueue.return_value = True
        instance.get_retry_count.return_value = 0
        yield instance


class TestWebhookEmitter:
    def test_no_endpoints(self, mock_delivery_queue):
        emitter = WebhookEmitter({"endpoints": []})
        count = emitter.emit("annotation.created", {"test": True})
        assert count == 0
        mock_delivery_queue.enqueue.assert_not_called()

    def test_event_matches_endpoint(self, mock_delivery_queue):
        config = {
            "endpoints": [{
                "name": "ep1",
                "url": "https://example.com/hook",
                "secret": "s3cret",
                "events": ["annotation.created"],
                "active": True,
            }]
        }
        emitter = WebhookEmitter(config)
        count = emitter.emit("annotation.created", {"data": "test"})
        assert count == 1
        mock_delivery_queue.enqueue.assert_called_once()

    def test_event_does_not_match(self, mock_delivery_queue):
        config = {
            "endpoints": [{
                "name": "ep1",
                "url": "https://example.com/hook",
                "events": ["task.completed"],
                "active": True,
            }]
        }
        emitter = WebhookEmitter(config)
        count = emitter.emit("annotation.created", {})
        assert count == 0

    def test_wildcard_matches_all(self, mock_delivery_queue):
        config = {
            "endpoints": [{
                "name": "catch_all",
                "url": "https://example.com/all",
                "events": ["*"],
                "active": True,
            }]
        }
        emitter = WebhookEmitter(config)
        count = emitter.emit("any.event.type", {"x": 1})
        assert count == 1

    def test_inactive_endpoint_skipped(self, mock_delivery_queue):
        config = {
            "endpoints": [{
                "name": "inactive",
                "url": "https://example.com/hook",
                "events": ["*"],
                "active": False,
            }]
        }
        emitter = WebhookEmitter(config)
        count = emitter.emit("annotation.created", {})
        assert count == 0

    def test_fan_out_to_multiple_endpoints(self, mock_delivery_queue):
        config = {
            "endpoints": [
                {
                    "name": "ep1",
                    "url": "https://a.com/hook",
                    "events": ["annotation.created"],
                    "active": True,
                },
                {
                    "name": "ep2",
                    "url": "https://b.com/hook",
                    "events": ["annotation.created", "task.completed"],
                    "active": True,
                },
                {
                    "name": "ep3",
                    "url": "https://c.com/hook",
                    "events": ["task.completed"],
                    "active": True,
                },
            ]
        }
        emitter = WebhookEmitter(config)
        count = emitter.emit("annotation.created", {})
        assert count == 2  # ep1 and ep2

    def test_endpoint_without_url_skipped(self, mock_delivery_queue):
        config = {
            "endpoints": [{
                "name": "no_url",
                "url": "",
                "events": ["*"],
            }]
        }
        emitter = WebhookEmitter(config)
        assert len(emitter.endpoints) == 0

    def test_stats_tracking(self, mock_delivery_queue):
        config = {
            "endpoints": [{
                "name": "ep1",
                "url": "https://example.com",
                "events": ["*"],
                "active": True,
            }]
        }
        emitter = WebhookEmitter(config)
        emitter.emit("e1", {})
        emitter.emit("e2", {})
        stats = emitter.get_stats()
        assert stats["total_emitted"] == 2
        assert stats["active_endpoints"] == 1

    def test_dropped_event_stats(self, mock_delivery_queue):
        mock_delivery_queue.enqueue.return_value = False  # Queue full
        config = {
            "endpoints": [{
                "name": "ep1",
                "url": "https://example.com",
                "events": ["*"],
                "active": True,
            }]
        }
        emitter = WebhookEmitter(config)
        count = emitter.emit("test", {})
        assert count == 0
        assert emitter.get_stats()["total_dropped"] == 1

    def test_get_endpoint_info_redacts_secrets(self, mock_delivery_queue):
        config = {
            "endpoints": [{
                "name": "ep1",
                "url": "https://example.com",
                "secret": "super-secret-key",
                "events": ["annotation.created"],
                "active": True,
            }]
        }
        emitter = WebhookEmitter(config)
        info = emitter.get_endpoint_info()
        assert len(info) == 1
        assert "secret" not in info[0]  # Secret not exposed
        assert info[0]["has_secret"] is True
        assert info[0]["name"] == "ep1"

"""
Regression test: the generic webhook normalizer must carry through common
quality-signal fields (status/feedback/score/tags) so triage and automation
rules can match them. Without this they were dropped during normalization.
"""

from potato.trace_ingestion.webhook_receiver import WebhookReceiver


def test_generic_normalize_preserves_signal_fields():
    receiver = WebhookReceiver(api_key="")
    trace = receiver.process_webhook({
        "id": "run-1",
        "task_description": "buy milk",
        "status": "error",
        "feedback": "thumbs_down",
        "score": 0.3,
        "tags": ["urgent"],
        "steps": [{"action_type": "click"}],
    }, format_hint="generic")

    assert trace["status"] == "error"
    assert trace["feedback"] == "thumbs_down"
    assert trace["score"] == 0.3
    assert trace["tags"] == ["urgent"]
    # And the core normalized fields are still present.
    assert trace["id"] == "webhook_run-1"
    assert trace["metadata"]["source"] == "webhook"


def test_absent_signals_not_injected():
    receiver = WebhookReceiver(api_key="")
    trace = receiver.process_webhook({"id": "r2", "task_description": "x", "steps": []},
                                     format_hint="generic")
    assert "status" not in trace
    assert "feedback" not in trace

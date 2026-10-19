"""
Write-back of Potato's answers to Langfuse and LangSmith.

A local HTTP server stands in for both services and records every request, so
the tests assert the bodies that would have been sent, field by field, and can
make the service fail on cue.
"""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from potato.trace_ingestion import writeback as wb
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory


class FakeService:
    """Records requests; ``replies`` is a queue of status codes (default 202)."""

    def __init__(self):
        self.requests = []
        self.replies = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"null")
                service.requests.append({"method": self.command, "path": self.path,
                                         "headers": dict(self.headers), "body": body})
                code = service.replies.pop(0) if service.replies else 202
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            do_POST = do_PATCH = _handle

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def service():
    fake = FakeService()
    yield fake
    fake.close()


@pytest.fixture
def queue(service):
    folder = create_test_directory("trace_writeback")
    cfg = {"trigger": "fully_annotated", "prefix": "potato", "min_annotators": 2,
           "langfuse": {"host": service.url, "public_key": "pk-1", "secret_key": "sk-1"},
           "langsmith": {"api_url": service.url, "api_key": "ls-1"}}
    q = wb.WritebackQueue(f"{folder}/q.sqlite", cfg)
    yield q
    cleanup_test_directory(folder)


RADIO = {"annotation_type": "radio", "name": "outcome", "labels": ["success", "failure"]}


def _status(q):
    return q.status()["counts"]


class TestSummaries:
    def test_radio_majority_with_the_count_in_the_comment(self):
        s = wb.summarize(RADIO, {"a": "success", "b": "success", "c": "failure"})
        assert (s["data_type"], s["value"]) == ("CATEGORICAL", "success")
        assert s["comment"] == "Potato: 2 of 3 annotator(s) chose success"
        assert s["metadata"]["distribution"] == {"success": 2, "failure": 1}
        assert s["metadata"]["pairwise_agreement"] == pytest.approx(1 / 3)

    def test_a_tie_sends_nothing(self):
        assert wb.summarize(RADIO, {"a": "success", "b": "failure"}) is None

    def test_multiselect_keeps_classes_more_than_half_chose(self):
        scheme = {"annotation_type": "multiselect", "name": "issues"}
        s = wb.summarize(scheme, {"a": ("loop", "tool"), "b": ("tool",), "c": ("tool", "x")})
        assert s["value"] == "tool"
        assert wb.summarize(scheme, {"a": ("loop",), "b": ("x",)})["value"] == "none"

    def test_numbers_are_averaged_and_likert_points_take_the_median(self):
        slider = wb.summarize({"annotation_type": "slider", "name": "q"}, {"a": 2.0, "b": 4.0})
        assert (slider["data_type"], slider["value"]) == ("NUMERIC", 3.0)
        likert = wb.summarize({"annotation_type": "likert", "name": "q", "size": 5},
                              {"a": "1", "b": "4", "c": "5"})
        assert (likert["value"], likert["metadata"]["statistic"]) == (4.0, "median")

    def test_stored_labels_become_answers(self):
        assert wb._answer("radio", {"success": "success"}) == "success"
        assert wb._answer("multiselect", {"x": "x", "y": "y", "z": False}) == ("x", "y")
        assert wb._answer("slider", {"slider": "7"}) == 7.0
        assert wb._answer("radio", {"text_box": "a note"}) is None

    def test_only_ingested_traces_are_targets(self):
        assert wb.trace_target({"metadata": {"source": "langfuse", "original_id": "t1"}}) == ("langfuse", "t1")
        assert wb.trace_target({"metadata": {"source": "webhook", "original_id": "t1"}}) is None
        assert wb.trace_target({"text": "plain item"}) is None


class TestLangfuse:
    def _score(self, value="success"):
        summary = wb.summarize(RADIO, {"a": value, "b": value})
        return wb.langfuse_score("trace-9", "potato.outcome", summary, instance_id="langfuse_trace-9",
                                 score_uuid=wb.score_id("langfuse", "langfuse_trace-9", "outcome"))

    def test_the_score_sent(self, queue, service):
        queue.enqueue("langfuse", "langfuse_trace-9", "outcome", self._score())
        assert queue.deliver_due() == 1
        request = service.requests[0]
        assert (request["method"], request["path"]) == ("POST", "/api/public/scores")
        assert base64.b64decode(request["headers"]["Authorization"].split()[1]) == b"pk-1:sk-1"
        [score] = request["body"]  # an array, as the batch API takes
        assert score["traceId"] == "trace-9"
        assert (score["name"], score["value"], score["dataType"]) == ("potato.outcome", "success", "CATEGORICAL")
        assert score["metadata"]["potato_item_id"] == "langfuse_trace-9"
        assert score["id"] == wb.score_id("langfuse", "langfuse_trace-9", "outcome")
        assert _status(queue) == {"pending": 0, "sent": 1, "failed": 0, "held": 0}

    def test_an_unchanged_score_is_not_sent_again(self, queue, service):
        assert queue.enqueue("langfuse", "i", "outcome", self._score())
        queue.deliver_due()
        assert not queue.enqueue("langfuse", "i", "outcome", self._score())
        assert queue.enqueue("langfuse", "i", "outcome", self._score("failure"))

    def test_an_older_server_gets_a_single_object(self, queue, service):
        service.replies = [400, 200]
        queue.enqueue("langfuse", "i", "outcome", self._score())
        assert queue.deliver_due() == 1
        assert isinstance(service.requests[0]["body"], list)
        assert service.requests[1]["body"]["traceId"] == "trace-9"

    def test_a_server_error_is_retried_later(self, queue, service):
        service.replies = [503]
        queue.enqueue("langfuse", "i", "outcome", self._score())
        assert queue.deliver_due(now=1000.0) == 0
        assert _status(queue)["pending"] == 1
        assert queue.deliver_due(now=1005.0) == 0  # backoff: not due yet
        assert len(service.requests) == 1
        assert queue.deliver_due(now=1000.0 + 21) == 1
        assert _status(queue) == {"pending": 0, "sent": 1, "failed": 0, "held": 0}

    def test_a_rejection_is_not_retried(self, queue, service):
        service.replies = [401]
        queue.enqueue("langfuse", "i", "outcome", self._score())
        queue.deliver_due()
        assert _status(queue)["failed"] == 1
        assert "HTTP 401" in queue.status()["recent_errors"][0]["error"]

    def test_a_partly_accepted_batch_is_not_retried(self, queue, service):
        service.replies = [207]
        queue.enqueue("langfuse", "i", "outcome", self._score())
        queue.deliver_due()
        assert _status(queue)["failed"] == 1

    def test_missing_keys_fail_with_a_message(self, queue, service):
        queue.cfg["langfuse"]["secret_key"] = ""
        queue.enqueue("langfuse", "i", "outcome", self._score())
        queue.deliver_due()
        assert service.requests == []
        assert "LANGFUSE_SECRET_KEY" in queue.status()["recent_errors"][0]["error"]


class TestLangSmith:
    def _feedback(self, value):
        summary = wb.summarize(RADIO, {"a": value, "b": value})
        return wb.langsmith_feedback("run-1", "potato.outcome", summary, instance_id="langsmith_run-1",
                                     score_uuid=wb.score_id("langsmith", "langsmith_run-1", "outcome"))

    def test_created_then_updated(self, queue, service):
        service.replies = [200, 200]
        queue.enqueue("langsmith", "i", "outcome", self._feedback("success"))
        queue.deliver_due()
        create = service.requests[0]
        assert (create["method"], create["path"]) == ("POST", "/api/v1/feedback")
        assert create["headers"]["x-api-key"] == "ls-1"
        body = create["body"]
        assert (body["run_id"], body["key"], body["value"]) == ("run-1", "potato.outcome", "success")
        assert body["feedback_source"]["type"] == "api"
        assert "score" not in body

        queue.enqueue("langsmith", "i", "outcome", self._feedback("failure"))
        queue.deliver_due()
        update = service.requests[1]
        assert (update["method"], update["path"]) == ("PATCH", f"/api/v1/feedback/{body['id']}")
        assert update["body"] == {"value": "failure", "comment": "Potato: 2 of 2 annotator(s) chose failure"}

    def test_an_update_to_a_deleted_feedback_creates_it_again(self, queue, service):
        service.replies = [200, 404, 200]
        queue.enqueue("langsmith", "i", "outcome", self._feedback("success"))
        queue.deliver_due()
        queue.enqueue("langsmith", "i", "outcome", self._feedback("failure"))
        queue.deliver_due()
        assert [r["method"] for r in service.requests] == ["POST", "PATCH", "POST"]

    def test_numbers_go_in_score(self):
        summary = wb.summarize({"annotation_type": "slider", "name": "q"}, {"a": 1.0, "b": 3.0})
        body = wb.langsmith_feedback("run-1", "potato.q", summary, instance_id="i", score_uuid="u")
        assert body["score"] == 2.0 and "value" not in body


class TestSettings:
    def test_off_unless_ingestion_and_writeback_are_on(self):
        assert wb.settings({}) is None
        assert wb.settings({"trace_ingestion": {"enabled": True}}) is None
        assert wb.settings({"trace_ingestion": {"enabled": False, "writeback": {}}}) is None

    def test_langfuse_defaults_come_from_the_source(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        cfg = wb.settings({"trace_ingestion": {"enabled": True, "writeback": {},
                           "sources": [{"type": "langfuse", "api_url": "https://lf.example/",
                                        "public_key": "pk", "secret_key": "sk"}]}})
        assert cfg["langfuse"] == {"host": "https://lf.example", "public_key": "pk", "secret_key": "sk"}
        assert (cfg["trigger"], cfg["prefix"], cfg["min_annotators"]) == ("fully_annotated", "potato", 2)

    def test_keys_from_the_named_environment_variables(self, monkeypatch):
        monkeypatch.setenv("MY_LS", "secret-ls")
        cfg = wb.settings({"trace_ingestion": {"enabled": True, "writeback": {
            "langsmith": {"api_key_env": "MY_LS"}}}, "max_annotations_per_item": 3})
        assert cfg["langsmith"]["api_key"] == "secret-ls"
        assert cfg["min_annotators"] == 3

    def test_a_bad_trigger_is_refused(self):
        with pytest.raises(ValueError, match="fully_annotated or adjudicated"):
            wb.settings({"trace_ingestion": {"enabled": True, "writeback": {"trigger": "sometimes"}}})


class TestHooks:
    """on_save / on_adjudication decide what to queue; the item lookups and
    the adjudication record are stubbed, the decision logic is real."""

    CONFIG = {"trace_ingestion": {"enabled": True, "writeback": {}},
              "annotation_schemes": [RADIO], "max_annotations_per_item": 2}

    @pytest.fixture
    def recorded(self, monkeypatch, queue):
        monkeypatch.setattr(wb, "_item_data", lambda iid: {
            "metadata": {"source": "langfuse", "original_id": f"trace-{iid}"}})
        monkeypatch.setattr(wb, "get_queue", lambda config, start=True: queue)
        return queue

    def _pending(self, q):
        import sqlite3
        with sqlite3.connect(q.db_path) as db:
            return [json.loads(p) for (p,) in db.execute(
                "SELECT payload FROM writeback WHERE status='pending'")]

    def test_one_annotator_is_not_enough(self, recorded, monkeypatch):
        monkeypatch.setattr(wb, "item_answers", lambda iid, s: {"outcome": {"a": "success"}})
        monkeypatch.setattr(wb, "_adjudicated", lambda c, iid: {})
        assert wb.on_save("i1", self.CONFIG) == 0
        monkeypatch.setattr(wb, "item_answers", lambda iid, s: {"outcome": {"a": "success", "b": "success"}})
        assert wb.on_save("i1", self.CONFIG) == 1
        [score] = self._pending(recorded)
        assert (score["traceId"], score["value"]) == ("trace-i1", "success")

    def test_an_adjudicated_value_wins_over_the_vote(self, recorded, monkeypatch):
        monkeypatch.setattr(wb, "item_answers", lambda iid, s: {"outcome": {"a": "success", "b": "failure"}})
        decided = wb.adjudicated_value(RADIO, {"failure": True})
        monkeypatch.setattr(wb, "_adjudicated", lambda c, iid: {"outcome": decided})
        assert wb.on_save("i1", self.CONFIG) == 1
        [score] = self._pending(recorded)
        assert (score["value"], score["comment"]) == ("failure", "Potato: adjudicated")

    def test_adjudicated_mode_waits_for_the_decision(self, recorded, monkeypatch):
        config = {**self.CONFIG, "trace_ingestion": {"enabled": True, "writeback": {"trigger": "adjudicated"}}}
        monkeypatch.setattr(wb, "item_answers", lambda iid, s: {"outcome": {"a": "success", "b": "success"}})
        assert wb.on_save("i1", config) == 0
        monkeypatch.setattr(wb, "_adjudicated", lambda c, iid: {
            "outcome": wb.adjudicated_value(RADIO, "success")})

        class Decision:
            instance_id = "i1"
        assert wb.on_adjudication(Decision(), config) == 1

    def test_a_failure_inside_never_reaches_the_save(self, monkeypatch):
        monkeypatch.setattr(wb, "_item_data", lambda iid: 1 / 0)
        assert wb.on_save("i1", self.CONFIG) == 0


class TestYamlKey:
    """Found by the potato-skill agent: the key was `on`, which YAML reads as
    True, and `potato validate` crashed on it."""

    def test_trigger_is_a_plain_word_in_yaml(self):
        import yaml
        assert yaml.safe_load("writeback:\n  trigger: adjudicated") == {
            "writeback": {"trigger": "adjudicated"}}

    def test_validate_reports_a_bare_on_key_instead_of_crashing(self):
        from potato.validate_cli import validate_config_file as validate_config
        folder = create_test_directory("writeback_yaml_on")
        try:
            import os
            os.makedirs(os.path.join(folder, "data"))
            with open(os.path.join(folder, "data", "d.jsonl"), "w") as handle:
                handle.write('{"id": "t1", "text": "x"}\n')
            path = os.path.join(folder, "config.yaml")
            with open(path, "w") as handle:
                handle.write(
                    "annotation_task_name: t\ntask_dir: .\noutput_annotation_dir: annotation_output/\n"
                    "data_files: [data/d.jsonl]\nitem_properties: {id_key: id, text_key: text}\n"
                    "trace_ingestion:\n  enabled: true\n  api_key: k\n  writeback:\n    on: adjudicated\n"
                    "annotation_schemes:\n  - {annotation_type: radio, name: v, description: d, labels: [a, b]}\n")
            report = validate_config(path)
            assert not any("Unexpected validation error" in e for e in report.errors)
            assert any("writeback.on" in w for w in report.unknown_keys + report.other_warnings)
        finally:
            cleanup_test_directory(folder)

    def test_the_unknown_key_check_survives_a_non_string_key(self, caplog):
        from potato.server_utils.config_module import validate_unknown_keys
        validate_unknown_keys({"trace_ingestion": {"enabled": True, "writeback": {True: "x", 3: "y"}}})
        assert any("not a string" in r.getMessage() for r in caplog.records)

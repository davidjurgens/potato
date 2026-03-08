"""Tests for the SWE-bench trace converter."""

import json
import pytest

from potato.trace_converter.converters.swebench_converter import SWEBenchConverter


class TestSWEBenchConverterDetect:
    """Detection tests for SWE-bench format."""

    def test_detect_basic(self):
        converter = SWEBenchConverter()
        data = [{
            "instance_id": "django__django-11133",
            "problem_statement": "HttpResponse doesn't handle memoryview",
            "patch": "diff --git a/..."
        }]
        assert converter.detect(data) is True

    def test_detect_with_model_patch(self):
        converter = SWEBenchConverter()
        data = [{
            "instance_id": "django__django-11133",
            "problem_statement": "Bug description",
            "model_patch": "diff --git a/..."
        }]
        assert converter.detect(data) is True

    def test_reject_missing_instance_id(self):
        converter = SWEBenchConverter()
        data = [{"problem_statement": "Bug", "patch": "diff"}]
        assert converter.detect(data) is False

    def test_reject_missing_problem_statement(self):
        converter = SWEBenchConverter()
        data = [{"instance_id": "test", "patch": "diff"}]
        assert converter.detect(data) is False

    def test_reject_missing_patch(self):
        converter = SWEBenchConverter()
        data = [{"instance_id": "test", "problem_statement": "Bug"}]
        assert converter.detect(data) is False

    def test_reject_empty(self):
        converter = SWEBenchConverter()
        assert converter.detect([]) is False


class TestSWEBenchConverterConvert:
    """Conversion tests for SWE-bench format."""

    def get_sample_data(self):
        return [{
            "instance_id": "django__django-11133",
            "problem_statement": "HttpResponse doesn't handle memoryview objects properly.",
            "repo": "django/django",
            "version": "3.0",
            "base_commit": "abc123def",
            "model_patch": "diff --git a/django/http/response.py b/django/http/response.py\n--- a/django/http/response.py\n+++ b/django/http/response.py\n@@ -1,3 +1,5 @@",
            "model_name_or_path": "gpt-4",
            "FAIL_TO_PASS": '["test_memoryview_response"]',
            "PASS_TO_PASS": '["test_basic_response", "test_streaming"]',
            "test_result": "resolved"
        }]

    def test_basic_conversion(self):
        converter = SWEBenchConverter()
        traces = converter.convert(self.get_sample_data())
        assert len(traces) == 1
        trace = traces[0]
        assert trace.id == "django__django-11133"
        assert trace.agent_name == "gpt-4"

    def test_task_description(self):
        converter = SWEBenchConverter()
        traces = converter.convert(self.get_sample_data())
        assert "memoryview" in traces[0].task_description

    def test_conversation_has_problem_and_patch(self):
        converter = SWEBenchConverter()
        traces = converter.convert(self.get_sample_data())
        conv = traces[0].conversation
        # Problem statement as User
        assert conv[0]["speaker"] == "User"
        assert "memoryview" in conv[0]["text"]
        # Patch as Agent (Patch)
        patch_turns = [t for t in conv if t["speaker"] == "Agent (Patch)"]
        assert len(patch_turns) == 1
        assert "diff" in patch_turns[0]["text"]

    def test_test_results_in_conversation(self):
        converter = SWEBenchConverter()
        traces = converter.convert(self.get_sample_data())
        conv = traces[0].conversation
        env_turns = [t for t in conv if t["speaker"] == "Environment"]
        assert len(env_turns) == 1
        assert "resolved" in env_turns[0]["text"]
        assert "FAIL_TO_PASS" in env_turns[0]["text"]

    def test_metadata(self):
        converter = SWEBenchConverter()
        traces = converter.convert(self.get_sample_data())
        meta = traces[0].metadata_table
        assert any(m["Property"] == "Repository" and m["Value"] == "django/django" for m in meta)
        assert any(m["Property"] == "Version" and m["Value"] == "3.0" for m in meta)
        assert any(m["Property"] == "Test Result" and m["Value"] == "resolved" for m in meta)
        assert any(m["Property"] == "FAIL_TO_PASS Count" and m["Value"] == "1" for m in meta)
        assert any(m["Property"] == "PASS_TO_PASS Count" and m["Value"] == "2" for m in meta)

    def test_parse_test_list_json_string(self):
        converter = SWEBenchConverter()
        result = converter._parse_test_list('["test1", "test2"]')
        assert result == ["test1", "test2"]

    def test_parse_test_list_actual_list(self):
        converter = SWEBenchConverter()
        result = converter._parse_test_list(["test1", "test2"])
        assert result == ["test1", "test2"]

    def test_parse_test_list_empty(self):
        converter = SWEBenchConverter()
        assert converter._parse_test_list("") == []
        assert converter._parse_test_list(None) == []

    def test_single_item(self):
        converter = SWEBenchConverter()
        data = self.get_sample_data()[0]
        traces = converter.convert(data)
        assert len(traces) == 1

    def test_to_dict(self):
        converter = SWEBenchConverter()
        traces = converter.convert(self.get_sample_data())
        d = traces[0].to_dict()
        assert "id" in d
        assert "conversation" in d

    def test_with_model_trajectory(self):
        converter = SWEBenchConverter()
        data = [{
            "instance_id": "test__repo-001",
            "problem_statement": "Bug in feature X",
            "patch": "diff...",
            "model_trajectory": [
                {"thought": "I need to investigate", "action": "find . -name '*.py'", "observation": "file.py"},
                {"thought": "Found the file", "action": "edit file.py", "observation": "Done"}
            ]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        thoughts = [t for t in conv if "Thought" in t["speaker"]]
        actions = [t for t in conv if "Action" in t["speaker"]]
        assert len(thoughts) == 2
        assert len(actions) == 2

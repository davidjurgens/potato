"""
SWE-bench Converter

Converts SWE-bench dataset format traces to Potato's canonical format.

Expected input format:
{
    "instance_id": "django__django-11133",
    "problem_statement": "HttpResponse doesn't handle memoryview objects...",
    "repo": "django/django",
    "version": "3.0",
    "base_commit": "abc123",
    "patch": "diff --git a/...",
    "model_patch": "diff --git a/...",
    "model_name_or_path": "gpt-4",
    "FAIL_TO_PASS": "[\"test_case_1\", \"test_case_2\"]",
    "PASS_TO_PASS": "[\"test_case_3\"]",
    "test_result": "resolved"
}

Also supports SWE-bench trajectory format with model_trajectory field.
"""

import json
from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class SWEBenchConverter(BaseTraceConverter):
    """Converter for SWE-bench coding benchmark traces."""

    format_name = "swebench"
    description = "SWE-bench coding agent benchmark format"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            trace_id = item.get("instance_id", f"swebench_{len(results)}")
            problem = item.get("problem_statement", "")
            repo = item.get("repo", "")
            version = item.get("version", "")
            model_name = item.get("model_name_or_path", "")

            # Build conversation
            conversation = []

            # Problem statement as User message
            if problem:
                conversation.append({"speaker": "User", "text": problem})

            # Model trajectory if available (detailed steps)
            trajectory = item.get("model_trajectory", [])
            if isinstance(trajectory, list):
                for step in trajectory:
                    if isinstance(step, dict):
                        if step.get("thought"):
                            conversation.append({
                                "speaker": "Agent (Thought)",
                                "text": step["thought"]
                            })
                        if step.get("action"):
                            conversation.append({
                                "speaker": "Agent (Action)",
                                "text": step["action"]
                            })
                        if step.get("observation"):
                            conversation.append({
                                "speaker": "Environment",
                                "text": step["observation"]
                            })

            # Model patch as Agent output
            patch = item.get("model_patch", item.get("patch", ""))
            if patch:
                conversation.append({
                    "speaker": "Agent (Patch)",
                    "text": f"```diff\n{patch}\n```"
                })

            # Test results as Environment
            test_result = item.get("test_result", "")
            fail_to_pass = self._parse_test_list(item.get("FAIL_TO_PASS", ""))
            pass_to_pass = self._parse_test_list(item.get("PASS_TO_PASS", ""))

            if fail_to_pass or pass_to_pass or test_result:
                test_summary_parts = []
                if test_result:
                    test_summary_parts.append(f"Result: {test_result}")
                if fail_to_pass:
                    test_summary_parts.append(f"FAIL_TO_PASS ({len(fail_to_pass)}): {', '.join(fail_to_pass[:5])}")
                    if len(fail_to_pass) > 5:
                        test_summary_parts[-1] += f" ... (+{len(fail_to_pass) - 5} more)"
                if pass_to_pass:
                    test_summary_parts.append(f"PASS_TO_PASS ({len(pass_to_pass)}): {', '.join(pass_to_pass[:5])}")
                    if len(pass_to_pass) > 5:
                        test_summary_parts[-1] += f" ... (+{len(pass_to_pass) - 5} more)"
                conversation.append({
                    "speaker": "Environment",
                    "text": "\n".join(test_summary_parts)
                })

            # Build metadata table
            metadata_table = []
            if repo:
                metadata_table.append({"Property": "Repository", "Value": repo})
            if version:
                metadata_table.append({"Property": "Version", "Value": version})
            if model_name:
                metadata_table.append({"Property": "Model", "Value": model_name})
            if test_result:
                metadata_table.append({"Property": "Test Result", "Value": test_result})
            if fail_to_pass:
                metadata_table.append({"Property": "FAIL_TO_PASS Count", "Value": str(len(fail_to_pass))})
            if pass_to_pass:
                metadata_table.append({"Property": "PASS_TO_PASS Count", "Value": str(len(pass_to_pass))})

            base_commit = item.get("base_commit", "")
            if base_commit:
                metadata_table.append({"Property": "Base Commit", "Value": base_commit})

            trace = CanonicalTrace(
                id=trace_id,
                task_description=problem[:500] if problem else f"SWE-bench: {trace_id}",
                conversation=conversation,
                agent_name=model_name,
                metadata_table=metadata_table,
            )
            results.append(trace)

        return results

    def _parse_test_list(self, value: Any) -> List[str]:
        """Parse a test list field (may be JSON string or actual list)."""
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False

        # SWE-bench requires instance_id + problem_statement
        if "instance_id" not in first:
            return False
        if "problem_statement" not in first:
            return False
        # Must also have either patch or model_patch
        return "patch" in first or "model_patch" in first

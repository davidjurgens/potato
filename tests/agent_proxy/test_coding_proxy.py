"""Unit tests for coding-agent proxies.

The planner LLM is replaced with a deterministic stub queue so each test
controls exactly which actions get executed. The subprocess proxy runs
real `python` / `bash` commands; the docker proxy is exercised via
mocked subprocess calls so the test suite doesn't require a Docker
daemon.
"""
import json
import os
import shutil
from unittest.mock import patch, MagicMock

import pytest

from potato.agent_proxy import AgentProxyFactory
from potato.agent_proxy.coding_proxy import (
    CodingAgentProxy,
    DockerCodingAgentProxy,
    SubprocessCodingAgentProxy,
    _ExecResult,
)


def _stub_planner(*plan_dicts):
    """Build a stub LLM that returns the given dicts in order, one per call.

    The dicts are the {thought, action} objects the real planner returns.
    """
    queue = list(plan_dicts)

    def chat_query(messages):
        if not queue:
            return json.dumps({"thought": "", "action": {"type": "finish", "code": "done"}})
        return json.dumps(queue.pop(0))

    stub = MagicMock()
    stub.chat_query.side_effect = chat_query
    return stub


@pytest.fixture
def subprocess_proxy():
    proxy = SubprocessCodingAgentProxy({
        "type": "subprocess_coding",
        "llm": {"endpoint_type": "ollama", "model": "stub"},
        "execution": {"per_step_timeout": 5, "max_output_chars": 2000},
    })
    return proxy


class TestRegistration:
    def test_subprocess_coding_registered(self):
        assert "subprocess_coding" in AgentProxyFactory.get_supported_types()

    def test_docker_coding_registered(self):
        assert "docker_coding" in AgentProxyFactory.get_supported_types()


class TestSubprocessCodingAgentProxy:
    def test_python_action_runs_and_captures_stdout(self, subprocess_proxy):
        plan = {"thought": "compute", "action": {"type": "python", "code": "print(2 + 2)"}}
        subprocess_proxy._llm = _stub_planner(plan)
        ctx = subprocess_proxy.start_session("Compute 2+2")
        try:
            resp = subprocess_proxy.send_message("please compute 2+2", ctx)
            assert resp.message.role == "agent"
            assert "4" in resp.message.content
            assert "[exit=0]" in resp.message.content
        finally:
            subprocess_proxy.end_session(ctx)
            assert not os.path.exists(ctx["workspace"])

    def test_shell_action_runs_in_workspace(self, subprocess_proxy):
        plan = {"thought": "list files", "action": {"type": "shell", "code": "echo hello && ls"}}
        subprocess_proxy._llm = _stub_planner(plan)
        ctx = subprocess_proxy.start_session("list things")
        try:
            resp = subprocess_proxy.send_message("ls the workspace", ctx)
            assert "hello" in resp.message.content
            assert "[exit=0]" in resp.message.content
        finally:
            subprocess_proxy.end_session(ctx)

    def test_starter_files_written_to_workspace(self):
        proxy = SubprocessCodingAgentProxy({
            "llm": {"endpoint_type": "ollama"},
            "execution": {
                "per_step_timeout": 5,
                "starter_files": {"hello.txt": "world\n"},
            },
        })
        proxy._llm = _stub_planner({
            "thought": "read", "action": {"type": "shell", "code": "cat hello.txt"},
        })
        ctx = proxy.start_session("starter")
        try:
            resp = proxy.send_message("read it", ctx)
            assert "world" in resp.message.content
        finally:
            proxy.end_session(ctx)

    def test_finish_action_marks_session_done(self, subprocess_proxy):
        plan = {"thought": "all good", "action": {"type": "finish", "code": "Sum is 4"}}
        subprocess_proxy._llm = _stub_planner(plan)
        ctx = subprocess_proxy.start_session("compute 2+2")
        try:
            resp = subprocess_proxy.send_message("please compute 2+2", ctx)
            assert resp.done is True
            assert "Sum is 4" in resp.message.content
            assert ctx["finished"] is True
            # Subsequent send_message returns done=True without re-planning
            resp2 = subprocess_proxy.send_message("hi", ctx)
            assert resp2.done is True
        finally:
            subprocess_proxy.end_session(ctx)

    def test_timeout_terminates_long_running_code(self):
        proxy = SubprocessCodingAgentProxy({
            "llm": {"endpoint_type": "ollama"},
            "execution": {"per_step_timeout": 1, "max_output_chars": 500},
        })
        plan = {"thought": "loop", "action": {"type": "python", "code": "while True: pass"}}
        proxy._llm = _stub_planner(plan)
        ctx = proxy.start_session("infinite loop")
        try:
            resp = proxy.send_message("loop forever", ctx)
            assert "timeout" in resp.message.content.lower()
        finally:
            proxy.end_session(ctx)

    def test_invalid_action_type_falls_through(self, subprocess_proxy):
        plan = {"thought": "?", "action": {"type": "magic", "code": "do stuff"}}
        subprocess_proxy._llm = _stub_planner(plan)
        ctx = subprocess_proxy.start_session("test")
        try:
            resp = subprocess_proxy.send_message("hi", ctx)
            assert "invalid action type" in resp.message.content.lower()
        finally:
            subprocess_proxy.end_session(ctx)

    def test_planner_failure_aborts_session(self, subprocess_proxy):
        subprocess_proxy._llm = MagicMock()
        subprocess_proxy._llm.chat_query.side_effect = RuntimeError("model down")
        ctx = subprocess_proxy.start_session("test")
        try:
            resp = subprocess_proxy.send_message("hi", ctx)
            assert resp.message.role == "error"
            assert ctx["finished"] is True
        finally:
            subprocess_proxy.end_session(ctx)

    def test_output_truncation(self):
        proxy = SubprocessCodingAgentProxy({
            "llm": {"endpoint_type": "ollama"},
            "execution": {"per_step_timeout": 5, "max_output_chars": 100},
        })
        plan = {
            "thought": "spam", "action": {"type": "python", "code": "print('x' * 5000)"},
        }
        proxy._llm = _stub_planner(plan)
        ctx = proxy.start_session("spam")
        try:
            resp = proxy.send_message("spam", ctx)
            assert "truncated" in resp.message.content
            # Make sure we don't dump 5000 characters
            assert resp.message.content.count("x") < 1000
        finally:
            proxy.end_session(ctx)

    def test_end_session_removes_workspace(self, subprocess_proxy):
        ctx = subprocess_proxy.start_session("noop")
        ws = ctx["workspace"]
        assert os.path.isdir(ws)
        subprocess_proxy.end_session(ctx)
        assert not os.path.isdir(ws)


class TestDockerCodingAgentProxy:
    def test_init_warns_when_docker_missing(self, caplog):
        with patch("potato.agent_proxy.coding_proxy.shutil.which", return_value=None):
            with caplog.at_level("WARNING", logger="potato.agent_proxy.coding_proxy"):
                DockerCodingAgentProxy({"llm": {}, "execution": {}, "docker": {}})
            assert any("docker" in r.message.lower() for r in caplog.records)

    def test_execute_invokes_docker_run_with_safe_flags(self, tmp_path):
        proxy = DockerCodingAgentProxy({
            "llm": {"endpoint_type": "ollama"},
            "execution": {"per_step_timeout": 5},
            "docker": {
                "image": "python:3.11-slim",
                "memory": "256m",
                "cpus": "0.5",
                "network": "none",
            },
        })
        ws = str(tmp_path)
        ctx = {"workspace": ws}
        completed = MagicMock()
        completed.stdout = "4\n"
        completed.stderr = ""
        completed.returncode = 0
        with patch("potato.agent_proxy.coding_proxy.subprocess.run", return_value=completed) as run:
            result = proxy._execute("python", "print(2+2)", ctx)
            cmd = run.call_args.args[0]
            # Safe-by-default flags must be present
            assert "--rm" in cmd
            assert "--network=none" in cmd
            assert "--memory=256m" in cmd
            assert "--cpus=0.5" in cmd
            assert "--read-only" in cmd
            assert any(c.startswith(f"{ws}:") for c in cmd)  # workspace mount
            assert "python:3.11-slim" in cmd
            assert result.exit_code == 0
            assert "4" in result.stdout

    def test_execute_handles_docker_missing(self, tmp_path):
        proxy = DockerCodingAgentProxy({
            "llm": {"endpoint_type": "ollama"},
            "execution": {"per_step_timeout": 5},
            "docker": {"image": "python:3.11-slim"},
        })
        ws = str(tmp_path)
        with patch(
            "potato.agent_proxy.coding_proxy.subprocess.run",
            side_effect=FileNotFoundError("docker not on PATH"),
        ):
            result = proxy._execute("python", "print(1)", {"workspace": ws})
            assert result.error and "docker" in result.error
            assert result.exit_code is None

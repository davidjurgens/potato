"""Regressions for the audit-20 findings."""

import re
import signal
import threading

import pytest


# --------------------------------------------------------------- finding 1 --
# atexit runs on a normal exit and on SIGINT, but not on SIGTERM -- which is
# what systemctl stop, docker stop, supervisord and plain kill all send.

class TestSigtermReleasesSandboxes:
    @staticmethod
    def _manager():
        import atexit
        from potato.coding_agent_runner_manager import CodingAgentRunnerManager

        manager = CodingAgentRunnerManager.__new__(CodingAgentRunnerManager)
        manager._sessions = {}
        manager._session_keys = {}
        manager._max_sessions = 10
        manager._session_ttl = 3600
        manager._cleanup_thread = threading.Thread(target=lambda: None, daemon=True)
        return manager

    def test_a_sigterm_handler_is_installed(self):
        manager = self._manager()
        previous = signal.getsignal(signal.SIGTERM)
        try:
            manager._install_termination_handler()
            installed = signal.getsignal(signal.SIGTERM)
            assert installed is not previous
            assert callable(installed)
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_the_handler_releases_and_exits(self):
        from potato.coding_agent_runner import CodingAgentConfig, CodingAgentRunner

        class Sandbox:
            def __init__(self):
                self.cleaned = 0

            def cleanup(self):
                self.cleaned += 1

        manager = self._manager()
        runner = CodingAgentRunner("p", CodingAgentConfig(), "")
        runner._sandbox = sandbox = Sandbox()
        manager._sessions["p"] = runner

        previous = signal.getsignal(signal.SIGTERM)
        try:
            manager._install_termination_handler()
            handler = signal.getsignal(signal.SIGTERM)
            with pytest.raises(SystemExit):
                handler(signal.SIGTERM, None)
            assert sandbox.cleaned == 1
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_a_pre_existing_handler_still_runs(self):
        """A process manager may own SIGTERM; this must not displace it."""
        manager = self._manager()
        seen = []

        def prior(signum, frame):
            seen.append(signum)

        previous = signal.getsignal(signal.SIGTERM)
        try:
            signal.signal(signal.SIGTERM, prior)
            manager._install_termination_handler()
            handler = signal.getsignal(signal.SIGTERM)
            with pytest.raises(SystemExit):
                handler(signal.SIGTERM, None)
            assert seen == [signal.SIGTERM]
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_a_release_failure_does_not_stop_the_exit(self):
        from potato.coding_agent_runner import CodingAgentConfig, CodingAgentRunner

        class Angry:
            def cleanup(self):
                raise RuntimeError("docker is unwell")

        manager = self._manager()
        runner = CodingAgentRunner("p", CodingAgentConfig(), "")
        runner._sandbox = Angry()
        manager._sessions["p"] = runner

        previous = signal.getsignal(signal.SIGTERM)
        try:
            manager._install_termination_handler()
            with pytest.raises(SystemExit):
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        finally:
            signal.signal(signal.SIGTERM, previous)


# --------------------------------------------------------------- finding 2 --
# agent_proxy read its endpoint settings flat only, while every other
# model-backed block nests them under ai_config.

class TestAgentProxyEndpointSettings:
    @staticmethod
    def _create(block):
        from potato.agent_proxy.base import AgentProxyFactory
        return AgentProxyFactory.create({"agent_proxy": block})

    def test_a_keyless_base_url_written_flat_works(self):
        assert self._create({"type": "openai", "base_url": "http://x:8001",
                             "model": "m"}).model == "m"

    def test_a_keyless_base_url_under_ai_config_works(self):
        """The shape ai_support, live_agent and judge_calibration all use."""
        assert self._create({"type": "openai",
                             "ai_config": {"base_url": "http://x:8001",
                                           "model": "m"}}).model == "m"

    def test_a_null_api_key_does_not_raise_attributeerror(self):
        """`api_key:` with nothing after it is a str method call on None."""
        self._create({"type": "openai", "api_key": None,
                      "base_url": "http://x:8001"})

    def test_the_flat_form_wins_over_the_nested_one(self):
        proxy = self._create({"type": "openai", "model": "flat",
                              "base_url": "http://x:8001",
                              "ai_config": {"model": "nested"}})
        assert proxy.model == "flat"

    def test_neither_key_nor_base_url_is_still_refused(self):
        from potato.agent_proxy.base import AgentProxyFactory
        import os

        previous = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with pytest.raises(ValueError) as excinfo:
                AgentProxyFactory.create(
                    {"agent_proxy": {"type": "openai", "model": "m"}})
        finally:
            if previous is not None:
                os.environ["OPENAI_API_KEY"] = previous
        message = str(excinfo.value)
        assert "base_url" in message, "the refusal must name the other way out"
        assert "ai_config" in message, "and where the setting may be written"


class TestAgentProxyErrorSurface:
    def test_a_config_error_is_not_reported_as_internal(self):
        import io
        source = io.open("potato/routes.py", encoding="utf-8").read()
        handler = source.split("Agent chat send error")[1][:600]
        assert "not configured correctly" in handler, (
            "a misconfigured proxy told the annotator 'An internal error "
            "occurred' and put the real message in the log")


# --------------------------------------------------------------- finding 3 --
# The task box seeded from the bound field whatever it held.

class TestTaskBoxSeedsOnlyFromATaskField:
    @staticmethod
    def _box(field_config, data):
        from potato.server_utils.displays.live_coding_agent_display import (
            LiveCodingAgentDisplay)
        html = LiveCodingAgentDisplay().render(field_config, data)
        match = re.search(r'class="lca-task-input"[^>]*>([^<]*)</textarea>', html)
        return match.group(1) if match else None

    def test_a_bound_field_that_is_not_a_task_does_not_seed(self):
        """`{key: repo}` put "calc" in a box asking for a task description."""
        assert self._box({"key": "repo", "type": "live_coding_agent"},
                         "calc") == ""

    @pytest.mark.parametrize("key", [
        "task", "task_description", "instruction", "instructions", "prompt"])
    def test_a_field_named_like_a_task_seeds(self, key):
        assert self._box({"key": key, "type": "live_coding_agent"},
                         "Fix the failing test") == "Fix the failing test"

    def test_task_field_names_the_key_explicitly(self):
        assert self._box(
            {"key": "repo", "type": "live_coding_agent", "task_field": "repo"},
            "Fix it") == "Fix it"

    def test_an_object_always_seeds_from_its_named_key(self):
        assert self._box({"key": "repo", "type": "live_coding_agent"},
                         {"task_description": "Refactor"}) == "Refactor"

    def test_task_field_picks_a_key_out_of_an_object(self):
        assert self._box(
            {"key": "repo", "type": "live_coding_agent", "task_field": "todo"},
            {"todo": "Ship it"}) == "Ship it"

    def test_task_field_is_a_declared_option(self):
        from potato.server_utils.displays.live_coding_agent_display import (
            LiveCodingAgentDisplay)
        assert "task_field" in LiveCodingAgentDisplay.optional_fields

    def test_the_seeded_task_is_escaped(self):
        assert "<script>" not in (
            self._box({"key": "task", "type": "live_coding_agent"},
                      "<script>alert(1)</script>") or "")

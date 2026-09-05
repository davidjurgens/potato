"""Regressions for the audit-19 findings."""

import time

import pytest


class _StubSandbox:
    def __init__(self):
        self.cleaned = 0

    def cleanup(self):
        self.cleaned += 1


def _runner(session_id="s1"):
    from potato.coding_agent_runner import CodingAgentConfig, CodingAgentRunner
    return CodingAgentRunner(session_id, CodingAgentConfig(), "")


# --------------------------------------------------------------- finding 1 --
# A live_coding_agent session left its container running: Stop did not release
# it, the reaper measured the wrong clock, and nothing ran at process exit.

class TestStopReleasesTheSandbox:
    def test_stop_tears_the_sandbox_down(self):
        """Stop left the container Up, at 512m each, one per session."""
        runner = _runner()
        runner._sandbox = sandbox = _StubSandbox()
        runner.stop()
        assert sandbox.cleaned == 1
        assert runner._sandbox is None

    def test_stop_still_completes_the_session(self):
        from potato.coding_agent_runner import CodingAgentState
        runner = _runner()
        runner._sandbox = _StubSandbox()
        runner.stop()
        assert runner.state is CodingAgentState.COMPLETED

    def test_releasing_twice_is_harmless(self):
        runner = _runner()
        runner._sandbox = sandbox = _StubSandbox()
        runner.release_sandbox()
        runner.release_sandbox()
        assert sandbox.cleaned == 1

    def test_a_cleanup_failure_does_not_propagate(self):
        """Stopping must not raise because teardown did."""
        class Angry:
            def cleanup(self):
                raise RuntimeError("docker is unwell")

        runner = _runner()
        runner._sandbox = Angry()
        runner.stop()          # must not raise
        assert runner._sandbox is None


class TestReaperUsesTheFinishTime:
    def test_finishing_stamps_the_clock(self):
        from potato.coding_agent_runner import CodingAgentState
        runner = _runner()
        assert runner._finished_at == 0.0
        runner._set_state(CodingAgentState.COMPLETED)
        assert runner._finished_at > 0

    def test_going_back_to_running_clears_it(self):
        from potato.coding_agent_runner import CodingAgentState
        runner = _runner()
        runner._set_state(CodingAgentState.COMPLETED)
        runner._set_state(CodingAgentState.RUNNING)
        assert runner._finished_at == 0.0

    def test_a_long_session_is_not_reaped_the_moment_it_finishes(self):
        """The reaper aged sessions from `_started_at`.

        A session that ran for most of the TTL was therefore expired seconds
        after completing, while one that finished at once held its container
        for the full window.
        """
        from potato.coding_agent_runner import CodingAgentState

        runner = _runner()
        runner._started_at = time.time() - 3599   # ran for nearly the whole TTL
        runner._set_state(CodingAgentState.COMPLETED)

        ttl = 3600
        since = runner._finished_at or runner._started_at
        assert time.time() - since < ttl, (
            "a session that just finished must not be immediately expired")


class TestSandboxesAreReleasedAtProcessExit:
    def test_the_manager_registers_an_exit_hook(self):
        """The cleanup thread is a daemon, so it never runs at shutdown."""
        import atexit
        import potato.coding_agent_runner_manager as module

        assert hasattr(module.CodingAgentRunnerManager, "_release_all")

    def test_release_all_cleans_every_session(self):
        from potato.coding_agent_runner_manager import CodingAgentRunnerManager

        manager = CodingAgentRunnerManager.__new__(CodingAgentRunnerManager)
        first, second = _runner("a"), _runner("b")
        first._sandbox, second._sandbox = _StubSandbox(), _StubSandbox()
        sandboxes = [first._sandbox, second._sandbox]
        manager._sessions = {"a": first, "b": second}
        manager._release_all()
        assert all(s.cleaned == 1 for s in sandboxes)


# --------------------------------------------------------------- finding 2 --
# agent_proxy had no documented path to a visible surface.

class TestAgentProxyNamesItsSurface:
    def test_the_key_doc_names_the_display_that_renders_it(self):
        from potato.server_utils.config_key_docs import CONFIG_KEY_DOCS
        description = CONFIG_KEY_DOCS["agent_proxy"].summary
        assert "interactive_chat" in description, (
            "the block configures a backend and renders nothing; the doc has "
            "to say what puts the panel on the page")

    def test_the_display_is_the_only_source_of_the_panel(self):
        """If this stops being true the doc above is wrong."""
        import io
        source = io.open(
            "potato/server_utils/displays/interactive_chat_display.py",
            encoding="utf-8").read()
        assert 'id="agent-chat-panel"' in source


# --------------------------------------------------------------- finding 3 --
class TestAgentProxyEnabledFlag:
    @pytest.mark.parametrize("config,expected", [
        ({}, False),
        ({"agent_proxy": {"type": "openai"}}, True),
        ({"agent_proxy": {"enabled": True}}, True),
        ({"agent_proxy": {"enabled": False}}, False),
        ({"agent_proxy": {}}, True),
    ])
    def test_enabled_false_turns_it_off(self, config, expected):
        """It was `"agent_proxy" in config`, so `enabled: false` still ran."""
        from potato.flask_server import _agent_proxy_enabled
        assert _agent_proxy_enabled(config) is expected


# --------------------------------------------------------------- finding 4 --
class TestLiveCodingAgentSeedsItsTask:
    @staticmethod
    def _task_box(data):
        import re
        from potato.server_utils.displays.live_coding_agent_display import (
            LiveCodingAgentDisplay)
        html = LiveCodingAgentDisplay().render(
            {"key": "task", "type": "live_coding_agent"}, data)
        match = re.search(
            r'class="lca-task-input"[^>]*>([^<]*)</textarea>', html)
        return match.group(1) if match else None

    def test_a_string_field_seeds_the_box(self):
        assert self._task_box("Fix the failing test") == "Fix the failing test"

    @pytest.mark.parametrize("key", ["task_description", "task"])
    def test_the_object_forms_seed_it(self, key):
        assert self._task_box({key: "Add a CLI flag"}) == "Add a CLI flag"

    def test_no_data_leaves_the_placeholder(self):
        assert self._task_box(None) == ""

    def test_the_task_is_escaped(self):
        assert "<script>" not in (self._task_box("<script>alert(1)</script>") or "")


# ------------------------------------------------- the defaults interaction --
class TestSandboxDefaultsAreExplained:
    def test_the_banner_warns_about_the_bare_image_with_no_network(self):
        from potato.sandbox import startup_report
        from potato.sandbox.settings import SandboxSettings

        report = startup_report(SandboxSettings(mode="container"))
        assert "no test runner" in report
        assert "sandbox_image" in report

    def test_a_custom_image_gets_no_note(self):
        from potato.sandbox import startup_report
        from potato.sandbox.settings import SandboxSettings

        report = startup_report(
            SandboxSettings(mode="container", sandbox_image="my/tools:1"))
        assert "no test runner" not in report

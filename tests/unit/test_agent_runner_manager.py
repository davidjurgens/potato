"""
Unit tests for AgentRunnerManager.

Tests cover:
- Singleton pattern (get_instance, clear_instance)
- create_session success, duplicate active session error, max sessions error
- get_session by session_id
- get_session_by_key by user_id/instance_id
- remove_session
- list_sessions
- TTL-based cleanup

AgentRunner internals are mocked so tests run without Playwright or LLM deps.
"""

import threading
import time
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_runner(session_id="abc123", state_value="idle"):
    """Return a MagicMock that quacks like an AgentRunner."""
    from potato.agent_runner import AgentState

    runner = MagicMock()
    runner.session_id = session_id
    runner.state = AgentState(state_value)
    runner.step_count = 0
    return runner


def _make_config():
    """Return a minimal AgentConfig instance."""
    from potato.agent_runner import AgentConfig
    return AgentConfig()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_singleton():
    """Ensure a fresh singleton for every test."""
    from potato.agent_runner_manager import AgentRunnerManager
    AgentRunnerManager.clear_instance()
    yield
    AgentRunnerManager.clear_instance()


@pytest.fixture
def manager():
    """Return a fresh AgentRunnerManager with a short TTL for cleanup tests."""
    from potato.agent_runner_manager import AgentRunnerManager
    return AgentRunnerManager.get_instance(max_sessions=3, session_ttl=60)


# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------

class TestSingletonPattern:
    def test_get_instance_returns_same_object(self):
        from potato.agent_runner_manager import AgentRunnerManager

        inst1 = AgentRunnerManager.get_instance()
        inst2 = AgentRunnerManager.get_instance()
        assert inst1 is inst2

    def test_clear_instance_allows_new_instance(self):
        from potato.agent_runner_manager import AgentRunnerManager

        inst1 = AgentRunnerManager.get_instance()
        AgentRunnerManager.clear_instance()
        inst2 = AgentRunnerManager.get_instance()
        assert inst1 is not inst2

    def test_get_instance_passes_kwargs_on_first_call(self):
        from potato.agent_runner_manager import AgentRunnerManager

        inst = AgentRunnerManager.get_instance(max_sessions=7, session_ttl=999)
        assert inst.max_sessions == 7
        assert inst.session_ttl == 999

    def test_get_instance_ignores_kwargs_on_subsequent_calls(self):
        """Once initialised, kwargs are silently ignored."""
        from potato.agent_runner_manager import AgentRunnerManager

        inst1 = AgentRunnerManager.get_instance(max_sessions=5)
        inst2 = AgentRunnerManager.get_instance(max_sessions=99)
        # Still the same instance, max_sessions unchanged
        assert inst1 is inst2
        assert inst1.max_sessions == 5

    def test_clear_instance_stops_cleanup_thread(self):
        from potato.agent_runner_manager import AgentRunnerManager

        inst = AgentRunnerManager.get_instance()
        thread = inst._cleanup_thread
        assert thread.is_alive()

        AgentRunnerManager.clear_instance()
        # Give the thread a moment to notice the stop event
        thread.join(timeout=2)
        assert not thread.is_alive()

    def test_thread_safety_of_get_instance(self):
        """Multiple threads calling get_instance concurrently get the same object."""
        from potato.agent_runner_manager import AgentRunnerManager

        instances = []
        errors = []

        def grab():
            try:
                instances.append(AgentRunnerManager.get_instance())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=grab) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(instances) == 20
        assert all(i is instances[0] for i in instances)


# ---------------------------------------------------------------------------
# create_session tests
# ---------------------------------------------------------------------------

class TestCreateSession:
    @patch("potato.agent_runner_manager.AgentRunner")
    def test_create_session_success(self, MockRunner, manager):
        mock_runner = _make_mock_runner("sess-001")
        MockRunner.return_value = mock_runner

        config = _make_config()
        runner = manager.create_session("user1", "inst1", config, "/tmp/shots")

        assert runner is mock_runner
        MockRunner.assert_called_once()
        # Confirm session is stored
        assert manager.get_session_by_key("user1", "inst1") is mock_runner

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_create_session_stores_metadata(self, MockRunner, manager):
        from potato.agent_runner import AgentState

        mock_runner = _make_mock_runner("sess-meta")
        MockRunner.return_value = mock_runner

        manager.create_session("userA", "instA", _make_config(), "/screenshots")

        sessions = manager.list_sessions()
        assert len(sessions) == 1
        entry = sessions[0]
        assert entry["user_id"] == "userA"
        assert entry["instance_id"] == "instA"
        assert entry["session_id"] == "sess-meta"
        assert "created" in entry

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_create_session_duplicate_active_raises(self, MockRunner, manager):
        """Creating a second session while the first is RUNNING raises RuntimeError."""
        from potato.agent_runner import AgentState

        mock_runner = _make_mock_runner("sess-dup", state_value="running")
        MockRunner.return_value = mock_runner

        manager.create_session("user1", "inst1", _make_config(), "/tmp")

        with pytest.raises(RuntimeError, match="Active session already exists"):
            manager.create_session("user1", "inst1", _make_config(), "/tmp")

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_create_session_duplicate_paused_raises(self, MockRunner, manager):
        from potato.agent_runner import AgentState

        mock_runner = _make_mock_runner("sess-paused", state_value="paused")
        MockRunner.return_value = mock_runner

        manager.create_session("user1", "inst1", _make_config(), "/tmp")

        with pytest.raises(RuntimeError, match="Active session already exists"):
            manager.create_session("user1", "inst1", _make_config(), "/tmp")

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_create_session_duplicate_takeover_raises(self, MockRunner, manager):
        from potato.agent_runner import AgentState

        mock_runner = _make_mock_runner("sess-takeover", state_value="takeover")
        MockRunner.return_value = mock_runner

        manager.create_session("user1", "inst1", _make_config(), "/tmp")

        with pytest.raises(RuntimeError, match="Active session already exists"):
            manager.create_session("user1", "inst1", _make_config(), "/tmp")

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_create_session_replaces_completed_session(self, MockRunner, manager):
        """A completed session for the same key is silently replaced."""
        from potato.agent_runner import AgentState

        # First session: completed
        done_runner = _make_mock_runner("sess-done", state_value="completed")
        MockRunner.return_value = done_runner
        manager.create_session("user1", "inst1", _make_config(), "/tmp")

        # Second session: new
        new_runner = _make_mock_runner("sess-new", state_value="idle")
        MockRunner.return_value = new_runner
        result = manager.create_session("user1", "inst1", _make_config(), "/tmp")

        assert result is new_runner
        assert manager.get_session_by_key("user1", "inst1") is new_runner

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_create_session_replaces_error_session(self, MockRunner, manager):
        from potato.agent_runner import AgentState

        err_runner = _make_mock_runner("sess-err", state_value="error")
        MockRunner.return_value = err_runner
        manager.create_session("user2", "inst2", _make_config(), "/tmp")

        fresh_runner = _make_mock_runner("sess-fresh", state_value="idle")
        MockRunner.return_value = fresh_runner
        result = manager.create_session("user2", "inst2", _make_config(), "/tmp")

        assert result is fresh_runner

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_create_session_max_sessions_error(self, MockRunner, manager):
        """RuntimeError when active sessions reach max_sessions limit."""
        from potato.agent_runner import AgentState

        # manager fixture has max_sessions=3; fill it up with RUNNING sessions
        for i in range(3):
            r = _make_mock_runner(f"sess-{i}", state_value="running")
            MockRunner.return_value = r
            manager.create_session(f"user{i}", f"inst{i}", _make_config(), "/tmp")

        # 4th session should fail
        extra = _make_mock_runner("sess-extra", state_value="idle")
        MockRunner.return_value = extra
        with pytest.raises(RuntimeError, match="Maximum concurrent sessions"):
            manager.create_session("user99", "inst99", _make_config(), "/tmp")

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_create_session_counts_only_active_states(self, MockRunner, manager):
        """Completed/error sessions do not count toward the active-session cap."""
        from potato.agent_runner import AgentState

        # Fill 2 running + 1 completed — only 2 are active
        for i in range(2):
            r = _make_mock_runner(f"sess-run-{i}", state_value="running")
            MockRunner.return_value = r
            manager.create_session(f"userR{i}", f"instR{i}", _make_config(), "/tmp")

        done = _make_mock_runner("sess-done", state_value="completed")
        MockRunner.return_value = done
        manager.create_session("userD", "instD", _make_config(), "/tmp")

        # One more active session is still allowed (cap is 3, only 2 active)
        extra = _make_mock_runner("sess-extra", state_value="idle")
        MockRunner.return_value = extra
        result = manager.create_session("userE", "instE", _make_config(), "/tmp")
        assert result is extra


# ---------------------------------------------------------------------------
# get_session tests
# ---------------------------------------------------------------------------

class TestGetSession:
    @patch("potato.agent_runner_manager.AgentRunner")
    def test_get_session_by_id_found(self, MockRunner, manager):
        mock_runner = _make_mock_runner("find-me")
        MockRunner.return_value = mock_runner
        manager.create_session("u1", "i1", _make_config(), "/tmp")

        result = manager.get_session("find-me")
        assert result is mock_runner

    def test_get_session_by_id_not_found(self, manager):
        result = manager.get_session("does-not-exist")
        assert result is None

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_get_session_by_key_found(self, MockRunner, manager):
        mock_runner = _make_mock_runner("key-sess")
        MockRunner.return_value = mock_runner
        manager.create_session("userX", "instX", _make_config(), "/tmp")

        result = manager.get_session_by_key("userX", "instX")
        assert result is mock_runner

    def test_get_session_by_key_not_found(self, manager):
        result = manager.get_session_by_key("nobody", "nothing")
        assert result is None

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_get_session_returns_correct_session_among_many(self, MockRunner, manager):
        runners = {}
        for i in range(3):
            r = _make_mock_runner(f"sid-{i}")
            runners[f"sid-{i}"] = r
            MockRunner.return_value = r
            manager.create_session(f"user{i}", f"inst{i}", _make_config(), "/tmp")

        for sid, expected in runners.items():
            assert manager.get_session(sid) is expected


# ---------------------------------------------------------------------------
# remove_session tests
# ---------------------------------------------------------------------------

class TestRemoveSession:
    @patch("potato.agent_runner_manager.AgentRunner")
    def test_remove_session_stops_runner(self, MockRunner, manager):
        mock_runner = _make_mock_runner("to-remove")
        MockRunner.return_value = mock_runner
        manager.create_session("u1", "i1", _make_config(), "/tmp")

        manager.remove_session("to-remove")

        mock_runner.stop.assert_called_once()
        assert manager.get_session("to-remove") is None
        assert manager.get_session_by_key("u1", "i1") is None

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_remove_session_clears_metadata(self, MockRunner, manager):
        mock_runner = _make_mock_runner("meta-remove")
        MockRunner.return_value = mock_runner
        manager.create_session("uMeta", "iMeta", _make_config(), "/tmp")

        manager.remove_session("meta-remove")

        sessions = manager.list_sessions()
        assert not any(s["session_id"] == "meta-remove" for s in sessions)

    def test_remove_session_nonexistent_is_noop(self, manager):
        # Should not raise
        manager.remove_session("ghost-session")

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_remove_session_leaves_others_intact(self, MockRunner, manager):
        keep = _make_mock_runner("keep-me")
        MockRunner.return_value = keep
        manager.create_session("uk", "ik", _make_config(), "/tmp")

        gone = _make_mock_runner("gone")
        MockRunner.return_value = gone
        manager.create_session("ug", "ig", _make_config(), "/tmp")

        manager.remove_session("gone")

        assert manager.get_session("keep-me") is keep
        assert manager.get_session("gone") is None


# ---------------------------------------------------------------------------
# list_sessions tests
# ---------------------------------------------------------------------------

class TestListSessions:
    def test_list_sessions_empty(self, manager):
        assert manager.list_sessions() == []

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_list_sessions_returns_all(self, MockRunner, manager):
        from potato.agent_runner import AgentState

        for i in range(3):
            r = _make_mock_runner(f"ls-{i}", state_value="idle")
            MockRunner.return_value = r
            manager.create_session(f"user{i}", f"inst{i}", _make_config(), "/tmp")

        sessions = manager.list_sessions()
        assert len(sessions) == 3

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_list_sessions_entry_structure(self, MockRunner, manager):
        from potato.agent_runner import AgentState

        mock_runner = _make_mock_runner("struct-sess", state_value="running")
        mock_runner.step_count = 5
        MockRunner.return_value = mock_runner

        manager.create_session("uStruct", "iStruct", _make_config(), "/tmp")

        sessions = manager.list_sessions()
        assert len(sessions) == 1
        entry = sessions[0]
        assert entry["session_id"] == "struct-sess"
        assert entry["user_id"] == "uStruct"
        assert entry["instance_id"] == "iStruct"
        assert entry["state"] == "running"
        assert entry["step_count"] == 5
        assert isinstance(entry["created"], float)

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_list_sessions_after_remove(self, MockRunner, manager):
        for i in range(2):
            r = _make_mock_runner(f"lr-{i}")
            MockRunner.return_value = r
            manager.create_session(f"user{i}", f"inst{i}", _make_config(), "/tmp")

        manager.remove_session("lr-0")
        sessions = manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "lr-1"


# ---------------------------------------------------------------------------
# TTL-based cleanup tests
# ---------------------------------------------------------------------------

class TestTTLCleanup:
    @patch("potato.agent_runner_manager.AgentRunner")
    def test_cleanup_removes_expired_idle_sessions(self, MockRunner):
        """Sessions past TTL in IDLE/COMPLETED/ERROR state are cleaned up."""
        from potato.agent_runner import AgentState, AgentConfig
        from potato.agent_runner_manager import AgentRunnerManager

        mgr = AgentRunnerManager(max_sessions=10, session_ttl=10)
        try:
            expired = _make_mock_runner("expired-idle", state_value="completed")
            MockRunner.return_value = expired
            mgr.create_session("uExp", "iExp", _make_config(), "/tmp")

            # Backdate the creation time to simulate TTL expiry
            key = "uExp:iExp"
            mgr._session_created[key] = time.time() - 20  # 20s > 10s TTL

            # Trigger cleanup (lock is not held here, use the public path)
            with mgr._lock:
                mgr._cleanup_expired_locked()

            assert mgr.get_session("expired-idle") is None
        finally:
            mgr.shutdown()

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_cleanup_keeps_running_sessions_within_ttl(self, MockRunner):
        """Running sessions within TTL are not removed."""
        from potato.agent_runner import AgentState
        from potato.agent_runner_manager import AgentRunnerManager

        mgr = AgentRunnerManager(max_sessions=10, session_ttl=3600)
        try:
            running = _make_mock_runner("still-running", state_value="running")
            MockRunner.return_value = running
            mgr.create_session("uRun", "iRun", _make_config(), "/tmp")

            with mgr._lock:
                mgr._cleanup_expired_locked()

            assert mgr.get_session("still-running") is running
        finally:
            mgr.shutdown()

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_cleanup_force_stops_very_old_running_sessions(self, MockRunner):
        """Sessions RUNNING past 2x TTL are force-stopped and removed."""
        from potato.agent_runner import AgentState
        from potato.agent_runner_manager import AgentRunnerManager

        mgr = AgentRunnerManager(max_sessions=10, session_ttl=10)
        try:
            zombie = _make_mock_runner("zombie-run", state_value="running")
            MockRunner.return_value = zombie
            mgr.create_session("uZom", "iZom", _make_config(), "/tmp")

            key = "uZom:iZom"
            mgr._session_created[key] = time.time() - 25  # > 2 * 10 = 20s

            with mgr._lock:
                mgr._cleanup_expired_locked()

            zombie.stop.assert_called_once()
            assert mgr.get_session("zombie-run") is None
        finally:
            mgr.shutdown()

    @patch("potato.agent_runner_manager.AgentRunner")
    def test_cleanup_expired_is_called_on_create_session(self, MockRunner):
        """create_session triggers _cleanup_expired_locked before adding the new session."""
        from potato.agent_runner_manager import AgentRunnerManager

        mgr = AgentRunnerManager(max_sessions=10, session_ttl=10)
        try:
            # Pre-fill with an expired completed session
            expired = _make_mock_runner("old-sess", state_value="completed")
            MockRunner.return_value = expired
            mgr.create_session("uOld", "iOld", _make_config(), "/tmp")
            mgr._session_created["uOld:iOld"] = time.time() - 20

            # Now create a new session — should trigger cleanup
            fresh = _make_mock_runner("new-sess", state_value="idle")
            MockRunner.return_value = fresh
            mgr.create_session("uNew", "iNew", _make_config(), "/tmp")

            assert mgr.get_session("old-sess") is None
            assert mgr.get_session("new-sess") is fresh
        finally:
            mgr.shutdown()


# ---------------------------------------------------------------------------
# shutdown tests
# ---------------------------------------------------------------------------

class TestShutdown:
    @patch("potato.agent_runner_manager.AgentRunner")
    def test_shutdown_stops_all_runners(self, MockRunner):
        from potato.agent_runner_manager import AgentRunnerManager

        mgr = AgentRunnerManager(max_sessions=10, session_ttl=3600)
        runners = []
        for i in range(3):
            r = _make_mock_runner(f"shut-{i}")
            MockRunner.return_value = r
            mgr.create_session(f"uS{i}", f"iS{i}", _make_config(), "/tmp")
            runners.append(r)

        mgr.shutdown()

        for r in runners:
            r.stop.assert_called_once()
        assert mgr.list_sessions() == []

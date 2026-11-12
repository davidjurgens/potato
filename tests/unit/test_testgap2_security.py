"""
Refused cases for the helpers and blueprints behind access control: origin
matching, user directories, live-agent session ownership, the MCP export
folder and Clerk sign-in.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from tests.helpers.test_utils import create_test_directory


# ---------------------------------------------------------------------------
# Same-origin check
# ---------------------------------------------------------------------------

class TestOriginCheck:
    def _check(self, **headers):
        from potato.server_utils.origin_check import is_same_origin
        app = Flask(__name__)
        with app.test_request_context("/x", method="POST", base_url="http://localhost:8000",
                                      headers=headers):
            from flask import request
            return is_same_origin(request)

    def test_the_same_origin_passes(self):
        assert self._check(Origin="http://localhost:8000")
        assert self._check(Referer="http://localhost:8000/annotate?x=1")

    @pytest.mark.parametrize("origin", [
        "http://localhost:8000.evil.example",   # passed the old prefix test
        "http://localhost:80001",
        "https://localhost:8000",
        "http://evil.example",
        "null",
    ])
    def test_another_origin_is_refused(self, origin):
        assert not self._check(Origin=origin)

    def test_a_referer_on_another_site_is_refused(self):
        assert not self._check(Referer="http://localhost:8000.evil.example/page")

    def test_no_headers_is_allowed(self):
        assert self._check()


def test_no_module_keeps_a_prefix_origin_check():
    """The nine copies were replaced by origin_check; a new copy should not appear."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "potato"
    offenders = [str(p) for p in root.rglob("*.py")
                 if "origin.startswith(host" in p.read_text(errors="ignore")
                 or "host not in origin" in p.read_text(errors="ignore")]
    assert offenders == []


# ---------------------------------------------------------------------------
# User directories
# ---------------------------------------------------------------------------

class TestUserDir:
    @pytest.mark.parametrize("name", ["zz/../alice", "../x", "/etc", "a\\b", ".hidden",
                                      "..", "a\x00b", ""])
    def test_a_name_that_is_not_one_plain_component_is_refused(self, name):
        from potato.server_utils.usernames import user_dir
        with pytest.raises(ValueError):
            user_dir(create_test_directory("tg2_userdir"), name)

    @pytest.mark.parametrize("name", ["alice", "alice@example.com", "José", "5f3a9c01e2"])
    def test_ordinary_names_map_to_one_directory(self, name):
        from potato.server_utils.usernames import user_dir
        root = create_test_directory("tg2_userdir_ok")
        assert user_dir(root, name) == os.path.join(root, name)

    def test_case_and_normalisation_variants_collide(self):
        from potato.server_utils.usernames import colliding_username
        assert colliding_username("Alice", ["alice"]) == "alice"
        assert colliding_username("José", ["José"]) == "José"
        assert colliding_username("alice", ["alice"]) is None


# ---------------------------------------------------------------------------
# Live agent sessions
# ---------------------------------------------------------------------------

@pytest.fixture
def live_agent_app():
    from potato.agent_runner import AgentConfig
    from potato.agent_runner_manager import AgentRunnerManager
    from potato.routes_live_agent import live_agent_bp
    AgentRunnerManager.clear_instance()
    app = Flask(__name__)
    app.secret_key = "x"
    app.add_url_rule("/login", "login", lambda: "login")
    app.register_blueprint(live_agent_bp)
    runner = AgentRunnerManager.get_instance().create_session(
        "alice", "item1", AgentConfig.from_config({}), create_test_directory("tg2_live"))
    rbac = MagicMock()
    rbac.check.return_value = False
    with patch("potato.server_utils.rbac.get_rbac_manager", return_value=rbac):
        yield app, runner
    AgentRunnerManager.clear_instance()


def _as(app, user):
    client = app.test_client()
    with client.session_transaction() as s:
        s["username"] = user
    return client


class TestLiveAgentOwnership:
    def test_another_annotator_cannot_see_or_drive_the_session(self, live_agent_app):
        app, runner = live_agent_app
        bob = _as(app, "bob")
        assert bob.get("/api/live_agent/sessions").get_json()["sessions"] == []
        for action in ("pause", "instruct", "stop"):
            r = bob.post(f"/api/live_agent/{action}/{runner.session_id}",
                         json={"instruction": "go elsewhere"})
            assert r.status_code == 404, action
        assert bob.get(f"/api/live_agent/state/{runner.session_id}").status_code == 404

    def test_the_owner_still_can(self, live_agent_app):
        app, runner = live_agent_app
        alice = _as(app, "alice")
        assert [s["session_id"] for s in alice.get("/api/live_agent/sessions").get_json()["sessions"]] \
            == [runner.session_id]
        assert alice.get(f"/api/live_agent/state/{runner.session_id}").status_code == 200

    def test_a_request_cannot_supply_the_agent_config(self, live_agent_app):
        """ai_config.base_url from the request would send the server's API key elsewhere."""
        app, _ = live_agent_app
        seen = {}
        from potato.agent_runner import AgentConfig
        real = AgentConfig.from_config

        def spy(cfg):
            seen.update(cfg)
            return real(cfg)
        with patch("potato.routes_live_agent.AgentConfig.from_config", side_effect=spy), \
                patch("potato.agent_runner.AgentRunner.start"):
            _as(app, "bob").post("/api/live_agent/start", json={
                "task_description": "t", "start_url": "http://x", "instance_id": "i",
                "config": {"ai_config": {"base_url": "http://evil.example"}}})
        assert "ai_config" not in seen

    def test_the_instance_id_cannot_steer_the_screenshot_folder(self, live_agent_app):
        from potato.routes_live_agent import _path_part
        assert "/" not in _path_part("../../etc") and not _path_part("../x").startswith(".")


class TestCodingAgentOwnership:
    def test_another_annotator_cannot_reach_the_session(self):
        from potato.coding_agent_runner_manager import CodingAgentRunnerManager
        from potato.routes_live_coding_agent import live_coding_agent_bp
        app = Flask(__name__)
        app.secret_key = "x"
        app.register_blueprint(live_coding_agent_bp)
        manager = MagicMock()
        runner = MagicMock()
        runner.get_state_summary.return_value = {"state": "running"}
        manager.get_session.side_effect = lambda sid: runner if sid == "s1" else None
        manager.get_session_owner.side_effect = lambda sid: "alice" if sid == "s1" else None
        manager.list_sessions.return_value = [{"session_id": "s1", "user_id": "alice"}]
        rbac = MagicMock()
        rbac.check.return_value = False
        with patch.object(CodingAgentRunnerManager, "get_instance", return_value=manager), \
                patch("potato.server_utils.rbac.get_rbac_manager", return_value=rbac):
            bob = _as(app, "bob")
            assert bob.get("/api/live_coding_agent/state/s1").status_code == 404
            assert bob.post("/api/live_coding_agent/stop/s1").status_code == 404
            assert bob.get("/api/live_coding_agent/sessions").get_json()["sessions"] == []
            assert _as(app, "alice").get("/api/live_coding_agent/state/s1").status_code == 200

    def test_the_manager_records_who_started_a_session(self):
        from potato.coding_agent_runner_manager import CodingAgentRunnerManager
        manager = CodingAgentRunnerManager.__new__(CodingAgentRunnerManager)
        manager._sessions, manager._session_keys, manager._owners = {}, {}, {}
        manager._max_sessions = 10
        with patch("potato.coding_agent_runner_manager.CodingAgentRunner"):
            manager.create_session("alice", "i1", MagicMock())
        (session_id,) = manager._sessions
        assert manager.get_session_owner(session_id) == "alice"


# ---------------------------------------------------------------------------
# MCP export folder
# ---------------------------------------------------------------------------

class TestMcpExportFolder:
    @pytest.fixture
    def client(self):
        from tests.helpers.test_utils import TestConfigManager
        from potato.mcp_server.routes import register_mcp_routes
        from potato.server_utils.agent_tokens import issue_token
        from potato.server_utils.rbac import init_rbac_manager
        schemes = [{"name": "s", "annotation_type": "radio", "description": "d", "labels": ["a", "b"]}]
        with TestConfigManager("tg2_mcp_export", schemes, num_instances=2) as tc:
            cfg = {"mcp": {"enabled": True, "tools": ["export_data"]}, "task_dir": tc.task_dir,
                   "__config_file__": tc.config_path,
                   "output_annotation_dir": os.path.join(tc.task_dir, "output")}
            init_rbac_manager(cfg)
            token = issue_token("exporter", role="adjudicator", config=cfg)
            app = Flask(__name__)
            app.config["mcp_task_config"] = cfg
            assert register_mcp_routes(app, cfg)
            yield app.test_client(), token, tc.task_dir

    def test_an_output_outside_the_exports_folder_is_refused(self, client):
        c, token, task_dir = client
        target = os.path.join(os.path.dirname(task_dir), "tg2_mcp_escape_target")
        import shutil
        shutil.rmtree(target, ignore_errors=True)
        for output in (target, "../../escape"):
            r = c.post("/api/mcp/tools/export_data", headers={"Authorization": "Bearer " + token},
                       json={"format": "csv", "output": output})
            assert r.status_code == 400, output
        assert not os.path.exists(target)


# ---------------------------------------------------------------------------
# Clerk and login timing
# ---------------------------------------------------------------------------

class TestClerkSessionBelongsToTheUsername:
    def _backend(self, body):
        from potato.authentication import ClerkAuthBackend
        backend = ClerkAuthBackend("key", "front")
        reply = MagicMock(status_code=200)
        reply.json.return_value = body
        return backend, patch("potato.authentication.requests.get", return_value=reply)

    def test_a_session_for_another_user_is_refused(self):
        backend, mocked = self._backend({"status": "active", "user_id": "user_mallory"})
        with mocked:
            assert not backend.authenticate("user_alice", "tok")

    def test_an_ended_session_is_refused(self):
        backend, mocked = self._backend({"status": "ended", "user_id": "user_alice"})
        with mocked:
            assert not backend.authenticate("user_alice", "tok")

    def test_the_owner_of_an_active_session_is_accepted(self):
        backend, mocked = self._backend({"status": "active", "user_id": "user_alice"})
        with mocked:
            assert backend.authenticate("user_alice", "tok")


def test_an_unknown_username_costs_a_password_hash():
    """Answering before hashing told an attacker which usernames exist."""
    import potato.authentication as auth
    backend = auth.InMemoryAuthBackend()
    with patch.object(auth, "_verify_password", wraps=auth._verify_password) as verify:
        assert not backend.authenticate("nobody", "guess")
    assert verify.called


def test_importing_authentication_hashes_nothing():
    """The unknown-user dummy hash is made on first use, not at import.

    Made at import, it cost every process 100k PBKDF2 iterations and broke
    the import under Pyodide, whose hashlib has no pbkdf2_hmac.
    """
    import subprocess
    import sys
    code = (
        "import hashlib\n"
        "del hashlib.pbkdf2_hmac\n"
        "import potato.authentication as auth\n"
        "assert auth._timing_dummy_hash is None\n"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_dummy_hash_is_made_once_and_verified_against():
    import potato.authentication as auth
    backend = auth.InMemoryAuthBackend()
    assert not backend.authenticate("nobody", "guess")
    first = auth._timing_dummy_hash
    assert first is not None
    assert not backend.authenticate("nobody", "again")
    assert auth._timing_dummy_hash == first

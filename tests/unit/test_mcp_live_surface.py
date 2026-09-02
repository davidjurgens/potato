"""
Tests for the live MCP control surface.

This is the only part of the agent work that can lose someone's data, so the
tests are mostly about refusals: what happens when the token is missing, wrong,
revoked, under-privileged, or asking for something the admin never granted.

Three properties matter more than the rest, and each has a test that fails loudly
if it regresses:

  * Debug mode does not unlock anything. `validate_admin_api_key()` returns True
    unconditionally under `debug: true` and `RBACManager.check()` passes
    everything but ADJUDICATE, so any accidental reuse of either would hand a
    debug server's full control to anyone who can reach the port.
  * A destructive tool needs two separate opt-ins plus `confirm: true`.
  * Every attempt, allowed or refused, lands in the audit log.
"""

import json

import pytest
from flask import Flask

from potato.mcp_server.live_tools import (
    DESTRUCTIVE_TOOL_NAMES,
    TOOL_NAMES,
    TOOLS,
    describe_tools,
)
from potato.mcp_server.routes import mcp_bp, register_mcp_routes
from potato.server_utils.agent_tokens import (
    issue_token,
    list_tokens,
    revoke_token,
    verify_token,
)
from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_mcp_config,
)


def _base_config(tmp_path, **mcp):
    return {
        "annotation_task_name": "Test",
        "task_dir": str(tmp_path),
        "output_annotation_dir": str(tmp_path / "out"),
        "item_properties": {"id_key": "id", "text_key": "text"},
        "mcp": {"enabled": True, **mcp},
    }


@pytest.fixture
def app(tmp_path):
    """A Flask app with the MCP surface mounted and a token issued."""
    config = _base_config(
        tmp_path,
        tools=["get_status", "list_items", "delete_annotations"],
        destructive=["delete_annotations"],
        audit_log=str(tmp_path / "audit.jsonl"),
    )
    flask_app = Flask(__name__)
    flask_app.config["mcp_task_config"] = config
    flask_app.register_blueprint(mcp_bp)

    token = issue_token("test-agent", role="admin", config=config)
    return flask_app, config, token


def _post(client, tool, token=None, payload=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        f"/api/mcp/tools/{tool}", headers=headers, json=payload or {}
    )


class TestToolRegistry:
    def test_registry_is_not_empty(self):
        assert TOOL_NAMES and DESTRUCTIVE_TOOL_NAMES

    def test_every_tool_declares_a_real_permission(self):
        from potato.server_utils.rbac import Permission

        for tool in TOOLS.values():
            assert tool.permission in Permission.ALL, (
                f"{tool.name} declares {tool.permission!r}, which is not an "
                f"RBAC permission"
            )

    def test_destructive_names_are_a_subset(self):
        assert set(DESTRUCTIVE_TOOL_NAMES) <= set(TOOL_NAMES)

    def test_every_tool_has_a_route(self):
        """A tool nobody can call is a lie in the manifest."""
        flask_app = Flask(__name__)
        flask_app.register_blueprint(mcp_bp)
        routes = {str(rule) for rule in flask_app.url_map.iter_rules()}
        for name in TOOL_NAMES:
            assert f"/api/mcp/tools/{name}" in routes, (
                f"{name} is in the registry but has no route"
            )

    def test_describe_tools_narrows_to_the_grant(self):
        described = describe_tools(["get_status"])
        assert [t["name"] for t in described] == ["get_status"]


class TestConfigValidation:
    def test_absent_block_is_fine(self):
        validate_mcp_config({})

    def test_disabled_block_is_not_checked(self):
        validate_mcp_config({"mcp": {"enabled": False, "tools": ["nonsense"]}})

    def test_unknown_tool_raises(self):
        """An allowlist typo must fail at boot, not warn.

        Everything else in config_module only warns on an unrecognized key. For
        a security allowlist that would mean an admin believes they granted
        something they did not.
        """
        with pytest.raises(ConfigValidationError) as excinfo:
            validate_mcp_config({"mcp": {"enabled": True, "tools": ["get_statuss"]}})
        assert "get_statuss" in str(excinfo.value)
        assert "get_status" in str(excinfo.value), "should list the valid names"

    def test_destructive_must_also_be_granted(self):
        with pytest.raises(ConfigValidationError) as excinfo:
            validate_mcp_config({"mcp": {
                "enabled": True,
                "tools": ["get_status"],
                "destructive": ["delete_annotations"],
            }})
        assert "must appear in both" in str(excinfo.value)

    def test_destructive_must_name_a_destructive_tool(self):
        with pytest.raises(ConfigValidationError) as excinfo:
            validate_mcp_config({"mcp": {
                "enabled": True,
                "tools": ["get_status"],
                "destructive": ["get_status"],
            }})
        assert "not destructive" in str(excinfo.value)

    def test_debug_plus_mcp_raises(self):
        with pytest.raises(ConfigValidationError) as excinfo:
            validate_mcp_config({
                "debug": True,
                "mcp": {"enabled": True, "tools": ["get_status"]},
            })
        assert "debug" in str(excinfo.value)

    def test_debug_is_allowed_when_stated_explicitly(self):
        validate_mcp_config({
            "debug": True,
            "mcp": {"enabled": True, "tools": ["get_status"], "allow_debug": True},
        })

    def test_wrong_types_raise(self):
        for block in ({"tools": "get_status"}, {"scope": []}, {"auth": "x"}):
            with pytest.raises(ConfigValidationError):
                validate_mcp_config({"mcp": {"enabled": True, **block}})


class TestRegistration:
    def test_disabled_means_no_routes(self, tmp_path):
        flask_app = Flask(__name__)
        config = _base_config(tmp_path)
        config["mcp"]["enabled"] = False
        assert register_mcp_routes(flask_app, config) is False
        assert not [
            r for r in flask_app.url_map.iter_rules() if "/api/mcp" in str(r)
        ]

    def test_debug_refuses_registration(self, tmp_path):
        """Second line of defence, in case validation was bypassed."""
        flask_app = Flask(__name__)
        config = _base_config(tmp_path, tools=["get_status"])
        config["debug"] = True
        assert register_mcp_routes(flask_app, config) is False

    def test_debug_with_allow_debug_registers(self, tmp_path):
        flask_app = Flask(__name__)
        config = _base_config(tmp_path, tools=["get_status"], allow_debug=True)
        config["debug"] = True
        assert register_mcp_routes(flask_app, config) is True

    def test_enabled_registers(self, tmp_path):
        flask_app = Flask(__name__)
        assert register_mcp_routes(
            flask_app, _base_config(tmp_path, tools=["get_status"])
        ) is True


class TestTokens:
    def test_issue_then_verify(self, tmp_path):
        config = _base_config(tmp_path)
        token = issue_token("agent-a", role="admin", config=config)
        record = verify_token(token, config)
        assert record and record.name == "agent-a" and record.role == "admin"

    def test_token_is_not_stored_in_plaintext(self, tmp_path):
        config = _base_config(tmp_path)
        token = issue_token("agent-a", config=config)
        with open(tmp_path / "mcp_tokens.json", encoding="utf-8") as f:
            assert token not in f.read()

    def test_wrong_token_is_refused(self, tmp_path):
        config = _base_config(tmp_path)
        issue_token("agent-a", config=config)
        assert verify_token("not-the-token", config) is None
        assert verify_token("", config) is None
        assert verify_token(None, config) is None

    def test_revocation(self, tmp_path):
        config = _base_config(tmp_path)
        token = issue_token("agent-a", config=config)
        assert revoke_token("agent-a", config) == 1
        assert verify_token(token, config) is None

    def test_invalid_role_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            issue_token("agent-a", role="superuser", config=_base_config(tmp_path))

    def test_unnamed_token_is_refused(self, tmp_path):
        """A token you cannot name is a token you cannot revoke."""
        with pytest.raises(ValueError):
            issue_token("  ", config=_base_config(tmp_path))

    def test_listing_never_leaks_a_token(self, tmp_path):
        config = _base_config(tmp_path)
        token = issue_token("agent-a", config=config)
        assert all(token not in json.dumps(r) for r in list_tokens(config))

    def test_admin_key_header_is_not_accepted(self, tmp_path):
        """X-API-Key carries the shared superuser key; it must not work here."""
        from potato.server_utils.agent_tokens import extract_bearer

        assert extract_bearer({"X-API-Key": "some-admin-key"}) is None
        assert extract_bearer({"Authorization": "Bearer abc"}) == "abc"
        assert extract_bearer({"X-Agent-Token": "abc"}) == "abc"


class TestTheGate:
    def test_no_token_is_401(self, app):
        flask_app, _, _ = app
        response = _post(flask_app.test_client(), "get_status")
        assert response.status_code == 401

    def test_bad_token_is_401(self, app):
        flask_app, _, _ = app
        response = _post(flask_app.test_client(), "get_status", token="nope")
        assert response.status_code == 401

    def test_revoked_token_is_401(self, app):
        flask_app, config, token = app
        revoke_token("test-agent", config)
        assert _post(flask_app.test_client(), "get_status", token=token).status_code == 401

    def test_ungranted_tool_is_403_and_says_what_is_granted(self, app):
        flask_app, _, token = app
        response = _post(flask_app.test_client(), "get_agreement", token=token)
        assert response.status_code == 403
        body = response.get_json()
        assert "not in mcp.tools" in body["error"]
        assert "get_status" in body["granted_tools"]

    def test_unknown_tool_is_404(self, app):
        flask_app, _, token = app
        response = _post(flask_app.test_client(), "no_such_tool", token=token)
        assert response.status_code in (404, 405)

    def test_destructive_without_confirm_is_refused(self, app):
        flask_app, _, token = app
        response = _post(
            flask_app.test_client(), "delete_annotations", token=token,
            payload={"username": "u", "instance_id": "1"},
        )
        assert response.status_code == 400
        assert "confirm" in response.get_json()["error"]

    def test_destructive_not_opted_in_is_refused(self, tmp_path):
        """Granted in mcp.tools but absent from mcp.destructive."""
        config = _base_config(
            tmp_path, tools=["delete_annotations"],
            audit_log=str(tmp_path / "audit.jsonl"),
        )
        flask_app = Flask(__name__)
        flask_app.config["mcp_task_config"] = config
        flask_app.register_blueprint(mcp_bp)
        token = issue_token("agent", role="admin", config=config)

        response = _post(
            flask_app.test_client(), "delete_annotations", token=token,
            payload={"username": "u", "instance_id": "1", "confirm": True},
        )
        assert response.status_code == 403
        assert "mcp.destructive" in response.get_json()["error"]

    def test_role_without_the_permission_is_refused(self, tmp_path):
        config = _base_config(
            tmp_path, tools=["list_items"], audit_log=str(tmp_path / "audit.jsonl")
        )
        flask_app = Flask(__name__)
        flask_app.config["mcp_task_config"] = config
        flask_app.register_blueprint(mcp_bp)
        token = issue_token("weak", role="annotator", config=config)

        response = _post(flask_app.test_client(), "list_items", token=token)
        assert response.status_code == 403
        assert "does not carry" in response.get_json()["error"]

    def test_scope_restricts_the_target_user(self, tmp_path):
        config = _base_config(
            tmp_path, tools=["delete_annotations"],
            destructive=["delete_annotations"],
            scope={"users": ["alice"]},
            audit_log=str(tmp_path / "audit.jsonl"),
        )
        flask_app = Flask(__name__)
        flask_app.config["mcp_task_config"] = config
        flask_app.register_blueprint(mcp_bp)
        token = issue_token("agent", role="admin", config=config)

        response = _post(
            flask_app.test_client(), "delete_annotations", token=token,
            payload={"username": "bob", "instance_id": "1", "confirm": True},
        )
        assert response.status_code == 403
        assert "scope" in response.get_json()["error"]


class TestDebugDoesNotUnlockAnything:
    """The property this whole design turns on.

    `validate_admin_api_key()` returns True unconditionally under debug and
    `RBACManager.check()` passes everything but ADJUDICATE. If the MCP gate ever
    consults either, a debug server becomes remote control with no lock.
    """

    def test_debug_server_still_refuses_a_missing_token(self, tmp_path):
        config = _base_config(
            tmp_path, tools=["get_status"], allow_debug=True,
            audit_log=str(tmp_path / "audit.jsonl"),
        )
        config["debug"] = True
        flask_app = Flask(__name__)
        flask_app.config["mcp_task_config"] = config
        assert register_mcp_routes(flask_app, config) is True

        assert _post(flask_app.test_client(), "get_status").status_code == 401

    def test_debug_server_still_refuses_a_bad_token(self, tmp_path):
        config = _base_config(
            tmp_path, tools=["get_status"], allow_debug=True,
            audit_log=str(tmp_path / "audit.jsonl"),
        )
        config["debug"] = True
        flask_app = Flask(__name__)
        flask_app.config["mcp_task_config"] = config
        register_mcp_routes(flask_app, config)

        response = _post(flask_app.test_client(), "get_status", token="bogus")
        assert response.status_code == 401

    def test_verify_token_never_reads_debug(self, tmp_path):
        config = _base_config(tmp_path)
        config["debug"] = True
        assert verify_token("anything-at-all", config) is None


class TestAuditLog:
    def _entries(self, path):
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_refusals_are_recorded(self, app, tmp_path):
        flask_app, config, _ = app
        _post(flask_app.test_client(), "get_status")

        entries = self._entries(config["mcp"]["audit_log"])
        assert any(e["event"] == "auth_failed" for e in entries), (
            "a refused call left no trace"
        )

    def test_ungranted_calls_name_the_agent(self, app, tmp_path):
        flask_app, config, token = app
        _post(flask_app.test_client(), "get_agreement", token=token)

        entries = self._entries(config["mcp"]["audit_log"])
        denied = [e for e in entries if e["event"] == "not_granted"]
        assert denied and denied[-1]["agent"] == "test-agent"

    def test_entries_are_one_json_object_per_line(self, app):
        flask_app, config, token = app
        _post(flask_app.test_client(), "get_status", token=token)

        with open(config["mcp"]["audit_log"], encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    assert isinstance(json.loads(line), dict)


class TestManifest:
    def test_requires_a_token(self, app):
        flask_app, _, _ = app
        assert flask_app.test_client().get("/api/mcp/manifest").status_code == 401

    def test_reports_only_the_granted_tools(self, app):
        flask_app, _, token = app
        response = flask_app.test_client().get(
            "/api/mcp/manifest", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        body = response.get_json()
        assert {t["name"] for t in body["tools"]} == {
            "get_status", "list_items", "delete_annotations"
        }
        assert body["destructive_enabled"] == ["delete_annotations"]
        assert body["agent"] == "test-agent"


class TestGetConfigRedaction:
    def test_secrets_are_not_returned(self, tmp_path):
        config = _base_config(
            tmp_path, tools=["get_config"], audit_log=str(tmp_path / "audit.jsonl")
        )
        config["secret_key"] = "super-secret"
        config["admin_api_key"] = "admin-secret"
        flask_app = Flask(__name__)
        flask_app.config["mcp_task_config"] = config
        flask_app.register_blueprint(mcp_bp)
        token = issue_token("agent", role="admin", config=config)

        response = _post(flask_app.test_client(), "get_config", token=token)
        assert response.status_code == 200
        body = json.dumps(response.get_json())
        assert "super-secret" not in body
        assert "admin-secret" not in body


class TestRemoteBridge:
    """`potato mcp connect` fronts a remote instance's surface over stdio.

    The bridge holds no policy: the tool list comes from the remote manifest and
    every refusal is the remote server's. These tests pin that, because a bridge
    that guessed at permissions locally would either hide tools an agent has or
    advertise ones it does not.
    """

    def _client(self, monkeypatch, responses):
        """A PotatoClient whose HTTP layer returns canned responses."""
        import io as _io
        import urllib.request

        from potato.mcp_server.connect import PotatoClient

        def fake_urlopen(request, timeout=None):
            path = request.full_url.split("://", 1)[1].split("/", 1)[1]
            body = json.dumps(responses["/" + path]).encode()

            class Response:
                def read(self_inner):
                    return body

                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    return False

            return Response()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        return PotatoClient("http://example.test", "tok")

    def test_manifest_and_call_send_the_bearer_token(self, monkeypatch):
        import urllib.request

        from potato.mcp_server.connect import PotatoClient

        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["auth"] = request.headers.get("Authorization")
            seen["method"] = request.method

            class Response:
                def read(self_inner):
                    return b"{}"

                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    return False

            return Response()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        PotatoClient("http://example.test", "sekrit").call("get_status", {})
        assert seen["auth"] == "Bearer sekrit"
        assert seen["method"] == "POST"

    def test_refusal_body_is_passed_through(self, monkeypatch):
        """A 403 body says which check failed; a status code alone does not."""
        import urllib.error
        import urllib.request

        from potato.mcp_server.connect import PotatoClient

        body = json.dumps({"error": "'x' is not in mcp.tools"}).encode()

        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, 403, "Forbidden", {}, __import__("io").BytesIO(body)
            )

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        result = PotatoClient("http://example.test", "tok").call("x", {})
        assert "not in mcp.tools" in result["error"]

    def test_unreachable_host_raises_remote_error(self, monkeypatch):
        import urllib.error
        import urllib.request

        from potato.mcp_server.connect import PotatoClient, RemoteError

        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RemoteError):
            PotatoClient("http://example.test", "tok").manifest()

    def test_summary_names_every_granted_tool(self):
        from potato.mcp_server.connect import summarize

        text = summarize({
            "task": "T", "agent": "a", "role": "admin",
            "tools": [
                {"name": "get_status", "summary": "s", "destructive": False},
                {"name": "delete_annotations", "summary": "d", "destructive": True},
            ],
            "destructive_enabled": ["delete_annotations"],
            "scope": {"users": ["alice"]},
        })
        assert "live_get_status" in text
        assert "[destructive]" in text
        assert "alice" in text

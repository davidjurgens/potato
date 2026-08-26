"""
Tests for the live coding agent sandbox ladder.

Covers the three things that made the previous implementation unsafe: a
configured sandbox that silently became no sandbox, tool paths that escaped the
workspace by construction, and modes whose names implied isolation they never
provided.
"""

import os
import shutil
import subprocess
import tempfile

import pytest

from potato.sandbox import (
    ACK_KEY,
    SandboxError,
    SandboxSettings,
    create_backend,
    preflight,
    resolve_within,
    startup_report,
)
from potato.coding_agent_backend import execute_tool


def _trusted_settings(**overrides):
    config = {"sandbox_mode": "trusted", ACK_KEY: True}
    config.update(overrides)
    return SandboxSettings.from_config(config)


@pytest.fixture
def workspace():
    path = tempfile.mkdtemp()
    with open(os.path.join(path, "main.py"), "w") as f:
        f.write("hello world\n")
    os.makedirs(os.path.join(path, "sub"), exist_ok=True)
    with open(os.path.join(path, "sub", "x.txt"), "w") as f:
        f.write("deep\n")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def sandbox(workspace):
    backend = create_backend(workspace, _trusted_settings())
    backend.create("test-session-01")
    yield backend
    backend.cleanup()


class TestSettingsLadder:
    """Mode parsing, defaults and the deprecation mapping."""

    def test_default_mode_is_container(self):
        settings = SandboxSettings.from_config({})
        assert settings.mode == "container"
        assert settings.container_cli == "docker"

    def test_container_defaults_to_no_network(self):
        assert SandboxSettings.from_config({}).sandbox_network == "none"

    def test_trusted_requires_acknowledgement(self):
        with pytest.raises(SandboxError) as exc:
            SandboxSettings.from_config({"sandbox_mode": "trusted"})
        # The error has to be actionable: it is the only thing an operator
        # upgrading from `direct` will see.
        assert ACK_KEY in str(exc.value)
        assert "container" in str(exc.value)

    def test_trusted_with_acknowledgement_is_allowed(self):
        settings = _trusted_settings()
        assert settings.mode == "trusted"
        assert settings.is_isolated_mode() is False

    @pytest.mark.parametrize("alias,expected,worktree", [
        ("docker", "container", False),
        ("direct", "trusted", False),
        ("worktree", "trusted", True),
    ])
    def test_deprecated_aliases_map_onto_the_ladder(self, alias, expected, worktree):
        settings = SandboxSettings.from_config(
            {"sandbox_mode": alias, ACK_KEY: True}
        )
        assert settings.mode == expected
        assert settings.use_worktree is worktree

    def test_worktree_alias_still_requires_acknowledgement(self):
        # `worktree` reads like isolation and is not. Upgrading must be a
        # deliberate act rather than a silent carry-over.
        with pytest.raises(SandboxError):
            SandboxSettings.from_config({"sandbox_mode": "worktree"})

    def test_invalid_mode_is_rejected(self):
        with pytest.raises(SandboxError):
            SandboxSettings.from_config({"sandbox_mode": "chroot"})

    def test_invalid_container_cli_is_rejected(self):
        with pytest.raises(SandboxError):
            SandboxSettings.from_config({"container_cli": "lxc"})

    def test_container_runtime_passes_through(self):
        # gVisor and Kata are drop-in runtimes, so upgrading the boundary is a
        # config key rather than new code.
        settings = SandboxSettings.from_config({"container_runtime": "runsc"})
        assert settings.container_runtime == "runsc"
        assert "runsc" in settings.describe()

    def test_startup_report_shouts_about_trusted_mode(self):
        report = startup_report(_trusted_settings())
        assert "NO ISOLATION" in report
        assert "NO ISOLATION" not in startup_report(
            SandboxSettings.from_config({})
        )


class TestNoSilentFallback:
    """A configured sandbox must never quietly become a weaker one."""

    def test_unavailable_container_cli_raises_rather_than_degrading(self, workspace):
        settings = SandboxSettings.from_config({
            "sandbox_mode": "container",
            "container_cli": "podman",
        })
        backend = create_backend(workspace, settings)

        # Simulate podman being absent regardless of the test machine.
        import potato.sandbox.container as container_mod
        original = container_mod.unavailable_reason
        container_mod.unavailable_reason = lambda cli: "podman is not installed"
        try:
            with pytest.raises(SandboxError) as exc:
                backend.create("no-fallback")
        finally:
            container_mod.unavailable_reason = original

        assert "podman" in str(exc.value)
        # The old code logged a warning and ran the tools on the host instead.
        assert backend.workspace != os.path.realpath("/")

    def test_preflight_explains_the_alternatives(self):
        import potato.sandbox.container as container_mod
        original = container_mod.unavailable_reason
        container_mod.unavailable_reason = lambda cli: "docker is not installed"
        try:
            reason = preflight(SandboxSettings.from_config({}))
        finally:
            container_mod.unavailable_reason = original

        assert reason is not None
        for hint in ("podman", "bubblewrap", ACK_KEY):
            assert hint in reason


class TestPathContainment:
    """`resolve_within` is the only guard under the trusted rung."""

    def test_relative_path_resolves(self, workspace):
        assert resolve_within(workspace, "main.py") == os.path.join(
            os.path.realpath(workspace), "main.py")

    def test_absolute_path_is_rejected(self, workspace):
        # The old executor honoured absolute paths by construction:
        # `join(wd, p) if not isabs(p) else p`.
        with pytest.raises(SandboxError):
            resolve_within(workspace, "/etc/passwd")

    def test_dotdot_escape_is_rejected(self, workspace):
        with pytest.raises(SandboxError):
            resolve_within(workspace, "../../../etc/passwd")

    def test_symlink_escape_is_rejected(self, workspace):
        os.symlink("/etc/passwd", os.path.join(workspace, "link"))
        with pytest.raises(SandboxError):
            resolve_within(workspace, "link")

    def test_nested_path_inside_workspace_is_allowed(self, workspace):
        resolve_within(workspace, "sub/x.txt")

    def test_workspace_root_itself_is_allowed(self, workspace):
        assert resolve_within(workspace, ".") == os.path.realpath(workspace)

    def test_prefix_sibling_is_not_treated_as_inside(self, workspace):
        # `/tmp/ws-evil` must not pass a naive startswith check against `/tmp/ws`.
        sibling = workspace + "-evil"
        os.makedirs(sibling, exist_ok=True)
        try:
            with pytest.raises(SandboxError):
                resolve_within(workspace, os.path.join("..", os.path.basename(sibling)))
        finally:
            shutil.rmtree(sibling, ignore_errors=True)


class TestToolContainment:
    """Every tool, not just Bash, has to respect the boundary."""

    def test_read_rejects_absolute_path(self, sandbox):
        result = execute_tool("Read", {"file_path": "/etc/passwd"}, sandbox)
        assert "Absolute paths are not permitted" in result

    def test_read_rejects_traversal(self, sandbox):
        result = execute_tool(
            "Read", {"file_path": "../../../etc/passwd"}, sandbox)
        assert "outside the sandbox workspace" in result

    def test_write_rejects_absolute_path(self, sandbox):
        result = execute_tool(
            "Write", {"file_path": "/tmp/potato-pwned", "content": "x"}, sandbox)
        assert "Absolute paths are not permitted" in result
        assert not os.path.exists("/tmp/potato-pwned")

    def test_edit_rejects_traversal(self, sandbox):
        result = execute_tool("Edit", {
            "file_path": "../escape.txt",
            "old_string": "a", "new_string": "b",
        }, sandbox)
        assert "outside the sandbox workspace" in result

    def test_grep_rejects_traversal(self, sandbox):
        result = execute_tool(
            "Grep", {"pattern": "root", "path": "../.."}, sandbox)
        assert "outside the sandbox workspace" in result

    def test_glob_does_not_return_paths_outside_workspace(self, sandbox):
        result = execute_tool("Glob", {"pattern": "../../*"}, sandbox)
        assert result == "(no matches)"

    def test_read_follows_no_symlink_out(self, sandbox):
        os.symlink("/etc/passwd", os.path.join(sandbox.workspace, "escape"))
        result = execute_tool("Read", {"file_path": "escape"}, sandbox)
        assert "outside the sandbox workspace" in result
        assert "root:" not in result

    def test_a_bare_path_is_refused(self, workspace):
        # Accepting a path is how a caller used to get no sandbox at all.
        with pytest.raises(TypeError):
            execute_tool("Read", {"file_path": "main.py"}, workspace)

    def test_tools_still_work_inside_the_workspace(self, sandbox):
        assert "hello world" in execute_tool(
            "Read", {"file_path": "main.py"}, sandbox)
        assert "File written" in execute_tool(
            "Write", {"file_path": "new/a.txt", "content": "x"}, sandbox)
        assert "sub/x.txt" in execute_tool(
            "Glob", {"pattern": "**/*.txt"}, sandbox)


class TestClientCannotChooseItsOwnBoundary:
    """Sandbox settings come from server YAML only."""

    def test_settings_ignore_unknown_client_keys(self):
        settings = SandboxSettings.from_config({
            "sandbox_mode": "container",
            # A request body shaped like a config must not be able to smuggle
            # these through even if it reaches from_config.
            "acknowledge_untrusted_code_execution": False,
        })
        assert settings.mode == "container"

    def test_start_route_does_not_apply_client_config(self):
        source = open("potato/routes_live_coding_agent.py", encoding="utf-8").read()
        start = source.index("def start_session()")
        end = source.index("def ", start + 10)
        body = source[start:end]
        for key in ("agent_config.working_dir =", "agent_config.backend_type =",
                    "agent_config.ai_config.update"):
            assert key not in body, (
                "start_session applies client-supplied %s; working_dir selects "
                "what gets mounted into the sandbox" % key
            )


@pytest.mark.skipif(shutil.which("docker") is None,
                    reason="docker not installed")
class TestContainerBackend:
    """The default rung, exercised against a real daemon when there is one."""

    @pytest.fixture
    def container(self, workspace):
        from potato.server_utils.container_utils import container_cli_available
        if not container_cli_available("docker"):
            pytest.skip("docker daemon not reachable")
        settings = SandboxSettings.from_config({"sandbox_mode": "container"})
        try:
            subprocess.run(["docker", "image", "inspect", settings.sandbox_image],
                           capture_output=True, check=True)
        except subprocess.CalledProcessError:
            pytest.skip("sandbox image %s not pulled" % settings.sandbox_image)
        backend = create_backend(workspace, settings)
        backend.create("pytest-ctr-01")
        yield backend
        backend.cleanup()

    def test_runs_as_unprivileged_user(self, container):
        assert "nobody" in execute_tool(
            "Bash", {"command": "whoami"}, container)

    def test_has_no_capabilities(self, container):
        result = execute_tool(
            "Bash", {"command": "grep CapEff /proc/self/status"}, container)
        assert "0000000000000000" in result

    def test_has_no_network(self, container):
        result = execute_tool(
            "Bash", {"command": "getent hosts example.com || echo NO_DNS"},
            container)
        assert "NO_DNS" in result

    def test_root_filesystem_is_read_only(self, container):
        result = execute_tool(
            "Bash", {"command": "touch /pwned && echo WROTE || echo READONLY"},
            container)
        assert "READONLY" in result

    def test_host_files_are_not_visible(self, container, workspace):
        host_marker = os.path.join(workspace, "..", "host-only.txt")
        result = execute_tool(
            "Bash", {"command": "cat %s 2>&1 || true" % host_marker}, container)
        assert "No such file" in result or "can't open" in result

    def test_workspace_is_a_copy_not_the_original(self, container, workspace):
        execute_tool("Write", {"file_path": "sandbox-only.txt",
                               "content": "x"}, container)
        assert not os.path.exists(os.path.join(workspace, "sandbox-only.txt"))

    def test_cleanup_removes_the_container(self, workspace):
        settings = SandboxSettings.from_config({"sandbox_mode": "container"})
        backend = create_backend(workspace, settings)
        backend.create("pytest-ctr-02")
        name = "potato-agent-pytest-ctr-0"
        backend.cleanup()
        listed = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=%s" % name,
             "--format", "{{.Names}}"],
            capture_output=True, text=True,
        ).stdout
        assert "pytest-ctr-02" not in listed

    def test_cleanup_does_not_touch_the_configured_directory(self, workspace):
        settings = SandboxSettings.from_config({"sandbox_mode": "container"})
        backend = create_backend(workspace, settings)
        backend.create("pytest-ctr-03")
        backend.cleanup()
        # A sibling provider once rmtree'd what turned out to be the live task
        # directory; this is the regression guard for that shape of bug.
        assert os.path.exists(os.path.join(workspace, "main.py"))

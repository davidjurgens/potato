"""Guards for the canonical Docker image.

None of these need a Docker daemon. The entrypoint is POSIX sh, so its logic
runs under /bin/sh directly, and the Dockerfile and .dockerignore are read as
text. That matters because the properties worth guarding here are the ones a
green build would not catch: an image that publishes a researcher's annotation
output or admin key, and a multi-worker start that silently drops annotations.

The one thing left uncovered is whether the image actually builds and serves,
which the publish workflow's smoke test does on real hardware.
"""

import os
import re
import stat
import subprocess

import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCKERFILE = os.path.join(REPO_ROOT, "Dockerfile")
ENTRYPOINT = os.path.join(REPO_ROOT, "docker-entrypoint.sh")
DOCKERIGNORE = os.path.join(REPO_ROOT, ".dockerignore")
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "docker-publish.yml")


@pytest.fixture(scope="module")
def dockerfile():
    with open(DOCKERFILE) as handle:
        return handle.read()


@pytest.fixture(scope="module")
def dockerignore_entries():
    entries = []
    with open(DOCKERIGNORE) as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                entries.append(line)
    return entries


# touch lives here; gunicorn lives in the virtualenv. Pinning PATH keeps a test
# that must not start a server from starting one on a machine that has it.
SYSTEM_PATH_ONLY = {"PATH": "/usr/bin:/bin"}


def run_entrypoint(args=(), env=None, cwd=None):
    """Execute the entrypoint under /bin/sh with a controlled environment."""
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    environment.update(env or {})
    return subprocess.run(
        ["/bin/sh", ENTRYPOINT, *args],
        env=environment, cwd=cwd or REPO_ROOT,
        capture_output=True, text=True, timeout=30,
    )


class TestEntrypointWorkerGuard:
    """Two workers means duplicate assignment and silently lost annotations.

    Potato holds the item pool, the assignment queue and per-user state in
    memory per process, and rewrites user_state.json in full on every save. This
    guard is the only thing standing between a deploy and that data loss, so it
    is asserted on the artifact rather than assumed from the source.
    """

    def test_refuses_to_start_with_multiple_workers(self, tmp_path):
        (tmp_path / "config.yaml").write_text("task_dir: .\n")
        result = run_entrypoint(env={"GUNICORN_WORKERS": "4"}, cwd=str(tmp_path))
        assert result.returncode == 1
        assert "per-process" in result.stderr

    def test_the_override_is_documented_in_the_error(self, tmp_path):
        (tmp_path / "config.yaml").write_text("task_dir: .\n")
        result = run_entrypoint(env={"GUNICORN_WORKERS": "2"}, cwd=str(tmp_path))
        assert "POTATO_ALLOW_MULTIWORKER=1" in result.stderr

    def test_explicit_override_gets_past_the_guard(self, tmp_path):
        """Someone who insists should reach the config check, not the guard."""
        result = run_entrypoint(
            env={"GUNICORN_WORKERS": "4", "POTATO_ALLOW_MULTIWORKER": "1"},
            cwd=str(tmp_path))
        assert "per-process" not in result.stderr
        assert "config file not found" in result.stderr

    def test_one_worker_is_the_default(self, dockerfile):
        assert "GUNICORN_WORKERS=1" in dockerfile


class TestEntrypointConfigCheck:
    def test_missing_config_names_the_mount(self, tmp_path):
        result = run_entrypoint(cwd=str(tmp_path))
        assert result.returncode == 1
        assert "config file not found" in result.stderr
        # The overwhelmingly common cause is a wrong -v argument.
        assert "/app" in result.stderr

    def test_missing_config_lists_what_is_there(self, tmp_path):
        (tmp_path / "config.yml").write_text("")     # .yml, not .yaml
        result = run_entrypoint(cwd=str(tmp_path))
        assert "config.yml" in result.stderr

    def test_potato_config_selects_the_file(self, tmp_path):
        (tmp_path / "other.yaml").write_text("task_dir: .\n")
        result = run_entrypoint(env={"POTATO_CONFIG": "missing.yaml"},
                                cwd=str(tmp_path))
        assert "missing.yaml" in result.stderr


@pytest.mark.skipif(os.geteuid() == 0,
                    reason="root writes to read-only directories anyway")
class TestEntrypointWriteProbe:
    """An unwritable /app is the most likely first failure of the whole image.

    Potato writes annotation output, potato.log and its SQLite databases into
    the project directory. A bind mount carries the host's ownership, and the
    container's uid matches it only by coincidence — so this fires on any
    directory created by root (which is every DigitalOcean droplet before the
    fix) and on any host account whose uid is not 1000 (which is every GitHub
    runner). Docker Desktop ignores ownership on bind mounts, so it passes on a
    Mac and fails on Linux.

    Without the probe the symptom is a PermissionError thirty frames into a
    gunicorn worker traceback, printed after the process has given up.
    """

    @pytest.fixture
    def unwritable_project(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "config.yaml").write_text("task_dir: .\n")
        project.chmod(stat.S_IRUSR | stat.S_IXUSR)
        yield str(project)
        project.chmod(stat.S_IRWXU)

    def test_refuses_rather_than_failing_inside_gunicorn(self, unwritable_project):
        result = run_entrypoint(cwd=unwritable_project)
        assert result.returncode == 1
        assert "not writable by uid" in result.stderr

    def test_names_both_ways_out(self, unwritable_project):
        result = run_entrypoint(cwd=unwritable_project)
        assert "chown -R 1000:1000" in result.stderr
        assert "--user" in result.stderr

    def test_says_why_the_directory_has_to_be_writable(self, unwritable_project):
        """Otherwise the reader assumes a read-only project would be fine."""
        assert "annotation output" in run_entrypoint(cwd=unwritable_project).stderr

    def test_the_override_exists_for_a_deliberate_read_only_mount(
            self, unwritable_project):
        """A config writing everything under /data is a legitimate setup."""
        result = run_entrypoint(env={"POTATO_ALLOW_READONLY_APP": "1"},
                                cwd=unwritable_project)
        assert "not writable by uid" not in result.stderr

    def test_a_writable_project_passes_the_probe(self, tmp_path):
        (tmp_path / "config.yaml").write_text("task_dir: .\n")
        result = run_entrypoint(env=SYSTEM_PATH_ONLY, cwd=str(tmp_path))
        assert "not writable by uid" not in result.stderr
        # Reaching the banner means the probe passed and the exec was next.
        assert "Starting Potato" in result.stdout

    def test_the_probe_leaves_nothing_behind(self, tmp_path):
        (tmp_path / "config.yaml").write_text("task_dir: .\n")
        run_entrypoint(env=SYSTEM_PATH_ONLY, cwd=str(tmp_path))
        assert [p.name for p in tmp_path.iterdir()] == ["config.yaml"]

    def test_a_command_override_skips_the_probe(self, unwritable_project):
        """`docker run potato potato validate x.yaml` needs no writable mount."""
        result = run_entrypoint(["echo", "hi"], cwd=unwritable_project)
        assert result.returncode == 0
        assert result.stdout.strip() == "hi"

    def test_the_probe_is_not_a_special_builtin_redirect(self):
        """`: > file` is fatal in dash when the redirect fails.

        POSIX makes a redirection error on a special built-in exit the shell,
        so the message this check exists to print never gets reached. The first
        version of the check had exactly that bug.
        """
        with open(ENTRYPOINT) as handle:
            source = handle.read()
        assert "touch " in source
        assert ": > " not in source


class TestEntrypointCommandOverride:
    def test_arguments_replace_the_server(self, tmp_path):
        result = run_entrypoint(["echo", "hello"], cwd=str(tmp_path))
        assert result.returncode == 0
        assert result.stdout.strip() == "hello"

    def test_override_does_not_require_a_config(self, tmp_path):
        """`docker run potato sh` must work in an empty directory."""
        result = run_entrypoint(["true"], cwd=str(tmp_path))
        assert result.returncode == 0


class TestDockerfile:
    def test_installs_from_setup_py_not_requirements(self, dockerfile):
        """requirements.txt is a development superset: pytest, selenium, docs.

        Installing it would put the whole test toolchain in a published image.
        """
        instructions = "\n".join(line for line in dockerfile.splitlines()
                                 if not line.lstrip().startswith("#"))
        assert "requirements.txt" not in instructions
        assert re.search(r"pip install [\"']?\.", instructions)

    def test_copies_only_what_the_install_needs(self, dockerfile):
        copied = re.findall(r"^COPY (?!--from)(.+)$", dockerfile, re.M)
        sources = []
        for line in copied:
            parts = line.split()
            sources.extend(parts[:-1])
        allowed = {"setup.py", "MANIFEST.in", "README.md", "potato/",
                   "docker-entrypoint.sh"}
        assert set(sources) <= allowed, (
            f"Dockerfile copies {set(sources) - allowed} into the image. Every "
            "added path is published to ghcr.io — check it holds no data or "
            "credentials before allowing it here.")

    def test_runs_as_a_non_root_user(self, dockerfile):
        assert re.search(r"^USER potato", dockerfile, re.M)
        # HuggingFace Spaces requires uid 1000 specifically.
        assert "-u 1000" in dockerfile

    def test_user_switch_precedes_the_entrypoint(self, dockerfile):
        """A USER after ENTRYPOINT would still run the server as root."""
        assert dockerfile.index("USER potato") < dockerfile.index("ENTRYPOINT")

    def test_ships_sqlite3_for_safe_pulls(self, dockerfile):
        """`deploy pull` snapshots WAL databases with `sqlite3 .backup`.

        Without the binary the pull silently falls back to copying the file,
        which yields a corrupt or stale database.
        """
        runtime = dockerfile[dockerfile.index("AS runtime"):]
        assert "sqlite3" in runtime

    def test_healthcheck_uses_the_unauthenticated_probe(self, dockerfile):
        assert "HEALTHCHECK" in dockerfile
        assert "/health" in dockerfile
        assert "/admin/health" not in dockerfile, (
            "/admin/health needs an API key; a HEALTHCHECK cannot supply one")

    def test_extras_are_a_build_arg(self, dockerfile):
        assert "ARG POTATO_EXTRAS" in dockerfile

    def test_is_multi_stage(self, dockerfile):
        """Keeps build-essential out of the published image."""
        assert dockerfile.count("FROM python:3.11-slim") == 2
        assert "COPY --from=builder" in dockerfile


class TestDockerignore:
    @pytest.mark.parametrize("path", [
        "annotation_output",     # real annotator records
        "admin_api_key.txt",     # a live credential
        "*.sqlite",              # the project database
        ".potato",               # deploy secret store
        ".git",
        "internal",              # untracked, not for publication
        "demo",
    ])
    def test_excludes_data_and_secrets(self, path, dockerignore_entries):
        assert path in dockerignore_entries, (
            f"'{path}' is not in .dockerignore; it would enter the build context "
            "and could be published to ghcr.io")

    @pytest.mark.parametrize("path", ["potato/models", "examples", "tests", "docs"])
    def test_excludes_bulk_that_the_image_does_not_need(self, path,
                                                        dockerignore_entries):
        assert path in dockerignore_entries

    def test_keeps_what_the_install_needs(self, dockerignore_entries):
        """An over-broad ignore breaks the build in a way that is hard to read."""
        for needed in ("setup.py", "MANIFEST.in", "README.md", "potato",
                       "docker-entrypoint.sh"):
            assert needed not in dockerignore_entries


class TestPublishWorkflow:
    @pytest.fixture(scope="class")
    def workflow(self):
        with open(WORKFLOW) as handle:
            return yaml.safe_load(handle)

    def test_is_valid_yaml_with_a_build_job(self, workflow):
        assert "build" in workflow["jobs"]

    def test_builds_both_architectures(self, workflow):
        text = open(WORKFLOW).read()
        assert "linux/amd64" in text and "linux/arm64" in text

    def test_pull_requests_do_not_push(self, workflow):
        steps = workflow["jobs"]["build"]["steps"]
        push_step = next(s for s in steps if s.get("name") == "Build and push")
        assert "pull_request" in str(push_step["with"]["push"])

    def test_publishes_a_core_and_an_all_variant(self, workflow):
        variants = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]
        assert {v["extras"] for v in variants} == {"", "all"}

    def test_refusal_checks_do_not_pipe_docker_into_grep(self, workflow):
        """Under `set -o pipefail` that pattern inverts its own result.

        Both refusal checks expect the container to exit non-zero. Piped into
        grep, the pipeline reports the failing `docker run` even when grep
        matched, so a guard that fired correctly reads as one that did not.
        That is exactly how the multi-worker check failed once the ownership
        fix let the smoke test reach it.
        """
        steps = workflow["jobs"]["build"]["steps"]
        script = next(s["run"] for s in steps
                      if "Smoke test" in s.get("name", ""))
        assert "pipefail" in script, "the assumption behind this test changed"
        offenders = [line.strip() for line in script.splitlines()
                     if "docker run" in line and "| grep" in line]
        assert not offenders, (
            f"docker run piped into grep under pipefail: {offenders}. Capture "
            "the output first: out=$(docker run ... 2>&1 || true)")

    def test_both_container_refusals_are_asserted(self, workflow):
        """A published image that cannot diagnose its own misuse is worse than
        one that fails loudly, because the symptom lands on the researcher."""
        steps = workflow["jobs"]["build"]["steps"]
        script = next(s["run"] for s in steps
                      if "Smoke test" in s.get("name", ""))
        assert "per-process" in script
        assert "not writable by uid" in script

    def test_the_smoke_project_is_given_to_the_container_user(self, workflow):
        """The checkout belongs to the runner account, not to uid 1000, so a
        bind mount of it straight from $PWD cannot be written to."""
        steps = workflow["jobs"]["build"]["steps"]
        script = next(s["run"] for s in steps
                      if "Smoke test" in s.get("name", ""))
        assert "chown -R 1000:1000" in script

    def test_smoke_tests_before_anyone_depends_on_the_tag(self, workflow):
        """The push used to run first, so a broken image reached the tag and
        the smoke test only reported it afterwards. Two runs published images
        that could not boot before this was reordered."""
        steps = workflow["jobs"]["build"]["steps"]
        names = [s.get("name", "") for s in steps]
        smoke = next(i for i, n in enumerate(names) if "Smoke test" in n)
        push = next(i for i, n in enumerate(names) if n == "Build and push")
        assert smoke < push, (
            "the image is pushed before it is tested, so `latest` can point at "
            "an image that does not boot")

    def test_the_tested_image_is_the_one_that_gets_pushed(self, workflow):
        """A test build with different build-args would prove nothing."""
        steps = workflow["jobs"]["build"]["steps"]
        test_build = next(s for s in steps if s.get("name") == "Build for testing")
        push = next(s for s in steps if s.get("name") == "Build and push")
        assert test_build["with"]["build-args"] == push["with"]["build-args"]
        assert test_build["with"]["context"] == push["with"]["context"]
        # Same cache scope, so the push reuses the exact layers just tested
        # rather than rebuilding amd64 from scratch.
        assert test_build["with"]["cache-to"] == push["with"]["cache-to"]

    def test_the_test_build_is_loadable_and_not_pushed(self, workflow):
        """buildx cannot load a multi-platform image, and a test build that
        pushed would defeat the point of testing first."""
        steps = workflow["jobs"]["build"]["steps"]
        test_build = next(s for s in steps if s.get("name") == "Build for testing")
        assert test_build["with"]["load"] is True
        assert "push" not in test_build["with"]
        assert test_build["with"]["platforms"] == "linux/amd64"

    def test_pull_requests_are_smoke_tested_too(self, workflow):
        """Nothing is pushed on a PR, so the test can run unconditionally —
        which is the only way a broken Dockerfile fails in review."""
        steps = workflow["jobs"]["build"]["steps"]
        smoke = next(s for s in steps if "Smoke test" in s.get("name", ""))
        assert "if" not in smoke, (
            "the smoke test is skipped on pull requests, so a broken image is "
            "found only after merge")

    def test_the_image_name_matches_what_the_provider_pulls(self):
        from potato.deploy.providers.local import DEFAULT_IMAGE
        assert DEFAULT_IMAGE.startswith("ghcr.io/"), DEFAULT_IMAGE
        # The workflow publishes ghcr.io/<owner>/<repo>; the provider default
        # must name the same image or `deploy up` pulls something that is not
        # there.
        assert DEFAULT_IMAGE.endswith(":latest")


class TestHealthEndpoint:
    """The probe the container, the load balancer and `deploy up` all poll."""

    def test_route_is_registered_unauthenticated(self):
        import potato.routes as routes
        source = open(routes.__file__).read()
        assert 'app.add_url_rule("/health", "health", health' in source, (
            "the /health route must be registered in configure_routes; a "
            "module-level @app.route alone 404s on the live server")

    def test_reports_nothing_beyond_liveness(self):
        """It is reachable without a session, so its body is public."""
        import potato.routes as routes
        source = open(routes.__file__).read()
        start = source.index('def health():')
        body = source[start:source.index('@app.route("/admin/health"', start)]
        for leak in ("annotation_task_name", "config.get", "task_name",
                     "get_annotations", "users"):
            assert leak not in body, f"/health exposes {leak} without auth"

    def test_the_session_guard_lets_it_through(self):
        import potato.flask_server as flask_server
        source = open(flask_server.__file__).read()
        assert "'/health'" in source

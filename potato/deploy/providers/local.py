"""Run a bundle in Docker on this machine.

Exists for two reasons. It gives a researcher a way to check what will actually
be deployed before spending money on a host, and it exercises the whole path —
bundle, harden, env injection, entrypoint, health check, pull — with no account
and no network. That makes it the integration-test target for everything the
cloud providers share.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Iterator, List, Optional

from potato.deploy.providers.base import (
    Action,
    DeployPlan,
    DeploymentStatus,
    DeploySpec,
    Provider,
    ProviderError,
    PullResult,
    register_provider,
)
from potato.deploy.state import DeploymentRecord

DEFAULT_IMAGE = "ghcr.io/davidjurgens/potato:latest"
CONTAINER_PREFIX = "potato-deploy-"


def _docker_available() -> bool:
    """True when docker is installed *and* its daemon is reachable.

    Checking only for the binary reports success on a machine where Docker
    Desktop is installed but not started, which then surfaces as a raw socket
    error instead of a usable message.
    """
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True,
                                text=True, timeout=15)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _run(args: List[str], check: bool = True, timeout: int = 120,
         merge_stderr: bool = False) -> str:
    """Run a docker command and return its stdout.

    ``merge_stderr`` folds the command's stderr into the returned text, which
    ``docker logs`` needs: it replays the container's two streams on its own
    two streams, and a Python traceback or a gunicorn boot failure arrives on
    stderr. Reading stdout alone returns the access log and drops the reason
    the server died.
    """
    try:
        if merge_stderr:
            result = subprocess.run(args, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    timeout=timeout)
        else:
            result = subprocess.run(args, capture_output=True, text=True,
                                    timeout=timeout)
    except FileNotFoundError:
        raise ProviderError("docker is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        raise ProviderError(f"docker command timed out: {' '.join(args[:3])}...")
    if check and result.returncode != 0:
        detail = (result.stderr or "").strip() or (result.stdout or "").strip()
        raise ProviderError(f"docker command failed ({result.returncode}): {detail}")
    return result.stdout


def _image_present(image: str) -> bool:
    """True when the image is already in the local daemon."""
    return bool(_run(["docker", "images", "-q", image],
                     check=False, timeout=30).strip())


def _container_state(container: str) -> dict:
    """`docker inspect`'s State object, or {} when the container is gone."""
    output = _run(["docker", "inspect", "--format", "{{json .State}}", container],
                  check=False, timeout=30)
    try:
        return json.loads(output.strip() or "{}")
    except ValueError:
        return {}


@register_provider
class LocalProvider(Provider):
    """Runs the published image against a bind-mounted bundle."""

    name = "local"
    ephemeral_fs = False
    public = False           # published on 127.0.0.1 only, see create()
    mounts_bundle = True     # /app is the bundle directory, not a copy of it
    supports_logs = True
    supports_pull = True

    def _container(self, name: str) -> str:
        return f"{CONTAINER_PREFIX}{name}"

    # -- plan ----------------------------------------------------------

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        image = spec.image or DEFAULT_IMAGE
        port = int(spec.extra.get("port", 8000))
        container = self._container(spec.name)
        env = self.runtime_env(spec, spec.extra.get("generated"))

        plan = DeployPlan(result_url_pattern=f"http://127.0.0.1:{port}",
                          estimated_cost_usd_month=0.0)
        plan.actions = [
            Action("docker.pull", f"pull {image}", {"image": image}),
            Action("docker.rm", f"remove any existing container {container}",
                   {"container": container}),
            Action("docker.run",
                   f"run {container} on 127.0.0.1:{port} with the bundle "
                   f"mounted at /app",
                   {"container": container, "image": image, "port": port,
                    "mount": bundle.bundle_dir if bundle else None,
                    # Keys only: values include generated secrets.
                    "env_keys": sorted(env)}),
            Action("health.wait",
                   f"poll http://127.0.0.1:{port}/health until the server answers, "
                   f"failing if the container exits first"),
        ]
        if shutil.which("docker") is None:
            plan.warnings.append(
                "docker is not installed; this plan cannot run here")
        elif not _docker_available():
            plan.warnings.append(
                "the docker daemon is not running; start Docker before `up`")
        return plan

    # -- create --------------------------------------------------------

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        if not _docker_available():
            raise ProviderError(
                "docker is required for the local provider. Install Docker Desktop "
                "or run the server directly with `potato start <config>`.")

        image = spec.image or DEFAULT_IMAGE
        port = int(spec.extra.get("port", 8000))
        container = self._container(spec.name)

        record = existing or DeploymentRecord(name=spec.name, provider=self.name)  # noqa: E501
        record.provider_ref = {"container": container, "port": port, "image": image}
        record.status = "creating"
        record.url = f"http://127.0.0.1:{port}"
        record.bundle_sha = bundle.sha256() if bundle else None
        # Persist before starting anything, so a failure still leaves a record
        # naming the container to clean up.
        store.upsert(record)

        _run(["docker", "rm", "-f", container], check=False)

        # `docker run` pulls only when the image is absent, so without this an
        # image pulled weeks ago is reused forever and nothing says so. A pull
        # failure is not fatal: an offline machine with the image already
        # cached should still be able to deploy.
        self.console(f"Pulling {image} ...")
        try:
            _run(["docker", "pull", image], timeout=900)
        except ProviderError as exc:
            if not _image_present(image):
                raise ProviderError(
                    f"could not pull {image} and no local copy exists: {exc}")
            self.console(f"Could not pull {image}; using the local copy. ({exc})")

        env = self.runtime_env(spec, spec.extra.get("generated"))
        # 127.0.0.1 explicitly. `-p 8000:7860` publishes on 0.0.0.0, so the
        # task answers on the laptop's LAN address to anyone on the same wifi —
        # while this provider declares `public = False` and preflight therefore
        # suppresses every public-host warning, including open registration.
        # Verified: before this, a deploy on a university network was reachable
        # at http://<laptop-ip>:8000 and returned 200. To reach it from another
        # device, use `potato share`, which gives it HTTPS and a real hostname.
        args = ["docker", "run", "-d", "--name", container,
                "-p", f"127.0.0.1:{port}:7860",
                "-v", f"{os.path.abspath(bundle.bundle_dir)}:/app",
                "-w", "/app",
                "--label", "potato-deploy=1",
                "--label", f"potato-name={spec.name}"]
        # The bundle directory belongs to whoever ran the CLI. The image runs as
        # uid 1000, which matches that only by coincidence, and on a Linux host
        # where it does not the server dies during boot on its first write.
        # Running as the caller also leaves the annotations owned by them rather
        # than by a uid they would need root to read.
        if hasattr(os, "getuid"):
            args += ["--user", f"{os.getuid()}:{os.getgid()}"]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args.append(image)

        try:
            container_id = _run(args, timeout=300).strip()
        except ProviderError:
            # Keep the record — it names the container to clean up — but do not
            # leave it claiming to be mid-creation forever.
            record.status = "failed"
            store.upsert(record)
            raise
        record.provider_ref["container_id"] = container_id
        store.upsert(record)

        # A container that starts and a server that serves are different
        # events. Every refusal the entrypoint makes — an unwritable mount, a
        # config that will not parse, a multi-worker override — happens after
        # `docker run` has already returned an id and exited 0. Without this
        # wait, `up` prints a URL for a container that is already dead and the
        # diagnosis stays in a log nobody was told to read.
        try:
            self._wait_until_serving(container, port)
        except ProviderError:
            record.status = "failed"
            store.upsert(record)
            raise

        record.status = "running"
        store.upsert(record)

        self.console(f"Started {container} at {record.url}")
        return record

    def _wait_until_serving(self, container: str, port: int,
                            timeout: float = 180.0) -> None:
        """Block until the server answers, or explain why it never will."""
        import urllib.error
        import urllib.request

        deadline = time.time() + timeout
        while time.time() < deadline:
            state = _container_state(container)
            if state and not state.get("Running"):
                raise ProviderError(self._boot_failure(container, state))
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=5)
                return
            except urllib.error.HTTPError:
                return  # answering, even if with a 4xx
            except Exception:
                time.sleep(1)

        raise ProviderError(
            f"{container} did not answer on port {port} within "
            f"{timeout:.0f}s. It is still running, so its logs are intact:\n"
            f"  docker logs {container}")

    @staticmethod
    def _boot_failure(container: str, state: dict) -> str:
        """The exit code and the tail of the log that explains it."""
        code = state.get("ExitCode")
        tail = _run(["docker", "logs", "--tail", "25", container],
                    check=False, timeout=30, merge_stderr=True).strip()
        message = [f"{container} exited with code {code} before serving a request."]
        if state.get("OOMKilled"):
            message.append(
                "It was killed for running out of memory. Give Docker more RAM, "
                "or use a smaller dataset.")
        if tail:
            message.append("Last 25 log lines:")
            message.append(tail)
        message.append(f"The container was left in place: docker logs {container}")
        return "\n".join(message)

    # -- status --------------------------------------------------------

    def status(self, record) -> DeploymentStatus:
        container = record.provider_ref.get("container")
        if not container:
            return DeploymentStatus(state="unknown", detail="no container recorded")

        output = _run(["docker", "inspect", container], check=False)
        if not output.strip():
            return DeploymentStatus(state="absent", url=record.url,
                                    detail="container does not exist")
        try:
            info = json.loads(output)[0]
        except (ValueError, IndexError, KeyError):
            return DeploymentStatus(state="unknown", detail="could not parse docker inspect")

        state = info.get("State", {})
        running = bool(state.get("Running"))
        return DeploymentStatus(
            state="running" if running else state.get("Status", "stopped"),
            url=record.url,
            healthy=running,
            detail=state.get("Error") or "",
            raw=state,
        )

    # -- logs ----------------------------------------------------------

    def logs(self, record, *, lines: int = 200, follow: bool = False) -> Iterator[str]:
        container = record.provider_ref.get("container")
        if not container:
            raise ProviderError("no container recorded for this deployment")
        args = ["docker", "logs", "--tail", str(lines)]
        if follow:
            args.append("--follow")
        args.append(container)

        if not follow:
            yield from _run(args, check=False, merge_stderr=True).splitlines()
            return

        process = subprocess.Popen(args, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        try:
            for line in process.stdout:
                yield line.rstrip("\n")
        finally:
            process.terminate()

    # -- pull ----------------------------------------------------------

    def pull(self, record, dest: str) -> PullResult:
        """Copy annotation output out of the running container.

        SQLite is snapshotted with `.backup` inside the container first: the
        database runs in WAL mode with a live writer, and copying the file alone
        yields a corrupt or stale database — a silent, total loss that surfaces
        weeks later.
        """
        container = record.provider_ref.get("container")
        if not container:
            raise ProviderError("no container recorded for this deployment")

        os.makedirs(dest, exist_ok=True)
        result = PullResult(dest=dest)

        _run(["docker", "cp", f"{container}:/app/annotation_output", dest], check=False)

        for database in ("project.sqlite", "datasets.sqlite"):
            snapshot = f"/tmp/{database}.snapshot"
            backup = _run(
                ["docker", "exec", container, "sh", "-c",
                 f"test -f /app/{database} && sqlite3 /app/{database} \".backup {snapshot}\""],
                check=False)
            del backup
            copied = _run(["docker", "cp", f"{container}:{snapshot}",
                           os.path.join(dest, database)], check=False)
            if copied is not None and os.path.exists(os.path.join(dest, database)):
                result.notes.append(f"{database} snapshotted with .backup")

        for dirpath, _dirnames, filenames in os.walk(dest):
            for filename in filenames:
                result.files += 1
                try:
                    result.bytes += os.path.getsize(os.path.join(dirpath, filename))
                except OSError:
                    pass
        return result

    # -- destroy -------------------------------------------------------

    def destroy(self, record, *, keep_data: bool = False) -> None:
        container = record.provider_ref.get("container")
        if container:
            _run(["docker", "rm", "-f", container], check=False)
            self.console(f"Removed container {container}")

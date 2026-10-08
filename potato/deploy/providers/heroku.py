"""Deploy a Potato task to Heroku (``--provider heroku``).

Heroku went into sustaining-engineering mode in February 2026: card-paying
accounts keep working, no new features are coming. It is offered because many
labs already have an account, not because it is the best target.

Two facts shape the provider:

* **The filesystem is wiped on every restart**, and dynos restart at least once
  a day. `create` refuses unless an off-host backup is configured (``--backup
  hf|s3``) or ``--demo`` says the data is disposable. The backup restores into
  the empty dyno at boot, which is what makes the daily restart survivable.
* **The container runs as an arbitrary non-root uid**, not the image's 1000, so
  the derived image makes /app writable by anyone (templates/derived.Dockerfile.j2).

The project is baked into an image Heroku builds: a source tarball holding the
bundle, a Dockerfile ``FROM`` the published image, and ``heroku.yml``, uploaded
through ``POST /sources`` and built with ``POST /apps/{app}/builds``. Nothing
needs Docker locally. ``--heroku-registry`` instead builds with local Docker and
pushes to registry.heroku.com, for when the Build API path fails.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

from potato.deploy.providers.base import (
    deploy_command,
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

API_ROOT = "https://api.heroku.com"
from potato.deploy.image import DEFAULT_IMAGE  # noqa: E402
DEFAULT_REGION = "us"
DEFAULT_SIZE = "basic"

# Monthly USD for one always-on dyno. Eco shares a 1000-hour pool and sleeps
# after 30 minutes idle, which wipes the filesystem, so it is allowed but warned.
DYNO_PRICES = {
    "eco": 5.0,
    "basic": 7.0,
    "standard-1x": 25.0,
    "standard-2x": 50.0,
    "performance-m": 250.0,
}
DYNO_MEMORY_MB = {
    "eco": 512, "basic": 512, "standard-1x": 512, "standard-2x": 1024,
    "performance-m": 2560,
}

HEROKU_YML = "build:\n  docker:\n    web: Dockerfile\n"


def app_name(deployment: str) -> str:
    """Heroku app names: lowercase, letters/digits/dashes, at most 30 chars."""
    slug = "".join(c if c.isalnum() else "-" for c in f"potato-{deployment}".lower())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:30].rstrip("-")


class HerokuAPI:
    """Authenticated session against the Platform API."""

    def __init__(self, token: str, *, root: str = API_ROOT, timeout: int = 30):
        if not token:
            raise ProviderError("A Heroku API key is required.")
        self.root = root.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.heroku+json; version=3",
            "Content-Type": "application/json",
            "User-Agent": "potato-deploy",
        })

    def request(self, method: str, path: str, *, accept: Optional[str] = None,
                **kwargs) -> Any:
        headers = {"Accept": accept} if accept else None
        url = path if path.startswith("http") else f"{self.root}{path}"
        attempt = 0
        while True:
            attempt += 1
            response = self.session.request(method, url, timeout=self.timeout,
                                            headers=headers, **kwargs)
            if response.status_code == 429 and attempt < 5:
                time.sleep(min(2 ** attempt, 30))
                continue
            break
        if response.status_code == 401:
            raise ProviderError(
                "Heroku rejected the API key (401). Create one with "
                "`heroku authorizations:create` or at "
                "https://dashboard.heroku.com/account/applications")
        if response.status_code >= 400:
            raise ProviderError(
                f"Heroku {method} {path} failed ({response.status_code}): "
                f"{_error_message(response)}")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    def account(self) -> Dict[str, Any]:
        return self.request("GET", "/account")

    def create_app(self, name: str, region: str) -> Dict[str, Any]:
        return self.request("POST", "/apps",
                            json={"name": name, "region": region, "stack": "container"})

    def get_app(self, name: str) -> Optional[Dict[str, Any]]:
        try:
            return self.request("GET", f"/apps/{name}")
        except ProviderError as exc:
            if "(404)" in str(exc):
                return None
            raise

    def set_config(self, name: str, env: Dict[str, str]) -> None:
        self.request("PATCH", f"/apps/{name}/config-vars", json=env)

    def create_source(self) -> Dict[str, Any]:
        return self.request("POST", "/sources")

    def create_build(self, name: str, url: str, version: str) -> Dict[str, Any]:
        return self.request("POST", f"/apps/{name}/builds",
                            json={"source_blob": {"url": url, "version": version}})

    def get_build(self, name: str, build_id: str) -> Dict[str, Any]:
        return self.request("GET", f"/apps/{name}/builds/{build_id}")

    def scale(self, name: str, size: str, quantity: int = 1) -> None:
        self.request("PATCH", f"/apps/{name}/formation/web",
                     json={"quantity": quantity, "size": size})

    def release_image(self, name: str, image_id: str) -> None:
        self.request("PATCH", f"/apps/{name}/formation",
                     accept="application/vnd.heroku+json; version=3.docker-releases",
                     json={"updates": [{"type": "web", "docker_image": image_id}]})

    def dynos(self, name: str) -> List[Dict[str, Any]]:
        result = self.request("GET", f"/apps/{name}/dynos")
        return result if isinstance(result, list) else []

    def log_session(self, name: str, lines: int, tail: bool) -> str:
        result = self.request("POST", f"/apps/{name}/log-sessions",
                              json={"lines": lines, "tail": tail})
        return result.get("logplex_url", "")

    def delete_app(self, name: str) -> None:
        try:
            self.request("DELETE", f"/apps/{name}")
        except ProviderError as exc:
            if "(404)" not in str(exc):
                raise


def _error_message(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:400] or "(no response body)"
    if isinstance(body, dict):
        return body.get("message") or body.get("id") or str(body)[:400]
    return str(body)[:400]


def source_files(spec: DeploySpec) -> Dict[str, str]:
    """The files added beside the bundle. Pure, so a test can read them."""
    from potato.deploy.providers.vm_base import render_template

    return {
        "Dockerfile": render_template(
            "derived.Dockerfile.j2", image=spec.image or DEFAULT_IMAGE,
            config_rel=spec.extra.get("config_rel", "config.yaml"),
            threads=spec.threads),
        "heroku.yml": HEROKU_YML,
    }


def build_source_tarball(spec: DeploySpec, bundle, dest: str) -> str:
    """bundle + Dockerfile + heroku.yml, as one .tar.gz."""
    with tempfile.TemporaryDirectory(prefix="potato-heroku-") as staging:
        shutil.copytree(bundle.bundle_dir, staging, dirs_exist_ok=True)
        for name, content in source_files(spec).items():
            with open(os.path.join(staging, name), "w", encoding="utf-8") as handle:
                handle.write(content)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with tarfile.open(dest, "w:gz") as archive:
            for entry in sorted(os.listdir(staging)):
                archive.add(os.path.join(staging, entry), arcname=entry)
    return dest


@register_provider
class HerokuProvider(Provider):
    """One container-stack web dyno built from the published image."""

    ignored_flags = ("domain",)
    name = "heroku"
    summary = ("Heroku container dyno from $7/mo; ephemeral disk, so it needs "
               "--backup (sustaining mode since 2026-02)")
    public = True
    ephemeral_fs = True
    supports_logs = True
    supports_pull = True

    def verify_credential(self):
        account = HerokuAPI(self.token).account()
        return account.get("email") or account.get("id", "unknown account")

    # -- plan ----------------------------------------------------------

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        size = (spec.size or DEFAULT_SIZE).lower()
        name = app_name(spec.name)
        env = self.runtime_env(spec, spec.extra.get("generated"))
        registry = bool(spec.extra.get("heroku_registry"))

        plan = DeployPlan(
            result_url_pattern=f"https://{name}-<id>.herokuapp.com",
            estimated_cost_usd_month=DYNO_PRICES.get(size))
        plan.actions = [
            Action("heroku.account", "verify the key with GET /account"),
            Action("heroku.app", f"create {name} on the container stack in "
                   f"{spec.region or DEFAULT_REGION}",
                   {"name": name, "region": spec.region or DEFAULT_REGION,
                    "stack": "container"}),
            Action("state.persist", "record the app name before anything else can fail"),
            Action("heroku.config", "set config vars (secrets never enter the image)",
                   {"keys": sorted(env)}),
        ]
        if registry:
            plan.actions += [
                Action("docker.build", "build the task image locally for linux/amd64"),
                Action("docker.push", f"push to registry.heroku.com/{name}/web"),
                Action("heroku.release", "release the pushed image"),
            ]
        else:
            plan.actions += [
                Action("heroku.source", "upload bundle + Dockerfile + heroku.yml "
                       "to a Heroku-hosted source URL"),
                Action("heroku.build", "build the image on Heroku from heroku.yml"),
            ]
        plan.actions += [
            Action("heroku.scale", f"run one {size} web dyno",
                   {"quantity": 1, "size": size}),
            Action("wait.http", "poll /health"),
        ]

        if size == "eco":
            plan.warnings.append(
                "Eco dynos sleep after 30 minutes idle. Each sleep wipes the "
                "filesystem; the backup restores it, at the cost of a slow first "
                "page for whoever wakes it.")
        memory = DYNO_MEMORY_MB.get(size)
        if memory and memory <= 512:
            plan.warnings.append(
                f"A {size} dyno has {memory} MB of RAM. Potato idles near 140 MB; "
                "a large dataset or many concurrent annotators can exceed it "
                "(Heroku error R14). Use --size standard-2x if that happens.")
        plan.warnings.append(
            "Heroku has been in sustaining-engineering mode since February 2026: "
            "it works, but gets no new features.")
        if size not in DYNO_PRICES:
            plan.warnings.append(f"Unknown dyno size {size!r}; no price shown.")
        if not bundle:
            plan.warnings.append("No bundle was built; this plan cannot run.")
        return plan

    # -- create --------------------------------------------------------

    def refusal(self, spec: DeploySpec, bundle) -> Optional[str]:
        if not spec.extra.get("backup_kinds") and not spec.demo:
            return _NO_BACKUP
        return None

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        refused = self.refusal(spec, bundle)
        if refused:
            raise ProviderError(refused)
        if bundle is None:
            raise ProviderError("No bundle was built; nothing to deploy.")

        api = HerokuAPI(self.token)
        api.account()
        size = (spec.size or DEFAULT_SIZE).lower()

        record = existing or DeploymentRecord(name=spec.name, provider=self.name)
        record.spec.update({"config_path": os.path.abspath(spec.config_path),
                            "size": size})
        name = record.provider_ref.get("app")

        if not name:
            record.status = "creating"
            store.upsert(record)
            app = self._create_app(api, spec)
            name = app["name"]
            record.provider_ref["app"] = name
            record.url = (app.get("web_url") or f"https://{name}.herokuapp.com").rstrip("/")
            store.upsert(record)
        elif api.get_app(name) is None:
            raise ProviderError(
                f"The Heroku app {name} no longer exists. Run `"
                + deploy_command("destroy", spec.config_path, record.name, "--force")
                + "` to clear the record, then deploy again.")
        else:
            record.status = "updating"
            store.upsert(record)

        try:
            env = self.runtime_env(spec, spec.extra.get("generated"))
            api.set_config(name, env)

            if spec.extra.get("heroku_registry"):
                self._release_from_registry(api, spec, bundle, name)
            else:
                self._build_on_heroku(api, spec, bundle, name)

            api.scale(name, size)
            record.bundle_sha = bundle.sha256()
            self.console("Waiting for the dyno to answer...")
            healthy = _wait_for_http(f"{record.url}/health", timeout=300)
            record.status = "running" if healthy else "unhealthy"
        except Exception:
            record.status = "failed"
            store.upsert(record)
            raise
        store.upsert(record)
        if not healthy:
            raise ProviderError(
                f"{record.url} never answered. See `"
                + deploy_command("logs", spec.config_path, record.name) + "`.")
        self.console(f"Live at {record.url}")
        return record

    def _create_app(self, api: HerokuAPI, spec: DeploySpec) -> Dict[str, Any]:
        """Names are global across Heroku; retry with a suffix when taken."""
        base = app_name(spec.name)
        region = spec.region or DEFAULT_REGION
        for attempt in range(4):
            candidate = base if attempt == 0 else f"{base[:25]}-{os.urandom(2).hex()}"
            try:
                self.console(f"Creating the Heroku app {candidate}...")
                return api.create_app(candidate, region)
            except ProviderError as exc:
                if "taken" not in str(exc).lower():
                    raise
        raise ProviderError(f"Could not find a free Heroku app name near {base}.")

    def _build_on_heroku(self, api: HerokuAPI, spec, bundle, name: str) -> None:
        workdir = spec.extra.get("bundle_workdir") or bundle.bundle_dir + ".dist"
        tarball = build_source_tarball(spec, bundle,
                                       os.path.join(workdir, "heroku-source.tar.gz"))
        source = api.create_source()
        blob = source.get("source_blob") or {}
        self.console("Uploading the source...")
        with open(tarball, "rb") as handle:
            response = requests.put(blob["put_url"], data=handle, timeout=600,
                                    headers={"Content-Type": ""})
        if response.status_code >= 300:
            raise ProviderError(f"Uploading the source failed ({response.status_code}).")

        build = api.create_build(name, blob["get_url"], bundle.sha256()[:12])
        self.console("Building on Heroku (the first build pulls the ~840 MB base "
                     "image)...")
        deadline = time.time() + 1800
        while time.time() < deadline:
            status = api.get_build(name, build["id"]).get("status")
            if status == "succeeded":
                return
            if status == "failed":
                raise ProviderError(
                    f"The Heroku build failed. Its log: "
                    f"{build.get('output_stream_url') or 'heroku builds:info'}\n"
                    "If it says heroku.yml or the container stack is not supported "
                    "by this build path, re-run with --heroku-registry (needs "
                    "Docker installed locally).")
            time.sleep(10)
        raise ProviderError("The Heroku build did not finish within 30 minutes.")

    def _release_from_registry(self, api: HerokuAPI, spec, bundle, name: str) -> None:
        if shutil.which("docker") is None:
            raise ProviderError("--heroku-registry needs Docker installed locally.")
        image = f"registry.heroku.com/{name}/web"
        workdir = tempfile.mkdtemp(prefix="potato-heroku-")
        try:
            shutil.copytree(bundle.bundle_dir, workdir, dirs_exist_ok=True)
            for filename, content in source_files(spec).items():
                with open(os.path.join(workdir, filename), "w") as handle:
                    handle.write(content)
            _docker(["login", "--username=_", "--password-stdin", "registry.heroku.com"],
                    stdin=self.token)
            self.console("Building the image for linux/amd64...")
            _docker(["build", "--platform", "linux/amd64", "-t", image, workdir])
            self.console("Pushing to Heroku's registry...")
            _docker(["push", image])
            image_id = _docker(["inspect", image, "--format", "{{.Id}}"]).strip()
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        api.release_image(name, image_id)

    # -- status / logs / pull / destroy --------------------------------

    def status(self, record) -> DeploymentStatus:
        name = record.provider_ref.get("app")
        if not name:
            return DeploymentStatus(state="unknown", detail="no app recorded")
        api = HerokuAPI(self.token)
        if api.get_app(name) is None:
            return DeploymentStatus(state="absent", url=record.url,
                                    detail="the app no longer exists")
        dynos = [d for d in api.dynos(name) if d.get("type") == "web"]
        states = {d.get("state") for d in dynos}
        if not dynos:
            return DeploymentStatus(state="stopped", url=record.url,
                                    detail="no web dyno is running")
        if states != {"up"}:
            return DeploymentStatus(state=",".join(sorted(s or "?" for s in states)),
                                    url=record.url)
        healthy = _wait_for_http(f"{record.url}/health", timeout=30)
        return DeploymentStatus(state="running" if healthy else "unhealthy",
                                url=record.url, healthy=healthy)

    def logs(self, record, *, lines: int = 200, follow: bool = False) -> Iterator[str]:
        url = HerokuAPI(self.token).log_session(record.provider_ref["app"], lines, follow)
        with requests.get(url, stream=True, timeout=(30, None if follow else 60)) as response:
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    yield line

    def pull(self, record, dest: str) -> PullResult:
        """Over the admin archive endpoint; the dyno has no shell to reach."""
        from potato.deploy.providers.render import _admin_key
        from potato.deploy.pull import pull_over_https

        admin_key = _admin_key(record)
        if not admin_key:
            raise ProviderError(
                "No admin key in .potato/secrets.json, so the archive endpoint "
                "cannot be used. The backup (HuggingFace dataset or S3 bucket) "
                "holds the same data.")
        return pull_over_https(record.url, admin_key, dest, console=self.console)

    def destroy(self, record, *, keep_data: bool = False) -> None:
        name = record.provider_ref.get("app")
        if name:
            HerokuAPI(self.token).delete_app(name)
            self.console(f"Deleted the Heroku app {name}")
        self.console("The backup (dataset or bucket) is not touched; it holds the "
                     "annotations. Remove it yourself when you no longer need it.")


_NO_BACKUP = (
    "Refusing to deploy to Heroku with nowhere to keep the annotations. A dyno's "
    "filesystem is wiped on every restart, and dynos restart at least daily.\n"
    "Pick one:\n"
    "  --backup hf --hf-token <token>   back up to a HuggingFace dataset\n"
    "  --backup s3 --s3-bucket <name>   back up to an S3 bucket (also R2/B2)\n"
    "  --demo                           the annotations are disposable")


def _docker(args: List[str], *, stdin: Optional[str] = None) -> str:
    result = subprocess.run(["docker", *args], input=stdin, capture_output=True,
                            text=True)
    if result.returncode != 0:
        raise ProviderError(f"docker {args[0]} failed: "
                            f"{(result.stderr or result.stdout).strip()[:600]}")
    return result.stdout


def _wait_for_http(url: str, timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=10).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(5)
    return False

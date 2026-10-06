"""Deploy a Potato task to Fly.io (``--provider fly``).

One Machine with a volume, created through the Machines REST API: about $7 a
month for 1 GB of RAM plus $0.15/GB of volume, HTTPS on ``<app>.fly.dev`` with
a shared IPv4 address that costs nothing. A Fly volume belongs to one Machine,
which is exactly the shape Potato needs: there is never a second copy of the
in-memory state to disagree with.

Fly chowns a volume's mount point to the image's user, so the task directory
can be the volume itself (/app). The project arrives at start like on Render:
inline through the Machine's ``files`` when it is small, or from the backup's
storage (``potato/deploy/bundle_store.py``). With a volume the entrypoint's sha
marker means it is fetched once per deploy, not once per restart.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, List, Optional

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
from potato.deploy.rest import RestAPI
from potato.deploy.state import DeploymentRecord

MACHINES_API = "https://api.machines.dev/v1"
GRAPHQL_API = "https://api.fly.io/graphql"
TOKEN_PAGE = "https://fly.io/user/personal_access_tokens (or `fly tokens create org`)"
DEFAULT_IMAGE = "ghcr.io/davidjurgens/potato:latest"
DEFAULT_REGION = "iad"
DEFAULT_MEMORY_MB = 1024
DEFAULT_VOLUME_GB = 1
CONTAINER_PORT = 7860

# shared-cpu-1x, USD/month, always on.
MEMORY_PRICES = {256: 1.94, 512: 3.19, 1024: 5.70, 2048: 11.39, 4096: 22.78}
VOLUME_PRICE_PER_GB = 0.15

#: Bundles at most this large travel inline in the Machine config.
INLINE_BUNDLE_LIMIT = 512 * 1024
INLINE_BUNDLE_PATH = "/potato-bundle.tar.gz"

#: Generated and user secrets go through Fly's secret store, not plain env.
SECRET_KEYS = ("POTATO_SECRET_KEY", "POTATO_ADMIN_API_KEY", "HF_TOKEN",
               "POTATO_BUNDLE_TOKEN", "POTATO_S3_ACCESS_KEY_ID",
               "POTATO_S3_SECRET_ACCESS_KEY")


def app_name(deployment: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in f"potato-{deployment}".lower())
    return "-".join(p for p in slug.split("-") if p)[:63]


def machine_config(spec: DeploySpec, *, image: str, env: Dict[str, str],
                   volume_id: Optional[str], memory_mb: int,
                   files: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """The Machine config. Pure, so a test can assert it exactly."""
    config: Dict[str, Any] = {
        "image": image,
        "env": env,
        "guest": {"cpu_kind": "shared", "cpus": 1, "memory_mb": memory_mb},
        "services": [{
            "protocol": "tcp",
            "internal_port": CONTAINER_PORT,
            # One Machine, always on: a stopped Machine answers its first
            # request after a cold start, which an annotator sees as a hang.
            "autostop": "off",
            "autostart": True,
            "min_machines_running": 1,
            "ports": [
                {"port": 80, "handlers": ["http"], "force_https": True},
                {"port": 443, "handlers": ["tls", "http"]},
            ],
        }],
        "checks": {"health": {"type": "http", "port": CONTAINER_PORT,
                              "path": "/health", "interval": "30s",
                              "timeout": "5s", "grace_period": "120s"}},
        "restart": {"policy": "always"},
        "metadata": {"potato": spec.name},
    }
    if volume_id:
        config["mounts"] = [{"volume": volume_id, "path": "/app"}]
    if files:
        config["files"] = files
    return config


class FlyAPI:
    def __init__(self, token: str):
        self.machines = RestAPI(MACHINES_API, token, provider="Fly.io",
                                token_page=TOKEN_PAGE)
        self.token = token

    def graphql(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        result = self.machines.request("POST", GRAPHQL_API,
                                       json={"query": query, "variables": variables})
        if result.get("errors"):
            raise ProviderError(f"Fly.io GraphQL: {result['errors'][0].get('message')}")
        return result.get("data") or {}


ALLOCATE_IP = """
mutation($input: AllocateIPAddressInput!) {
  allocateIpAddress(input: $input) { ipAddress { id address type } }
}"""

SET_SECRETS = """
mutation($input: SetSecretsInput!) {
  setSecrets(input: $input) { release { id } }
}"""


@register_provider
class FlyProvider(Provider):
    """One Fly Machine with a volume, on <app>.fly.dev."""

    name = "fly"
    summary = "Fly.io: one Machine + volume on <app>.fly.dev, about $6/mo"
    public = True
    ephemeral_fs = False
    supports_logs = False
    supports_pull = True

    def verify_credential(self):
        data = FlyAPI(self.token).graphql("query { viewer { email } }", {})
        return (data.get("viewer") or {}).get("email") or "token accepted"

    # -- plan ----------------------------------------------------------

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        name = app_name(spec.name)
        memory = _memory(spec)
        volume_gb = spec.volume_gb or DEFAULT_VOLUME_GB
        env, secret_keys = self._split_env(spec)
        delivery = self._delivery_description(spec, bundle)

        plan = DeployPlan(
            result_url_pattern=f"https://{name}.fly.dev",
            estimated_cost_usd_month=(MEMORY_PRICES.get(memory)
                                      + volume_gb * VOLUME_PRICE_PER_GB)
            if memory in MEMORY_PRICES else None)
        plan.actions = [
            Action("fly.app", f"create the app {name} in org "
                   f"{spec.extra.get('owner') or 'personal'}"),
            Action("state.persist", "record the app before anything else can fail"),
            Action("fly.ips", "allocate a shared IPv4 (free) and an IPv6 address"),
            Action("fly.secrets", "store secrets in Fly's secret store",
                   {"keys": sorted(secret_keys)}),
            Action("fly.volume", f"create a {volume_gb} GB volume in "
                   f"{spec.region or DEFAULT_REGION}"),
            Action("bundle.deliver", delivery),
            Action("fly.machine", f"create one shared-cpu-1x/{memory}MB Machine "
                   "with the volume at /app",
                   machine_config(spec, image=spec.image or DEFAULT_IMAGE,
                                  env={k: "…" for k in env}, volume_id="<volume>",
                                  memory_mb=memory)),
            Action("wait.started", "wait for the Machine to start"),
            Action("wait.http", "poll /health"),
        ]
        plan.warnings.append(
            "Fly has no free tier; new organizations need a card on file.")
        if not bundle:
            plan.warnings.append("No bundle was built; this plan cannot run.")
        return plan

    def _split_env(self, spec: DeploySpec):
        env = self.runtime_env(spec, spec.extra.get("generated"))
        secrets = {k: v for k, v in env.items() if k in SECRET_KEYS or k in spec.secrets}
        plain = {k: v for k, v in env.items() if k not in secrets}
        return plain, secrets

    def _store(self, spec):
        from potato.deploy.bundle_store import store_for

        options = spec.extra.get("backup")
        return store_for(options) if options is not None else None

    def _can_deliver(self, spec, bundle) -> bool:
        return self._store(spec) is not None or (
            bundle is not None and bundle.total_bytes <= INLINE_BUNDLE_LIMIT)

    def _delivery_description(self, spec, bundle) -> str:
        store = self._store(spec)
        if store is not None:
            return f"upload the project to {store.describe()}; fetched at start"
        if bundle is not None and bundle.total_bytes <= INLINE_BUNDLE_LIMIT:
            return "ship the project inline in the Machine's files"
        return "(nowhere; see REFUSED below)"

    # -- create --------------------------------------------------------

    def refusal(self, spec: DeploySpec, bundle) -> Optional[str]:
        if bundle is not None and not self._can_deliver(spec, bundle):
            return _NO_DELIVERY
        return None

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        if bundle is None:
            raise ProviderError("No bundle was built; nothing to deploy.")
        refused = self.refusal(spec, bundle)
        if refused:
            raise ProviderError(refused)

        api = FlyAPI(self.token)
        name = app_name(spec.name)
        region = spec.region or DEFAULT_REGION
        record = existing or DeploymentRecord(name=spec.name, provider=self.name)
        record.spec.update({"config_path": os.path.abspath(spec.config_path),
                            "region": region})

        if not record.provider_ref.get("app"):
            record.status = "creating"
            store.upsert(record)
            api.machines.post("/apps", {"app_name": name,
                                        "org_slug": spec.extra.get("owner") or "personal"})
            record.provider_ref["app"] = name
            record.url = f"https://{name}.fly.dev"
            store.upsert(record)
            for kind in ("shared_v4", "v6"):
                api.graphql(ALLOCATE_IP, {"input": {"appId": name, "type": kind}})
        else:
            record.status = "updating"
            store.upsert(record)

        try:
            env, secrets = self._split_env(spec)
            files = None
            location = self._deliver(spec, bundle)
            if location is None:
                files = [{"guest_path": INLINE_BUNDLE_PATH,
                          "raw_value": _inline_bundle(spec, bundle)}]
                env.update({"POTATO_BUNDLE_URL": f"file://{INLINE_BUNDLE_PATH}"})
                env["POTATO_BUNDLE_SHA256"] = _file_sha(spec, bundle)
            else:
                plain = location.env()
                token = plain.pop("POTATO_BUNDLE_TOKEN", None)
                env.update(plain)
                if token:
                    secrets["POTATO_BUNDLE_TOKEN"] = token
            if secrets:
                api.graphql(SET_SECRETS, {"input": {
                    "appId": record.provider_ref["app"],
                    "secrets": [{"key": k, "value": v} for k, v in sorted(secrets.items())]}})

            if not record.provider_ref.get("volume_id"):
                volume = api.machines.post(f"/apps/{name}/volumes", {
                    "name": "potato_data", "region": region,
                    "size_gb": int(spec.volume_gb or DEFAULT_VOLUME_GB)})
                record.provider_ref["volume_id"] = volume["id"]
                store.upsert(record)

            config = machine_config(spec, image=spec.image or DEFAULT_IMAGE, env=env,
                                    volume_id=record.provider_ref["volume_id"],
                                    memory_mb=_memory(spec), files=files)
            machine_id = record.provider_ref.get("machine_id")
            if machine_id:
                # Update in place: stop, replace config, start. One Machine, so
                # there is never a second process on the volume.
                api.machines.post(f"/apps/{name}/machines/{machine_id}",
                                  {"config": config, "region": region})
            else:
                machine = api.machines.post(f"/apps/{name}/machines",
                                            {"name": "potato", "region": region,
                                             "config": config})
                machine_id = machine["id"]
                record.provider_ref["machine_id"] = machine_id
                store.upsert(record)

            api.machines.get(f"/apps/{name}/machines/{machine_id}/wait"
                             "?state=started&timeout=60")
            record.bundle_sha = bundle.sha256()
            record.status = "running" if _healthy(record.url, timeout=300) else "unhealthy"
        except Exception:
            record.status = "failed"
            store.upsert(record)
            raise
        store.upsert(record)
        self.console(f"Live at {record.url}")
        return record

    def _deliver(self, spec, bundle):
        """Publish to the backup's storage, or None to ship inline."""
        store = self._store(spec)
        if store is None:
            return None
        from potato.deploy.bundle_store import publish

        return publish(bundle, store, spec.extra.get("bundle_workdir")
                       or bundle.bundle_dir + ".dist")

    # -- status / pull / destroy ---------------------------------------

    def status(self, record) -> DeploymentStatus:
        name = record.provider_ref.get("app")
        if not name:
            return DeploymentStatus(state="unknown", detail="no app recorded")
        api = FlyAPI(self.token)
        if api.machines.get_or_none(f"/apps/{name}") is None:
            return DeploymentStatus(state="absent", url=record.url)
        machine = api.machines.get_or_none(
            f"/apps/{name}/machines/{record.provider_ref.get('machine_id')}") or {}
        state = machine.get("state", "unknown")
        if state != "started":
            return DeploymentStatus(state=state, url=record.url, raw=machine)
        healthy = _healthy(record.url, timeout=20)
        return DeploymentStatus(state="running" if healthy else "unhealthy",
                                url=record.url, healthy=healthy, raw=machine)

    def logs(self, record, *, lines: int = 200, follow: bool = False):
        raise ProviderError(
            "Fly serves logs over its own transport, not the REST API. Use:\n"
            f"  fly logs -a {record.provider_ref.get('app')}")

    def pull(self, record, dest: str) -> PullResult:
        from potato.deploy.providers.render import _admin_key
        from potato.deploy.pull import pull_over_https

        admin_key = _admin_key(record)
        if not admin_key:
            raise ProviderError("No admin key in .potato/secrets.json; cannot pull.")
        return pull_over_https(record.url, admin_key, dest, console=self.console)

    def destroy(self, record, *, keep_data: bool = False) -> None:
        name = record.provider_ref.get("app")
        if not name:
            return
        if keep_data:
            self.console("Fly deletes an app's volumes with the app; --keep-data "
                         "cannot keep them. Pull first.")
        FlyAPI(self.token).machines.delete(f"/apps/{name}?force=true")
        self.console(f"Deleted the Fly app {name} and its volume")


_NO_DELIVERY = (
    "Fly runs the published image and fetches your project into it, so the "
    f"project has to be somewhere first. Projects under {INLINE_BUNDLE_LIMIT // 1024} "
    "KB travel inline; this one is larger. Pass --backup hf --hf-token <token> or "
    "--backup s3 --s3-bucket <bucket>, and the project goes to that storage.")


def _memory(spec: DeploySpec) -> int:
    if spec.size and str(spec.size).isdigit():
        return int(spec.size)
    return DEFAULT_MEMORY_MB


def _tarball(spec, bundle) -> str:
    from potato.deploy.bundle import bundle_tarball

    workdir = spec.extra.get("bundle_workdir") or bundle.bundle_dir + ".dist"
    os.makedirs(workdir, exist_ok=True)
    return bundle_tarball(bundle, os.path.join(workdir, "bundle.tar.gz"))


def _inline_bundle(spec, bundle) -> str:
    with open(_tarball(spec, bundle), "rb") as handle:
        return base64.b64encode(handle.read()).decode("ascii")


def _file_sha(spec, bundle) -> str:
    from potato.deploy.bundle_store import file_sha256

    return file_sha256(_tarball(spec, bundle))


def _healthy(url: str, timeout: int) -> bool:
    import time

    import requests

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"{url}/health", timeout=10).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(5)
    return False

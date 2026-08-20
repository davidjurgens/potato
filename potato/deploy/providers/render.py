"""Deploy a Potato task to Render.

The free path. No credit card, no CLI, no git repository: one
``POST /v1/services`` with ``image.imagePath`` deploys a prebuilt image, and
HTTPS on ``*.onrender.com`` comes with it.

What it buys in convenience it charges for in persistence. A free instance has
no disk and spins down after 15 minutes idle, and a spun-down instance loses
everything written to its filesystem. So the provider refuses to create a free
service without a route for the data to leave: either a HuggingFace Dataset
backup, or ``--demo`` to say out loud that the annotations are disposable. A
paid instance with a disk has neither problem.

The bundle travels differently here than on a droplet. Render pulls an image and
runs it; there is no SSH and nothing to upload to. So the project is fetched at
container start from a URL, or baked into a derived image. Fetch-at-start is the
default because it needs no registry account.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

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

API_ROOT = "https://api.render.com/v1"
DEFAULT_IMAGE = "ghcr.io/davidjurgens/potato:latest"
DEFAULT_REGION = "oregon"
DEFAULT_PLAN = "free"

# Render routes to whatever the service listens on; the image defaults to 7860.
CONTAINER_PORT = 7860

PLAN_PRICES = {
    "free": 0.0,
    "starter": 7.0,
    "standard": 25.0,
    "pro": 85.0,
}
DISK_PRICE_PER_GB = 0.25

# Free instances stop after this much idle time and lose their filesystem.
FREE_IDLE_MINUTES = 15


class RenderAPI:
    """Authenticated session against api.render.com."""

    def __init__(self, token: str, *, root: str = API_ROOT, timeout: int = 30):
        if not token:
            raise ProviderError("A Render API key is required.")
        self.root = root.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "potato-deploy",
        })

    def request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.root}{path}"
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.session.request(method, url, timeout=self.timeout,
                                                **kwargs)
            except requests.RequestException as exc:
                raise ProviderError(f"Could not reach the Render API: {exc}") from exc

            if response.status_code == 429 and attempt <= 5:
                header = response.headers.get("Retry-After", "")
                delay = int(header) if header.isdigit() else min(2 ** attempt, 30)
                time.sleep(min(delay, 60))
                continue

            if response.status_code == 401:
                raise ProviderError(
                    "Render rejected the API key (401). Create one at "
                    "https://dashboard.render.com/u/settings#api-keys")
            if response.status_code >= 400:
                raise ProviderError(
                    f"Render API error {response.status_code} on {method} {path}: "
                    f"{_error_message(response)}")
            if response.status_code == 204 or not response.content:
                return {}
            try:
                return response.json()
            except ValueError:
                return {}

    def verify_token(self) -> List[Dict[str, Any]]:
        """Owners visible to this key. Also the id a service must be created under."""
        return [item.get("owner", item) for item in self.request("GET", "/owners")]

    def create_service(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self.request("POST", "/services", json=payload)
        # The create response nests the service; a fetch does not.
        return result.get("service", result)

    def get_service(self, service_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self.request("GET", f"/services/{service_id}")
        except ProviderError as exc:
            if "404" in str(exc):
                return None
            raise

    def delete_service(self, service_id: str) -> None:
        try:
            self.request("DELETE", f"/services/{service_id}")
        except ProviderError as exc:
            if "404" not in str(exc):
                raise

    def trigger_deploy(self, service_id: str) -> Dict[str, Any]:
        return self.request("POST", f"/services/{service_id}/deploys", json={})

    def list_deploys(self, service_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        result = self.request("GET", f"/services/{service_id}/deploys?limit={limit}")
        if isinstance(result, list):
            return [item.get("deploy", item) for item in result]
        return []


def _error_message(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:400] or "(no response body)"
    if isinstance(body, dict):
        return body.get("message") or body.get("error") or str(body)[:400]
    return str(body)[:400]


def service_payload(spec: DeploySpec, *, owner_id: str, env: Dict[str, str],
                    bundle_url: Optional[str] = None) -> Dict[str, Any]:
    """The POST /v1/services body.

    Pure, so a test can assert exactly what would be created.
    """
    plan = spec.extra.get("plan") or DEFAULT_PLAN
    image = spec.image or DEFAULT_IMAGE

    env_vars = [{"key": key, "value": str(value)} for key, value in sorted(env.items())]
    if bundle_url:
        env_vars.append({"key": "POTATO_BUNDLE_URL", "value": bundle_url})

    payload: Dict[str, Any] = {
        "type": "web_service",
        "name": f"potato-{spec.name}",
        "ownerId": owner_id,
        "region": spec.region or DEFAULT_REGION,
        "image": {"imagePath": image},
        "envVars": env_vars,
        "serviceDetails": {
            "env": "image",
            "plan": plan,
            "envSpecificDetails": {},
            # One instance, always. Potato holds the item pool, the assignment
            # queue and every annotator's state in memory per process, so a
            # second instance hands out work the first already assigned and the
            # later save wins. Horizontal scaling is not a tuning choice here.
            "numInstances": 1,
        },
    }

    disk_gb = spec.volume_gb
    if disk_gb:
        payload["serviceDetails"]["disk"] = {
            "name": f"potato-{spec.name}-data",
            "mountPath": "/data",
            "sizeGB": int(disk_gb),
        }
    return payload


@register_provider
class RenderProvider(Provider):
    """A single web service running the published image."""

    name = "render"
    requires = ()
    public = True
    supports_logs = False       # log streaming needs a paid plan and a websocket
    supports_pull = True        # over HTTPS: there is no shell to SSH into

    @property
    def ephemeral_fs(self) -> bool:
        # True on free, false with a disk. The value is per-deployment, so
        # callers that need it accurately use plan().warnings instead.
        return True

    # -- plan ----------------------------------------------------------

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        plan_name = spec.extra.get("plan") or DEFAULT_PLAN
        env = self.runtime_env(spec, spec.extra.get("generated"))
        payload = service_payload(spec, owner_id="<owner-id>", env=env)
        # Never render values: a plan is printed and often pasted into an issue.
        payload["envVars"] = sorted(env)

        result = DeployPlan(
            result_url_pattern=f"https://potato-{spec.name}.onrender.com",
            estimated_cost_usd_month=_estimate_cost(plan_name, spec.volume_gb))
        result.actions = [
            Action("render.owners", "verify the API key with GET /v1/owners"),
            Action("render.service",
                   f"create a {plan_name} web service from "
                   f"{spec.image or DEFAULT_IMAGE}", payload),
            Action("state.persist",
                   "record the service id before anything else can fail"),
            Action("wait.deploy", "poll the deploy until it reports live"),
            Action("wait.http", "poll the service URL until it answers"),
        ]

        has_backup = bool(spec.extra.get("huggingface_backup"))
        if plan_name == "free":
            if not spec.volume_gb:
                result.warnings.append(
                    f"A free Render instance has no disk and stops after "
                    f"{FREE_IDLE_MINUTES} minutes idle. Everything written to it "
                    "is lost when it stops, including annotations.")
            if not has_backup and not spec.demo:
                result.warnings.append(
                    "Nothing is configured to carry the data off the instance. "
                    "Supply --hf-token for a HuggingFace Dataset backup, choose "
                    "--plan starter --volume-gb 1, or pass --demo if the "
                    "annotations are genuinely disposable.")
        if spec.volume_gb and plan_name == "free":
            result.warnings.append(
                "Render does not attach disks to free instances; this needs "
                "--plan starter or higher.")
        if not bundle:
            result.warnings.append("No bundle was built; this plan cannot run.")
        return result

    # -- create --------------------------------------------------------

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        plan_name = spec.extra.get("plan") or DEFAULT_PLAN
        has_backup = bool(spec.extra.get("huggingface_backup"))

        # The refusal is the point of this provider's create(). A free instance
        # with no backup loses the study's data the first time it goes idle, and
        # it does so silently, fifteen minutes after the last annotator leaves.
        if plan_name == "free" and not has_backup and not spec.demo:
            raise ProviderError(
                "Refusing to create a free Render service with no way to keep the "
                "annotations.\n"
                f"A free instance has no disk and stops after {FREE_IDLE_MINUTES} "
                "minutes idle; when it stops, everything on its filesystem is gone.\n"
                "Pick one:\n"
                "  --hf-token <token>          back up to a HuggingFace Dataset\n"
                "  --plan starter --volume-gb 1  a paid instance with a real disk\n"
                "  --demo                      the annotations are disposable")

        api = RenderAPI(self.token)
        owners = api.verify_token()
        if not owners:
            raise ProviderError(
                "The Render API key is valid but is attached to no owner, so "
                "nothing can be created with it.")
        owner_id = spec.extra.get("owner_id") or owners[0].get("id")

        record = existing or DeploymentRecord(name=spec.name, provider=self.name)
        record.spec.update({"config_path": os.path.abspath(spec.config_path),
                            "plan": plan_name})

        if record.provider_ref.get("service_id"):
            return self._redeploy(api, record, store)

        record.status = "creating"
        store.upsert(record)

        env = self.runtime_env(spec, spec.extra.get("generated"))
        env.update(_backup_env(spec))

        try:
            service = api.create_service(service_payload(
                spec, owner_id=owner_id, env=env,
                bundle_url=spec.extra.get("bundle_url")))
        except ProviderError:
            record.status = "failed"
            store.upsert(record)
            raise

        record.provider_ref["service_id"] = service.get("id")
        record.provider_ref["owner_id"] = owner_id
        record.url = (service.get("serviceDetails", {}) or {}).get("url") \
            or f"https://potato-{spec.name}.onrender.com"
        record.bundle_sha = bundle.sha256() if bundle else None
        store.upsert(record)

        self.console(f"Created service {record.provider_ref['service_id']}")
        self.console("Waiting for the first deploy...")
        if not self._wait_for_live(api, record):
            record.status = "unhealthy"
            store.upsert(record)
            raise ProviderError(
                f"The service was created but never became live. Check the build "
                f"log at https://dashboard.render.com/web/"
                f"{record.provider_ref['service_id']}")

        record.status = "running"
        store.upsert(record)
        self.console(f"Live at {record.url}")
        return record

    def _redeploy(self, api, record, store) -> DeploymentRecord:
        record.status = "updating"
        store.upsert(record)
        api.trigger_deploy(record.provider_ref["service_id"])
        self.console("Triggered a redeploy; waiting for it to go live...")
        record.status = "running" if self._wait_for_live(api, record) else "unhealthy"
        store.upsert(record)
        return record

    def _wait_for_live(self, api, record, timeout: int = 900) -> bool:
        service_id = record.provider_ref["service_id"]
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            deploys = api.list_deploys(service_id, limit=1)
            status = (deploys[0].get("status") if deploys else None)
            if status != last:
                self.console(f"  deploy: {status}")
                last = status
            if status == "live":
                return True
            if status in ("build_failed", "update_failed", "canceled",
                          "pre_deploy_failed"):
                return False
            time.sleep(10)
        return False

    # -- status --------------------------------------------------------

    def status(self, record) -> DeploymentStatus:
        service_id = record.provider_ref.get("service_id")
        if not service_id:
            return DeploymentStatus(state="unknown", detail="no service recorded")

        api = RenderAPI(self.token)
        service = api.get_service(service_id)
        if service is None:
            return DeploymentStatus(state="absent", url=record.url,
                                    detail="the service no longer exists")
        if service.get("suspended") == "suspended":
            return DeploymentStatus(
                state="suspended", url=record.url, raw=service,
                detail="Render has suspended the service; check billing or the "
                       "dashboard")

        deploys = api.list_deploys(service_id, limit=1)
        deploy_status = deploys[0].get("status") if deploys else "unknown"

        healthy, detail = self._probe(record)
        if not healthy and record.spec.get("plan", DEFAULT_PLAN) == "free":
            detail += (" A free instance spins down when idle, so the first "
                       "request after a quiet period takes up to a minute.")
        return DeploymentStatus(
            state="running" if healthy else deploy_status,
            url=record.url, healthy=healthy, detail=detail.strip(), raw=service)

    def _probe(self, record) -> tuple:
        if not record.url:
            return False, "no URL recorded"
        try:
            # Generous: a cold free instance takes tens of seconds to wake.
            response = requests.get(f"{record.url}/health", timeout=90)
        except requests.RequestException as exc:
            return False, f"{record.url} is not answering: {exc}"
        if response.status_code == 200:
            return True, ""
        if response.status_code == 503:
            return False, "the server is still loading data (503 from /health)."
        return False, f"/health returned {response.status_code}."

    # -- logs / pull ---------------------------------------------------

    def logs(self, record, *, lines: int = 200, follow: bool = False) -> Iterator[str]:
        raise ProviderError(
            "Render's log API needs a paid plan and a websocket connection, so "
            "Potato does not stream them. Read them in the dashboard: "
            f"https://dashboard.render.com/web/"
            f"{record.provider_ref.get('service_id', '')}")

    def pull(self, record, dest: str) -> PullResult:
        """Download over HTTPS, because there is no shell on a Render service.

        A free instance may have spun down, in which case the first request
        wakes it and takes up to a minute; the pull timeouts allow for that.
        """
        from potato.deploy.pull import pull_over_https

        admin_key = _admin_key(record)
        if not admin_key:
            raise ProviderError(
                "No admin API key for this deployment, and there is no SSH into a "
                "Render service, so there is no way to reach the data. The key is "
                "written to .potato/secrets.json at deploy time.")
        if not record.url:
            raise ProviderError("No URL recorded for this deployment.")
        return pull_over_https(record.url, admin_key, dest, console=self.console)

    # -- destroy -------------------------------------------------------

    def destroy(self, record, *, keep_data: bool = False) -> None:
        service_id = record.provider_ref.get("service_id")
        if not service_id:
            self.console("No service recorded; nothing to delete.")
            return
        RenderAPI(self.token).delete_service(service_id)
        self.console(f"Deleted service {service_id}")
        if keep_data:
            self.console(
                "keep_data has no effect on Render: deleting a service deletes "
                "its disk too. Anything already backed up is unaffected.")


def _admin_key(record) -> Optional[str]:
    """The admin API key from the project's secret store."""
    from potato.deploy.state import SecretStore

    config_path = record.spec.get("config_path")
    if not config_path:
        return None
    return SecretStore(config_path).get(record.name, "admin_api_key")


def _backup_env(spec: DeploySpec) -> Dict[str, str]:
    """HF token for the in-process Dataset backup, when one is configured."""
    token = spec.extra.get("hf_token")
    return {"HF_TOKEN": token} if token else {}


def _estimate_cost(plan_name: str, disk_gb: Optional[int]) -> float:
    cost = PLAN_PRICES.get(plan_name, 0.0)
    if disk_gb:
        cost += float(disk_gb) * DISK_PRICE_PER_GB
    return cost

"""Deploy a Potato task to Render.

The free path. No credit card, no CLI, no git repository: one
``POST /v1/services`` with ``image.imagePath`` deploys a prebuilt image, and
HTTPS on ``*.onrender.com`` comes with it.

What it buys in convenience it charges for in persistence. A free instance has
no disk and spins down after 15 minutes idle, and a spun-down instance loses
everything written to its filesystem. The provider refuses to create any
service without a backup (HuggingFace Dataset or S3), because the backup's
storage is also how the project reaches the container (below); on the free plan
it is the only copy of the annotations as well.

The bundle travels differently here than on a droplet. Render pulls an image and
runs it; there is no SSH and nothing to upload to. So the project is published
to the backup's own storage (see ``potato/deploy/bundle_store.py``) and the
container's entrypoint fetches it at start. That needs no registry account. An
earlier version set ``POTATO_BUNDLE_URL`` only when something passed a URL in,
nothing ever did, and nothing in the image read it: every service booted the
bare image and exited at the config check.
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
from potato.deploy.image import DEFAULT_IMAGE  # noqa: E402
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

    def update_env_vars(self, service_id: str, env_vars: List[Dict[str, str]]) -> Any:
        """Replace the service's environment (PUT replaces the whole set)."""
        return self.request("PUT", f"/services/{service_id}/env-vars", json=env_vars)

    def trigger_deploy(self, service_id: str,
                       image_url: Optional[str] = None) -> Dict[str, Any]:
        # An image-backed service deploys the image named here; without it,
        # Render redeploys whatever image the service was created with.
        body = {"imageUrl": image_url} if image_url else {}
        return self.request("POST", f"/services/{service_id}/deploys", json=body)

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


def env_var_list(env: Dict[str, str]) -> List[Dict[str, str]]:
    return [{"key": key, "value": str(value)} for key, value in sorted(env.items())]


def service_payload(spec: DeploySpec, *, owner_id: str,
                    env: Dict[str, str]) -> Dict[str, Any]:
    """The POST /v1/services body.

    Pure, so a test can assert exactly what would be created. ``env`` carries
    the bundle location (POTATO_BUNDLE_*) alongside the runtime environment.
    """
    plan = spec.extra.get("plan") or DEFAULT_PLAN
    image = spec.image or DEFAULT_IMAGE

    env_vars = env_var_list(env)

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
        # /app, where the image works and the entrypoint unpacks the project.
        # The disk used to be mounted at /data, which nothing wrote to, so a
        # paid disk held none of the annotations.
        payload["serviceDetails"]["disk"] = {
            "name": f"potato-{spec.name}-data",
            "mountPath": "/app",
            "sizeGB": int(disk_gb),
        }
    return payload


@register_provider
class RenderProvider(Provider):
    """A single web service running the published image."""

    ignored_flags = ("domain", "size")
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

    def verify_credential(self):
        owners = RenderAPI(self.token).verify_token()
        if not owners:
            raise ProviderError("Render accepted the key but returned no owner.")
        first = owners[0]
        return first.get("email") or first.get("name") or first.get("id", "unknown")

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        plan_name = spec.extra.get("plan") or DEFAULT_PLAN
        env = self.runtime_env(spec, spec.extra.get("generated"))
        payload = service_payload(spec, owner_id="<owner-id>", env=env)
        # Never render values: a plan is printed and often pasted into an issue.
        payload["envVars"] = sorted(env)

        result = DeployPlan(
            result_url_pattern=f"https://potato-{spec.name}.onrender.com",
            estimated_cost_usd_month=_estimate_cost(plan_name, spec.volume_gb))
        bundle_store = _bundle_store(spec)
        result.actions = [
            Action("render.owners", "verify the API key with GET /v1/owners"),
            Action("bundle.publish",
                   f"upload the project tarball to "
                   f"{bundle_store.describe() if bundle_store else '(nowhere; see REFUSED below)'}"
                   "; the container fetches it at start"),
            Action("render.service",
                   f"create a {plan_name} web service from "
                   f"{spec.image or DEFAULT_IMAGE}", payload),
            Action("state.persist",
                   "record the service id before anything else can fail"),
            Action("wait.deploy", "poll the deploy until it reports live"),
            Action("wait.http", "poll the service URL until it answers"),
        ]

        if result.estimated_cost_usd_month is None:
            result.warnings.append(
                f"No price is known for Render plan {plan_name!r}; check "
                "Render's pricing before confirming.")
        if bundle_store is not None and bundle_store.kind == "s3" and not spec.volume_gb:
            result.warnings.append(
                "The project is fetched from a presigned S3 URL, valid seven "
                "days. With no disk every restart fetches again, so after a "
                "week a restart fails until `potato deploy up` is run again. "
                "Add --backup hf, or a disk, to avoid that.")
        if plan_name == "free":
            result.warnings.append(
                f"A free Render instance has no disk and stops after "
                f"{FREE_IDLE_MINUTES} minutes idle and loses everything "
                "written to it. The backup is the only copy of the "
                "annotations, restored when it starts again.")
        if not bundle:
            result.warnings.append("No bundle was built; this plan cannot run.")
        return result

    # -- create --------------------------------------------------------

    def refusal(self, spec: DeploySpec, bundle) -> Optional[str]:
        # The project is uploaded to the backup's storage, so every Render
        # deploy needs one. That also covers the free plan, whose data would
        # otherwise be lost fifteen minutes after the last annotator leaves.
        plan_name = spec.extra.get("plan") or DEFAULT_PLAN
        if not spec.extra.get("backup_kinds") or _bundle_store(spec) is None:
            if plan_name == "free":
                return _NO_BUNDLE_STORE + _FREE_PLAN_NOTE
            return _NO_BUNDLE_STORE
        # A free instance takes no disk. Requesting one used to drop both
        # data-loss warnings from the plan while the service ran without it.
        if plan_name == "free" and spec.volume_gb:
            return ("Render does not attach disks to free instances, so "
                    "--volume-gb needs --plan starter or higher. Without a disk "
                    "the backup is the only copy of the annotations.")
        record = spec.extra.get("existing_record")
        if record is not None and record.provider_ref.get("service_id"):
            had = record.spec or {}
            changed = [f"{flag} {want} (it has {had.get(key)})"
                       for key, flag, want in (("plan", "--plan", spec.extra.get("plan")),
                                               ("region", "--region", spec.region),
                                               ("volume_gb", "--volume-gb", spec.volume_gb))
                       if want is not None and had.get(key) is not None
                       and str(want) != str(had.get(key))]
            if changed:
                return (f"'{record.name}' already has a Render service, and a "
                        f"redeploy cannot change {', '.join(changed)}. Change it "
                        "in the Render dashboard, or pull, destroy and deploy again.")
        return None

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        plan_name = spec.extra.get("plan") or DEFAULT_PLAN
        refused = self.refusal(spec, bundle)
        if refused:
            raise ProviderError(refused)
        bundle_store = _bundle_store(spec)

        api = RenderAPI(self.token)
        owners = api.verify_token()
        if not owners:
            raise ProviderError(
                "The Render API key is valid but is attached to no owner, so "
                "nothing can be created with it.")
        owner_id = spec.extra.get("owner_id") or owners[0].get("id")

        record = existing or DeploymentRecord(name=spec.name, provider=self.name)
        record.spec["config_path"] = os.path.abspath(spec.config_path)

        env = self._service_env(spec, bundle, bundle_store)

        if record.provider_ref.get("service_id"):
            return self._redeploy(api, record, store, env,
                                  image=spec.image or DEFAULT_IMAGE)

        # Recorded only when the service is created: a redeploy cannot change
        # them, and recording the requested plan made `status` report one the
        # service did not have.
        record.spec.update({"plan": plan_name,
                            "region": spec.region or DEFAULT_REGION,
                            "volume_gb": spec.volume_gb})

        record.status = "creating"
        store.upsert(record)

        try:
            service = api.create_service(service_payload(
                spec, owner_id=owner_id, env=env))
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

    def _service_env(self, spec, bundle, bundle_store) -> Dict[str, str]:
        """Runtime environment plus where to fetch the freshly published bundle."""
        if bundle is None:
            raise ProviderError("No bundle was built; nothing to deploy.")
        from potato.deploy.bundle_store import publish

        self.console(f"Publishing the project to {bundle_store.describe()}...")
        location = publish(bundle, bundle_store,
                           spec.extra.get("bundle_workdir")
                           or os.path.join(bundle.bundle_dir + ".dist"))
        env = self.runtime_env(spec, spec.extra.get("generated"))
        env.update(location.env())
        return env

    def _redeploy(self, api, record, store, env: Dict[str, str],
                  image: Optional[str] = None) -> DeploymentRecord:
        """Push the new environment (and so the new bundle), then deploy.

        Triggering a deploy alone restarted the old bundle with the old
        settings: the documented way to push a change changed nothing.
        """
        record.status = "updating"
        store.upsert(record)
        api.update_env_vars(record.provider_ref["service_id"], env_var_list(env))
        api.trigger_deploy(record.provider_ref["service_id"], image_url=image)
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


_NO_BUNDLE_STORE = (
    "Render runs the published image and fetches your project into it at start, "
    "so the project has to be uploaded somewhere first. It goes to the backup's "
    "storage, so --demo is not an option here: pass --backup hf --hf-token "
    "<token> (recommended: the link never expires) or --backup s3 --s3-bucket "
    "<bucket>.")

_FREE_PLAN_NOTE = (
    " On the free plan the backup is also the only copy of the annotations, "
    f"since the instance stops after {FREE_IDLE_MINUTES} minutes idle and loses "
    "its filesystem.")


def _bundle_store(spec: DeploySpec):
    from potato.deploy.bundle_store import store_for

    options = spec.extra.get("backup")
    return store_for(options) if options is not None else None


def _estimate_cost(plan_name: str, disk_gb: Optional[int]) -> Optional[float]:
    # An unlisted plan is unknown, not free.
    if plan_name not in PLAN_PRICES:
        return None
    cost = PLAN_PRICES[plan_name]
    if disk_gb:
        cost += float(disk_gb) * DISK_PRICE_PER_GB
    return cost

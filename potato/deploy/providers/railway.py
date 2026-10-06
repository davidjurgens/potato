"""Deploy a Potato task to Railway (``--provider railway``).

A project with one service running the published image, a volume mounted at
/app, and a ``*.up.railway.app`` domain. Billing is per usage: the $5 Hobby
plan includes $5 of it, and a small always-on task typically lands at $10-20
a month. The GraphQL calls below were checked against Railway's published
schema (it allows introspection) in October 2026.

Railway mounts volumes owned by root, so the service runs with
``RAILWAY_RUN_UID=0``; the image's entrypoint chowns /app and drops to its own
user before the server starts. The project arrives at start from the backup's
storage, like on Render; with a volume, the entrypoint fetches it once per
deploy rather than once per restart.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

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

GRAPHQL_API = "https://backboard.railway.com/graphql/v2"
TOKEN_PAGE = "https://railway.com/account/tokens"
DEFAULT_IMAGE = "ghcr.io/davidjurgens/potato:latest"
CONTAINER_PORT = 7860

FAILED_STATES = {"FAILED", "CRASHED", "REMOVED", "SKIPPED"}

PROJECT_CREATE = """
mutation($input: ProjectCreateInput!) {
  projectCreate(input: $input) {
    id
    environments { edges { node { id name } } }
  }
}"""

SERVICE_CREATE = """
mutation($input: ServiceCreateInput!) { serviceCreate(input: $input) { id } }"""

VOLUME_CREATE = """
mutation($input: VolumeCreateInput!) { volumeCreate(input: $input) { id } }"""

VARIABLES_UPSERT = """
mutation($input: VariableCollectionUpsertInput!) {
  variableCollectionUpsert(input: $input)
}"""

INSTANCE_UPDATE = """
mutation($serviceId: String!, $environmentId: String!,
         $input: ServiceInstanceUpdateInput!) {
  serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId,
                        input: $input)
}"""

DOMAIN_CREATE = """
mutation($input: ServiceDomainCreateInput!) {
  serviceDomainCreate(input: $input) { domain }
}"""

REDEPLOY = """
mutation($serviceId: String!, $environmentId: String!) {
  serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId)
}"""

LATEST_DEPLOYMENT = """
query($input: DeploymentListInput!) {
  deployments(input: $input, first: 1) { edges { node { id status } } }
}"""

LOGS = """
query($deploymentId: String!, $limit: Int) {
  deploymentLogs(deploymentId: $deploymentId, limit: $limit) { message timestamp }
}"""

PROJECT_DELETE = """
mutation($id: String!) { projectDelete(id: $id) }"""


def instance_settings() -> Dict[str, Any]:
    """One replica, never asleep, no overlap between old and new deploys.

    An overlap would run two containers against the one volume for a moment:
    two copies of the item pool, and the later save wins.
    """
    return {
        "numReplicas": 1,
        "sleepApplication": False,
        "overlapSeconds": 0,
        "healthcheckPath": "/health",
        "healthcheckTimeout": 300,
        "restartPolicyType": "ALWAYS",
    }


class RailwayAPI:
    def __init__(self, token: str):
        self.http = RestAPI(GRAPHQL_API, token, provider="Railway",
                            token_page=TOKEN_PAGE)

    def run(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        result = self.http.request("POST", GRAPHQL_API,
                                   json={"query": query, "variables": variables or {}})
        if result.get("errors"):
            raise ProviderError(f"Railway: {result['errors'][0].get('message')}")
        return result.get("data") or {}


@register_provider
class RailwayProvider(Provider):
    """One Railway service with a volume."""

    name = "railway"
    summary = "Railway: image + volume on *.up.railway.app, usage-billed (~$10-20/mo)"
    public = True
    ephemeral_fs = False
    supports_logs = True
    supports_pull = True

    def verify_credential(self):
        me = RailwayAPI(self.token).run("query { me { email } }").get("me") or {}
        return me.get("email") or "token accepted"

    def _store(self, spec):
        from potato.deploy.bundle_store import store_for

        options = spec.extra.get("backup")
        return store_for(options) if options is not None else None

    # -- plan ----------------------------------------------------------

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        env = self.runtime_env(spec, spec.extra.get("generated"))
        store = self._store(spec)
        plan = DeployPlan(result_url_pattern="https://<service>.up.railway.app")
        plan.actions = [
            Action("railway.project", f"create the project potato-{spec.name}"),
            Action("state.persist", "record the project before anything else can fail"),
            Action("railway.service", f"create a service from "
                   f"{spec.image or DEFAULT_IMAGE}"),
            Action("railway.volume", "mount a volume at /app"),
            Action("bundle.publish",
                   f"upload the project to {store.describe() if store else '(nowhere; see REFUSED below)'}"),
            Action("railway.variables", "set variables, including RAILWAY_RUN_UID=0",
                   {"keys": sorted(set(env) | {"RAILWAY_RUN_UID", "PORT",
                                               "POTATO_BUNDLE_URL"})}),
            Action("railway.instance", "one replica, no sleep, no deploy overlap",
                   instance_settings()),
            Action("railway.domain", "generate a *.up.railway.app domain"),
            Action("wait.deploy", "wait for the deployment to succeed"),
        ]
        plan.warnings.append(
            "Railway bills by usage: RAM, CPU and volume per minute. A small task "
            "that is always on typically costs $10-20 a month.")
        if not bundle:
            plan.warnings.append("No bundle was built; this plan cannot run.")
        return plan

    # -- create --------------------------------------------------------

    def refusal(self, spec: DeploySpec, bundle) -> Optional[str]:
        return _NO_STORE if self._store(spec) is None else None

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        if bundle is None:
            raise ProviderError("No bundle was built; nothing to deploy.")
        refused = self.refusal(spec, bundle)
        if refused:
            raise ProviderError(refused)
        bundle_store = self._store(spec)

        api = RailwayAPI(self.token)
        record = existing or DeploymentRecord(name=spec.name, provider=self.name)
        record.spec.update({"config_path": os.path.abspath(spec.config_path)})
        ref = record.provider_ref

        if not ref.get("project_id"):
            record.status = "creating"
            store.upsert(record)
            project = api.run(PROJECT_CREATE, {"input": {
                "name": f"potato-{spec.name}",
                "description": "Potato annotation task"}})["projectCreate"]
            ref["project_id"] = project["id"]
            edges = (project.get("environments") or {}).get("edges") or []
            if not edges:
                raise ProviderError("Railway created the project with no environment.")
            ref["environment_id"] = edges[0]["node"]["id"]
            store.upsert(record)
        else:
            record.status = "updating"
            store.upsert(record)

        try:
            from potato.deploy.bundle_store import publish

            location = publish(bundle, bundle_store, spec.extra.get("bundle_workdir")
                               or bundle.bundle_dir + ".dist")
            variables = self.runtime_env(spec, spec.extra.get("generated"))
            variables.update(location.env())
            variables.update({"RAILWAY_RUN_UID": "0", "PORT": str(CONTAINER_PORT)})

            if not ref.get("service_id"):
                service = api.run(SERVICE_CREATE, {"input": {
                    "projectId": ref["project_id"],
                    "environmentId": ref["environment_id"],
                    "name": "potato",
                    "source": {"image": spec.image or DEFAULT_IMAGE},
                    "variables": variables}})["serviceCreate"]
                ref["service_id"] = service["id"]
                store.upsert(record)
                api.run(VOLUME_CREATE, {"input": {
                    "projectId": ref["project_id"],
                    "environmentId": ref["environment_id"],
                    "serviceId": ref["service_id"], "mountPath": "/app"}})
                api.run(INSTANCE_UPDATE, {"serviceId": ref["service_id"],
                                          "environmentId": ref["environment_id"],
                                          "input": instance_settings()})
                domain = api.run(DOMAIN_CREATE, {"input": {
                    "serviceId": ref["service_id"],
                    "environmentId": ref["environment_id"],
                    "targetPort": CONTAINER_PORT}})["serviceDomainCreate"]["domain"]
                record.url = f"https://{domain}"
                store.upsert(record)
            else:
                api.run(VARIABLES_UPSERT, {"input": {
                    "projectId": ref["project_id"],
                    "environmentId": ref["environment_id"],
                    "serviceId": ref["service_id"],
                    "variables": variables, "skipDeploys": True}})
            api.run(REDEPLOY, {"serviceId": ref["service_id"],
                               "environmentId": ref["environment_id"]})

            status = self._wait_for_deploy(api, record)
            record.bundle_sha = bundle.sha256()
            record.status = "running" if status == "SUCCESS" else "unhealthy"
        except Exception:
            record.status = "failed"
            store.upsert(record)
            raise
        store.upsert(record)
        if record.status != "running":
            raise ProviderError(f"The Railway deployment ended {status}. "
                                f"See `potato deploy logs --name {record.name}`.")
        self.console(f"Live at {record.url}")
        return record

    def _latest(self, api: RailwayAPI, record) -> Dict[str, Any]:
        ref = record.provider_ref
        edges = api.run(LATEST_DEPLOYMENT, {"input": {
            "projectId": ref["project_id"], "serviceId": ref["service_id"],
            "environmentId": ref["environment_id"]}}).get("deployments", {}).get("edges")
        return (edges or [{}])[0].get("node") or {}

    def _wait_for_deploy(self, api: RailwayAPI, record, timeout: int = 1200) -> str:
        deadline = time.time() + timeout
        status = "UNKNOWN"
        while time.time() < deadline:
            status = self._latest(api, record).get("status") or status
            if status == "SUCCESS" or status in FAILED_STATES:
                return status
            time.sleep(10)
        return status

    # -- status / logs / pull / destroy --------------------------------

    def status(self, record) -> DeploymentStatus:
        if not record.provider_ref.get("service_id"):
            return DeploymentStatus(state="unknown", detail="no service recorded")
        latest = self._latest(RailwayAPI(self.token), record)
        status = latest.get("status", "UNKNOWN")
        return DeploymentStatus(state="running" if status == "SUCCESS" else status.lower(),
                                url=record.url, healthy=status == "SUCCESS", raw=latest)

    def logs(self, record, *, lines: int = 200, follow: bool = False):
        api = RailwayAPI(self.token)
        deployment = self._latest(api, record).get("id")
        if not deployment:
            raise ProviderError("No deployment found.")
        for entry in api.run(LOGS, {"deploymentId": deployment,
                                    "limit": lines}).get("deploymentLogs") or []:
            yield f"{entry.get('timestamp', '')} {entry.get('message', '')}"

    def pull(self, record, dest: str) -> PullResult:
        from potato.deploy.providers.render import _admin_key
        from potato.deploy.pull import pull_over_https

        admin_key = _admin_key(record)
        if not admin_key:
            raise ProviderError("No admin key in .potato/secrets.json; cannot pull.")
        return pull_over_https(record.url, admin_key, dest, console=self.console)

    def destroy(self, record, *, keep_data: bool = False) -> None:
        project = record.provider_ref.get("project_id")
        if not project:
            return
        if keep_data:
            self.console("Deleting a Railway project deletes its volume; "
                         "--keep-data cannot keep it. Pull first.")
        RailwayAPI(self.token).run(PROJECT_DELETE, {"id": project})
        self.console(f"Deleted the Railway project {project}")


_NO_STORE = (
    "Railway runs the published image and fetches your project into it at start, "
    "so the project has to be uploaded somewhere first. It goes to the backup's "
    "storage, so --demo is not an option here: pass --backup hf --hf-token <token> or --backup s3 --s3-bucket "
    "<bucket>.")

"""Deploy a Potato task to ECS Express Mode (``--provider aws-ecs``).

The managed AWS option: no server to patch, a real HTTPS URL on
``*.ecs.<region>.on.aws`` with an AWS-managed certificate, and AWS runs the
load balancer. It is also the most expensive target here (Fargate task, ALB and
their IPv4 addresses come to roughly $45-70 a month) and the most constrained:

* **No volume.** The Express API (CreateExpressGatewayService) takes one
  container and nothing else; there is no field for EFS or a task definition.
  The task's disk is gone whenever the task is replaced, so, as on Heroku, an
  off-host backup with restore-on-boot is required.
* **Deploys overlap by design.** Express performs a rolling, zero-downtime
  replacement, so for a moment two tasks run. Each would restore and back up
  on its own, and the later write wins. After creating the service this module
  switches its deployment to stop-then-start (``maximumPercent`` 100,
  ``minimumHealthyPercent`` 0) and reads the setting back. Every redeploy
  checks it again and refuses if Express has reverted it, rather than letting
  two copies of the study race.

Secrets go to SSM Parameter Store as SecureStrings and reach the container as
ECS ``secrets``, never as plain environment variables.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Iterator, List, Optional

from potato.deploy.providers.aws._aws import (
    AWSClient,
    caller_identity,
    is_not_found,
    wait_until,
)
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

DEFAULT_REGION = "us-east-1"
from potato.deploy.image import DEFAULT_IMAGE  # noqa: E402
CPU = "512"
MEMORY = "1024"
CONTAINER_PORT = 7860

EXECUTION_ROLE = "potato-ecs-task-execution"
INFRASTRUCTURE_ROLE = "potato-ecs-express-infrastructure"
EXECUTION_POLICY = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
INFRASTRUCTURE_POLICY = ("arn:aws:iam::aws:policy/service-role/"
                         "AmazonECSInfrastructureRoleforExpressGatewayServices")

#: Values that travel as SSM SecureStrings rather than plain environment.
SECRET_KEYS = ("POTATO_SECRET_KEY", "POTATO_ADMIN_API_KEY", "HF_TOKEN",
               "POTATO_BUNDLE_TOKEN", "POTATO_S3_ACCESS_KEY_ID",
               "POTATO_S3_SECRET_ACCESS_KEY")

# us-east-1, USD/month: 0.5 vCPU / 1 GB Fargate, one ALB with light traffic, and
# the public IPv4 addresses the task and the ALB use. Estimated.
ESTIMATED_MONTHLY = 18.0 + 18.0 + 11.0

STOP_THEN_START = {"strategy": "ROLLING", "maximumPercent": 100,
                   "minimumHealthyPercent": 0}


def trust_policy(service: str) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": service},
        "Action": "sts:AssumeRole"}]})


def parameter_path(deployment: str, key: str) -> str:
    return f"/potato/{deployment}/{key}"


def express_request(spec: DeploySpec, *, execution_role: str, infrastructure_role: str,
                    env: Dict[str, str], secrets: Dict[str, str], log_group: str,
                    image: str) -> Dict[str, Any]:
    """The CreateExpressGatewayService call. ``secrets`` maps names to SSM ARNs."""
    return {
        "serviceName": f"potato-{spec.name}",
        "executionRoleArn": execution_role,
        "infrastructureRoleArn": infrastructure_role,
        "healthCheckPath": "/health",
        "cpu": CPU,
        "memory": MEMORY,
        "primaryContainer": {
            "image": image,
            "containerPort": CONTAINER_PORT,
            "environment": [{"name": k, "value": v} for k, v in sorted(env.items())],
            "secrets": [{"name": k, "valueFrom": v} for k, v in sorted(secrets.items())],
            "awsLogsConfiguration": {"logGroup": log_group,
                                     "logStreamPrefix": "potato"},
        },
        # Exactly one task. Potato's item pool and user state live in one
        # process; a second task would be a second, diverging copy.
        "scalingTarget": {"minTaskCount": 1, "maxTaskCount": 1},
        "tags": [{"key": "potato", "value": spec.name}],
    }


@register_provider
class ECSExpressProvider(Provider):
    """ECS Express Mode on Fargate, with backup-and-restore for its disk."""

    ignored_flags = ("size", "volume_gb", "domain")
    name = "aws-ecs"
    summary = ("AWS ECS Express Mode: managed HTTPS, no server, ~$45-70/mo; "
               "ephemeral disk, so it needs --backup")
    requires = ("boto3",)
    install_extra = "deploy-aws"
    public = True
    ephemeral_fs = True
    supports_logs = True
    supports_pull = True

    def __init__(self, token: Optional[str] = None, console=None):
        super().__init__(token=token, console=console)
        self.profile: Optional[str] = None
        self._clients: Dict[str, AWSClient] = {}

    def _client(self, service: str, region: str) -> AWSClient:
        key = f"{service}:{region}"
        if key not in self._clients:
            self._clients[key] = AWSClient(
                service, region=region,
                profile=self.profile or os.environ.get("AWS_PROFILE"))
        return self._clients[key]

    def verify_credential(self):
        return caller_identity(self.profile or os.environ.get("AWS_PROFILE"))

    # -- plan ----------------------------------------------------------

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        region = spec.region or DEFAULT_REGION
        env, secrets = self._split_env(spec)
        plan = DeployPlan(result_url_pattern=f"https://<id>.ecs.{region}.on.aws",
                          estimated_cost_usd_month=ESTIMATED_MONTHLY)
        plan.actions = [
            Action("aws.identity", "confirm the credentials with sts:GetCallerIdentity"),
            Action("iam.roles", f"create or reuse {EXECUTION_ROLE} and "
                   f"{INFRASTRUCTURE_ROLE}"),
            Action("ssm.secrets", "store secrets as SecureString parameters",
                   {"paths": [parameter_path(spec.name, k) for k in sorted(secrets)]}),
            Action("bundle.publish", "upload the project to the backup's storage"),
            Action("logs.group", f"create the log group /potato/{spec.name}"),
            Action("ecs.express", "create the Express service, one 0.5 vCPU / 1 GB task",
                   express_request(spec, execution_role="<role>",
                                   infrastructure_role="<role>",
                                   env={k: "…" for k in env},
                                   secrets={k: "<ssm-arn>" for k in secrets},
                                   log_group=f"/potato/{spec.name}",
                                   image=spec.image or DEFAULT_IMAGE)),
            Action("state.persist", "record the service before anything else can fail"),
            Action("ecs.deployment", "switch deploys to stop-then-start and verify it",
                   STOP_THEN_START),
            Action("wait.http", "poll the service URL until it answers"),
        ]
        plan.warnings.append(
            "ECS Express is the most expensive target here. If you do not need a "
            "managed service, --provider aws (Lightsail) is $12/mo.")
        if not bundle:
            plan.warnings.append("No bundle was built; this plan cannot run.")
        return plan

    def _split_env(self, spec: DeploySpec):
        env = self.runtime_env(spec, spec.extra.get("generated"))
        secrets = {k: v for k, v in env.items() if k in SECRET_KEYS or k in spec.secrets}
        return {k: v for k, v in env.items() if k not in secrets}, secrets

    # -- create --------------------------------------------------------

    def _bundle_store(self, spec: DeploySpec):
        from potato.deploy.bundle_store import store_for

        options = spec.extra.get("backup")
        return store_for(options) if options is not None else None

    def refusal(self, spec: DeploySpec, bundle) -> Optional[str]:
        if not spec.extra.get("backup_kinds") or self._bundle_store(spec) is None:
            return _NO_BACKUP
        return None

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        refused = self.refusal(spec, bundle)
        if refused:
            raise ProviderError(refused)
        if bundle is None:
            raise ProviderError("No bundle was built; nothing to deploy.")
        from potato.deploy.bundle_store import publish

        bundle_store = self._bundle_store(spec)

        self.profile = spec.extra.get("aws_profile") or self.profile
        region = spec.region or DEFAULT_REGION
        caller_identity(self.profile or os.environ.get("AWS_PROFILE"))
        ecs = self._client("ecs", region)

        record = existing or DeploymentRecord(name=spec.name, provider=self.name)
        record.spec.update({"config_path": os.path.abspath(spec.config_path)})
        ref = record.provider_ref
        ref["region"] = region
        if self.profile:
            ref["aws_profile"] = self.profile

        if ref.get("service_arn"):
            self._require_stop_then_start(ecs, ref)

        record.status = "updating" if ref.get("service_arn") else "creating"
        store.upsert(record)
        try:
            execution_role, infrastructure_role = self._roles(spec.name, region)
            location = publish(bundle, bundle_store, spec.extra.get("bundle_workdir")
                               or bundle.bundle_dir + ".dist")
            env, secrets = self._split_env(spec)
            bundle_env = location.env()
            token = bundle_env.pop("POTATO_BUNDLE_TOKEN", None)
            env.update(bundle_env)
            if token:
                secrets["POTATO_BUNDLE_TOKEN"] = token
            secret_arns = self._store_secrets(spec.name, region, secrets)
            ref["parameters"] = sorted(secret_arns.values())
            log_group = f"/potato/{spec.name}"
            self._log_group(region, log_group)
            ref["log_group"] = log_group
            store.upsert(record)

            request = express_request(
                spec, execution_role=execution_role,
                infrastructure_role=infrastructure_role, env=env, secrets=secret_arns,
                log_group=log_group, image=spec.image or DEFAULT_IMAGE)

            if ref.get("service_arn"):
                update = {k: v for k, v in request.items()
                          if k not in ("serviceName", "infrastructureRoleArn", "tags")}
                ecs.call("update_express_gateway_service",
                         serviceArn=ref["service_arn"], **update)
            else:
                created = ecs.call("create_express_gateway_service", **request)["service"]
                # Before anything else can fail: a service with an ALB bills hourly.
                ref["service_arn"] = created["serviceArn"]
                ref["cluster"] = created.get("cluster")
                ref["service_name"] = created.get("serviceName")
                store.upsert(record)
                self._make_stop_then_start(ecs, ref)

            record.url = self._wait_for_url(ecs, ref)
            store.upsert(record)
            healthy = _healthy(record.url, timeout=900)
            record.bundle_sha = bundle.sha256()
            record.status = "running" if healthy else "unhealthy"
        except Exception:
            record.status = "failed"
            store.upsert(record)
            raise
        store.upsert(record)
        if record.status != "running":
            raise ProviderError(f"{record.url} never answered. See `" + deploy_command(
                "logs", record.spec.get("config_path"), record.name) + "`.")
        self.console(f"Live at {record.url}")
        return record

    def _roles(self, deployment: str, region: str):
        iam = self._client("iam", region)
        execution = self._role(iam, EXECUTION_ROLE, "ecs-tasks.amazonaws.com",
                               EXECUTION_POLICY)
        # The execution role reads this deployment's parameters, and no others.
        account = execution.split(":")[4]
        iam.call("put_role_policy", RoleName=EXECUTION_ROLE,
                 PolicyName=f"potato-{deployment}-parameters",
                 PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [{
                     "Effect": "Allow", "Action": ["ssm:GetParameters"],
                     "Resource": f"arn:aws:ssm:{region}:{account}:parameter"
                                 f"{parameter_path(deployment, '*')}"}]}))
        infrastructure = self._role(iam, INFRASTRUCTURE_ROLE, "ecs.amazonaws.com",
                                    INFRASTRUCTURE_POLICY)
        return execution, infrastructure

    def _role(self, iam: AWSClient, name: str, service: str, policy: str) -> str:
        try:
            return iam.call("get_role", RoleName=name)["Role"]["Arn"]
        except ProviderError as exc:
            if not is_not_found(exc.__cause__ or exc):
                raise
        self.console(f"Creating the IAM role {name}...")
        arn = iam.call("create_role", RoleName=name,
                       AssumeRolePolicyDocument=trust_policy(service),
                       Description="Created by potato deploy",
                       Tags=[{"Key": "potato", "Value": "deploy"}])["Role"]["Arn"]
        iam.call("attach_role_policy", RoleName=name, PolicyArn=policy)
        time.sleep(10)   # IAM is eventually consistent; ECS rejects a role it cannot see yet
        return arn

    def _store_secrets(self, deployment: str, region: str,
                       secrets: Dict[str, str]) -> Dict[str, str]:
        ssm = self._client("ssm", region)
        arns = {}
        for key, value in sorted(secrets.items()):
            name = parameter_path(deployment, key)
            ssm.call("put_parameter", Name=name, Value=str(value), Type="SecureString",
                     Overwrite=True)
            arns[key] = ssm.call("get_parameter", Name=name)["Parameter"]["ARN"]
        return arns

    def _log_group(self, region: str, name: str) -> None:
        logs = self._client("logs", region)
        try:
            logs.call("create_log_group", logGroupName=name)
            logs.call("put_retention_policy", logGroupName=name, retentionInDays=30)
        except ProviderError as exc:
            if "ResourceAlreadyExists" not in str(exc):
                raise

    def _make_stop_then_start(self, ecs: AWSClient, ref: Dict[str, Any]) -> None:
        try:
            ecs.call("update_service", cluster=ref["cluster"],
                     service=ref["service_name"],
                     deploymentConfiguration=dict(STOP_THEN_START))
        except ProviderError as exc:
            raise ProviderError(
                f"ECS would not switch this service to stop-then-start deploys "
                f"({exc}). The service exists and is recorded; remove it with "
                "`potato deploy destroy`, and use --provider aws instead.") from exc
        self._require_stop_then_start(ecs, ref)

    def _require_stop_then_start(self, ecs: AWSClient, ref: Dict[str, Any]) -> None:
        services = ecs.call("describe_services", cluster=ref["cluster"],
                            services=[ref["service_name"]]).get("services") or []
        configuration = (services[0].get("deploymentConfiguration") or {}) if services else {}
        if configuration.get("maximumPercent") != 100:
            raise ProviderError(
                "This ECS service would start a new task before stopping the old "
                f"one (deploymentConfiguration is {configuration or 'unknown'}). Two "
                "tasks would each restore and back up the study, and the later write "
                "would win. Refusing to deploy. Destroy and recreate, or use "
                "--provider aws.")

    def _wait_for_url(self, ecs: AWSClient, ref: Dict[str, Any]) -> str:
        found = {}

        def ready() -> bool:
            service = ecs.call("describe_express_gateway_service",
                               serviceArn=ref["service_arn"]).get("service") or {}
            for configuration in service.get("activeConfigurations") or []:
                for path in configuration.get("ingressPaths") or []:
                    if path.get("accessType") == "PUBLIC" and path.get("endpoint"):
                        found["url"] = path["endpoint"]
                        return True
            return False

        if not wait_until(ready, timeout=900, interval=10):
            raise ProviderError("The Express service never reported a public URL.")
        url = found["url"]
        return url if url.startswith("http") else f"https://{url}"

    # -- status / logs / pull / destroy --------------------------------

    def _bind(self, record) -> AWSClient:
        self.profile = self.profile or record.provider_ref.get("aws_profile")
        return self._client("ecs", record.provider_ref.get("region") or DEFAULT_REGION)

    def status(self, record) -> DeploymentStatus:
        ecs = self._bind(record)
        arn = record.provider_ref.get("service_arn")
        if not arn:
            return DeploymentStatus(state="unknown", detail="no service recorded")
        try:
            service = ecs.call("describe_express_gateway_service",
                               serviceArn=arn).get("service") or {}
        except ProviderError as exc:
            if is_not_found(exc.__cause__ or exc):
                return DeploymentStatus(state="absent", url=record.url)
            raise
        code = (service.get("status") or {}).get("statusCode", "UNKNOWN")
        if code != "ACTIVE":
            return DeploymentStatus(state=code.lower(), url=record.url, raw=service)
        healthy = _healthy(record.url, timeout=20)
        return DeploymentStatus(state="running" if healthy else "unhealthy",
                                url=record.url, healthy=healthy)

    def logs(self, record, *, lines: int = 200, follow: bool = False) -> Iterator[str]:
        self._bind(record)
        logs = self._client("logs", record.provider_ref.get("region") or DEFAULT_REGION)
        events = logs.call("filter_log_events",
                           logGroupName=record.provider_ref["log_group"],
                           limit=lines).get("events") or []
        for event in events[-lines:]:
            yield event.get("message", "").rstrip()

    def pull(self, record, dest: str) -> PullResult:
        from potato.deploy.providers.render import _admin_key
        from potato.deploy.pull import pull_over_https

        admin_key = _admin_key(record)
        if not admin_key:
            raise ProviderError("No admin key in .potato/secrets.json; the backup "
                                "holds the same data.")
        return pull_over_https(record.url, admin_key, dest, console=self.console)

    def destroy(self, record, *, keep_data: bool = False) -> None:
        ecs = self._bind(record)
        region = record.provider_ref.get("region") or DEFAULT_REGION
        arn = record.provider_ref.get("service_arn")
        if arn:
            try:
                ecs.call("delete_express_gateway_service", serviceArn=arn)
                self.console("Deleted the Express service (and its load balancer)")
            except ProviderError as exc:
                if not is_not_found(exc.__cause__ or exc):
                    raise
        ssm = self._client("ssm", region)
        # Every parameter `up` stored, not just the built-in keys: each --secret
        # KEY=... was left behind in SSM as a SecureString.
        names = {parameter_path(record.name, k) for k in SECRET_KEYS}
        names |= {arn.split(":parameter", 1)[1]
                  for arn in record.provider_ref.get("parameters") or []
                  if ":parameter" in arn}
        ordered = sorted(names)
        for start in range(0, len(ordered), 10):     # the API takes ten at a time
            ssm.call("delete_parameters", Names=ordered[start:start + 10])
        self.console("Deleted the deployment's SSM parameters")
        if record.provider_ref.get("log_group"):
            try:
                self._client("logs", region).call(
                    "delete_log_group", logGroupName=record.provider_ref["log_group"])
            except ProviderError:
                pass
        self.console("The IAM roles are shared by every potato ECS deployment and are "
                     "left in place. The backup is not touched.")


_NO_BACKUP = (
    "Refusing to deploy to ECS Express with nowhere to keep the annotations. The "
    "Express API offers no volume, so the task's disk is gone whenever the task "
    "is replaced. The backup's storage is also where your project is uploaded "
    "for the task to fetch, so --demo is not an option here.\n"
    "Pick one:\n"
    "  --backup hf --hf-token <token>   back up to a HuggingFace dataset\n"
    "  --backup s3 --s3-bucket <name>   back up to an S3 bucket")


def _healthy(url: str, timeout: int) -> bool:
    import requests

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"{url}/health", timeout=10).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(10)
    return False

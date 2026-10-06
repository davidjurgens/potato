"""Deploy a Potato task to an AWS Lightsail instance (``--provider aws``).

The AWS target to recommend. A Lightsail bundle has a flat monthly price that
already includes a public IPv4 address, an SSD and data transfer, which EC2
bills separately, and the permissions it needs are ``lightsail:*`` plus
``sts:GetCallerIdentity`` — no VPC, no security groups, no IAM roles. New AWS
accounts get $100-200 of credit, which covers months of the 2 GB bundle.

The machine half is ``vm_base.VMProvider``: SSH, cloud-init, Caddy with a
Let's Encrypt certificate for the static IP. This module is the Lightsail API.

The deploy key travels in cloud-init (``ssh_authorized_keys``) rather than
through Lightsail's key-pair API, so nothing depends on which key types that
API accepts; the instance is created without a key pair of ours.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from potato.deploy.providers.aws._aws import (
    AWSClient,
    caller_identity,
    is_not_found,
    wait_until,
)
from potato.deploy.providers.base import (
    Action,
    DeploySpec,
    ProviderError,
    register_provider,
)
from potato.deploy.providers.vm_base import PUBLIC_PORTS, VMProvider

DEFAULT_REGION = "us-east-1"
DEFAULT_BUNDLE = "small_3_0"
BLUEPRINT = "ubuntu_24_04"

# Monthly USD, IPv4 included (the *_ipv6_* bundles are cheaper and cannot get
# an IP certificate for an IPv4 address, so they are not offered). Shown before
# the confirmation prompt; `create` checks the bundle is still sold.
BUNDLE_PRICES = {
    "nano_3_0": 5.0,
    "micro_3_0": 7.0,
    "small_3_0": 12.0,
    "medium_3_0": 24.0,
    "large_3_0": 44.0,
    "xlarge_3_0": 84.0,
    "2xlarge_3_0": 164.0,
}
BUNDLE_MEMORY_MB = {
    "nano_3_0": 512,
    "micro_3_0": 1024,
    "small_3_0": 2048,
    "medium_3_0": 4096,
    "large_3_0": 8192,
    "xlarge_3_0": 16384,
    "2xlarge_3_0": 32768,
}
DISK_PRICE_PER_GB = 0.10

# Lightsail asks for a device path; Nitro instances expose the disk as NVMe
# regardless, so the volume script tries both.
DISK_PATH = "/dev/xvdf"
DISK_CANDIDATES = [DISK_PATH, "/dev/nvme1n1"]


def names(deployment: str) -> Dict[str, str]:
    base = f"potato-{deployment}"
    return {"instance": base, "static_ip": f"{base}-ip", "disk": f"{base}-data"}


def instance_request(spec: DeploySpec, *, region: str, bundle: str,
                     user_data: str) -> Dict[str, Any]:
    """The CreateInstances call. Pure, so a test can assert it exactly."""
    return {
        "instanceNames": [names(spec.name)["instance"]],
        "availabilityZone": f"{region}a",
        "blueprintId": BLUEPRINT,
        "bundleId": bundle,
        "userData": user_data,
        "tags": [{"key": "potato", "value": spec.name}],
    }


def port_request(instance_name: str) -> Dict[str, Any]:
    """Inbound 22/80/443 only. PutInstancePublicPorts replaces the whole set,
    which closes anything Lightsail opened by default."""
    return {
        "instanceName": instance_name,
        "portInfos": [{"fromPort": port, "toPort": port, "protocol": "tcp"}
                      for port in PUBLIC_PORTS],
    }


@register_provider
class LightsailProvider(VMProvider):
    """A Lightsail instance running the published image behind Caddy."""

    name = "aws"
    summary = ("AWS Lightsail: one VM, flat $12/mo for 2 GB with IPv4 and disk; "
               "the recommended AWS target")
    requires = ("boto3", "paramiko")
    install_extra = "deploy-aws"
    ssh_user = "ubuntu"
    server_noun = "instance"
    server_id_key = "instance_name"
    default_region = DEFAULT_REGION
    default_size = DEFAULT_BUNDLE
    user_data_limit = 16 * 1024
    console_name = "the Lightsail console (https://lightsail.aws.amazon.com)"

    def __init__(self, token: Optional[str] = None, console=None):
        super().__init__(token=token, console=console)
        self.profile: Optional[str] = None

    # -- credentials ---------------------------------------------------

    def verify_credential(self):
        return caller_identity(self.profile or os.environ.get("AWS_PROFILE"))

    def _api(self, region: Optional[str] = None) -> AWSClient:
        return AWSClient("lightsail", region=region or DEFAULT_REGION,
                         profile=self.profile or os.environ.get("AWS_PROFILE"))

    def _bind(self, record) -> None:
        self.profile = self.profile or record.provider_ref.get("aws_profile")

    # -- pricing -------------------------------------------------------

    def memory_mb(self, size: str) -> Optional[int]:
        return BUNDLE_MEMORY_MB.get(size)

    def estimate_cost(self, size: str, volume_gb: Optional[int]) -> Optional[float]:
        if size not in BUNDLE_PRICES:
            return None
        return BUNDLE_PRICES[size] + (float(volume_gb) * DISK_PRICE_PER_GB
                                      if volume_gb else 0.0)

    def volume_device_hint(self, spec: DeploySpec) -> str:
        return DISK_PATH

    # -- plan ----------------------------------------------------------

    def _provider_actions(self, spec: DeploySpec, *, region: str, size: str,
                          user_data: str) -> List[Action]:
        n = names(spec.name)
        actions = [
            Action("aws.identity", "confirm the credentials with sts:GetCallerIdentity"),
            Action("ssh.keygen", "generate an ed25519 deploy key, delivered by cloud-init"),
            Action("lightsail.bundles", f"check that bundle {size} is still sold"),
        ]
        if spec.volume_gb:
            actions.append(Action(
                "lightsail.disk", f"create a {spec.volume_gb} GB disk {n['disk']}",
                {"diskName": n["disk"], "availabilityZone": f"{region}a",
                 "sizeInGb": spec.volume_gb}))
        request = instance_request(spec, region=region, bundle=size,
                                   user_data="<cloud-init>")
        actions += [
            Action("lightsail.instance",
                   f"create {n['instance']} ({size}, {BLUEPRINT}) in {region}a",
                   request),
            Action("state.persist", "record the instance name before anything else can fail"),
            Action("wait.active", "poll until the instance is running"),
            Action("lightsail.static_ip",
                   f"allocate {n['static_ip']} and attach it, so the address and its "
                   "certificate survive a stop/start"),
            Action("lightsail.ports", "open 22/80/443 only; never 8000",
                   port_request(n["instance"])),
        ]
        if spec.volume_gb:
            actions.append(Action("lightsail.attach_disk",
                                  f"attach {n['disk']} at {DISK_PATH}"))
        return actions

    # -- create --------------------------------------------------------

    def create(self, spec: DeploySpec, bundle, existing, store):
        self.profile = spec.extra.get("aws_profile") or self.profile
        if existing is not None:
            self._bind(existing)
        return super().create(spec, bundle, existing, store)

    def _check_account(self, api) -> None:
        caller_identity(self.profile or os.environ.get("AWS_PROFILE"))

    def _create_infrastructure(self, api, spec, record, store, *, region, size,
                               public_key, user_data_for: Callable) -> str:
        n = names(spec.name)
        if self.profile:
            record.provider_ref["aws_profile"] = self.profile
        self._check_bundle(api, size)

        if spec.volume_gb:
            self.console(f"Creating a {spec.volume_gb} GB disk...")
            api.call("create_disk", diskName=n["disk"],
                     availabilityZone=f"{region}a", sizeInGb=int(spec.volume_gb),
                     tags=[{"key": "potato", "value": spec.name}])
            record.provider_ref["disk_name"] = n["disk"]
            record.provider_ref["volume_devices"] = list(DISK_CANDIDATES)
            store.upsert(record)

        user_data = user_data_for(DISK_PATH if spec.volume_gb else None)
        self.console(f"Creating a {size} Lightsail instance in {region}a...")
        api.call("create_instances", **instance_request(
            spec, region=region, bundle=size, user_data=user_data))
        # Before anything else can fail: an instance nobody recorded bills forever.
        record.provider_ref["instance_name"] = n["instance"]
        store.upsert(record)

        self.console("Waiting for the instance to start...")
        if not wait_until(lambda: self._instance_state(api, n["instance"]) == "running",
                          timeout=600, interval=5):
            raise ProviderError(
                f"{n['instance']} did not reach running within 10 minutes. It is "
                "recorded, so `potato deploy destroy` can still remove it.")

        api.call("allocate_static_ip", staticIpName=n["static_ip"])
        record.provider_ref["static_ip_name"] = n["static_ip"]
        store.upsert(record)
        api.call("attach_static_ip", staticIpName=n["static_ip"],
                 instanceName=n["instance"])
        api.call("put_instance_public_ports", **port_request(n["instance"]))

        if spec.volume_gb:
            self.console("Attaching the disk...")
            if not wait_until(lambda: self._disk_state(api, n["disk"]) == "available",
                              timeout=300, interval=5):
                raise ProviderError(f"The disk {n['disk']} never became available.")
            api.call("attach_disk", diskName=n["disk"], instanceName=n["instance"],
                     diskPath=DISK_PATH)

        address = api.call("get_static_ip", staticIpName=n["static_ip"])
        ip = (address.get("staticIp") or {}).get("ipAddress")
        if not ip:
            raise ProviderError(f"The static IP {n['static_ip']} has no address.")
        return ip

    def _check_bundle(self, api, size: str) -> None:
        bundles = api.call("get_bundles").get("bundles") or []
        active = {b.get("bundleId") for b in bundles if b.get("isActive", True)}
        if active and size not in active:
            linux = sorted(b for b in active if b and b.endswith("_3_0"))
            raise ProviderError(
                f"Lightsail does not sell bundle {size!r} here. Pass --size with "
                f"one of: {', '.join(linux) or ', '.join(sorted(active))}")

    def _instance_state(self, api, name: str) -> Optional[str]:
        try:
            instance = api.call("get_instance", instanceName=name).get("instance") or {}
        except ProviderError as exc:
            if is_not_found(exc.__cause__ or exc):
                return None
            raise
        return (instance.get("state") or {}).get("name")

    def _disk_state(self, api, name: str) -> Optional[str]:
        disk = api.call("get_disk", diskName=name).get("disk") or {}
        return disk.get("state")

    # -- status / destroy ----------------------------------------------

    def status(self, record):
        self._bind(record)
        return super().status(record)

    def logs(self, record, **kwargs):
        self._bind(record)
        return super().logs(record, **kwargs)

    def pull(self, record, dest: str):
        self._bind(record)
        return super().pull(record, dest)

    def destroy(self, record, *, keep_data: bool = False) -> None:
        self._bind(record)
        super().destroy(record, keep_data=keep_data)

    def _server_state(self, api, record) -> Tuple[str, Dict[str, Any]]:
        state = self._instance_state(api, record.provider_ref["instance_name"])
        if state is None:
            return "absent", {}
        return ("active" if state == "running" else state), {"state": state}

    def _destroy_infrastructure(self, api, record, *, keep_data: bool) -> None:
        """Instance first (it holds the disk and the IP), then the IP, then the disk.

        A released static IP stops billing; an unattached one bills, so it is
        never left behind. Every step tolerates a missing resource.
        """
        reference = record.provider_ref
        instance = reference.get("instance_name")
        if instance:
            self._ignore_missing(lambda: api.call(
                "delete_instance", instanceName=instance, forceDeleteAddOns=True))
            self.console(f"Deleted instance {instance}")

        static_ip = reference.get("static_ip_name")
        if static_ip:
            self._ignore_missing(lambda: api.call("release_static_ip",
                                                  staticIpName=static_ip))
            self.console(f"Released static IP {static_ip}")

        disk = reference.get("disk_name")
        if disk and keep_data:
            self.console(f"Kept disk {disk}; it bills ${DISK_PRICE_PER_GB:.2f}/GB "
                         "per month until deleted in the Lightsail console.")
        elif disk:
            # Detaching lags the instance delete.
            def gone() -> bool:
                try:
                    api.call("delete_disk", diskName=disk, forceDeleteAddOns=True)
                    return True
                except ProviderError as exc:
                    return is_not_found(exc.__cause__ or exc)
            if wait_until(gone, timeout=120, interval=10):
                self.console(f"Deleted disk {disk}")
            else:
                self.console(f"Disk {disk} could not be deleted (still attached?). "
                             "It bills until removed in the Lightsail console.")

    @staticmethod
    def _ignore_missing(action) -> None:
        try:
            action()
        except ProviderError as exc:
            if not is_not_found(exc.__cause__ or exc):
                raise

"""Deploy a Potato task to an OpenStack cloud (``--provider openstack``).

The point of this provider is Jetstream2: NSF ACCESS allocations make it free
for US researchers, and every instance gets a real DNS name, so the
certificate is an ordinary 90-day one rather than an IP certificate. The same
code covers campus OpenStack clouds and EGI's federated cloud, which fall back
to an IP certificate.

Credentials are OpenStack's own: a ``clouds.yaml`` entry named with ``--cloud``
(or ``OS_CLOUD``), or ``OS_*`` application-credential variables. Nothing
leaves the machine except through openstacksdk.

Images differ in their default login (ubuntu, exouser, cloud-user), so
cloud-init creates a ``potato-deploy`` sudo user holding the deploy key and
SSH uses that.
"""

from __future__ import annotations

import base64
import os
import re
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from potato.deploy.providers.base import (
    Action,
    DeploySpec,
    ProviderError,
    register_provider,
)
from potato.deploy.providers.vm_base import PUBLIC_PORTS, VMProvider

INSTALL_HINT = "pip install 'potato-annotation[deploy-openstack]'"
DEPLOY_USER = "potato-deploy"


@dataclass(frozen=True)
class CloudPreset:
    """Defaults for a known cloud. Anything here can be overridden by flags."""

    flavor: str
    image: str
    external_network: str
    hostname: Optional[str] = None   # format with name=, project=


PRESETS: Dict[str, CloudPreset] = {
    "jetstream2": CloudPreset(
        flavor="m3.small", image="Featured-Ubuntu24", external_network="public",
        hostname="{name}.{project}.projects.jetstream-cloud.org"),
}
#: vCPUs per Jetstream2 CPU flavor; each vCPU-hour costs one SU.
JETSTREAM2_VCPUS = {"m3.tiny": 1, "m3.small": 2, "m3.quad": 4, "m3.medium": 8,
                    "m3.large": 16, "m3.xl": 32, "m3.2xl": 64}

GENERIC = CloudPreset(flavor="m1.small", image="Ubuntu 24.04", external_network="public")

VOLUME_DEVICES = ["/dev/sdb", "/dev/vdb"]


def dns_label(value: str) -> str:
    label = re.sub(r"[^a-z0-9-]", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", label)[:63]


def preset_for(cloud: Optional[str]) -> CloudPreset:
    return PRESETS.get((cloud or "").lower(), GENERIC)


def security_rules() -> List[Dict[str, Any]]:
    return [{"direction": "ingress", "ethertype": ethertype, "protocol": "tcp",
             "port_range_min": port, "port_range_max": port,
             "remote_ip_prefix": prefix}
            for port in PUBLIC_PORTS
            for ethertype, prefix in (("IPv4", "0.0.0.0/0"), ("IPv6", "::/0"))]


def connect(cloud: Optional[str], region: Optional[str] = None):
    try:
        import openstack
    except ImportError as exc:
        raise ProviderError(f"The openstack provider needs openstacksdk: {INSTALL_HINT}") from exc
    try:
        return openstack.connect(cloud=cloud or os.environ.get("OS_CLOUD"),
                                 region_name=region)
    except Exception as exc:
        raise ProviderError(
            f"Could not authenticate to OpenStack ({exc}). Pass --cloud with a "
            "clouds.yaml entry, or source an application-credential openrc file. "
            "Jetstream2: https://docs.jetstream-cloud.org/ui/cli/auth/") from exc


@register_provider
class OpenStackProvider(VMProvider):
    """One OpenStack server with a floating IP, behind Caddy."""

    name = "openstack"
    summary = ("OpenStack (Jetstream2, campus clouds): free with an allocation; "
               "real hostname on Jetstream2")
    requires = ("openstack", "paramiko")
    install_extra = "deploy-openstack"
    ssh_user = DEPLOY_USER
    deploy_user = DEPLOY_USER
    server_noun = "server"
    server_id_key = "server_id"
    user_data_limit = 64 * 1024
    console_name = "the cloud's Horizon or Exosphere console"

    def __init__(self, token: Optional[str] = None, console=None):
        super().__init__(token=token, console=console)
        self.cloud: Optional[str] = None
        self._conn = None

    @property
    def default_size(self) -> str:   # type: ignore[override]
        return preset_for(self.cloud).flavor

    def verify_credential(self):
        conn = connect(self.cloud or os.environ.get("OS_CLOUD"))
        project = getattr(conn, "current_project", None)
        name = getattr(project, "name", None) if project else None
        return f"project {name or conn.current_project_id}"

    def _api(self, region: Optional[str] = None):
        if self._conn is None:
            self._conn = connect(self.cloud, region)
        return self._conn

    def _bind(self, record) -> None:
        self.cloud = self.cloud or record.provider_ref.get("cloud")

    def has_hostname(self, spec: DeploySpec) -> bool:
        return preset_for(spec.extra.get("cloud") or self.cloud).hostname is not None

    def host_placeholder(self, spec: DeploySpec) -> str:
        preset = preset_for(spec.extra.get("cloud") or self.cloud)
        if spec.domain:
            return spec.domain
        if preset.hostname:
            return preset.hostname.format(name=dns_label(f"potato-{spec.name}"),
                                          project="<allocation>")
        return "<floating-ip>"

    def estimate_cost(self, size, volume_gb):
        return None

    def cost_note(self, size: str, volume_gb: Optional[int]) -> Optional[str]:
        if preset_for(self.cloud) is not PRESETS["jetstream2"]:
            return None
        # Jetstream2 CPU flavors bill one SU per vCPU-hour.
        vcpus = JETSTREAM2_VCPUS.get(size)
        if vcpus is None:
            return ("Charged to your allocation, not a card: Jetstream2 CPU "
                    f"flavors use one SU per vCPU per hour; check {size}'s vCPU "
                    "count in Horizon.")
        return (f"Charged to your allocation, not a card: on Jetstream2 an {size} "
                f"uses {vcpus} SU{'s' if vcpus != 1 else ''} per hour, about "
                f"{vcpus * 8760:,} a year if left running.")

    def volume_device_hint(self, spec: DeploySpec) -> str:
        return VOLUME_DEVICES[0]

    # -- plan ----------------------------------------------------------

    def _provider_actions(self, spec: DeploySpec, *, region: str, size: str,
                          user_data: str) -> List[Action]:
        preset = preset_for(spec.extra.get("cloud") or self.cloud)
        image = spec.extra.get("os_image") or preset.image
        actions = [
            Action("openstack.auth", f"authenticate to cloud "
                   f"{spec.extra.get('cloud') or self.cloud or '$OS_CLOUD'}"),
            Action("ssh.keygen", f"generate an ed25519 deploy key for user {DEPLOY_USER}"),
            Action("openstack.lookup", f"find flavor {size}, image {image!r} and a network"),
            Action("openstack.security_group", "allow inbound 22/80/443 only; never 8000",
                   {"rules": security_rules()}),
        ]
        if spec.volume_gb:
            actions.append(Action("openstack.volume",
                                  f"create a {spec.volume_gb} GB volume"))
        actions += [
            Action("openstack.server", f"create {dns_label('potato-' + spec.name)} "
                   f"({size}, {image})"),
            Action("state.persist", "record the server id before anything else can fail"),
            Action("wait.active", "wait for ACTIVE"),
            Action("openstack.floating_ip",
                   f"attach a floating IP from {preset.external_network}"),
        ]
        return actions

    # -- create --------------------------------------------------------

    def _resolve_cloud(self, spec: DeploySpec) -> None:
        # default_size and cost_note read self.cloud, so plan() must set it the
        # same way create() does or the dry run shows the generic flavor.
        self.cloud = spec.extra.get("cloud") or self.cloud or os.environ.get("OS_CLOUD")

    def plan(self, spec: DeploySpec, bundle):
        self._resolve_cloud(spec)
        return super().plan(spec, bundle)

    def create(self, spec: DeploySpec, bundle, existing, store):
        self._resolve_cloud(spec)
        if existing is not None:
            self._bind(existing)
        return super().create(spec, bundle, existing, store)

    def _check_account(self, api) -> None:
        if not getattr(api, "current_project_id", None):
            raise ProviderError("OpenStack authenticated but returned no project.")

    def _create_infrastructure(self, api, spec, record, store, *, region, size,
                               public_key, user_data_for: Callable) -> str:
        preset = preset_for(self.cloud)
        server_name = dns_label(f"potato-{spec.name}")
        record.provider_ref["cloud"] = self.cloud

        # Jetstream2 names every instance, so Caddy gets an ordinary
        # certificate for the hostname rather than a 6-day IP certificate.
        if preset.hostname and not spec.domain:
            project = getattr(getattr(api, "current_project", None), "name", None)
            if project:
                spec.domain = preset.hostname.format(name=server_name,
                                                     project=dns_label(project))
                record.spec["domain"] = spec.domain

        flavor = api.compute.find_flavor(size)
        if flavor is None:
            names = sorted(f.name for f in api.compute.flavors())
            raise ProviderError(f"No flavor {size!r}. Pass --size with one of: "
                                f"{', '.join(names)}")
        image_name = spec.extra.get("os_image") or preset.image
        image = api.image.find_image(image_name)
        if image is None:
            raise ProviderError(f"No image {image_name!r} on this cloud. Pass "
                                "--os-image with an Ubuntu 22.04 or 24.04 image name.")
        network = self._network(api, spec.extra.get("network"))

        group = api.network.create_security_group(
            name=f"potato-{spec.name}", description="Potato: 22/80/443")
        record.provider_ref["security_group_id"] = group.id
        store.upsert(record)
        for rule in security_rules():
            api.network.create_security_group_rule(security_group_id=group.id, **rule)

        volume = None
        if spec.volume_gb:
            volume = api.block_storage.create_volume(size=int(spec.volume_gb),
                                                     name=f"potato-{spec.name}")
            record.provider_ref["volume_id"] = volume.id
            record.provider_ref["volume_devices"] = [
                f"/dev/disk/by-id/virtio-{volume.id[:20]}",
                f"/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_{volume.id[:20]}",
                *VOLUME_DEVICES]
            store.upsert(record)

        user_data = user_data_for(VOLUME_DEVICES[0] if spec.volume_gb else None)
        self.console(f"Creating {server_name} ({size}, {image_name})...")
        server = api.compute.create_server(
            name=server_name, image_id=image.id, flavor_id=flavor.id,
            networks=[{"uuid": network.id}],
            security_groups=[{"name": group.name}],
            user_data=base64.b64encode(user_data.encode()).decode(),
            metadata={"potato": spec.name})
        # Before anything else can fail: a server nobody recorded bills forever.
        record.provider_ref["server_id"] = server.id
        store.upsert(record)

        server = api.compute.wait_for_server(server, status="ACTIVE", wait=900)
        external = api.network.find_network(preset.external_network)
        if external is None:
            raise ProviderError(f"No external network {preset.external_network!r} "
                                "for a floating IP.")
        floating = api.network.create_ip(floating_network_id=external.id)
        record.provider_ref["floating_ip_id"] = floating.id
        store.upsert(record)
        api.compute.add_floating_ip_to_server(server, floating.floating_ip_address)

        if volume is not None:
            api.block_storage.wait_for_status(volume, status="available", wait=300)
            api.compute.create_volume_attachment(server, volume_id=volume.id)

        if spec.domain:
            self._wait_for_dns(spec.domain, floating.floating_ip_address)
        return floating.floating_ip_address

    def _network(self, api, name: Optional[str]):
        if name:
            network = api.network.find_network(name)
            if network is None:
                raise ProviderError(f"No network {name!r}.")
            return network
        try:
            topology = api.network.get_auto_allocated_topology()
            return api.network.get_network(topology.id)
        except Exception as exc:
            raise ProviderError(
                "No --network given and this project has no auto-allocated "
                f"network ({exc}). Create one in Horizon/Exosphere, or pass "
                "--network <name>.") from exc

    def _wait_for_dns(self, hostname: str, address: str, timeout: int = 300) -> None:
        """Jetstream2 publishes the record a minute or two after the IP attaches.

        Caddy's ACME challenge fails until it does; waiting here turns a
        confusing certificate error into a short pause.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if address in {info[4][0] for info in socket.getaddrinfo(hostname, 443)}:
                    return
            except socket.gaierror:
                pass
            time.sleep(10)
        self.console(f"{hostname} does not resolve to {address} yet; the certificate "
                     "will be issued once it does.")

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
        server = api.compute.find_server(record.provider_ref["server_id"])
        if server is None:
            return "absent", {}
        status = getattr(server, "status", "UNKNOWN")
        return ("active" if status == "ACTIVE" else status.lower()), {"status": status}

    def _destroy_infrastructure(self, api, record, *, keep_data: bool) -> None:
        reference = record.provider_ref
        if reference.get("server_id"):
            server = api.compute.find_server(reference["server_id"])
            if server is not None:
                api.compute.delete_server(server)
                api.compute.wait_for_delete(server, wait=300)
            self.console(f"Deleted server {reference['server_id']}")
        if reference.get("floating_ip_id"):
            api.network.delete_ip(reference["floating_ip_id"], ignore_missing=True)
            self.console("Released the floating IP")
        if reference.get("security_group_id"):
            api.network.delete_security_group(reference["security_group_id"],
                                              ignore_missing=True)
            self.console("Deleted the security group")
        volume = reference.get("volume_id")
        if volume and keep_data:
            self.console(f"Kept volume {volume}; it counts against your quota.")
        elif volume:
            api.block_storage.delete_volume(volume, ignore_missing=True)
            self.console("Deleted the volume")

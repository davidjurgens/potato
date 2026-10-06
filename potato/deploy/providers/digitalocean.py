"""Deploy a Potato task to a DigitalOcean droplet.

This is the provider the rest of the interface was designed around. Persistence,
TLS without a domain, secret injection, log retrieval and getting the data back
are all real problems here, and solving them on a plain VM produces an interface
that a push-to-git host can also satisfy. Doing it the other way round yields a
`Provider` that only fits Spaces.

The machine-independent half (SSH, cloud-init, upload, Caddy, pull, logs) lives
in ``vm_base.VMProvider``; this module is the DigitalOcean API around it.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from potato.deploy.do_api import DigitalOceanAPI
from potato.deploy.providers.base import (
    Action,
    DeploySpec,
    ProviderError,
    register_provider,
)
from potato.deploy.providers.vm_base import (  # noqa: F401  (re-exported)
    APP_DIR,
    APP_PORT,
    CADDY_CONTAINER,
    CADDY_IMAGE,
    CONTAINER,
    DATA_DIR,
    DEFAULT_IMAGE,
    ENV_FILE,
    LETSENCRYPT_DIRECTORY,
    MIN_RECOMMENDED_MEMORY_MB,
    VMProvider,
    build_cloud_init,
    https_fallback as _https_fallback,
    render_env_file as _render_env_file,
    render_template,
)
from potato.deploy.remote import generate_keypair  # noqa: F401  (tests patch it here)

BASE_IMAGE = "docker-20-04"

DEFAULT_REGION = "nyc3"
DEFAULT_SIZE = "s-2vcpu-2gb"

# Monthly price by slug. Displayed before the confirmation prompt, so a wrong
# number here misleads someone about their own money.
SIZE_PRICES = {
    "s-1vcpu-1gb": 6.0,
    "s-1vcpu-2gb": 12.0,
    "s-2vcpu-2gb": 18.0,
    "s-2vcpu-4gb": 24.0,
    "s-4vcpu-8gb": 48.0,
}
VOLUME_PRICE_PER_GB = 0.10


def _memory_mb(size_slug: str) -> Optional[int]:
    """Parse the memory out of a size slug like `s-2vcpu-2gb`."""
    for part in (size_slug or "").split("-"):
        if part.endswith("gb") and part[:-2].isdigit():
            return int(part[:-2]) * 1024
        if part.endswith("mb") and part[:-2].isdigit():
            return int(part[:-2])
    return None


def firewall_rules(name: str, tag: str) -> Dict[str, Any]:
    """Inbound 22/80/443 only.

    Port 8000 is never opened. The container binds it to 127.0.0.1 and Caddy
    reaches it over loopback, so the plaintext app is unreachable from outside
    even if this firewall is deleted by hand.
    """
    anywhere = {"addresses": ["0.0.0.0/0", "::/0"]}
    return {
        "name": f"potato-{name}",
        "inbound_rules": [
            {"protocol": "tcp", "ports": "22", "sources": anywhere},
            {"protocol": "tcp", "ports": "80", "sources": anywhere},
            {"protocol": "tcp", "ports": "443", "sources": anywhere},
        ],
        "outbound_rules": [
            {"protocol": "tcp", "ports": "all", "destinations": anywhere},
            {"protocol": "udp", "ports": "all", "destinations": anywhere},
            {"protocol": "icmp", "destinations": anywhere},
        ],
        "tags": [tag],
    }


def droplet_payload(spec: DeploySpec, *, tag: str, ssh_key_id, user_data: str,
                    region: str, size: str) -> Dict[str, Any]:
    return {
        "name": f"potato-{spec.name}",
        "region": region,
        "size": size,
        "image": BASE_IMAGE,
        "ssh_keys": [ssh_key_id],
        "backups": False,
        "ipv6": True,
        "monitoring": True,
        "tags": [tag, "potato"],
        "user_data": user_data,
    }


@register_provider
class DigitalOceanProvider(VMProvider):
    """A single droplet running the published image behind Caddy."""

    name = "digitalocean"
    server_noun = "droplet"
    server_id_key = "droplet_id"
    default_region = DEFAULT_REGION
    default_size = DEFAULT_SIZE
    console_name = "the DigitalOcean console"

    def verify_credential(self):
        account = DigitalOceanAPI(self.token).verify_token()
        email = account.get("email") or "unknown account"
        limit = account.get("droplet_limit")
        status = account.get("status")
        detail = f"{email}"
        if status and status != "active":
            detail += f", status {status}"
        if limit is not None:
            detail += f", droplet limit {limit}"
        return detail

    # -- VMProvider hooks ----------------------------------------------

    def _api(self, region: Optional[str] = None):
        return DigitalOceanAPI(self.token)

    def _check_account(self, api) -> None:
        account = api.verify_token()
        if account.get("status") not in (None, "active"):
            raise ProviderError(
                f"The DigitalOcean account is {account.get('status')}: "
                f"{account.get('status_message') or 'see the console'}")

    def memory_mb(self, size: str) -> Optional[int]:
        return _memory_mb(size)

    def estimate_cost(self, size: str, volume_gb: Optional[int]) -> float:
        return _estimate_cost(size, volume_gb)

    def volume_device_hint(self, spec: DeploySpec) -> str:
        return _volume_device(spec)

    def _provider_actions(self, spec: DeploySpec, *, region: str, size: str,
                          user_data: str) -> List[Action]:
        tag = f"potato-{spec.name}"
        actions = [
            Action("do.account", "verify the token with GET /v2/account"),
            Action("ssh.keygen",
                   "generate an ed25519 deploy key (never your own key)"),
            Action("do.ssh_key", f"register the public key as potato-{spec.name}",
                   {"name": f"potato-{spec.name}"}),
        ]
        if spec.volume_gb:
            actions.append(Action(
                "do.volume", f"create a {spec.volume_gb} GB volume in {region}",
                {"size_gigabytes": spec.volume_gb, "region": region}))
        actions += [
            Action("do.droplet", f"create a {size} droplet in {region} from {BASE_IMAGE}",
                   droplet_payload(spec, tag=tag, ssh_key_id="<key-id>",
                                   user_data=user_data, region=region, size=size)),
            Action("state.persist",
                   "record the droplet id before anything else can fail"),
            Action("do.firewall", "allow inbound 22/80/443 only; never 8000",
                   firewall_rules(spec.name, tag)),
            Action("wait.active", "poll until the droplet reports active with an IPv4"),
        ]
        return actions

    def _create_infrastructure(self, api, spec, record, store, *, region, size,
                               public_key, user_data_for: Callable) -> str:
        tag = record.provider_ref["tag"]
        ssh_key = api.create_ssh_key(f"potato-{spec.name}", public_key)
        record.provider_ref["ssh_key_id"] = ssh_key["id"]
        store.upsert(record)

        volume_id = None
        if spec.volume_gb:
            self.console(f"Creating a {spec.volume_gb} GB volume...")
            volume = api.create_volume({
                "name": f"potato-{spec.name}",
                "region": region,
                "size_gigabytes": int(spec.volume_gb),
                "filesystem_type": "ext4",
                "tags": [tag],
            })
            volume_id = volume["id"]
            record.provider_ref["volume_id"] = volume_id
            record.provider_ref["volume_name"] = volume["name"]
            record.provider_ref["volume_devices"] = [_volume_device(spec)]
            store.upsert(record)

        user_data = user_data_for(_volume_device(spec) if spec.volume_gb else None)
        self.console(f"Creating a {size} droplet in {region}...")
        droplet = api.create_droplet(droplet_payload(
            spec, tag=tag, ssh_key_id=ssh_key["id"], user_data=user_data,
            region=region, size=size))

        # Before anything else can fail. A droplet whose id exists only in a
        # dead process is a machine that bills forever.
        record.provider_ref["droplet_id"] = droplet["id"]
        store.upsert(record)

        firewall = api.create_firewall(firewall_rules(spec.name, tag))
        record.provider_ref["firewall_id"] = firewall["id"]
        store.upsert(record)

        ip = self._wait_for_ipv4(api, droplet["id"])
        if volume_id:
            self.console("Attaching the volume...")
            api.attach_volume(volume_id, droplet["id"], region)
        return ip

    def _wait_for_ipv4(self, api, droplet_id: int, timeout: int = 300) -> str:
        self.console("Waiting for the droplet to become active...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            droplet = api.get_droplet(droplet_id) or {}
            for network in (droplet.get("networks", {}).get("v4") or []):
                if network.get("type") == "public" and network.get("ip_address"):
                    return network["ip_address"]
            time.sleep(5)
        raise ProviderError(
            f"Droplet {droplet_id} did not report a public IPv4 within {timeout}s. "
            "It may still be provisioning; check the DigitalOcean console. The "
            "droplet id is recorded locally, so `potato deploy destroy` can "
            "still remove it.")

    def _server_state(self, api, record) -> Tuple[str, Dict[str, Any]]:
        droplet = api.get_droplet(record.provider_ref["droplet_id"])
        if droplet is None:
            return "absent", {}
        return droplet.get("status", "unknown"), droplet

    def _destroy_infrastructure(self, api, record, *, keep_data: bool) -> None:
        """Remove the droplet, firewall, SSH key and volume.

        Order matters: the droplet goes first so the volume detaches, and every
        step tolerates a missing resource so a partly-destroyed deployment can
        be finished off rather than becoming unremovable.
        """
        reference = record.provider_ref

        droplet_id = reference.get("droplet_id")
        if droplet_id:
            api.delete_droplet(droplet_id)
            self.console(f"Deleted droplet {droplet_id}")

        if reference.get("firewall_id"):
            api.delete_firewall(reference["firewall_id"])
            self.console("Deleted the firewall")

        if reference.get("ssh_key_id"):
            try:
                api.delete_ssh_key(reference["ssh_key_id"])
                self.console("Removed the deploy key")
            except ProviderError as exc:
                self.console(f"Could not remove the deploy key: {exc}")

        volume_id = reference.get("volume_id")
        if volume_id and not keep_data:
            # The droplet has to release it first; a detach lags the delete.
            for attempt in range(12):
                try:
                    api.delete_volume(volume_id)
                    self.console("Deleted the volume")
                    break
                except ProviderError:
                    time.sleep(5)
            else:
                self.console(
                    f"Volume {volume_id} could not be deleted (still attached?). "
                    "It continues to bill until removed in the console.")
        elif volume_id:
            self.console(f"Kept volume {volume_id}; it still bills "
                         f"${VOLUME_PRICE_PER_GB:.2f}/GB per month.")

        # Anything created but never recorded — a mid-create crash — is still
        # tagged, so name it rather than leaving it to bill unnoticed.
        orphans = [d for d in api.droplets_by_tag(reference.get("tag", ""))
                   if d.get("id") != droplet_id]
        for orphan in orphans:
            self.console(f"Also found tagged droplet {orphan['id']} "
                         f"({orphan.get('name')}); deleting it too")
            api.delete_droplet(orphan["id"])


def _record_spec(spec: DeploySpec) -> Dict[str, Any]:
    return DigitalOceanProvider().record_spec(spec)


def _volume_device(spec: DeploySpec) -> str:
    """DigitalOcean exposes an attached volume at a name-derived path."""
    return f"/dev/disk/by-id/scsi-0DO_Volume_potato-{spec.name}"


def _estimate_cost(size: str, volume_gb: Optional[int]) -> float:
    cost = SIZE_PRICES.get(size, 0.0)
    if volume_gb:
        cost += float(volume_gb) * VOLUME_PRICE_PER_GB
    return cost

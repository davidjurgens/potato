"""Deploy a Potato task to a Hetzner Cloud server (``--provider hetzner``).

The cheapest real VM in this list, even after Hetzner's two 2026 price rises:
a CX23 (2 vCPU, 4 GB) is about €5.49 a month plus €0.50 for its IPv4 address.
It bills in euros, from European companies, which some institutions cannot
use; that is the main reason not to.

The API takes cloud-init as ``user_data`` (32 KiB), registers the deploy key
for root, attaches the firewall and the volume at creation, and reports the
address in the create response, so there is no attach race to wait out.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from potato.deploy.providers.base import (
    Action,
    DeploySpec,
    ProviderError,
    register_provider,
)
from potato.deploy.providers.vm_base import PUBLIC_PORTS, VMProvider
from potato.deploy.rest import RestAPI

API_ROOT = "https://api.hetzner.cloud/v1"
TOKEN_PAGE = "https://console.hetzner.cloud/ (project → Security → API tokens)"
DEFAULT_LOCATION = "nbg1"
DEFAULT_TYPE = "cx23"
IMAGE = "ubuntu-24.04"

# Euro list prices after the June 2026 change, per month, IPv4 extra.
TYPE_PRICES_EUR = {"cx23": 5.49, "cx33": 8.49, "cax11": 5.99, "cax21": 9.99}
TYPE_MEMORY_MB = {"cx23": 4096, "cx33": 8192, "cax11": 4096, "cax21": 8192}
IPV4_EUR = 0.50
VOLUME_EUR_PER_GB = 0.057
US_LOCATIONS = ("ash", "hil")


def hetzner_api(token: str) -> RestAPI:
    return RestAPI(API_ROOT, token, provider="Hetzner", token_page=TOKEN_PAGE)


def firewall_rules() -> List[Dict[str, Any]]:
    """Inbound 22/80/443 only. Outbound is unrestricted by default."""
    return [{"direction": "in", "protocol": "tcp", "port": str(port),
             "source_ips": ["0.0.0.0/0", "::/0"],
             "description": f"potato {port}"} for port in PUBLIC_PORTS]


def server_request(spec: DeploySpec, *, server_type: str, location: str,
                   ssh_key_id, firewall_id, volume_id, user_data: str) -> Dict[str, Any]:
    """The POST /servers body. Pure, so a test can assert it exactly."""
    body: Dict[str, Any] = {
        "name": f"potato-{spec.name}",
        "server_type": server_type,
        "image": IMAGE,
        "location": location,
        "ssh_keys": [ssh_key_id],
        "user_data": user_data,
        "firewalls": [{"firewall": firewall_id}],
        "labels": {"potato": spec.name},
        "public_net": {"enable_ipv4": True, "enable_ipv6": True},
        "start_after_create": True,
    }
    if volume_id:
        body["volumes"] = [volume_id]
        body["automount"] = False   # the shared volume script mounts it
    return body


@register_provider
class HetznerProvider(VMProvider):
    """One Hetzner Cloud server behind Caddy."""

    name = "hetzner"
    summary = "Hetzner Cloud: a 4 GB VM for about €6/mo, the cheapest durable target"
    server_noun = "server"
    server_id_key = "server_id"
    default_region = DEFAULT_LOCATION
    default_size = DEFAULT_TYPE
    user_data_limit = 32 * 1024
    console_name = "the Hetzner Cloud console"

    def verify_credential(self):
        servers = hetzner_api(self.token).get("/servers?per_page=1")
        total = ((servers.get("meta") or {}).get("pagination") or {}).get("total_entries")
        return f"project token accepted ({total if total is not None else '?'} servers)"

    def _api(self, region: Optional[str] = None) -> RestAPI:
        return hetzner_api(self.token)

    def memory_mb(self, size: str) -> Optional[int]:
        return TYPE_MEMORY_MB.get(size)

    def cost_note(self, size: str, volume_gb: Optional[int]) -> Optional[str]:
        if size not in TYPE_PRICES_EUR:
            return None
        total = TYPE_PRICES_EUR[size] + IPV4_EUR + (
            float(volume_gb) * VOLUME_EUR_PER_GB if volume_gb else 0.0)
        return f"Estimated cost: €{total:.2f}/month (Hetzner bills in euros)."

    def volume_device_hint(self, spec: DeploySpec) -> str:
        return "/dev/disk/by-id/scsi-0HC_Volume_<id>"

    def _provider_actions(self, spec: DeploySpec, *, region: str, size: str,
                          user_data: str) -> List[Action]:
        actions = [
            Action("hetzner.token", "check the project token with GET /servers"),
            Action("hetzner.server_type", f"check that {size} is sold in {region}"),
            Action("ssh.keygen", "generate an ed25519 deploy key"),
            Action("hetzner.ssh_key", f"register it as potato-{spec.name}"),
            Action("hetzner.firewall", "allow inbound 22/80/443 only; never 8000",
                   {"rules": firewall_rules()}),
        ]
        if spec.volume_gb:
            actions.append(Action("hetzner.volume",
                                  f"create a {spec.volume_gb} GB volume in {region}"))
        actions += [
            Action("hetzner.server", f"create a {size} running {IMAGE} in {region}",
                   server_request(spec, server_type=size, location=region,
                                  ssh_key_id="<key>", firewall_id="<fw>",
                                  volume_id="<vol>" if spec.volume_gb else None,
                                  user_data="<cloud-init>")),
            Action("state.persist", "record the server id before anything else can fail"),
            Action("wait.active", "poll until the server is running"),
        ]
        return actions

    def _check_account(self, api) -> None:
        api.get("/servers?per_page=1")

    def _check_server_type(self, api, size: str, location: str) -> None:
        types = api.get(f"/server_types?name={size}").get("server_types") or []
        if not types:
            names = sorted(t["name"] for t in api.get("/server_types?per_page=50")
                           .get("server_types", []) if not t.get("deprecated"))
            raise ProviderError(
                f"Hetzner has no server type {size!r}. Pass --size with one of: "
                f"{', '.join(names)}")
        prices = types[0].get("prices") or []
        if prices and location not in {p.get("location") for p in prices}:
            sold = sorted(p.get("location") for p in prices)
            raise ProviderError(
                f"{size} is not sold in {location} (it is in: {', '.join(sold)}). "
                "Pass --region with one of those, or --size for a type sold there"
                + ("; the US locations sell the CPX range." if location in US_LOCATIONS
                   else "."))

    def _create_infrastructure(self, api, spec, record, store, *, region, size,
                               public_key, user_data_for: Callable) -> str:
        self._check_server_type(api, size, region)

        key = api.post("/ssh_keys", {"name": f"potato-{spec.name}-{int(time.time())}",
                                     "public_key": public_key,
                                     "labels": {"potato": spec.name}})["ssh_key"]
        record.provider_ref["ssh_key_id"] = key["id"]
        store.upsert(record)

        firewall = api.post("/firewalls", {"name": f"potato-{spec.name}",
                                           "rules": firewall_rules(),
                                           "labels": {"potato": spec.name}})["firewall"]
        record.provider_ref["firewall_id"] = firewall["id"]
        store.upsert(record)

        volume_id = None
        if spec.volume_gb:
            volume = api.post("/volumes", {
                "name": f"potato-{spec.name}", "size": int(spec.volume_gb),
                "location": region, "labels": {"potato": spec.name}})["volume"]
            volume_id = volume["id"]
            record.provider_ref["volume_id"] = volume_id
            record.provider_ref["volume_devices"] = [
                volume.get("linux_device") or f"/dev/disk/by-id/scsi-0HC_Volume_{volume_id}"]
            store.upsert(record)

        user_data = user_data_for(record.provider_ref.get("volume_devices", [None])[0])
        self.console(f"Creating a {size} server in {region}...")
        created = api.post("/servers", server_request(
            spec, server_type=size, location=region, ssh_key_id=key["id"],
            firewall_id=firewall["id"], volume_id=volume_id, user_data=user_data))
        server = created["server"]
        # Before anything else can fail: a server nobody recorded bills forever.
        record.provider_ref["server_id"] = server["id"]
        store.upsert(record)

        deadline = time.time() + 600
        while time.time() < deadline:
            current = api.get(f"/servers/{server['id']}")["server"]
            if current.get("status") == "running":
                return current["public_net"]["ipv4"]["ip"]
            time.sleep(5)
        raise ProviderError(f"Server {server['id']} did not start within 10 minutes.")

    def _server_state(self, api, record) -> Tuple[str, Dict[str, Any]]:
        found = api.get_or_none(f"/servers/{record.provider_ref['server_id']}")
        if found is None:
            return "absent", {}
        server = found.get("server") or {}
        status = server.get("status", "unknown")
        return ("active" if status == "running" else status), server

    def _destroy_infrastructure(self, api, record, *, keep_data: bool) -> None:
        reference = record.provider_ref
        if reference.get("server_id"):
            api.delete(f"/servers/{reference['server_id']}")
            self.console(f"Deleted server {reference['server_id']}")
            # The firewall and volume stay "in use" until the server is gone.
            deadline = time.time() + 180
            while time.time() < deadline and api.get_or_none(
                    f"/servers/{reference['server_id']}") is not None:
                time.sleep(5)
        if reference.get("firewall_id"):
            api.delete(f"/firewalls/{reference['firewall_id']}")
            self.console("Deleted the firewall")
        if reference.get("ssh_key_id"):
            api.delete(f"/ssh_keys/{reference['ssh_key_id']}")
            self.console("Removed the deploy key")
        volume = reference.get("volume_id")
        if volume and keep_data:
            self.console(f"Kept volume {volume}; it bills until deleted in the console.")
        elif volume:
            api.delete(f"/volumes/{volume}")
            self.console("Deleted the volume")

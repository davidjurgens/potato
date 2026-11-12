"""Deploy a Potato task to an Akamai (Linode) instance (``--provider linode``).

A 2 GB Linode is $12/month, unchanged through 2026. The API needs a root
password even when keys are supplied; one is generated per deployment, kept
in the secret store, and made useless for login by cloud-init's
``ssh_pwauth: false``. Cloud-init arrives through the Metadata service
(``metadata.user_data``), which the Ubuntu 24.04 image supports.
"""

from __future__ import annotations

import base64
import secrets as pysecrets
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
from potato.deploy.state import SecretStore

API_ROOT = "https://api.linode.com/v4"
TOKEN_PAGE = "https://cloud.linode.com/profile/tokens"
DEFAULT_REGION = "us-east"
DEFAULT_TYPE = "g6-standard-1"
IMAGE = "linode/ubuntu24.04"

TYPE_PRICES = {"g6-nanode-1": 5.0, "g6-standard-1": 12.0, "g6-standard-2": 24.0,
               "g6-standard-4": 48.0}
TYPE_MEMORY_MB = {"g6-nanode-1": 1024, "g6-standard-1": 2048, "g6-standard-2": 4096,
                  "g6-standard-4": 8192}
VOLUME_PRICE_PER_GB = 0.10


def linode_api(token: str) -> RestAPI:
    return RestAPI(API_ROOT, token, provider="Linode", token_page=TOKEN_PAGE)


def firewall_request(spec: DeploySpec) -> Dict[str, Any]:
    """Drop everything inbound except 22/80/443."""
    return {
        "label": f"potato-{spec.name}"[:32],
        "rules": {
            "inbound_policy": "DROP",
            "outbound_policy": "ACCEPT",
            "inbound": [{
                "label": "potato-web",
                "action": "ACCEPT",
                "protocol": "TCP",
                "ports": ",".join(str(p) for p in PUBLIC_PORTS),
                "addresses": {"ipv4": ["0.0.0.0/0"], "ipv6": ["::/0"]},
            }],
        },
        "tags": ["potato"],
    }


def instance_request(spec: DeploySpec, *, region: str, linode_type: str,
                     public_key: str, root_pass: str, firewall_id,
                     user_data: str) -> Dict[str, Any]:
    """The POST /linode/instances body. Pure, so a test can assert it exactly."""
    return {
        "label": f"potato-{spec.name}"[:64],
        "region": region,
        "type": linode_type,
        "image": IMAGE,
        "root_pass": root_pass,
        "authorized_keys": [public_key],
        "firewall_id": firewall_id,
        "metadata": {"user_data": base64.b64encode(user_data.encode()).decode()},
        "tags": ["potato", f"potato-{spec.name}"],
        "booted": True,
    }


@register_provider
class LinodeProvider(VMProvider):
    """One Linode instance behind Caddy."""

    name = "linode"
    summary = "Akamai/Linode: a 2 GB VM for $12/mo"
    server_noun = "linode"
    server_id_key = "linode_id"
    default_region = DEFAULT_REGION
    default_size = DEFAULT_TYPE
    user_data_limit = 64 * 1024
    console_name = "the Linode Cloud Manager"

    def verify_credential(self):
        profile = linode_api(self.token).get("/profile")
        return profile.get("email") or profile.get("username") or "profile"

    def _api(self, region: Optional[str] = None) -> RestAPI:
        return linode_api(self.token)

    def memory_mb(self, size: str) -> Optional[int]:
        return TYPE_MEMORY_MB.get(size)

    def estimate_cost(self, size: str, volume_gb: Optional[int]) -> Optional[float]:
        if size not in TYPE_PRICES:
            return None
        return TYPE_PRICES[size] + (float(volume_gb) * VOLUME_PRICE_PER_GB
                                    if volume_gb else 0.0)

    def volume_device_hint(self, spec: DeploySpec) -> str:
        return f"/dev/disk/by-id/scsi-0Linode_Volume_potato-{spec.name}"

    def _provider_actions(self, spec: DeploySpec, *, region: str, size: str,
                          user_data: str) -> List[Action]:
        actions = [
            Action("linode.profile", "verify the token with GET /profile"),
            Action("ssh.keygen", "generate an ed25519 deploy key"),
            Action("linode.firewall", "allow inbound 22/80/443 only; never 8000",
                   firewall_request(spec)),
            Action("linode.instance", f"create a {size} running {IMAGE} in {region}",
                   {k: v for k, v in instance_request(
                       spec, region=region, linode_type=size, public_key="<key>",
                       root_pass="<generated, stored in .potato/secrets.json>",
                       firewall_id="<fw>", user_data="").items() if k != "metadata"}),
            Action("state.persist", "record the linode id before anything else can fail"),
            Action("wait.active", "poll until the linode is running"),
        ]
        if spec.volume_gb:
            actions.append(Action("linode.volume",
                                  f"create a {spec.volume_gb} GB volume attached to it"))
        return actions

    def _check_account(self, api) -> None:
        api.get("/profile")

    def _create_infrastructure(self, api, spec, record, store, *, region, size,
                               public_key, user_data_for: Callable) -> str:
        firewall = api.post("/networking/firewalls", firewall_request(spec))
        record.provider_ref["firewall_id"] = firewall["id"]
        store.upsert(record)

        volume_label = f"potato-{spec.name}"[:32]
        if spec.volume_gb:
            record.provider_ref["volume_devices"] = [
                f"/dev/disk/by-id/scsi-0Linode_Volume_{volume_label}"]

        # Required by the API; never usable for login (ssh_pwauth: false).
        root_pass = pysecrets.token_urlsafe(32)
        SecretStore(spec.config_path).put(spec.name, "linode_root_password", root_pass)

        user_data = user_data_for((record.provider_ref.get("volume_devices") or [None])[0])
        self.console(f"Creating a {size} linode in {region}...")
        instance = api.post("/linode/instances", instance_request(
            spec, region=region, linode_type=size, public_key=public_key,
            root_pass=root_pass, firewall_id=firewall["id"], user_data=user_data))
        # Before anything else can fail: an instance nobody recorded bills forever.
        record.provider_ref["linode_id"] = instance["id"]
        store.upsert(record)

        deadline = time.time() + 600
        while time.time() < deadline:
            current = api.get(f"/linode/instances/{instance['id']}")
            if current.get("status") == "running" and current.get("ipv4"):
                ip = current["ipv4"][0]
                break
            time.sleep(5)
        else:
            raise ProviderError(f"Linode {instance['id']} did not start within 10 minutes.")

        if spec.volume_gb:
            volume = api.post("/volumes", {"label": volume_label,
                                           "size": int(spec.volume_gb),
                                           "linode_id": instance["id"],
                                           "tags": ["potato"]})
            record.provider_ref["volume_id"] = volume["id"]
            store.upsert(record)
        return ip

    def _server_state(self, api, record) -> Tuple[str, Dict[str, Any]]:
        found = api.get_or_none(f"/linode/instances/{record.provider_ref['linode_id']}")
        if found is None:
            return "absent", {}
        status = found.get("status", "unknown")
        return ("active" if status == "running" else status), found

    def _destroy_infrastructure(self, api, record, *, keep_data: bool) -> None:
        reference = record.provider_ref
        volume = reference.get("volume_id")
        if volume:
            # A volume must be detached before its linode can take it along.
            try:
                api.post(f"/volumes/{volume}/detach")
            except ProviderError:
                pass
        if reference.get("linode_id"):
            api.delete(f"/linode/instances/{reference['linode_id']}")
            self.console(f"Deleted linode {reference['linode_id']}")
        if reference.get("firewall_id"):
            api.delete(f"/networking/firewalls/{reference['firewall_id']}")
            self.console("Deleted the firewall")
        if volume and keep_data:
            self.console(f"Kept volume {volume}; it bills until deleted.")
        elif volume:
            deadline = time.time() + 120
            while True:
                try:
                    api.delete(f"/volumes/{volume}")
                    self.console("Deleted the volume")
                    break
                except ProviderError:
                    if time.time() > deadline:
                        self.console(f"Volume {volume} is still detaching; delete it "
                                     "in the Linode Cloud Manager.")
                        break
                    time.sleep(10)

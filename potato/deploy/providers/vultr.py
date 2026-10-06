"""Deploy a Potato task to a Vultr instance (``--provider vultr``).

A US-billed VPS at DigitalOcean-like prices ($10/month for 2 GB). The API takes
base64 cloud-init, registers the deploy key for root, and applies a firewall
group; block storage attaches after the instance exists, which the shared
volume script waits out.
"""

from __future__ import annotations

import base64
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

API_ROOT = "https://api.vultr.com/v2"
TOKEN_PAGE = "https://my.vultr.com/settings/#settingsapi"
DEFAULT_REGION = "ewr"
DEFAULT_PLAN = "vc2-1c-2gb"
OS_NAME = "Ubuntu 24.04 LTS x64"

PLAN_PRICES = {"vc2-1c-1gb": 5.0, "vc2-1c-2gb": 10.0, "vc2-2c-4gb": 20.0,
               "vc2-4c-8gb": 40.0}
PLAN_MEMORY_MB = {"vc2-1c-1gb": 1024, "vc2-1c-2gb": 2048, "vc2-2c-4gb": 4096,
                  "vc2-4c-8gb": 8192}
BLOCK_PRICE_PER_GB = 0.10
BLOCK_DEVICES = ["/dev/vdb", "/dev/sdb"]


def vultr_api(token: str) -> RestAPI:
    return RestAPI(API_ROOT, token, provider="Vultr", token_page=TOKEN_PAGE)


def firewall_rules() -> List[Dict[str, Any]]:
    rules = []
    for port in PUBLIC_PORTS:
        rules.append({"ip_type": "v4", "protocol": "tcp", "subnet": "0.0.0.0",
                      "subnet_size": 0, "port": str(port), "notes": "potato"})
        rules.append({"ip_type": "v6", "protocol": "tcp", "subnet": "::",
                      "subnet_size": 0, "port": str(port), "notes": "potato"})
    return rules


def instance_request(spec: DeploySpec, *, region: str, plan: str, os_id,
                     ssh_key_id, firewall_id, user_data: str) -> Dict[str, Any]:
    """The POST /instances body. Pure, so a test can assert it exactly."""
    return {
        "region": region,
        "plan": plan,
        "os_id": os_id,
        "label": f"potato-{spec.name}",
        "hostname": f"potato-{spec.name}",
        "sshkey_id": [ssh_key_id],
        "firewall_group_id": firewall_id,
        "user_data": base64.b64encode(user_data.encode("utf-8")).decode("ascii"),
        "enable_ipv6": True,
        "backups": "disabled",
        "tags": ["potato", f"potato-{spec.name}"],
    }


@register_provider
class VultrProvider(VMProvider):
    """One Vultr instance behind Caddy."""

    name = "vultr"
    summary = "Vultr: a 2 GB VPS for $10/mo"
    server_noun = "instance"
    server_id_key = "instance_id"
    default_region = DEFAULT_REGION
    default_size = DEFAULT_PLAN
    user_data_limit = 64 * 1024
    console_name = "the Vultr console"

    def verify_credential(self):
        account = vultr_api(self.token).get("/account").get("account") or {}
        return account.get("email") or account.get("name") or "account"

    def _api(self, region: Optional[str] = None) -> RestAPI:
        return vultr_api(self.token)

    def memory_mb(self, size: str) -> Optional[int]:
        return PLAN_MEMORY_MB.get(size)

    def estimate_cost(self, size: str, volume_gb: Optional[int]) -> Optional[float]:
        if size not in PLAN_PRICES:
            return None
        return PLAN_PRICES[size] + (float(volume_gb) * BLOCK_PRICE_PER_GB
                                    if volume_gb else 0.0)

    def volume_device_hint(self, spec: DeploySpec) -> str:
        return BLOCK_DEVICES[0]

    def _provider_actions(self, spec: DeploySpec, *, region: str, size: str,
                          user_data: str) -> List[Action]:
        actions = [
            Action("vultr.account", "verify the key with GET /account"),
            Action("vultr.os", f"look up the os_id for {OS_NAME}"),
            Action("ssh.keygen", "generate an ed25519 deploy key"),
            Action("vultr.ssh_key", f"register it as potato-{spec.name}"),
            Action("vultr.firewall", "allow inbound 22/80/443 only; never 8000",
                   {"rules": firewall_rules()}),
            Action("vultr.instance", f"create a {size} instance in {region}",
                   instance_request(spec, region=region, plan=size, os_id="<os>",
                                    ssh_key_id="<key>", firewall_id="<fw>",
                                    user_data="")),
            Action("state.persist", "record the instance id before anything else can fail"),
            Action("wait.active", "poll until the instance is active with an IPv4"),
        ]
        if spec.volume_gb:
            actions.append(Action("vultr.block",
                                  f"create a {spec.volume_gb} GB block volume and attach it"))
        return actions

    def _check_account(self, api) -> None:
        api.get("/account")

    def _os_id(self, api) -> int:
        cursor = ""
        while True:
            page = api.get(f"/os?per_page=500{'&cursor=' + cursor if cursor else ''}")
            for entry in page.get("os") or []:
                if entry.get("name") == OS_NAME:
                    return entry["id"]
            cursor = ((page.get("meta") or {}).get("links") or {}).get("next") or ""
            if not cursor:
                raise ProviderError(f"Vultr no longer lists {OS_NAME!r}.")

    def _create_infrastructure(self, api, spec, record, store, *, region, size,
                               public_key, user_data_for: Callable) -> str:
        os_id = self._os_id(api)

        key = api.post("/ssh-keys", {"name": f"potato-{spec.name}",
                                     "ssh_key": public_key})["ssh_key"]
        record.provider_ref["ssh_key_id"] = key["id"]
        store.upsert(record)

        group = api.post("/firewalls", {"description": f"potato-{spec.name}"})
        group_id = (group.get("firewall_group") or {})["id"]
        record.provider_ref["firewall_id"] = group_id
        store.upsert(record)
        for rule in firewall_rules():
            api.post(f"/firewalls/{group_id}/rules", rule)

        if spec.volume_gb:
            record.provider_ref["volume_devices"] = list(BLOCK_DEVICES)

        user_data = user_data_for(BLOCK_DEVICES[0] if spec.volume_gb else None)
        self.console(f"Creating a {size} instance in {region}...")
        instance = api.post("/instances", instance_request(
            spec, region=region, plan=size, os_id=os_id, ssh_key_id=key["id"],
            firewall_id=group_id, user_data=user_data))["instance"]
        # Before anything else can fail: an instance nobody recorded bills forever.
        record.provider_ref["instance_id"] = instance["id"]
        store.upsert(record)

        ip = self._wait_for_ip(api, instance["id"])

        if spec.volume_gb:
            block = api.post("/blocks", {"region": region, "size_gb": int(spec.volume_gb),
                                         "label": f"potato-{spec.name}"})["block"]
            record.provider_ref["block_id"] = block["id"]
            store.upsert(record)
            api.post(f"/blocks/{block['id']}/attach",
                     {"instance_id": instance["id"], "live": True})
        return ip

    def _wait_for_ip(self, api, instance_id: str, timeout: int = 600) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            instance = api.get(f"/instances/{instance_id}")["instance"]
            ip = instance.get("main_ip")
            if instance.get("status") == "active" and ip and ip != "0.0.0.0":
                return ip
            time.sleep(5)
        raise ProviderError(f"Instance {instance_id} did not become active in time.")

    def _server_state(self, api, record) -> Tuple[str, Dict[str, Any]]:
        found = api.get_or_none(f"/instances/{record.provider_ref['instance_id']}")
        if found is None:
            return "absent", {}
        instance = found.get("instance") or {}
        status = instance.get("status", "unknown")
        power = instance.get("power_status")
        if status == "active" and power in (None, "running"):
            return "active", instance
        return power or status, instance

    def _destroy_infrastructure(self, api, record, *, keep_data: bool) -> None:
        reference = record.provider_ref
        block = reference.get("block_id")
        # Deleting the instance detaches its block storage; the block survives.
        if reference.get("instance_id"):
            api.delete(f"/instances/{reference['instance_id']}")
            self.console(f"Deleted instance {reference['instance_id']}")
        if reference.get("firewall_id"):
            api.delete(f"/firewalls/{reference['firewall_id']}")
            self.console("Deleted the firewall group")
        if reference.get("ssh_key_id"):
            api.delete(f"/ssh-keys/{reference['ssh_key_id']}")
            self.console("Removed the deploy key")
        if block and keep_data:
            self.console(f"Kept block volume {block}; it bills until deleted.")
        elif block:
            deadline = time.time() + 120
            while True:
                try:
                    api.delete(f"/blocks/{block}")
                    self.console("Deleted the block volume")
                    break
                except ProviderError:
                    if time.time() > deadline:
                        self.console(f"Block volume {block} is still attached; "
                                     "delete it in the Vultr console.")
                        break
                    time.sleep(10)

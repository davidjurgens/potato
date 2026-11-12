"""A small DigitalOcean API v2 client.

Five endpoints — droplets, volumes, firewalls, SSH keys, account — do not
justify the `pydo` SDK and the dependency it drags in. `requests` is already a
core dependency.

Two behaviours are worth having in one place rather than at each call site.
Rate limits carry a `Retry-After`, and honouring the server's own number beats
guessing with exponential backoff. And DigitalOcean returns its errors as JSON
with a human-readable `message`, which is far more useful than
`HTTPError: 422 Client Error` — so errors are unwrapped before they are raised.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from potato.deploy.providers.base import ProviderError

logger = logging.getLogger(__name__)

API_ROOT = "https://api.digitalocean.com/v2"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 6


class DigitalOceanAPI:
    """Authenticated session against api.digitalocean.com."""

    def __init__(self, token: str, *, root: str = API_ROOT,
                 timeout: int = DEFAULT_TIMEOUT):
        if not token:
            raise ProviderError("A DigitalOcean API token is required.")
        self.token = token
        self.root = root.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "potato-deploy",
        })

    # -- transport -----------------------------------------------------

    def request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.root}{path}"
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.session.request(
                    method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                raise ProviderError(
                    f"Could not reach the DigitalOcean API: {exc}") from exc

            if response.status_code == 429 and attempt <= MAX_RETRIES:
                delay = _retry_after(response, attempt)
                logger.info("Rate limited by DigitalOcean; waiting %ss", delay)
                time.sleep(delay)
                continue

            if response.status_code == 401:
                raise ProviderError(
                    "DigitalOcean rejected the token (401). Check that it has not "
                    "expired and that it carries write scope: "
                    "https://cloud.digitalocean.com/account/api/tokens")

            if response.status_code >= 400:
                raise ProviderError(
                    f"DigitalOcean API error {response.status_code} on "
                    f"{method} {path}: {_error_message(response)}")

            if response.status_code == 204 or not response.content:
                return {}
            try:
                return response.json()
            except ValueError:
                return {}

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, payload: Dict[str, Any]) -> Any:
        return self.request("POST", path, json=payload)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # -- account -------------------------------------------------------

    def verify_token(self) -> Dict[str, Any]:
        """Fail before anything is created rather than halfway through."""
        return self.get("/account").get("account", {})

    # -- ssh keys ------------------------------------------------------

    def create_ssh_key(self, name: str, public_key: str) -> Dict[str, Any]:
        """Register a public key, reusing the existing one on a fingerprint clash.

        DigitalOcean rejects a duplicate public key with a 422. Re-running `up`
        after a partial failure is exactly when that happens, so treat it as
        success and look the key up instead.
        """
        try:
            return self.post("/account/keys",
                             {"name": name, "public_key": public_key})["ssh_key"]
        except ProviderError as exc:
            if "422" not in str(exc):
                raise
            for key in self.list_ssh_keys():
                if key.get("public_key", "").split()[:2] == public_key.split()[:2]:
                    logger.info("Reusing already-registered SSH key %s", key["id"])
                    return key
            raise

    def list_ssh_keys(self) -> List[Dict[str, Any]]:
        return self._paginate("/account/keys", "ssh_keys")

    def delete_ssh_key(self, key_id: int) -> None:
        self.delete(f"/account/keys/{key_id}")

    # -- droplets ------------------------------------------------------

    def create_droplet(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/droplets", payload)["droplet"]

    def get_droplet(self, droplet_id: int) -> Optional[Dict[str, Any]]:
        try:
            return self.get(f"/droplets/{droplet_id}").get("droplet")
        except ProviderError as exc:
            if "404" in str(exc):
                return None
            raise

    def delete_droplet(self, droplet_id: int) -> None:
        try:
            self.delete(f"/droplets/{droplet_id}")
        except ProviderError as exc:
            # Already gone is the outcome destroy wanted.
            if "404" not in str(exc):
                raise

    def droplets_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """Find droplets without the local state file.

        This is the recovery path when `.potato/deployments.json` is lost or was
        never written, which is why every resource is tagged at creation.
        """
        return self._paginate(f"/droplets?tag_name={tag}", "droplets")

    # -- volumes -------------------------------------------------------

    def create_volume(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/volumes", payload)["volume"]

    def delete_volume(self, volume_id: str) -> None:
        try:
            self.delete(f"/volumes/{volume_id}")
        except ProviderError as exc:
            if "404" not in str(exc):
                raise

    def attach_volume(self, volume_id: str, droplet_id: int,
                      region: str) -> Dict[str, Any]:
        return self.post(f"/volumes/{volume_id}/actions",
                         {"type": "attach", "droplet_id": droplet_id,
                          "region": region})

    # -- firewalls -----------------------------------------------------

    def create_firewall(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/firewalls", payload)["firewall"]

    def delete_firewall(self, firewall_id: str) -> None:
        try:
            self.delete(f"/firewalls/{firewall_id}")
        except ProviderError as exc:
            if "404" not in str(exc):
                raise

    # -- helpers -------------------------------------------------------

    def _paginate(self, path: str, key: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        url = path
        while url:
            page = self.get(url)
            items.extend(page.get(key, []))
            url = (page.get("links", {}).get("pages", {}) or {}).get("next")
        return items


def _retry_after(response, attempt: int) -> int:
    """Seconds to wait, taking the server's own number when it gives one."""
    header = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if header and str(header).strip().isdigit():
        return min(int(str(header).strip()), 120)
    # DigitalOcean's rate limit resets hourly and reports the epoch second.
    reset = response.headers.get("ratelimit-reset")
    if reset and str(reset).strip().isdigit():
        remaining = int(str(reset).strip()) - int(time.time())
        if 0 < remaining <= 120:
            return remaining
    return min(2 ** attempt, 60)


def _error_message(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:400] or "(no response body)"
    if isinstance(body, dict):
        message = body.get("message") or body.get("error") or ""
        if body.get("id") and message:
            return f"{message} (id: {body['id']})"
        if message:
            return message
    return str(body)[:400]

"""A small JSON REST client for the token-authenticated provider APIs.

Hetzner, Vultr, Linode and Fly speak plain JSON over HTTPS with a bearer token,
and need the same handful of behaviours: retry on 429 with the server's
Retry-After, name the console page on a 401, unwrap the provider's error
message, and treat a 404 on delete as already gone.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

import requests

from potato.deploy.providers.base import ProviderError


class RestAPI:
    def __init__(self, root: str, token: str, *, provider: str, token_page: str,
                 timeout: int = 30, extra_headers: Optional[Dict[str, str]] = None,
                 error_message: Optional[Callable[[Any], str]] = None,
                 sleep: Callable[[float], None] = time.sleep):
        if not token:
            raise ProviderError(f"A {provider} API token is required.")
        self.root = root.rstrip("/")
        self.provider = provider
        self.token_page = token_page
        self.timeout = timeout
        self._error_message = error_message or default_error_message
        self._sleep = sleep
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "potato-deploy",
        })
        if extra_headers:
            self.session.headers.update(extra_headers)

    def request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.root}{path}"
        attempt = 0
        while True:
            attempt += 1
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            if response.status_code == 429 and attempt < 6:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    delay = 2 ** attempt
                self._sleep(min(delay, 60))
                continue
            break
        if response.status_code == 401:
            raise ProviderError(
                f"{self.provider} rejected the token (401). Create one at "
                f"{self.token_page}")
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.provider} {method} {path} failed ({response.status_code}): "
                f"{self._error_message(response)}")
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("POST", path, json=body or {})

    def delete(self, path: str) -> None:
        """Delete, treating 404 as success: destroy must be re-runnable."""
        try:
            self.request("DELETE", path)
        except ProviderError as exc:
            if "(404)" not in str(exc):
                raise

    def get_or_none(self, path: str) -> Optional[Any]:
        try:
            return self.get(path)
        except ProviderError as exc:
            if "(404)" in str(exc):
                return None
            raise


def default_error_message(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:400] or "(no response body)"
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return error.get("message") or str(error)[:400]
        if isinstance(body.get("errors"), list) and body["errors"]:
            first = body["errors"][0]
            return first.get("reason") if isinstance(first, dict) else str(first)
        return body.get("message") or error or str(body)[:400]
    return str(body)[:400]

"""Expose a locally-running server on a public HTTPS URL.

This is not a deployment and the docs say so plainly: the URL dies when the
laptop sleeps. It is for a pilot, a lab meeting, or handing a colleague a link
for twenty minutes.

Three backends, because the obvious one has a real problem:

``cloudflared``
    A quick tunnel needs no account at all, which makes it the default. But
    ``trycloudflare.com`` has been used heavily enough for malware staging that
    university proxies and mail gateways now filter it — exactly the networks
    study participants sit behind.

``tailscale``
    Funnel serves on ``*.ts.net``, which **is** on the Public Suffix List, so
    cookies are isolated per host. Needs a Tailscale account, and the node must
    already be logged in.

``ngrok``
    Free tier shows an interstitial before the page, which is poor for
    participants. Included because some institutions already allow it.

Whichever backend runs, the server binds to 127.0.0.1 so nothing is reachable
except through the tunnel, and ``POTATO_PROXY_FIX`` is set so ``url_for`` and
session cookies see the external scheme and host.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from typing import Iterator, List, Optional

from potato.deploy.providers.base import (
    Action,
    DeployPlan,
    DeploymentStatus,
    DeploySpec,
    Provider,
    ProviderError,
    register_provider,
)
from potato.deploy.state import DeploymentRecord

# cloudflared prints the assigned hostname to stderr during startup.
CLOUDFLARE_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
NGROK_URL_RE = re.compile(r"https://[a-z0-9-]+\.ngrok(?:-free)?\.(?:app|io)")
TAILSCALE_URL_RE = re.compile(r"https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net")

BACKENDS = ("cloudflared", "tailscale", "ngrok")


def detect_backend(preferred: Optional[str] = None) -> str:
    """Pick a tunnel backend, preferring one the user asked for."""
    if preferred:
        if preferred not in BACKENDS:
            raise ProviderError(
                f"Unknown tunnel backend '{preferred}'. Choose from: {', '.join(BACKENDS)}")
        binary = "tailscale" if preferred == "tailscale" else preferred
        if not shutil.which(binary):
            raise ProviderError(
                f"{preferred} was requested but '{binary}' is not on PATH.\n"
                f"{install_hint(preferred)}")
        return preferred

    for candidate in BACKENDS:
        binary = "tailscale" if candidate == "tailscale" else candidate
        if shutil.which(binary):
            if candidate == "ngrok" and not os.environ.get("NGROK_AUTHTOKEN"):
                continue
            return candidate

    raise ProviderError(
        "No tunnel backend found. Install one:\n"
        + "\n".join(f"  {b}: {install_hint(b)}" for b in BACKENDS))


def install_hint(backend: str) -> str:
    return {
        "cloudflared": "brew install cloudflared  (no account required)",
        "tailscale": "brew install tailscale, then `tailscale up`  (account required; "
                     "ts.net is on the Public Suffix List, so cookies are isolated)",
        "ngrok": "brew install ngrok, then set NGROK_AUTHTOKEN  (free tier shows an "
                 "interstitial page to visitors)",
    }.get(backend, "")


def _tunnel_command(backend: str, port: int) -> List[str]:
    if backend == "cloudflared":
        return ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"]
    if backend == "ngrok":
        return ["ngrok", "http", str(port), "--log", "stdout"]
    if backend == "tailscale":
        return ["tailscale", "funnel", str(port)]
    raise ProviderError(f"unknown backend {backend}")


def _url_pattern(backend: str):
    return {"cloudflared": CLOUDFLARE_URL_RE,
            "ngrok": NGROK_URL_RE,
            "tailscale": TAILSCALE_URL_RE}[backend]


def start_tunnel(backend: str, port: int, timeout: float = 60.0):
    """Start the tunnel and return ``(process, public_url)``."""
    command = _tunnel_command(backend, port)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1)

    pattern = _url_pattern(backend)
    deadline = time.time() + timeout
    captured: List[str] = []

    while time.time() < deadline:
        if process.poll() is not None:
            remainder = process.stdout.read() if process.stdout else ""
            raise ProviderError(
                f"{backend} exited before publishing a URL:\n"
                + "".join(captured[-20:]) + remainder)
        line = process.stdout.readline() if process.stdout else ""
        if not line:
            time.sleep(0.1)
            continue
        captured.append(line)
        match = pattern.search(line)
        if match:
            return process, match.group(0)

    process.terminate()
    raise ProviderError(
        f"{backend} did not publish a URL within {timeout:.0f}s. Last output:\n"
        + "".join(captured[-20:]))


@register_provider
class TunnelProvider(Provider):
    """Publishes a locally-running server through a tunnel."""

    name = "tunnel"
    ephemeral_fs = False
    public = True
    supports_logs = False
    supports_pull = False

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        port = int(spec.extra.get("port", 8000))
        backend = spec.extra.get("backend") or "cloudflared"

        plan = DeployPlan(estimated_cost_usd_month=0.0)
        plan.result_url_pattern = {
            "cloudflared": "https://<random>.trycloudflare.com",
            "ngrok": "https://<random>.ngrok-free.app",
            "tailscale": "https://<host>.<tailnet>.ts.net",
        }.get(backend, "https://<tunnel-host>")

        plan.actions = [
            Action("server.start",
                   f"start Potato on 127.0.0.1:{port} with POTATO_PROXY_FIX=1",
                   {"port": port, "host": "127.0.0.1"}),
            Action("tunnel.start", f"run: {' '.join(_tunnel_command(backend, port))}",
                   {"backend": backend}),
            Action("url.capture", f"read the public URL from {backend} output"),
        ]
        plan.warnings.append(
            "This is not a deployment: the URL stops working when this process exits.")
        if backend == "cloudflared":
            plan.warnings.append(
                "Some university and corporate networks filter trycloudflare.com. "
                "Use --backend tailscale if participants cannot reach the link.")
        if backend == "ngrok":
            plan.warnings.append(
                "The ngrok free tier shows visitors an interstitial page first.")
        return plan

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        raise ProviderError(
            "The tunnel provider is driven by `potato share`, which runs the server "
            "and the tunnel together in the foreground.")

    def status(self, record) -> DeploymentStatus:
        return DeploymentStatus(
            state="ephemeral", url=record.url, healthy=False,
            detail="Tunnels live only while `potato share` is running.")

    def destroy(self, record, *, keep_data: bool = False) -> None:
        # Stopping `potato share` is what ends the tunnel.
        return None

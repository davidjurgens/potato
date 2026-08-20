"""The contract every deploy target implements.

Two constraints shape this interface, and both exist to make the subsystem
testable and safe rather than merely tidy.

**``plan()`` takes no credentials and performs no I/O.** It turns a spec plus a
bundle into the list of calls that would be made. That makes it the ``--dry-run``
output and the entire unit-test surface at once: a test can assert the exact
firewall rules, cloud-init contents and injected environment keys without a
token or a network.

**``create()`` receives the store.** It must persist a record the moment a
resource acquires an id, before any later call can fail. A half-finished create
that leaves a billable machine running with no local record of it is the
characteristic failure of tools in this category, and the only defence is to
write the id down before doing anything else.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DeploySpec:
    """Everything a provider needs, independent of which provider it is."""

    name: str
    config_path: str
    region: Optional[str] = None
    size: Optional[str] = None
    domain: Optional[str] = None
    image: Optional[str] = None
    workers: int = 1
    threads: int = 8
    env: Dict[str, str] = field(default_factory=dict)
    secrets: Dict[str, str] = field(default_factory=dict)
    volume_gb: Optional[int] = None
    private: bool = False
    demo: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def public_env(self) -> Dict[str, str]:
        """Environment safe to print. Secret *values* are never included."""
        return dict(self.env)


@dataclass
class Action:
    """One step of a plan, renderable without performing it."""

    kind: str
    description: str
    request: Optional[Dict[str, Any]] = None

    def render(self) -> str:
        return f"{self.kind:22s} {self.description}"


@dataclass
class DeployPlan:
    actions: List[Action] = field(default_factory=list)
    estimated_cost_usd_month: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    result_url_pattern: str = ""

    def render(self) -> str:
        lines = [f"{len(self.actions)} step(s):"]
        lines += [f"  {i + 1:2d}. {a.render()}" for i, a in enumerate(self.actions)]
        if self.result_url_pattern:
            lines.append("")
            lines.append(f"Result URL: {self.result_url_pattern}")
        if self.estimated_cost_usd_month is not None:
            cost = self.estimated_cost_usd_month
            lines.append(f"Estimated cost: ${cost:.2f}/month"
                         if cost else "Estimated cost: free")
        for warning in self.warnings:
            lines.append(f"WARNING: {warning}")
        return "\n".join(lines)


@dataclass
class DeploymentStatus:
    state: str
    url: Optional[str] = None
    healthy: bool = False
    detail: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PullResult:
    dest: str
    files: int = 0
    bytes: int = 0
    skipped: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


class ProviderError(RuntimeError):
    """A provider operation failed in a way the user must act on."""


class Provider(ABC):
    """Base class for every deploy target."""

    name: str = "base"
    #: pip extras that must be installed before this provider can run.
    requires: tuple = ()
    #: True when the host loses its filesystem on restart.
    ephemeral_fs: bool = False
    #: True when the target is reachable from the public internet.
    public: bool = True
    supports_logs: bool = False
    supports_pull: bool = False

    def __init__(self, token: Optional[str] = None, console=None):
        self.token = token
        self.console = console or logger.info

    # -- required ------------------------------------------------------

    @abstractmethod
    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        """Describe what create() would do. No credentials, no I/O."""

    @abstractmethod
    def create(self, spec: DeploySpec, bundle, existing, store):
        """Provision or update, persisting a record as soon as an id exists."""

    @abstractmethod
    def status(self, record) -> DeploymentStatus:
        """Report the current state of a deployment."""

    @abstractmethod
    def destroy(self, record, *, keep_data: bool = False) -> None:
        """Remove every resource this provider created for the deployment."""

    # -- optional ------------------------------------------------------

    def logs(self, record, *, lines: int = 200, follow: bool = False) -> Iterator[str]:
        raise ProviderError(f"{self.name} does not support log retrieval")

    def pull(self, record, dest: str) -> PullResult:
        raise ProviderError(f"{self.name} does not support pulling data")

    # -- helpers -------------------------------------------------------

    def check_requirements(self) -> List[str]:
        """Return import errors for missing optional dependencies."""
        import importlib
        missing = []
        for module in self.requires:
            try:
                importlib.import_module(module)
            except ImportError:
                missing.append(module)
        return missing

    def runtime_env(self, spec: DeploySpec, generated) -> Dict[str, str]:
        """Environment for the container.

        Generated secrets travel here rather than in the bundle, which is what
        keeps them out of a repo-backed target's git history.
        """
        env = {
            "POTATO_CONFIG": spec.extra.get("config_rel", "config.yaml"),
            "GUNICORN_WORKERS": str(spec.workers),
            "GUNICORN_THREADS": str(spec.threads),
            "POTATO_NONINTERACTIVE": "1",
        }
        if generated is not None:
            env["POTATO_SECRET_KEY"] = generated.secret_key
            env["POTATO_ADMIN_API_KEY"] = generated.admin_api_key
        env.update(spec.env)
        env.update(spec.secrets)
        return env


_REGISTRY: Dict[str, type] = {}
_BUILTINS_LOADED = False


def register_provider(cls: type) -> type:
    _REGISTRY[cls.name] = cls
    return cls


def get_provider(name: str, token: Optional[str] = None, console=None) -> Provider:
    _load_builtin_providers()
    if name not in _REGISTRY:
        raise ProviderError(
            f"Unknown provider '{name}'. Available: {', '.join(available_providers())}")
    return _REGISTRY[name](token=token, console=console)


def available_providers() -> List[str]:
    _load_builtin_providers()
    return sorted(_REGISTRY)


def _load_builtin_providers() -> None:
    """Import the built-in providers once.

    Guarded by an explicit flag rather than by an empty registry: importing one
    provider module directly registers it, which would leave the registry
    non-empty and cause the rest never to load. That made the provider list
    depend on import order.
    """
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    from potato.deploy.providers import (  # noqa: F401
        digitalocean, huggingface, local, render, tunnel)

"""Find a provider API token without ever writing one down.

Tokens are resolved per-invocation from the places a user has already put them.
Nothing here persists a token: a deploy tool that caches provider credentials in
the working directory turns one leaked repo into one compromised cloud account.

Resolution order, first hit wins:

1. an explicit ``--token``
2. ``POTATO_DEPLOY_TOKEN_<PROVIDER>``
3. the provider's own conventional environment variables
4. the provider's own config file, where reading it is unambiguous
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


class CredentialError(RuntimeError):
    """No usable credential was found for a provider."""


@dataclass(frozen=True)
class CredentialSource:
    """Where a token came from. The value is deliberately not stored."""

    provider: str
    description: str


@dataclass(frozen=True)
class ProviderCredentials:
    """Environment variables and help text for one provider."""

    provider: str
    env_vars: Sequence[str]
    console_url: str
    scope_hint: str
    file_loader: Optional[Callable[[], Optional[str]]] = None
    file_description: str = ""


def _read_huggingface_token() -> Optional[str]:
    try:
        from huggingface_hub import get_token
        return get_token()
    except Exception:
        return None


def _read_doctl_token() -> Optional[str]:
    """Read the token doctl stores, when there is exactly one context.

    With several contexts there is no way to know which one the user means, so
    reading any of them would silently deploy to the wrong account.
    """
    path = os.path.expanduser("~/.config/doctl/config.yaml")
    if not os.path.isfile(path):
        return None
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except Exception:
        return None
    contexts = data.get("auth-contexts") or {}
    if contexts:
        logger.debug("doctl config has named contexts; not guessing between them")
        return None
    token = data.get("access-token")
    return token if isinstance(token, str) and token else None


PROVIDER_CREDENTIALS: Dict[str, ProviderCredentials] = {
    "digitalocean": ProviderCredentials(
        provider="digitalocean",
        env_vars=("DIGITALOCEAN_TOKEN", "DIGITALOCEAN_ACCESS_TOKEN", "DO_TOKEN"),
        console_url="https://cloud.digitalocean.com/account/api/tokens",
        scope_hint="a personal access token with read and write scope",
        file_loader=_read_doctl_token,
        file_description="~/.config/doctl/config.yaml",
    ),
    "huggingface": ProviderCredentials(
        provider="huggingface",
        env_vars=("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACEHUB_API_TOKEN"),
        console_url="https://huggingface.co/settings/tokens",
        scope_hint="a token with write access",
        file_loader=_read_huggingface_token,
        file_description="the huggingface_hub token cache",
    ),
    "render": ProviderCredentials(
        provider="render",
        env_vars=("RENDER_API_KEY", "RENDER_TOKEN"),
        console_url="https://dashboard.render.com/u/settings#api-keys",
        scope_hint="an API key",
    ),
    "fly": ProviderCredentials(
        provider="fly",
        env_vars=("FLY_API_TOKEN", "FLY_ACCESS_TOKEN"),
        console_url="https://fly.io/user/personal_access_tokens",
        scope_hint="a personal access token",
    ),
    # Run locally or through a tunnel; no provider account involved.
    "local": ProviderCredentials(
        provider="local", env_vars=(), console_url="", scope_hint=""),
    "tunnel": ProviderCredentials(
        provider="tunnel", env_vars=("NGROK_AUTHTOKEN",),
        console_url="https://dashboard.ngrok.com/get-started/your-authtoken",
        scope_hint="only needed for ngrok; cloudflared quick tunnels need no account"),
}


def generic_env_var(provider: str) -> str:
    return f"POTATO_DEPLOY_TOKEN_{provider.upper().replace('-', '_')}"


def requires_credential(provider: str) -> bool:
    spec = PROVIDER_CREDENTIALS.get(provider)
    return bool(spec and spec.env_vars)


def resolve_token(provider: str, explicit: Optional[str] = None,
                  environ: Optional[Dict[str, str]] = None):
    """Return ``(token, source)``, or ``(None, None)`` when none is found.

    Never raises for a missing token — callers decide whether one is required,
    because ``plan`` and ``check`` must work without credentials.
    """
    env = os.environ if environ is None else environ
    spec = PROVIDER_CREDENTIALS.get(provider)

    if explicit:
        return explicit, CredentialSource(provider, "--token")

    generic = generic_env_var(provider)
    if env.get(generic):
        return env[generic], CredentialSource(provider, f"${generic}")

    if spec is None:
        return None, None

    for name in spec.env_vars:
        if env.get(name):
            return env[name], CredentialSource(provider, f"${name}")

    if spec.file_loader is not None:
        try:
            token = spec.file_loader()
        except Exception:
            token = None
        if token:
            return token, CredentialSource(provider, spec.file_description)

    return None, None


def require_token(provider: str, explicit: Optional[str] = None,
                  environ: Optional[Dict[str, str]] = None):
    """Like resolve_token, but raise with instructions when nothing is found."""
    token, source = resolve_token(provider, explicit, environ)
    if token:
        return token, source
    raise CredentialError(missing_token_message(provider))


def missing_token_message(provider: str) -> str:
    spec = PROVIDER_CREDENTIALS.get(provider)
    if spec is None:
        return (f"Unknown provider '{provider}'. Known providers: "
                f"{', '.join(sorted(PROVIDER_CREDENTIALS))}.")

    lines = [f"No API token found for {provider}."]
    if spec.console_url:
        lines.append(f"Create {spec.scope_hint} at {spec.console_url}, then either:")
    else:
        lines.append("This provider needs no token.")
        return "\n".join(lines)

    lines.append(f"  export {spec.env_vars[0]}=<token>")
    lines.append(f"  potato deploy up <config> --provider {provider} --token <token>")
    if spec.file_description:
        lines.append(f"Also read from: {spec.file_description}")
    return "\n".join(lines)


def redact(value: Optional[str], keep: int = 4) -> str:
    """Render a token safely for logs and dry-run output."""
    if not value:
        return "<unset>"
    if len(value) <= keep:
        return "*" * len(value)
    return f"{'*' * (len(value) - keep)}{value[-keep:]}"


def describe_available(environ: Optional[Dict[str, str]] = None,
                       providers: Optional[Sequence[str]] = None) -> List[str]:
    """One line per provider saying whether a credential is present.

    ``providers`` restricts the listing to targets that exist. The credential
    table carries entries for targets that are not implemented yet — listing
    them advertises a `--provider fly` that argparse then rejects.
    """
    names = sorted(PROVIDER_CREDENTIALS if providers is None
                   else set(PROVIDER_CREDENTIALS) & set(providers))
    out = []
    for provider in names:
        if not requires_credential(provider):
            out.append(f"{provider:14s} no token required")
            continue
        token, source = resolve_token(provider, environ=environ)
        if token:
            out.append(f"{provider:14s} found via {source.description} ({redact(token)})")
        else:
            out.append(f"{provider:14s} not configured")
    return out

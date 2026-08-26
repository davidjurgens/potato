"""
Per-agent bearer tokens for the MCP endpoint.

The shared admin key cannot express "this agent may read progress and nothing
else", because it is a superuser by construction: `RBACManager.check()` returns
True for every permission the moment it validates. An agent with standing access
to a live task needs less than that.

So: named tokens, each bound to a role, stored as SHA-256 digests in
`{task_dir}/mcp_tokens.json`. The plaintext is shown once, at issue time, and
never written down -- the file is only useful for checking a token someone
already has.

Deliberately separate from `admin_key.py`:

  * `validate_admin_api_key()` returns True unconditionally under `debug: true`.
    That is defensible for a dashboard on a laptop and indefensible for a remote
    control surface, so nothing here consults debug mode.
  * Admin keys are one shared secret. These are per-agent and revocable
    individually, which is what makes an audit log worth keeping.

Usage:
    from potato.server_utils.agent_tokens import issue_token, verify_token
    record = verify_token(presented, config)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_FILE = "mcp_tokens.json"

# Roles a token may hold, resolved through DEFAULT_ROLE_PERMISSIONS.
VALID_ROLES = ("admin", "adjudicator", "annotator")

_LOCK = threading.Lock()


@dataclass
class TokenRecord:
    """A token's metadata. The token itself is not stored, only its digest."""

    name: str
    role: str
    created: str
    note: str = ""
    revoked: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_file_path(config: Optional[Dict[str, Any]] = None) -> str:
    """Where tokens live: `mcp.auth.tokens_file` under `task_dir`."""
    config = config or {}
    mcp_config = config.get("mcp") or {}
    auth = mcp_config.get("auth") or {}
    filename = auth.get("tokens_file") or DEFAULT_TOKEN_FILE
    if os.path.isabs(filename):
        return filename
    return os.path.join(config.get("task_dir") or ".", filename)


def load_tokens(config: Optional[Dict[str, Any]] = None) -> Dict[str, TokenRecord]:
    """Digest -> record. Missing or unreadable file means no tokens."""
    path = token_file_path(config)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}

    out: Dict[str, TokenRecord] = {}
    for digest, fields in (raw or {}).items():
        try:
            out[digest] = TokenRecord(**fields)
        except TypeError:
            logger.warning("Skipping malformed token record %s", digest[:8])
    return out


def save_tokens(tokens: Dict[str, TokenRecord],
                config: Optional[Dict[str, Any]] = None) -> str:
    """Write the token file with owner-only permissions."""
    path = token_file_path(config)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    payload = {digest: record.to_dict() for digest, record in tokens.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - filesystem dependent
        logger.warning("Could not restrict permissions on %s", path)
    return path


def issue_token(name: str, role: str = "annotator", note: str = "",
                config: Optional[Dict[str, Any]] = None) -> str:
    """Mint a token for `name` and return it. Shown once; not recoverable."""
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}, got {role!r}")
    if not name or not name.strip():
        raise ValueError("A token needs a name, so it can be revoked later")

    from datetime import datetime, timezone

    token = secrets.token_urlsafe(32)
    record = TokenRecord(
        name=name.strip(),
        role=role,
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        note=note,
    )

    with _LOCK:
        tokens = load_tokens(config)
        tokens[_digest(token)] = record
        save_tokens(tokens, config)

    return token


def revoke_token(name: str, config: Optional[Dict[str, Any]] = None) -> int:
    """Revoke every token issued under `name`. Returns how many."""
    with _LOCK:
        tokens = load_tokens(config)
        count = 0
        for record in tokens.values():
            if record.name == name and not record.revoked:
                record.revoked = True
                count += 1
        if count:
            save_tokens(tokens, config)
    return count


def list_tokens(config: Optional[Dict[str, Any]] = None) -> List[dict]:
    """Every token's metadata, newest last. Never includes a token."""
    return sorted(
        (record.to_dict() for record in load_tokens(config).values()),
        key=lambda r: r["created"],
    )


def verify_token(presented: Optional[str],
                 config: Optional[Dict[str, Any]] = None) -> Optional[TokenRecord]:
    """Return the record for `presented`, or None.

    Compares digests with `hmac.compare_digest`, and iterates the whole table
    rather than looking the digest up, so the time taken does not depend on
    which token was presented.

    Debug mode is not consulted. A remote control surface that unlocks itself
    when someone leaves `debug: true` on is not a control surface.
    """
    if not presented:
        return None

    candidate = _digest(presented)
    match: Optional[TokenRecord] = None
    for digest, record in load_tokens(config).items():
        if hmac.compare_digest(digest, candidate) and not record.revoked:
            match = record
    return match


def extract_bearer(headers) -> Optional[str]:
    """Pull a token from `Authorization: Bearer` or `X-Agent-Token`.

    MCP clients emit the first natively. `X-API-Key` is deliberately not read
    here: that header carries the shared admin key, and letting it in through
    this path would reintroduce the superuser the tokens exist to avoid.
    """
    authorization = headers.get("Authorization", "") or ""
    if authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
        if token:
            return token

    token = (headers.get("X-Agent-Token") or "").strip()
    return token or None

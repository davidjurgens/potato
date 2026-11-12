"""
Resume and stop links: signed, expiring, and bound to one participant.

A link carries ``purpose|session|expiry|epoch|participant`` and an
HMAC-SHA256 tag over it, the same construction the external runtime phase
uses for signed returns (``potato/runtimes/adapters/external.py``). That
phase is keyed with a secret shared with another server; these links are
checked only by this server, so the key is private to it:

1. ``POTATO_SCHEDULE_LINK_KEY`` when set (use this when several servers or
   restarts on a fresh disk must accept the same links), else
2. a random key generated once and kept beside the contact store
   (``<task_dir>/.potato/scheduling/link.key``, mode 0600), so links sent
   before a restart still work after it.

``epoch`` is the participant's link generation: raising it (when they stop
messages) invalidates every link sent to them before.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Optional, Tuple

ENV_KEY = "POTATO_SCHEDULE_LINK_KEY"
_TAG_BYTES = 16
PURPOSES = ("resume", "stop")


def load_key(private_dir: str) -> bytes:
    env = os.environ.get(ENV_KEY)
    if env:
        return env.encode("utf-8")
    path = os.path.join(private_dir, "link.key")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            value = fh.read().strip()
        if len(value) >= 32:
            return value.encode("utf-8")
    os.makedirs(private_dir, exist_ok=True)
    value = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    return value.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(key: bytes, purpose: str, participant: str, session_id: str,
               expires_at: float, epoch: int = 0) -> str:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown link purpose {purpose!r}")
    # The participant goes last so a "|" in a user name cannot shift fields.
    payload = "|".join([purpose, session_id or "", str(int(expires_at)), str(epoch), participant])
    body = payload.encode("utf-8")
    tag = hmac.new(key, body, hashlib.sha256).digest()[:_TAG_BYTES]
    return f"{_b64(body)}.{_b64(tag)}"


def read_token(key: bytes, token: str, now: float
               ) -> Tuple[Optional[dict], Optional[str]]:
    """``(claims, None)`` for a good link, ``(claims_or_None, problem)``
    otherwise. ``problem`` is ``"invalid"`` or ``"expired"``; an expired
    link still returns its claims so the page can say which session closed.
    """
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 1024:
        return None, "invalid"
    body_text, tag_text = token.split(".")
    try:
        body = _unb64(body_text)
        tag = _unb64(tag_text)
    except (ValueError, TypeError):
        return None, "invalid"
    expected = hmac.new(key, body, hashlib.sha256).digest()[:_TAG_BYTES]
    if not hmac.compare_digest(tag, expected):
        return None, "invalid"
    try:
        purpose, session_id, expires, epoch, participant = body.decode("utf-8").split("|", 4)
        claims = {"purpose": purpose, "participant": participant, "session": session_id,
                  "expires_at": int(expires), "epoch": int(epoch)}
    except (ValueError, UnicodeDecodeError):
        return None, "invalid"
    if purpose not in PURPOSES:
        return None, "invalid"
    if now >= claims["expires_at"]:
        return claims, "expired"
    return claims, None

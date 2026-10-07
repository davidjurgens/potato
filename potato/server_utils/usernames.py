"""Which usernames an account may have, and where its files live.

An annotator's work is stored in ``<output_annotation_dir>/<username>/``, so a
username is a path component. Three things follow:

* A name containing a path separator, or ``.``/``..``, names some other
  directory: ``zz/../alice`` is alice's, ``../x`` is outside the output
  directory. Such names are refused at every point an account is created, and
  :func:`user_dir` refuses them again before anything touches the disk.
* Two names that differ only in case (``Alice``, ``alice``) or Unicode
  normalisation (``José`` as one code point or as ``e`` plus a combining
  accent) are one directory on macOS and Windows. A new account whose
  :func:`collision_key` matches an existing account is refused.
* Control characters and very long names break file systems and logs.
"""

from __future__ import annotations

import os
import unicodedata
from typing import Iterable, Optional

MAX_USERNAME_LENGTH = 200


def username_problem(username) -> Optional[str]:
    """Why this username cannot be used, or None when it can."""
    if not isinstance(username, str) or not username.strip():
        return "A username is required."
    if len(username) > MAX_USERNAME_LENGTH:
        return f"Usernames are limited to {MAX_USERNAME_LENGTH} characters."
    if "/" in username or "\\" in username:
        return "Usernames cannot contain / or \\."
    if username.startswith("."):
        return "Usernames cannot start with a dot."
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in username):
        return "Usernames cannot contain control characters."
    return None


def collision_key(username: str) -> str:
    """The form under which two usernames share a directory on some file systems."""
    return unicodedata.normalize("NFC", username).casefold()


def colliding_username(username: str, existing: Iterable[str]) -> Optional[str]:
    """An existing username that is a different spelling of the same directory."""
    key = collision_key(username)
    for other in existing:
        if isinstance(other, str) and other != username and collision_key(other) == key:
            return other
    return None


def user_dir(output_dir: str, username: str) -> str:
    """The directory holding this user's files. Raises ValueError for a name
    that would leave ``output_dir`` or land in another user's directory."""
    problem = username_problem(username)
    if problem:
        raise ValueError(f"Refusing to use {username!r} as a directory name: {problem}")
    root = os.path.realpath(output_dir)
    path = os.path.realpath(os.path.join(root, username))
    if os.path.dirname(path) != root:
        raise ValueError(f"Refusing to use {username!r} as a directory name: "
                         "it does not resolve to a directory directly inside "
                         f"{output_dir}")
    return os.path.join(output_dir, username)

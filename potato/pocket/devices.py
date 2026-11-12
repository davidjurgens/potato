"""Device detection and per-user device tracking.

Two jobs:

1. **Classify requests** as mobile / tablet / desktop from the User-Agent so
   the annotate route can send touch devices to ``/pocket`` (and warn them
   when the task is not touch-capable).
2. **Track which device classes each annotator uses** so admins can see who
   is annotating from a phone — relevant both for data quality (some
   annotation types are not mobile friendly) and for deciding whether to
   enable Pocket Mode at all. Visits are aggregated per user and persisted
   to ``<output_annotation_dir>/pocket/device_visits.json``.

Known limitation, by design: iPadOS 13+ Safari masquerades as desktop
Safari ("Macintosh") in its User-Agent, so it cannot be caught server-side.
The client-side check in base_template_v2.html (primary pointer is coarse)
covers those devices; this module handles everything that identifies itself.
"""

import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MOBILE = "mobile"
TABLET = "tablet"
DESKTOP = "desktop"

# Phones: Android UAs include "Mobile" on phones but not tablets.
_MOBILE_RE = re.compile(
    r"iPhone|iPod|Windows Phone|BlackBerry|BB10|Opera Mini|webOS"
    r"|Android(?=.*\bMobile\b)|\bMobile\b(?=.*Android)",
    re.IGNORECASE,
)
# Tablets: iPad (pre-iPadOS-13 UAs), Android without Mobile, Kindle/Silk.
_TABLET_RE = re.compile(
    r"iPad|Tablet|Silk/|Kindle|PlayBook|Android(?!.*\bMobile\b)",
    re.IGNORECASE,
)


def classify_user_agent(user_agent: Optional[str]) -> str:
    """'mobile' | 'tablet' | 'desktop' for a User-Agent string.

    Anything unrecognized (including empty UAs and API clients like
    python-requests) is 'desktop' — the class that changes no behavior.
    """
    ua = user_agent or ""
    if _MOBILE_RE.search(ua):
        return MOBILE
    if _TABLET_RE.search(ua):
        return TABLET
    return DESKTOP


def is_touch_device(user_agent: Optional[str]) -> bool:
    return classify_user_agent(user_agent) in (MOBILE, TABLET)


class DeviceTracker:
    """Thread-safe per-user aggregation of device-class visits."""

    def __init__(self, output_dir: Optional[str]):
        self._lock = threading.Lock()
        self._path = (os.path.join(output_dir, "pocket", "device_visits.json")
                      if output_dir else None)
        self._users: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path or not os.path.exists(self._path):
            return
        try:
            with open(self._path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._users = data
        except (OSError, ValueError) as e:
            logger.warning("device tracker: could not load %s: %s", self._path, e)

    def _save_locked(self) -> None:
        if not self._path:
            return
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._users, f, indent=1, sort_keys=True)
            os.replace(tmp, self._path)
        except OSError as e:  # tracking must never break a page load
            logger.warning("device tracker: could not save %s: %s", self._path, e)

    def record(self, username: str, user_agent: Optional[str],
               surface: str) -> str:
        """Record one page visit. ``surface`` is 'annotate' or 'pocket'.

        Returns the classified device for convenience.
        """
        device = classify_user_agent(user_agent)
        with self._lock:
            entry = self._users.setdefault(username, {
                "visits": {MOBILE: 0, TABLET: 0, DESKTOP: 0},
                "pocket_visits": 0,
                "last_device": None,
                "last_seen": None,
                "last_user_agent": None,
            })
            entry["visits"][device] = entry["visits"].get(device, 0) + 1
            if surface == "pocket":
                entry["pocket_visits"] += 1
            entry["last_device"] = device
            entry["last_seen"] = time.time()
            entry["last_user_agent"] = (user_agent or "")[:300]
            self._save_locked()
        return device

    def record_client_hint(self, username: str, device: str) -> None:
        """Record a client-side detection (coarse-pointer check) that
        contradicts the User-Agent — e.g. an iPad with a desktop UA."""
        if device not in (MOBILE, TABLET):
            return
        with self._lock:
            entry = self._users.get(username)
            if entry is None:
                return
            entry["client_detected_touch"] = True
            entry["last_device"] = device
            self._save_locked()

    def stats(self) -> Dict[str, Any]:
        """Admin payload: per-user rows + a summary."""
        with self._lock:
            rows = []
            touch_users = 0
            for username, entry in sorted(self._users.items()):
                visits = entry.get("visits", {})
                used_touch = bool(
                    visits.get(MOBILE, 0) or visits.get(TABLET, 0)
                    or entry.get("client_detected_touch"))
                if used_touch:
                    touch_users += 1
                rows.append({
                    "username": username,
                    "mobile_visits": visits.get(MOBILE, 0),
                    "tablet_visits": visits.get(TABLET, 0),
                    "desktop_visits": visits.get(DESKTOP, 0),
                    "pocket_visits": entry.get("pocket_visits", 0),
                    "used_touch_device": used_touch,
                    "last_device": entry.get("last_device"),
                    "last_seen": entry.get("last_seen"),
                })
            return {
                "users": rows,
                "summary": {
                    "n_users_seen": len(rows),
                    "n_touch_users": touch_users,
                },
            }


# ----------------------------------------------------------------------
# Lazy singleton: tracking works whether or not Pocket Mode is enabled, so
# initialization pulls the output dir from the live config on first use
# rather than relying on a boot-path hook.

_TRACKER: Optional[DeviceTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_device_tracker() -> DeviceTracker:
    global _TRACKER
    if _TRACKER is None:
        with _TRACKER_LOCK:
            if _TRACKER is None:
                output_dir = None
                try:
                    from potato.server_utils.config_module import config
                    output_dir = config.get("output_annotation_dir") or None
                except Exception:
                    pass
                _TRACKER = DeviceTracker(output_dir)
    return _TRACKER


def clear_device_tracker() -> None:
    global _TRACKER
    _TRACKER = None

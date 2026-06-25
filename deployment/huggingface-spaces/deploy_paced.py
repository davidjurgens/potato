#!/usr/bin/env python3
"""Rate-limit-aware paced deploy of remaining Potato Spaces.

HF enforces a rolling ~1000-requests/window 'api' rate limit. Each upload_folder
burns many requests, so a burst saturates it. The 429 response carries a precise
'Retry after N seconds' hint — this script HONORS that hint (instead of blind
exponential backoff) and paces one Space at a time.

Run in background; writes progress to /tmp/paced_deploy.log.
"""
import re
import sys
import time
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
MANIFEST = SCRIPT_DIR / "spaces_manifest.yaml"
BUILD_ROOT = REPO_ROOT / "spaces-build"
ORG = "Blablablab"
BASE_DELAY = 8           # polite gap between successful Spaces
MAX_RETRY_PER_STEP = 12  # how many times to honor a 429 on one step


def log(msg):
    print(msg, flush=True)


def load_manifest():
    data = yaml.safe_load(open(MANIFEST))
    defaults = data.get("defaults", {}) or {}
    return {e["id"]: {**defaults, **e} for e in data.get("spaces", [])}


def retry_after_seconds(err) -> int:
    """Pull the server's retry hint from a 429: header first, then message."""
    resp = getattr(err, "response", None)
    if resp is not None:
        ra = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
        if ra and str(ra).strip().isdigit():
            return int(ra)
    m = re.search(r"[Rr]etry after (\d+)", str(err))
    if m:
        return int(m.group(1))
    return 60  # conservative default


class WindowClosed(Exception):
    """The HF Space-creation window is shut (sustained long retry-afters).

    Raised to abort the whole run cheaply instead of burning ~60 min per
    blocked Space — a later re-run picks up where this left off (idempotent).
    """


# A create that returns this many CONSECUTIVE long retry-afters means the
# new-Space-creation window is closed for a while; bail and let a re-run resume.
LONG_WAIT = 200          # seconds; HF emits a flat ~300s when the window is shut
LONG_STREAK_TO_BAIL = 2


def with_429_retry(fn, label):
    from huggingface_hub.utils import HfHubHTTPError
    long_streak = 0
    for attempt in range(MAX_RETRY_PER_STEP):
        try:
            return fn()
        except HfHubHTTPError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code == 429:
                wait = retry_after_seconds(e) + 5
                if wait >= LONG_WAIT:
                    long_streak += 1
                    if long_streak >= LONG_STREAK_TO_BAIL:
                        raise WindowClosed(
                            f"{label}: {long_streak} consecutive ~{wait}s waits "
                            f"— creation window closed, aborting run for resume")
                else:
                    long_streak = 0
                log(f"    429 on {label}: honoring retry-after, sleeping {wait}s "
                    f"(attempt {attempt + 1}/{MAX_RETRY_PER_STEP})")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"{label}: exhausted 429 retries")


def ensure_built(sid):
    import subprocess
    out = BUILD_ROOT / sid
    if not (out / "config.yaml").is_file():
        subprocess.run([sys.executable, str(SCRIPT_DIR / "build_space.py"), sid], check=True)
    return out


def deploy_one(sid, entry):
    from huggingface_hub import create_repo, upload_folder
    repo_id = f"{ORG}/{sid}"
    build_dir = ensure_built(sid)
    with_429_retry(
        lambda: create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True),
        f"create {sid}",
    )
    with_429_retry(
        lambda: upload_folder(
            repo_id=repo_id, repo_type="space", folder_path=str(build_dir),
            commit_message=f"Deploy Potato demo: {entry['title']}",
        ),
        f"upload {sid}",
    )
    return repo_id


def main():
    from huggingface_hub import HfApi
    spaces = load_manifest()
    live = {s.id.split("/")[-1] for s in HfApi().list_spaces(author=ORG)}
    remaining = [(sid, e) for sid, e in spaces.items() if sid not in live]
    # force re-upload of media Spaces that need the sanitizer fix even if "live"
    force = [(sid, spaces[sid]) for sid in ("video-annotation",) if sid in live]
    queue = remaining + force

    log(f"=== paced deploy: {len(remaining)} new + {len(force)} re-upload, total {len(queue)} ===")
    ok, fail = [], []
    stopped_early = False
    for i, (sid, entry) in enumerate(queue, 1):
        log(f"[{i}/{len(queue)}] {sid}")
        try:
            deploy_one(sid, entry)
            ok.append(sid)
            log(f"  ✓ {sid}  ({len(ok)} ok so far)")
        except WindowClosed as e:
            log(f"  ⏸ window closed at {sid}: {e}")
            log(f"  ⏸ deployed {len(ok)} this batch; {len(queue) - i + 1} still queued. "
                f"Re-run later to resume (idempotent).")
            stopped_early = True
            break
        except Exception as e:
            fail.append(sid)
            log(f"  ✗ {sid}: {type(e).__name__}: {str(e)[:160]}")
        time.sleep(BASE_DELAY)
    status = "PAUSED (window closed)" if stopped_early else "DONE"
    log(f"=== {status}: {len(ok)} ok, {len(fail)} failed ===")
    if fail:
        log("failed: " + ", ".join(fail))
    # exit 2 signals "paused, more to do" so a wrapper/cron can decide to re-run
    sys.exit(2 if stopped_early else 0)


if __name__ == "__main__":
    main()

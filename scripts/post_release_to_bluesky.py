#!/usr/bin/env python3
"""Post a Potato release thread to Bluesky.

Usage:
    BSKY_HANDLE=potatoannotator.bsky.social BSKY_APP_PASSWORD=xxxx \
        python scripts/post_release_to_bluesky.py --tag v2.6.0

Environment variables:
    BSKY_HANDLE       Full Bluesky handle, e.g. potatoannotator.bsky.social
    BSKY_APP_PASSWORD App password created at https://bsky.app/settings/app-passwords
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone


BSKY_API = "https://bsky.social/xrpc"


def _post(endpoint: str, body: dict, token: str | None = None) -> dict:
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BSKY_API}/{endpoint}", data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} from {endpoint}: {body_text}") from e


def login(handle: str, password: str) -> tuple[str, str]:
    resp = _post("com.atproto.server.createSession", {"identifier": handle, "password": password})
    return resp["accessJwt"], resp["did"]


def post_skeet(text: str, token: str, did: str,
               reply_root: dict | None = None,
               reply_parent: dict | None = None) -> dict:
    record: dict = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if reply_root and reply_parent:
        record["reply"] = {"root": reply_root, "parent": reply_parent}

    resp = _post("com.atproto.repo.createRecord", {
        "repo": did,
        "collection": "app.bsky.feed.post",
        "record": record,
    }, token=token)
    return {"cid": resp["cid"], "uri": resp["uri"]}


def ref(post: dict) -> dict:
    return {"cid": post["cid"], "uri": post["uri"]}


def build_thread(tag: str) -> list[str]:
    """Return the list of post texts for the release thread."""
    # Strip leading 'v' for display
    version = tag.lstrip("v")
    release_url = f"https://github.com/davidjurgens/potato/releases/tag/{tag}"

    posts = []

    # --- Post 1: headline ---
    posts.append(
        f"🥔 Potato {version} is out!\n\n"
        "This release brings full QDA (Qualitative Data Analysis) mode, "
        "LLM-as-judge calibration & alignment, and trajectory-editing schemas "
        "for SFT/DPO training data. 84 commits since v2.5.0.\n\n"
        f"Full release notes → {release_url}"
    )

    # --- Post 2: QDA Mode ---
    posts.append(
        "🔬 New: QDA Mode\n\n"
        "New opt-in `qda_mode` for qualitative coding:\n\n"
        "• SQLite persistence (memos, search index, codebook, cases)\n"
        "• Analyst memos + sidebar UI & exporter\n"
        "• FTS5 search + claim guard (no double-work)\n"
        "• In-vivo coding, on-the-fly add, retroactive merge/split"
    )

    # --- Post 3: Agent eval / LLM-as-judge ---
    posts.append(
        "🤖 New: LLM-as-Judge Calibration\n\n"
        "Auto-label trajectories with an LLM judge, then calibrate vs. blind human "
        "judgments. A signal-based triage queue routes the most informative items "
        "to humans first.\n\n"
        "New `trajectory_edit` + `trajectory_correction` schemas for SFT/DPO data."
    )

    # --- Post 4: Other highlights + upgrade ---
    posts.append(
        f"⚡ Also in {version}:\n\n"
        "• Boot time halved: import 6.5s→2s, RSS 750→365 MB\n"
        "• 14 previously-dead admin/API routes now registered\n"
        "• Heterogeneous annotator coverage + reclaim abandoned assignments\n"
        "• Relicensed to GPL-3.0-or-later\n\n"
        f"pip install --upgrade potato-annotation=={version}"
    )

    return posts


def main() -> None:
    parser = argparse.ArgumentParser(description="Post a Potato release thread to Bluesky")
    parser.add_argument("--tag", required=True, help="Release tag, e.g. v2.6.0")
    parser.add_argument("--dry-run", action="store_true", help="Print posts without sending")
    args = parser.parse_args()

    handle = os.environ.get("BSKY_HANDLE", "").strip()
    password = os.environ.get("BSKY_APP_PASSWORD", "").strip()

    posts = build_thread(args.tag)

    if args.dry_run:
        print("=== DRY RUN — thread preview ===\n")
        for i, text in enumerate(posts, 1):
            print(f"--- Post {i} ({len(text)} chars) ---")
            print(text)
            print()
        return

    if not handle or not password:
        print(
            "Error: set BSKY_HANDLE and BSKY_APP_PASSWORD environment variables.\n"
            "Create an app password at https://bsky.app/settings/app-passwords",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Logging in as {handle} …")
    token, did = login(handle, password)
    print("Authenticated.")

    root_ref: dict | None = None
    parent_ref: dict | None = None

    for i, text in enumerate(posts, 1):
        print(f"Posting skeet {i}/{len(posts)} …")
        result = post_skeet(text, token, did,
                            reply_root=root_ref,
                            reply_parent=parent_ref)
        if i == 1:
            root_ref = ref(result)
        parent_ref = ref(result)
        print(f"  → {result['uri']}")
        if i < len(posts):
            time.sleep(1)  # be polite to the API

    print(f"\nThread posted! Root: {root_ref['uri']}")


if __name__ == "__main__":
    main()

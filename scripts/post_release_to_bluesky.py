#!/usr/bin/env python3
"""Post a Potato release thread to Bluesky.

Usage:
    python scripts/post_release_to_bluesky.py --tag v2.4.5
    python scripts/post_release_to_bluesky.py          # uses latest release

Required environment variables:
    BSKY_HANDLE       e.g.  potatoannotator.bsky.social
    BSKY_APP_PASSWORD an App Password from bsky.app Settings → App Passwords

Optional environment variables:
    GITHUB_TOKEN      increases the GitHub API rate limit
"""

import argparse
import json
import os
import re
import sys
import textwrap
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


BSKY_API = "https://bsky.social/xrpc"
GITHUB_API = "https://api.github.com"
REPO = "davidjurgens/potato"
MAX_POST_CHARS = 296  # leave 4-char buffer under Bluesky's 300-char limit


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def _github_get(path: str) -> dict:
    url = f"{GITHUB_API}/repos/{REPO}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.getenv("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_release(tag: str | None) -> dict:
    if tag:
        return _github_get(f"/releases/tags/{tag}")
    return _github_get("/releases/latest")


# ---------------------------------------------------------------------------
# Thread composition
# ---------------------------------------------------------------------------

def _split_into_posts(paragraphs: list[str], header: str) -> list[str]:
    """Greedily pack paragraphs into ≤MAX_POST_CHARS posts."""
    posts: list[str] = []
    current = header
    for para in paragraphs:
        candidate = current + "\n\n" + para if current else para
        if len(candidate) <= MAX_POST_CHARS:
            current = candidate
        else:
            if current:
                posts.append(current)
            # If a single paragraph is too long, hard-wrap it.
            if len(para) > MAX_POST_CHARS:
                lines = textwrap.wrap(para, MAX_POST_CHARS)
                posts.extend(lines[:-1])
                current = lines[-1]
            else:
                current = para
    if current:
        posts.append(current)
    return posts


def _section_bullets(body: str, heading: str) -> list[str]:
    """Extract the bullet lines under a markdown ## heading."""
    pattern = rf"##\s+{re.escape(heading)}.*?\n(.*?)(?=\n##|\Z)"
    m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    lines = m.group(1).strip().splitlines()
    bullets = [l.strip() for l in lines if l.strip().startswith(("-", "*", "•"))]
    return bullets


def compose_thread(release: dict) -> list[str]:
    name = release["name"]
    tag = release["tag_name"]
    url = release["html_url"]
    body = release.get("body", "")

    # --- Post 1: headline ---
    intro = (
        f"🥔 {name} is out!\n\n"
        f"pip install --upgrade potato-annotation\n\n"
        f"Here's what's new 🧵👇"
    )

    posts = [intro]

    # --- Extract sections from the markdown body ---
    # Find all ## sections
    sections = re.findall(r"##\s+(.+?)\n(.*?)(?=\n##|\Z)", body, re.DOTALL)

    for section_title, section_body in sections:
        section_title = section_title.strip()
        # Skip upgrade section — already covered in post 1
        if re.match(r"upgrade", section_title, re.IGNORECASE):
            continue

        # Collect top-level bullets and sub-bullets
        bullets: list[str] = []
        for line in section_body.strip().splitlines():
            stripped = line.strip()
            if stripped.startswith(("-", "*", "•")):
                # Remove markdown bold
                text = re.sub(r"\*\*(.*?)\*\*", r"\1", stripped.lstrip("-*•").strip())
                # Truncate very long bullets
                if len(text) > 200:
                    text = text[:197] + "…"
                bullets.append(f"• {text}")

        if not bullets:
            continue

        header = f"📌 {section_title}"
        section_posts = _split_into_posts(bullets, header)
        posts.extend(section_posts)

    # --- Final post: link ---
    posts.append(
        f"Full release notes & upgrade guide:\n{url}\n\n"
        f"Thanks for using Potato! 🥔"
    )

    return posts


# ---------------------------------------------------------------------------
# Bluesky API
# ---------------------------------------------------------------------------

def _bsky_post(path: str, payload: dict, token: str | None = None) -> dict:
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BSKY_API}/{path}", data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Bluesky API error {e.code}: {body}") from e


def create_session(handle: str, password: str) -> tuple[str, str]:
    resp = _bsky_post(
        "com.atproto.server.createSession",
        {"identifier": handle, "password": password},
    )
    return resp["accessJwt"], resp["did"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def post_thread(posts: list[str], handle: str, password: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"\n{'='*60}\nDRY RUN — {len(posts)} posts\n{'='*60}")
        for i, p in enumerate(posts, 1):
            print(f"\n--- Post {i} ({len(p)} chars) ---\n{p}")
        return

    token, did = create_session(handle, password)
    print(f"Authenticated as {handle}")

    root_ref = None
    parent_ref = None

    for i, text in enumerate(posts, 1):
        record: dict = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": _now_iso(),
            "langs": ["en"],
        }

        if root_ref and parent_ref:
            record["reply"] = {
                "root": root_ref,
                "parent": parent_ref,
            }

        payload = {
            "repo": did,
            "collection": "app.bsky.feed.post",
            "record": record,
        }

        resp = _bsky_post("com.atproto.repo.createRecord", payload, token)
        ref = {"uri": resp["uri"], "cid": resp["cid"]}

        if root_ref is None:
            root_ref = ref
        parent_ref = ref

        print(f"  Posted {i}/{len(posts)}: {resp['uri']}")
        if i < len(posts):
            time.sleep(0.5)  # be polite to the API

    print(f"\nThread posted! Root: {root_ref['uri']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Post a Potato release thread to Bluesky.")
    parser.add_argument("--tag", help="Release tag (e.g. v2.4.5). Defaults to latest.")
    parser.add_argument("--dry-run", action="store_true", help="Print posts without sending.")
    args = parser.parse_args()

    handle = os.getenv("BSKY_HANDLE")
    password = os.getenv("BSKY_APP_PASSWORD")

    if not args.dry_run and (not handle or not password):
        print(
            "Error: BSKY_HANDLE and BSKY_APP_PASSWORD environment variables are required.\n"
            "Create an App Password at: https://bsky.app/settings/app-passwords",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Fetching release {'(' + args.tag + ')' if args.tag else '(latest)'}…")
    release = fetch_release(args.tag)
    print(f"Found: {release['name']}")

    posts = compose_thread(release)
    post_thread(posts, handle or "dry-run", password or "", dry_run=args.dry_run)


if __name__ == "__main__":
    main()

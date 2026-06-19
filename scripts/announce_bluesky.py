#!/usr/bin/env python3
"""
Post a Bluesky thread announcing a new Potato GitHub release.

Required environment variables:
  BLUESKY_HANDLE        Your Bluesky handle, e.g. potatoannotator.bsky.social
  BLUESKY_APP_PASSWORD  An app password from Bluesky › Settings › App passwords
                        (NOT your main account password)

Set by the calling harness / webhook handler:
  RELEASE_TAG    e.g. v2.6.0
  RELEASE_NAME   e.g. "Potato 2.6.0 — QDA Mode & Trajectory Editing"
  RELEASE_BODY   Full markdown release notes
  RELEASE_URL    HTML URL of the release page

Usage (manual / testing):
  export BLUESKY_HANDLE=potatoannotator.bsky.social
  export BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
  export RELEASE_TAG=v2.6.0
  export RELEASE_NAME="Potato 2.6.0 — QDA Mode, LLM-as-Judge Calibration & Trajectory Editing"
  export RELEASE_BODY="$(cat release_notes.md)"
  export RELEASE_URL=https://github.com/davidjurgens/potato/releases/tag/v2.6.0
  python scripts/announce_bluesky.py
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BSKY_API = "https://bsky.social/xrpc"
MAX_CHARS = 295  # Bluesky hard limit is 300; leave a small buffer


# ---------------------------------------------------------------------------
# AT Protocol helpers
# ---------------------------------------------------------------------------

def _bsky_post(url, data, token=None):
    body = json.dumps(data).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Bluesky API error {exc.code}: {exc.read().decode()}") from exc


def create_session(handle, password):
    return _bsky_post(
        f"{BSKY_API}/com.atproto.server.createSession",
        {"identifier": handle, "password": password},
    )


def create_post(token, did, text, reply_to=None):
    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if reply_to:
        record["reply"] = {
            "root": reply_to["root"],
            "parent": reply_to["parent"],
        }
    return _bsky_post(
        f"{BSKY_API}/com.atproto.repo.createRecord",
        {"repo": did, "collection": "app.bsky.feed.post", "record": record},
        token=token,
    )


def post_thread(handle, password, posts):
    """Authenticate and publish a list of strings as a reply thread."""
    session = create_session(handle, password)
    token, did = session["accessJwt"], session["did"]

    root_ref = parent_ref = None
    for i, text in enumerate(posts):
        reply_to = None
        if root_ref:
            reply_to = {"root": root_ref, "parent": parent_ref}

        result = create_post(token, did, text, reply_to)
        ref = {"cid": result["cid"], "uri": result["uri"]}
        if i == 0:
            root_ref = ref
        parent_ref = ref

        preview = text[:80].replace("\n", " ")
        print(f"  [{i + 1}/{len(posts)}] {preview}…")
        if i < len(posts) - 1:
            time.sleep(0.6)  # small courtesy delay between posts

    return root_ref


# ---------------------------------------------------------------------------
# Release-notes → thread formatter
# ---------------------------------------------------------------------------

SECTION_EMOJIS = {
    "qualitative data analysis": "📋",
    "qda": "📋",
    "agent evaluation": "🤖",
    "llm-as-judge": "🤖",
    "llm": "🤖",
    "annotation workflow": "⚙️",
    "assignment": "⚙️",
    "licensing": "📄",
    "performance": "🚀",
    "robustness": "🔧",
    "upgrade": "⬆️",
}

# Sections whose content we fold into a custom final CTA post
_SKIP_HEADINGS = {"upgrade"}


def _emoji_for(heading):
    low = heading.lower()
    for keyword, emoji in SECTION_EMOJIS.items():
        if keyword in low:
            return emoji
    return "📌"


def _parse_sections(markdown):
    """Return list of (heading, body) from ## headings."""
    sections = []
    current_heading = None
    current_lines = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if current_heading is not None:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line[3:].strip()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)
    if current_heading:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return sections


def _section_to_post(heading, body):
    """Convert a markdown section to a ≤MAX_CHARS Bluesky post."""
    # Strip fenced code blocks
    body = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    # Collapse ### sub-headings to plain text
    body = re.sub(r"###+ (.+)", r"\1:", body)
    # Strip bold/italic markers
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    body = re.sub(r"\*(.+?)\*", r"\1", body)
    # Strip markdown links but keep their visible text
    body = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", body)
    # Collapse excess blank lines
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    # Collect bullet lines; skip sub-section-only lines
    lines = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("- ", "* ")):
            lines.append("• " + line[2:])
        elif not line.startswith("#"):
            lines.append(line)

    em = _emoji_for(heading)
    header = f"{em} {heading}\n"
    available = MAX_CHARS - len(header)

    body_text = ""
    for line in lines:
        candidate = (body_text + "\n" + line) if body_text else line
        if len(candidate) <= available:
            body_text = candidate
        else:
            remaining = available - len(body_text) - 5
            if remaining > 20 and not body_text:
                body_text = line[:remaining] + "…"
            break

    return (header + body_text).strip()


def build_thread(tag, name, body, url):
    """Build the full list of post strings for a release announcement thread."""
    version = tag.lstrip("v")
    subtitle = re.sub(rf"^Potato\s+{re.escape(version)}\s*[—–-]?\s*", "", name).strip()

    # Post 1: hook
    if subtitle:
        hook = f"🥔 Potato {version} is out!\n\n{subtitle}\n\nHere's what's new 🧵👇"
    else:
        hook = f"🥔 Potato {version} is out! Here's what's new 🧵👇"
    if len(hook) > MAX_CHARS:
        hook = f"🥔 Potato {version} is out! Here's what's new 🧵👇"
    posts = [hook]

    # One post per ## section (skip Upgrade — that becomes the CTA)
    for heading, content in _parse_sections(body):
        if heading.lower() in _SKIP_HEADINGS:
            continue
        post = _section_to_post(heading, content)
        if len(post) > 10:
            posts.append(post)

    # Final post: upgrade CTA
    posts.append(
        f"⬆️ Upgrade:\npip install --upgrade potato-annotation=={version}\n\n"
        f"Full release notes:\n{url}"
    )

    return posts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    handle = os.environ.get("BLUESKY_HANDLE", "").strip()
    app_password = os.environ.get("BLUESKY_APP_PASSWORD", "").strip()

    if not handle or not app_password:
        print(
            "ERROR: Bluesky credentials not found.\n\n"
            "Set these environment variables:\n"
            "  BLUESKY_HANDLE       — your Bluesky handle (e.g. potatoannotator.bsky.social)\n"
            "  BLUESKY_APP_PASSWORD — an app password from:\n"
            "                         Bluesky › Settings › Privacy and security › App passwords\n"
            "                         (do NOT use your main account password)\n",
            file=sys.stderr,
        )
        sys.exit(1)

    tag = os.environ.get("RELEASE_TAG", "").strip()
    if not tag:
        print("ERROR: RELEASE_TAG must be set (e.g. v2.6.0)", file=sys.stderr)
        sys.exit(1)

    name = os.environ.get("RELEASE_NAME", f"Potato {tag}")
    body = os.environ.get("RELEASE_BODY", "")
    url = os.environ.get(
        "RELEASE_URL",
        f"https://github.com/davidjurgens/potato/releases/tag/{tag}",
    )

    posts = build_thread(tag, name, body, url)

    print(f"Posting {len(posts)}-post thread for {tag} as @{handle} …\n")
    root = post_thread(handle, app_password, posts)
    print(f"\nDone. Root post URI: {root['uri']}")


if __name__ == "__main__":
    main()

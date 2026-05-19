#!/usr/bin/env python3
"""Post Potato GitHub release announcements as a Bluesky thread.

Compares the latest GitHub release against a locally-tracked state file
and posts an announcement thread to Bluesky when a new version is found.

Required env vars:
    BLUESKY_APP_PASSWORD   App password from https://bsky.app/settings/app-passwords

Optional env vars:
    BLUESKY_IDENTIFIER     Bluesky handle (default: potatoannotator.bsky.social)
    GITHUB_TOKEN           GitHub token to avoid rate limits
    DRY_RUN                Set to 1 to preview posts without actually posting
    FORCE_POST             Set to 1 to post even if already posted
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import urllib.error

GITHUB_REPO = "davidjurgens/potato"
DEFAULT_BLUESKY_HANDLE = "potatoannotator.bsky.social"
BLUESKY_PDS = "https://bsky.social"
STATE_FILE = Path(__file__).parent / ".last_bluesky_release"
MAX_CHARS = 300
MAX_BULLET_CHARS = 110  # Truncate individual bullets beyond this

# Maps lowercase ## section names to an emoji. None = skip the section entirely.
SECTION_EMOJIS = {
    "bug fix": "🔧",
    "bug fixes": "🔧",
    "other": "🔧",
    "new feature": "✨",
    "new features": "✨",
    "features": "✨",
    "documentation": "📖",
    "docs": "📖",
    "infrastructure": "⚙️",
    "testing": "🧪",
    "agent evaluation": "🤖",
    "live agent evaluation": "🤖",
    "ai-assisted annotation": "🤖",
    "enterprise integration": "🏢",
    "annotation system improvements": "📋",
    "new annotation schemas": "📋",
    "display system": "📋",
    "data & export": "📊",
    "data and export": "📊",
    "quality control": "✅",
    "ux": "💅",
    "dependency changes": None,
    "install": None,
    "upgrade": None,
    "changes from rc1": None,
}


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def github_latest_release():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    headers = {
        "User-Agent": "potato-bluesky-bot/1.0",
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Bluesky / AT Protocol helpers
# ---------------------------------------------------------------------------

def _bsky_request(endpoint, payload, token=None):
    url = f"{BLUESKY_PDS}/xrpc/{endpoint}"
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"Bluesky API error {e.code}: {e.read().decode()}", file=sys.stderr)
        raise


def bluesky_login(identifier, password):
    return _bsky_request("com.atproto.server.createSession", {
        "identifier": identifier,
        "password": password,
    })


def _make_link_facets(text):
    """Return AT Protocol facets for any https:// URLs found in text."""
    facets = []
    for m in re.finditer(r'https?://[^\s]+', text):
        uri = m.group(0).rstrip('.,)')
        byte_start = len(text[:m.start()].encode("utf-8"))
        byte_end = byte_start + len(uri.encode("utf-8"))
        facets.append({
            "$type": "app.bsky.richtext.facet",
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": uri}],
        })
    return facets


def _post_record(session, text, reply_to=None):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    record = {"$type": "app.bsky.feed.post", "text": text, "createdAt": now}
    facets = _make_link_facets(text)
    if facets:
        record["facets"] = facets
    if reply_to:
        record["reply"] = reply_to
    return _bsky_request(
        "com.atproto.repo.createRecord",
        {"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
        token=session["accessJwt"],
    )


def post_thread(session, posts, dry_run=False):
    """Post a list of strings as a Bluesky reply chain. Returns root ref dict."""
    root_ref = parent_ref = None
    for i, text in enumerate(posts):
        print(f"\n--- [{i+1}/{len(posts)}] ({len(text)} chars) ---")
        print(text)
        if dry_run:
            continue

        reply_to = None
        if root_ref:
            reply_to = {"root": root_ref, "parent": parent_ref}

        result = _post_record(session, text, reply_to)
        ref = {"cid": result["cid"], "uri": result["uri"]}
        if root_ref is None:
            root_ref = ref
        parent_ref = ref

        if i < len(posts) - 1:
            time.sleep(1)

    return root_ref


# ---------------------------------------------------------------------------
# Release note parsing
# ---------------------------------------------------------------------------

def _clean_inline(text):
    """Strip bold, inline-code, and markdown links from a string."""
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    return text.strip()


def parse_body(body):
    """Parse a GitHub release body into a list of (section_name, bullets, plain) tuples.

    - Aggregates ### sub-section content under its parent ## section.
    - Skips sections whose lowercase name maps to None in SECTION_EMOJIS.
    - Skips fenced code blocks.
    """
    sections = []
    current_name = None
    current_bullets = []
    current_plain = []
    in_code_block = False

    def flush():
        if current_name is not None and (current_bullets or current_plain):
            sections.append((current_name, list(current_bullets), list(current_plain)))

    for line in body.split('\n'):
        stripped = line.strip()

        if stripped.startswith('```'):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if re.match(r'^## ', stripped):
            flush()
            header = stripped[3:].strip()
            # Explicitly None means skip; missing from dict means include with default emoji
            if SECTION_EMOJIS.get(header.lower()) is None and header.lower() in SECTION_EMOJIS:
                current_name = None
            else:
                current_name = header
            current_bullets = []
            current_plain = []

        elif re.match(r'^### ', stripped):
            pass  # Sub-headers: just let their content flow into the parent section

        elif re.match(r'^[-*] ', stripped) or re.match(r'^\s+[-*] ', stripped):
            if current_name is not None:
                content = _clean_inline(re.sub(r'^\s*[-*] ', '', stripped))
                if len(content) > MAX_BULLET_CHARS:
                    content = content[:MAX_BULLET_CHARS - 1] + '…'
                current_bullets.append(content)

        elif stripped and not stripped.startswith('#') and not stripped.startswith('|'):
            if current_name is not None:
                current_plain.append(_clean_inline(stripped))

    flush()
    return sections


def _section_emoji(name):
    return SECTION_EMOJIS.get(name.lower(), "📌")


def _bullets_to_posts(section_name, bullets):
    """Pack bullet list under a section header into ≤MAX_CHARS posts."""
    emoji = _section_emoji(section_name)
    header = f"{emoji} {section_name}"
    posts = []
    current = header + "\n"

    for bullet in bullets:
        line = f"• {bullet}\n"
        if len(current) + len(line) <= MAX_CHARS:
            current += line
        else:
            if current.strip() != header:
                posts.append(current.rstrip())
            current = header + " (cont'd)\n" + line

    if current.strip() not in (header, header + " (cont'd)"):
        posts.append(current.rstrip())

    return posts


def _plain_to_post(section_name, plain_lines):
    """Format plain-text section content as a single ≤MAX_CHARS post."""
    emoji = _section_emoji(section_name)
    body = " ".join(plain_lines)
    text = f"{emoji} {section_name}\n\n{body}"
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS - 1] + '…'
    return text


# ---------------------------------------------------------------------------
# Thread formatting
# ---------------------------------------------------------------------------

def format_thread(release):
    """Return a list of strings to post as a Bluesky thread."""
    tag = release["tag_name"]
    version = tag.lstrip("v")
    name = release["name"]
    url = release["html_url"]
    body = release.get("body", "")

    posts = []

    # --- Opening post ---
    pip_cmd = f"pip install --upgrade potato-annotation=={version}"
    for template in [
        f"🥔 Potato {tag} released!\n\n{name}\n\n{pip_cmd}\n\n{url}",
        f"🥔 Potato {tag}: {name}\n\n{pip_cmd}\n\n{url}",
        f"🥔 Potato {tag} is out!\n\n{pip_cmd}\n\n{url}",
        f"🥔 Potato {tag}\n\n{pip_cmd}\n\n{url}",
    ]:
        if len(template) <= MAX_CHARS:
            posts.append(template)
            break

    # --- Body sections ---
    for section_name, bullets, plain in parse_body(body):
        if bullets:
            posts.extend(_bullets_to_posts(section_name, bullets))
        elif plain:
            posts.append(_plain_to_post(section_name, plain))

    return posts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    identifier = os.environ.get("BLUESKY_IDENTIFIER", DEFAULT_BLUESKY_HANDLE)
    password = os.environ.get("BLUESKY_APP_PASSWORD")
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    force = os.environ.get("FORCE_POST", "").lower() in ("1", "true", "yes")

    if not password and not dry_run:
        print("Error: BLUESKY_APP_PASSWORD is not set.", file=sys.stderr)
        print("Create an app password at: https://bsky.app/settings/app-passwords")
        sys.exit(1)

    print("Fetching latest Potato release from GitHub...")
    release = github_latest_release()
    latest = release["tag_name"]
    last = STATE_FILE.read_text().strip() if STATE_FILE.exists() else None

    print(f"Latest GitHub release : {latest}")
    print(f"Last Bluesky post     : {last or 'none'}")

    if latest == last and not force:
        print("Already posted. Nothing to do.")
        return

    posts = format_thread(release)
    print(f"\nThread will contain {len(posts)} post(s).")

    if dry_run:
        print("\n[DRY RUN — no posts sent]\n")
        post_thread(None, posts, dry_run=True)
        return

    print(f"\nLogging in to Bluesky as {identifier}...")
    session = bluesky_login(identifier, password)
    print(f"Logged in: @{session['handle']}")

    print(f"\nPosting thread...")
    root = post_thread(session, posts)

    if root:
        post_id = root["uri"].split("/")[-1]
        print(f"\nThread live: https://bsky.app/profile/{identifier}/post/{post_id}")

    STATE_FILE.write_text(latest)
    print(f"State file updated: {latest}")


if __name__ == "__main__":
    main()

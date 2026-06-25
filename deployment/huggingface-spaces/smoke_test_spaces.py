#!/usr/bin/env python3
"""Smoke-test the Potato Spaces catalog: boot each source config and confirm the
annotation phase renders. Run from the repo root.

For each manifest entry it launches:
    python potato/flask_server.py start <source>/config.yaml -p <port> --debug --debug-phase annotation
then polls the home page (which 302-redirects to the annotation phase in debug mode)
and checks the rendered page looks like a real annotation screen.

This is the feasibility gate for "gated" demos (live/ingestion variants): if they don't
render from bundled static data, they fail here and should stay local-only.

Usage:
    python deployment/huggingface-spaces/smoke_test_spaces.py --all
    python deployment/huggingface-spaces/smoke_test_spaces.py --gated
    python deployment/huggingface-spaces/smoke_test_spaces.py agent-trace-evaluation ner-span
    python deployment/huggingface-spaces/smoke_test_spaces.py --category multimodal
"""
import argparse
import http.cookiejar
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
MANIFEST = SCRIPT_DIR / "spaces_manifest.yaml"
BASE_PORT = 8900
BOOT_TIMEOUT = 40  # seconds to wait for a server to come up
# Markers that indicate a real annotation screen rendered.
PAGE_MARKERS = ["main-content", "annotation", "instance"]


def load_manifest():
    with open(MANIFEST) as f:
        data = yaml.safe_load(f)
    defaults = data.get("defaults", {}) or {}
    return {e["id"]: {**defaults, **e} for e in data.get("spaces", [])}


def make_opener():
    """An opener with its own cookie jar — the debug auto-login sets a session
    cookie; without retaining it, '/' redirects in an infinite loop."""
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def fetch(opener, url, timeout=8):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "potato-smoke"})
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # 4xx/5xx are real responses (server is up)
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        return e.code, body
    except Exception:  # noqa: BLE001 — connection refused etc. (not up yet)
        return None, ""


def test_one(space_id, entry, port):
    config = REPO_ROOT / entry["source"] / "config.yaml"
    if not config.is_file():
        return False, "no config.yaml"

    log = Path(f"/tmp/smoke_{space_id}.log")
    with open(log, "w") as lf:
        proc = subprocess.Popen(
            [sys.executable, "potato/flask_server.py", "start", str(config),
             "-p", str(port), "--debug", "--debug-phase", "annotation"],
            cwd=str(REPO_ROOT), stdout=lf, stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group so we can kill reloader children
        )
    try:
        opener = make_opener()
        deadline = time.time() + BOOT_TIMEOUT
        status, body = None, ""
        while time.time() < deadline:
            if proc.poll() is not None:
                return False, f"server exited early (rc={proc.returncode}); see {log}"
            # '/' auto-logs-in (debug) and lands on the annotation page; the cookie
            # jar retains the session so redirects resolve to a 200.
            status, body = fetch(opener, f"http://localhost:{port}/")
            if status is not None:
                break
            time.sleep(1.5)
        if status is None:
            return False, f"no response within {BOOT_TIMEOUT}s; see {log}"

        a_status, a_body = fetch(opener, f"http://localhost:{port}/annotate")
        page = a_body if len(a_body) > len(body) else body
        ok_markers = sum(m in page.lower() for m in PAGE_MARKERS)
        if ok_markers >= 1 and len(page) > 1500:
            return True, f"render ok ({len(page)//1000}k, markers={ok_markers})"
        return False, f"home={status} annotate={a_status} markers={ok_markers} len={len(page)}; see {log}"
    finally:
        # Kill the whole process group — Flask's --debug reloader spawns children
        # that survive a SIGTERM sent only to the parent.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ids", nargs="*", help="Specific space ids to test")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--gated", action="store_true", help="Only test gated (live) variants")
    ap.add_argument("--ready-only", action="store_true", help="Skip needs_ai demos")
    ap.add_argument("--category")
    args = ap.parse_args()

    spaces = load_manifest()
    if args.ids:
        selected = [(i, spaces[i]) for i in args.ids if i in spaces]
    elif args.gated:
        selected = [(i, e) for i, e in spaces.items() if e.get("status") == "gated"]
    elif args.category:
        selected = [(i, e) for i, e in spaces.items() if e["category"] == args.category]
    elif args.all:
        selected = list(spaces.items())
    else:
        ap.error("provide ids, or --all / --gated / --category")
    if args.ready_only:
        selected = [(i, e) for i, e in selected if not e.get("needs_ai")]

    print(f"Smoke-testing {len(selected)} spaces…\n")
    passed, failed = [], []
    for n, (sid, entry) in enumerate(selected):
        port = BASE_PORT + (n % 80)
        ok, detail = test_one(sid, entry, port)
        flag = "gated" if entry.get("status") == "gated" else ("ai" if entry.get("needs_ai") else "")
        mark = "✓" if ok else "✗"
        print(f"  {mark} {sid:28} {flag:5} {detail}", flush=True)
        (passed if ok else failed).append(sid)

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    if failed:
        print("FAILED:", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()

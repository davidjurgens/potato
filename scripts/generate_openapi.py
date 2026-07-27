#!/usr/bin/env python3
"""
Auto-generate the OpenAPI 3.1 spec for Potato's HTTP API.

Enumerates the live Flask url_map (plus every config-gated blueprint) so the
API index cannot drift from the code the way the hand-written reference did.

Usage:
    python scripts/generate_openapi.py
    python scripts/generate_openapi.py --check   # exit 1 if stale
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, "docs", "api-reference", "openapi.json")


def _version() -> str:
    try:
        from potato import __version__
        return str(__version__)
    except Exception:
        return "unknown"


def render(spec) -> str:
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the checked-in spec matches the app; do not write.",
    )
    args = parser.parse_args()

    from potato.server_utils.openapi_spec import build_openapi_spec

    spec = build_openapi_spec(version=_version())
    payload = render(spec)

    n_paths = len(spec["paths"])
    n_ops = sum(len(v) for v in spec["paths"].values())

    if args.check:
        # The version string moves with releases; compare everything else so a
        # version bump alone does not fail the build.
        def normalized(text):
            data = json.loads(text)
            data["info"]["version"] = "-"
            return json.dumps(data, indent=2, sort_keys=True)

        if not os.path.exists(OUTPUT):
            print(f"Missing {os.path.relpath(OUTPUT, ROOT)}")
            return 1
        if normalized(open(OUTPUT).read()) != normalized(payload):
            print("OpenAPI spec is out of date.")
            print("Regenerate with: python scripts/generate_openapi.py")
            return 1
        print(f"OpenAPI spec is up to date ({n_paths} paths, {n_ops} operations).")
        return 0

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        f.write(payload)
    print(f"Wrote {os.path.relpath(OUTPUT, ROOT)} ({n_paths} paths, {n_ops} operations)")

    unavailable = spec["info"].get("x-potato-unavailable-blueprints")
    if unavailable:
        print("Optional blueprints that could not be imported (omitted from spec):")
        for entry in unavailable:
            print(f"  - {entry}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Auto-generate the JSON Schema for Potato task configuration.

Reads the schema registry, the display registry, and KNOWN_CONFIG_KEYS to
produce a JSON Schema that stays in sync with the code. Editors that speak
`# yaml-language-server: $schema=` validate configs against it, and coding
agents get a machine-checkable contract instead of prose.

Two copies are written from one build:
  potato/schemas/potato-config.schema.json  (ships in the wheel, resolves offline)
  docs/schemas/potato-config.schema.json    (served by Read the Docs at SCHEMA_URL)

Usage:
    python scripts/generate_config_schema.py
    python scripts/generate_config_schema.py --check   # exit 1 if stale
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from potato.server_utils.config_schema import SCHEMA_URL, build_config_schema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUTS = [
    os.path.join(ROOT, "potato", "schemas", "potato-config.schema.json"),
    os.path.join(ROOT, "docs", "schemas", "potato-config.schema.json"),
]

# Editors (VS Code + YAML extension, JetBrains, Zed, Helix) read this comment and
# validate the file live. It is also the most reliable way for a coding agent to
# discover that a machine-checkable contract exists at all.
MODELINE = f"# yaml-language-server: $schema={SCHEMA_URL}"


def stamp_examples() -> int:
    """Prepend the schema modeline to every example config that lacks one."""
    stamped = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "examples", "**", "config.yaml"),
                                 recursive=True)):
        with open(path) as f:
            text = f.read()
        if "yaml-language-server:" in text:
            continue
        with open(path, "w") as f:
            f.write(f"{MODELINE}\n{text}")
        stamped += 1
    return stamped


def render(schema) -> str:
    """Serialize deterministically so regeneration produces no spurious diffs."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the checked-in files match the registries; do not write.",
    )
    parser.add_argument(
        "--stamp-examples",
        action="store_true",
        help="Add the '# yaml-language-server: $schema=' line to example configs.",
    )
    args = parser.parse_args()

    payload = render(build_config_schema())

    if args.check:
        stale = []
        for path in OUTPUTS:
            if not os.path.exists(path) or open(path).read() != payload:
                stale.append(os.path.relpath(path, ROOT))
        if stale:
            print("Config schema is out of date: " + ", ".join(stale))
            print("Regenerate with: python scripts/generate_config_schema.py")
            return 1
        print("Config schema is up to date.")
        return 0

    for path in OUTPUTS:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(payload)
        print(f"Wrote {os.path.relpath(path, ROOT)}")

    if args.stamp_examples:
        print(f"Stamped {stamp_examples()} example config(s) with the schema modeline")
    return 0


if __name__ == "__main__":
    sys.exit(main())

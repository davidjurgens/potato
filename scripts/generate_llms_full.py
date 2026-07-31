#!/usr/bin/env python3
"""
Auto-generate docs/llms-full.txt — the whole documentation set as one file.

`llms.txt` is a curated index of links, maintained by hand. This is its
companion: every documentation page inlined, so an agent can ingest the full
reference in one fetch instead of crawling 180+ pages.

Pages are emitted in mkdocs nav order (the curated reading order), with any
page missing from the nav appended afterwards so nothing is silently dropped.

Usage:
    python scripts/generate_llms_full.py
    python scripts/generate_llms_full.py --check   # exit 1 if stale
"""

import argparse
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
MKDOCS = os.path.join(ROOT, "mkdocs.yml")
OUTPUT = os.path.join(DOCS, "llms-full.txt")

# Not documentation prose: the curated index itself, this file, and the
# generated machine-readable artifacts (linked from llms.txt instead).
EXCLUDE = {"llms.txt", "llms-full.txt"}

PREAMBLE = """\
# Potato — Full Documentation

> Every page of the Potato documentation, concatenated. Potato is a free,
> open-source, self-hosted annotation and agent-evaluation platform for NLP,
> agentic, and GenAI research. Tasks are configured entirely in YAML.
>
> This file is generated — see scripts/generate_llms_full.py. For a short
> curated index of links instead, see llms.txt. For machine-readable contracts,
> see schemas/potato-config.schema.json (config) and
> api-reference/openapi.json (HTTP API).

"""


def nav_docs(node, out):
    """Depth-first walk of the mkdocs nav, collecting doc paths in order."""
    if isinstance(node, str):
        if node.endswith(".md"):
            out.append(node)
    elif isinstance(node, list):
        for item in node:
            nav_docs(item, out)
    elif isinstance(node, dict):
        for value in node.values():
            nav_docs(value, out)
    return out


def ordered_docs():
    """Nav-ordered docs first, then any remaining markdown file, both deduped."""
    config = yaml.safe_load(open(MKDOCS))
    ordered, seen = [], set()

    for rel in nav_docs(config.get("nav", []), []):
        if rel in seen or rel in EXCLUDE:
            continue
        if os.path.exists(os.path.join(DOCS, rel)):
            ordered.append(rel)
            seen.add(rel)

    extras = []
    for dirpath, dirnames, filenames in os.walk(DOCS):
        dirnames[:] = [d for d in dirnames if d not in {"img", "stylesheets", "javascripts"}]
        for filename in sorted(filenames):
            if not filename.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, filename), DOCS)
            if rel not in seen and rel not in EXCLUDE:
                extras.append(rel)
                seen.add(rel)

    return ordered, sorted(extras)


def render() -> str:
    ordered, extras = ordered_docs()
    parts = [PREAMBLE]

    for rel in ordered + extras:
        with open(os.path.join(DOCS, rel), encoding="utf-8") as f:
            body = f.read().rstrip()
        parts.append(
            f"\n\n---\n\n<!-- source: docs/{rel} -->\n"
            f"URL: https://potatoannotator.readthedocs.io/en/latest/"
            f"{rel[:-3].removesuffix('/index')}/\n\n{body}\n"
        )

    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Verify the checked-in file is current; do not write.")
    args = parser.parse_args()

    payload = render()
    ordered, extras = ordered_docs()

    if args.check:
        if not os.path.exists(OUTPUT) or open(OUTPUT, encoding="utf-8").read() != payload:
            print("llms-full.txt is out of date.")
            print("Regenerate with: python scripts/generate_llms_full.py")
            return 1
        print(f"llms-full.txt is up to date ({len(ordered) + len(extras)} pages).")
        return 0

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(payload)
    size_kb = len(payload.encode("utf-8")) / 1024
    print(f"Wrote docs/llms-full.txt — {len(ordered)} nav pages "
          f"+ {len(extras)} off-nav pages, {size_kb:.0f} KB")
    if extras:
        print("Pages not in the mkdocs nav (appended at the end):")
        for rel in extras[:10]:
            print(f"  - {rel}")
        if len(extras) > 10:
            print(f"  ... and {len(extras) - 10} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())

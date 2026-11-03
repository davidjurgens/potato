#!/usr/bin/env python
"""
`potato codebook <config.yaml>` — initialise / migrate a project's
codebook from its YAML config.

For every annotation scheme with ``codebook: true`` it ensures a code
exists for each YAML label, with the label's colour and description,
through the same seeding path the server uses. Codes get
**deterministic** ids (``uuid5`` over ``project | parent_id | name``) so
re-running is a no-op and the same config always yields the same ids
across machines (saved annotations link to codes by id).

Idempotent: existing codes are left untouched; only missing ones are
created. Safe to run repeatedly and in CI.

Usage:
    potato codebook path/to/config.yaml
    potato codebook path/to/config.yaml --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

import yaml

from potato.codebook.codebook import Codebook
# deterministic_code_id is re-exported: it lived here before the server's
# seeding path shared it.
from potato.codebook.schema_bridge import (  # noqa: F401
    _label_name,
    deterministic_code_id,
    seed_label,
)


def _resolve_task_dir(config_file: str, config: Dict[str, Any]) -> str:
    base = os.path.dirname(os.path.abspath(config_file))
    return os.path.normpath(os.path.join(base, config.get("task_dir", ".")))


def init_codebook(config_file: str, *, dry_run: bool = False) -> Dict[str, int]:
    """Seed missing codes for every codebook-enabled scheme.

    Returns {"created": n, "existing": m}.
    """
    with open(config_file, "rt", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}

    task_dir = _resolve_task_dir(config_file, config)
    project = config.get("annotation_task_name") or "default"
    schemes: List[Dict[str, Any]] = config.get("annotation_schemes") or []

    created = existing = 0
    for scheme in schemes:
        if not isinstance(scheme, dict) or not scheme.get("codebook"):
            continue
        cb = Codebook.load(task_dir, project)
        present = set(cb.labels())
        for entry in scheme.get("labels") or []:
            name = _label_name(entry)
            if not name:
                continue
            if name in present:
                existing += 1
                continue
            if dry_run:
                created += 1
                present.add(name)
                continue
            # The server's seeding path, so a code created here carries
            # the label's colour and description too.
            if seed_label(task_dir, project, entry,
                          created_by="codebook-cli") is not None:
                created += 1
                present.add(name)
            else:
                existing += 1

    return {"created": created, "existing": existing}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="potato codebook",
        description="Initialise a project codebook from its YAML config.")
    parser.add_argument("config_file", help="Path to the project config.yaml")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be created without writing.")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.config_file):
        print(f"Config not found: {args.config_file}", file=sys.stderr)
        return 2

    result = init_codebook(args.config_file, dry_run=args.dry_run)
    verb = "Would create" if args.dry_run else "Created"
    print(f"{verb} {result['created']} code(s); "
          f"{result['existing']} already present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

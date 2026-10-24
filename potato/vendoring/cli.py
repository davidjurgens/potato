"""
``potato vendor`` — install the large browser libraries some features need.

Usage::

    potato vendor list
    potato vendor fetch molstar
    potato vendor fetch --for-config path/to/config.yaml
    potato vendor fetch --all
    potato vendor verify
    potato vendor path

Nothing is fetched implicitly. A config that uses a feature whose library is
not installed fails validation with the command that installs it.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from potato import vendoring


def _required_for_config(path: str) -> List[str]:
    import yaml
    from potato.vendoring.requirements import required_bundles
    from potato.server_utils.config_module import normalize_config_before_validation
    import os
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    config = normalize_config_before_validation(config, os.path.dirname(os.path.abspath(path)))
    return required_bundles(config)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="potato vendor",
                                     description="Install pinned third-party browser libraries.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List the bundles and whether each is installed")
    f = sub.add_parser("fetch", help="Download, verify and install bundles")
    f.add_argument("names", nargs="*",
                   help="Bundle names, as `potato vendor list` prints them (e.g. molstar)")
    f.add_argument("--all", action="store_true", help="Every bundle")
    f.add_argument("--for-config", metavar="CONFIG",
                   help="The bundles this config needs")
    f.add_argument("--force", action="store_true", help="Re-download even if installed")
    v = sub.add_parser("verify", help="Check installed files against their recorded hashes")
    v.add_argument("names", nargs="*",
                   help="Bundle names (default: every installed bundle)")
    sub.add_parser("path", help="Print the vendor directory")
    args = parser.parse_args(argv)

    if args.command == "path":
        print(vendoring.vendor_dir())
        return 0

    if args.command == "list":
        bundles = vendoring.all_bundles()
        if not bundles:
            print("No fetchable bundles are defined.")
            return 0
        for b in bundles:
            state = "installed" if vendoring.is_installed(b.name) else "not installed"
            size = f", ~{b.approx_mb:g} MB" if b.approx_mb else ""
            print(f"{b.name:<22} {b.version:<12} {b.license:<18} {state}{size}")
            print(f"    {b.description}")
        print(f"\nVendor directory: {vendoring.vendor_dir()}")
        return 0

    if args.command == "fetch":
        names = list(args.names)
        if args.all:
            names = [b.name for b in vendoring.all_bundles()]
        if args.for_config:
            names += _required_for_config(args.for_config)
        if not names and (args.all or args.for_config):
            # Nothing registered, or the config needs nothing: done, not an error.
            print("Nothing to fetch: " + ("no bundles are registered."
                                          if args.all and not vendoring.all_bundles()
                                          else "the config needs no bundles."))
            return 0
        if not names:
            print("Name at least one bundle, or pass --all or --for-config. "
                  "See `potato vendor list`.", file=sys.stderr)
            return 2
        failed = 0
        for name in dict.fromkeys(names):
            try:
                vendoring.fetch(name, force=args.force)
            except Exception as e:  # report every bundle, then fail
                print(f"{name}: {e}", file=sys.stderr)
                failed += 1
        return 1 if failed else 0

    if args.command == "verify":
        names = args.names or [b.name for b in vendoring.all_bundles()
                               if vendoring.is_installed(b.name)]
        problems = [p for n in names for p in vendoring.verify(n)]
        for p in problems:
            print(p, file=sys.stderr)
        if not problems:
            print(f"{len(names)} bundle(s) intact.")
        return 1 if problems else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

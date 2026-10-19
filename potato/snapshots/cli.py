"""
`potato snapshot`: freeze, list, compare and check project snapshots.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="potato snapshot",
        description="Freeze a project's config, data and annotations under an id "
                    "you can cite, and compare or check snapshots later.")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="freeze the project as it is now")
    create.add_argument("config", help="the project's config.yaml")
    create.add_argument("--note", default="", help="what this snapshot is for")
    create.add_argument("--tag", help="a name to point at it, e.g. paper-v1")
    create.add_argument("--force", action="store_true",
                        help="write a snapshot even if nothing changed since the last one")

    listing = sub.add_parser("list", help="snapshots, newest first")
    listing.add_argument("config")
    listing.add_argument("--json", action="store_true")

    show = sub.add_parser("show", help="one snapshot's manifest and agreement")
    show.add_argument("config")
    show.add_argument("ref", nargs="?", default="latest",
                      help="id, id prefix, tag, or latest (default)")
    show.add_argument("--json", action="store_true")

    diff = sub.add_parser("diff", help="what changed between two snapshots")
    diff.add_argument("config")
    diff.add_argument("old", help="the earlier snapshot (id, prefix or tag)")
    diff.add_argument("new", nargs="?", default="latest", help="the later one (default latest)")
    diff.add_argument("--json", action="store_true")

    tag = sub.add_parser("tag", help="point a name at a snapshot")
    tag.add_argument("config")
    tag.add_argument("ref")
    tag.add_argument("name")

    verify = sub.add_parser("verify", help="re-hash a snapshot against its manifest")
    verify.add_argument("config")
    verify.add_argument("ref", nargs="?", default="latest")
    return parser


def _summary_line(m: dict) -> str:
    counts = m.get("counts") or {}
    tags = f" [{', '.join(m['tags'])}]" if m.get("tags") else ""
    note = f"  {m['note']}" if m.get("note") else ""
    return (f"{m['id']}{tags}  {counts.get('items', 0)} items, "
            f"{counts.get('annotators', 0)} annotators, "
            f"{counts.get('annotations', 0)} answers{note}")


def _show(m: dict) -> str:
    lines = [_summary_line(m),
             f"  created       {m.get('created_at')}",
             f"  content hash  {m.get('content_hash')}",
             f"  bundle sha256 {m.get('bundle_sha256')}",
             f"  potato        {m.get('potato_version')}"]
    if m.get("previous"):
        lines.append(f"  previous      {m['previous']}")
    for scheme in (m.get("agreement") or {}).get("schemes") or []:
        alpha = scheme.get("alpha")
        lines.append(f"  alpha {scheme.get('name')}: "
                     + ("n/a" if alpha is None else f"{alpha:.3f}"))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    from potato.snapshots import build, diff as diff_mod, store

    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            try:
                manifest = build.create_snapshot(args.config, note=args.note,
                                                 tag=args.tag, force=args.force)
            except build.SnapshotUnchanged as unchanged:
                print(f"Nothing has changed since {unchanged.existing['id']}; "
                      f"no snapshot written (use --force to write one anyway).")
                if args.tag:
                    print(f"Tagged {unchanged.existing['id']} as {args.tag}.")
                return 0
            print(f"Snapshot {manifest['id']}")
            print(f"  content hash {manifest['content_hash']}")
            print(f"  {len(manifest.get('project_files') or [])} study file(s) besides the config")
            if args.tag:
                print(f"  tagged {args.tag}")
            for note in manifest.get("omitted") or []:
                print(f"  left out (credentials): {note}")
            for folder in manifest.get("referenced_directories") or []:
                print(f"  not copied (a folder): {folder}")
            for warning in manifest.get("warnings") or []:
                print(f"warning: {warning}", file=sys.stderr)
            return 0
        if args.command == "list":
            snapshots = store.list_snapshots(args.config)
            if args.json:
                print(json.dumps([{k: v for k, v in s.items() if k != "bundle_contents"}
                                  for s in snapshots], indent=2))
            elif not snapshots:
                print("No snapshots yet. `potato snapshot create <config>` makes one.")
            else:
                for snapshot in snapshots:
                    print(_summary_line(snapshot))
            return 0
        if args.command == "show":
            manifest = store.resolve(args.config, args.ref)
            print(json.dumps(manifest, indent=2) if args.json else _show(manifest))
            return 0
        if args.command == "diff":
            old = store.load_snapshot(args.config, args.old)
            new = store.load_snapshot(args.config, args.new)
            result = diff_mod.diff_snapshots(old, new)
            print(diff_mod.to_json(result) if args.json else diff_mod.format_diff(result))
            return 0
        if args.command == "tag":
            manifest = store.tag_snapshot(args.config, args.ref, args.name)
            print(f"{args.name} -> {manifest['id']}")
            return 0
        if args.command == "verify":
            result = store.verify_snapshot(args.config, args.ref)
            if result["ok"]:
                print(f"{result['id']}: OK")
                return 0
            print(f"{result['id']}: FAILED")
            for problem in result["problems"]:
                print(f"  {problem}")
            return 1
    except (LookupError, ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())

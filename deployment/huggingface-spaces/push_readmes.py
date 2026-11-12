#!/usr/bin/env python3
"""Push regenerated READMEs to live Spaces without rebuilding them.

The catalog's READMEs are generated from ``spaces_manifest.yaml`` by
``build_space.render_readme``. When that template changes — as it did when
HuggingFace made Docker Spaces a paid feature and the old "Duplicate this Space
on free hardware" line became false — the live copies keep the stale text until
something pushes the new one.

A full rebuild would do it, but a Space rebuild costs a build slot, and the org
is capped at three concurrent running Spaces. This uploads README.md alone.

Usage::

    python deployment/huggingface-spaces/push_readmes.py              # dry run
    python deployment/huggingface-spaces/push_readmes.py --apply
    python deployment/huggingface-spaces/push_readmes.py --apply --only qda-mode
    python deployment/huggingface-spaces/push_readmes.py --apply --skip-running

``--skip-running`` leaves RUNNING and SLEEPING Spaces alone.

**A commit to a SLEEPING Space is destructive when the org is at its quota.**
Any commit queues a rebuild, a rebuild needs a running slot, and HuggingFace caps
the org at three concurrent cpu-basic Spaces. A paused Space absorbs the commit
and stays paused, and a running Space rebuilds in place while still serving. A
sleeping one is neither: it tries to start, gets a 403, and lands in PAUSED,
which never wakes for a visitor and cannot be restarted until a slot frees. That
is how ner-span went dark. The push refuses that combination unless
``--wake-sleeping`` says otherwise.

Requires a write token (``huggingface_hub.get_token()`` or ``HF_TOKEN``).
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_space import load_manifest, render_readme  # noqa: E402

DEFAULT_ORG = "Blablablab"
COMMIT_MESSAGE = "docs: regenerate README from manifest template"

# Concurrent cpu-basic Spaces HuggingFace allows one org on the free plan.
CPU_BASIC_QUOTA = 3


def live_readme(api, repo_id: str) -> str | None:
    """The README currently in the Space, or None when it has none."""
    try:
        path = api.hf_hub_download(repo_id=repo_id, filename="README.md",
                                   repo_type="space")
    except Exception:
        return None
    return Path(path).read_text(encoding="utf-8")


def stage_of(api, repo_id: str) -> str:
    try:
        return api.get_space_runtime(repo_id).stage
    except Exception as exc:
        return f"?({type(exc).__name__})"


def running_count(api, org: str) -> int:
    """How many of the org's Spaces currently hold a compute slot."""
    total = 0
    for space in api.list_spaces(author=org):
        try:
            if api.get_space_runtime(space.id).stage.startswith("RUNNING"):
                total += 1
        except Exception:
            pass
    return total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", default=DEFAULT_ORG)
    parser.add_argument("--only", action="append", default=None,
                        help="restrict to these space ids (repeatable)")
    parser.add_argument("--skip-running", action="store_true",
                        help="leave RUNNING/SLEEPING Spaces untouched")
    parser.add_argument("--wake-sleeping", action="store_true",
                        help="push to SLEEPING Spaces even when the org is at its "
                             "quota; the rebuild will fail and leave them PAUSED")
    parser.add_argument("--apply", action="store_true",
                        help="actually upload; without it nothing is written")
    parser.add_argument("--diff", action="store_true",
                        help="print a unified diff for each change")
    args = parser.parse_args(argv)

    from huggingface_hub import HfApi

    api = HfApi()
    spaces = load_manifest()
    selected = args.only or sorted(spaces)

    unknown = [s for s in selected if s not in spaces]
    if unknown:
        parser.error(f"not in the manifest: {', '.join(unknown)}")

    changed, unchanged, skipped, failed = [], [], [], []

    at_quota = running_count(api, args.org) >= CPU_BASIC_QUOTA
    if at_quota and not args.wake_sleeping:
        print(f"note: {args.org} is at its cpu-basic quota "
              f"({CPU_BASIC_QUOTA} running); SLEEPING Spaces will be left alone "
              f"so a failed rebuild cannot pause them.\n")

    for space_id in selected:
        repo_id = f"{args.org}/{space_id}"
        stage = stage_of(api, repo_id)

        if args.skip_running and stage in ("RUNNING", "SLEEPING"):
            skipped.append((space_id, stage))
            continue

        if stage == "SLEEPING" and at_quota and not args.wake_sleeping:
            skipped.append((space_id, "SLEEPING/at-quota"))
            continue

        try:
            wanted = render_readme(spaces[space_id])
        except SystemExit as exc:      # render_readme validates HF colors
            failed.append((space_id, str(exc)))
            continue

        current = live_readme(api, repo_id)
        if current == wanted:
            unchanged.append(space_id)
            continue

        print(f"{space_id:<28} {stage:<12} README differs")
        if args.diff and current is not None:
            sys.stdout.writelines(difflib.unified_diff(
                current.splitlines(keepends=True),
                wanted.splitlines(keepends=True),
                fromfile=f"{space_id}/live", tofile=f"{space_id}/generated"))

        if not args.apply:
            changed.append(space_id)
            continue

        try:
            api.upload_file(
                path_or_fileobj=wanted.encode("utf-8"),
                path_in_repo="README.md",
                repo_id=repo_id,
                repo_type="space",
                commit_message=COMMIT_MESSAGE,
            )
        except Exception as exc:
            failed.append((space_id, f"{type(exc).__name__}: {exc}"))
            continue

        after = stage_of(api, repo_id)
        note = "" if after == stage else f"  -> {after}"
        print(f"{space_id:<28} pushed{note}")
        changed.append(space_id)

    verb = "pushed" if args.apply else "would push"
    print(f"\n{verb}: {len(changed)}   already current: {len(unchanged)}"
          f"   skipped: {len(skipped)}   failed: {len(failed)}")
    for space_id, reason in failed:
        print(f"  FAILED {space_id}: {reason}")
    for space_id, why in skipped:
        print(f"  skipped {space_id}: {why}")
    if not args.apply and changed:
        print("\nRe-run with --apply to upload.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

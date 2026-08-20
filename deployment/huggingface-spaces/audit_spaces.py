#!/usr/bin/env python3
"""Reconcile the Spaces manifest against what is actually live on HuggingFace.

Written after an audit found 23 of 64 manifest entries had never been deployed,
one had uploaded only two files, and 37 of the rest sat PAUSED — a state that,
unlike SLEEPING, does not wake when a visitor opens the page. None of that was
visible from the manifest, because nothing ever compared the two.

Usage::

    python deployment/huggingface-spaces/audit_spaces.py            # human report
    python deployment/huggingface-spaces/audit_spaces.py --json     # machine readable
    python deployment/huggingface-spaces/audit_spaces.py --check    # exit 1 on drift

``--check`` is the CI-friendly form: it fails when a featured Space is not
reachable, or when a manifest entry claims to be deployed and is not.

Requires a read token (``huggingface_hub.get_token()`` or ``HF_TOKEN``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

MANIFEST = Path(__file__).with_name("spaces_manifest.yaml")
DEFAULT_ORG = "Blablablab"

# Stages from which a visitor gets a working demo. SLEEPING counts: free-tier
# Spaces sleep on idle and wake on the next request. PAUSED does not — HF only
# restarts a paused Space when its owner asks, so a visitor sees a dead page.
HEALTHY_STAGES = {"RUNNING", "SLEEPING"}
TRANSIENT_STAGES = {"BUILDING", "APP_STARTING", "RUNNING_BUILDING"}


def load_manifest(path: Path = MANIFEST) -> tuple[list, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("spaces", []), data.get("defaults", {}) or {}


def audit(org: str = DEFAULT_ORG) -> dict:
    """Compare every manifest entry with its live counterpart."""
    from huggingface_hub import HfApi

    api = HfApi()
    entries, defaults = load_manifest()

    live_ids = {s.id.split("/", 1)[1] for s in api.list_spaces(author=org)}

    rows = []
    for entry in entries:
        space_id = entry["id"]
        featured = bool(entry.get("featured", defaults.get("featured", False)))
        record = {
            "id": space_id,
            "category": entry.get("category", "?"),
            "featured": featured,
            "manifest_status": entry.get("status", defaults.get("status", "ready")),
            "deployed": space_id in live_ids,
            "stage": None,
            "error": None,
            "file_count": None,
            "healthy": False,
        }

        if record["deployed"]:
            try:
                runtime = api.get_space_runtime(f"{org}/{space_id}")
                raw = getattr(runtime, "raw", {}) or {}
                record["stage"] = runtime.stage
                record["error"] = raw.get("errorMessage") or None
                record["healthy"] = runtime.stage in HEALTHY_STAGES
            except Exception as exc:  # network / permission
                record["error"] = f"{type(exc).__name__}: {exc}"
            try:
                files = api.list_repo_files(f"{org}/{space_id}", repo_type="space")
                record["file_count"] = len(files)
                # A Space with no Dockerfile never got a complete upload.
                if "Dockerfile" not in files:
                    record["error"] = (record["error"] or "") + " [no Dockerfile — partial upload]"
            except Exception:
                pass

        rows.append(record)

    return {
        "org": org,
        "manifest_count": len(entries),
        "live_count": len(live_ids),
        "rows": rows,
        "orphans": sorted(live_ids - {e["id"] for e in entries}),
    }


def problems(report: dict) -> list[str]:
    """Return drift worth failing CI over."""
    issues = []
    for row in report["rows"]:
        if row["featured"]:
            if not row["deployed"]:
                issues.append(f"{row['id']}: featured but never deployed")
            elif not row["healthy"] and row["stage"] not in TRANSIENT_STAGES:
                issues.append(
                    f"{row['id']}: featured but stage={row['stage']}"
                    f"{' (' + row['error'].strip() + ')' if row['error'] else ''}"
                )
        if row["deployed"] and row["error"] and "no Dockerfile" in row["error"]:
            issues.append(f"{row['id']}: deployed but incomplete — no Dockerfile")
    return issues


def render(report: dict) -> str:
    rows = report["rows"]
    featured = [r for r in rows if r["featured"]]
    deployed = [r for r in rows if r["deployed"] and not r["featured"]]
    missing = [r for r in rows if not r["deployed"]]

    out = [
        f"Manifest entries : {report['manifest_count']}",
        f"Live in {report['org']:<9s}: {report['live_count']}",
        "",
        f"FEATURED ({len(featured)}) — these must be reachable:",
    ]
    for row in sorted(featured, key=lambda r: r["id"]):
        mark = "OK " if row["healthy"] else "BAD"
        detail = row["stage"] or ("not deployed" if not row["deployed"] else "?")
        suffix = f"  {row['error'].strip()}" if row["error"] else ""
        out.append(f"  {mark} {row['id']:28s} {detail}{suffix}")

    out.append("")
    out.append(f"DEPLOYED, NOT FEATURED ({len(deployed)}):")
    by_stage: dict = {}
    for row in deployed:
        by_stage.setdefault(row["stage"] or "unknown", []).append(row["id"])
    for stage, ids in sorted(by_stage.items()):
        out.append(f"  {stage:16s} {len(ids):3d}  {', '.join(sorted(ids)[:6])}"
                   + (" ..." if len(ids) > 6 else ""))

    out.append("")
    out.append(f"IN MANIFEST, NOT DEPLOYED ({len(missing)}):")
    for row in sorted(missing, key=lambda r: r["id"]):
        out.append(f"  {row['id']:28s} status={row['manifest_status']}")

    if report["orphans"]:
        out.append("")
        out.append(f"LIVE BUT NOT IN MANIFEST ({len(report['orphans'])}): "
                   f"{', '.join(report['orphans'])}")

    found = problems(report)
    out.append("")
    if found:
        out.append(f"PROBLEMS ({len(found)}):")
        out.extend(f"  - {p}" for p in found)
    else:
        out.append("No drift: every featured Space is reachable.")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--org", default=DEFAULT_ORG)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 when a featured Space is unreachable")
    args = parser.parse_args(argv)

    report = audit(args.org)
    print(json.dumps(report, indent=2) if args.json else render(report))

    if args.check and problems(report):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

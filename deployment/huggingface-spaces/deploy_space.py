#!/usr/bin/env python3
"""Deploy a built Potato Space to HuggingFace.

Creates (or reuses) a Docker Space repo and uploads the build directory.
Uses huggingface_hub, which auto-detects large/media files for git-lfs and
respects your stored HF login (`huggingface-cli login`) or the HF_TOKEN env var.

Usage:
    # Authenticate once (you run this):
    #   huggingface-cli login           # or: export HF_TOKEN=hf_...
    python deployment/huggingface-spaces/deploy_space.py <space-id> <hf-org> [--private]
    python deployment/huggingface-spaces/deploy_space.py --all <hf-org> [--ready-only]

Notes:
  * Builds the Space first if its build dir is missing.
  * "gated" demos (live/ingestion variants) are skipped by --all unless --include-gated.
  * "needs_ai" demos require an LLM endpoint configured to work fully; they still
    deploy, but wire ai_support/solo_mode/judge to the HF Inference API (HF_TOKEN) first.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
MANIFEST = SCRIPT_DIR / "spaces_manifest.yaml"
BUILD_ROOT = REPO_ROOT / "spaces-build"


def load_manifest():
    with open(MANIFEST) as f:
        data = yaml.safe_load(f)
    defaults = data.get("defaults", {}) or {}
    return {e["id"]: {**defaults, **e} for e in data.get("spaces", [])}


def ensure_build(space_id: str) -> Path:
    out = BUILD_ROOT / space_id
    if not (out / "config.yaml").is_file():
        print(f"  building {space_id} (no existing build) …")
        subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "build_space.py"), space_id],
            check=True,
        )
    return out


def deploy(space_id: str, org: str, entry: dict, private: bool):
    from huggingface_hub import create_repo, upload_folder

    repo_id = f"{org}/{space_id}"
    build_dir = ensure_build(space_id)
    print(f"Deploying {repo_id}  ←  {build_dir}")

    create_repo(
        repo_id,
        repo_type="space",
        space_sdk="docker",
        private=private,
        exist_ok=True,
    )
    upload_folder(
        repo_id=repo_id,
        repo_type="space",
        folder_path=str(build_dir),
        commit_message=f"Deploy Potato demo: {entry['title']}",
    )
    print(f"  ✓ https://huggingface.co/spaces/{repo_id}")
    if entry.get("needs_ai"):
        print("    ⚠ needs an LLM endpoint — set HF_TOKEN and wire ai_support/solo_mode/judge "
              "to the HF Inference API for full functionality.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("space_id", nargs="?", help="Space id (or use --all)")
    ap.add_argument("org", nargs="?", help="HF org/user namespace (e.g. Blablablab)")
    ap.add_argument("--all", action="store_true", help="Deploy every manifest entry")
    ap.add_argument("--ready-only", action="store_true",
                    help="With --all: skip needs_ai demos too")
    ap.add_argument("--include-gated", action="store_true",
                    help="With --all: include 'gated' live/ingestion variants")
    ap.add_argument("--private", action="store_true")
    args = ap.parse_args()

    spaces = load_manifest()

    if args.all:
        org = args.space_id or args.org
        if not org:
            ap.error("--all requires an org: deploy_space.py --all <hf-org>")
        for sid, entry in spaces.items():
            if entry.get("status") == "gated" and not args.include_gated:
                print(f"  skip {sid} (gated)")
                continue
            if entry.get("needs_ai") and args.ready_only:
                print(f"  skip {sid} (needs AI)")
                continue
            deploy(sid, org, entry, args.private)
        return

    if not args.space_id or not args.org:
        ap.error("usage: deploy_space.py <space-id> <hf-org>  (or --all <hf-org>)")
    if args.space_id not in spaces:
        raise SystemExit(f"unknown space id '{args.space_id}'")
    deploy(args.space_id, args.org, spaces[args.space_id], args.private)


if __name__ == "__main__":
    main()

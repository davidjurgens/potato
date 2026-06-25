#!/usr/bin/env python3
"""Build a push-ready HuggingFace Space from the spaces_manifest.yaml catalog.

Assembles a self-contained Space directory (Docker SDK, port 7860) for a single
manifest entry: copies the source examples/ project (config + data + layouts),
the potato package source, deployment scaffolding, and a generated HF README with
valid frontmatter. Optionally writes a .gitattributes for git-lfs media demos.

Usage:
    python deployment/huggingface-spaces/build_space.py <space-id> [output_dir]
    python deployment/huggingface-spaces/build_space.py --all [output_root]
    python deployment/huggingface-spaces/build_space.py --list

The output can be pushed directly to a HuggingFace Space repo (see deploy_space.sh).
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
MANIFEST = SCRIPT_DIR / "spaces_manifest.yaml"
TEMPLATE_DIR = SCRIPT_DIR / "demo-space"  # source of Dockerfile + entrypoint

# Files/dirs never copied from an examples/ source project.
SOURCE_EXCLUDES = [
    "annotation_output",
    "*.sqlite",
    "*.sqlite-shm",
    "*.sqlite-wal",
    "admin_api_key.txt",
    "__pycache__",
    "*.pyc",
    "*.log",
    ".DS_Store",
]
# Excludes when copying the potato package source.
POTATO_EXCLUDES = ["__pycache__", "*.pyc", ".git", "node_modules"]

LFS_PATTERNS = [
    "*.mp4", "*.webm", "*.mov", "*.mkv",
    "*.wav", "*.mp3", "*.ogg", "*.flac", "*.m4a",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp",
    "*.pdf",
]


def load_manifest():
    with open(MANIFEST) as f:
        data = yaml.safe_load(f)
    defaults = data.get("defaults", {}) or {}
    spaces = {}
    for entry in data.get("spaces", []):
        merged = {**defaults, **entry}
        spaces[entry["id"]] = merged
    return spaces


def patch_demo_config(config_path: Path):
    """Make a demo frictionless: name-only login, no password, no registration.
    Sets require_no_password + allow_all_users so visitors just enter a name."""
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    cfg["require_no_password"] = True       # flask_server maps this to require_password=False
    cfg.pop("require_password", None)        # avoid a conflicting explicit value
    uc = cfg.get("user_config")
    if not isinstance(uc, dict):
        uc = {}
    uc["allow_all_users"] = True
    cfg["user_config"] = uc
    # Drop any crowd-login type that would force a different flow
    if isinstance(cfg.get("login"), dict) and cfg["login"].get("type") in ("mturk", "prolific", "url_direct"):
        cfg["login"]["type"] = "standard"
    with open(config_path, "w") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def rsync(src: Path, dst: Path, excludes):
    dst.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-a"]
    for pat in excludes:
        cmd += ["--exclude", pat]
    cmd += [f"{src}/", f"{dst}/"]
    subprocess.run(cmd, check=True)


# HuggingFace Spaces only accepts these colorFrom/colorTo values.
HF_COLORS = {"red", "yellow", "green", "blue", "indigo", "purple", "pink", "gray"}


def render_readme(entry) -> str:
    for key in ("color_from", "color_to"):
        if entry[key] not in HF_COLORS:
            raise SystemExit(
                f"[{entry['id']}] invalid HF {key}='{entry[key]}'. "
                f"Allowed: {', '.join(sorted(HF_COLORS))}")
    base_tags = ["annotation", "potato", entry["category"]]
    tags = base_tags + [t for t in entry.get("tags", []) if t not in base_tags]
    tag_lines = "\n".join(f"  - {t}" for t in tags)
    repo = "https://github.com/davidjurgens/potato"
    site = "https://www.potatoannotator.com"
    return f"""---
title: {entry['title']}
emoji: {entry['emoji']}
colorFrom: {entry['color_from']}
colorTo: {entry['color_to']}
sdk: docker
app_port: 7860
pinned: false
license: {entry['license']}
tags:
{tag_lines}
---

# {entry['title']}

{entry['summary']}

A live demo of **[Potato]({site})** — the free, self-hosted annotation platform for NLP,
agentic, and GenAI research, configured entirely through YAML.
Visit **[www.potatoannotator.com]({site})** for docs, the schema gallery, and more demos.

## Try it out

1. Enter any username to log in (no password required).
2. Read the item shown in the main panel.
3. Annotate using the schemes on the right.
4. Click **Next** to continue.

> **Run your own copy:** click the **⋮ → Duplicate this Space** button (top-right) to launch
> this exact demo in your own account on free hardware — change the data and config to make it yours.

> Annotations in this demo are ephemeral. To collect and keep data, deploy your own
> Space — see the [deployment guide]({repo}/blob/master/deployment/huggingface-spaces/deploy.md).

## About Potato

Potato supports 20+ annotation types — text, spans, images, audio, video, documents,
and agent traces — with AI-assisted labeling, quality control, and adjudication.

🥔 **Website: [www.potatoannotator.com]({site})** &nbsp;·&nbsp;
[Documentation]({site}) &nbsp;·&nbsp;
[GitHub]({repo}) &nbsp;·&nbsp;
[All demos]({repo}/blob/master/docs/data-export/potato_on_huggingface.md)
"""


def build_space(entry, out_dir: Path):
    space_id = entry["id"]
    source = REPO_ROOT / entry["source"]
    config = source / "config.yaml"
    if not config.is_file():
        raise SystemExit(f"[{space_id}] source config not found: {config}")

    print(f"Building Space '{space_id}'  ({entry['source']}) → {out_dir}")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # 1. Copy the examples/ project (config + data + layouts + any aux files)
    rsync(source, out_dir, SOURCE_EXCLUDES)
    patch_demo_config(out_dir / "config.yaml")  # frictionless name-only login

    # 2. Copy the potato package source
    rsync(REPO_ROOT / "potato", out_dir / "potato", POTATO_EXCLUDES)

    # 3. Project install files
    for fname in ("requirements.txt", "setup.py"):
        shutil.copy2(REPO_ROOT / fname, out_dir / fname)

    # 4. Deployment scaffolding (Dockerfile + entrypoint)
    shutil.copy2(TEMPLATE_DIR / "Dockerfile", out_dir / "Dockerfile")
    entrypoint = out_dir / "entrypoint.sh"
    shutil.copy2(TEMPLATE_DIR / "entrypoint.sh", entrypoint)
    entrypoint.chmod(0o755)

    # 5. Generated HF README with frontmatter
    (out_dir / "README.md").write_text(render_readme(entry))

    # 6. Empty output dir so the app can write at runtime
    ann_out = out_dir / "annotation_output"
    ann_out.mkdir(exist_ok=True)
    (ann_out / ".gitkeep").write_text("")

    # 7. git-lfs for media demos
    if entry.get("needs_lfs"):
        lfs = "\n".join(f"{p} filter=lfs diff=lfs merge=lfs -text" for p in LFS_PATTERNS)
        (out_dir / ".gitattributes").write_text(lfs + "\n")

    print(f"  ✓ {space_id} built"
          f"{'  (git-lfs media)' if entry.get('needs_lfs') else ''}"
          f"{'  [needs AI endpoint]' if entry.get('needs_ai') else ''}"
          f"{'  [GATED — verify static render]' if entry.get('status') == 'gated' else ''}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("space_id", nargs="?", help="Space id from the manifest")
    ap.add_argument("output", nargs="?", help="Output dir (default: spaces-build/<id>)")
    ap.add_argument("--all", action="store_true", help="Build every manifest entry")
    ap.add_argument("--list", action="store_true", help="List manifest entries and exit")
    args = ap.parse_args()

    spaces = load_manifest()

    if args.list:
        for sid, e in spaces.items():
            flags = []
            if e.get("needs_lfs"):
                flags.append("lfs")
            if e.get("needs_ai"):
                flags.append("ai")
            if e.get("status") == "gated":
                flags.append("gated")
            tag = f"  [{','.join(flags)}]" if flags else ""
            print(f"{sid:28} {e['category']:14} {e['source']}{tag}")
        print(f"\n{len(spaces)} spaces in catalog")
        return

    build_root = REPO_ROOT / "spaces-build"
    if args.all:
        root = Path(args.output) if args.output else build_root
        for sid, entry in spaces.items():
            build_space(entry, root / sid)
        print(f"\nBuilt {len(spaces)} spaces under {root}")
        return

    if not args.space_id:
        ap.error("provide a space id, or --all, or --list")
    if args.space_id not in spaces:
        raise SystemExit(f"unknown space id '{args.space_id}'. Try --list.")
    out = Path(args.output) if args.output else build_root / args.space_id
    build_space(spaces[args.space_id], out)
    print(f"\nDeploy with: bash {SCRIPT_DIR.name}/deploy_space.sh {args.space_id} <hf-org>")


if __name__ == "__main__":
    main()

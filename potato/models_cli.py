"""
``potato download-models`` — fetch model weights and the inference runtime.

Weights are NOT bundled with Potato and NOT downloaded implicitly. Two reasons,
and both are deliberate:

* **Licensing.** Models in this space do not share one licence, and some are
  not permissive. Shipping weights inside the package, or fetching them
  silently on first use, would push that decision onto users who never made it.
  An explicit command means the person running it has seen the licence line
  printed next to the model they asked for. One model (SAM 3) goes further and
  requires ``--accept-licence`` before anything is fetched.
* **Size.** A quantized encoder is tens of megabytes and an open-vocabulary
  detector is over a hundred. Downloading that during an annotator's first
  click would look like a hang.

Everything is verified against a pinned SHA-256. A file that does not match is
deleted rather than kept, because a half-written or substituted model produces
garbage output rather than an error, which is far harder to diagnose.

The registry itself lives in :mod:`potato.model_zoo`, because the schema
generator and the config validator need to ask questions about models that have
nothing to do with downloading them.

Usage::

    potato download-models --list
    potato download-models mobile_sam
    potato download-models grounding_dino_tiny
    potato download-models --all --dir potato/models
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from potato.model_zoo import (
    DEFAULT_MODEL,
    MODELS,
    ORT_RUNTIME,
    ORT_VERSION,
    ModelFile,
    ModelSpec,
    ModelTask,
    get as _zoo_get,
)

#: Kept as an alias: this class was named for the days when segmentation was
#: the only thing Potato downloaded.
SegmentationModel = ModelSpec

__all__ = [
    "DEFAULT_MODEL", "DEFAULT_MODEL_DIR", "MODELS", "ORT_RUNTIME",
    "ORT_VERSION", "ModelFile", "ModelSpec", "SegmentationModel",
    "available", "download_model", "installed", "main", "model_dir",
]

#: Where models land by default. Gitignored: these are large binaries fetched
#: per install, not source.
DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "models"


def _resolve(key: str) -> Optional[ModelSpec]:
    """A model by key, including the runtime, which is fetched the same way."""
    return _zoo_get(key)


def available(key: str) -> bool:
    """True when this model has concrete files that can actually be fetched."""
    model = _resolve(key)
    return bool(model and model.files)


def model_dir(base: Optional[str] = None) -> Path:
    return Path(base) if base else DEFAULT_MODEL_DIR


def installed(key: str, base: Optional[str] = None) -> bool:
    """True when every file of the model is present on disk."""
    model = _resolve(key)
    if not model or not model.files:
        return False
    root = model_dir(base) / key
    return all((root / f.name).exists() for f in model.files)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_model(key: str, base: Optional[str] = None,
                   force: bool = False, accept_licence: bool = False) -> Path:
    """
    Fetch one model, verifying every file. Returns the directory it landed in.

    Raises ``RuntimeError`` with an actionable message rather than leaving a
    partial download behind: an unverified model produces wrong output instead
    of an error, which is much harder to notice.
    """
    model = _resolve(key)
    if model is None:
        raise RuntimeError(
            f"Unknown model {key!r}. Known models: {', '.join(sorted(MODELS))}")
    if model.licence_ack and not accept_licence:
        raise RuntimeError(
            f"{key} is distributed under: {model.licence}\n"
            f"  {model.licence_url}\n"
            f"Read it, then re-run with --accept-licence to confirm you accept "
            f"its terms. Potato will not fetch a licence-gated model on your "
            f"behalf without that."
        )
    if not model.files:
        raise RuntimeError(
            f"No download is configured for {key!r} yet. Potato does not ship "
            f"or invent weight URLs; point your config at a checkpoint you "
            f"already hold, or use a model listed as available in "
            f"`potato download-models --list`."
        )

    root = model_dir(base) / key
    root.mkdir(parents=True, exist_ok=True)

    for spec in model.files:
        target = root / spec.name
        if target.exists() and not force:
            if _sha256(target) == spec.sha256:
                continue
            # A stale or corrupted file is worse than a missing one.
            target.unlink()

        tmp = target.with_suffix(target.suffix + ".part")
        try:
            urllib.request.urlretrieve(spec.url, tmp)
        except (urllib.error.URLError, OSError) as exc:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"Could not download {spec.name} for {key}: {exc}") from exc

        actual = _sha256(tmp)
        if actual != spec.sha256:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"Checksum mismatch for {spec.name}: expected {spec.sha256}, "
                f"got {actual}. The file was NOT kept — an unverified model "
                f"silently produces wrong output."
            )
        shutil.move(str(tmp), str(target))

    return root


def missing_requirements(key: str, base: Optional[str] = None) -> List[str]:
    """Zoo keys this model needs that are not installed yet.

    Declared rather than assumed: every browser model needs the runtime, and a
    user who downloads only the model gets "no available backend found", which
    reads like a browser problem rather than a missing file.
    """
    model = _resolve(key)
    if model is None:
        return []
    return [dep for dep in model.requires if not installed(dep, base)]


_TASK_HEADINGS = {
    ModelTask.INTERACTIVE_SEGMENTATION: "Click-to-segment",
    ModelTask.TEXT_DETECTION: "Text prompt -> boxes",
    ModelTask.TEXT_SEGMENTATION: "Text prompt -> masks",
    ModelTask.VIDEO_TRACKING: "Track through video",
    ModelTask.RUNTIME: "Runtime",
}


def _print_model(model: ModelSpec, base: Optional[str]) -> None:
    if not model.files:
        state = "no download configured"
    elif installed(model.key, base):
        state = "installed"
    else:
        state = f"available ({model.total_mb} MB)"
    default = "  [default]" if model.key == DEFAULT_MODEL else ""
    print(f"  {model.key:<22} {state}{default}")
    print(f"  {'':<22} {model.description}")
    flag = "" if model.commercial_use else "   <-- NON-COMMERCIAL"
    ack = "   <-- requires --accept-licence" if model.licence_ack else ""
    print(f"  {'':<22} licence: {model.licence}{flag}{ack}")
    if model.runs_on == "server":
        print(f"  {'':<22} runs on a server, not in the browser")
    if model.notes:
        print(f"  {'':<22} {model.notes}")
    print()


def _print_listing(base: Optional[str]) -> None:
    print("Models\n")
    for task in ModelTask:
        if task == ModelTask.RUNTIME:
            continue
        group = [MODELS[k] for k in sorted(MODELS) if MODELS[k].task == task]
        if not group:
            continue
        print(f"{_TASK_HEADINGS.get(task, task.value)}")
        for model in group:
            _print_model(model, base)

    print(f"{_TASK_HEADINGS[ModelTask.RUNTIME]}")
    _print_model(ORT_RUNTIME, base)

    print(f"Model directory: {model_dir(base)}")
    print("\nPotato does not bundle or auto-download weights. Review the "
          "licence for any model before using it in a study.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="potato download-models",
        description="Download model weights and the inference runtime.",
    )
    parser.add_argument("model", nargs="?", default=None,
                        help=f"Model key (default: {DEFAULT_MODEL})")
    parser.add_argument("--list", action="store_true",
                        help="Show known models and whether they are installed")
    parser.add_argument("--all", action="store_true",
                        help="Download every model that has a configured source")
    parser.add_argument("--dir", default=None,
                        help=f"Target directory (default: {DEFAULT_MODEL_DIR})")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if the file is present and valid")
    parser.add_argument("--accept-licence", "--accept-license",
                        dest="accept_licence", action="store_true",
                        help="Confirm you accept a licence-gated model's terms")
    parser.add_argument("--with-requirements", action="store_true",
                        help="Also fetch anything the model needs (the runtime)")
    args = parser.parse_args(argv)

    if args.list or (not args.model and not args.all):
        _print_listing(args.dir)
        return 0

    keys = sorted(k for k in MODELS if available(k)) if args.all \
        else [args.model or DEFAULT_MODEL]

    if args.all and not keys:
        print("No model has a configured download source yet.", file=sys.stderr)
        return 1

    if args.with_requirements:
        needed: List[str] = []
        for key in keys:
            for dep in missing_requirements(key, args.dir):
                if dep not in needed and dep not in keys:
                    needed.append(dep)
        keys = needed + keys

    for key in keys:
        try:
            path = download_model(key, args.dir, force=args.force,
                                  accept_licence=args.accept_licence)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{key} -> {path}")

    for key in keys:
        for dep in missing_requirements(key, args.dir):
            print(f"note: {key} also needs {dep!r} — run: "
                  f"potato download-models {dep}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

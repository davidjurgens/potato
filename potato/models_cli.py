"""
``potato download-models`` — fetch segmentation model weights.

Weights are NOT bundled with Potato and NOT downloaded implicitly. Two reasons,
and both are deliberate:

* **Licensing.** SAM-family releases do not share one licence, and some are not
  permissive. Shipping weights inside the package, or fetching them silently on
  first use, would push that decision onto users who never made it. An explicit
  command means the person running it has seen the licence line printed next to
  the model they asked for.
* **Size.** A quantized encoder is tens of megabytes. Downloading that during an
  annotator's first click would look like a hang.

Everything is verified against a pinned SHA-256. A file that does not match is
deleted rather than kept, because a half-written or substituted model produces
garbage masks rather than an error, which is far harder to diagnose.

Usage::

    potato download-models --list
    potato download-models mobile_sam
    potato download-models --all --dir potato/models
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

#: Where models land by default. Gitignored: these are large binaries fetched
#: per install, not source.
DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "models"


@dataclass
class ModelFile:
    """One downloadable artifact belonging to a model."""

    name: str
    url: str
    sha256: str
    size_mb: float


@dataclass
class SegmentationModel:
    """A segmentation model: what it is, what it costs, and what it permits."""

    key: str
    description: str
    licence: str
    #: False when the licence forbids commercial use without permission. Kept
    #: as a flag rather than left inside the licence string because it is the
    #: one property that can make a model unusable for a given project, and
    #: nobody reads a licence name in a list.
    commercial_use: bool = True
    #: Encoder and decoder ship separately: the encoder runs once per image and
    #: the decoder once per click, so caching them apart is what makes
    #: interactive segmentation feel instant.
    files: List[ModelFile] = field(default_factory=list)
    notes: str = ""

    @property
    def total_mb(self) -> float:
        return round(sum(f.size_mb for f in self.files), 1)


#: Pinned revision of the MobileSAM ONNX export. A commit, never `main`: a
#: moving branch turns a verified download into a checksum failure with no
#: explanation the user can act on.
_MOBILE_SAM_REV = "0d3b403339b4674a82493d5e97964dd78089ddc8"

#: The registry. Adding a model means adding it here and nowhere else.
#:
#: URLs and hashes are intentionally left unset for now: they must be filled in
#: from a specific published release and verified, and inventing them would
#: produce a command that fails at download time with a checksum error the user
#: cannot act on. `available()` reports which entries are actually fetchable.
MODELS: Dict[str, SegmentationModel] = {
    "mobile_sam": SegmentationModel(
        key="mobile_sam",
        description="MobileSAM — SAM's ViT-H encoder distilled into TinyViT",
        # Upstream MobileSAM is Apache-2.0; this particular ONNX export is
        # published under MIT. Both are permissive, but they are not the same
        # licence, so the one that actually applies to the bytes we download is
        # the one recorded here.
        licence="MIT (ONNX export); upstream MobileSAM is Apache-2.0",
        commercial_use=True,
        files=[
            # Pinned to a commit, not `main`: a branch can move under us and
            # then the checksum fails with no explanation.
            ModelFile(
                name="encoder.onnx",
                url=(f"https://huggingface.co/Acly/MobileSAM/resolve/"
                     f"{_MOBILE_SAM_REV}/mobile_sam_image_encoder.onnx"),
                sha256="580f5fb648ea1062c0aabc26217aed56921985f03f0cbbd852bba81d760cc749",
                size_mb=28.2,
            ),
            ModelFile(
                name="decoder.onnx",
                url=(f"https://huggingface.co/Acly/MobileSAM/resolve/"
                     f"{_MOBILE_SAM_REV}/sam_mask_decoder_single.onnx"),
                sha256="93915fc7c993ab9d59ab8c9ccd3bce37f7509c81ab4150a74abd4d2abbd8570d",
                size_mb=16.5,
            ),
        ],
        notes="The default. 9.66M parameters total (5M encoder) against the "
              "original SAM's 611M, at comparable mask quality. Verified: a "
              "single click produces a mask in ~1s on CPU.",
    ),
    "edge_sam": SegmentationModel(
        key="edge_sam",
        description="EdgeSAM — prompt-in-the-loop distillation, fastest on-device",
        licence="NTU S-Lab License 1.0 — NON-COMMERCIAL use only",
        commercial_use=False,
        files=[],
        notes="Fastest of the three on low-end hardware, but the licence permits "
              "redistribution and use 'for non-commercial purpose' only; "
              "commercial use requires contacting the authors. Check this "
              "against your project before annotating a dataset you intend "
              "to publish or sell.",
    ),
    "sam2_hiera_tiny": SegmentationModel(
        key="sam2_hiera_tiny",
        description="SAM 2 (Hiera tiny) — better masks, and video propagation",
        licence="Apache-2.0",
        commercial_use=True,
        files=[],
        notes="The only option that supports mask propagation across video "
              "frames. Smallest of SAM 2's four backbones "
              "(tiny / small / base+ / large).",
    ),
}

DEFAULT_MODEL = "mobile_sam"

#: ONNX Runtime Web version. Pinned, and matched to the `onnxruntime` Python
#: package used to verify the model contract, so the browser and the reference
#: implementation cannot silently diverge.
ORT_VERSION = "1.27.0"

#: The runtime is fetched, not vendored.
#:
#: Every other frontend dependency lives in `potato/static/vendor/` and is
#: committed. This one cannot: the wasm binary alone is 13.5 MB, and committing
#: it would add more to the repository than the entire rest of the source.
#: Since segmentation ALREADY requires downloading weights, putting the runtime
#: in that same step means one command makes segmentation work and an
#: air-gapped install copies exactly one directory.
#:
#: `ort.wasm.min.js` is the wasm-only build. The full `ort.min.js` also carries
#: WebGL and WebGPU backends we do not use, at 7x the size.
ORT_RUNTIME = SegmentationModel(
    key="onnxruntime",
    description=f"ONNX Runtime Web {ORT_VERSION} (wasm backend)",
    licence="MIT",
    commercial_use=True,
    files=[
        ModelFile(
            name="ort.wasm.min.js",
            url=(f"https://cdn.jsdelivr.net/npm/onnxruntime-web@{ORT_VERSION}"
                 f"/dist/ort.wasm.min.js"),
            sha256="ea3a767b15df7dbe3d695ec9c182ca0f15b2ce7750156c6b70276e11c28997f0",
            size_mb=0.05,
        ),
        # The wasm GLUE module. Easy to miss and fatal without it: ORT >= 1.20
        # dynamically imports this .mjs alongside the binary, and its absence
        # surfaces as "no available backend found", which reads like a browser
        # capability problem rather than a missing file.
        ModelFile(
            name="ort-wasm-simd-threaded.mjs",
            url=(f"https://cdn.jsdelivr.net/npm/onnxruntime-web@{ORT_VERSION}"
                 f"/dist/ort-wasm-simd-threaded.mjs"),
            sha256="0a1e718d99c41b22c21f2520ff4f9e883a6b5533856e398d21816ee8eb8185d3",
            size_mb=0.024,
        ),
        ModelFile(
            name="ort-wasm-simd-threaded.wasm",
            url=(f"https://cdn.jsdelivr.net/npm/onnxruntime-web@{ORT_VERSION}"
                 f"/dist/ort-wasm-simd-threaded.wasm"),
            sha256="d1ab1b94b16a65b29d710d0b587b29e7bed336827577623913479b8afe8113e6",
            size_mb=13.48,
        ),
    ],
    notes="Threading is left OFF at runtime: multi-threaded wasm needs "
          "SharedArrayBuffer, which needs COOP/COEP headers that Potato does "
          "not set. The threaded binary runs fine single-threaded; the "
          "non-threaded build is simply not published separately.",
)


def _resolve(key: str) -> Optional[SegmentationModel]:
    """A model by key, including the runtime, which is fetched the same way."""
    if key == ORT_RUNTIME.key:
        return ORT_RUNTIME
    return MODELS.get(key)


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
                   force: bool = False) -> Path:
    """
    Fetch one model, verifying every file. Returns the directory it landed in.

    Raises ``RuntimeError`` with an actionable message rather than leaving a
    partial download behind: an unverified model produces wrong masks instead
    of an error, which is much harder to notice.
    """
    model = _resolve(key)
    if model is None:
        raise RuntimeError(
            f"Unknown model {key!r}. Known models: {', '.join(sorted(MODELS))}")
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
                f"silently produces wrong masks."
            )
        shutil.move(str(tmp), str(target))

    return root


def _print_listing(base: Optional[str]) -> None:
    print("Segmentation models\n")
    for key in sorted(MODELS):
        model = MODELS[key]
        if not model.files:
            state = "no download configured"
        elif installed(key, base):
            state = "installed"
        else:
            state = f"available ({model.total_mb} MB)"
        default = "  [default]" if key == DEFAULT_MODEL else ""
        print(f"  {key:<20} {state}{default}")
        print(f"  {'':<20} {model.description}")
        flag = "" if model.commercial_use else "   <-- NON-COMMERCIAL"
        print(f"  {'':<20} licence: {model.licence}{flag}")
        if model.notes:
            print(f"  {'':<20} {model.notes}")
        print()
    print(f"Model directory: {model_dir(base)}")
    print("\nPotato does not bundle or auto-download weights. Review the "
          "licence for any model before using it in a study.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="potato download-models",
        description="Download segmentation model weights for Potato.",
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
    args = parser.parse_args(argv)

    if args.list or (not args.model and not args.all):
        _print_listing(args.dir)
        return 0

    keys = sorted(k for k in MODELS if available(k)) if args.all \
        else [args.model or DEFAULT_MODEL]

    if args.all and not keys:
        print("No model has a configured download source yet.", file=sys.stderr)
        return 1

    for key in keys:
        try:
            path = download_model(key, args.dir, force=args.force)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{key} -> {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

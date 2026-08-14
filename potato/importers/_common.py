"""
Helpers shared by every annotation importer.

``apply_url_prefix`` lived as five byte-identical private copies, one per
importer, which is how three of them came to ignore ``--image-url-prefix``
entirely: the flag was parsed, threaded through options, and then dropped,
so the canvas 404'd with nothing in the UI explaining why. A single definition
means a new importer either calls it or visibly does not.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

#: Extensions we will look for when pairing an annotation with its image.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")

#: Assumed when an image cannot be found or measured. Formats that store
#: normalized coordinates are unaffected in geometry; only the recorded pixel
#: dimensions are a guess, and the caller is warned when this is used.
FALLBACK_SIZE = (1000, 1000)


def apply_url_prefix(file_name: str, options: Optional[dict]) -> str:
    """
    Join ``--image-url-prefix`` onto a bare filename.

    Without this the generated project stores ``street.jpg``, which no route
    serves, so the canvas shows a broken image and the cause is not visible
    from the UI.
    """
    prefix = (options or {}).get("image_url_prefix") or ""
    if not prefix:
        return file_name
    return prefix.rstrip("/") + "/" + str(file_name).lstrip("/")


def probe_image_size(path: Path) -> Optional[Tuple[int, int]]:
    """
    Read an image's pixel dimensions, or None if it cannot be measured.

    Pillow is optional. Formats whose coordinates are absolute pixels need real
    dimensions to normalize correctly, so callers must warn rather than
    silently substitute a guess.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


def find_image(root: Path, stem: str,
               extensions: Iterable[str] = IMAGE_EXTENSIONS) -> Optional[Path]:
    """Locate ``stem.<ext>`` under ``root``, searching common image folders."""
    candidates = [root, root / "images", root / "JPEGImages", root / "img1",
                  root.parent / "images"]
    for base in candidates:
        if not base.is_dir():
            continue
        for ext in extensions:
            candidate = base / f"{stem}{ext}"
            if candidate.exists():
                return candidate
    return None


def safe_instance_id(text: str) -> str:
    """
    A stable, filesystem- and URL-safe instance id derived from a path.

    Frame-sequence formats key items by ``sequence/frame``, and that slash
    reaches URLs and filenames, so it is flattened here rather than in each
    importer.
    """
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text)).strip("_") or "item"

"""
Image transcoding for formats no browser displays.

TIFF, HEIC and camera RAW are what scientific and photographic corpora actually
arrive as, and every one of them renders as a broken image in every browser.
They are converted to WebP on first request.

The part that matters beyond "make it display" is **16-bit windowing**.
A 16-bit microscopy or medical TIFF has a value range no display can show, and
the naive conversion — Pillow's default 8-bit cast — divides by 256 and throws
away exactly the low-contrast detail such images are captured for. A scan whose
interesting structure lives between 1200 and 1800 becomes uniform black, which
looks like a corrupt file rather than a windowing problem. So:

* the source's real min/max are measured and reported;
* a window (``min``, ``max``, ``gamma``) can be applied per request, which is
  what the annotator's sliders drive;
* with no window given, the default is a **percentile stretch**, not a raw
  cast, so the first render is legible.

Multi-page TIFFs expose a page index rather than silently showing page 0, which
would present a 40-slice stack as a single image and lose the rest without
saying anything.

Pillow is optional; HEIC additionally needs ``pillow-heif`` and RAW needs
``rawpy``. Each absence produces the install command for that specific format.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ImageTranscodeError(RuntimeError):
    """Raised with a message the UI can show verbatim."""


#: Extensions browsers render natively. Anything here is served as-is.
IMAGE_PASSTHROUGH = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif",
                     ".svg", ".ico"}

#: Extensions we transcode, mapped to the extra dependency each needs.
TRANSCODE_IMAGE_EXTENSIONS = {
    ".tif": "", ".tiff": "",
    ".heic": "pillow-heif", ".heif": "pillow-heif",
    ".dng": "rawpy", ".cr2": "rawpy", ".cr3": "rawpy", ".nef": "rawpy",
    ".arw": "rawpy", ".orf": "rawpy", ".rw2": "rawpy", ".raf": "rawpy",
    ".pef": "rawpy", ".srw": "rawpy",
    ".jp2": "", ".j2k": "", ".ppm": "", ".pgm": "", ".pbm": "", ".pnm": "",
}

#: Percentile stretch used when no explicit window is requested. Clipping the
#: extremes is what makes a 16-bit scan legible on first view; a raw cast
#: usually renders as near-black.
DEFAULT_LOW_PERCENTILE = 0.5
DEFAULT_HIGH_PERCENTILE = 99.5

#: Pillow modes whose samples exceed 8 bits.
HIGH_DEPTH_MODES = {"I", "I;16", "I;16B", "I;16L", "I;16N", "F", "I;32"}

WEBP_QUALITY = 90


def needs_transcode(path: str) -> bool:
    """Whether this file has to be converted before a browser can show it."""
    return Path(path).suffix.lower() in TRANSCODE_IMAGE_EXTENSIONS


def _require_pillow():
    try:
        from PIL import Image
    except ImportError:
        raise ImageTranscodeError(
            "This image format needs Pillow, which is not installed. "
            "Install it with `pip install Pillow`, or convert the file to "
            "PNG/JPEG yourself.")
    return Image


def _open(path: Path, page: int = 0):
    """
    Open any supported source as a Pillow image.

    HEIC and RAW need their own decoders, and each reports its own install
    command — "install Pillow" is unhelpful when Pillow is already present and
    the missing piece is `pillow-heif`.
    """
    Image = _require_pillow()
    suffix = path.suffix.lower()

    if suffix in (".heic", ".heif"):
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except ImportError:
            raise ImageTranscodeError(
                "HEIC images need the pillow-heif decoder. Install it with "
                "`pip install pillow-heif`, or convert with "
                "`heif-convert photo.heic photo.jpg`.")

    if suffix in (".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2",
                  ".raf", ".pef", ".srw"):
        try:
            import rawpy
        except ImportError:
            raise ImageTranscodeError(
                f"Camera RAW ({suffix}) needs the rawpy decoder. Install it "
                f"with `pip install rawpy`, or convert with "
                f"`dcraw -c -w file{suffix} > file.ppm`.")
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess()
        return Image.fromarray(rgb)

    try:
        image = Image.open(path)
    except Exception as exc:
        raise ImageTranscodeError(f"Could not read {path.name}: {exc}")

    if page:
        try:
            image.seek(page)
        except (EOFError, ValueError):
            raise ImageTranscodeError(
                f"{path.name} has no page {page}; it has "
                f"{getattr(image, 'n_frames', 1)}.")
    return image


def describe_image(path: str) -> Dict[str, Any]:
    """
    What the UI needs to decide whether to offer windowing controls.

    Reports the real sample range for high-depth sources, because "this is
    16-bit" is not actionable but "values run 1180-1840" is.
    """
    source = Path(path)
    image = _open(source)
    info: Dict[str, Any] = {
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
        "pages": int(getattr(image, "n_frames", 1) or 1),
        "high_depth": image.mode in HIGH_DEPTH_MODES,
        "needs_transcode": needs_transcode(path),
    }
    if info["high_depth"]:
        try:
            low, high = image.getextrema()
            info["value_min"], info["value_max"] = low, high
            stretch_low, stretch_high = _percentile_window(image)
            info["suggested_window"] = {"min": stretch_low, "max": stretch_high}
        except (TypeError, ValueError):
            pass
    return info


#: Above this many pixels, percentiles are computed from a subsample. The
#: window only needs to be approximately right, and reading every pixel of a
#: 100-megapixel scan in pure Python is slow enough to look like a hang.
PERCENTILE_SAMPLE_LIMIT = 1_000_000


def _percentile_window(image) -> Tuple[float, float]:
    """
    The default window: clip the extreme tails.

    A single hot pixel at 65535 is enough to push everything real into the
    bottom 2% of the range, so a min/max stretch renders as black. Percentiles
    are what make the first view legible without the annotator touching
    anything.

    Computed from the samples rather than ``Image.histogram()``: Pillow's
    histogram bucketing differs by mode, and on 16- and 32-bit images the bin
    edges do not correspond to the value range in the way the obvious reading
    assumes — which produced a window that mapped everything to white.
    """
    try:
        samples = list(image.getdata())
    except (OSError, ValueError):
        return 0.0, 1.0
    if not samples:
        return 0.0, 1.0

    if len(samples) > PERCENTILE_SAMPLE_LIMIT:
        stride = len(samples) // PERCENTILE_SAMPLE_LIMIT + 1
        samples = samples[::stride]

    # A multi-band high-depth image is unusual, but a tuple here would sort
    # meaninglessly rather than raising, so it is handled explicitly.
    if samples and isinstance(samples[0], (tuple, list)):
        samples = [s[0] for s in samples]

    samples.sort()
    last = len(samples) - 1

    def value_at(percentile):
        index = int(round(last * percentile / 100.0))
        return float(samples[max(0, min(last, index))])

    low = value_at(DEFAULT_LOW_PERCENTILE)
    high = value_at(DEFAULT_HIGH_PERCENTILE)
    if high <= low:
        # A flat image, or one whose content is narrower than the sampling
        # resolution. Fall back to the true extrema so it still renders.
        return float(samples[0]), float(samples[-1]) or float(samples[0]) + 1.0
    return low, high


def _apply_window(image, window_min, window_max, gamma):
    """
    Map a high-depth image into 8 bits through an explicit window.

    Pillow's own `convert("L")` on a 16-bit image divides by 256, which is a
    window of [0, 65535] -- almost never the right one, and the reason such
    images look empty by default.
    """
    Image = _require_pillow()

    if window_min is None or window_max is None:
        window_min, window_max = _percentile_window(image)
    span = float(window_max) - float(window_min)
    if span <= 0:
        span = 1.0

    scale = 255.0 / span
    offset = -float(window_min) * scale
    # Pillow evaluates point() on a 32-bit ("I") image SYMBOLICALLY and accepts
    # only a linear `v * scale + offset`. Clamping inside the lambda raises
    # TypeError, so the clamp is left to the "L" target mode, which saturates
    # out-of-range values -- exactly the behaviour a display window wants.
    #
    # Pillow does NOT reliably honour the target mode here: on mode "I" it
    # returns another "I" image, and a later 256-entry LUT (the gamma step)
    # then fails with "point operation not supported for this mode". So the
    # conversion is forced rather than assumed.
    windowed = image.point(lambda v: v * scale + offset, "L")
    if windowed.mode != "L":
        windowed = windowed.convert("L")

    if gamma and abs(float(gamma) - 1.0) > 1e-6:
        inverse = 1.0 / float(gamma)
        table = [min(255, int(((i / 255.0) ** inverse) * 255 + 0.5))
                 for i in range(256)]
        windowed = windowed.point(table)
    return windowed


def transcode_image(source: str, destination: str, *,
                    page: int = 0,
                    window_min: Optional[float] = None,
                    window_max: Optional[float] = None,
                    gamma: float = 1.0,
                    max_pixels: Optional[int] = None) -> Dict[str, Any]:
    """
    Convert ``source`` to a browser-displayable WebP at ``destination``.

    Args:
        source: Path to the original file
        destination: Path to write (``.webp``)
        page: Page/frame index for multi-page TIFFs
        window_min: Low end of the display window (high-depth sources)
        window_max: High end of the display window
        gamma: Gamma applied after windowing; 1.0 is none
        max_pixels: Downscale above this pixel count, preserving aspect

    Returns:
        Metadata about what was written, including the window actually used.

    Raises:
        ImageTranscodeError: With a message suitable for showing to the user.
    """
    source_path = Path(source)
    if not source_path.exists():
        raise ImageTranscodeError(f"{source_path.name} does not exist")

    image = _open(source_path, page=page)
    used_window = None

    if image.mode in HIGH_DEPTH_MODES:
        if window_min is None or window_max is None:
            window_min, window_max = _percentile_window(image)
        used_window = {"min": window_min, "max": window_max, "gamma": gamma}
        image = _apply_window(image, window_min, window_max, gamma)
    elif image.mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGBA" if "A" in image.mode else "RGB")

    if max_pixels and image.width * image.height > max_pixels:
        from PIL import Image as PILImage

        ratio = (max_pixels / (image.width * image.height)) ** 0.5
        image = image.resize(
            (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
            PILImage.LANCZOS)

    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        image.save(destination_path, "WEBP", quality=WEBP_QUALITY)
    except Exception as exc:
        raise ImageTranscodeError(
            f"Could not write a WebP for {source_path.name}: {exc}")

    return {
        "path": str(destination_path),
        "width": image.width,
        "height": image.height,
        "window": used_window,
        "page": page,
    }

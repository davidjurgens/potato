"""
Helpers shared by the digital-humanities importers (W3C Web Annotation, IIIF,
PAGE XML) and the TEI text importer.

* reading a JSON document from a local file or, only when the caller passed an
  http(s) URL explicitly, from the network;
* the text a span's offsets index once Potato has rendered an item, and a map
  from offsets in the source string to offsets in that text;
* SVG and media-fragment geometry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlparse

#: Largest remote document read (bytes). A IIIF manifest of a 1,000-page
#: volume is a few megabytes.
MAX_REMOTE_BYTES = 50 * 1024 * 1024
REMOTE_TIMEOUT = 30


def is_url(value: Any) -> bool:
    return isinstance(value, str) and value.lower().startswith(("http://", "https://"))


def repair_url(value: str) -> str:
    """``Path("https://x/y")`` collapses the double slash; put it back."""
    for scheme in ("https:/", "http:/"):
        if value.startswith(scheme) and not value.startswith(scheme + "/"):
            return scheme + "/" + value[len(scheme):]
    return value


def fetch_json(url: str) -> Any:
    """GET a JSON document over http(s). Raises ValueError on anything else."""
    if not is_url(url):
        raise ValueError(f"only http(s) URLs are fetched, not {url!r}")
    import urllib.request
    request = urllib.request.Request(url, headers={
        "Accept": "application/ld+json, application/json;q=0.9, */*;q=0.1",
        "User-Agent": "potato-import",
    })
    try:
        with urllib.request.urlopen(request, timeout=REMOTE_TIMEOUT) as response:  # noqa: S310
            raw = response.read(MAX_REMOTE_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"could not fetch {url}: {exc}") from exc
    if len(raw) > MAX_REMOTE_BYTES:
        raise ValueError(f"{url} is larger than {MAX_REMOTE_BYTES // (1024 * 1024)} MB")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{url} is not JSON: {exc}") from exc


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{path} is not JSON: {exc}") from exc


def within(path: Path, roots: Iterable[Optional[Path]]) -> bool:
    """Whether ``path``, with symlinks resolved, lies inside one of ``roots``."""
    try:
        real = Path(path).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    for root in roots:
        if root is None:
            continue
        try:
            top = Path(root).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if real == top or top in real.parents:
            return True
    return False


def local_path(reference: str, base_dir: Optional[Path],
               roots: Optional[Iterable[Optional[Path]]] = None,
               refused: Optional[Callable[[str], None]] = None) -> Optional[Path]:
    """A ``file://`` URI or a relative/absolute path that names an existing file
    inside ``roots`` (default: ``base_dir``).

    An import file is data from somewhere else. A path that leaves the input
    (``/etc/hosts``, ``file:///...``, ``../../x``, a symlink out) would copy a
    local file into the project's ``media/``, which the server publishes, so
    it is refused, and ``refused`` is called with the reference.
    """
    if not isinstance(reference, str) or not reference or is_url(reference):
        return None
    ref = reference.split("#", 1)[0]
    if ref.startswith("file://"):
        ref = unquote(urlparse(ref).path)
    elif ":" in ref.split("/", 1)[0] and not re.match(r"^[A-Za-z]:[\\/]", ref):
        return None          # urn:..., tag:..., some other scheme
    candidate = Path(ref)
    if not candidate.is_absolute() and base_dir is not None:
        candidate = Path(base_dir) / candidate
    if not candidate.is_file():
        return None
    allowed = list(roots) if roots is not None else [base_dir]
    if not within(candidate, allowed):
        if refused is not None:
            refused(reference)
        return None
    return candidate


def refusal_warning(result: Any, where: str) -> Callable[[str], None]:
    """A ``refused`` callback that warns on ``result`` and counts the refusal."""
    def warn(reference: str) -> None:
        result.warn(f"{where}: {reference} is outside the input folder and --image-dir; "
                    "not copied (move the file into the input folder, or pass --image-dir)")
        result.skipped["files outside the input folder"] += 1
    return warn


def unmeasured_reason(path: Optional[Path]) -> str:
    """Why ``probe_image_size(path)`` came back empty, for a warning."""
    if path is None:
        return "the image is not a local file"
    try:
        import PIL  # noqa: F401
    except ImportError:
        return "Pillow is not installed (pip install pillow)"
    return f"Pillow could not read {Path(path).name}"


def slug(text: Any, fallback: str = "item") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "")).strip("-._")
    return value[:80] or fallback


def unique_id(base: str, seen: set) -> str:
    candidate, n = base, 2
    while candidate in seen:
        candidate = f"{base}-{n}"
        n += 1
    seen.add(candidate)
    return candidate


def iri_tail(iri: str) -> str:
    """The last path segment of an IRI (or the part after the last ``:`` of a URN)."""
    value = str(iri or "").split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if value.startswith("urn:"):
        return value.rsplit(":", 1)[-1]
    return unquote(value.rsplit("/", 1)[-1])


# ---------------------------------------------------------------------------
# Rendered text
# ---------------------------------------------------------------------------

def rendered_text(raw: str) -> Tuple[str, Callable[[int], int]]:
    """The text the annotation page holds for ``raw``, and an offset map.

    Potato's span offsets index the instance text as the browser holds it:
    control characters dropped, runs of spaces and tabs collapsed to one,
    the ends trimmed, the result sanitized (see ``ExportContext.covered_text``).
    An importer that computes offsets on the source string has to move them
    into that text, or every span after a doubled space lands one character
    late.

    The returned function maps an offset in ``raw`` to the offset of the same
    character in the rendered text (a deleted character maps to the position of
    the next character that survives).
    """
    from potato.server_utils.span_text import instance_dom_text, normalize_display_text
    dom = instance_dom_text(normalize_display_text(raw or ""))
    if dom == raw:
        return dom, (lambda offset: offset)
    mapping: List[int] = []
    j = 0
    for ch in raw:
        if j < len(dom) and (ch == dom[j] or (ch in " \t" and dom[j] == " ")):
            mapping.append(j)
            j += 1
        else:
            mapping.append(j)
    mapping.append(len(dom))

    def remap(offset: int) -> int:
        offset = max(0, min(int(offset), len(raw)))
        return mapping[offset]
    return dom, remap


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def locate_quote(text: str, exact: str, prefix: str = "", suffix: str = "",
                 hint: Optional[int] = None) -> Optional[Tuple[int, int]]:
    """Find ``exact`` in ``text`` the way a TextQuoteSelector means it.

    Every occurrence is scored by how much of ``prefix`` it is preceded by and
    how much of ``suffix`` it is followed by; ties go to the one nearest
    ``hint`` (a position the source also gave, possibly off by a few
    characters). Returns ``(start, end)`` or None when ``exact`` is absent.
    """
    if not exact:
        return None
    best = None
    start = text.find(exact)
    while start != -1:
        end = start + len(exact)
        before = text[:start]
        after = text[end:]
        score = 0
        if prefix:
            score += _common_suffix(before, prefix)
        if suffix:
            score += _common_prefix(after, suffix)
        distance = abs(start - hint) if hint is not None else 0
        key = (-score, distance, start)
        if best is None or key < best[0]:
            best = (key, (start, end))
        start = text.find(exact, start + 1)
    return best[1] if best else None


def _common_suffix(a: str, b: str) -> int:
    n = 0
    while n < len(a) and n < len(b) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _common_prefix(a: str, b: str) -> int:
    n = 0
    while n < len(a) and n < len(b) and a[n] == b[n]:
        n += 1
    return n


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

_XYWH = re.compile(
    r"xywh=(?:(pixel|percent):)?\s*([-0-9.eE]+)\s*,\s*([-0-9.eE]+)\s*,\s*([-0-9.eE]+)\s*,\s*([-0-9.eE]+)")


def parse_xywh(value: str) -> Optional[Tuple[str, float, float, float, float]]:
    """``xywh=pixel:10,20,30,40`` (or ``percent:``, or no unit) -> unit, x, y, w, h."""
    match = _XYWH.search(str(value or ""))
    if not match:
        return None
    unit = match.group(1) or "pixel"
    x, y, w, h = (float(match.group(i)) for i in range(2, 6))
    if w <= 0 or h <= 0:
        return None
    return unit, x, y, w, h


_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def _floats(text: str) -> List[float]:
    return [float(v) for v in re.findall(_NUM, text or "")]


def parse_points(text: str) -> List[List[float]]:
    """``"1,2 3,4"`` or ``"1 2 3 4"`` -> ``[[1, 2], [3, 4]]``."""
    values = _floats(text)
    return [[values[i], values[i + 1]] for i in range(0, len(values) - 1, 2)]


def parse_svg(value: str) -> Optional[Dict[str, Any]]:
    """The first shape in an SvgSelector's SVG.

    Returns ``{"kind": "polygon"|"polyline"|"bbox"|"ellipse", "points" | "bbox"
    | "ellipse", "viewbox": (w, h) | None, "approximate": bool}`` or None.
    ``path`` elements are reduced to their vertices (curve control points are
    dropped), so a curved outline drawn in Mirador comes in as a polygon
    through its anchor points and is flagged approximate.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        return None
    viewbox = None
    vb = root.get("viewBox") if root.tag.endswith("svg") else None
    if vb:
        nums = _floats(vb)
        if len(nums) == 4 and nums[2] > 0 and nums[3] > 0:
            viewbox = (nums[2], nums[3])
    elif root.get("width") and root.get("height"):
        w, h = _floats(root.get("width")), _floats(root.get("height"))
        if w and h and w[0] > 0 and h[0] > 0:
            viewbox = (w[0], h[0])
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("polygon", "polyline"):
            points = parse_points(el.get("points", ""))
            if len(points) >= (3 if tag == "polygon" else 2):
                return {"kind": tag, "points": points, "viewbox": viewbox, "approximate": False}
        elif tag == "rect":
            x, y = _floats(el.get("x", "0")), _floats(el.get("y", "0"))
            w, h = _floats(el.get("width", "0")), _floats(el.get("height", "0"))
            if w and h and w[0] > 0 and h[0] > 0:
                return {"kind": "bbox", "bbox": [x[0] if x else 0.0, y[0] if y else 0.0, w[0], h[0]],
                        "viewbox": viewbox, "approximate": False}
        elif tag in ("circle", "ellipse"):
            cx, cy = _floats(el.get("cx", "0")), _floats(el.get("cy", "0"))
            if tag == "circle":
                r = _floats(el.get("r", "0"))
                rx = ry = r[0] if r else 0.0
            else:
                rx = (_floats(el.get("rx", "0")) or [0.0])[0]
                ry = (_floats(el.get("ry", "0")) or [0.0])[0]
            if rx > 0 and ry > 0:
                return {"kind": "ellipse",
                        "ellipse": {"cx": cx[0] if cx else 0.0, "cy": cy[0] if cy else 0.0,
                                    "rx": rx, "ry": ry, "angle": 0.0},
                        "viewbox": viewbox, "approximate": False}
        elif tag == "path":
            points, curved = _path_vertices(el.get("d", ""))
            if len(points) >= 3:
                return {"kind": "polygon", "points": points, "viewbox": viewbox,
                        "approximate": curved}
    return None


def _path_vertices(d: str) -> Tuple[List[List[float]], bool]:
    """Anchor points of an SVG path (M/L/H/V/C/S/Q/T/Z, absolute or relative)."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + _NUM, d or "")
    points: List[List[float]] = []
    x = y = 0.0
    cmd = None
    curved = False
    i = 0
    arity = {"M": 2, "L": 2, "T": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "A": 7}
    while i < len(tokens):
        tok = tokens[i]
        if re.match(r"[A-Za-z]", tok):
            cmd = tok
            i += 1
            if cmd in "Zz":
                continue
        if cmd is None or cmd in "Zz":
            i += 1
            continue
        n = arity[cmd.upper()]
        args = tokens[i:i + n]
        if len(args) < n:
            break
        try:
            vals = [float(a) for a in args]
        except ValueError:
            break
        i += n
        rel = cmd.islower()
        up = cmd.upper()
        if up in "CSQA":
            curved = True
        if up == "H":
            x = x + vals[0] if rel else vals[0]
        elif up == "V":
            y = y + vals[0] if rel else vals[0]
        else:
            nx, ny = vals[-2], vals[-1]
            x, y = (x + nx, y + ny) if rel else (nx, ny)
        points.append([x, y])
        if cmd == "M":
            cmd = "L"
        elif cmd == "m":
            cmd = "l"
    # A closed path repeats its first vertex; drop the duplicate.
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points, curved


def polygon_bbox(points: List[List[float]]) -> List[float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def format_points(points: List[List[float]]) -> str:
    """PAGE XML's ``x1,y1 x2,y2`` with integer pixels."""
    return " ".join(f"{int(round(x))},{int(round(y))}" for x, y in points)


def fmt_number(value: float) -> str:
    return f"{round(float(value), 2):g}"

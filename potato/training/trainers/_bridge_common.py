"""What the four inference bridges share (openai-vlm-boxes, hf-inference,
roboflow, cvat-nuclio): reading a secret by the name of the environment
variable that holds it, sending an image, posting JSON without putting a
key in an error message, and turning a service's pixel boxes and outlines
into the image widget's objects.

A bridge trains nothing. ``fit`` checks that the service answers and writes
a card naming it; ``predict`` sends the held-out and unlabelled items, so
the run gets a held-out score against this project's annotators, write-back
and review like a trained model.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from potato.training.base import TrainerError

CARD = "bridge.json"

_PROBE: Optional[bytes] = None


def secret(env: Optional[str]) -> str:
    return os.environ.get(env, "") if env else ""


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def env_problems(params: Dict[str, Any], keys: Iterable[str],
                 required: Iterable[str] = ()) -> List[str]:
    """A named environment variable that is not set is a problem; so is a
    required one left unnamed. A value that is not a variable name is not
    echoed: it is most likely the key itself, pasted in the wrong place."""
    problems = []
    for key in keys:
        env = params.get(key)
        if env and not _ENV_NAME.match(str(env)):
            problems.append("%s must be the name of an environment variable (letters, "
                            "digits and _), not the key itself. Put the key in a "
                            "variable on the server and give its name here." % key)
        elif env and not os.environ.get(env):
            problems.append("%s names %s, which is not set in the server's environment."
                            % (key, env))
        elif not env and key in required:
            problems.append("%s must name the environment variable holding the key."
                            % key)
    return problems


def scheme_labels(params: Dict[str, Any], schema, bundle) -> List[str]:
    scheme = params.get("_scheme") or {}
    names = [str(l.get("name") if isinstance(l, dict) else l)
             for l in scheme.get("labels") or []]
    return names or list(schema.labels) or list(bundle.labels(schema.name))


def label_for(name: Any, labels: List[str], label_map: Dict[str, Any],
              bio: bool = False) -> Optional[str]:
    """The scheme label a service's class name means: through *label_map*
    (a class mapped to null is dropped), then an exact or case-insensitive
    match. With *bio*, an entity tag's B-/I-/E-/S- prefix is dropped first
    when the full name matches nothing. None when the scheme has no such
    label."""
    name = "" if name is None else str(name)
    if name in (label_map or {}):
        mapped = label_map[name]
        return str(mapped) if mapped is not None and str(mapped) in labels else None
    if name in labels:
        return name
    folded = {l.lower(): l for l in labels}
    found = folded.get(name.strip().lower())
    if found is None and bio and re.match(r"^[BIES]-.", name):
        return label_for(name[2:], labels, label_map)
    return found


def image_bytes(path: str, max_side: Optional[int] = None) -> Tuple[bytes, str, int, int, float]:
    """``(bytes, mime, width, height, scale)``: the image as a JPEG or PNG,
    shrunk so its longer side is at most *max_side* (``scale`` is sent size
    over original size), with the ORIGINAL width and height."""
    from PIL import Image
    with Image.open(path) as img:
        width, height = img.size
        scale = 1.0
        if max_side and max(width, height) > max_side:
            scale = max_side / float(max(width, height))
            img = img.resize((max(1, round(width * scale)), max(1, round(height * scale))))
        # Transparency survives as PNG; everything else goes as JPEG.
        alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        buffer = io.BytesIO()
        if alpha:
            img.convert("RGBA").save(buffer, format="PNG")
            mime = "image/png"
        else:
            img.convert("RGB").save(buffer, format="JPEG", quality=92)
            mime = "image/jpeg"
    return buffer.getvalue(), mime, width, height, scale


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def probe_image() -> bytes:
    """An 8 x 8 white JPEG."""
    global _PROBE
    if _PROBE is None:
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "white").save(buffer, format="JPEG")
        _PROBE = buffer.getvalue()
    return _PROBE


def redact(url: str) -> str:
    """A URL without its query string, where an API key may be."""
    return url.split("?", 1)[0]


_SECRET_SHAPES = [
    (re.compile(r"((?:api[_-]?key|access[_-]?token|token|key)=)[^&\s\"'<>]+", re.I),
     r"\1[redacted]"),
    (re.compile(r"(Bearer|Token|Basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [redacted]"),
]


def scrub(text: Any, secrets: Iterable[str] = ()) -> str:
    """*text* with the given secrets, and anything shaped like a key in a
    query string or an Authorization header, replaced by ``[redacted]``. A
    service that echoes the request in its error body echoes the key. Scrub
    the whole text and cut it afterwards: a key cut in half is no longer the
    key, and its first half is still most of it."""
    from urllib.parse import quote
    out = "" if text is None else str(text)
    for value in secrets:
        if value and len(value) >= 4:
            for form in {value, quote(value, safe=""), quote(value)}:
                out = out.replace(form, "[redacted]")
    for pattern, repl in _SECRET_SHAPES:
        out = pattern.sub(repl, out)
    return out


def post(url: str, *, timeout: float, headers: Optional[Dict[str, str]] = None,
         json_body: Any = None, data: Any = None, secrets: Iterable[str] = ()) -> Any:
    """POST and return the parsed JSON; a TrainerError naming the URL
    without its query on failure, with any of *secrets* (and anything shaped
    like a key) scrubbed from the service's answer."""
    import requests
    secrets = [s for s in secrets if s]
    try:
        response = requests.post(url, json=json_body, data=data, headers=headers or {},
                                 timeout=timeout)
    except requests.RequestException as exc:
        raise TrainerError("Could not reach %s: %s" % (redact(url), type(exc).__name__))
    if response.status_code >= 400:
        raise TrainerError("%s answered %d: %s" % (redact(url), response.status_code,
                                                   scrub(response.text, secrets)[:300]))
    try:
        return response.json()
    except ValueError:
        raise TrainerError("%s answered with something that is not JSON: %s"
                           % (redact(url), scrub(response.text, secrets)[:200]))


def write_card(workdir: str, card: Dict[str, Any]) -> str:
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, CARD)
    with open(path, "w") as fh:
        json.dump(card, fh, indent=2)
    return path


def read_card(artifact_dir: str) -> Dict[str, Any]:
    with open(os.path.join(artifact_dir, CARD)) as fh:
        return json.load(fh)


def number(value: Any) -> Optional[float]:
    """A finite number from a service's score, or None ("high", null, nan)."""
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _finite(*values: Any) -> bool:
    try:
        return all(math.isfinite(float(v)) for v in values)
    except (TypeError, ValueError):
        return False


def box(label: str, x0: float, y0: float, x1: float, y1: float, width: int, height: int,
        score: Optional[float], version: str) -> Optional[Dict[str, Any]]:
    """A pixel box as the image widget's object, clipped to the image; None
    when nothing of it is on the image."""
    if not _finite(x0, y0, x1, y1) or not width or not height:
        return None
    x0, x1 = sorted((float(x0), float(x1)))
    y0, y1 = sorted((float(y0), float(y1)))
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(float(width), x1), min(float(height), y1)
    if x1 <= x0 or y1 <= y0:
        return None
    out = {"type": "bbox", "label": label, "color": "",
           "coordinates": {"x": round(x0 / width, 5), "y": round(y0 / height, 5),
                           "width": round((x1 - x0) / width, 5),
                           "height": round((y1 - y0) / height, 5)},
           "source": "ai", "ai_model": version}
    if number(score) is not None:
        out["confidence"] = round(number(score), 4)
    return out


def polygon(label: str, points: List[Tuple[float, float]], width: int, height: int,
            score: Optional[float], version: str) -> Optional[Dict[str, Any]]:
    """A pixel outline as the image widget's polygon, its points clipped to
    the image; None with fewer than three."""
    ring = [(min(max(float(x), 0.0), width), min(max(float(y), 0.0), height))
            for x, y in points if _finite(x, y)]
    if len(ring) < 3 or not width or not height:
        return None
    out = {"type": "polygon", "label": label, "color": "",
           "coordinates": [{"x": round(x / width, 5), "y": round(y / height, 5)}
                           for x, y in ring],
           "source": "ai", "ai_model": version}
    if number(score) is not None:
        out["confidence"] = round(number(score), 4)
    return out


def least_confident(objects: List[Dict[str, Any]]) -> Optional[float]:
    scores = [o["confidence"] for o in objects if isinstance(o.get("confidence"), (int, float))]
    return round(min(scores), 4) if scores else None


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def parse_json_text(text: str) -> Any:
    """JSON from a model's reply: the reply itself, inside a code fence, or
    the first object or array in it."""
    text = _FENCE.sub("", (text or "").strip())
    try:
        return json.loads(text)
    except ValueError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    return None

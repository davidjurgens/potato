"""
Spectrogram box annotation (``annotation_type: spectrogram_annotation``).

Annotators draw time-frequency boxes on a spectrogram of the item's audio:
drag to draw, drag a box to move it, drag its corner to resize, arrow keys to
nudge. Each box gets a label from the scheme's list (a species list, call
types). The answer is one hidden ``.annotation-data-input`` holding a JSON
list::

    [{"start_s": 1.25, "end_s": 1.9, "low_hz": 2500.0, "high_hz": 6200.0,
      "label": "Turdus migratorius"}, ...]

``low_hz`` / ``high_hz`` are null for a time-only box (imported from an
Audacity label without a spectral line, or a BirdNET CSV row), drawn as a
full-height band. Imported boxes keep their provenance keys (``source``,
``ai_model``, ``confidence``, ``import_format``); a moved or resized one gets
``edited: true``.

The spectrogram is computed in the browser (``static/spectrogram-annotation.js``:
Web Audio decode, short-time Fourier transform, one column per pixel), so no
third-party library is loaded and no server-side audio tooling is needed.
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (escape_html_content, generate_layout_attributes,
                               generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

COLORMAPS = ("viridis", "magma", "grayscale")
FFT_SIZES = (256, 512, 1024, 2048, 4096)
DEFAULT_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#9333ea", "#0891b2",
                  "#db2777", "#65a30d", "#ea580c", "#4f46e5"]


def _labels(raw: Any, schema_name: str) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"spectrogram_annotation '{schema_name}': labels must be a non-empty list")
    out = []
    for i, label in enumerate(raw):
        if isinstance(label, dict):
            name = str(label.get("name", "")).strip()
            color = label.get("color") or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
            key = label.get("key_value")
        else:
            name, color, key = str(label).strip(), DEFAULT_COLORS[i % len(DEFAULT_COLORS)], None
        if not name:
            raise ValueError(f"spectrogram_annotation '{schema_name}': label {i + 1} has no name")
        if key is None and i < 9:
            key = str(i + 1)
        out.append({"name": name, "color": str(color), "key": str(key) if key is not None else ""})
    return out


def generate_spectrogram_annotation_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    labels = _labels(annotation_scheme.get("labels"), schema_name)
    fft_size = int(annotation_scheme.get("fft_size", 1024))
    if fft_size not in FFT_SIZES:
        raise ValueError(f"spectrogram_annotation '{schema_name}': fft_size must be one of "
                         f"{', '.join(map(str, FFT_SIZES))}")
    colormap = annotation_scheme.get("colormap", "viridis")
    if colormap not in COLORMAPS:
        raise ValueError(f"spectrogram_annotation '{schema_name}': colormap must be one of "
                         f"{', '.join(COLORMAPS)}")
    config = {
        "schema": schema_name,
        "labels": labels,
        "sourceField": annotation_scheme.get("source_field", "audio_url"),
        "minFreq": float(annotation_scheme.get("min_freq", 0) or 0),
        "maxFreq": (float(annotation_scheme["max_freq"])
                    if annotation_scheme.get("max_freq") not in (None, "") else None),
        "fftSize": fft_size,
        "colormap": colormap,
        "height": int(annotation_scheme.get("height", 280)),
        "minBoxes": int(annotation_scheme.get("min_boxes", 0) or 0),
        "maxBoxes": (int(annotation_scheme["max_boxes"])
                     if annotation_scheme.get("max_boxes") not in (None, "") else None),
    }
    esc = escape_html_content(schema_name)
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    html = f"""
    <form id="{esc}" class="annotation-form spectrogram-annotation" action="javascript:void(0)"
          data-annotation-type="spectrogram_annotation" data-schema-name="{esc}"
          data-spectrogram-config='{escape_html_content(json.dumps(config))}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="sg-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="sg-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="sg-root">
                <p class="sg-loading" role="status">Loading audio…</p>
            </div>
            <input type="hidden" class="annotation-data-input spectrogram-input"
                   id="input-{esc}" name="{esc}" schema="{esc}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []

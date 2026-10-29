"""
Camera-trap detections as a review project: MegaDetector batch output and
COCO Camera Traps.

``megadetector``
    MegaDetector batch-output JSON (format_version 1.x)::

        {"info": {"format_version": "1.4", "detector": "md_v5a.0.0.pt"},
         "detection_categories": {"1": "animal", "2": "person", "3": "vehicle"},
         "classification_categories": {"5": "Puma concolor"},     # optional
         "images": [{"file": "cam1/IMG_0001.JPG",
                     "detections": [{"category": "1", "conf": 0.93,
                                     "bbox": [0.31, 0.42, 0.20, 0.18],
                                     "classifications": [["5", 0.88]]}]}]}

    ``bbox`` is ``[x, y, width, height]`` normalized to the image, from the
    top-left corner -- the same convention Potato's image annotation stores,
    so boxes need no image size. Detections below ``--md-threshold``
    (default 0.2) are left out. A detection whose ``conf`` or ``bbox`` is not
    a number is left out with a warning naming the file, the image and the
    detection; a bbox that reaches outside 0..1 is kept and warned about. The
    box keeps the detector's ``conf`` as ``confidence`` and the top
    classification's score as ``attributes.classification_confidence``, so an
    export can write each where it belongs. A video entry (``frame_rate``
    set, detections carrying ``frame_number``) is reviewed at clip level.

``coco_camera_traps``
    COCO JSON whose images carry the camera-trap fields ``seq_id``,
    ``seq_num_frames``, ``frame_num``, ``location`` and ``datetime``.
    Categories are species (plus ``empty``); annotations may have a ``bbox``
    in pixels, or none (an image-level label).

Each image becomes one item with three questions:

* ``triage`` (radio: empty / animal / person / vehicle), pre-filled from the
  highest-confidence detection, for a quick pass that separates empty frames;
* ``detections`` (image_annotation, bounding boxes), pre-filled with the
  detections, labelled with the species classification when there is one and
  the detector category otherwise;
* ``species`` (multiselect), when the source names species.

With ``--sequences``, images sharing a ``seq_id`` become one item shown as a
gallery, with ``triage`` and ``species`` answered for the sequence (boxes
cannot be drawn on a gallery; the detections ride along in the data file).

Images are served from ``/media/<file>``. With ``--image-dir`` the generated
config points ``media_directory`` at that folder; with
``--image-url-prefix`` the prefix is joined to each file name instead.
"""

from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from potato.export.cv_utils import to_client_object
from potato.importers._common import apply_url_prefix

from .base import ProjectImportResult, ProjectItem

TRIAGE_SCHEME = "triage"
DETECTION_SCHEME = "detections"
SPECIES_SCHEME = "species"
TRIAGE_LABELS = ["empty", "animal", "person", "vehicle"]
DEFAULT_MD_THRESHOLD = 0.2
MD_DEFAULT_CATEGORIES = {"1": "animal", "2": "person", "3": "vehicle"}
VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v", ".wmv", ".mts")

#: The detector's generic categories and the words datasets use for them.
_TRIAGE_WORDS = {
    "animal": "animal", "animals": "animal",
    "person": "person", "human": "person", "people": "person", "humans": "person",
    "vehicle": "vehicle", "car": "vehicle", "vehicles": "vehicle",
    "empty": "empty", "blank": "empty", "none": "empty", "nothing": "empty",
}
GENERIC_LABELS = ("animal", "person", "vehicle")

#: Species colours; the three generic categories keep their own below.
_PALETTE = ["#f58231", "#911eb4", "#f032e6", "#008080", "#9a6324", "#bcf60c",
            "#800000", "#46f0f0", "#808000", "#000075", "#fabebe", "#808080"]
_FIXED_COLORS = {"animal": "#3cb44b", "person": "#e6194b", "vehicle": "#4363d8"}


def item_id(file: str, taken: set) -> str:
    """An instance id for a file path. Ids travel in URL paths
    (``/api/spans/<id>``), so the folder separators cannot stay."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", str(file)).strip("_") or "image"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    taken.add(candidate)
    return candidate


def triage_of(name: str) -> str:
    """The triage class of a category or species name: species are animals."""
    return _TRIAGE_WORDS.get(str(name).strip().lower(), "animal")


def is_generic(name: str) -> bool:
    return str(name).strip().lower() in _TRIAGE_WORDS


def label_color(name: str, index: int) -> str:
    return _FIXED_COLORS.get(name, _PALETTE[index % len(_PALETTE)])


def _is_video(entry: dict) -> bool:
    name = str(entry.get("file") or entry.get("file_name") or "")
    return "frame_rate" in entry or name.lower().endswith(VIDEO_EXTENSIONS)


def _peek(path: Path, head: int = 1 << 20, tail: int = 1 << 16) -> Tuple[str, str]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        first = handle.read(head)
        last = b""
        if size > head:
            handle.seek(max(head, size - tail))
            last = handle.read()
    return (first.decode("utf-8", errors="replace"), last.decode("utf-8", errors="replace"))


def _load(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except ValueError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("images"), list):
        raise ValueError(f"{path.name} has no images[] list")
    return data


class _Frame:
    """One image (or video) on its way to becoming an item."""

    def __init__(self, file: str):
        self.file = file
        self.fields: Dict[str, Any] = {}
        self.boxes: List[dict] = []
        self.triage: Optional[str] = None
        self.triage_conf = -1.0
        self.species: "OrderedDict[str, None]" = OrderedDict()
        self.raw_detections: Optional[list] = None
        self.video = False

    def vote(self, triage: str, conf: float) -> None:
        if conf > self.triage_conf:
            self.triage, self.triage_conf = triage, conf


class _CameraTrapImporter:
    format_name = ""
    description = ""
    file_extensions = [".json"]
    import_label = ""

    # ---- shared assembly -------------------------------------------------

    def _url(self, file: str, options: dict) -> str:
        # A file the detector read from a URL is served from there: under
        # /media/ it was a path to nothing, and Darwin Core had no public link.
        if str(file).startswith(("http://", "https://")):
            return str(file)
        if options.get("image_url_prefix"):
            return apply_url_prefix(file, options)
        return "/media/" + str(file).replace("\\", "/").lstrip("/")

    def _probe(self, frames: List[_Frame], options: dict, result: ProjectImportResult) -> None:
        image_dir = options.get("image_dir")
        if not image_dir:
            return
        try:
            from PIL import Image
        except ImportError:   # sizes are optional; boxes are normalized
            Image = None
        missing = 0
        for frame in frames:
            path = os.path.join(image_dir, frame.file)
            if not os.path.isfile(path):
                missing += 1
                continue
            if Image is None or frame.video or frame.fields.get("image_width"):
                continue
            try:
                with Image.open(path) as handle:
                    frame.fields["image_width"], frame.fields["image_height"] = handle.size
            except Exception:  # noqa: BLE001 - an unreadable image keeps its item
                continue
        if missing:
            result.warn(f"{missing} of {len(frames)} file(s) are not under --image-dir {image_dir}")

    def _assemble(self, frames: List[_Frame], options: dict, species: List[str],
                  result: ProjectImportResult, model: str) -> ProjectImportResult:
        sequences = bool(options.get("sequences"))
        videos = [f for f in frames if f.video]
        if videos and len(videos) != len(frames):
            result.warn(f"{len(videos)} video entr{'y' if len(videos) == 1 else 'ies'} left out: "
                        "a project reviews either images or videos, and this one has images")
            result.skipped["video entries in an image project"] = len(videos)
            frames = [f for f in frames if not f.video]
        clip_level = bool(frames) and all(f.video for f in frames)
        if not frames:
            raise ValueError("no images to import")

        self._probe(frames, options, result)
        for frame in frames:
            frame.fields["file"] = frame.file
            key = "video_url" if frame.video else "image_url"
            frame.fields[key] = self._url(frame.file, options)
        if options.get("image_dir") and not options.get("image_url_prefix"):
            result.extra_config = {"media_directory": os.path.abspath(options["image_dir"])}
        elif not options.get("image_url_prefix") and not all(
                str(f.file).startswith(("http://", "https://")) for f in frames):
            result.warn("images are served from the project's media/ folder: copy or link the "
                        "image folder there, or re-run with --image-dir or --image-url-prefix")

        box_labels = OrderedDict((name, None) for name in species)
        for frame in frames:
            for box in frame.boxes:
                box_labels.setdefault(box["label"], None)
        species_names = [n for n in box_labels if not is_generic(n)]
        for frame in frames:
            for name in frame.species:
                if name not in species_names and not is_generic(name):
                    species_names.append(name)
        detection_labels = species_names + [g for g in GENERIC_LABELS]

        schemes: List[dict] = [{
            "annotation_type": "radio",
            "name": TRIAGE_SCHEME,
            "description": ("What does this sequence show?" if sequences
                            else "What does this image show?"),
            "labels": list(TRIAGE_LABELS),
            "sequential_key_binding": True,
        }]
        if not (sequences or clip_level):
            schemes.append({
                "annotation_type": "image_annotation",
                "name": DETECTION_SCHEME,
                "description": "Correct the boxes: move or resize them, change the label, "
                               "delete false detections, and draw any animal that was missed.",
                "source_field": "image_url",
                "tools": ["bbox"],
                "zoom_enabled": True,
                "pan_enabled": True,
                "labels": [{"name": n, "color": label_color(n, i)}
                           for i, n in enumerate(detection_labels)],
            })
        if species_names:
            schemes.append({
                "annotation_type": "multiselect",
                "name": SPECIES_SCHEME,
                "description": "Which species are present?",
                "labels": species_names,
            })
        result.schemes = schemes

        if sequences:
            groups: "OrderedDict[str, List[_Frame]]" = OrderedDict()
            for frame in frames:
                seq = frame.fields.get("seq_id")
                groups.setdefault(str(seq) if seq not in (None, "") else f"single:{frame.file}",
                                  []).append(frame)
            without = sum(1 for k in groups if k.startswith("single:"))
            if without:
                result.warn(f"{without} image(s) have no seq_id and are their own sequence")
            taken = set()
            for key, members in groups.items():
                members.sort(key=lambda f: (f.fields.get("frame_num") or 0, f.file))
                result.items.append(self._sequence_item(key, members, model, taken))
            result.text_key = "seq_id"
            result.instance_display = {"fields": [{
                "key": "frames", "type": "gallery", "label": "Sequence",
                "display_options": {"layout": "grid", "columns": 3, "show_captions": True,
                                    "zoomable": True}}]}
        else:
            taken: set = set()
            for frame in frames:
                result.items.append(self._frame_item(frame, clip_level, model, item_id(frame.file, taken)))
            result.text_key = "video_url" if clip_level else "image_url"
            if clip_level:
                result.instance_display = {"fields": [{
                    "key": "video_url", "type": "video", "label": "Clip"}]}
        return result

    def _frame_item(self, frame: _Frame, clip_level: bool, model: str, iid: str) -> ProjectItem:
        item = ProjectItem(instance_id=iid, fields=dict(frame.fields))
        source = {"model": model}
        if frame.triage is not None:
            item.predictions[TRIAGE_SCHEME] = frame.triage
            item.prediction_sources[TRIAGE_SCHEME] = dict(source, score=round(frame.triage_conf, 4))
        if not clip_level:
            item.predictions[DETECTION_SCHEME] = frame.boxes
            item.prediction_sources[DETECTION_SCHEME] = dict(source)
        if frame.species:
            item.predictions[SPECIES_SCHEME] = list(frame.species)
            item.prediction_sources[SPECIES_SCHEME] = dict(source)
        if frame.raw_detections is not None:
            item.fields["md_detections"] = {frame.file: frame.raw_detections}
        return item

    def _sequence_item(self, key: str, members: List[_Frame], model: str, taken: set) -> ProjectItem:
        seq_id = key[len("single:"):] if key.startswith("single:") else key
        first = members[0]
        fields: Dict[str, Any] = {
            "seq_id": seq_id,
            "files": [m.file for m in members],
            "frames": [{"url": m.fields["image_url"],
                        "caption": f"{i + 1}/{len(members)} · {os.path.basename(m.file)}"}
                       for i, m in enumerate(members)],
        }
        for name in ("location", "deployment_id", "latitude", "longitude"):
            if first.fields.get(name) not in (None, ""):
                fields[name] = first.fields[name]
        if any(m.fields.get("datetime") for m in members):
            fields["frame_datetimes"] = [m.fields.get("datetime") for m in members]
        times = sorted(str(m.fields["datetime"]) for m in members if m.fields.get("datetime"))
        if times:
            fields["datetime"], fields["datetime_end"] = times[0], times[-1]
        detections = {m.file: (m.raw_detections if m.raw_detections is not None else m.boxes)
                      for m in members}
        fields["md_detections" if any(m.raw_detections is not None for m in members)
               else "frame_boxes"] = detections
        item = ProjectItem(instance_id=item_id(seq_id, taken), fields=fields)
        best = max(members, key=lambda m: m.triage_conf)
        source = {"model": model}
        if best.triage is not None:
            item.predictions[TRIAGE_SCHEME] = best.triage
            item.prediction_sources[TRIAGE_SCHEME] = dict(source, score=round(best.triage_conf, 4))
        species = OrderedDict()
        for m in members:
            species.update(m.species)
        if species:
            item.predictions[SPECIES_SCHEME] = list(species)
            item.prediction_sources[SPECIES_SCHEME] = dict(source)
        return item


class MegaDetectorImporter(_CameraTrapImporter):
    format_name = "megadetector"
    import_label = "MegaDetector"
    description = "MegaDetector batch output (JSON) as camera-trap review: triage, boxes, species"

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != ".json":
            return False
        head, tail = _peek(path)
        text = head + tail
        return ('"detection_categories"' in text and '"images"' in text
                and ('"detections"' in head or '"failure"' in head))

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        options = dict(options or {})
        data = _load(Path(path))
        threshold = options.get("md_threshold")
        threshold = DEFAULT_MD_THRESHOLD if threshold is None else float(threshold)
        info = data.get("info") or {}
        version = str(info.get("format_version", ""))
        result = ProjectImportResult(source_format="MegaDetector batch output", text_key="image_url")
        if version and not version.startswith("1."):
            result.warn(f"format_version {version}: this importer reads 1.x; check the result")
        categories = {str(k): str(v) for k, v in
                      (data.get("detection_categories") or MD_DEFAULT_CATEGORIES).items()}
        classes = {str(k): str(v) for k, v in (data.get("classification_categories") or {}).items()}
        detector = str(info.get("detector") or "MegaDetector")
        model = os.path.splitext(os.path.basename(detector))[0] or "MegaDetector"

        frames: List[_Frame] = []
        failures = below = unreadable = outside = 0
        source_name = Path(path).name
        for image_index, entry in enumerate(data["images"]):
            if not isinstance(entry, dict) or not entry.get("file"):
                continue
            if entry.get("failure"):
                failures += 1
                continue
            frame = _Frame(str(entry["file"]).replace("\\", "/"))
            frame.video = _is_video(entry)
            for name in ("datetime", "location", "seq_id", "frame_num", "frame_rate",
                         "latitude", "longitude"):
                if entry.get(name) not in (None, ""):
                    frame.fields[name] = entry[name]
            kept = []
            for det_index, det in enumerate(entry.get("detections") or []):
                if not isinstance(det, dict):
                    continue
                where = f"{source_name}: images[{image_index}] ({frame.file}) detections[{det_index}]"
                conf = _number(det.get("conf", 0) or 0)
                if conf is None:
                    unreadable += 1
                    result.warn(f"{where}: conf {det.get('conf')!r} is not a number; "
                                f"detection left out")
                    continue
                if conf < threshold:
                    below += 1
                    continue
                kept.append(det)
                category = categories.get(str(det.get("category")), str(det.get("category")))
                label = category
                top, top_conf = _top_class(det.get("classifications"), classes)
                if top:
                    label = top
                    frame.species.setdefault(top, None)
                frame.vote(triage_of(category), conf)
                bbox = det.get("bbox")
                if frame.video or not isinstance(bbox, list) or len(bbox) < 4:
                    continue
                coords = [_number(v) for v in bbox[:4]]
                if any(v is None for v in coords):
                    unreadable += 1
                    result.warn(f"{where}: bbox {bbox[:4]!r} is not four numbers; box left out")
                    continue
                x, y, w, h = coords
                if min(x, y) < 0 or w <= 0 or h <= 0 or x + w > 1.0001 or y + h > 1.0001:
                    outside += 1
                    result.warn(f"{where}: bbox {bbox[:4]!r} reaches outside the image "
                                f"([x, y, w, h] normalized to 0..1); kept as it is")
                box = to_client_object(
                    "bbox", label, label_color(label, 0) if is_generic(label) else "",
                    img_w=1.0, img_h=1.0, bbox=coords,
                    provenance={"source": "ai", "ai_model": detector, "confidence": round(conf, 4),
                                "import_format": "megadetector"})
                if box:
                    if top and top_conf is not None:
                        box["attributes"] = {"classification_confidence": round(top_conf, 4)}
                    frame.boxes.append(box)
            image_top, _ = _top_class(entry.get("classifications"), classes)
            if image_top:
                frame.species.setdefault(image_top, None)
            if frame.triage is None:
                frame.triage, frame.triage_conf = "empty", 0.0
            if frame.video or options.get("sequences"):
                frame.raw_detections = kept
            frames.append(frame)
        if failures:
            result.skipped["images MegaDetector failed to read"] = failures
        if below:
            result.skipped[f"detections below --md-threshold {threshold}"] = below
        if unreadable:
            result.skipped["detections with a conf or bbox that is not a number"] = unreadable
        if outside:
            result.skipped["boxes reaching outside the image (kept)"] = outside
        _fill_colors(frames)
        return self._assemble(frames, options, [], result, model)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _top_class(classifications: Any, classes: Dict[str, str]) -> Tuple[Optional[str], Optional[float]]:
    """The highest-scoring species of a ``[[class_id, conf], ...]`` list, and its score."""
    if not isinstance(classifications, list):
        return None, None
    best, best_conf = None, -1.0
    for pair in classifications:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            try:
                conf = float(pair[1])
            except (TypeError, ValueError):
                continue
            if conf > best_conf:
                best, best_conf = str(pair[0]), conf
    if best is None:
        return None, None
    return classes.get(best, best), best_conf


def _fill_colors(frames: List[_Frame]) -> None:
    """Give every box the colour its label gets in the scheme."""
    order: "OrderedDict[str, None]" = OrderedDict()
    for frame in frames:
        for box in frame.boxes:
            if not is_generic(box["label"]):
                order.setdefault(box["label"], None)
    index = {name: i for i, name in enumerate(order)}
    for frame in frames:
        for box in frame.boxes:
            box["color"] = (label_color(box["label"], 0) if is_generic(box["label"])
                            else label_color(box["label"], index[box["label"]]))


class COCOCameraTrapsImporter(_CameraTrapImporter):
    format_name = "coco_camera_traps"
    import_label = "COCO Camera Traps"
    description = "COCO Camera Traps JSON (seq_id, location, datetime) as camera-trap review"

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != ".json":
            return False
        head, tail = _peek(path)
        text = head + tail
        return ('"seq_id"' in head and '"categories"' in text and '"images"' in text
                and '"detection_categories"' not in text)

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        options = dict(options or {})
        data = _load(Path(path))
        result = ProjectImportResult(source_format="COCO Camera Traps", text_key="image_url")
        names = {c.get("id"): str(c.get("name")) for c in data.get("categories") or []
                 if isinstance(c, dict)}
        by_image: Dict[Any, List[dict]] = {}
        for ann in data.get("annotations") or []:
            if isinstance(ann, dict):
                by_image.setdefault(ann.get("image_id"), []).append(ann)

        frames: List[_Frame] = []
        unsized = 0
        for image in data["images"]:
            if not isinstance(image, dict) or not image.get("file_name"):
                continue
            frame = _Frame(str(image["file_name"]).replace("\\", "/"))
            frame.video = _is_video(image)
            for name in ("datetime", "location", "seq_id", "seq_num_frames", "frame_num",
                         "latitude", "longitude"):
                if image.get(name) not in (None, ""):
                    frame.fields[name] = image[name]
            if image.get("width") and image.get("height"):
                frame.fields["image_width"] = int(image["width"])
                frame.fields["image_height"] = int(image["height"])
            frames.append(frame)
            frame._anns = by_image.get(image.get("id"), [])  # type: ignore[attr-defined]
        self._probe(frames, options, result)   # sizes for pixel boxes
        for frame in frames:
            w, h = frame.fields.get("image_width"), frame.fields.get("image_height")
            for ann in frame._anns:  # type: ignore[attr-defined]
                name = names.get(ann.get("category_id"), str(ann.get("category_id")))
                kind = triage_of(name)
                frame.vote(kind, 1.0 if kind != "empty" else 0.0)
                if kind == "empty":
                    continue
                if not is_generic(name):
                    frame.species.setdefault(name, None)
                bbox = ann.get("bbox")
                if not isinstance(bbox, list) or len(bbox) < 4 or frame.video:
                    continue
                if not (w and h):
                    unsized += 1
                    continue
                box = to_client_object("bbox", name, "", img_w=float(w), img_h=float(h),
                                       bbox=[float(v) for v in bbox[:4]],
                                       provenance={"source": "import",
                                                   "import_format": "coco_camera_traps"})
                if box:
                    frame.boxes.append(box)
            if options.get("sequences"):
                frame.raw_detections = None
        if unsized:
            result.warn(f"{unsized} box(es) left out: their images have no width/height "
                        "(add them, or pass --image-dir so they can be read)")
            result.skipped["boxes on images of unknown size"] = unsized
        _fill_colors(frames)
        species = [n for n in names.values() if not is_generic(n)]
        return self._assemble(frames, options, species, result, self.import_label)

"""
MOTChallenge exporter — the other half of the MOT round trip.

Writes one directory per sequence::

    <sequence>/seqinfo.ini
    <sequence>/gt/gt.txt

with rows ``frame, id, bb_left, bb_top, bb_width, bb_height, conf, class, visibility``.

Points where this differs from its neighbours, and would be wrong if assumed:

* **Boxes are origin + size here**, unlike the KITTI exporter beside it, which
  writes corners. Both formats come out of the same driving pipelines, so the
  convention is asserted by test in each direction rather than left to memory.
* **Frames are 1-indexed.** Items carry the frame number they were imported
  with; an item that has none is numbered from 1 in item order, never from 0.
* **``conf`` = 0 means "exclude from evaluation"**, not "unconfident". An object
  flagged ``attributes.ignore`` is written with conf 0, and everything else
  with conf 1 — writing a real confidence into that column would silently
  convert uncertain annotations into ignore regions.
* **The track id is the identity**, taken from ``instance``/``track_id``. An
  object with neither gets a fresh id rather than ``-1``: a gt.txt with -1 ids
  is a detection file, not ground truth, and evaluators treat it very
  differently.

Video tracks (a ``video_annotation`` scheme in tracking or combined mode) are
written too: each video is a sequence named after its item, with a row on
every frame from a track's first keyframe to its last. Boxes between
keyframes are interpolated from the normalized boxes (``bboxNorm``) and
scaled to the video's pixel size, which comes from ``--option width=...
height=...``, the item's ``width``/``height``, or ffprobe, in that order.

Rows are numbered in the video's real frames. The annotation page numbers
frames at the scheme's ``video_fps`` (30 when unset), which need not be the
file's rate; each keyframe also stores its ``time``, so a row goes at
``round(time x fps) + 1`` with the fps ffprobe reports, and that fps is the
``frameRate`` in seqinfo.ini.
"""

import configparser
import logging
import os
from typing import Dict, List, Optional, Tuple

from potato.server_utils.track_attributes import attributes_at

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import (
    extract_image_annotations,
    blank_item_warning,
    get_image_dimensions,
    normalize_annotation_object,
)

logger = logging.getLogger(__name__)

#: Written when an item carries no sequence name.
DEFAULT_SEQUENCE = "sequence"

#: MOT ground-truth class id for a tracked pedestrian.
DEFAULT_CLASS = 1

#: Reverse of the importer's map, so a round trip keeps the class id.
CLASS_IDS = {
    "pedestrian": 1, "person_on_vehicle": 2, "car": 3, "bicycle": 4,
    "motorbike": 5, "non_motorized_vehicle": 6, "static_person": 7,
    "distractor": 8, "occluder": 9, "occluder_on_ground": 10,
    "occluder_full": 11, "reflection": 12,
}


class MOTExporter(BaseExporter):
    format_name = "mot"
    description = "MOTChallenge tracking ground truth (seqinfo.ini + gt/gt.txt)"
    file_extensions = [".txt", ".ini"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not any(s.get("annotation_type") == "image_annotation" or _is_tracking_video(s)
                   for s in context.schemas):
            return False, ("No image_annotation schema, and no video_annotation scheme "
                           "in tracking or combined mode, found in config")
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        warnings: List[str] = []
        files_written: List[str] = []
        os.makedirs(output_path, exist_ok=True)

        by_image: Dict[str, list] = {}
        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            for _schema, objects in extract_image_annotations(ann):
                by_image.setdefault(instance_id, []).extend(objects)

        sequences: Dict[str, list] = {}
        for order, (instance_id, objects) in enumerate(sorted(by_image.items())):
            item = context.items.get(instance_id, {})
            sequence = str(item.get("sequence") or DEFAULT_SEQUENCE)
            # 1-indexed. An item with no recorded frame is numbered in order,
            # starting at 1 -- never 0, which every MOT evaluator drops.
            frame = item.get("frame")
            try:
                frame = int(frame)
            except (TypeError, ValueError):
                frame = order + 1
            sequences.setdefault(sequence, []).append(
                (frame, instance_id, objects, item))

        unsupported: Dict[str, int] = {}
        num_rows = 0
        synthetic_ids = 0

        for sequence, frames in sorted(sequences.items()):
            seq_dir = os.path.join(output_path, sequence)
            gt_dir = os.path.join(seq_dir, "gt")
            os.makedirs(gt_dir, exist_ok=True)

            rows: List[str] = []
            next_id = 10_000  # well clear of real track ids
            width = height = 0
            for frame, _instance_id, objects, item in sorted(frames):
                w, h = get_image_dimensions(
                    item, config=context.config, annotation=ann)
                width, height = width or w, height or h
                for obj in objects:
                    obj_type = obj.get("type", "")
                    if obj_type != "bbox":
                        unsupported[obj_type] = unsupported.get(obj_type, 0) + 1
                        continue
                    canon = normalize_annotation_object(obj, w, h)
                    if canon is None:
                        continue
                    x, y, bw, bh = canon["bbox"]

                    attrs = obj.get("attributes") or {}
                    track_id = attrs.get("track_id", obj.get("instance"))
                    try:
                        track_id = int(track_id)
                    except (TypeError, ValueError):
                        track_id = next_id
                        next_id += 1
                        synthetic_ids += 1

                    label = str(obj.get("label") or "").lower()
                    class_id = CLASS_IDS.get(label, DEFAULT_CLASS)
                    # 0 means "ignore region" in gt, so it is set ONLY from the
                    # ignore flag, never from a confidence score.
                    conf = 0 if attrs.get("ignore") else 1
                    visibility = attrs.get("visibility", 1)

                    rows.append(
                        f"{frame},{track_id},{x:.2f},{y:.2f},{bw:.2f},{bh:.2f},"
                        f"{conf},{class_id},{visibility}")
                    num_rows += 1

            gt_path = os.path.join(gt_dir, "gt.txt")
            with open(gt_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(rows))
                if rows:
                    fh.write("\n")
            files_written.append(gt_path)

            seq_path = self._write_seqinfo(
                seq_dir, sequence, frames, width, height)
            files_written.append(seq_path)

        for obj_type, count in sorted(unsupported.items()):
            warnings.append(
                f"{count} {obj_type} annotation(s) were not written: MOT ground "
                f"truth holds boxes only. Export to DAVIS or COCO to keep "
                f"{obj_type} geometry.")
        if synthetic_ids:
            warnings.append(
                f"{synthetic_ids} object(s) had no track id and were given "
                f"fresh ones starting at 10000. A gt.txt with id -1 is a "
                f"detection file rather than ground truth, so ids are never "
                f"left unset.")

        video_rows, video_sequences = self._export_video_tracks(
            context, output_path, options, warnings, files_written)
        num_rows += video_rows

        # Items nobody marked produce no record at all, so they are
        # absent from the output rather than present and empty. Only for
        # image schemes: a video item is written from its tracks.
        if any(s.get("annotation_type") == "image_annotation" for s in context.schemas):
            _blank = blank_item_warning(context, 'the MOT export')
            if _blank:
                warnings.append(_blank)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={"num_images": len(by_image), "num_annotations": num_rows,
                   "num_sequences": len(sequences) + video_sequences},
        )

    def _export_video_tracks(self, context, output_path, options, warnings,
                             files_written) -> Tuple[int, int]:
        """MOT sequences from video tracks; returns (rows, sequences)."""
        from potato.server_utils.iaa.attribute_agreement import track_objects

        schemes = [s for s in context.schemas if _is_tracking_video(s)]
        if not schemes:
            return 0, 0
        users = {a.get("user_id") for a in context.annotations}
        num_rows = num_sequences = 0
        no_size: List[str] = []
        no_boxes = cubic = 0
        assumed_rate: List[str] = []
        for record in context.annotations:
            instance_id = str(record.get("instance_id", ""))
            item = context.items.get(instance_id, {})
            for scheme in schemes:
                tracks = track_objects((record.get("labels") or {}).get(scheme.get("name")))
                if not tracks:
                    continue
                width, height, probed_fps = _video_size(context, item, scheme, options)
                if not width or not height:
                    no_size.append(instance_id)
                    continue
                # The rate the page numbered frames at, and the file's own.
                page_fps = _number(scheme.get("video_fps")) or 30.0
                fps = probed_fps or page_fps
                if not probed_fps and not scheme.get("video_fps"):
                    assumed_rate.append(instance_id)
                sequence = instance_id if len(users) <= 1 else f"{instance_id}__{record.get('user_id')}"
                if len(schemes) > 1:
                    sequence += f"__{scheme.get('name')}"
                seq_dir = os.path.join(output_path, sequence)
                os.makedirs(os.path.join(seq_dir, "gt"), exist_ok=True)
                rows: List[str] = []
                last_frame = 0
                for number, track in enumerate(tracks, start=1):
                    keyframes = _normalized_keyframes(track, page_fps, fps)
                    if not keyframes:
                        no_boxes += 1
                        continue
                    mode = track.get("interpolation") or "linear"
                    cubic += mode == "cubic"
                    label = str(track.get("label") or "").lower()
                    # Attributes can change along the track (per_keyframe);
                    # each row takes the value at its frame.
                    frame_of = (lambda key, kf, _p=page_fps, _f=fps: _real_frame(key, kf, _p, _f))
                    for frame in range(keyframes[0][0], keyframes[-1][0] + 1):
                        attrs = attributes_at(track, frame, frame_of)
                        conf = 0 if attrs.get("ignore") else 1
                        box = _box_between(keyframes, frame, hold=(mode == "constant"))
                        x, y = box["x"] * width, box["y"] * height
                        bw, bh = box["width"] * width, box["height"] * height
                        rows.append(f"{frame + 1},{number},{x:.2f},{y:.2f},{bw:.2f},{bh:.2f},"
                                    f"{conf},{CLASS_IDS.get(label, DEFAULT_CLASS)},"
                                    f"{attrs.get('visibility', 1)}")
                        last_frame = max(last_frame, frame + 1)
                gt_path = os.path.join(seq_dir, "gt", "gt.txt")
                with open(gt_path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(rows) + ("\n" if rows else ""))
                files_written.append(gt_path)
                files_written.append(self._write_seqinfo(
                    seq_dir, sequence, [(last_frame,)], width, height, fps=fps))
                num_rows += len(rows)
                num_sequences += 1
        if no_size:
            warnings.append(
                f"{len(no_size)} video(s) were not written because their pixel size is "
                f"unknown: pass --option width=... --option height=..., add width and "
                f"height to the items, or install ffprobe. "
                f"{', '.join(sorted(set(no_size))[:10])}")
        if no_boxes:
            warnings.append(f"{no_boxes} track(s) were not written: their keyframes have no "
                            f"normalized box (bboxNorm), so their pixel position is unknown.")
        if cubic:
            warnings.append(f"{cubic} track(s) use cubic interpolation; MOT rows between "
                            f"their keyframes were interpolated linearly.")
        if assumed_rate:
            warnings.append(
                f"{len(assumed_rate)} video(s) have no video_fps in the scheme and no frame "
                f"rate from ffprobe, so rows assume 30 fps; if the file's rate differs, "
                f"frame numbers are off. {', '.join(sorted(set(assumed_rate))[:10])}")
        return num_rows, num_sequences

    @staticmethod
    def _write_seqinfo(seq_dir, sequence, frames, width, height, fps=30) -> str:
        """
        seqinfo.ini carries the image size, which is what lets the importer
        read the file back without needing the frames themselves.
        """
        parser = configparser.ConfigParser()
        parser.optionxform = str  # MOT's keys are camelCase; do not lowercase.
        parser["Sequence"] = {
            "name": sequence,
            "imDir": "img1",
            "frameRate": str(int(round(fps or 30))),
            "seqLength": str(max((f for f, *_ in frames), default=0)),
            "imWidth": str(int(width or 0)),
            "imHeight": str(int(height or 0)),
            "imExt": ".jpg",
        }
        path = os.path.join(seq_dir, "seqinfo.ini")
        with open(path, "w", encoding="utf-8") as fh:
            parser.write(fh, space_around_delimiters=False)
        return path


def _is_tracking_video(scheme: dict) -> bool:
    return (scheme.get("annotation_type") == "video_annotation"
            and scheme.get("mode") in ("tracking", "combined"))


def _number(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _normalized_keyframes(track: dict, page_fps: float = 30.0,
                          fps: float = 30.0) -> List[Tuple[int, dict]]:
    """``[(frame, bboxNorm)]`` in the video's real frames, sorted.

    The real frame comes from the keyframe's ``time`` when it has one, else
    from its page frame rescaled from the page's rate. Two keyframes landing
    on one real frame keep the later.
    """
    out: Dict[int, dict] = {}
    for key, kf in (track.get("keyframes") or {}).items():
        if not isinstance(kf, dict) or not isinstance(kf.get("bboxNorm"), dict):
            continue
        frame = _real_frame(key, kf, page_fps, fps)
        if frame is None:
            continue
        out[frame] = kf["bboxNorm"]
    return sorted(out.items(), key=lambda pair: pair[0])


def _real_frame(key, kf: dict, page_fps: float = 30.0, fps: float = 30.0):
    """A keyframe's frame in the video's real frames: from its ``time`` when
    it has one, else its page frame rescaled from the page's rate."""
    time = _number(kf.get("time"))
    try:
        return int(round(time * fps) if time is not None
                   else round(int(kf.get("frame", key)) * fps / page_fps))
    except (TypeError, ValueError):
        return None


def _box_between(keyframes: List[Tuple[int, dict]], frame: int, hold: bool = False) -> dict:
    before = max((pair for pair in keyframes if pair[0] <= frame), key=lambda p: p[0])
    after = min((pair for pair in keyframes if pair[0] >= frame), key=lambda p: p[0])
    if hold or after[0] == before[0]:
        return before[1]
    t = (frame - before[0]) / (after[0] - before[0])
    return {k: before[1][k] + (after[1][k] - before[1][k]) * t
            for k in ("x", "y", "width", "height")}


def _video_size(context, item: dict, scheme: dict, options: dict):
    """(width, height, fps) of an item's video; each None when unknown.

    The fps is the file's (``--option fps=...``, the item's ``fps``, or
    ffprobe), never the scheme's `video_fps`, which is the rate the page
    numbered frames at.
    """
    number = _number
    width, height = number(options.get("width")), number(options.get("height"))
    fps = number(options.get("fps")) or number(item.get("fps"))
    if not (width and height):
        width, height = number(item.get("width")), number(item.get("height"))
    if not (width and height) or not fps:
        source = item.get(scheme.get("source_field") or "video_url") or item.get("video")
        info = {}
        if isinstance(source, str) and not source.startswith(("http://", "https://")):
            from potato.media.paths import resolve_media_path
            from potato.media.video import probe_video
            path = source.split("/media/", 1)[-1].lstrip("/")
            _root, target = resolve_media_path(context.config, path, context="Video")
            if target and os.path.isfile(target):
                info = probe_video(target)
        if not (width and height):
            width, height = number(info.get("width")), number(info.get("height"))
        fps = fps or number(info.get("fps"))
    return width, height, fps

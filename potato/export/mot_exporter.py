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
"""

import configparser
import logging
import os
from typing import Dict, List, Optional, Tuple

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
        if not any(s.get("annotation_type") == "image_annotation"
                   for s in context.schemas):
            return False, "No image_annotation schema found in config"
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

        # Items nobody marked produce no record at all, so they are
        # absent from the output rather than present and empty.
        _blank = blank_item_warning(context, 'the MOT export')
        if _blank:
            warnings.append(_blank)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={"num_images": len(by_image), "num_annotations": num_rows,
                   "num_sequences": len(sequences)},
        )

    @staticmethod
    def _write_seqinfo(seq_dir, sequence, frames, width, height) -> str:
        """
        seqinfo.ini carries the image size, which is what lets the importer
        read the file back without needing the frames themselves.
        """
        parser = configparser.ConfigParser()
        parser.optionxform = str  # MOT's keys are camelCase; do not lowercase.
        parser["Sequence"] = {
            "name": sequence,
            "imDir": "img1",
            "frameRate": "30",
            "seqLength": str(max((f for f, *_ in frames), default=0)),
            "imWidth": str(int(width or 0)),
            "imHeight": str(int(height or 0)),
            "imExt": ".jpg",
        }
        path = os.path.join(seq_dir, "seqinfo.ini")
        with open(path, "w", encoding="utf-8") as fh:
            parser.write(fh, space_around_delimiters=False)
        return path

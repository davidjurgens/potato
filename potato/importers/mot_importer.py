"""
MOTChallenge tracking importer (``gt/gt.txt`` and ``det/det.txt``).

A MOT sequence is a directory::

    MOT17-02/
      seqinfo.ini          name, imDir, imExt, seqLength, imWidth, imHeight
      img1/000001.jpg ...
      gt/gt.txt            ground truth
      det/det.txt          public detections

Each CSV line is::

    frame, id, bb_left, bb_top, bb_width, bb_height, conf, class, visibility

Details that matter:

* **Frames are 1-indexed.** Frame 1 is ``img1/000001.jpg``. Treating the column
  as 0-indexed shifts every annotation one frame earlier, which is invisible on
  a static image and wrong for every temporal use.
* **The box IS origin+size here** — unlike KITTI, which is corners. The two
  formats sit next to each other in most driving pipelines, which is exactly
  why each importer states its own convention.
* **``seqinfo.ini`` carries the real image dimensions**, so a MOT import needs
  neither Pillow nor the images themselves to normalize correctly.
* **``conf`` = 0 in ground truth means "ignore"**, not "low confidence". Those
  boxes mark regions excluded from evaluation and are preserved with an
  ``ignore`` attribute rather than dropped or silently mixed in.

Potato's image schema has no spatio-temporal object yet, so a track is imported
as one annotation per frame carrying its track id in ``instance``. That is the
honest mapping: every box is editable, and the identity that links them across
frames survives. Linking them into a single scrubable object is Wave 4's video
work, and the import says so rather than implying it already happened.
"""

from __future__ import annotations

import configparser
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import FALLBACK_SIZE, apply_url_prefix, safe_instance_id
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: MOT16/17/20 ground-truth class ids. Only class 1 is a tracking target; the
#: rest exist so that evaluation can exclude the right regions.
MOT_CLASSES = {
    1: "pedestrian",
    2: "person_on_vehicle",
    3: "car",
    4: "bicycle",
    5: "motorbike",
    6: "non_motorized_vehicle",
    7: "static_person",
    8: "distractor",
    9: "occluder",
    10: "occluder_on_ground",
    11: "occluder_full",
    12: "reflection",
}

#: MOT ships one CSV row per box; anything shorter is not a MOT line.
MIN_FIELDS = 6


class MOTImporter(BaseAnnotationImporter):
    format_name = "mot"
    description = "MOTChallenge tracking (seqinfo.ini + gt/gt.txt)"
    file_extensions = [".txt", ".ini"]

    def detect(self, data: Any) -> bool:
        return isinstance(data, dict) and "mot_sequences" in data

    # ------------------------------------------------------------------

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        base = Path(root)
        sequences = self._find_sequences(base)
        if not sequences:
            raise ValueError(
                f"No MOT sequence found under {base}. Expected a directory "
                f"with gt/gt.txt (or det/det.txt), optionally alongside "
                f"seqinfo.ini — either one sequence or a folder of them.")
        return self.parse({"mot_sequences": sequences, "root": base}, options)

    @staticmethod
    def _find_sequences(base: Path) -> List[Path]:
        def is_sequence(path: Path) -> bool:
            return ((path / "gt" / "gt.txt").exists()
                    or (path / "det" / "det.txt").exists()
                    or (path / "seqinfo.ini").exists())

        if is_sequence(base):
            return [base]
        return sorted(d for d in base.iterdir() if d.is_dir() and is_sequence(d))

    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not self.detect(data):
            raise ValueError(
                "Not a MOT dataset. Point --input at a sequence directory "
                "containing gt/gt.txt, not at the CSV itself.")

        result = ImportResult()
        labels: Dict[str, dict] = {}
        multi = len(data["mot_sequences"]) > 1
        num_tracks = 0
        ignored = 0

        for seq_dir in data["mot_sequences"]:
            info = self._seqinfo(seq_dir, result.warnings)
            csv_path, source = self._annotation_file(seq_dir)
            if csv_path is None:
                result.warnings.append(
                    f"{seq_dir.name} has neither gt/gt.txt nor det/det.txt; "
                    f"its frames were skipped.")
                continue

            by_frame: Dict[int, List[dict]] = {}
            tracks = set()
            for lineno, raw in enumerate(
                    csv_path.read_text(encoding="utf-8").splitlines(), start=1):
                row = [p.strip() for p in raw.split(",")]
                if len(row) < MIN_FIELDS or not row[0]:
                    continue
                parsed = self._row(row, info, csv_path.name, lineno,
                                   result.warnings)
                if parsed is None:
                    continue
                frame, obj, track_id, is_ignore = parsed
                ignored += int(is_ignore)
                if track_id >= 0:
                    tracks.add(track_id)
                by_frame.setdefault(frame, []).append(obj)
                labels.setdefault(obj["label"], {"name": obj["label"]})

            num_tracks += len(tracks)
            self._emit_frames(seq_dir, info, by_frame, multi, options, result)
            result.warnings.append(
                f"{seq_dir.name}: read {source} "
                f"({len(tracks)} track(s) across {len(by_frame)} frame(s)).")

        if num_tracks:
            result.warnings.append(
                f"{num_tracks} track(s) were imported as one box per frame, "
                f"with the track id kept in each object's `instance` field. "
                f"Potato's image schema has no single scrubable track object "
                f"yet, so the boxes are editable per frame and their identity "
                f"survives, but they do not move together.")
        if ignored:
            result.warnings.append(
                f"{ignored} box(es) are marked conf=0, which MOT ground truth "
                f"uses to mean 'exclude from evaluation' rather than 'low "
                f"confidence'. They carry attributes.ignore = true.")

        result.labels = [labels[n] for n in sorted(labels)]
        result.tools = ["bbox"]
        result.summarize(num_tracks=num_tracks)
        return result

    # ------------------------------------------------------------------

    @staticmethod
    def _annotation_file(seq_dir: Path):
        gt = seq_dir / "gt" / "gt.txt"
        if gt.exists():
            return gt, "gt/gt.txt"
        det = seq_dir / "det" / "det.txt"
        if det.exists():
            return det, "det/det.txt (public detections, not ground truth)"
        return None, ""

    def _seqinfo(self, seq_dir: Path, warnings: List[str]) -> dict:
        """
        Read seqinfo.ini. It carries the true image size, so a correct import
        needs neither Pillow nor the frames on disk.
        """
        info = {"imDir": "img1", "imExt": ".jpg",
                "imWidth": FALLBACK_SIZE[0], "imHeight": FALLBACK_SIZE[1],
                "seqLength": 0, "measured": False}
        path = seq_dir / "seqinfo.ini"
        if not path.exists():
            warnings.append(
                f"{seq_dir.name} has no seqinfo.ini, so image dimensions are "
                f"unknown. Boxes were normalized against an assumed "
                f"{FALLBACK_SIZE[0]}x{FALLBACK_SIZE[1]} and will be in the "
                f"wrong place unless that happens to be correct.")
            return info

        parser = configparser.ConfigParser()
        try:
            parser.read(path, encoding="utf-8")
            section = parser["Sequence"]
        except Exception as exc:
            warnings.append(f"Could not read {path.name}: {exc}")
            return info

        for key, cast in (("imDir", str), ("imExt", str), ("imWidth", int),
                          ("imHeight", int), ("seqLength", int)):
            if key in section:
                try:
                    info[key] = cast(section[key])
                except ValueError:
                    pass
        info["measured"] = info["imWidth"] > 0 and info["imHeight"] > 0
        return info

    def _row(self, row, info, file_name, lineno, warnings):
        try:
            frame = int(float(row[0]))
            track_id = int(float(row[1]))
            x, y = float(row[2]), float(row[3])
            # Origin+size here, unlike KITTI's corners.
            w, h = float(row[4]), float(row[5])
        except ValueError:
            warnings.append(f"{file_name}:{lineno} is not a MOT row. Skipped.")
            return None

        if w <= 0 or h <= 0:
            return None

        class_id = 1
        conf = 1.0
        visibility = None
        if len(row) > 6 and row[6]:
            try:
                conf = float(row[6])
            except ValueError:
                pass
        if len(row) > 7 and row[7]:
            try:
                class_id = int(float(row[7]))
            except ValueError:
                pass
        if len(row) > 8 and row[8]:
            try:
                visibility = float(row[8])
            except ValueError:
                pass

        label = MOT_CLASSES.get(class_id, f"class_{class_id}")
        obj = to_client_object(
            "bbox", label,
            img_w=info["imWidth"], img_h=info["imHeight"],
            bbox=[x, y, w, h],
            instance=track_id if track_id >= 0 else None,
        )
        if obj is None:
            return None

        attributes: Dict[str, Any] = {}
        if track_id >= 0:
            attributes["track_id"] = track_id
        # conf == 0 in ground truth means "ignore region", not "unconfident".
        is_ignore = conf == 0
        if is_ignore:
            attributes["ignore"] = True
        elif conf != 1.0:
            attributes["confidence"] = conf
        if visibility is not None:
            attributes["visibility"] = visibility
        if attributes:
            obj["attributes"] = attributes
        return frame, obj, track_id, is_ignore

    def _emit_frames(self, seq_dir, info, by_frame, multi, options, result):
        """
        One item per frame. Frames are 1-indexed and zero-padded to six digits,
        which is what MOT's img1/ directories use.
        """
        frames = sorted(by_frame) or []
        seq_length = info.get("seqLength") or 0
        if seq_length and frames:
            # Include annotated frames only: importing 600 empty frames makes a
            # 60-item project unusable and every empty item exports as agreement
            # on "nothing here".
            frames = [f for f in frames if 1 <= f <= seq_length] or frames

        for frame in frames:
            name = f"{frame:06d}{info['imExt']}"
            rel = f"{info['imDir']}/{name}"
            file_name = f"{seq_dir.name}/{rel}" if multi else rel
            instance_id = safe_instance_id(f"{seq_dir.name}_{frame:06d}")
            result.images.append(ImportedImage(
                instance_id=instance_id,
                file_name=file_name,
                width=info["imWidth"],
                height=info["imHeight"],
                objects=by_frame[frame],
                extra={
                    "image_url": apply_url_prefix(file_name, options),
                    "sequence": seq_dir.name,
                    # 1-indexed, as MOT stores it.
                    "frame": frame,
                },
            ))

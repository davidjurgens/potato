"""
KITTI tracking labels on lidar sequences, as point-cloud tracks.

The tracking benchmark's split directory (``training/`` or ``testing/``)
holds one sequence per id::

    label_02/0000.txt          frame track_id type truncated occluded alpha
                               x1 y1 x2 y2  h w l  x y z  ry  [score]
    velodyne/0000/000000.bin   one scan per frame
    calib/0000.txt             P0..P3, R_rect, Tr_velo_cam (no colons on
                               the last two; see calibration.parse_kitti_calib)

Each sequence becomes one item whose ``point_cloud`` lists its scans, and
each labelled object one keyframe of its track. The labels are in the
rectified camera frame, so every box goes through the sequence's calibration
into the lidar frame (``kitti3d.kitti_to_cuboid``, the inverse of what the
``kitti_3d`` export writes). A sequence without a calibration file is skipped
with a warning: a box placed without one would sit in the wrong frame.

* ``DontCare`` rows (track id -1) mark regions excluded from evaluation and
  are not objects; they are counted and left out.
* Truncation (0-2) and occlusion (0-3) become ``truncated`` and ``occluded``
  attributes, in the words the ``kitti_3d`` export reads back.
* A KITTI track can vanish for some frames and come back under the same id.
  Potato interpolates a track between its keyframes, so across such a gap the
  box is interpolated; the import counts the gaps.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._common import apply_url_prefix
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

DONT_CARE = "DontCare"

#: The words the kitti_3d export maps back to these codes
#: (spatial_sequences.OCCLUSION_LEVELS / TRUNCATION_LEVELS).
OCCLUSION_NAMES = {0: "none", 1: "partly", 2: "largely", 3: "unknown"}
TRUNCATION_NAMES = {0: "none", 1: "partly", 2: "fully"}

#: Field positions in a tracking label line.
_FRAME, _TRACK, _TYPE, _TRUNCATED, _OCCLUDED = 0, 1, 2, 3, 4
_DIMS, _LOC, _RY, _SCORE = slice(10, 13), slice(13, 16), 16, 17

#: Per keyframe: KITTI labels occlusion and truncation frame by frame, and
#: without the flag an edit on one frame changed the whole track.
ATTRIBUTES = [
    {"name": "occluded", "type": "select", "per_keyframe": True,
     "options": ["none", "partly", "largely", "unknown"], "default": "none"},
    {"name": "truncated", "type": "select", "per_keyframe": True,
     "options": ["none", "partly", "fully"], "default": "none"},
]


def split_dir(base: Path) -> Optional[Path]:
    """The directory holding label_02/, velodyne/ and calib/, or None."""
    for candidate in (base, base / "training", base / "testing"):
        if (candidate / "label_02").is_dir():
            return candidate
    return None


class KITTITrackingImporter(BaseAnnotationImporter):
    format_name = "kitti_tracking"
    description = "KITTI tracking labels on lidar sequences (label_02/, velodyne/, calib/)"
    file_extensions = [".txt"]

    def detect(self, data: Any) -> bool:
        return isinstance(data, dict) and "kitti_tracking_root" in data

    def parse_directory(self, root: str, options: Optional[dict] = None) -> ImportResult:
        base = split_dir(Path(root))
        if base is None:
            raise ValueError(f"No label_02/ under {root} (or its training/ or testing/).")
        if not (base / "velodyne").is_dir():
            raise ValueError(
                f"{base} has label_02/ but no velodyne/. The tracks are drawn on the "
                f"lidar scans, so download the velodyne archive into the same folder.")
        return self.parse({"kitti_tracking_root": base}, options)

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        if not self.detect(data):
            raise ValueError("Not a KITTI tracking dataset. Point --input at the folder "
                             "holding label_02/, velodyne/ and calib/.")
        base: Path = data["kitti_tracking_root"]
        result = ImportResult()
        labels: Dict[str, dict] = {}
        counts = {"dont_care": 0, "unlabelled_frames": 0, "gaps": 0, "tracks": 0, "frames": 0}

        for label_file in sorted((base / "label_02").glob("*.txt")):
            seq = label_file.stem
            item = self._sequence(base, seq, label_file, result.warnings, counts, options)
            if item is None:
                continue
            for obj in item.objects:
                labels.setdefault(obj["label"], {"name": obj["label"]})
            result.images.append(item)

        if not result.images:
            raise ValueError(f"No sequence under {base} could be imported: "
                             + "; ".join(result.warnings[:3]))
        if counts["dont_care"]:
            result.warnings.append(
                f"Left out {counts['dont_care']} DontCare row(s): they mark regions "
                f"KITTI excludes from evaluation, not objects.")
        if counts["unlabelled_frames"]:
            result.warnings.append(
                f"{counts['unlabelled_frames']} label row(s) name a frame with no scan in "
                f"velodyne/ and were skipped.")
        if counts["gaps"]:
            result.warnings.append(
                f"{counts['gaps']} gap(s) where a track disappears and comes back under "
                f"the same id. Potato interpolates a track between keyframes, so the box "
                f"is interpolated across each gap; delete it there if the object is "
                f"really gone.")

        result.labels = [labels[name] for name in sorted(labels)]
        result.tools = ["cuboid_3d"]
        result.project = {
            "annotation_type": "spatial_annotation",
            "source_field": "point_cloud",
            "text_key": "notes",
            "media_root": str(base.resolve()),
            "noun": "sequence",
            "scheme": {"calibration_field": "calibration",
                       "attributes": [dict(a) for a in ATTRIBUTES]},
        }
        result.summarize(num_tracks=counts["tracks"], num_frames=counts["frames"])
        return result

    def _sequence(self, base: Path, seq: str, label_file: Path, warnings: List[str],
                  counts: Dict[str, int], options: Optional[dict] = None) -> Optional[ImportedImage]:
        from potato.export.kitti3d import kitti_to_cuboid
        from potato.media.calibration import CalibrationError, parse_kitti_calib

        scans = sorted((base / "velodyne" / seq).glob("*.bin"))
        if not scans:
            warnings.append(f"Sequence {seq}: no scans in velodyne/{seq}/; skipped.")
            return None
        calib_path = base / "calib" / f"{seq}.txt"
        try:
            calibration = parse_kitti_calib(calib_path.read_text(encoding="utf-8"))
        except (OSError, CalibrationError) as exc:
            warnings.append(f"Sequence {seq}: no usable calib/{seq}.txt ({exc}); skipped, "
                            f"since its boxes cannot be placed in the lidar frame without it.")
            return None
        warnings.extend(f"Sequence {seq}: {w}" for w in calibration.warnings)
        reference_rt = calibration.reference_rt

        # Potato's frame k is the k-th scan, and KITTI's frame number is the
        # scan's file name, so the two agree only when the scans run 000000,
        # 000001, ... with none missing. With 000004 missing, scan 000005
        # would become frame 4: the export would write the wrong frame number
        # and interpolation would treat frames 3 and 5 as neighbours.
        try:
            numbers = [int(scan.stem) for scan in scans]
        except ValueError:
            warnings.append(f"Sequence {seq}: velodyne/{seq}/ holds scans whose names are "
                            f"not frame numbers; skipped.")
            return None
        if numbers != list(range(len(numbers))):
            missing = sorted(set(range(max(numbers) + 1)) - set(numbers))
            shown = ", ".join(f"{n:06d}" for n in missing[:5]) + (" ..." if len(missing) > 5 else "")
            warnings.append(f"Sequence {seq}: scans {shown} are missing from velodyne/{seq}/, "
                            f"so its frames cannot be numbered as KITTI numbers them; "
                            f"skipped. Restore the scans and import again.")
            return None
        index_of = {number: number for number in numbers}

        objects: List[dict] = []
        frames_by_track: Dict[str, List[int]] = {}
        for lineno, raw in enumerate(label_file.read_text(encoding="utf-8").splitlines(), 1):
            fields = raw.split()
            if not fields:
                continue
            if len(fields) < 17:
                warnings.append(f"label_02/{seq}.txt:{lineno} has {len(fields)} fields; a "
                                f"tracking label needs 17. Skipped.")
                continue
            try:
                frame, track = int(fields[_FRAME]), int(fields[_TRACK])
                truncated = int(float(fields[_TRUNCATED]))
                occluded = int(float(fields[_OCCLUDED]))
            except ValueError:
                warnings.append(f"label_02/{seq}.txt:{lineno} is not numeric where it "
                                f"should be. Skipped.")
                continue
            label = fields[_TYPE]
            if label == DONT_CARE or track < 0:
                counts["dont_care"] += 1
                continue
            if frame not in index_of:
                counts["unlabelled_frames"] += 1
                continue
            obj = kitti_to_cuboid(label, fields[_DIMS], fields[_LOC], fields[_RY],
                                  reference_rt, track_id=str(track))
            if obj is None:
                warnings.append(f"label_02/{seq}.txt:{lineno} has an unusable box "
                                f"(size must be positive). Skipped.")
                continue
            obj["frame"] = index_of[frame]
            obj["attributes"] = {"occluded": OCCLUSION_NAMES.get(occluded, "unknown"),
                                 "truncated": TRUNCATION_NAMES.get(truncated, "none")}
            if len(fields) > _SCORE:
                try:
                    obj["confidence"] = float(fields[_SCORE])
                except ValueError:
                    pass
            objects.append(obj)
            frames_by_track.setdefault(str(track), []).append(obj["frame"])

        for frames in frames_by_track.values():
            frames.sort()
            counts["gaps"] += sum(1 for a, b in zip(frames, frames[1:]) if b - a > 1)
        counts["tracks"] += len(frames_by_track)
        counts["frames"] += len(scans)
        objects.sort(key=lambda o: (o["frame"], o["track_id"]))
        return ImportedImage(
            instance_id=seq,
            file_name=f"label_02/{seq}.txt",
            width=0,
            height=0,
            objects=objects,
            # --image-url-prefix can point the scans at a server (the viewer
            # converts a remote cloud); the calibration is read from the
            # media directory either way.
            extra={"point_cloud": [apply_url_prefix(scan.relative_to(base).as_posix(), options)
                                   for scan in scans],
                   "calibration": {"file": f"calib/{seq}.txt"},
                   "notes": (f"KITTI tracking sequence {seq}: {len(scans)} frames, "
                             f"{len(frames_by_track)} tracks")},
        )

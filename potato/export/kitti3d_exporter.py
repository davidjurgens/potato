"""
KITTI 3D labels from point-cloud annotations, for single clouds and sequences.

A single cloud writes ``label_2/<stem>.txt`` in KITTI's fifteen-field object
format. A sequence (an item whose cloud field lists one cloud per frame)
writes ``label_02/<stem>.txt`` in KITTI's tracking format: the same fifteen
fields after ``frame track_id``, one line per object per frame, with boxes
between keyframes interpolated (potato/export/spatial_sequences.py).

KITTI's 3D fields are in the rectified reference camera's frame, so every
item needs its calibration (the scheme's `calibration_field`). The frame
conversion, the bottom-face location and the yaw are kitti3d.py's; this
module only gathers objects and writes files. Truncation and occlusion come
from `truncated`/`occluded` attributes when the scheme declares them.

Only cuboids are written: KITTI has no point or polyline object.

The 2D box columns are the cuboid projected through the calibration's first
camera (KITTI's P2 by default) and clipped to its image. They matter: KITTI
evaluation assigns difficulty from the 2D box height and ignores any object
under 25 px, zero boxes included. The image size comes from the calibration,
``--option image_width=... image_height=...``, or the calibration's image
file; without one the boxes are written unclipped, with a warning.
"""

import logging
import math
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)

#: Rotation the format could not carry beyond this is reported (radians).
TILT_REPORT = math.radians(1.0)


class KITTI3DExporter(BaseExporter):
    format_name = "kitti_3d"
    description = ("KITTI 3D object labels (label_2) and, for point-cloud sequences, "
                   "KITTI tracking labels (label_02)")
    file_extensions = [".txt"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not any(s.get("annotation_type") == "spatial_annotation" for s in context.schemas):
            return False, "No spatial_annotation schema found in config"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.export import spatial_sequences as seq
        from potato.export.kitti3d import cuboid_to_kitti, format_kitti_3d_line, projected_box
        from potato.server_utils.annotation_values import _parse_blob

        schemes = [s for s in context.schemas if s.get("annotation_type") == "spatial_annotation"]
        warnings: List[str] = []
        files: List[str] = []
        users = {a.get("user_id") for a in context.annotations
                 if any((a.get("labels") or {}).get(s.get("name")) for s in schemes)}
        per_user = len(users) > 1
        skipped_types: Dict[str, int] = {}
        no_calibration: List[str] = []
        tilted = 0
        n_objects = n_items = 0
        no_box = 0
        unknown_truncation: Dict[str, int] = {}
        unknown_occlusion: Dict[str, int] = {}
        unclipped: List[str] = []
        options = options or {}

        for record in context.annotations:
            instance_id = str(record.get("instance_id", ""))
            item = context.items.get(instance_id) or {}
            for scheme in schemes:
                stored = (record.get("labels") or {}).get(scheme.get("name"))
                if not stored:
                    continue
                objects = [o for o in _parse_blob(stored) if isinstance(o, dict)]
                for obj in objects:
                    _c, _f, unknown = seq.truncation_attribute(obj.get("attributes") or {})
                    if unknown is not None:
                        unknown_truncation[str(unknown)] = unknown_truncation.get(str(unknown), 0) + 1
                    _c, unknown = seq.occlusion_attribute(obj.get("attributes") or {})
                    if unknown is not None:
                        unknown_occlusion[str(unknown)] = unknown_occlusion.get(str(unknown), 0) + 1
                    if obj.get("type") != "cuboid_3d":
                        kind = str(obj.get("type"))
                        skipped_types[kind] = skipped_types.get(kind, 0) + 1
                reference, camera, size = self._calibration(context, item, scheme, warnings,
                                                            options)
                if reference is None:
                    no_calibration.append(instance_id)
                    continue
                if camera is not None and size is None:
                    unclipped.append(instance_id)
                cloud = item.get(scheme.get("source_field") or "point_cloud")
                frames = seq.sequence_frames(cloud)
                # A sequence is named by its item; a single cloud by its file,
                # as KITTI names label files after the scan.
                stem = instance_id if frames or not isinstance(cloud, str) \
                    else os.path.splitext(os.path.basename(cloud))[0] or instance_id
                base = os.path.join(output_path, str(record.get("user_id"))) if per_user else output_path
                if frames:
                    lines, _ids = seq.kitti_tracking_lines(objects, len(frames), reference,
                                                           camera=camera, image_size=size)
                    no_box += sum(1 for line in lines if line.split()[6:10] == ["0.00"] * 4)
                    folder = os.path.join(base, "label_02")
                else:
                    lines = []
                    for obj in objects:
                        canonical = seq._canonical(obj) or {}
                        fields = cuboid_to_kitti(canonical, reference)
                        if fields is None:
                            continue
                        tilted += fields["tilt"] > TILT_REPORT
                        box, cut = (projected_box(canonical, camera, *(size or (None, None)))
                                    if camera is not None else (None, 0.0))
                        no_box += box is None
                        attributes = obj.get("attributes") or {}
                        lines.append(format_kitti_3d_line(
                            str(obj.get("label") or "DontCare"), fields, bbox=box,
                            truncated=seq._truncation(attributes, cut),
                            occluded=seq._occlusion(attributes)))
                    folder = os.path.join(base, "label_2")
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, f"{stem}.txt")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + ("\n" if lines else ""))
                files.append(path)
                n_objects += len(lines)
                n_items += 1

        for kind, count in sorted(skipped_types.items()):
            warnings.append(f"{count} {kind} annotation(s) were not written: KITTI labels "
                            f"hold 3D boxes only.")
        if no_calibration:
            warnings.append(
                f"{len(no_calibration)} item(s) were not written because they have no "
                f"usable calibration, and KITTI's 3D fields are in the camera frame: "
                f"{', '.join(sorted(set(no_calibration))[:10])}")
        if no_box:
            warnings.append(
                f"{no_box} line(s) have a zero 2D box: the object is behind the camera, "
                f"outside its image, or the calibration has no camera. KITTI evaluation "
                f"ignores objects whose 2D box is under 25 px tall.")
        if unknown_truncation:
            values = ", ".join(f"'{v}'" for v in sorted(unknown_truncation))
            warnings.append(
                f"{sum(unknown_truncation.values())} object(s) have a truncation value that "
                f"is not none/partly/fully, a share from 0 to 1 or true/false ({values}); "
                f"the object's other truncation attribute was written if it has one, and "
                f"otherwise the share of the box outside the image.")
        if unknown_occlusion:
            warnings.append(seq.unknown_occlusion_warning(unknown_occlusion))
        if unclipped:
            warnings.append(
                f"{len(unclipped)} item(s) have 2D boxes that were not clipped to the image, "
                f"because the image size is unknown: pass --option image_width=... "
                f"--option image_height=..., or name the camera image in the calibration. "
                f"{', '.join(sorted(set(unclipped))[:10])}")
        if tilted:
            warnings.append(f"{tilted} box(es) were tilted by more than 1 degree; KITTI "
                            f"stores yaw only, so their pitch and roll were dropped.")
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=warnings,
                            stats={"num_items": n_items, "num_lines": n_objects})

    @staticmethod
    def _calibration(context: ExportContext, item: Dict[str, Any], scheme: Dict[str, Any],
                     warnings: List[str], options: Dict[str, Any]):
        """``(reference_rt, camera, (width, height) | None)``; rt None when unusable.

        The camera is the calibration's first (P2 for a KITTI file), the one
        KITTI's 2D boxes are drawn in.
        """
        from potato.media.calibration import CalibrationError, parse_calibration
        from potato.media.paths import resolve_media_path

        raw = item.get(scheme.get("calibration_field") or "calibration")
        if raw in (None, ""):
            return None, None, None

        def resolve(path):
            _root, target = resolve_media_path(context.config, path, context="Calibration")
            return target
        try:
            calibration = parse_calibration(raw, resolve=resolve)
        except CalibrationError as exc:
            logger.warning("calibration unreadable: %s", exc)
            return None, None, None
        camera = calibration.cameras[0] if calibration.cameras else None
        reference = calibration.reference_rt
        if reference is None and camera is not None:
            message = ("Calibrations without a reference camera use their first "
                       "camera's frame for KITTI's 3D fields.")
            if message not in warnings:
                warnings.append(message)
            reference = camera.rt
        return reference, camera, _image_size(context, camera, options)


def _image_size(context: ExportContext, camera, options: Dict[str, Any]):
    """The camera image's ``(width, height)``, or None when nothing says."""
    if camera is None:
        return None
    if camera.width and camera.height:
        return int(camera.width), int(camera.height)
    try:
        if options.get("image_width") and options.get("image_height"):
            return int(options["image_width"]), int(options["image_height"])
    except (TypeError, ValueError):
        pass
    if camera.image:
        from potato.media.paths import resolve_media_path
        _root, target = resolve_media_path(context.config, camera.image, context="Image")
        if target and os.path.isfile(target):
            try:
                from PIL import Image
                with Image.open(target) as image:
                    return image.size
            except Exception:  # noqa: BLE001 - an unreadable image only loses clipping
                logger.warning("could not read %s for its size", target)
    return None

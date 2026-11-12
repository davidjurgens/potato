"""
Exports for volume_annotation: a NIfTI label volume, and a DICOM SEG.

``volume_nifti`` writes, per annotator and item,
``<user>/<item>__<schema>.nii.gz``: one uint8 label volume in the source
file's own voxel order and affine (label n is the scheme's n-th label, 0 is
background) and ``<item>__<schema>__shapes.json`` with the boxes and polygons
in voxel coordinates, plus one ``labels__<schema>.json`` per scheme, at the top
of the export, mapping values to names. Works for NIfTI and DICOM sources.

``dicom_seg`` writes ``<user>/<item>__<schema>.dcm``: a binary DICOM
Segmentation (one segment per label with voxels) referencing the source
series, for PACS and clinical viewers. DICOM sources only. Each segment
carries the label's coded concepts (the label's ``dicom:`` codes, or SNOMED
CT "Tissue" by default). By DICOM's rules a SEG copies the patient and study
modules from the images it segments, so it carries the same identifying data
as the series.

``dicom_sr`` writes the same SEG and, beside it, ``<item>__<schema>__sr.dcm``:
a Comprehensive 3D SR whose content is a TID 1500 Measurement Report, one
TID 1411 volumetric group per segment with its volume in mm3, the annotator
as the person observer.

All three need the `volumes` extra (pydicom, nibabel, highdicom).
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


def _volume_schemes(context):
    return [s for s in context.schemas if s.get("annotation_type") == "volume_annotation"]


def _label_names(scheme) -> List[str]:
    out = []
    for item in scheme.get("labels") or []:
        name = item if isinstance(item, str) else (item or {}).get("name")
        if name:
            out.append(str(name))
    return out


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._") or "item"


def _records(context, scheme):
    """(record, item, annotation dict) for every stored answer on ``scheme``."""
    for record in context.annotations:
        value = (record.get("labels") or {}).get(scheme.get("name"))
        if isinstance(value, dict) and "_data" in value:
            value = value["_data"]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                continue
        if not isinstance(value, dict) or "masks" not in value:
            continue
        yield record, context.items.get(str(record.get("instance_id"))) or {}, value


def _open(context, scheme, item, annotation):
    from potato.media.paths import resolve_media_path
    from potato.media.volumes import load_volume
    path = item.get(scheme.get("source_field") or "volume") or annotation.get("volume")
    if not isinstance(path, str) or not path:
        raise ValueError("the item names no volume")
    _root, resolved = resolve_media_path(context.config, path, context="Volume export")
    if resolved is None or not os.path.exists(resolved):
        raise ValueError(f"volume {path} not found in the media directory")
    return load_volume(resolved)


class _VolumeExporter(BaseExporter):
    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not _volume_schemes(context):
            return False, "No volume_annotation schema found in config"
        try:
            import nibabel  # noqa: F401
            import pydicom  # noqa: F401
        except ImportError:
            return False, "needs pip install 'potato-annotation[volumes]'"
        return True, ""

    def _base(self, output_path, record):
        folder = os.path.join(output_path, _safe(record.get("user_id")))
        os.makedirs(folder, exist_ok=True)
        return folder


class VolumeNiftiExporter(_VolumeExporter):
    format_name = "volume_nifti"
    description = "Volume masks as NIfTI label volumes (source geometry), with label table and shapes"
    file_extensions = [".nii.gz", ".json"]

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.media.volume_masks import labelmap, to_nifti_bytes
        files, warnings = [], []
        n_items = 0
        for scheme in _volume_schemes(context):
            names = _label_names(scheme)
            table = os.path.join(output_path, f"labels__{_safe(scheme['name'])}.json")
            os.makedirs(output_path, exist_ok=True)
            with open(table, "w", encoding="utf-8") as fh:
                json.dump({"0": "background", **{str(n): name for n, name in
                                                  enumerate(names, start=1)}}, fh, indent=2)
            files.append(table)
            for record, item, annotation in _records(context, scheme):
                instance = str(record.get("instance_id"))
                try:
                    volume = _open(context, scheme, item, annotation)
                except Exception as exc:
                    warnings.append(f"{instance}: {exc}")
                    continue
                stored_shape = annotation.get("shape")
                if stored_shape and list(stored_shape) != list(volume.shape):
                    warnings.append(f"{instance}: the annotation was drawn on a volume of "
                                    f"shape {stored_shape}, the file is now {list(volume.shape)}; "
                                    f"skipped")
                    continue
                folder = self._base(output_path, record)
                stem = f"{_safe(instance)}__{_safe(scheme['name'])}"
                path = os.path.join(folder, f"{stem}.nii.gz")
                with open(path, "wb") as fh:
                    fh.write(to_nifti_bytes(labelmap(annotation, volume.shape, names), volume))
                files.append(path)
                shapes = annotation.get("shapes") or []
                if shapes:
                    shape_path = os.path.join(folder, f"{stem}__shapes.json")
                    with open(shape_path, "w", encoding="utf-8") as fh:
                        json.dump({"coordinates": "canonical RAS+ voxel (i, j, k)",
                                   "shapes": shapes}, fh, indent=2)
                    files.append(shape_path)
                n_items += 1
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=warnings, stats={"num_items": n_items})


class DicomSegExporter(_VolumeExporter):
    format_name = "dicom_seg"
    description = "Volume masks as DICOM Segmentation objects referencing the source series"
    file_extensions = [".dcm"]
    #: Also write a TID 1500 measurement report beside each SEG.
    with_sr = False

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        ok, reason = super().can_export(context)
        if not ok:
            return ok, reason
        try:
            import highdicom  # noqa: F401
        except ImportError:
            return False, "needs highdicom: pip install 'potato-annotation[volumes]'"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.media.volume_masks import (label_volume, source_datasets, to_dicom_seg,
                                               to_dicom_sr)
        from potato.server_utils.schemas.volume_annotation import label_dicom_codes
        files, warnings = [], []
        not_dicom = []
        n_reports = 0
        for scheme in _volume_schemes(context):
            names = _label_names(scheme)
            try:
                codes = label_dicom_codes(scheme)
            except ValueError as exc:
                warnings.append(f"{scheme.get('name')}: {exc}")
                continue
            for record, item, annotation in _records(context, scheme):
                instance = str(record.get("instance_id"))
                try:
                    volume = _open(context, scheme, item, annotation)
                except Exception as exc:
                    warnings.append(f"{instance}: {exc}")
                    continue
                if volume.kind != "dicom":
                    not_dicom.append(instance)
                    continue
                stored_shape = annotation.get("shape")
                if stored_shape and list(stored_shape) != list(volume.shape):
                    warnings.append(f"{instance}: the annotation was drawn on a volume of "
                                    f"shape {stored_shape}, the series is now "
                                    f"{list(volume.shape)}; skipped")
                    continue
                masks = {name: label_volume(annotation, volume.shape, name) for name in names}
                if not any(mask.any() for mask in masks.values()):
                    continue
                annotator = str(record.get("user_id"))
                try:
                    sources = source_datasets(volume)
                    seg = to_dicom_seg(names, masks, volume, annotator=annotator,
                                       series_description=f"Potato {scheme['name']}",
                                       label_codes=codes, sources=sources)
                except Exception as exc:
                    warnings.append(f"{instance}: the SEG could not be built: {exc}")
                    continue
                folder = self._base(output_path, record)
                stem = f"{_safe(instance)}__{_safe(scheme['name'])}"
                path = os.path.join(folder, f"{stem}.dcm")
                seg.save_as(path)
                files.append(path)
                if not self.with_sr:
                    continue
                try:
                    sr = to_dicom_sr(seg, masks, volume, sources, annotator=annotator,
                                     label_codes=codes,
                                     series_description=f"Potato {scheme['name']} volumes")
                except Exception as exc:
                    warnings.append(f"{instance}: the SR could not be built: {exc}")
                    continue
                sr_path = os.path.join(folder, f"{stem}__sr.dcm")
                sr.save_as(sr_path)
                files.append(sr_path)
                n_reports += 1
        if not_dicom:
            warnings.append(f"{len(set(not_dicom))} item(s) are not DICOM series, and a SEG "
                            f"references DICOM images; use volume_nifti for them: "
                            f"{', '.join(sorted(set(not_dicom))[:10])}")
        stats = {"num_files": len(files)}
        if self.with_sr:
            stats["num_reports"] = n_reports
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=warnings, stats=stats)


class DicomSrExporter(DicomSegExporter):
    """The SEG plus a DICOM SR measurement report (TID 1500) that references it.

    Both are written together because the SR points at the SEG by its SOP
    Instance UID: a SEG written by a separate ``dicom_seg`` run gets a new
    UID, and the report would then reference an object that does not exist.
    """
    format_name = "dicom_sr"
    description = ("Volume masks as a DICOM SEG plus a Comprehensive 3D SR (TID 1500) "
                   "with each segment's volume and the annotator as observer")
    file_extensions = [".dcm"]
    with_sr = True

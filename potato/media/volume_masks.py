"""
Label masks on a 3D volume: storage, interpolation, import, export, agreement.

A volume annotation stores, per label, one binary mask per axial slice it
touches, in canonical voxel space (see volumes.py):

    {"labels": ["Lesion", "Bone"],
     "masks": {"Lesion": {"24": [counts...], "25": [...]}},
     "shapes": [...]}

Each slice mask is an array of shape (nJ, nI) -- row j, column i, voxel order
rather than screen order -- flattened row-major and run-length encoded as
alternating counts of 0s and 1s, starting with 0s (COCO's uncompressed RLE
over a C-order flatten). Masks painted on coronal or sagittal views are
written into the axial slices they cross, so this is the only stored form.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# -- run-length encoding ----------------------------------------------------

def rle_encode(mask: np.ndarray) -> List[int]:
    flat = np.asarray(mask, dtype=bool).ravel(order="C")
    if flat.size == 0:
        return []
    changes = np.flatnonzero(np.diff(flat.astype(np.int8))) + 1
    bounds = np.concatenate(([0], changes, [flat.size]))
    counts = np.diff(bounds).tolist()
    if flat[0]:
        counts = [0] + counts
    return [int(c) for c in counts]


def rle_decode(counts: Sequence[int], shape: Tuple[int, int]) -> np.ndarray:
    total = int(shape[0]) * int(shape[1])
    flat = np.zeros(total, dtype=bool)
    position, value = 0, False
    for count in counts or ():
        count = int(count)
        if count < 0 or position + count > total:
            raise ValueError("RLE runs past the end of the slice")
        if value:
            flat[position:position + count] = True
        position += count
        value = not value
    return flat.reshape(shape)


def slice_shape(volume_shape: Sequence[int]) -> Tuple[int, int]:
    ni, nj, _nk = volume_shape
    return int(nj), int(ni)


def label_volume(annotation: Dict[str, Any], volume_shape: Sequence[int],
                 label: str) -> np.ndarray:
    """One label's mask as a boolean [i, j, k] array."""
    ni, nj, nk = (int(n) for n in volume_shape)
    out = np.zeros((ni, nj, nk), dtype=bool)
    for key, counts in ((annotation.get("masks") or {}).get(label) or {}).items():
        k = int(key)
        if 0 <= k < nk:
            out[:, :, k] = rle_decode(counts, (nj, ni)).T
    return out


def labelmap(annotation: Dict[str, Any], volume_shape: Sequence[int],
             labels: Optional[Sequence[str]] = None) -> np.ndarray:
    """All labels as a uint8 [i, j, k] array: 0 is background, n is labels[n-1].

    Where labels overlap, the later label in the list wins.
    """
    labels = list(labels if labels is not None else annotation.get("labels") or [])
    out = np.zeros(tuple(int(n) for n in volume_shape), dtype=np.uint8)
    for index, label in enumerate(labels, start=1):
        out[label_volume(annotation, volume_shape, label)] = index
    return out


def masks_from_volume(mask: np.ndarray) -> Dict[str, List[int]]:
    """A boolean [i, j, k] mask as the stored {k: counts} form (empty slices skipped)."""
    out = {}
    for k in range(mask.shape[2]):
        plane = mask[:, :, k].T
        if plane.any():
            out[str(k)] = rle_encode(plane)
    return out


# -- interpolation ---------------------------------------------------------

def _signed_distance(mask: np.ndarray) -> np.ndarray:
    from scipy.ndimage import distance_transform_edt
    if not mask.any():
        return np.full(mask.shape, np.inf)
    outside = distance_transform_edt(~mask)
    inside = distance_transform_edt(mask)
    return outside - inside


def interpolate_slices(slices: Dict[int, np.ndarray]) -> Dict[int, np.ndarray]:
    """Fill the gaps between painted slices of one label.

    Shape-based interpolation: each pair of consecutive painted slices with
    unpainted slices between them is blended through their signed distance
    maps. Returns only the new slices; painted ones are never changed, and
    the run before the first and after the last painted slice stays empty.
    """
    painted = sorted(k for k, m in slices.items() if np.asarray(m).any())
    filled: Dict[int, np.ndarray] = {}
    for low, high in zip(painted, painted[1:]):
        if high - low < 2:
            continue
        a = _signed_distance(np.asarray(slices[low], dtype=bool))
        b = _signed_distance(np.asarray(slices[high], dtype=bool))
        for k in range(low + 1, high):
            if k in slices and np.asarray(slices[k]).any():
                continue
            t = (k - low) / (high - low)
            filled[k] = ((1 - t) * a + t * b) <= 0
    return filled


def interpolation_gaps(slices: Dict[int, np.ndarray],
                       filled: Dict[int, np.ndarray]) -> List[Dict[str, Any]]:
    """Gaps interpolation could not fill, for telling the annotator why.

    Blending two outlines that do not overlap shrinks each toward nothing
    before the other grows, so the middle slices come out empty. Each
    returned gap names the painted pair and the slices left empty.
    """
    painted = sorted(k for k, m in slices.items() if np.asarray(m).any())
    gaps = []
    for low, high in zip(painted, painted[1:]):
        empty = [k for k in range(low + 1, high)
                 if not (k in filled and np.asarray(filled[k]).any())
                 and not (k in slices and np.asarray(slices[k]).any())]
        if empty:
            gaps.append({"from": low, "to": high, "empty": empty})
    return gaps


# -- RTSTRUCT import -------------------------------------------------------

def rtstruct_masks(rtstruct_path: str, volume) -> Dict[str, np.ndarray]:
    """Each ROI of an RTSTRUCT as a boolean [i, j, k] mask on ``volume``.

    Contour points are patient coordinates (LPS); they are taken into the
    volume's canonical voxel space through its affine and filled per slice.
    Contours on planes that do not fall on a slice are dropped with a
    warning rather than smeared onto the nearest one.
    """
    import pydicom
    from PIL import Image, ImageDraw

    ds = pydicom.dcmread(rtstruct_path)
    names = {int(r.ROINumber): str(r.ROIName) for r in getattr(ds, "StructureSetROISequence", [])}
    to_voxel = np.linalg.inv(volume.affine)
    ni, nj, nk = volume.shape
    out: Dict[str, np.ndarray] = {}
    for roi in getattr(ds, "ROIContourSequence", []):
        name = names.get(int(roi.ReferencedROINumber), f"ROI {roi.ReferencedROINumber}")
        mask = out.setdefault(name, np.zeros((ni, nj, nk), dtype=bool))
        for contour in getattr(roi, "ContourSequence", []):
            if str(getattr(contour, "ContourGeometricType", "")) not in ("CLOSED_PLANAR", ""):
                continue
            points = np.array(contour.ContourData, dtype=float).reshape(-1, 3)
            ras = points * np.array([-1.0, -1.0, 1.0])
            voxels = (to_voxel @ np.c_[ras, np.ones(len(ras))].T).T[:, :3]
            k_values = voxels[:, 2]
            k = int(round(float(k_values.mean())))
            if np.ptp(k_values) > 0.5 or not 0 <= k < nk or abs(k_values.mean() - k) > 0.25:
                logger.warning("RTSTRUCT %s: a contour of %s is not on an axial slice; "
                               "skipped", rtstruct_path, name)
                continue
            canvas = Image.new("1", (ni, nj), 0)
            ImageDraw.Draw(canvas).polygon([(float(i), float(j)) for i, j, _ in voxels],
                                           outline=1, fill=1)
            mask[:, :, k] |= np.asarray(canvas, dtype=bool).T
    return out


# -- export ----------------------------------------------------------------

def to_nifti_bytes(labels_ijk: np.ndarray, volume) -> bytes:
    """A label volume as .nii.gz bytes, in the source file's voxel order and affine."""
    import gzip
    import io
    import nibabel as nib
    from potato.media.volumes import to_source_order
    data = to_source_order(volume, labels_ijk).astype(np.uint8)
    image = nib.Nifti1Image(data, volume.source_affine)
    image.header.set_xyzt_units("mm")
    image.header["descrip"] = b"Potato label volume"
    raw = image.to_bytes()
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as gz:
        gz.write(raw)
    return buffer.getvalue()


def to_dicom_seg(labels: Sequence[str], label_masks: Dict[str, np.ndarray], volume,
                 *, series_description: str = "Potato segmentation",
                 annotator: Optional[str] = None) -> Any:
    """A DICOM SEG (highdicom) referencing the DICOM series the volume came from.

    By DICOM's rules the SEG copies the patient and study modules from its
    source images, so it carries the same identifying data as the series.
    """
    import highdicom as hd
    import pydicom
    from pydicom.sr.coding import Code
    from potato.media.volumes import to_source_order

    if volume.kind != "dicom" or not volume.dicom_files:
        raise ValueError("DICOM SEG export needs a DICOM series source")
    sources = [pydicom.dcmread(path) for path in volume.dicom_files]
    # The patient and study modules' Type 2 attributes must be present, even
    # if empty; de-identified series often drop them. Filled on the in-memory
    # copies only.
    for source in sources:
        for keyword in _TYPE2_COPIED:
            if keyword not in source:
                setattr(source, keyword, "")
    present = [label for label in labels if label_masks.get(label) is not None
               and label_masks[label].any()]
    if not present:
        raise ValueError("no label has any voxels to export")
    frames = []
    for label in present:
        source = to_source_order(volume, label_masks[label])          # [col, row, slice]
        frames.append(np.ascontiguousarray(source.transpose(2, 1, 0)))  # [slice, row, col]
    pixel_array = np.stack(frames, axis=-1).astype(np.uint8)
    tissue = Code("85756007", "SCT", "Tissue")
    descriptions = [
        hd.seg.SegmentDescription(
            segment_number=n, segment_label=label[:64],
            segmented_property_category=tissue, segmented_property_type=tissue,
            algorithm_type=hd.seg.SegmentAlgorithmTypeValues.MANUAL)
        for n, label in enumerate(present, start=1)]
    from potato import __version__ as potato_version
    seg = hd.seg.Segmentation(
        source_images=sources, pixel_array=pixel_array,
        segmentation_type=hd.seg.SegmentationTypeValues.BINARY,
        segment_descriptions=descriptions,
        series_instance_uid=hd.UID(), series_number=900,
        sop_instance_uid=hd.UID(), instance_number=1,
        manufacturer="Potato", manufacturer_model_name="Potato annotation",
        software_versions=str(potato_version), device_serial_number="0",
        series_description=series_description[:64],
        # A username is not a DICOM person name (Family^Given); it goes in
        # the free-text description instead.
        content_description=(f"Annotator: {annotator}"[:64] if annotator else None))
    return seg


#: Type 2 attributes highdicom copies from the source into the SEG.
_TYPE2_COPIED = ("PatientName", "PatientID", "PatientBirthDate", "PatientSex",
                 "StudyDate", "StudyTime", "ReferringPhysicianName", "StudyID",
                 "AccessionNumber")


# -- agreement -------------------------------------------------------------

def dice(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    """2|A and B| / (|A| + |B|); None when both are empty."""
    a, b = np.asarray(a, dtype=bool), np.asarray(b, dtype=bool)
    total = int(a.sum()) + int(b.sum())
    if total == 0:
        return None
    return 2.0 * int(np.logical_and(a, b).sum()) / total

"""
3D medical volumes: NIfTI files and DICOM series, read into one geometry.

Every volume becomes a nibabel image in the closest canonical orientation,
RAS+: voxel index i grows toward the patient's Right, j toward Anterior, k
toward Superior. Working in one orientation means the three views are always
anatomical whatever the scanner wrote, and the mask a browser paints lands in
the same voxels for a DICOM series and for the NIfTI conversion of it.
``to_source_order`` puts a canonical array back into the file's own voxel
order for export.

Views are drawn in radiological convention -- the patient's right on the
viewer's left -- and the same index mapping lives in volume-annotation.js:

* axial (k fixed):    row r -> j = nJ-1-r,  column c -> i = nI-1-c
* coronal (j fixed):  row r -> k = nK-1-r,  column c -> i = nI-1-c
* sagittal (i fixed): row r -> k = nK-1-r,  column c -> j = nJ-1-c

DICOM headers carry patient information. Only the tags an administrator
lists in ``display_tags`` reach an annotator, and the identifying ones
(DICOM PS3.15 basic profile) only when also listed in
``allow_identifying_tags``.

Needs the optional extra: ``pip install 'potato-annotation[volumes]'``.
"""

from __future__ import annotations

import io
import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

INSTALL_HINT = "Volumes need pydicom and nibabel: pip install 'potato-annotation[volumes]'"

NIFTI_SUFFIXES = (".nii", ".nii.gz")
AXES = ("axial", "coronal", "sagittal")

#: Window presets (center, width) by modality.
PRESETS = {
    "CT": [("Soft tissue", 40, 400), ("Lung", -600, 1500), ("Bone", 400, 1800),
           ("Brain", 40, 80)],
}

#: Attributes DICOM PS3.15's basic confidentiality profile removes or
#: replaces. They never reach an annotator unless an administrator names them
#: in ``allow_identifying_tags`` as well as ``display_tags``.
IDENTIFYING_TAGS = frozenset({
    "PatientName", "PatientID", "IssuerOfPatientID", "OtherPatientIDs",
    "OtherPatientIDsSequence", "OtherPatientNames", "PatientBirthName",
    "PatientBirthDate", "PatientBirthTime", "PatientSex", "PatientAge",
    "PatientSize", "PatientWeight", "PatientAddress", "PatientTelephoneNumbers",
    "PatientMotherBirthName", "MedicalRecordLocator", "EthnicGroup", "Occupation",
    "AdditionalPatientHistory", "PatientComments", "MilitaryRank",
    "BranchOfService", "CountryOfResidence", "RegionOfResidence",
    "InstitutionName", "InstitutionAddress", "InstitutionalDepartmentName",
    "ReferringPhysicianName", "ReferringPhysicianAddress",
    "ReferringPhysicianTelephoneNumbers", "PerformingPhysicianName",
    "NameOfPhysiciansReadingStudy", "PhysiciansOfRecord", "OperatorsName",
    "RequestingPhysician", "AccessionNumber", "StudyID", "StudyDate",
    "SeriesDate", "AcquisitionDate", "ContentDate", "StudyTime", "SeriesTime",
    "AcquisitionTime", "ContentTime", "AcquisitionDateTime", "StationName",
    "DeviceSerialNumber", "StudyInstanceUID", "SeriesInstanceUID",
    "SOPInstanceUID", "FrameOfReferenceUID", "StudyDescription",
    "SeriesDescription", "ProtocolName", "ImageComments",
    "RequestAttributesSequence", "PerformedProcedureStepDescription",
})


class VolumeError(Exception):
    """A volume that cannot be read. The message says why and what to do."""


def volumes_available() -> bool:
    try:
        import nibabel  # noqa: F401
        import pydicom  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class Volume:
    """A volume in canonical RAS+ voxel order, data[i, j, k]."""
    data: np.ndarray
    affine: np.ndarray                  # voxel (i, j, k, 1) -> RAS mm
    spacing: Tuple[float, float, float]
    kind: str                           # "nifti" | "dicom"
    modality: str = ""
    dicom_windows: List[Tuple[float, float]] = field(default_factory=list)
    #: The first DICOM slice's header, without pixel data (tags on request).
    header: Any = None
    #: DICOM source files in canonical k order, for SEG export.
    dicom_files: List[str] = field(default_factory=list)
    #: For a multi-frame (enhanced) source: the single file's frame index of
    #: each slice in canonical k order; None for a classic series.
    dicom_frames: Optional[List[int]] = None
    #: nibabel orientation of the source, to put a mask back into it.
    source_ornt: Any = None
    source_shape: Tuple[int, ...] = ()
    #: The source file's own voxel -> RAS affine, for exports in its order.
    source_affine: Any = None

    @property
    def shape(self) -> Tuple[int, int, int]:
        return tuple(int(n) for n in self.data.shape[:3])


# -- raw files -------------------------------------------------------------

def is_raw_medical_file(path: str) -> bool:
    """A DICOM or NIfTI file, which /media/ must not hand out as-is.

    DICOM is recognised by its "DICM" preamble marker at byte 128, so a
    file without a .dcm suffix is caught too; NIfTI by suffix or by its
    single-file magic. Both carry header text (patient tags, or NIfTI's free
    descrip / aux_file / db_name fields) that the volume routes filter.
    """
    lowered = str(path).lower()
    if lowered.endswith(NIFTI_SUFFIXES + (".hdr",)):
        return True
    try:
        with open(path, "rb") as handle:
            head = handle.read(352)
    except OSError:
        return False
    if len(head) >= 132 and head[128:132] == b"DICM":
        return True
    return len(head) >= 348 and head[344:348] in (b"n+1\0", b"n+2\0")


# -- reading ---------------------------------------------------------------

def is_volume_path(path: str) -> bool:
    lowered = path.lower()
    if lowered.endswith(NIFTI_SUFFIXES):
        return True
    return os.path.isdir(path)


def _require():
    try:
        import nibabel  # noqa: F401
        import pydicom  # noqa: F401
    except ImportError as exc:
        raise VolumeError(INSTALL_HINT) from exc


def read_volume(path: str) -> Volume:
    """Read a NIfTI file or a directory holding one DICOM series."""
    _require()
    if os.path.isdir(path):
        return _read_dicom_series(path)
    if str(path).lower().endswith(NIFTI_SUFFIXES):
        return _read_nifti(path)
    raise VolumeError(f"{Path(path).name} is not a NIfTI file (.nii, .nii.gz) or a "
                      "directory of DICOM files")


def _canonical(image, kind, **extra) -> Volume:
    import nibabel as nib
    from nibabel.orientations import io_orientation

    source_ornt = io_orientation(image.affine)
    canonical = nib.as_closest_canonical(image)
    data = np.asanyarray(canonical.dataobj)
    if data.ndim == 4 and data.shape[3] == 1:
        data = data[..., 0]
    if data.ndim != 3:
        raise VolumeError(f"expected a 3D volume, found {data.ndim} dimensions "
                          f"(shape {data.shape})")
    zooms = tuple(float(z) for z in canonical.header.get_zooms()[:3])
    return Volume(data=data, affine=np.asarray(canonical.affine, dtype=float),
                  spacing=zooms, kind=kind, source_ornt=source_ornt,
                  source_shape=tuple(image.shape[:3]),
                  source_affine=np.asarray(image.affine, dtype=float), **extra)


def _read_nifti(path: str) -> Volume:
    import nibabel as nib
    try:
        image = nib.load(path)
    except Exception as exc:
        raise VolumeError(f"{Path(path).name} could not be read as NIfTI: {exc}") from exc
    image = nib.Nifti1Image(np.asanyarray(image.dataobj).astype(np.float32),
                            image.affine, image.header)
    return _canonical(image, "nifti")


def _read_dicom_series(directory: str) -> Volume:
    import nibabel as nib
    import pydicom

    files = []
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if not os.path.isfile(full) or name.startswith("."):
            continue
        try:
            ds = pydicom.dcmread(full, stop_before_pixels=True)
        except Exception:
            continue                    # not DICOM: a README, a thumbnail
        if "PixelData" not in ds and not hasattr(ds, "Rows"):
            continue
        files.append((full, ds))
    if not files:
        raise VolumeError(f"{Path(directory).name}/ holds no DICOM images")

    by_series: Dict[str, list] = {}
    for full, ds in files:
        by_series.setdefault(str(getattr(ds, "SeriesInstanceUID", "")), []).append((full, ds))
    if len(by_series) > 1:
        raise VolumeError(f"{Path(directory).name}/ holds {len(by_series)} DICOM series; "
                          "put each series in its own directory")
    series = next(iter(by_series.values()))
    first = series[0][1]
    multiframe = [item for item in series if int(getattr(item[1], "NumberOfFrames", 1) or 1) > 1]
    if multiframe and (len(multiframe) > 1 or len(series) > 1):
        raise VolumeError("this series mixes several multi-frame files, or multi-frame and "
                          "single-frame files; put one multi-frame file in its own directory")
    frames = _enhanced_frames(*multiframe[0]) if multiframe else [_classic_frame(f, ds)
                                                                  for f, ds in series]
    for key, attr in (("orientation", "ImageOrientationPatient"),
                      ("position", "ImagePositionPatient"), ("spacing", "PixelSpacing")):
        if any(frame[key] is None for frame in frames):
            raise VolumeError(f"the DICOM images have no {attr}, so they cannot be "
                              "placed in 3D")
    if any(str(getattr(ds, "BurnedInAnnotation", "")).upper() == "YES" for _f, ds in series):
        # Ultrasound and secondary captures often write the patient's name
        # into the image itself, where no tag filter can reach it.
        raise VolumeError("these images are marked BurnedInAnnotation YES: patient "
                          "details may be written into the pixels. Remove them from "
                          "the images before using the series")

    orientation = np.array(frames[0]["orientation"], dtype=float)
    for frame in frames:
        if not np.allclose(np.array(frame["orientation"], dtype=float), orientation, atol=1e-4):
            raise VolumeError("the slices do not all have the same orientation "
                              "(ImageOrientationPatient); a localizer or scout image "
                              "may be in the series. Remove it and try again")
    row_dir, col_dir = orientation[:3], orientation[3:]
    normal = np.cross(row_dir, col_dir)
    frames.sort(key=lambda frame: float(np.dot(np.array(frame["position"], dtype=float), normal)))
    positions = [np.array(frame["position"], dtype=float) for frame in frames]
    if len(frames) > 1:
        steps = np.diff([float(np.dot(p, normal)) for p in positions])
        if np.any(steps <= 0) or np.ptp(steps) > 0.01 * max(abs(steps.mean()), 1e-6):
            raise VolumeError("the DICOM slices are not evenly spaced along one axis "
                              "(missing or duplicated slices?)")
        slice_vector = (positions[-1] - positions[0]) / (len(frames) - 1)
        cosine = abs(float(np.dot(slice_vector, normal))) / max(np.linalg.norm(slice_vector), 1e-9)
        tilt = float(np.degrees(np.arccos(min(1.0, cosine))))
        if tilt > 0.5:
            # The world geometry would be right (a sheared affine) but the
            # views and the slice spacing would not.
            raise VolumeError(f"the series has a {tilt:.1f} degree gantry tilt; resample "
                              "it to orthogonal slices first (dcm2niix does this)")
    else:
        slice_vector = normal * float(frames[0]["thickness"] or 1.0)

    if multiframe:
        pixels_all = pydicom.dcmread(multiframe[0][0]).pixel_array
        slices = [pixels_all[frame["frame"]].astype(np.float32) * frame["slope"] + frame["intercept"]
                  for frame in frames]
    else:
        slices = []
        for frame in frames:
            pixels = pydicom.dcmread(frame["file"]).pixel_array.astype(np.float32)
            slices.append(pixels * frame["slope"] + frame["intercept"])
    stack = np.stack(slices, axis=0)                      # (slice, row, col)
    data_ijk = np.ascontiguousarray(stack.transpose(2, 1, 0))  # (col, row, slice)

    row_spacing, col_spacing = (float(v) for v in frames[0]["spacing"])
    lps = np.eye(4)
    lps[:3, 0] = row_dir * col_spacing                    # i: along a row
    lps[:3, 1] = col_dir * row_spacing                    # j: down a column
    lps[:3, 2] = slice_vector
    lps[:3, 3] = positions[0]
    ras = np.diag([-1.0, -1.0, 1.0, 1.0]) @ lps

    windows = []
    centers, widths = frames[0]["window"]
    if centers is not None and widths is not None:
        centers = list(centers) if hasattr(centers, "__iter__") else [centers]
        widths = list(widths) if hasattr(widths, "__iter__") else [widths]
        windows = [(float(c), float(w)) for c, w in zip(centers, widths)]

    volume = _canonical(nib.Nifti1Image(data_ijk, ras), "dicom",
                        modality=str(getattr(first, "Modality", "") or ""),
                        dicom_windows=windows, header=first)
    # Source order: source voxel k is dicom_files[k] (to_source_order maps a
    # canonical mask back onto it), or frame dicom_frames[k] of the one
    # multi-frame file.
    if multiframe:
        volume.dicom_files = [multiframe[0][0]]
        volume.dicom_frames = [frame["frame"] for frame in frames]
    else:
        volume.dicom_files = [frame["file"] for frame in frames]
    return volume


def _classic_frame(path: str, ds) -> Dict[str, Any]:
    """One single-frame DICOM file as a frame record."""
    return {"file": path, "frame": None,
            "orientation": getattr(ds, "ImageOrientationPatient", None),
            "position": getattr(ds, "ImagePositionPatient", None),
            "spacing": getattr(ds, "PixelSpacing", None),
            "thickness": getattr(ds, "SliceThickness", None),
            "slope": float(getattr(ds, "RescaleSlope", 1) or 1),
            "intercept": float(getattr(ds, "RescaleIntercept", 0) or 0),
            "window": (getattr(ds, "WindowCenter", None), getattr(ds, "WindowWidth", None))}


def _enhanced_frames(path: str, ds) -> List[Dict[str, Any]]:
    """Each frame of a multi-frame (enhanced) DICOM file as a frame record.

    Enhanced files keep each frame's geometry in its own functional groups
    (PerFrameFunctionalGroupsSequence), with what all frames share in
    SharedFunctionalGroupsSequence; a value per frame wins over a shared one,
    and a shared one over the same attribute at the top level.
    """
    shared_seq = getattr(ds, "SharedFunctionalGroupsSequence", None)
    shared = shared_seq[0] if shared_seq else None
    per_frame = list(getattr(ds, "PerFrameFunctionalGroupsSequence", None) or [])
    count = int(getattr(ds, "NumberOfFrames", 1) or 1)
    if len(per_frame) != count:
        raise VolumeError(f"{Path(path).name} has {count} frames but "
                          f"{len(per_frame)} per-frame functional groups")

    def value(group, sequence, attr):
        for owner in (group, shared):
            items = getattr(owner, sequence, None) if owner is not None else None
            if items:
                found = getattr(items[0], attr, None)
                if found is not None:
                    return found
        # Some vendor and legacy-converted files leave a value (RescaleSlope,
        # WindowCenter) at the top level instead of in a functional group.
        return getattr(ds, attr, None)

    frames = []
    for index, group in enumerate(per_frame):
        slope = value(group, "PixelValueTransformationSequence", "RescaleSlope")
        intercept = value(group, "PixelValueTransformationSequence", "RescaleIntercept")
        frames.append({
            "file": path, "frame": index,
            "orientation": value(group, "PlaneOrientationSequence", "ImageOrientationPatient"),
            "position": value(group, "PlanePositionSequence", "ImagePositionPatient"),
            "spacing": value(group, "PixelMeasuresSequence", "PixelSpacing"),
            "thickness": value(group, "PixelMeasuresSequence", "SliceThickness"),
            "slope": float(slope if slope is not None else 1) or 1.0,
            "intercept": float(intercept if intercept is not None else 0),
            "window": (value(group, "FrameVOILUTSequence", "WindowCenter"),
                       value(group, "FrameVOILUTSequence", "WindowWidth")),
        })
    return frames


def to_source_order(volume: "Volume", array: np.ndarray) -> np.ndarray:
    """A canonical [i, j, k] array in the source file's voxel order.

    For a DICOM series that is [column, row, slice] with slice k in
    ``volume.dicom_files[k]``; for NIfTI, the file's own axes.
    """
    from nibabel.orientations import apply_orientation, ornt_transform
    canonical_ornt = np.array([[0, 1], [1, 1], [2, 1]])
    return apply_orientation(array, ornt_transform(canonical_ornt, volume.source_ornt))


# -- caching ---------------------------------------------------------------

_cache: "OrderedDict[Tuple[str, float], Volume]" = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_SIZE = 3


def _version(path: str) -> float:
    if os.path.isdir(path):
        stamps = [os.path.getmtime(os.path.join(path, n)) for n in os.listdir(path)]
        return max(stamps + [os.path.getmtime(path)])
    return os.path.getmtime(path)


def load_volume(path: str) -> Volume:
    """read_volume with a small in-process cache keyed by path and mtime."""
    key = (os.path.abspath(path), _version(path))
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    volume = read_volume(path)
    with _cache_lock:
        _cache[key] = volume
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return volume


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# -- views -----------------------------------------------------------------

def view_slice(volume: Volume, axis: str, index: int) -> np.ndarray:
    """The 2D array an axis view shows at ``index``, in screen orientation."""
    data = volume.data
    ni, nj, nk = volume.shape
    if axis == "axial":
        if not 0 <= index < nk:
            raise VolumeError(f"axial slice {index} is outside 0..{nk - 1}")
        return data[::-1, ::-1, index].T
    if axis == "coronal":
        if not 0 <= index < nj:
            raise VolumeError(f"coronal slice {index} is outside 0..{nj - 1}")
        return data[::-1, index, ::-1].T
    if axis == "sagittal":
        if not 0 <= index < ni:
            raise VolumeError(f"sagittal slice {index} is outside 0..{ni - 1}")
        return data[index, ::-1, ::-1].T
    raise VolumeError(f"axis must be one of {', '.join(AXES)}")


def windows(volume: Volume) -> List[Dict[str, Any]]:
    """Window presets to offer: the file's own, the modality's, a fallback."""
    out = [{"name": f"From file{'' if i == 0 else f' {i + 1}'}", "center": c, "width": w}
           for i, (c, w) in enumerate(volume.dicom_windows) if w > 0]
    out += [{"name": n, "center": c, "width": w}
            for n, c, w in PRESETS.get(volume.modality.upper(), [])]
    lo, hi = np.percentile(volume.data[np.isfinite(volume.data)], [1, 99])
    out.append({"name": "Auto", "center": float((lo + hi) / 2),
                "width": float(max(hi - lo, 1e-6))})
    return out


def render_png(volume: Volume, axis: str, index: int, center: float, width: float) -> bytes:
    from PIL import Image
    plane = view_slice(volume, axis, index).astype(np.float32)
    width = max(float(width), 1e-6)
    low = center - width / 2
    scaled = np.clip((plane - low) / width, 0, 1) * 255
    image = Image.fromarray(scaled.astype(np.uint8), mode="L")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def header_tags(volume: Volume, display_tags: Sequence[str],
                allow_identifying_tags: Sequence[str] = ()) -> Dict[str, str]:
    """The header values an annotator may see, in the order asked for."""
    if volume.header is None:
        return {}
    allowed = set(allow_identifying_tags or ())
    shown = {}
    for keyword in display_tags or ():
        if keyword in IDENTIFYING_TAGS and keyword not in allowed:
            continue
        value = volume.header.get(keyword)
        if value is None:
            value = _shared_functional_value(volume.header, keyword)
        if value is None:
            continue
        text = str(value.value if hasattr(value, "value") else value)
        if text:
            shown[keyword] = text
    return shown


def _shared_functional_value(header, keyword: str):
    """A tag an enhanced file keeps in its shared functional groups
    (SliceThickness under PixelMeasuresSequence, say), or None."""
    shared = getattr(header, "SharedFunctionalGroupsSequence", None)
    if not shared:
        return None
    for element in shared[0]:
        if element.VR == "SQ" and element.value:
            found = element.value[0].get(keyword)
            if found is not None:
                return found
    return None


def describe(volume: Volume, display_tags=(), allow_identifying_tags=()) -> Dict[str, Any]:
    finite = volume.data[np.isfinite(volume.data)]
    return {
        "kind": volume.kind,
        "shape": list(volume.shape),
        "spacing": [round(s, 6) for s in volume.spacing],
        "modality": volume.modality,
        "range": [float(finite.min()), float(finite.max())] if finite.size else [0, 0],
        "windows": windows(volume),
        "tags": header_tags(volume, display_tags, allow_identifying_tags),
    }

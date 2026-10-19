"""
Generate the synthetic CT phantom this example annotates.

Writes, from one array:

* media/phantom_dicom/  a 48-slice CT series (one file per slice)
* media/phantom.nii.gz  the same volume as NIfTI, same physical geometry
* media/phantom_rtstruct.dcm  an RTSTRUCT outlining the "lesion" sphere

The phantom is an elliptical body (40 HU) in air (-1000 HU) with a bone ring
(700 HU) and a 9 mm-radius sphere (120 HU). The DICOM header carries made-up
patient details, so the example shows identifying tags being withheld.
Deterministic: run it again and the files are the same apart from UIDs.

    python examples/image/ct-volume/generate_volume.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

COLS, ROWS, SLICES = 96, 80, 48
PIXEL = 0.8            # mm, in-plane
THICKNESS = 2.5        # mm, between slices
ORIGIN = np.array([-38.4, -32.0, -60.0])      # LPS of the first voxel
LESION_CENTER = (60, 30, 24)                  # col, row, slice
LESION_RADIUS = 9.0                           # mm


def phantom() -> np.ndarray:
    """HU values, indexed [slice, row, col]."""
    rng = np.random.default_rng(7)
    z, y, x = np.mgrid[0:SLICES, 0:ROWS, 0:COLS].astype(float)
    hu = np.full((SLICES, ROWS, COLS), -1000.0)
    body = ((x - COLS / 2) / 42) ** 2 + ((y - ROWS / 2) / 34) ** 2 <= 1
    hu[body] = 40.0
    ring = np.hypot(x - COLS / 2, y - ROWS * 0.62)
    hu[(ring >= 6) & (ring <= 9) & body] = 700.0
    cx, cy, cz = LESION_CENTER
    lesion = np.sqrt(((x - cx) * PIXEL) ** 2 + ((y - cy) * PIXEL) ** 2
                     + ((z - cz) * THICKNESS) ** 2) <= LESION_RADIUS
    hu[lesion] = 120.0
    hu[body] += rng.normal(0, 6, size=int(body.sum()))
    return hu.round()


def lps_affine() -> np.ndarray:
    affine = np.eye(4)
    affine[:3, 0] = [PIXEL, 0, 0]          # i: columns, along +x (L)
    affine[:3, 1] = [0, PIXEL, 0]          # j: rows, along +y (P)
    affine[:3, 2] = [0, 0, THICKNESS]      # k: slices, along +z (S)
    affine[:3, 3] = ORIGIN
    return affine


def write_dicom(hu: np.ndarray, out: Path):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.dcm"):
        old.unlink()
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    uids = []
    for k in range(SLICES):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = Dataset()
        ds.file_meta = meta
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID = study, series
        ds.FrameOfReferenceUID = frame
        ds.Modality = "CT"
        # Made up, and here to be withheld: see display_tags in config.yaml.
        ds.PatientName = "Phantom^Synthetic"
        ds.PatientID = "PHANTOM-0001"
        ds.PatientBirthDate = "19700101"
        ds.InstitutionName = "Potato Example Hospital"
        ds.StudyDate = dt.date(2026, 1, 1).strftime("%Y%m%d")
        ds.SeriesDescription = "Synthetic chest phantom"
        ds.BodyPartExamined = "CHEST"
        ds.Manufacturer = "Potato synthetic"
        ds.KVP = "120"
        ds.SliceThickness = str(THICKNESS)
        ds.PixelSpacing = [str(PIXEL), str(PIXEL)]
        ds.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
        position = ORIGIN + np.array([0, 0, k * THICKNESS])
        ds.ImagePositionPatient = [f"{v:.4f}" for v in position]
        ds.SliceLocation = f"{position[2]:.4f}"
        ds.InstanceNumber = k + 1
        ds.Rows, ds.Columns = ROWS, COLS
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
        ds.PixelRepresentation = 0
        ds.RescaleIntercept, ds.RescaleSlope = "-1024", "1"
        ds.WindowCenter, ds.WindowWidth = "40", "400"
        ds.PixelData = (hu[k] + 1024).astype(np.uint16).tobytes()
        ds.save_as(out / f"slice_{k:03d}.dcm", enforce_file_format=True)
        uids.append(ds.SOPInstanceUID)
    return study, series, frame, uids


def write_nifti(hu: np.ndarray, out: Path):
    import nibabel as nib
    ras = np.diag([-1.0, -1.0, 1.0, 1.0]) @ lps_affine()
    data = hu.transpose(2, 1, 0).astype(np.int16)          # [i, j, k]
    image = nib.Nifti1Image(data, ras)
    image.header.set_xyzt_units("mm")
    nib.save(image, out)


def write_rtstruct(out: Path, study, series, frame, uids):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.sequence import Sequence
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

    rt_class = "1.2.840.10008.5.1.4.1.1.481.3"
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = rt_class
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID, ds.SOPInstanceUID = rt_class, meta.MediaStorageSOPInstanceUID
    ds.Modality = "RTSTRUCT"
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study, generate_uid()
    ds.PatientName, ds.PatientID = "Phantom^Synthetic", "PHANTOM-0001"
    ds.StructureSetLabel = "Example"

    image_refs = Sequence()
    for uid in uids:
        ref = Dataset()
        ref.ReferencedSOPClassUID, ref.ReferencedSOPInstanceUID = CTImageStorage, uid
        image_refs.append(ref)
    series_ref = Dataset()
    series_ref.SeriesInstanceUID = series
    series_ref.ContourImageSequence = image_refs
    study_ref = Dataset()
    study_ref.ReferencedSOPClassUID = "1.2.840.10008.3.1.2.3.1"
    study_ref.ReferencedSOPInstanceUID = study
    study_ref.RTReferencedSeriesSequence = Sequence([series_ref])
    frame_ref = Dataset()
    frame_ref.FrameOfReferenceUID = frame
    frame_ref.RTReferencedStudySequence = Sequence([study_ref])
    ds.ReferencedFrameOfReferenceSequence = Sequence([frame_ref])

    roi = Dataset()
    roi.ROINumber, roi.ReferencedFrameOfReferenceUID = 1, frame
    roi.ROIName, roi.ROIGenerationAlgorithm = "Lesion", "MANUAL"
    ds.StructureSetROISequence = Sequence([roi])

    cx, cy, cz = LESION_CENTER
    center = ORIGIN + np.array([cx * PIXEL, cy * PIXEL, 0])
    contours = Sequence()
    for k in range(SLICES):
        dz = (k - cz) * THICKNESS
        if abs(dz) >= LESION_RADIUS:
            continue
        radius = np.sqrt(LESION_RADIUS ** 2 - dz ** 2)
        z = ORIGIN[2] + k * THICKNESS
        angles = np.linspace(0, 2 * np.pi, 32, endpoint=False)
        points = []
        for a in angles:
            points += [round(center[0] + radius * np.cos(a), 3),
                       round(center[1] + radius * np.sin(a), 3), round(z, 3)]
        contour = Dataset()
        image = Dataset()
        image.ReferencedSOPClassUID, image.ReferencedSOPInstanceUID = CTImageStorage, uids[k]
        contour.ContourImageSequence = Sequence([image])
        contour.ContourGeometricType = "CLOSED_PLANAR"
        contour.NumberOfContourPoints = len(points) // 3
        contour.ContourData = points
        contours.append(contour)
    roi_contour = Dataset()
    roi_contour.ReferencedROINumber = 1
    roi_contour.ROIDisplayColor = [230, 80, 60]
    roi_contour.ContourSequence = contours
    ds.ROIContourSequence = Sequence([roi_contour])
    observation = Dataset()
    observation.ObservationNumber, observation.ReferencedROINumber = 1, 1
    observation.RTROIInterpretedType, observation.ROIInterpreter = "GTV", ""
    ds.RTROIObservationsSequence = Sequence([observation])
    ds.save_as(out, enforce_file_format=True)


def main():
    hu = phantom()
    media = HERE / "media"
    media.mkdir(parents=True, exist_ok=True)
    study, series, frame, uids = write_dicom(hu, media / "phantom_dicom")
    write_nifti(hu, media / "phantom.nii.gz")
    write_rtstruct(media / "phantom_rtstruct.dcm", study, series, frame, uids)
    print(f"wrote {media}")


if __name__ == "__main__":
    main()

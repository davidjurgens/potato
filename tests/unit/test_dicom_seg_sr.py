"""
DICOM SEG and SR export from volume_annotation, read back with pydicom and
highdicom.

The source is a small synthetic CT series written here with pydicom: 16 x 12
pixels, 6 slices, 0.7 mm pixels, 2.0 mm apart, made-up identifiers. Masks are
painted in canonical voxel space, stored the way the client stores them
(volume_masks.masks_from_volume), and exported through the registry, so
these tests start from the stored annotation, not from a hand-built SEG.
"""

import json
import os
import shutil

import numpy as np
import pytest

pydicom = pytest.importorskip("pydicom")
hd = pytest.importorskip("highdicom")
pytest.importorskip("nibabel")

from potato.export.base import ExportContext  # noqa: E402
from potato.export.registry import export_registry  # noqa: E402
from potato.media import volume_masks as vm  # noqa: E402
from potato.media import volumes as vol  # noqa: E402
from potato.server_utils.config_module import (  # noqa: E402
    ConfigValidationError, validate_single_annotation_scheme)
from tests.helpers.test_utils import create_test_directory  # noqa: E402

COLS, ROWS, SLICES = 16, 12, 6
PIXEL, GAP = 0.7, 2.0
VOXEL_MM3 = PIXEL * PIXEL * GAP

LESION = {"category": {"code": "49755003", "scheme": "SCT",
                       "meaning": "Morphologically Altered Structure"},
          "type": {"code": "52988006", "scheme": "SCT", "meaning": "Lesion"},
          "anatomic_region": {"code": "39607008", "scheme": "SCT", "meaning": "Lung"}}

SCHEME = {"annotation_type": "volume_annotation", "name": "seg",
          "description": "Segment", "source_field": "volume",
          "labels": [{"name": "Lesion", "dicom": LESION}, {"name": "Bone"}, {"name": "Empty"}]}


def write_series(folder):
    """A synthetic CT series: one file per slice, fake patient and study."""
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid
    os.makedirs(folder, exist_ok=True)
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    rng = np.random.default_rng(3)
    for k in range(SLICES):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = Dataset()
        ds.file_meta = meta
        ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = study, series, frame
        ds.PatientName, ds.PatientID = "TEST^SYNTHETIC", "FAKE-0001"
        ds.PatientBirthDate, ds.PatientSex = "", "O"
        ds.StudyDate, ds.StudyTime, ds.StudyID, ds.AccessionNumber = "20000101", "120000", "1", ""
        ds.ReferringPhysicianName = ""
        ds.Modality, ds.SeriesNumber, ds.InstanceNumber = "CT", 1, k + 1
        ds.Manufacturer = "Synthetic"
        ds.ImagePositionPatient = [0.0, 0.0, k * GAP]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.PixelSpacing = [PIXEL, PIXEL]
        ds.SliceThickness = GAP
        ds.Rows, ds.Columns = ROWS, COLS
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 1
        ds.RescaleIntercept, ds.RescaleSlope = 0, 1
        ds.PixelData = rng.integers(-100, 100, (ROWS, COLS)).astype(np.int16).tobytes()
        ds.save_as(os.path.join(folder, f"slice_{k:02d}.dcm"), enforce_file_format=True)


@pytest.fixture(scope="module")
def project():
    root = create_test_directory("dicom_seg_sr")
    media = os.path.join(root, "media")
    shutil.rmtree(media, ignore_errors=True)
    write_series(os.path.join(media, "ct"))
    return root


@pytest.fixture(scope="module")
def volume(project):
    return vol.read_volume(os.path.join(project, "media", "ct"))


def masks(volume):
    lesion = np.zeros(volume.shape, bool)
    lesion[4:9, 3:7, 1:4] = True             # 5 x 4 x 3 = 60 voxels
    bone = np.zeros(volume.shape, bool)
    bone[10:12, 8:10, 5] = True              # 4 voxels
    return {"Lesion": lesion, "Bone": bone, "Empty": np.zeros(volume.shape, bool)}


def context(project, volume, scheme=SCHEME, user="ada"):
    m = masks(volume)
    stored = {"shape": list(volume.shape),
              "masks": {name: vm.masks_from_volume(mask) for name, mask in m.items()}}
    record = {"instance_id": "case 1", "user_id": user,
              "labels": {scheme["name"]: {"_data": json.dumps(stored)}}}
    return ExportContext(config={"task_dir": project, "media_directory": "media"},
                         annotations=[record], items={"case 1": {"id": "case 1", "volume": "ct"}},
                         schemas=[scheme], output_dir=project)


def read(path):
    return pydicom.dcmread(path)


class TestSegmentation:
    def test_each_label_with_voxels_is_a_coded_segment(self, project, volume):
        out = os.path.join(project, "out_seg")
        shutil.rmtree(out, ignore_errors=True)
        result = export_registry.export("dicom_seg", context(project, volume), out)
        assert result.success, result.errors
        (path,) = result.files_written
        assert path.endswith(os.path.join("ada", "case_1__seg.dcm"))
        seg = read(path)
        assert [s.SegmentLabel for s in seg.SegmentSequence] == ["Lesion", "Bone"]
        lesion, bone = seg.SegmentSequence
        assert lesion.SegmentedPropertyTypeCodeSequence[0].CodeValue == "52988006"
        assert lesion.SegmentedPropertyTypeCodeSequence[0].CodeMeaning == "Lesion"
        assert lesion.SegmentedPropertyCategoryCodeSequence[0].CodeValue == "49755003"
        assert lesion.AnatomicRegionSequence[0].CodeValue == "39607008"
        assert lesion.TrackingID == "Lesion"
        # No codes in the config: the generic default.
        assert bone.SegmentedPropertyTypeCodeSequence[0].CodeValue == "85756007"
        assert bone.SegmentedPropertyTypeCodeSequence[0].CodingSchemeDesignator == "SCT"
        assert "AnatomicRegionSequence" not in bone
        assert seg.PatientID == "FAKE-0001"
        source_series = read(volume.dicom_files[0]).SeriesInstanceUID
        assert seg.ReferencedSeriesSequence[0].SeriesInstanceUID == source_series

    def test_segment_pixels_match_the_painted_masks(self, project, volume):
        out = os.path.join(project, "out_pixels")
        shutil.rmtree(out, ignore_errors=True)
        (path,) = export_registry.export("dicom_seg", context(project, volume), out).files_written
        parsed = hd.seg.Segmentation.from_dataset(read(path))
        uids = [read(f).SOPInstanceUID for f in volume.dicom_files]
        for number, label in ((1, "Lesion"), (2, "Bone")):
            pixels = parsed.get_pixels_by_source_instance(
                source_sop_instance_uids=uids, segment_numbers=[number],
                combine_segments=False)[..., 0].astype(bool)
            expected = vol.to_source_order(volume, masks(volume)[label]).transpose(2, 1, 0)
            assert np.array_equal(pixels, expected), label

    def test_dicom_seg_writes_no_report(self, project, volume):
        out = os.path.join(project, "out_noreport")
        shutil.rmtree(out, ignore_errors=True)
        result = export_registry.export("dicom_seg", context(project, volume), out)
        assert not any(p.endswith("__sr.dcm") for p in result.files_written)


class TestMeasurementReport:
    @pytest.fixture(scope="class")
    def pair(self, project, volume):
        out = os.path.join(project, "out_sr")
        shutil.rmtree(out, ignore_errors=True)
        result = export_registry.export("dicom_sr", context(project, volume), out)
        assert result.success, result.errors
        seg_path, sr_path = result.files_written
        assert sr_path == seg_path[:-4] + "__sr.dcm"
        assert result.stats == {"num_files": 2, "num_reports": 1}
        return read(seg_path), read(sr_path), sr_path

    def test_the_report_is_tid_1500_in_a_comprehensive_3d_sr(self, pair):
        _seg, sr, _path = pair
        assert sr.SOPClassUID == "1.2.840.10008.5.1.4.1.1.88.34"      # Comprehensive 3D SR
        assert sr.ContentTemplateSequence[0].TemplateIdentifier == "1500"
        assert sr.ConceptNameCodeSequence[0].CodeValue == "126000"     # Imaging Measurement Report
        assert sr.CompletionFlag == "COMPLETE" and sr.VerificationFlag == "UNVERIFIED"
        assert sr.PatientID == "FAKE-0001"

    def test_one_volume_per_segment_referencing_the_seg(self, pair):
        seg, _sr, path = pair
        report = hd.sr.srread(path)
        groups = report.content.get_volumetric_roi_measurement_groups()
        assert len(groups) == 2
        by_id = {g.tracking_identifier: g for g in groups}
        assert set(by_id) == {"Lesion", "Bone"}
        for label, voxels, number in (("Lesion", 60, 1), ("Bone", 4, 2)):
            group = by_id[label]
            (measurement,) = group.get_measurements()
            assert measurement.name.value == "118565006"                   # SCT Volume
            assert measurement.unit.value == "mm3"
            assert measurement.value == pytest.approx(voxels * VOXEL_MM3, rel=1e-6)
            ref = group.referenced_segment
            assert ref.referenced_sop_instance_uid == seg.SOPInstanceUID
            assert ref.referenced_segment_numbers == [number]
        assert by_id["Lesion"].finding_type.value == "52988006"
        assert by_id["Bone"].finding_type.value == "85756007"
        # The SR's tracking UID is the SEG segment's, so the two link up.
        seg_uid = {s.SegmentLabel: s.TrackingUID for s in seg.SegmentSequence}
        assert by_id["Lesion"].tracking_uid == seg_uid["Lesion"]

    def test_the_annotator_is_the_person_observer(self, pair):
        _seg, _sr, path = pair
        report = hd.sr.srread(path)
        (observer,) = report.content.get_observer_contexts()
        assert observer.observer_type.value == "121006"                    # DCM Person
        attributes = observer.observer_identifying_attributes
        assert str(attributes.name) == "ada^"
        assert attributes.login_name == "ada"

    def test_the_seg_and_source_images_are_the_evidence(self, pair, volume):
        seg, sr, _path = pair
        evidence = {item.ReferencedSOPInstanceUID
                    for study in sr.CurrentRequestedProcedureEvidenceSequence
                    for series in study.ReferencedSeriesSequence
                    for item in series.ReferencedSOPSequence}
        sources = {read(f).SOPInstanceUID for f in volume.dicom_files}
        assert seg.SOPInstanceUID in evidence and sources <= evidence

    def test_a_username_that_is_not_a_person_name_is_made_one(self):
        assert vm.person_name("x^y=z\\w") == "x_y_z_w^"
        assert vm.person_name("") == "anonymous^"


class TestConfigCodes:
    def _scheme(self, dicom):
        return {**SCHEME, "labels": [{"name": "Lesion", "dicom": dicom}]}

    def test_valid_codes_pass(self):
        validate_single_annotation_scheme(SCHEME, "annotation_schemes[0]")

    @pytest.mark.parametrize("dicom, message", [
        ({"type": {"code": "52988006", "scheme": "SCT"}}, r"type\.meaning is required"),
        ({"typ": {"code": "1", "scheme": "SCT", "meaning": "x"}}, "unknown keys"),
        ({"type": {"code": "1", "scheme": "SCT", "meaning": "x", "extra": 1}}, "unknown keys"),
        ({"type": {"code": "1", "scheme": "S" * 17, "meaning": "x"}}, "at most 16"),
        ("SCT:52988006", "must be a mapping"),
    ])
    def test_a_malformed_code_is_a_startup_error_naming_the_label(self, dicom, message):
        with pytest.raises(ConfigValidationError, match=message) as info:
            validate_single_annotation_scheme(self._scheme(dicom), "annotation_schemes[0]")
        assert "Lesion" in str(info.value)

    def test_partial_codes_keep_the_default_category(self):
        from potato.server_utils.schemas.volume_annotation import dicom_codes
        codes = dicom_codes({"name": "L", "dicom": {"type": LESION["type"]}})
        assert codes["type"]["code"] == "52988006"
        assert codes["category"] == {"code": "85756007", "scheme": "SCT", "meaning": "Tissue"}

    def test_the_generator_still_renders_with_codes(self):
        from potato.server_utils.schemas.volume_annotation import generate_volume_annotation_layout
        html, _keys = generate_volume_annotation_layout(SCHEME)
        assert "VolumeAnnotationManager" in html and "52988006" not in html

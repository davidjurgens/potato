"""
3D volumes (potato/media/volumes.py, volume_masks.py) against the synthetic
CT phantom from examples/image/ct-volume, regenerated into a test directory.

The phantom is written as a DICOM series and as NIfTI from one array, so the
two readers must agree voxel for voxel; its lesion is a known sphere, so an
RTSTRUCT import and an interpolation can be scored against the truth.
"""

import importlib.util
import io
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pydicom")
nib = pytest.importorskip("nibabel")

from potato.media import volume_masks as vm  # noqa: E402
from potato.media import volumes as vol  # noqa: E402

GENERATOR = Path("examples/image/ct-volume/generate_volume.py")


@pytest.fixture(scope="module")
def gen(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("generate_volume", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE = tmp_path_factory.mktemp("phantom")
    module.main()
    return module


@pytest.fixture(scope="module")
def dicom(gen):
    return vol.read_volume(str(gen.HERE / "media" / "phantom_dicom"))


@pytest.fixture(scope="module")
def nifti(gen):
    return vol.read_volume(str(gen.HERE / "media" / "phantom.nii.gz"))


@pytest.fixture(scope="module")
def lesion_truth(gen):
    z, y, x = np.mgrid[0:gen.SLICES, 0:gen.ROWS, 0:gen.COLS].astype(float)
    cx, cy, cz = gen.LESION_CENTER
    source = np.sqrt(((x - cx) * gen.PIXEL) ** 2 + ((y - cy) * gen.PIXEL) ** 2
                     + ((z - cz) * gen.THICKNESS) ** 2) <= gen.LESION_RADIUS
    image = nib.Nifti1Image(source.transpose(2, 1, 0).astype(np.uint8),
                            np.diag([-1.0, -1.0, 1.0, 1.0]) @ gen.lps_affine())
    return np.asanyarray(nib.as_closest_canonical(image).dataobj).astype(bool)


class TestReading:
    def test_dicom_and_nifti_of_one_phantom_agree(self, dicom, nifti):
        assert dicom.shape == nifti.shape == (96, 80, 48)
        assert np.allclose(dicom.affine, nifti.affine)
        assert np.allclose(dicom.data, nifti.data)
        assert dicom.spacing == pytest.approx((0.8, 0.8, 2.5))

    def test_canonical_axes_point_right_anterior_superior(self, dicom):
        # RAS+: each index step moves toward R, A and S respectively.
        directions = dicom.affine[:3, :3]
        assert directions[0, 0] > 0 and directions[1, 1] > 0 and directions[2, 2] > 0

    def test_the_lesion_lands_where_the_generator_put_it(self, dicom, gen):
        # DICOM column 60 (toward patient Left) is canonical i = 95 - 60.
        center = np.argwhere(dicom.data > 100).mean(axis=0)   # lesion + bone
        hits = np.argwhere(np.abs(dicom.data - 120) < 20)
        lesion = hits[np.linalg.norm(hits - [35, 49, 24], axis=1) < 6].mean(axis=0)
        assert lesion == pytest.approx([35, 49, 24], abs=1.0)
        assert center is not None

    def test_a_directory_of_two_series_is_refused(self, gen, tmp_path):
        import shutil
        series = gen.HERE / "media" / "phantom_dicom"
        mixed = tmp_path / "mixed"
        shutil.copytree(series, mixed)
        import pydicom
        other = pydicom.dcmread(next(mixed.glob("*.dcm")))
        other.SeriesInstanceUID = "1.2.3.4"
        other.save_as(mixed / "zzz.dcm")
        with pytest.raises(vol.VolumeError, match="2 DICOM series"):
            vol.read_volume(str(mixed))

    def test_a_missing_slice_is_refused(self, gen, tmp_path):
        import shutil
        gappy = tmp_path / "gappy"
        shutil.copytree(gen.HERE / "media" / "phantom_dicom", gappy)
        (gappy / "slice_020.dcm").unlink()
        with pytest.raises(vol.VolumeError, match="not evenly spaced"):
            vol.read_volume(str(gappy))

    def test_other_files_are_refused_with_the_reason(self, tmp_path):
        path = tmp_path / "scan.png"
        path.write_bytes(b"\x89PNG")
        with pytest.raises(vol.VolumeError, match="not a NIfTI"):
            vol.read_volume(str(path))


class TestRefusals:
    def _series(self, gen, tmp_path, edit):
        import pydicom
        import shutil
        folder = tmp_path / "series"
        shutil.copytree(gen.HERE / "media" / "phantom_dicom", folder)
        for n, path in enumerate(sorted(folder.glob("*.dcm"))):
            ds = pydicom.dcmread(path)
            edit(n, ds)
            ds.save_as(path)
        return str(folder)

    def test_burned_in_annotation_is_refused(self, gen, tmp_path):
        def edit(n, ds):
            if n == 3:
                ds.BurnedInAnnotation = "YES"
        with pytest.raises(vol.VolumeError, match="BurnedInAnnotation"):
            vol.read_volume(self._series(gen, tmp_path, edit))

    def test_a_scout_with_another_orientation_is_named(self, gen, tmp_path):
        def edit(n, ds):
            if n == 0:
                ds.ImageOrientationPatient = ["1", "0", "0", "0", "0", "-1"]
        with pytest.raises(vol.VolumeError, match="same orientation"):
            vol.read_volume(self._series(gen, tmp_path, edit))

    def test_gantry_tilt_is_refused_with_the_fix(self, gen, tmp_path):
        # Each slice shifted along y as z grows: a 10 degree tilt.
        import math
        def edit(n, ds):
            x, y, z = (float(v) for v in ds.ImagePositionPatient)
            ds.ImagePositionPatient = [f"{x:.4f}", f"{y + n * gen.THICKNESS * math.tan(math.radians(10)):.4f}",
                                       f"{z:.4f}"]
        with pytest.raises(vol.VolumeError, match="gantry tilt.*dcm2niix"):
            vol.read_volume(self._series(gen, tmp_path, edit))


class TestRawFiles:
    def test_dicom_and_nifti_are_recognised(self, gen, tmp_path):
        import shutil
        dcm = next((gen.HERE / "media" / "phantom_dicom").glob("*.dcm"))
        bare = tmp_path / "IM0001"                       # no suffix
        shutil.copy(dcm, bare)
        assert vol.is_raw_medical_file(str(bare))
        assert vol.is_raw_medical_file(str(gen.HERE / "media" / "phantom.nii.gz"))
        assert vol.is_raw_medical_file(str(gen.HERE / "media" / "phantom_rtstruct.dcm"))
        png = tmp_path / "a.png"
        png.write_bytes(b"\x89PNG" + b"\0" * 400)
        assert not vol.is_raw_medical_file(str(png))


class TestViews:
    @pytest.mark.parametrize("axis,index,voxel,cell", [
        # (i, j, k) -> (row, column) per the mapping in volumes.py
        ("axial", 10, (3, 5, 10), (80 - 1 - 5, 96 - 1 - 3)),
        ("coronal", 5, (3, 5, 10), (48 - 1 - 10, 96 - 1 - 3)),
        ("sagittal", 3, (3, 5, 10), (48 - 1 - 10, 80 - 1 - 5)),
    ])
    def test_each_view_puts_a_voxel_where_the_client_expects_it(
            self, dicom, axis, index, voxel, cell):
        marked = vol.Volume(data=np.zeros(dicom.shape), affine=dicom.affine,
                            spacing=dicom.spacing, kind="test")
        marked.data[voxel] = 1
        plane = vol.view_slice(marked, axis, index)
        assert tuple(np.argwhere(plane == 1)[0]) == cell

    def test_out_of_range_slices_are_refused(self, dicom):
        with pytest.raises(vol.VolumeError):
            vol.view_slice(dicom, "axial", 48)

    def test_the_png_is_windowed(self, dicom):
        from PIL import Image
        png = vol.render_png(dicom, "axial", 24, center=40, width=400)
        image = np.asarray(Image.open(io.BytesIO(png)))
        assert image.shape == (80, 96)
        assert image.min() == 0                    # air, below the window
        assert 100 < np.median(image[image > 0]) < 160   # soft tissue, mid-grey

    def test_presets_come_from_the_file_and_the_modality(self, dicom, nifti):
        names = [w["name"] for w in vol.windows(dicom)]
        assert names[0] == "From file" and "Lung" in names and names[-1] == "Auto"
        assert [w["name"] for w in vol.windows(nifti)] == ["Auto"]


class TestPatientTags:
    def test_identifying_tags_are_withheld_unless_allowed(self, dicom):
        shown = vol.header_tags(dicom, ["Modality", "PatientName", "PatientBirthDate",
                                        "SeriesDescription", "BodyPartExamined"])
        assert shown == {"Modality": "CT", "BodyPartExamined": "CHEST"}
        allowed = vol.header_tags(dicom, ["SeriesDescription"], ["SeriesDescription"])
        assert allowed == {"SeriesDescription": "Synthetic chest phantom"}

    def test_a_tag_not_asked_for_is_never_shown(self, dicom):
        assert vol.header_tags(dicom, [], ["PatientName"]) == {}

    def test_nifti_has_no_header_to_show(self, nifti):
        assert vol.header_tags(nifti, ["Modality"]) == {}


class TestMasks:
    def test_rle_round_trips(self):
        rng = np.random.default_rng(3)
        for shape in [(1, 1), (5, 7), (80, 96)]:
            mask = rng.random(shape) > 0.6
            assert np.array_equal(vm.rle_decode(vm.rle_encode(mask), shape), mask)
        full = np.ones((4, 4), bool)
        assert vm.rle_encode(full) == [0, 16]

    def test_rle_refuses_runs_past_the_slice(self):
        with pytest.raises(ValueError):
            vm.rle_decode([3, 40], (4, 4))

    def test_rtstruct_import_matches_the_sphere(self, dicom, gen, lesion_truth):
        rois = vm.rtstruct_masks(str(gen.HERE / "media" / "phantom_rtstruct.dcm"), dicom)
        assert set(rois) == {"Lesion"}
        assert vm.dice(rois["Lesion"], lesion_truth) > 0.92

    def test_interpolation_rebuilds_the_skipped_slices(self, lesion_truth):
        # The sphere spans axial slices 21..27. Paint the two ends and the
        # middle, as an annotator would: blending the two small end caps alone
        # makes a narrow cylinder that misses the sphere's widest part.
        painted = {k: lesion_truth[:, :, k].T for k in (21, 24, 27)}
        filled = vm.interpolate_slices(painted)
        assert sorted(filled) == [22, 23, 25, 26]
        rebuilt = np.zeros_like(lesion_truth)
        for k, plane in {**painted, **filled}.items():
            rebuilt[:, :, k] = plane.T
        assert vm.dice(rebuilt, lesion_truth) > 0.85
        for k in painted:                                    # never rewritten
            assert k not in filled
        assert vm.interpolate_slices({21: painted[21]}) == {}

    def test_outlines_that_do_not_overlap_are_reported(self):
        a = np.zeros((40, 40), bool)
        a[2:9, 2:9] = True
        b = np.zeros((40, 40), bool)
        b[30:37, 30:37] = True
        slices = {0: a, 10: b}
        filled = vm.interpolate_slices(slices)
        gaps = vm.interpolation_gaps(slices, filled)
        assert gaps and gaps[0]["from"] == 0 and gaps[0]["to"] == 10
        assert set(range(3, 8)) <= set(gaps[0]["empty"])
        overlap = {0: a, 10: np.roll(a, 1, axis=1)}
        assert vm.interpolation_gaps(overlap, vm.interpolate_slices(overlap)) == []

    def test_dice(self):
        a = np.zeros((4, 4, 4), bool)
        b = a.copy()
        a[0:2] = True
        b[1:3] = True
        assert vm.dice(a, b) == pytest.approx(0.5)
        assert vm.dice(np.zeros(3, bool), np.zeros(3, bool)) is None


class TestExport:
    def test_nifti_labels_keep_the_source_geometry(self, dicom, lesion_truth, tmp_path):
        labels = lesion_truth.astype(np.uint8)
        path = tmp_path / "labels.nii.gz"
        path.write_bytes(vm.to_nifti_bytes(labels, dicom))
        image = nib.load(str(path))
        assert np.allclose(image.affine, dicom.source_affine)
        assert np.array_equal(np.asanyarray(nib.as_closest_canonical(image).dataobj), labels)

    def test_a_mask_goes_back_into_a_non_canonical_file_order(self, dicom, tmp_path):
        # An LPI-ordered NIfTI: canonical order differs from the file's.
        lpi = np.diag([-1.0, -1.0, -1.0, 1.0]) @ dicom.affine
        data = np.asarray(dicom.data)[::-1, ::-1, ::-1]
        lpi[:3, 3] = dicom.affine[:3, :3] @ (np.array(dicom.shape) - 1) + dicom.affine[:3, 3]
        source = tmp_path / "lpi.nii.gz"
        nib.save(nib.Nifti1Image(data.astype(np.float32), lpi), str(source))
        flipped = vol.read_volume(str(source))
        assert np.allclose(flipped.data, dicom.data)            # same canonical volume
        marker = np.zeros(flipped.shape, np.uint8)
        marker[3, 5, 10] = 1
        back = vol.to_source_order(flipped, marker)
        assert tuple(np.argwhere(back == 1)[0]) == (96 - 1 - 3, 80 - 1 - 5, 48 - 1 - 10)

    def test_dicom_seg_references_the_series(self, dicom, lesion_truth):
        pytest.importorskip("highdicom")
        import highdicom as hd
        import pydicom
        seg = vm.to_dicom_seg(["Lesion", "Empty"],
                              {"Lesion": lesion_truth, "Empty": np.zeros_like(lesion_truth)},
                              dicom, annotator="ada")
        buffer = io.BytesIO()
        seg.save_as(buffer)
        buffer.seek(0)
        dataset = pydicom.dcmread(buffer)
        assert [s.SegmentLabel for s in dataset.SegmentSequence] == ["Lesion"]
        assert dataset.ContentDescription == "Annotator: ada"
        parsed = hd.seg.Segmentation.from_dataset(dataset)
        sources = [pydicom.dcmread(f) for f in dicom.dicom_files]
        pixels = parsed.get_pixels_by_source_instance(
            source_sop_instance_uids=[s.SOPInstanceUID for s in sources],
            segment_numbers=[1], combine_segments=False)[..., 0].astype(bool)
        assert np.array_equal(pixels, vol.to_source_order(dicom, lesion_truth).transpose(2, 1, 0))


class TestAgreement:
    def test_volume_report_scores_labels_by_dice(self, lesion_truth):
        from potato.server_utils.iaa.volume_agreement import volume_report
        shape = list(lesion_truth.shape)
        shifted = np.roll(lesion_truth, 2, axis=0)
        a = {"shape": shape, "masks": {"Lesion": vm.masks_from_volume(lesion_truth)}}
        b = {"shape": shape, "masks": {"Lesion": vm.masks_from_volume(shifted)}}
        report = volume_report({"item": {"u1": a, "u2": {"_data": __import__("json").dumps(b)}}},
                               {"labels": ["Lesion", "Bone"]})
        expected = vm.dice(lesion_truth, shifted)
        assert report["dice_by_label"]["Lesion"] == pytest.approx(expected, abs=1e-4)
        assert report["dice_by_label"]["Bone"] is None       # nobody painted it
        assert report["mean_dice"] == pytest.approx(expected, abs=1e-4)
        assert report["n_items"] == 1

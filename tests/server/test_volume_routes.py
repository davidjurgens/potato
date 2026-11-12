"""
Volume routes and the volume_annotation schema on a real server, with the
synthetic CT phantom written into the test project's media directory.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest
import requests

pytest.importorskip("pydicom")
pytest.importorskip("nibabel")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

GENERATOR = Path("examples/image/ct-volume/generate_volume.py")
SCHEME = {
    "annotation_type": "volume_annotation", "name": "ct", "description": "Segment",
    "labels": ["Lesion", "Bone"], "source_field": "volume",
    "prefill_rtstruct_field": "rtstruct",
    "display_tags": ["Modality", "PatientName", "SeriesDescription"],
    "allow_identifying_tags": ["SeriesDescription"],
}


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("volume_routes")
    spec = importlib.util.spec_from_file_location("generate_volume", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.HERE = Path(test_dir)
    gen.main()
    data = create_test_data_file(test_dir, [
        {"id": "dicom", "volume": "phantom_dicom", "rtstruct": "phantom_rtstruct.dcm",
         "text": "DICOM"},
        {"id": "nifti", "volume": "phantom.nii.gz", "text": "NIfTI"},
    ])
    config = create_test_config(test_dir, [SCHEME], data_files=[data],
                                require_password=False,
                                additional_config={"media_directory": "media"})
    srv = FlaskTestServer(config_file=config)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def _signed_in(server, user):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": user, "pass": "p"}, timeout=10)
    s.post(f"{server.base_url}/auth", data={"email": user, "pass": "p"}, timeout=10)
    return s


def test_info_shows_only_the_tags_the_schema_allows(server):
    s = _signed_in(server, "tags")
    r = s.get(f"{server.base_url}/media/volume/phantom_dicom",
              params={"info": 1, "schema": "ct"}, timeout=20)
    assert r.status_code == 200
    info = r.json()
    assert info["shape"] == [96, 80, 48] and info["kind"] == "dicom"
    assert info["tags"] == {"Modality": "CT", "SeriesDescription": "Synthetic chest phantom"}
    # Another schema name, or none, unlocks nothing.
    bare = s.get(f"{server.base_url}/media/volume/phantom_dicom",
                 params={"info": 1, "schema": "nope"}, timeout=20).json()
    assert bare["tags"] == {}


def test_a_slice_is_a_png(server):
    r = _signed_in(server, "png").get(f"{server.base_url}/media/volume/phantom.nii.gz",
                     params={"axis": "coronal", "index": 40, "wc": 40, "ww": 400}, timeout=20)
    assert r.status_code == 200 and r.headers["Content-Type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("params,status", [
    ({"axis": "oblique"}, 400),
    ({"axis": "axial", "index": 999}, 400),
])
def test_bad_slice_requests_are_refused(server, params, status):
    r = _signed_in(server, "bad").get(f"{server.base_url}/media/volume/phantom_dicom",
                                      params=params, timeout=20)
    assert r.status_code == status


def test_paths_outside_the_media_directory_are_refused(server):
    r = _signed_in(server, "trav").get(f"{server.base_url}/media/volume/..%2F..%2Fetc",
                                       params={"info": 1}, timeout=20)
    assert r.status_code in (403, 404)


@pytest.mark.parametrize("path", [
    "phantom_dicom/slice_000.dcm",      # the patient header, unfiltered
    "phantom_rtstruct.dcm",
    "phantom.nii.gz",
])
def test_raw_medical_files_are_not_served(server, path):
    # The volume routes filter the header to display_tags; the raw file would
    # hand all of it out. Refused signed in or not.
    assert requests.get(f"{server.base_url}/media/{path}", timeout=10).status_code == 403
    signed = _signed_in(server, "raw")
    r = signed.get(f"{server.base_url}/media/{path}", timeout=10)
    assert r.status_code == 403
    assert b"PHANTOM-0001" not in r.content


def test_volume_views_need_a_sign_in(server):
    anon = requests.Session()
    for params in ({"info": 1, "schema": "ct"}, {"axis": "axial", "index": 0}):
        assert anon.get(f"{server.base_url}/media/volume/phantom_dicom", params=params,
                        timeout=10).status_code == 401


def test_interpolation_and_prefill_need_a_sign_in(server):
    anon = requests.Session()
    assert anon.post(f"{server.base_url}/media/volume-tools/interpolate",
                     json={"shape": [4, 4, 4], "slices": {}}, timeout=10).status_code == 401
    assert anon.get(f"{server.base_url}/media/volume-tools/prefill",
                    params={"volume": "phantom_dicom", "rtstruct": "phantom_rtstruct.dcm",
                            "schema": "ct"}, timeout=10).status_code == 401


def test_prefill_maps_rois_to_labels(server):
    s = _signed_in(server, "prefiller")
    r = s.get(f"{server.base_url}/media/volume-tools/prefill",
              params={"volume": "phantom_dicom", "rtstruct": "phantom_rtstruct.dcm",
                      "schema": "ct"}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body["masks"]) == ["Lesion"] and body["unmatched"] == []
    assert sorted(int(k) for k in body["masks"]["Lesion"]) == list(range(21, 28))


def test_interpolation_names_the_gaps_it_cannot_fill(server):
    from potato.media.volume_masks import rle_encode
    import numpy as np
    s = _signed_in(server, "gaps")
    a = np.zeros((40, 40), bool)
    a[2:9, 2:9] = True
    b = np.zeros((40, 40), bool)
    b[30:37, 30:37] = True                       # far from a: no overlap
    r = s.post(f"{server.base_url}/media/volume-tools/interpolate",
               json={"shape": [40, 40, 11], "slices": {"0": rle_encode(a), "10": rle_encode(b)}},
               timeout=20)
    gaps = r.json()["gaps"]
    assert len(gaps) == 1 and gaps[0]["from"] == 0 and gaps[0]["to"] == 10
    assert 5 in gaps[0]["empty"]


def test_interpolation_fills_between_slices(server):
    from potato.media.volume_masks import rle_encode
    import numpy as np
    s = _signed_in(server, "interp")
    plane = np.zeros((8, 8), bool)
    plane[2:6, 2:6] = True
    r = s.post(f"{server.base_url}/media/volume-tools/interpolate",
               json={"shape": [8, 8, 10], "slices": {"2": rle_encode(plane),
                                                      "6": rle_encode(plane)}}, timeout=20)
    assert r.status_code == 200
    assert sorted(int(k) for k in r.json()["filled"]) == [3, 4, 5]


def test_an_oversized_interpolation_is_refused(server):
    s = _signed_in(server, "big")
    r = s.post(f"{server.base_url}/media/volume-tools/interpolate",
               json={"shape": [10000, 10, 10], "slices": {}}, timeout=10)
    assert r.status_code == 400


def test_two_annotators_get_a_dice_report(server):
    from potato.media.volume_masks import rle_encode
    import numpy as np
    plane = np.zeros((80, 96), bool)
    plane[30:40, 30:40] = True
    shifted = np.roll(plane, 2, axis=1)
    for user, mask in (("vol_a", plane), ("vol_b", shifted)):
        s = _signed_in(server, user)
        s.get(f"{server.base_url}/annotate", timeout=20)
        value = {"volume": "phantom_dicom", "shape": [96, 80, 48], "labels": ["Lesion", "Bone"],
                 "masks": {"Lesion": {"24": rle_encode(mask)}}, "shapes": []}
        r = s.post(f"{server.base_url}/updateinstance", json={
            "instance_id": "dicom", "annotations": {"ct:::_data": json.dumps(value)},
            "span_annotations": []}, timeout=20)
        assert r.status_code == 200, r.text
    # The stored values, read back the way the agreement report reads them.
    from potato.server_utils.iaa.dispatcher import SchemaKind, _gather_raw, classify_schema
    from potato.server_utils.iaa.volume_agreement import volume_report
    from potato.user_state_management import get_user_state_manager
    usm = get_user_state_manager()
    states = {u: usm.get_user_state(u) for u in ("vol_a", "vol_b")}
    assert classify_schema(SCHEME) == SchemaKind.VOLUME
    metrics = volume_report(_gather_raw(["dicom"], states, "ct"), SCHEME)
    # Two 10x10 squares two columns apart: Dice = 2*80/200.
    assert metrics["dice_by_label"]["Lesion"] == pytest.approx(0.8, abs=1e-6)
    assert metrics["n_items"] == 1

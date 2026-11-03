"""Video tracks: targets from keyframes, association, MOTA/IDF1, prelabels,
and video-track end to end on synthetic videos of a moving square."""

import json
import os

import pytest

from potato.training import registry, tracking
from potato.training.dataset import build_bundle
from potato.training.evaluation import HEADLINE, score_split
from potato.training.events import EXIT_OK
from tests.unit.test_training_trainers import _context, _predictions, _run, _spec

HAVE = __import__("importlib").util.find_spec

SCHEME = {"annotation_type": "video_annotation", "name": "trk", "description": "",
          "mode": "tracking", "labels": ["box"], "video_fps": 10}


def stored(tracks, fps=10, duration=4.0):
    return {"_data": json.dumps({"video_metadata": {"fps": fps, "duration": duration},
                                 "segments": [], "tracks": tracks})}


def track(tid, label, frames):
    """A track from ``{frame: (x, y, w, h)}`` normalized boxes."""
    return {"id": tid, "label": label, "keyframes": {
        str(f): {"frame": f, "type": "bbox", "bbox": {"x": 999, "y": 999, "width": 1, "height": 1},
                 "bboxNorm": dict(zip(("x", "y", "width", "height"), box))}
        for f, box in frames.items()}}


def test_tracks_are_targets_by_normalized_box_and_interpolate():
    target = tracking.track_target(stored({"t1": track("t1", "box", {
        0: (0.1, 0.1, 0.2, 0.2), 10: (0.5, 0.1, 0.2, 0.2)})}))
    assert target["fps"] == 10 and len(target["tracks"]) == 1
    (t,) = target["tracks"]
    # The canvas box (999, 999) is the annotator's screen; the target ignores it.
    assert t["keyframes"] == [[0, 0.1, 0.1, 0.2, 0.2], [10, 0.5, 0.1, 0.2, 0.2]]
    assert tracking.box_at(t, 5) == pytest.approx([0.3, 0.1, 0.2, 0.2])
    assert tracking.box_at(t, 11) is None
    assert tracking.track_target(stored({})) is None


def test_the_tracking_kind_is_by_mode():
    assert registry.kind_of_schema(SCHEME) == "track"
    assert registry.kind_of_schema(dict(SCHEME, mode="segment")) == "temporal"
    assert [t.name for t in registry.trainers_for_schema(SCHEME, "video")] == ["video-track"]


def test_association_follows_a_box_and_ends_a_lost_track():
    moving = [(f, [{"label": "box", "box": [0.1 + 0.02 * f, 0.1, 0.2, 0.2], "score": 0.9}])
              for f in range(10)]
    # Gone for 4 frames, then back: more than max_age 2, so a new track.
    moving += [(f, []) for f in range(10, 14)]
    moving += [(14, [{"label": "box", "box": [0.38, 0.1, 0.2, 0.2], "score": 0.9}])]
    tracks = tracking.associate(moving, match_iou=0.3, max_age=2, new_track_score=0.5)
    assert sorted(len(t["keyframes"]) for t in tracks) == [1, 10]
    # A weak detection nobody continues does not start a track.
    assert tracking.associate([(0, [{"label": "box", "box": [0, 0, .1, .1], "score": 0.2}])]) == []


def test_mota_and_idf1_against_the_annotated_tracks():
    gold = tracking.track_target(stored({
        "a": track("a", "box", {0: (0.0, 0.0, 0.2, 0.2), 20: (0.0, 0.0, 0.2, 0.2)}),
        "b": track("b", "box", {0: (0.6, 0.6, 0.2, 0.2), 20: (0.6, 0.6, 0.2, 0.2)})}))
    rows = [{"instance_id": "v", "targets": {"t": gold}}]
    same = tracking.track_payload([
        {"label": "box", "keyframes": [[0, 0.0, 0.0, 0.2, 0.2, 0.9], [20, 0.0, 0.0, 0.2, 0.2, 0.9]]},
        {"label": "box", "keyframes": [[0, 0.6, 0.6, 0.2, 0.2, 0.9], [20, 0.6, 0.6, 0.2, 0.2, 0.9]]}],
        10, 2.0, None, None)
    metrics, _ = score_split(rows, {("v", "t"): same}, "t", "track")
    assert metrics[HEADLINE["track"]] == 1.0 and metrics["mota"] == 1.0
    # Ids swapped halfway: every frame still has both boxes, identity does not.
    swapped = tracking.track_payload([
        {"label": "box", "keyframes": [[0, 0.0, 0.0, 0.2, 0.2, 0.9], [9, 0.0, 0.0, 0.2, 0.2, 0.9],
                                       [10, 0.6, 0.6, 0.2, 0.2, 0.9], [20, 0.6, 0.6, 0.2, 0.2, 0.9]]},
        {"label": "box", "keyframes": [[0, 0.6, 0.6, 0.2, 0.2, 0.9], [9, 0.6, 0.6, 0.2, 0.2, 0.9],
                                       [10, 0.0, 0.0, 0.2, 0.2, 0.9], [20, 0.0, 0.0, 0.2, 0.2, 0.9]]}],
        10, 2.0, None, None)
    metrics, _ = score_split(rows, {("v", "t"): swapped}, "t", "track")
    assert metrics["idf1"] < 1.0 and metrics["id_switches"] >= 2
    missed, _ = score_split(rows, {}, "t", "track")
    assert missed["mota"] == 0.0 and missed["idf1"] == 0.0


def test_track_prelabels_keep_boxes_on_the_picture_with_scheme_labels():
    from potato.server_utils.prelabel_values import prelabel_values
    payload = {"video_metadata": {"duration": 4.0}, "tracks": {
        "t1": track("t1", "box", {0: (0.1, 0.1, 0.2, 0.2), 5: (0.9, 0.1, 0.2, 0.2)}),
        "t2": track("t2", "car", {0: (0.1, 0.1, 0.2, 0.2)})}}
    (value,) = prelabel_values(SCHEME, payload).values()
    kept = json.loads(value)["tracks"]
    assert list(kept) == ["t1"] and list(kept["t1"]["keyframes"]) == ["0"]
    # The canvas box is not sent: the page computes it in its own pixels.
    assert "bbox" not in kept["t1"]["keyframes"]["0"]
    assert prelabel_values(dict(SCHEME, mode="segment"), payload) is None


def square_video(path, frames=40, fps=10, size=96, start=8, speed=1.5):
    import cv2
    import numpy
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (size, size))
    for f in range(frames):
        image = numpy.full((size, size, 3), 40, dtype="uint8")
        x = int(start + speed * f)
        image[30:54, x:x + 24] = (230, 230, 230)
        writer.write(image)
    writer.release()
    return [(0, start / size), (frames - 1, (start + speed * (frames - 1)) / size)]


def video_project(tmp, n=6):
    os.makedirs(tmp / "media", exist_ok=True)
    items, annotations = {}, []
    for i in range(n):
        iid = "v%d" % i
        (f0, x0), (f1, x1) = square_video(tmp / "media" / ("v%d.avi" % i), start=4 + i * 3)
        items[iid] = {"id": iid, "video": "media/v%d.avi" % i}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {"trk": stored({
            "t1": track("t1", "box", {f0: (x0, 30 / 96, 24 / 96, 24 / 96),
                                      f1: (x1, 30 / 96, 24 / 96, 24 / 96)})})}})
    scheme = dict(SCHEME, source_field="video")
    return _context(tmp, [scheme], items, annotations)


@pytest.mark.skipif(not all(HAVE(m) for m in ("torch", "torchvision", "cv2")),
                    reason="torch/torchvision/cv2 absent")
def test_video_track_trains_and_writes_tracks_back(tmp_path):
    config, context = video_project(tmp_path, n=6)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["trk"], split_seed=4)
    spec = _spec(tmp_path, config, bundle, "video-track", "trk", {
        "pretrained": False, "epochs": 1, "min_size": 64, "batch_size": 4, "min_instances": 2,
        "score_threshold": 0.0, "max_detections": 2, "frame_fps": 2.0,
        "new_track_score": 0.0})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    assert metrics["heldout_metric"].endswith("idf1")
    assert metrics["n_train_frames"] > 0
    record = _predictions(spec)[0]
    payload = record["payload"]
    kf = next(iter(next(iter(payload["tracks"].values()))["keyframes"].values()))
    assert set(kf["bboxNorm"]) == {"x", "y", "width", "height"} and kf["source"] == "ai"
    assert payload["video_metadata"]["duration"] == pytest.approx(4.0, abs=0.2)


@pytest.mark.skipif(not all(HAVE(m) for m in ("torch", "torchvision", "cv2")),
                    reason="torch/torchvision/cv2 absent")
def test_a_video_opencv_cannot_read_is_left_out_not_the_run(tmp_path):
    """Audit 105 B5: one unreadable video raised out of the fit."""
    config, context = video_project(tmp_path, n=6)
    (tmp_path / "media" / "v1.avi").write_bytes(b"not a video")
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["trk"], split_seed=4)
    spec = _spec(tmp_path, config, bundle, "video-track", "trk", {
        "pretrained": False, "epochs": 1, "min_size": 64, "batch_size": 4, "min_instances": 2,
        "score_threshold": 0.0, "max_detections": 2, "frame_fps": 2.0, "new_track_score": 0.0})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert any("could not read" in e.get("msg", "") or "Left out v1" in e.get("msg", "")
               for e in report.of_type("log"))

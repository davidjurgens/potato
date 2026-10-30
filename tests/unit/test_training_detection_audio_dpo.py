"""Detection, audio segment tagging and DPO trainers, their bundle targets,
their held-out scores, and the segments exporter.

As in test_training_trainers.py, every model is built on the spot and runs on
the CPU, so nothing downloads. The detection data is coloured squares on a
grey background, the audio is beeps in noise, and the preference data prefers
the polite response: easy enough that a trainer which cannot learn them has a
broken loop.
"""

import json
import math
import os
import random
import types

import pytest

from potato.training import registry
from potato.training.base import SchemaSpec
from potato.training.dataset import build_bundle
from potato.training.evaluation import score_predictions, score_split
from potato.training.events import EXIT_CANCELLED, EXIT_OK
from tests.unit.test_training_trainers import (_context, _predictions, _run,
                                               _spec)

HAVE = __import__("importlib").util.find_spec
needs_torch = pytest.mark.skipif(not (HAVE("torch") and HAVE("transformers")),
                                 reason="torch/transformers absent")


# ------------------------------------------------------------------ data

def square_images(directory, n, seed=0):
    """Grey images with one or two red or blue squares, and their boxes in
    the image widget's normalized shape."""
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    os.makedirs(directory, exist_ok=True)
    out = []
    for i in range(n):
        width, height = 96, 72
        img = Image.new("RGB", (width, height), (200, 200, 200))
        draw = ImageDraw.Draw(img)
        objects = []
        for _ in range(rng.randint(1, 2)):
            label = rng.choice(["red", "blue"])
            size = rng.randint(14, 26)
            x, y = rng.randint(0, width - size), rng.randint(0, height - size)
            draw.rectangle([x, y, x + size - 1, y + size - 1],
                           fill=(220, 30, 30) if label == "red" else (30, 30, 220))
            objects.append({"type": "bbox", "label": label, "color": "",
                            "coordinates": {"x": x / width, "y": y / height,
                                            "width": size / width,
                                            "height": size / height}})
        path = os.path.join(directory, "img%03d.png" % i)
        img.save(path)
        out.append((path, objects))
    return out


def detection_project(tmp, n=30):
    images = square_images(str(tmp / "img"), n)
    items, annotations = {}, []
    for i, (path, objects) in enumerate(images):
        iid = "i%03d" % i
        items[iid] = {"id": iid, "image": os.path.relpath(path, tmp)}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {},
                            "image_annotations": {"boxes": objects}})
    scheme = {"annotation_type": "image_annotation", "name": "boxes",
              "description": "", "labels": ["red", "blue"], "tools": ["bbox"]}
    config, context = _context(tmp, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "image"
    return config, context, images


def audio_project(tmp, n=30):
    from tests.helpers.tiny_hf import beep_recordings

    recordings = beep_recordings(str(tmp / "audio"), n)
    items, annotations = {}, []
    for i, (path, segments) in enumerate(recordings):
        iid = "a%03d" % i
        items[iid] = {"id": iid, "audio": os.path.relpath(path, tmp)}
        annotations.append({"instance_id": iid, "user_id": "u", "labels": {
            "calls": {"_data": json.dumps({"segments": segments})}}})
    scheme = {"annotation_type": "audio_annotation", "name": "calls",
              "description": "", "labels": [{"name": "beep"}], "mode": "label"}
    config, context = _context(tmp, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "audio"
    return config, context, recordings


POLITE = ["thank you kindly friend", "please enjoy happily", "warm wishes kindly"]
RUDE = ["go away fool", "nobody cares idiot", "shut up loser"]


def preference_project(tmp, n=60, ties_every=10):
    rng = random.Random(0)
    items, annotations, texts = {}, [], ["Answer:", "tell", "me", "about"]
    for i in range(n):
        polite, rude = rng.choice(POLITE), rng.choice(RUDE)
        polite_first = rng.random() < 0.5
        pair = [polite, rude] if polite_first else [rude, polite]
        prompt = "tell me about %s" % rng.choice(["lunch", "music", "books"])
        iid = "p%03d" % i
        items[iid] = {"id": iid, "prompt": prompt, "responses": pair}
        choice = "A" if polite_first else "B"
        if ties_every and i % ties_every == ties_every - 1:
            choice = "tie"
        annotations.append({"instance_id": iid, "user_id": "u", "labels": {
            "pref": {"selection": choice}}})
        texts += pair + [prompt]
    scheme = {"annotation_type": "pairwise", "name": "pref",
              "description": "Which is better?", "mode": "binary",
              "items_key": "responses", "labels": ["A", "B"],
              "allow_tie": True}
    config, context = _context(tmp, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "responses"
    return config, context, texts


# --------------------------------------------------------------- bundles

class TestBundleTargets:
    def test_a_pairwise_answer_is_the_choice_not_the_key(self, tmp_path):
        """{"selection": "A"} trained as the label "selection" on every item."""
        _, context, _ = preference_project(tmp_path, n=12, ties_every=0)
        bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["pref"],
                                    split_spec={"train": 1.0})
        rows = list(bundle.read_split("train"))
        assert {r["targets"]["pref"] for r in rows} == {"A", "B"}
        assert bundle.labels("pref") == ["A", "B"]

    def test_pairwise_rows_carry_both_responses_and_the_prompt(self, tmp_path):
        _, context, _ = preference_project(tmp_path, n=4, ties_every=0)
        bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["pref"],
                                    split_spec={"train": 1.0})
        row = next(r for r in bundle.read_split("train")
                   if r["instance_id"] == "p000")
        item = context.items["p000"]
        assert row["candidates"] == item["responses"]
        assert row["prompt"] == item["prompt"]
        # The text is the two responses, not a Python list literal.
        assert row["text"] == "\n\n".join(item["responses"])

    def test_audio_segments_become_timed_targets(self, tmp_path):
        _, context, recordings = audio_project(tmp_path, n=4)
        bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["calls"],
                                    split_spec={"train": 1.0})
        assert bundle.modality == "audio"
        assert bundle.labels("calls") == ["beep"]
        row = next(r for r in bundle.read_split("train")
                   if r["instance_id"] == "a000")
        assert row["targets"]["calls"] == [
            {"start": s["start_time"], "end": s["end_time"], "label": "beep"}
            for s in recordings[0][1]]

    def test_boxes_declare_their_labels(self, tmp_path):
        _, context, _ = detection_project(tmp_path, n=6)
        bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["boxes"],
                                    split_spec={"train": 1.0})
        assert bundle.modality == "image"
        assert bundle.labels("boxes") == ["blue", "red"]


class TestRegistry:
    def test_each_new_kind_finds_its_trainers(self):
        def names(scheme, modality=None):
            return sorted(t.name for t in registry.trainers_for_schema(
                scheme, modality=modality))

        assert names({"annotation_type": "pairwise", "name": "p"}) == ["llm-dpo"]
        # Scale mode is a rating, not a choice between two responses.
        assert "llm-dpo" not in names({"annotation_type": "pairwise",
                                       "name": "p", "mode": "scale"})
        assert names({"annotation_type": "image_annotation", "name": "b"},
                     "image") == ["torchvision-detect", "torchvision-segment",
                                  "ultralytics-detect", "ultralytics-segment"]
        assert names({"annotation_type": "audio_annotation", "name": "c"},
                     "audio") == ["hf-audio-tagger"]

    def test_only_the_agpl_trainer_asks_for_a_licence(self):
        asking = [r["name"] for r in registry.list_trainers() if r["licence_ack"]]
        assert asking == ["ultralytics-detect", "ultralytics-segment"]


# --------------------------------------------------------------- scoring

class TestHeldOutScoring:
    BOX = {"type": "bbox", "label": "red",
           "coordinates": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}}

    def test_boxes_that_match_score_full_map(self):
        rows = [{"instance_id": "0", "targets": {"b": [self.BOX]}}]
        prediction = dict(self.BOX, confidence=0.9)
        metrics, _ = score_split(rows, {("0", "b"): [prediction]}, "b",
                                 "geometry")
        assert metrics["map_50"] == pytest.approx(1.0)
        assert metrics["map_50_95"] == pytest.approx(1.0)

    def test_a_box_shifted_past_iou_half_scores_nothing(self):
        rows = [{"instance_id": "0", "targets": {"b": [self.BOX]}}]
        # Shifted by its own width: IoU 0.
        moved = {"type": "bbox", "label": "red", "confidence": 0.9,
                 "coordinates": {"x": 0.3, "y": 0.1, "width": 0.2,
                                 "height": 0.2}}
        metrics, _ = score_split(rows, {("0", "b"): [moved]}, "b", "geometry")
        assert metrics["map_50"] == 0.0

    def test_a_box_detector_is_scored_against_each_shapes_bounding_box(self):
        """Box against polygon is IoU 0 in the agreement code, so a detector
        that found every annotated circle scored 0 on them."""
        circle = {"type": "polygon", "label": "circle", "coordinates": [
            {"x": 0.5 + 0.1 * math.cos(t * math.pi / 8),
             "y": 0.5 + 0.1 * math.sin(t * math.pi / 8)} for t in range(16)]}
        rows = [{"instance_id": "0", "targets": {"b": [circle]}}]
        box = {"type": "bbox", "label": "circle", "confidence": 0.9,
               "coordinates": {"x": 0.4, "y": 0.4, "width": 0.2, "height": 0.2}}
        metrics, _ = score_split(rows, {("0", "b"): [box]}, "b", "geometry")
        assert metrics["map_50"] == pytest.approx(1.0)

    def test_segments_match_at_iou_half_with_the_same_label(self):
        rows = [{"instance_id": "0", "targets": {"c": [
            {"start": 0.0, "end": 1.0, "label": "beep"},
            {"start": 2.0, "end": 3.0, "label": "beep"}]}}]
        payload = {"segments": [
            {"start_time": 0.1, "end_time": 1.0, "label": "beep"},   # IoU .9
            {"start_time": 2.0, "end_time": 2.4, "label": "beep"},   # IoU .4
            {"start_time": 0.0, "end_time": 1.0, "label": "buzz"}]}  # label
        metrics, _ = score_split(rows, {("0", "c"): payload}, "c", "temporal")
        assert metrics["precision"] == pytest.approx(1 / 3)
        assert metrics["recall"] == pytest.approx(1 / 2)
        assert metrics["matched_iou"] == pytest.approx(0.9)

    def test_no_preference_answers_are_not_scored(self):
        rows = [{"instance_id": "0", "targets": {"p": "A"}},
                {"instance_id": "1", "targets": {"p": "tie"}}]
        preds = {("0", "p"): {"label": "A"}, ("1", "p"): {"label": "B"}}
        metrics, n = score_split(rows, preds, "p", "preference")
        assert n == 1 and metrics["accuracy"] == 1.0

    def test_headlines(self):
        bundle = types.SimpleNamespace(read_split=lambda name: iter(
            [{"instance_id": "0", "targets": {"b": [self.BOX]}}]
            if name == "val" else []))
        schema = SchemaSpec(name="b", annotation_type="image_annotation",
                            kind="geometry")
        out = score_predictions(bundle, {("0", "b"): [self.BOX]}, [schema])
        assert out["heldout_metric"] == "val map_50"


# ------------------------------------------------------------- detection

class TestDetectionHelpers:
    def test_a_polygon_trains_as_its_bounding_box(self):
        from potato.training.trainers.torchvision_detect import boxes_from_objects
        polygon = {"type": "polygon", "label": "red", "coordinates": [
            {"x": 0.1, "y": 0.2}, {"x": 0.5, "y": 0.2}, {"x": 0.3, "y": 0.6}]}
        boxes, classes = boxes_from_objects([polygon], 100, 50,
                                            {"blue": 0, "red": 1})
        assert boxes == [[pytest.approx(10), pytest.approx(10),
                          pytest.approx(50), pytest.approx(30)]]
        assert classes == [2]   # 0 is background

    def test_detections_come_back_in_the_widgets_shape(self):
        from potato.training.trainers.torchvision_detect import client_boxes
        out = client_boxes([[10, 10, 50, 30], [0, 0, 5, 5]], [0.4, 0.9], [2, 1],
                           ["blue", "red"], 100, 50, "run-7")
        assert [o["label"] for o in out] == ["blue", "red"]   # by score
        assert out[1]["coordinates"] == {"x": 0.1, "y": 0.2, "width": 0.4,
                                         "height": 0.4}
        assert out[1]["source"] == "ai" and out[1]["ai_model"] == "run-7"

    def test_yolo_label_lines(self):
        from potato.training.trainers.ultralytics_detect import yolo_lines
        box = {"type": "bbox", "label": "red",
               "coordinates": {"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.4}}
        assert yolo_lines([box], 100, 50, {"red": 3}) == [
            "3 0.300000 0.400000 0.400000 0.400000"]


@needs_torch
class TestTorchvisionDetect:
    def test_fit_predict_and_score_end_to_end(self, tmp_path):
        pytest.importorskip("torchvision")
        config, context, _ = detection_project(tmp_path, n=24)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["boxes"], split_seed=1)
        spec = _spec(tmp_path, config, bundle, "torchvision-detect", "boxes",
                     {"pretrained": False, "epochs": 1, "min_size": 64,
                      "batch_size": 4, "min_instances": 4,
                      "score_threshold": 0.0, "max_detections": 5})
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        metrics = result["metrics"]
        # Untrained, so the score is low; that it is a real mAP is the point.
        assert metrics["heldout_metric"] in ("test map_50", "val map_50")
        assert 0.0 <= metrics["heldout_score"] <= 1.0
        records = _predictions(spec)
        assert records
        shape = records[0]["payload"][0]
        assert shape["type"] == "bbox" and shape["source"] == "ai"
        assert set(shape["coordinates"]) == {"x", "y", "width", "height"}

    def test_cancel(self, tmp_path, monkeypatch):
        pytest.importorskip("torchvision")
        from potato.training import worker
        monkeypatch.setitem(worker._STOP, "requested", True)
        config, context, _ = detection_project(tmp_path, n=12)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["boxes"], split_spec={"train": 1.0})
        spec = _spec(tmp_path, config, bundle, "torchvision-detect", "boxes",
                     {"pretrained": False, "epochs": 3, "min_size": 64,
                      "min_instances": 4})
        code, _, _ = _run(spec, should_stop=lambda: True)
        assert code == EXIT_CANCELLED


@needs_torch
class TestUltralyticsDetect:
    def test_settings_are_switched_off_in_memory_only(self, tmp_path,
                                                      monkeypatch):
        pytest.importorskip("ultralytics")
        from potato.training.trainers.ultralytics_detect import _quiet_ultralytics
        from ultralytics.utils import SETTINGS

        path = str(SETTINGS.file)
        before = open(path).read() if os.path.isfile(path) else None
        _quiet_ultralytics()
        assert SETTINGS["sync"] is False and SETTINGS.get("mlflow") is False
        from ultralytics.utils.events import events
        assert events.enabled is False
        assert os.environ["YOLO_AUTOINSTALL"] == "false"
        after = open(path).read() if os.path.isfile(path) else None
        assert after == before

    def test_fit_and_predict_from_an_architecture_file(self, tmp_path):
        pytest.importorskip("ultralytics")
        config, context, _ = detection_project(tmp_path, n=20)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["boxes"], split_seed=1)
        spec = _spec(tmp_path, config, bundle, "ultralytics-detect", "boxes",
                     {"model_name": "yolo11n.yaml", "epochs": 1,
                      "image_size": 64, "batch_size": 8, "mosaic": False,
                      "min_instances": 4})
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        assert result["metrics"]["heldout_metric"].endswith("map_50")
        assert os.path.isfile(os.path.join(spec.workdir, "model", "best.pt"))
        # The run and data directories are not artifacts.
        assert not os.path.exists(os.path.join(spec.workdir, "yolo_run"))
        assert not os.path.exists(os.path.join(spec.workdir, "yolo_data"))


def outline_project(tmp, n=16):
    """Red squares annotated as polygons, blue circles as ellipses."""
    from PIL import Image, ImageDraw

    rng = random.Random(0)
    os.makedirs(str(tmp / "img"), exist_ok=True)
    items, annotations = {}, []
    for i in range(n):
        width, height = 128, 96
        img = Image.new("RGB", (width, height), (200, 200, 200))
        draw = ImageDraw.Draw(img)
        objects = []
        for _ in range(rng.randint(1, 2)):
            label, size = rng.choice(["square", "circle"]), rng.randint(20, 36)
            x, y = rng.randint(0, width - size), rng.randint(0, height - size)
            if label == "square":
                draw.rectangle([x, y, x + size, y + size], fill=(220, 30, 30))
                objects.append({"type": "polygon", "label": label, "coordinates": [
                    {"x": px / width, "y": py / height} for px, py in
                    [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]]})
            else:
                draw.ellipse([x, y, x + size, y + size], fill=(30, 30, 220))
                objects.append({"type": "ellipse", "label": label, "coordinates": {
                    "cx": (x + size / 2) / width, "cy": (y + size / 2) / height,
                    "rx": size / 2 / width, "ry": size / 2 / height,
                    "angle": 0}})
        path = str(tmp / "img" / ("%03d.png" % i))
        img.save(path)
        iid = "i%03d" % i
        items[iid] = {"id": iid, "image": "img/%03d.png" % i}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {},
                            "image_annotations": {"shapes": objects}})
    scheme = {"annotation_type": "image_annotation", "name": "shapes",
              "description": "", "labels": ["square", "circle"],
              "tools": ["polygon", "ellipse"]}
    config, context = _context(tmp, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "image"
    return config, context


class TestSegmentationHelpers:
    def test_outlines_in_and_boxes_out(self):
        from potato.training.trainers._segmentation import outline_polygons
        ellipse = {"type": "ellipse", "label": "c", "coordinates": {
            "cx": 0.5, "cy": 0.5, "rx": 0.25, "ry": 0.25, "angle": 0}}
        rings = outline_polygons(ellipse, 100, 100)
        assert len(rings) == 1
        xs = [p[0] for p in rings[0]]
        assert min(xs) == pytest.approx(25, abs=0.5)
        assert max(xs) == pytest.approx(75, abs=0.5)
        box = {"type": "bbox", "label": "c",
               "coordinates": {"x": 0, "y": 0, "width": 1, "height": 1}}
        assert outline_polygons(box, 100, 100) == []

    def test_a_mask_is_traced_and_scaled_to_the_image(self):
        from potato.export.cv_utils import bitmap_to_rle
        from potato.training.trainers._segmentation import outline_polygons
        bitmap = [0] * 100
        for y in range(2, 8):
            for x in range(3, 7):
                bitmap[y * 10 + x] = 1
        mask = {"type": "mask", "label": "m", "rle": bitmap_to_rle(bitmap, 10, 10)}
        ring = outline_polygons(mask, 100, 100)[0]
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        # Pixel centres, ten times larger: 30..60 across, 20..70 down.
        assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx(
            (30, 60, 20, 70), abs=10)

    def test_a_traced_mask_is_simplified_for_editing(self):
        import numpy

        from potato.training.trainers._segmentation import MAX_VERTICES, mask_polygons
        yy, xx = numpy.mgrid[:200, :200]
        disc = (xx - 100) ** 2 + (yy - 100) ** 2 < 80 ** 2
        rings = mask_polygons(disc)
        assert len(rings) == 1 and 8 <= len(rings[0]) <= MAX_VERTICES

    def test_yolo_seg_lines(self):
        from potato.training.trainers.ultralytics_segment import yolo_seg_lines
        square = {"type": "polygon", "label": "s", "coordinates": [
            {"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.5},
            {"x": 0.1, "y": 0.5}]}
        box = {"type": "bbox", "label": "s",
               "coordinates": {"x": 0, "y": 0, "width": 1, "height": 1}}
        assert yolo_seg_lines([square, box], 200, 100, {"s": 2}) == [
            "2 0.100000 0.100000 0.500000 0.100000 0.500000 0.500000 "
            "0.100000 0.500000"]

    def test_outlines_are_scored_as_polygons_and_boxes_left_out(self):
        circle = {"type": "ellipse", "label": "c", "coordinates": {
            "cx": 0.5, "cy": 0.5, "rx": 0.1, "ry": 0.1, "angle": 0}}
        box = {"type": "bbox", "label": "c",
               "coordinates": {"x": 0, "y": 0, "width": 0.1, "height": 0.1}}
        rows = [{"instance_id": "0", "targets": {"b": [circle, box]}}]
        predicted = {"type": "polygon", "label": "c", "confidence": 0.9,
                     "coordinates": [
                         {"x": 0.5 + 0.1 * math.cos(t * math.pi / 18),
                          "y": 0.5 + 0.1 * math.sin(t * math.pi / 18)}
                         for t in range(36)]}
        metrics, _ = score_split(rows, {("0", "b"): [predicted]}, "b",
                                 "geometry")
        assert metrics["n_objects"] == 1.0
        assert metrics["map_50"] == pytest.approx(1.0)


@needs_torch
class TestTorchvisionSegment:
    def test_fit_predict_and_score_end_to_end(self, tmp_path):
        pytest.importorskip("torchvision")
        config, context = outline_project(tmp_path)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["shapes"], split_seed=1)
        spec = _spec(tmp_path, config, bundle, "torchvision-segment", "shapes",
                     {"pretrained": False, "epochs": 1, "min_size": 64,
                      "min_instances": 4, "score_threshold": 0.0,
                      "max_detections": 3})
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        assert result["metrics"]["heldout_metric"].endswith("map_50")
        shape = _predictions(spec)[0]["payload"][0]
        assert shape["type"] == "polygon" and shape["source"] == "ai"
        assert 3 <= len(shape["coordinates"]) <= 64


@needs_torch
class TestUltralyticsSegment:
    def test_fit_from_an_architecture_file(self, tmp_path):
        pytest.importorskip("ultralytics")
        config, context = outline_project(tmp_path, n=20)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["shapes"], split_seed=1)
        spec = _spec(tmp_path, config, bundle, "ultralytics-segment", "shapes",
                     {"model_name": "yolo11n-seg.yaml", "epochs": 1,
                      "image_size": 64, "batch_size": 8, "mosaic": False,
                      "min_instances": 4})
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        assert result["metrics"]["heldout_metric"].endswith("map_50")
        assert os.path.isfile(os.path.join(spec.workdir, "model", "best.pt"))


class TestLicenceGate:
    def test_auto_retrain_will_not_run_an_agpl_trainer_unconfirmed(self, tmp_path):
        from potato.training.manager import TrainingManager

        config = {"task_dir": str(tmp_path), "annotation_schemes": [],
                  "model_training": {"enabled": True, "auto_retrain": {
                      "enabled": True, "trainer": "ultralytics-detect",
                      "schemas": ["boxes"], "update_frequency": 1}}}
        manager = TrainingManager(config)
        started = []
        manager.start_run = lambda *a, **k: started.append(a) or {
            "started": True, "run_id": "r1"}
        manager._annotation_count = lambda: 100
        outcome = manager.maybe_auto_retrain()
        assert not outcome["started"] and not started
        assert "accept_licence" in outcome["reason"]

        config["model_training"]["auto_retrain"]["accept_licence"] = True
        manager.maybe_auto_retrain()
        assert started


# ------------------------------------------------------------------ audio

class TestAudioHelpers:
    def test_frames_are_labelled_by_their_centre(self):
        from potato.training.trainers.hf_audio_tagger import frame_targets
        frames = frame_targets([{"start": 0.05, "end": 0.15, "label": "beep"}],
                               {"beep": 0}, 5, 0.04, 0.0)
        # Centres at .02 .06 .10 .14 .18
        assert [f[0] for f in frames] == [0.0, 1.0, 1.0, 1.0, 0.0]

    def test_decoding_closes_short_gaps_and_drops_short_segments(self):
        from potato.training.trainers.hf_audio_tagger import decode_segments
        probs = [[p] for p in (0.9, 0.9, 0.2, 0.9, 0.1, 0.1, 0.1, 0.8, 0.1)]
        times = [0.1 * i for i in range(len(probs))]
        segments = decode_segments(probs, times, ["beep"], 0.1, 0.5,
                                   min_gap_s=0.1, min_duration_s=0.15)
        assert [(s["start_time"], s["end_time"]) for s in segments] == [(0.0, 0.4)]

    @needs_torch
    def test_frame_counts_follow_the_encoder_not_the_stride(self, tmp_path):
        from transformers import AutoModelForAudioFrameClassification

        from potato.training.trainers.hf_audio_tagger import HFAudioTaggerTrainer
        from tests.helpers.tiny_hf import tiny_wav2vec2
        model = AutoModelForAudioFrameClassification.from_pretrained(
            tiny_wav2vec2(str(tmp_path / "m")), num_labels=1)
        # 80-sample hop, but the kernels' overhang loses frames.
        assert HFAudioTaggerTrainer._frames_for(model, 16000) == \
            int(model._get_feat_extract_output_lengths(16000)) < 16000 // 80


@needs_torch
class TestAudioTagger:
    def test_learns_the_beeps(self, tmp_path):
        pytest.importorskip("soundfile")
        from tests.helpers.tiny_hf import tiny_wav2vec2
        config, context, recordings = audio_project(tmp_path, n=40)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["calls"], split_seed=1)
        spec = _spec(tmp_path, config, bundle, "hf-audio-tagger", "calls",
                     {"model_name": tiny_wav2vec2(str(tmp_path / "m")),
                      "epochs": 25, "batch_size": 8, "learning_rate": 3e-3,
                      "freeze_feature_encoder": False, "patience": None,
                      "min_instances": 4})
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        assert result["metrics"]["heldout_metric"].endswith(" f1")
        assert result["metrics"]["heldout_score"] >= 0.6
        record = _predictions(spec)[0]
        segment = record["payload"]["segments"][0]
        # The audio widget's own value shape, so write-back renders it, with
        # the provenance the widget keeps (audit 98 re-verify).
        assert {"start_time", "end_time", "label", "id"} <= set(segment)
        assert segment["source"] == "ai"
        assert segment["ai_model"].startswith("hf-audio-tagger-calls-")


# -------------------------------------------------------------------- DPO

@needs_torch
class TestDPO:
    def test_dpo_loss_by_hand(self):
        import torch

        from potato.training.trainers.llm_dpo import dpo_loss
        loss, margin = dpo_loss(torch.tensor([-1.0]), torch.tensor([-3.0]),
                                torch.tensor([-2.0]), torch.tensor([-2.0]), 0.5)
        assert float(margin) == pytest.approx(1.0)
        assert float(loss) == pytest.approx(-torch.nn.functional.logsigmoid(
            torch.tensor(1.0)).item())

    @pytest.mark.parametrize("lora", [True, False])
    def test_learns_the_preference_and_skips_ties(self, tmp_path, lora):
        pytest.importorskip("peft")
        from tests.helpers.tiny_hf import tiny_causal_lm
        config, context, texts = preference_project(tmp_path, n=80)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["pref"], split_seed=1)
        spec = _spec(tmp_path, config, bundle, "llm-dpo", "pref",
                     {"model_name": tiny_causal_lm(str(tmp_path / "m"), texts),
                      "lora": lora, "epochs": 6, "batch_size": 8,
                      "gradient_accumulation": 1, "beta": 0.5,
                      "learning_rate": 1e-3 if lora else 5e-4,
                      "patience": None, "min_instances": 4})
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        metrics = result["metrics"]
        assert metrics["heldout_metric"] == "test accuracy"
        assert metrics["heldout_score"] >= 0.9
        test_ties = sum(1 for r in bundle.read_split("test")
                        if r["targets"]["pref"] == "tie")
        assert metrics["test_n"] == bundle.split_size("test") - test_ties
        payload = _predictions(spec)[0]["payload"]
        assert payload["label"] in ("A", "B") and 0.5 <= payload["confidence"] <= 1


# --------------------------------------------------------- segments export

class TestSegmentsExporter:
    def _context(self, schemes, annotations, items):
        from potato.export.base import ExportContext
        return ExportContext(config={}, annotations=annotations, items=items,
                             schemas=schemes, output_dir="")

    def test_jsonl_and_one_rttm_per_annotator(self, tmp_path):
        from potato.export.registry import export_registry
        exporter = export_registry.get("segments")
        scheme = {"annotation_type": "audio_annotation", "name": "turns"}
        value = lambda segs: {"_data": json.dumps({"segments": segs})}
        context = self._context([scheme], [
            {"instance_id": "c1", "user_id": "ann one", "labels": {"turns": value([
                {"start_time": 1.5, "end_time": 3.25, "label": "Speaker A"},
                {"start_time": 0.0, "end_time": 1.0, "label": "Speaker B"}])}},
            {"instance_id": "c1", "user_id": "two", "labels": {"turns": value([
                {"start_time": 0.0, "end_time": 2.0, "label": "Speaker A"}])}},
        ], {"c1": {"id": "c1", "audio": "media/call 01.wav"}})
        result = exporter.export(context, str(tmp_path))
        assert result.success, result.errors
        rows = [json.loads(line) for line in
                open(tmp_path / "segments.jsonl").read().splitlines()]
        assert len(rows) == 3
        assert rows[0] == {"instance_id": "c1", "user_id": "ann one",
                           "schema": "turns", "start": 0.0, "end": 1.0,
                           "duration": 1.0, "label": "Speaker B",
                           "media": "media/call 01.wav"}
        rttm = open(tmp_path / "rttm" / "ann_one.rttm").read().splitlines()
        assert rttm == [
            "SPEAKER call_01 1 0.000 1.000 <NA> <NA> Speaker_B <NA> <NA>",
            "SPEAKER call_01 1 1.500 1.750 <NA> <NA> Speaker_A <NA> <NA>"]
        assert os.path.isfile(tmp_path / "rttm" / "two.rttm")

    def test_several_schemes_get_a_directory_each(self, tmp_path):
        from potato.export.segments_exporter import SegmentsExporter
        schemes = [{"annotation_type": "audio_annotation", "name": "a"},
                   {"annotation_type": "video_annotation", "name": "v"}]
        seg = {"_data": json.dumps({"segments": [
            {"start_time": 0, "end_time": 1, "label": "x"}]})}
        context = self._context(schemes, [
            {"instance_id": "i", "user_id": "u", "labels": {"a": seg, "v": seg}}],
            {"i": {"id": "i"}})
        result = SegmentsExporter().export(context, str(tmp_path))
        assert result.success
        assert os.path.isfile(tmp_path / "rttm" / "a" / "u.rttm")
        assert os.path.isfile(tmp_path / "rttm" / "v" / "u.rttm")

    def test_refuses_a_project_with_no_timeline(self):
        from potato.export.segments_exporter import SegmentsExporter
        ok, reason = SegmentsExporter().can_export(self._context(
            [{"annotation_type": "radio", "name": "r"}], [], {}))
        assert not ok and "audio_annotation" in reason

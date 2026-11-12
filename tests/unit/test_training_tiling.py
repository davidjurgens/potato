"""Cutting large images into tiles for the detection trainers, and putting
their predictions back together.

Before this a whole slide was resized to a few hundred pixels (no nucleus
survives that) and shipped whole, gigabytes, to every remote host.
"""

import json
import os
import random

import pytest

from potato.training import tiling
from potato.training.base import BundleRef
from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from tests.unit.test_training_detection_audio_dpo import _context, _predictions, _run, _spec

HAVE = __import__("importlib").util.find_spec


def _box(x, y, w, h, label="red", **extra):
    return dict({"type": "bbox", "label": label,
                 "coordinates": {"x": x, "y": y, "width": w, "height": h}}, **extra)


def big_images(directory, n, size=(240, 160), seed=0):
    """Grey images with red squares, and the squares as normalized boxes."""
    from PIL import Image, ImageDraw
    rng = random.Random(seed)
    os.makedirs(directory, exist_ok=True)
    out = []
    width, height = size
    for i in range(n):
        img = Image.new("RGB", size, (200, 200, 200))
        draw = ImageDraw.Draw(img)
        objects = []
        for _ in range(3):
            side = 16
            x, y = rng.randint(0, width - side), rng.randint(0, height - side)
            draw.rectangle([x, y, x + side - 1, y + side - 1], fill=(220, 30, 30))
            objects.append(_box(x / width, y / height, side / width, side / height))
        path = os.path.join(directory, "big%02d.png" % i)
        img.save(path)
        out.append((path, objects))
    return out


def tiled_project(tmp, n=12, tiling_config=None):
    images = big_images(str(tmp / "img"), n)
    items, annotations = {}, []
    for i, (path, objects) in enumerate(images):
        iid = "b%02d" % i
        items[iid] = {"id": iid, "image": os.path.relpath(path, tmp)}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {},
                            "image_annotations": {"boxes": objects}})
    scheme = {"annotation_type": "image_annotation", "name": "boxes",
              "description": "", "labels": ["red"], "tools": ["bbox"]}
    config, context = _context(tmp, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "image"
    config["model_training"] = {"tiling": tiling_config if tiling_config is not None
                                else {"enabled": True, "tile_size": 96, "overlap": 32}}
    return config, context, images


# ------------------------------------------------------------------ pieces

def test_settings_are_checked():
    assert tiling.settings({})["enabled"] == "auto"
    assert tiling.settings({"model_training": {"tiling": False}})["enabled"] is False
    for bad in ({"overlap": 2048}, {"tile_size": 0}, {"downsample": 0.5},
                {"enabled": "yes"}, {"tile_sise": 512}):
        with pytest.raises(tiling.TilingError):
            tiling.settings({"model_training": {"tiling": bad}})


def test_the_grid_reaches_every_edge_without_running_off():
    tiles = tiling.grid(250, 100, 96, 64)
    xs = sorted({t[0] for t in tiles})
    assert xs == [0, 64, 128, 154]          # the last column ends at 250
    assert all(x + w <= 250 and y + h <= 100 for x, y, w, h in tiles)
    assert tiling.grid(50, 40, 96, 64) == [(0, 0, 50, 40)]


def test_clipping_keeps_what_is_mostly_inside():
    # A 20x20 box at (90, 10) on a 200x100 image; the tile is x 0..100.
    box = _box(90 / 200, 10 / 100, 20 / 200, 20 / 100)
    half = tiling.clip_object(box, (0, 0, 100, 100), 200, 100, min_visible=0.4)
    assert len(half) == 1
    c = half[0]["coordinates"]
    assert c["x"] == pytest.approx(0.9) and c["width"] == pytest.approx(0.1)
    # 0.5 inside, below a 0.6 threshold, and 10x20 is under a quarter of the tile.
    assert tiling.clip_object(box, (0, 0, 100, 100), 200, 100, min_visible=0.6) == []
    # A polygon becomes the piece inside.
    triangle = {"type": "polygon", "label": "t", "coordinates": [
        {"x": 0.4, "y": 0.1}, {"x": 0.6, "y": 0.1}, {"x": 0.4, "y": 0.5}]}
    piece = tiling.clip_object(triangle, (0, 0, 100, 100), 200, 100, min_visible=0.4)
    assert piece and piece[0]["type"] == "polygon"
    assert max(p["x"] for p in piece[0]["coordinates"]) == pytest.approx(1.0)
    point = {"type": "landmark", "label": "p", "coordinates": {"x": 0.75, "y": 0.5}}
    assert tiling.clip_object(point, (0, 0, 100, 100), 200, 100, 0.4) == []
    assert tiling.clip_object(point, (100, 0, 100, 100), 200, 100, 0.4)[0][
        "coordinates"] == {"x": 0.5, "y": 0.5}


def test_a_piece_of_a_huge_region_still_trains():
    """A region spanning many tiles is under min_visible in each, but each
    piece covering most of its tile is still that region."""
    region = _box(0.0, 0.0, 1.0, 1.0, label="tissue")
    pieces = tiling.clip_object(region, (0, 0, 100, 100), 1000, 1000, min_visible=0.4)
    assert len(pieces) == 1


def test_tile_predictions_map_back_and_overlap_duplicates_merge():
    tile_a = {"x": 0, "y": 0, "w": 100, "h": 100, "width": 200, "height": 100}
    tile_b = dict(tile_a, x=60)
    # An object at x 90..110 px: tile b sees all of it; tile a sees 90..100,
    # cut by its right edge, which tile b continues past.
    whole = _box(0.3, 0.1, 0.2, 0.1, confidence=0.7)
    cut = _box(0.9, 0.1, 0.1, 0.1, confidence=0.95)
    assert tiling._touches_inner_edge(cut, tile_a)
    assert not tiling._touches_inner_edge(whole, tile_b)
    mapped_whole = tiling.to_parent(whole, tile_b)
    mapped_cut = dict(tiling.to_parent(cut, tile_a), _cut=True)
    assert mapped_whole["coordinates"]["x"] == pytest.approx(0.45)
    assert mapped_whole["coordinates"]["width"] == pytest.approx(0.1)
    assert mapped_cut["coordinates"]["x"] == pytest.approx(0.45)
    # A second full copy from a third tile, at IoU above 0.5.
    copy = dict(mapped_whole, confidence=0.6)
    kept = tiling.merge([mapped_whole, mapped_cut, copy])
    # One object, the whole one, with the cut copy's higher confidence.
    assert len(kept) == 1
    assert kept[0]["coordinates"]["width"] == pytest.approx(0.1)
    assert kept[0]["confidence"] == 0.95 and "_cut" not in kept[0]
    other = _box(0.1, 0.5, 0.05, 0.1, label="blue", confidence=0.5)
    assert len(tiling.merge([mapped_whole, mapped_cut, other])) == 2


def test_an_object_inside_another_is_kept_unless_it_was_cut():
    """A nucleus inside a cell, both labelled "cell", is two objects; the
    containment rule deleted the nucleus at any confidence (audit 102)."""
    cell = _box(0.1, 0.1, 0.4, 0.4, confidence=0.6)
    nucleus = _box(0.25, 0.25, 0.05, 0.05, confidence=0.95)
    assert len(tiling.merge([cell, nucleus])) == 2
    assert len(tiling.merge([cell, dict(nucleus, _cut=True)])) == 1


def test_two_tiles_copies_of_a_point_are_one_point():
    a = {"type": "landmark", "label": "p", "coordinates": {"x": 0.5, "y": 0.5}, "confidence": 0.9}
    b = dict(a, coordinates={"x": 0.5004, "y": 0.5003}, confidence=0.8)
    far = dict(a, coordinates={"x": 0.6, "y": 0.5})
    assert len(tiling.merge([a, b], point_tolerance=0.001)) == 1
    assert len(tiling.merge([a, b, far], point_tolerance=0.001)) == 2
    assert len(tiling.merge([a, b])) == 2
    # Exactly the tolerance apart, measured in floating point.
    c = dict(a, coordinates={"x": 0.5 + 0.004, "y": 0.5})
    assert len(tiling.merge([a, c], point_tolerance=4 / 1000)) == 1


# ------------------------------------------------------------------ bundle

def test_bundle_tiles_after_the_split(tmp_path):
    config, context, images = tiled_project(tmp_path)
    bundle, stats, split_ids = build_bundle(context, str(tmp_path / "b"), ["boxes"],
                                            split_seed=1)
    assert bundle.manifest["tiling"]["tile_size"] == 96
    assert stats.tiles["n_items"] == 12 and stats.tiles["n_tiles"] > 12
    # The ledger sees images; the split files hold tiles.
    assert set(sum(split_ids.values(), [])) == {"b%02d" % i for i in range(12)}
    assert sum(stats.splits.values()) == 12
    parents = {}
    with open(os.path.join(bundle.root, tiling.PARENTS_FILE)) as fh:
        for line in fh:
            parent = json.loads(line)
            parents[parent["instance_id"]] = parent
    for split, ids in split_ids.items():
        for row in bundle.read_split(split):
            assert row["parent_id"] in ids and parents[row["parent_id"]]["split"] == split
            assert os.path.isfile(os.path.join(bundle.root, "media", row["media"]))
            from PIL import Image
            with Image.open(os.path.join(bundle.root, "media", row["media"])) as tile:
                assert tile.size == (96, 96)
    train = list(bundle.read_split("train"))
    # Every training tile has an object, or is one of the sampled empties.
    with_objects = [r for r in train if r["targets"]["boxes"]]
    assert len(train) - len(with_objects) <= len(with_objects) * 0.25 + 1
    assert parents["b00"]["size"] == [240, 160]


def test_auto_leaves_small_images_whole(tmp_path):
    config, context, _ = tiled_project(tmp_path, n=6, tiling_config={})
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["boxes"])
    assert "tiling" not in bundle.manifest and not stats.tiles
    assert all("parent_id" not in r for r in bundle.read_split("train"))


def test_stitch_and_score_on_the_parents(tmp_path):
    config, context, images = tiled_project(tmp_path)
    bundle, _, split_ids = build_bundle(context, str(tmp_path / "b"), ["boxes"],
                                        split_seed=1)
    truth = {"b%02d" % i: objects for i, (_, objects) in enumerate(images)}
    # Predict every tile's own clipped truth: after stitching, each image
    # should score as a perfect detector.
    path = str(tmp_path / "predictions.jsonl")
    with open(path, "w") as fh:
        for split in ("val", "test"):
            for row in bundle.read_split(split):
                payload = [dict(o, confidence=0.9) for o in row["targets"]["boxes"]]
                fh.write(json.dumps({"instance_id": row["instance_id"],
                                     "schema_name": "boxes", "payload": payload,
                                     "confidence": 0.9}) + "\n")
    n = tiling.stitch_file(bundle, path)
    with open(path) as fh:
        records = [json.loads(line) for line in fh]
    assert n == len(records) and {r["instance_id"] for r in records} <= set(truth)
    assert all("@" not in r["instance_id"] for r in records)
    from potato.training.evaluation import read_predictions, score_predictions
    from potato.training.base import SchemaSpec
    scores = score_predictions(bundle, read_predictions(path),
                               [SchemaSpec(name="boxes", annotation_type="image_annotation", kind="geometry")])
    assert scores["heldout_metric"].endswith("map_50")
    assert scores["heldout_score"] > 0.9


@pytest.mark.skipif(not (HAVE("torch") and HAVE("torchvision")),
                    reason="torch/torchvision absent")
def test_detector_trains_on_tiles_and_predicts_whole_images(tmp_path):
    config, context, _ = tiled_project(tmp_path, n=10)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["boxes"],
                                split_seed=1, include_unlabeled=False)
    spec = _spec(tmp_path, config, bundle, "torchvision-detect", "boxes",
                 {"pretrained": False, "epochs": 1, "min_size": 64,
                  "batch_size": 4, "min_instances": 2,
                  "score_threshold": 0.0, "max_detections": 5})
    code, result, _ = _run(spec)
    assert code == EXIT_OK
    assert result["metrics"]["heldout_metric"].endswith("map_50")
    records = _predictions(spec)
    assert records and all("@" not in r["instance_id"] for r in records)
    for record in records:
        for shape in record["payload"]:
            c = shape["coordinates"]
            assert 0.0 <= c["x"] <= 1.0 and 0.0 <= c["y"] <= 1.0


@pytest.mark.skipif(not HAVE("openslide"), reason="openslide absent")
def test_a_slide_is_tiled_over_tissue_only(tmp_path):
    """An Aperio slide openslide reads: white glass with one pink
    island. Prediction tiles cover the island and skip the glass."""
    import numpy
    import tifffile
    width, height = 1024, 768
    image = numpy.full((height, width, 3), 245, numpy.uint8)
    image[100:400, 100:500] = (232, 170, 200)
    path = tmp_path / "slide.svs"
    head = "Aperio Image Library v12.0.0 \n%dx%d [0,0 %dx%d] (256x256)" % (
        width, height, width, height)
    # metadata=None: openslide recognises Aperio by the description alone.
    with tifffile.TiffWriter(str(path)) as tif:
        tif.write(image, tile=(256, 256), photometric="rgb", metadata=None,
                  description="%s -> %dx%d|MPP = 0.5" % (head, width, height))
        thumb = image[::8, ::8].copy()
        tif.write(thumb, photometric="rgb", metadata=None,
                  description="%s -> %dx%d - thumbnail" % (head, thumb.shape[1], thumb.shape[0]))
    from potato.media.slides import is_slide
    if not is_slide(str(path)):
        pytest.skip("openslide does not read this TIFF")
    reader = tiling._open(str(path))
    try:
        assert reader.slide and reader.size == (width, height)
        assert reader.mpp == 0.5
        tiles = tiling.grid(width, height, 256, 256)
        fractions = dict(zip(tiles, tiling._tissue(reader, tiles)))
        assert fractions[(256, 256, 256, 256)] > 0.5      # inside the island
        assert fractions[(768, 512, 256, 256)] == 0.0     # bare glass
    finally:
        reader.close()


def test_a_bare_name_is_found_in_the_media_directory(tmp_path):
    """The deep-zoom viewer takes a path inside media_directory, so a slide
    study's items name ``slide.svs``; read beside the task directory, every
    one was missing and the run had no images."""
    from PIL import Image
    os.makedirs(tmp_path / "media")
    Image.new("RGB", (32, 32)).save(tmp_path / "media" / "pic.png")
    scheme = {"annotation_type": "image_annotation", "name": "boxes",
              "description": "", "labels": ["red"], "tools": ["bbox"]}
    items = {"p": {"id": "p", "image": "pic.png"}}
    annotations = [{"instance_id": "p", "user_id": "a", "labels": {},
                    "image_annotations": {"boxes": [_box(0.1, 0.1, 0.2, 0.2)]}}]
    config, context = _context(tmp_path, [scheme], items, annotations)
    config["media_directory"] = "media"
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["boxes"],
                                    split_spec={"train": 1.0})
    assert stats.n_media_missing == 0
    row = next(bundle.read_split("train"))
    assert row["media_source"] == "media/pic.png"


def test_an_empty_tile_is_a_negative_and_an_empty_image_is_not():
    from potato.training.trainers import _hf_common as hf
    rows = [{"instance_id": "a@0,0", "parent_id": "a", "targets": {"s": []}},
            {"instance_id": "b", "targets": {"s": []}},
            {"instance_id": "c", "targets": {"s": [_box(0, 0, 1, 1)]}}]
    assert [r["instance_id"] for r in hf.rows_with_target(rows, "s")] == ["c"]
    assert [r["instance_id"] for r in hf.rows_with_target(rows, "s", negative_tiles=True)] \
        == ["a@0,0", "c"]


@pytest.mark.skipif(not (HAVE("torch") and HAVE("torchvision")),
                    reason="torch/torchvision absent")
def test_detector_targets_for_an_empty_tile():
    from potato.training.trainers.torchvision_detect import TorchvisionDetectTrainer
    from potato.training.trainers.torchvision_segment import TorchvisionSegmentTrainer
    for trainer in (TorchvisionDetectTrainer(), TorchvisionSegmentTrainer()):
        target = trainer._row_target([], 32, 24, {"red": 0})
        tensors = trainer._target_tensors(target, 32, 24, True, "cpu")
        assert tuple(tensors["boxes"].shape) == (0, 4)
        if "masks" in tensors:
            assert tuple(tensors["masks"].shape) == (0, 24, 32)


def test_two_images_with_one_name_stay_two_images(tmp_path):
    """a/001.jpg and b/001.jpg shared a two-digit folder one time in 256,
    and the second item trained on the first's image."""
    from PIL import Image
    import hashlib
    from potato.training import dataset
    # Find two folders whose old two-digit digests collide.
    folders, seen = [], {}
    for n in range(2000):
        name = "dir%d" % n
        path = os.path.abspath(str(tmp_path / name / "001.png"))
        key = hashlib.sha1(path.encode()).hexdigest()[:2]
        if key in seen:
            folders = [seen[key], name]
            break
        seen[key] = name
    assert folders
    for n, folder in enumerate(folders):
        os.makedirs(tmp_path / folder)
        Image.new("RGB", (8, 8), (n * 200, 0, 0)).save(tmp_path / folder / "001.png")
    stats = dataset.BundleStats()
    media = str(tmp_path / "bundle_media")
    linked = [dataset._link_media(os.path.join(f, "001.png"), str(tmp_path), media, stats)
              for f in folders]
    assert linked[0] != linked[1]
    with Image.open(os.path.join(media, linked[1])) as image:
        assert image.getpixel((0, 0))[0] == 200


def test_media_outside_the_project_is_not_linked(tmp_path):
    from potato.training import dataset
    outside = tmp_path / "elsewhere"
    project = tmp_path / "project"
    os.makedirs(outside)
    os.makedirs(project / "media")
    (outside / "secret.txt").write_text("not for the GPU host")
    os.symlink(outside / "secret.txt", project / "media" / "link.png")
    stats = dataset.BundleStats()
    media = str(tmp_path / "bundle_media")
    for reference in (str(outside / "secret.txt"), "../elsewhere/secret.txt",
                      "/media/link.png"):
        assert dataset._link_media(reference, str(project), media, stats) is None, reference
    assert stats.n_media_outside == 3


def test_the_tile_index_finds_exactly_the_overlapping_tiles():
    tiles = tiling.grid(1000, 700, 256, 192)
    index = tiling._TileIndex(tiles)
    rng = random.Random(4)
    for _ in range(200):
        x0, y0 = rng.uniform(-50, 1000), rng.uniform(-50, 700)
        reach = (x0, y0, x0 + rng.uniform(0, 300), y0 + rng.uniform(0, 300))
        brute = [t for t in tiles if t[0] < reach[2] and t[0] + t[2] > reach[0]
                 and t[1] < reach[3] and t[1] + t[3] > reach[1]]
        assert sorted(index.over(reach)) == sorted(brute)


def test_capped_prediction_tiles_are_spread_over_the_image():
    """Every tile of an ordinary image is all tissue; sorted by tissue
    alone, the cap kept the top strip (audit 102)."""
    tiles = tiling.grid(1000, 1000, 100, 100)
    kept = tiling._most_tissue(tiles, [1.0] * len(tiles), 10)
    assert len(kept) == 10 and len({y for _, y, _, _ in kept}) > 3
    # Five columns and a cap of four kept one column with a stride.
    five = tiling.grid(500, 1000, 100, 100)
    kept = tiling._most_tissue(sorted(five), [1.0] * len(five), 4)
    assert len({x for x, _, _, _ in kept}) > 1 and len({y for _, y, _, _ in kept}) > 1
    fractions = [0.5] * len(tiles)
    fractions[57] = 0.9
    assert tiles[57] in tiling._most_tissue(tiles, fractions, 3)


def test_overlap_past_half_a_tile_is_refused():
    with pytest.raises(tiling.TilingError):
        tiling.settings({"model_training": {"tiling": {"tile_size": 512, "overlap": 511}}})
    assert tiling.settings({"model_training": {"tiling": {"tile_size": 512,
                                                          "overlap": 256}}})["overlap"] == 256

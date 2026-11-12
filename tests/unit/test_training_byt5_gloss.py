"""byt5-gloss on a toy agglutinative language, fitted end to end on a tiny
byte-level T5. A stem and a suffix each have one gloss, so a model that
learns the parts can gloss combinations; the held-out score is morpheme
gloss accuracy."""

import json
import os
import random
import types
from pathlib import Path

import pytest

from potato.training import worker
from potato.training.base import ResourceLimits, TrainingSpec
from potato.training.dataset import build_bundle, schema_specs_from_config
from potato.training.events import EXIT_OK, CollectingReporter
from potato.training.trainers.byt5_gloss import pairs_of, segments_words
from tests.helpers.test_utils import create_test_directory

HAVE_HF = all(__import__("importlib").util.find_spec(m) for m in
              ("torch", "transformers"))
needs_hf = pytest.mark.skipif(not HAVE_HF, reason="torch/transformers absent")

STEMS = {"kitab": "book", "ev": "house", "kedi": "cat", "masa": "table"}
SUFFIXES = {"im": "1SG", "ler": "PL", "de": "LOC"}


@pytest.fixture
def work(request):
    return Path(create_test_directory("byt5_" + request.node.name))


def _word(stem, suffix):
    return {"word": stem + suffix, "morphemes": "%s-%s" % (stem, suffix),
            "gloss": "%s-%s" % (STEMS[stem], SUFFIXES[suffix])}


def test_pairs_and_segmentation_detection():
    target = {"words": [_word("ev", "de"), {"word": "x", "morphemes": "x", "gloss": ""}]}
    assert pairs_of(target, segment=True) == [
        ("gloss: ev-de || word: evde || sentence: evde x", "house-LOC"),
        ("segment: evde || sentence: evde x", "ev-de")]
    assert segments_words([{"targets": {"g": target}}], "g")
    assert not segments_words([{"targets": {"g": {"words": [
        {"word": "ev", "morphemes": "ev", "gloss": "house"}]}}}], "g")


def test_a_gloss_source_field_is_text_not_media(work):
    """``source_field`` names the sentence. Looked up as a media file, every
    gloss item was counted as missing media."""
    scheme = {"annotation_type": "interlinear_gloss", "name": "igt",
              "source_field": "sentence"}
    words = [_word("ev", "de")]
    items = {"s%d" % n: {"id": "s%d" % n, "sentence": "evde"} for n in range(4)}
    annotations = [{"instance_id": iid, "user_id": "a", "labels": {
        "igt": {"igt": json.dumps({"words": words, "translation": ""})}}} for iid in items]
    config = {"task_dir": str(work), "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": [scheme]}
    context = types.SimpleNamespace(config=config, annotations=annotations, items=items,
                                    schemas=[scheme], output_dir=str(work),
                                    phase_responses={})
    bundle, stats, _ = build_bundle(context, str(work / "bundle"), ["igt"], split_seed=1)
    assert stats.n_media_missing == 0
    assert not any("media_missing" in row for split in ("train", "val", "test")
                   for row in bundle.read_split(split))


@needs_hf
def test_glossing_learns_stems_and_suffixes(work):
    from tests.helpers.tiny_hf import tiny_byt5
    scheme = {"annotation_type": "interlinear_gloss", "name": "igt", "source_field": "text"}
    rng = random.Random(0)
    items, annotations = {}, []
    for n in range(60):
        words = [_word(rng.choice(list(STEMS)), rng.choice(list(SUFFIXES)))
                 for _ in range(2)]
        text = " ".join(w["word"] for w in words)
        iid = "s%02d" % n
        items[iid] = {"id": iid, "text": text}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {
            "igt": {"igt": json.dumps({"words": words, "translation": ""})}}})
    # One item nobody glossed yet: it is predicted from its words alone.
    items["u1"] = {"id": "u1", "text": "kitabler evim"}
    config = {"task_dir": str(work), "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": [scheme]}
    context = types.SimpleNamespace(config=config, annotations=annotations, items=items,
                                    schemas=[scheme], output_dir=str(work),
                                    phase_responses={})
    bundle, _, _ = build_bundle(context, str(work / "bundle"), ["igt"], split_seed=1,
                                include_unlabeled=True)
    spec = TrainingSpec(
        run_id="r1", trainer="byt5-gloss",
        schemas=schema_specs_from_config(config, ["igt"], bundle.manifest["labels"]),
        bundle_dir=bundle.root, workdir=str(work / "artifacts"),
        params={"epochs": 40, "batch_size": 16, "learning_rate": 3e-3, "min_instances": 4,
                "patience": None, "max_new_tokens": 24,
                "model_name": tiny_byt5(str(work / "m"))},
        seed=3, limits=ResourceLimits(device="cpu"))
    report = CollectingReporter()
    assert worker.run(spec, report) == EXIT_OK, [e["msg"] for e in report.of_type("log")][-4:]
    metrics = report.of_type("result")[0]["metrics"]
    print({k: v for k, v in metrics.items() if "accuracy" in k})
    assert metrics["heldout_metric"] == "test morpheme_accuracy"
    assert metrics["heldout_score"] >= 0.7, metrics
    with open(os.path.join(spec.workdir, "predictions.jsonl")) as fh:
        by_id = {r["instance_id"]: r["payload"] for r in map(json.loads, fh)}
    unseen = by_id["u1"]["words"]
    assert [w["word"] for w in unseen] == ["kitabler", "evim"]
    assert all(w["morphemes"] and w["gloss"] for w in unseen)

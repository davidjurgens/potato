"""The transformer trainers, and the held-out scorer every trainer shares.

Each trainer is fitted end to end through ``worker.run`` on a model built on
the spot (tests/helpers/tiny_hf.py), so nothing downloads, and on the CPU, so
the result does not depend on the machine's accelerator. The data is easy on
purpose: a trainer that cannot learn red from blue has a broken loop, and one
that can is what these tests need to see before checking what it wrote.
"""

import json
import os
import pickle
import random
import subprocess
import sys
import types

import pytest

from potato.training import registry, worker
from potato.training.base import (BundleRef, ResourceLimits, SchemaSpec,
                                  TrainingSpec)
from potato.training.dataset import build_bundle, schema_specs_from_config
from potato.training.evaluation import score_predictions, score_split
from potato.training.events import EXIT_CANCELLED, EXIT_OK, CollectingReporter

HAVE_HF = all(__import__("importlib").util.find_spec(m) for m in
              ("torch", "transformers", "tokenizers"))
needs_hf = pytest.mark.skipif(not HAVE_HF, reason="torch/transformers absent")

POS = ["great movie loved it", "wonderful film excellent", "so good enjoyed",
       "great charming work", "loved excellent film", "a delight"]
NEG = ["terrible movie hated it", "awful film poor", "so bad disliked",
       "poor tedious work", "hated dreadful film", "a chore"]


def _context(tmp, schemes, items, annotations):
    config = {"task_dir": str(tmp),
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": schemes}
    return config, types.SimpleNamespace(
        config=config, annotations=annotations, items=items, schemas=schemes,
        output_dir=str(tmp), phase_responses={})


def _spec(tmp, config, bundle, trainer, schema, params):
    return TrainingSpec(
        run_id="r1", trainer=trainer,
        schemas=schema_specs_from_config(config, [schema],
                                         bundle.manifest["labels"]),
        bundle_dir=bundle.root, workdir=str(tmp / "artifacts"),
        params=params, seed=3, limits=ResourceLimits(device="cpu"))


def _run(spec, should_stop=None):
    report = CollectingReporter(should_stop=should_stop)
    code = worker.run(spec, report)
    result = (report.of_type("result") or [None])[0]
    return code, result, report


def _predictions(spec):
    path = os.path.join(spec.workdir, "predictions.jsonl")
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def sentiment_project(tmp, multilabel=False):
    scheme = {"annotation_type": "multiselect" if multilabel else "radio",
              "name": "s", "description": "s",
              "labels": ["positive", "negative", "great"]}
    items, annotations = {}, []
    for rep in range(5):
        for n, text in enumerate(POS + NEG):
            iid = "i%d_%02d" % (rep, n)
            items[iid] = {"id": iid, "text": "%s %d" % (text, rep)}
            value = {"positive" if n < len(POS) else "negative": True}
            if multilabel and "great" in text:
                value["great"] = True
            annotations.append({"instance_id": iid, "user_id": "a",
                                "labels": {"s": value}})
    return _context(tmp, [scheme], items, annotations)


# ------------------------------------------------------------- scoring

class _Bundle:
    def __init__(self, splits):
        self.splits = splits

    def read_split(self, name):
        return iter(self.splits.get(name, []))


class TestHeldOutScoring:
    def test_nominal_accuracy_and_macro_f1_by_hand(self):
        rows = [{"instance_id": str(i), "targets": {"s": g}}
                for i, g in enumerate(["a", "a", "b", "b"])]
        preds = {("0", "s"): {"label": "a"}, ("1", "s"): {"label": "b"},
                 ("2", "s"): {"label": "b"}, ("3", "s"): {"label": "b"}}
        metrics, n = score_split(rows, preds, "s", "nominal")
        assert n == 4
        assert metrics["accuracy"] == pytest.approx(0.75)
        # a: P=1 R=.5 F1=2/3; b: P=2/3 R=1 F1=.8; mean = 0.7333
        assert metrics["macro_f1"] == pytest.approx((2 / 3 + 0.8) / 2)

    def test_a_missing_prediction_counts_as_wrong(self):
        """A trainer must not score higher by skipping hard items."""
        rows = [{"instance_id": "0", "targets": {"s": "a"}},
                {"instance_id": "1", "targets": {"s": "b"}}]
        metrics, _ = score_split(rows, {("0", "s"): {"label": "a"}}, "s",
                                 "nominal")
        assert metrics["accuracy"] == 0.5
        assert metrics["coverage"] == 0.5

    def test_multilabel_micro_f1(self):
        rows = [{"instance_id": "0", "targets": {"s": ["a", "b"]}},
                {"instance_id": "1", "targets": {"s": ["b"]}}]
        preds = {("0", "s"): [{"label": "a"}], ("1", "s"): [{"label": "b"},
                                                           {"label": "c"}]}
        metrics, _ = score_split(rows, preds, "s", "multilabel")
        # tp=2 fp=1 fn=1 -> P=R=2/3
        assert metrics["micro_f1"] == pytest.approx(2 / 3)
        assert metrics["exact_match"] == 0.0

    def test_spans_match_on_start_end_and_label(self):
        rows = [{"instance_id": "0", "targets": {"ner": [
            {"start": 0, "end": 4, "name": "LOC"},
            {"start": 5, "end": 9, "name": "PER"}]}}]
        preds = {("0", "ner"): [{"start": 0, "end": 4, "label": "LOC"},
                                {"start": 5, "end": 9, "label": "LOC"}]}
        metrics, _ = score_split(rows, preds, "ner", "span")
        assert metrics["precision"] == 0.5 and metrics["recall"] == 0.5

    def test_text_token_f1(self):
        rows = [{"instance_id": "0", "targets": {"t": "The cat sat."}}]
        metrics, _ = score_split(rows, {("0", "t"): "the cat"}, "t", "text")
        assert metrics["exact_match"] == 0.0
        assert metrics["token_f1"] == pytest.approx(0.8)

    def test_the_headline_avoids_the_split_a_checkpoint_was_chosen_on(self):
        bundle = _Bundle({
            "val": [{"instance_id": "v", "targets": {"s": "a"}}],
            "test": [{"instance_id": "t", "targets": {"s": "a"}}]})
        preds = {("v", "s"): {"label": "a"}, ("t", "s"): {"label": "b"}}
        schema = SchemaSpec(name="s", annotation_type="radio", kind="nominal")
        plain = score_predictions(bundle, preds, [schema])
        assert plain["heldout_metric"] == "val macro_f1"
        chosen = score_predictions(bundle, preds, [schema], selected_on="val")
        assert chosen["heldout_metric"] == "test macro_f1"
        assert chosen["heldout_score"] == 0.0


class TestSklearnRunsAreScoredOnHeldOutData:
    def test_the_worker_reports_a_val_score_not_training_accuracy(self, tmp_path):
        config, context = sentiment_project(tmp_path)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"],
                                    split_seed=1)
        spec = _spec(tmp_path, config, bundle, "sklearn-text", "s",
                     {"min_instances": 4})
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        metrics = result["metrics"]
        assert "heldout_score" in metrics
        assert metrics["heldout_metric"].startswith("val ")
        assert metrics["val_n"] == bundle.split_size("val")


# -------------------------------------------------------------- bundles

class TestBundleTargets:
    def test_a_text_target_is_what_was_written(self, tmp_path):
        """It used to be the input's name, "text_box", for every item."""
        scheme = {"annotation_type": "text", "name": "why",
                  "description": "Why?"}
        items = {"i%d" % n: {"id": "i%d" % n, "text": "x %d" % n}
                 for n in range(6)}
        annotations = [{"instance_id": iid, "user_id": "a",
                        "labels": {"why": {"text_box": "because %s" % iid}}}
                       for iid in items]
        config, context = _context(tmp_path, [scheme], items, annotations)
        bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["why"],
                                    split_spec={"train": 1.0})
        targets = {r["instance_id"]: r["targets"]["why"]
                   for r in bundle.read_split("train")}
        assert targets["i3"] == "because i3"
        assert bundle.manifest["schemas"][0]["kind"] == "text"
        assert bundle.manifest["schemas"][0]["description"] == "Why?"

    def test_a_span_bundle_declares_its_labels(self, tmp_path):
        scheme = {"annotation_type": "span", "name": "ner", "description": "",
                  "labels": ["PER", "LOC", "ORG"]}
        items = {"a": {"id": "a", "text": "bob in rome"}}
        annotations = [{"instance_id": "a", "user_id": "u", "labels": {},
                        "spans": {"ner": [
                            {"start": 0, "end": 3, "name": "PER"},
                            {"start": 7, "end": 11, "name": "LOC"}]}}]
        _, context = _context(tmp_path, [scheme], items, annotations)
        bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["ner"],
                                    split_spec={"train": 1.0})
        # Observed, not declared: ORG was never used.
        assert bundle.labels("ner") == ["LOC", "PER"]


class TestRegistry:
    def test_listing_the_trainers_imports_no_training_library(self):
        probe = ("import sys; from potato.training import registry; "
                 "rows = registry.list_trainers(); "
                 "print(sorted(r['name'] for r in rows)); "
                 "print([m for m in ('torch', 'transformers', 'peft', "
                 "'sentence_transformers') if m in sys.modules])")
        out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                             text=True, timeout=120,
                             cwd=os.path.dirname(os.path.dirname(
                                 os.path.dirname(os.path.abspath(__file__)))))
        assert out.returncode == 0, out.stderr[-1000:]
        names, loaded = out.stdout.strip().splitlines()
        for name in ("hf-text-classification", "hf-token-classification",
                     "setfit", "hf-image-classification", "llm-sft"):
            assert name in names
        assert loaded == "[]"

    def test_span_and_image_schemes_find_their_trainers(self):
        span = [t.name for t in registry.trainers_for_schema(
            {"annotation_type": "span", "name": "n"})]
        assert span == ["hf-token-classification"]
        image = [t.name for t in registry.trainers_for_schema(
            {"annotation_type": "radio", "name": "n"}, modality="image")]
        assert "hf-image-classification" in image
        assert "hf-text-classification" not in image


# ------------------------------------------------------------- trainers

TRAIN = {"epochs": 25, "batch_size": 8, "learning_rate": 3e-3,
         "min_instances": 4, "patience": None}


@needs_hf
class TestTextClassification:
    def _fit(self, tmp_path, multilabel=False, **extra):
        from tests.helpers.tiny_hf import tiny_encoder
        config, context = sentiment_project(tmp_path, multilabel)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"],
                                    split_seed=1)
        params = dict(TRAIN, model_name=tiny_encoder(str(tmp_path / "m"),
                                                     POS + NEG), **extra)
        spec = _spec(tmp_path, config, bundle, "hf-text-classification", "s",
                     params)
        return spec, _run(spec)

    def test_nominal_learns_and_writes_label_payloads(self, tmp_path):
        spec, (code, result, _) = self._fit(tmp_path)
        assert code == EXIT_OK
        assert result["metrics"]["heldout_score"] >= 0.9
        # The checkpoint was chosen on val, so the headline comes from test.
        assert result["metrics"]["heldout_metric"] == "test macro_f1"
        record = _predictions(spec)[0]
        assert record["payload"]["label"] in ("positive", "negative")
        assert 0 < record["confidence"] <= 1

    def test_multilabel_predicts_a_list_of_labels(self, tmp_path):
        spec, (code, result, _) = self._fit(tmp_path, multilabel=True)
        assert code == EXIT_OK
        assert result["metrics"]["heldout_score"] >= 0.9
        payloads = [r["payload"] for r in _predictions(spec)]
        assert all(isinstance(p, list) for p in payloads)
        assert any({"positive", "great"} <= {e["label"] for e in p}
                   for p in payloads)

    def test_lora_saves_an_adapter_and_reloads_it(self, tmp_path):
        spec, (code, result, report) = self._fit(tmp_path, lora=True)
        assert code == EXIT_OK
        files = os.listdir(os.path.join(spec.workdir, "model"))
        assert "adapter_config.json" in files
        assert any("LoRA r=16" in e["msg"] for e in report.of_type("log"))
        # Predictions came from the reloaded base model plus adapter.
        assert len(_predictions(spec)) == bundle_predict_count(spec)

    def test_cancelling_stops_the_fit(self, tmp_path, monkeypatch):
        from tests.helpers.tiny_hf import tiny_encoder
        config, context = sentiment_project(tmp_path)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"],
                                    split_seed=1)
        spec = _spec(tmp_path, config, bundle, "hf-text-classification", "s",
                     dict(TRAIN, model_name=tiny_encoder(str(tmp_path / "m"),
                                                         POS + NEG)))
        monkeypatch.setitem(worker._STOP, "requested", True)
        code, result, report = _run(spec, should_stop=lambda: True)
        assert code == EXIT_CANCELLED
        assert result is None
        assert not os.path.exists(os.path.join(spec.workdir,
                                               "predictions.jsonl"))


def bundle_predict_count(spec):
    bundle = BundleRef.load(spec.bundle_dir)
    return sum(bundle.split_size(s) for s in ("val", "test"))


@needs_hf
class TestTokenClassification:
    def test_spans_come_back_as_character_offsets(self, tmp_path):
        from tests.helpers.tiny_hf import tiny_encoder
        rng = random.Random(0)
        people, places = ["alice", "bob", "carol"], ["paris", "rome", "oslo"]
        fill = ["went", "to", "and", "then", "with", "saw", "the"]
        items, annotations, texts = {}, [], []
        for n in range(70):
            words, spans, pos = [], [], 0
            for _ in range(rng.randint(5, 30 if n % 10 == 0 else 10)):
                r = rng.random()
                w = rng.choice(people if r < .25 else places if r < .5 else fill)
                if words:
                    pos += 1
                if r < .5:
                    spans.append({"start": pos, "end": pos + len(w),
                                  "name": "PER" if r < .25 else "LOC"})
                words.append(w)
                pos += len(w)
            text = " ".join(words)
            texts.append(text)
            items["i%02d" % n] = {"id": "i%02d" % n, "text": text}
            if spans:
                annotations.append({"instance_id": "i%02d" % n, "user_id": "a",
                                    "labels": {}, "spans": {"ner": spans}})
        scheme = {"annotation_type": "span", "name": "ner", "description": "",
                  "labels": ["PER", "LOC"]}
        config, context = _context(tmp_path, [scheme], items, annotations)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["ner"], split_seed=1)
        # max_length 16 forces the long items into several windows.
        params = dict(TRAIN, epochs=20, max_length=16, stride=4,
                      model_name=tiny_encoder(str(tmp_path / "m"), texts))
        spec = _spec(tmp_path, config, bundle, "hf-token-classification",
                     "ner", params)
        code, result, report = _run(spec)
        assert code == EXIT_OK
        windows = result["metrics"]["n_windows"]
        assert windows > result["metrics"]["n_train"]
        assert result["metrics"]["heldout_score"] >= 0.9
        for record in _predictions(spec):
            text = items[record["instance_id"]]["text"]
            for span in record["payload"]:
                surface = text[span["start"]:span["end"]]
                expected = "PER" if surface in people else "LOC"
                assert surface in people + places
                assert span["label"] == expected

    def test_overlapping_gold_spans_keep_the_longest(self):
        from potato.training.trainers.hf_token_classification import \
            non_overlapping
        kept, dropped = non_overlapping([
            {"start": 0, "end": 10, "name": "ORG"},
            {"start": 0, "end": 4, "name": "PER"},
            {"start": 11, "end": 15, "name": "LOC"}])
        assert kept == [(0, 10, "ORG"), (11, 15, "LOC")]
        assert dropped == 1


@needs_hf
class TestSetFit:
    def test_few_shot_fit_through_contrastive_pairs(self, tmp_path):
        pytest.importorskip("sentence_transformers")
        from tests.helpers.tiny_hf import tiny_encoder
        config, context = sentiment_project(tmp_path)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["s"],
                                    split_seed=1)
        spec = _spec(tmp_path, config, bundle, "setfit", "s", {
            "model_name": tiny_encoder(str(tmp_path / "m"), POS + NEG),
            "epochs": 2, "batch_size": 16, "learning_rate": 1e-3,
            "num_iterations": 5, "min_instances": 4})
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        # 5 iterations x 2 partners x every train row.
        assert result["metrics"]["n_pairs"] == 10 * bundle.split_size("train")
        assert result["metrics"]["heldout_score"] >= 0.9
        with open(os.path.join(spec.workdir, "head.pkl"), "rb") as fh:
            assert pickle.load(fh)["multilabel"] is False

    def test_multilabel_pairs_are_scored_by_jaccard(self):
        from potato.training.trainers.setfit_trainer import make_pairs
        pairs = make_pairs(["a", "b", "c"], [["x", "y"], ["x"], ["z"]], True,
                           iterations=3, seed=0, limit=0)
        sims = {(p[0], p[1]): p[2] for p in pairs}
        assert sims.get(("a", "b"), 0.5) == 0.5
        assert all(s == 0.0 for (x, y), s in sims.items()
                   if "c" in (x, y))


@needs_hf
class TestImageClassification:
    def test_vit_learns_colours_and_skips_images_it_cannot_read(self, tmp_path):
        pytest.importorskip("PIL")
        from tests.helpers.tiny_hf import colour_images, tiny_vit
        images = colour_images(str(tmp_path / "images"), 60)
        items, annotations = {}, []
        for n, (path, label) in enumerate(images):
            iid = "i%02d" % n
            items[iid] = {"id": iid, "image": os.path.relpath(path, tmp_path)}
            annotations.append({"instance_id": iid, "user_id": "a",
                                "labels": {"c": {label: True}}})
        for n in range(4):
            items["remote%d" % n] = {"id": "remote%d" % n,
                                     "image": "https://example.org/%d.png" % n}
        scheme = {"annotation_type": "radio", "name": "c", "description": "",
                  "labels": ["red", "blue"]}
        config, context = _context(tmp_path, [scheme], items, annotations)
        config["item_properties"]["text_key"] = "image"
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["c"],
                                    split_seed=1, include_unlabeled=True)
        assert bundle.modality == "image"
        spec = _spec(tmp_path, config, bundle, "hf-image-classification", "c",
                     dict(TRAIN, epochs=15,
                          model_name=tiny_vit(str(tmp_path / "m"))))
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        assert result["metrics"]["heldout_score"] >= 0.9
        predicted = {r["instance_id"] for r in _predictions(spec)}
        # Remote images are unlabeled and unreadable: no prediction at all,
        # rather than a confident guess about a picture never seen.
        assert not any(i.startswith("remote") for i in predicted)
        assert predicted


@needs_hf
class TestLLMSFT:
    def test_full_finetune_learns_to_answer_and_generates(self, tmp_path):
        from tests.helpers.tiny_hf import tiny_causal_lm
        rng = random.Random(0)
        words = ["paris", "rome", "oslo", "lima", "cairo", "delhi"]
        items, annotations, texts = {}, [], ["which city comes first ? answer :"]
        for n in range(80):
            ws = [rng.choice(words) for _ in range(4)]
            texts.append(" ".join(ws))
            items["i%02d" % n] = {"id": "i%02d" % n, "text": " ".join(ws)}
            annotations.append({"instance_id": "i%02d" % n, "user_id": "a",
                                "labels": {"first": {"text_box": ws[0]}}})
        scheme = {"annotation_type": "text", "name": "first",
                  "description": "Which city comes first?"}
        config, context = _context(tmp_path, [scheme], items, annotations)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"),
                                    ["first"], split_seed=1)
        spec = _spec(tmp_path, config, bundle, "llm-sft", "first", dict(
            TRAIN, epochs=30, lora=False, gradient_accumulation=1,
            max_new_tokens=4,
            model_name=tiny_causal_lm(str(tmp_path / "m"), texts)))
        code, result, _ = _run(spec)
        assert code == EXIT_OK
        assert result["metrics"]["heldout_score"] >= 0.9
        assert result["metrics"]["heldout_metric"] == "test token_f1"
        records = _predictions(spec)
        right = sum(r["payload"] == items[r["instance_id"]]["text"].split()[0]
                    for r in records)
        # Generated text, decoded and cut at the end-of-answer token.
        assert right >= 0.85 * len(records)

    def test_the_loss_covers_the_answer_only(self):
        from potato.training.trainers.llm_sft import encode_example
        from tests.helpers.tiny_hf import build_tokenizer
        tok = build_tokenizer(["a b c d e answer here"])
        tok.eos_token = "<eos>"
        example = encode_example(tok, "a b c d e", "answer here", 64)
        n_prompt = len(tok("a b c d e", add_special_tokens=False)["input_ids"])
        assert example["labels"][:n_prompt] == [-100] * n_prompt
        assert example["labels"][n_prompt:] == example["input_ids"][n_prompt:]
        # A long prompt is cut from the left; the answer survives whole.
        long = encode_example(tok, " ".join(["a"] * 100), "answer here", 16)
        assert len(long["input_ids"]) == 16
        assert long["input_ids"][-3:] == long["labels"][-3:]

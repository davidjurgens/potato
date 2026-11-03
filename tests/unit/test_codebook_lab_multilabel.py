"""
Tests for codebook_lab's multi-label support: platinum loading, scoring
(label canonicalization, invalid labels, exact match), F1 metrics, the
hybridizer ranking by per-label F1, and single-label backward compat.
"""

import json

import pytest
import yaml

from potato.codebook_lab import io_utils
from potato.codebook_lab.hybridizer import build_hybrid
from potato.codebook_lab.models import (
    Code, CodebookVariant, ExamplePrediction, PlatinumExample, VariantScore,
)
from potato.codebook_lab.scorer import score_variant


LABELS = ["joy", "gratitude", "neutral"]


class FakeEndpoint:
    """Returns a canned response per text, as a JSON string (the shape
    most real endpoints return)."""

    def __init__(self, by_text):
        self.by_text = by_text
        self.prompts = []

    def query(self, prompt, schema):
        self.prompts.append(prompt)
        for text, resp in self.by_text.items():
            if text in prompt:
                if isinstance(resp, Exception):
                    raise resp
                return json.dumps(resp)
        raise AssertionError("unexpected prompt")


def _variant(vid="v", defs=None):
    defs = defs or {}
    return CodebookVariant(
        variant_id=vid,
        codes=[Code(name=l, definition=defs.get(l, f"{l} def")) for l in LABELS])


def _pred(gold, pred):
    return ExamplePrediction(
        example_id="x", true_label=gold[0],
        predicted_label=pred[0] if pred else None,
        correct=set(gold) == set(pred),
        true_labels=list(gold), predicted_labels=list(pred))


class TestPlatinumLoading:
    def test_accepts_label_and_labels(self, tmp_path):
        p = tmp_path / "plat.yaml"
        p.write_text(yaml.safe_dump([
            {"id": "a", "text": "t1", "label": "joy"},
            {"id": "b", "text": "t2", "labels": ["joy", "gratitude"]},
        ]))
        ex = io_utils.load_platinum_examples(str(p), LABELS, multi_label=True)
        assert ex[0].labels == ["joy"]
        assert ex[1].labels == ["joy", "gratitude"]
        assert ex[1].to_dict()["labels"] == ["joy", "gratitude"]
        assert ex[0].to_dict() == {"id": "a", "text": "t1", "label": "joy"}

    def test_multi_label_item_rejected_in_single_label_mode(self, tmp_path):
        p = tmp_path / "plat.yaml"
        p.write_text(yaml.safe_dump([
            {"id": "b", "text": "t2", "labels": ["joy", "gratitude"]}]))
        with pytest.raises(ValueError, match="task_type: multi_label"):
            io_utils.load_platinum_examples(str(p), LABELS)

    def test_unknown_label_in_list_rejected(self, tmp_path):
        p = tmp_path / "plat.yaml"
        p.write_text(yaml.safe_dump([
            {"id": "b", "text": "t2", "labels": ["joy", "awe"]}]))
        with pytest.raises(ValueError, match="awe"):
            io_utils.load_platinum_examples(str(p), LABELS, multi_label=True)


class TestMultiLabelScoring:
    def test_canonicalizes_and_flags_invalid(self):
        examples = [
            PlatinumExample("1", "thanks so much!", ["gratitude", "joy"]),
            PlatinumExample("2", "ok then", ["neutral"]),
            PlatinumExample("3", "yay", ["joy"]),
        ]
        ep = FakeEndpoint({
            "thanks so much!": {"labels": [" Joy", "GRATITUDE", "joy"]},
            "ok then": {"labels": ["neutral", "boredom"]},
            "yay": {"labels": ["joy", "gratitude"]},
        })
        score = score_variant(ep, _variant(), "task", examples, multi_label=True)
        p1, p2, p3 = score.predictions
        # De-duplicated, codebook order, case/space-insensitive.
        assert p1.predicted_labels == ["joy", "gratitude"] and p1.correct
        # Right label but a hallucinated extra one: not an exact match.
        assert p2.predicted_labels == ["neutral"]
        assert p2.invalid_labels == ["boredom"] and not p2.correct
        # Over-labeling: extra valid label.
        assert not p3.correct
        assert score.overall_accuracy == pytest.approx(1 / 3)
        assert "Select every label that applies" in ep.prompts[0]

    def test_failed_call_counts_as_no_prediction(self):
        examples = [PlatinumExample("1", "hello", ["joy", "gratitude"])]
        ep = FakeEndpoint({"hello": RuntimeError("boom")})
        score = score_variant(ep, _variant(), "task", examples, multi_label=True)
        p = score.predictions[0]
        assert p.error == "boom" and p.predicted_labels == []
        assert p.true_labels == ["joy", "gratitude"]
        assert score.per_label_counts() == {
            "joy": {"tp": 0, "fp": 0, "fn": 1},
            "gratitude": {"tp": 0, "fp": 0, "fn": 1},
        }


class TestMetrics:
    def test_per_label_f1_and_macro(self):
        s = VariantScore("v", multi_label=True, predictions=[
            _pred(["joy"], ["joy", "gratitude"]),  # joy tp, gratitude fp
            _pred(["gratitude"], ["gratitude"]),   # gratitude tp
            _pred(["neutral"], ["joy"]),           # neutral fn, joy fp
        ])
        f1 = s.per_label_f1()
        assert f1["joy"] == pytest.approx(2 / 3)        # 2*1/(2+1+0)
        assert f1["gratitude"] == pytest.approx(2 / 3)  # 2*1/(2+1+0)
        assert f1["neutral"] == 0.0
        assert s.overall_score == pytest.approx((2 / 3 + 2 / 3 + 0) / 3)
        assert s.per_label_score() == f1
        assert s.metric_name == "F1"

    def test_label_with_no_gold_not_scored(self):
        s = VariantScore("v", multi_label=True, predictions=[
            _pred(["joy"], ["joy", "neutral"])])
        assert set(s.per_label_f1()) == {"joy"}

    def test_roundtrip(self):
        s = VariantScore("v", multi_label=True, predictions=[
            _pred(["joy", "gratitude"], ["joy"])])
        back = VariantScore.from_dict(json.loads(json.dumps(s.to_dict())))
        assert back.multi_label
        assert back.per_label_f1() == s.per_label_f1()
        assert back.predictions[0].true_labels == ["joy", "gratitude"]

    def test_single_label_unchanged(self):
        s = VariantScore("v", predictions=[
            ExamplePrediction("1", "joy", "joy", True),
            ExamplePrediction("2", "joy", "neutral", False),
        ])
        assert s.overall_score == s.overall_accuracy == 0.5
        assert s.per_label_score() == {"joy": 0.5}
        d = s.to_dict()
        assert "macro_f1" not in d and "true_labels" not in d["predictions"][0]


class TestHybridizerMultiLabel:
    def test_picks_best_f1_per_label(self):
        a = _variant("a", {"joy": "A-joy", "gratitude": "A-grat"})
        b = _variant("b", {"joy": "B-joy", "gratitude": "B-grat"})
        # a is perfect on joy but over-applies it onto gratitude items;
        # b never over-applies joy but misses half of it.
        sa = VariantScore("a", multi_label=True, predictions=[
            _pred(["joy"], ["joy"]),
            _pred(["joy"], ["joy"]),
            _pred(["gratitude"], ["joy"]),
            _pred(["gratitude"], ["joy"]),
        ])
        sb = VariantScore("b", multi_label=True, predictions=[
            _pred(["joy"], ["joy"]),
            _pred(["joy"], []),
            _pred(["gratitude"], ["gratitude"]),
            _pred(["gratitude"], ["gratitude"]),
        ])
        # joy F1: a = 2*2/(4+2) = .667, b = 2/(2+0+1) = .667 -> tie, b wins
        # on macro-F1 (b: (.667+1)/2 vs a: (.667+0)/2). gratitude: b.
        hybrid = build_hybrid([a, b], [sa, sb])
        assert hybrid.code("joy").definition == "B-joy"
        assert hybrid.code("gratitude").definition == "B-grat"

    def test_over_labeling_loses_on_f1(self):
        a = _variant("a", {"joy": "A-joy"})
        b = _variant("b", {"joy": "B-joy"})
        # Both catch every joy item; a also slaps joy on everything else.
        sa = VariantScore("a", multi_label=True, predictions=[
            _pred(["joy"], ["joy"]), _pred(["neutral"], ["neutral", "joy"])])
        sb = VariantScore("b", multi_label=True, predictions=[
            _pred(["joy"], ["joy"]), _pred(["neutral"], ["neutral"])])
        assert build_hybrid([a, b], [sa, sb]).code("joy").definition == "B-joy"


class TestCliMultiLabel:
    def test_end_to_end_with_fake_endpoint(self, tmp_path, monkeypatch, capsys):
        from potato.codebook_lab import cli

        (tmp_path / "seed.yaml").write_text(yaml.safe_dump(
            [Code(name=l, definition=f"{l} def").to_dict() for l in LABELS]))
        (tmp_path / "plat.yaml").write_text(yaml.safe_dump([
            {"id": "1", "text": "thank you, so happy", "labels": ["gratitude", "joy"]},
            {"id": "2", "text": "fine", "labels": ["neutral"]},
        ]))
        (tmp_path / "exp.yaml").write_text(yaml.safe_dump({
            "seed_codebook": "seed.yaml",
            "platinum_examples": "plat.yaml",
            "task_type": "multi_label",
            "task_description": "Label emotions.",
            "output_dir": "run",
            "generation_model": {"endpoint_type": "ollama", "model": "m"},
        }))
        variants_dir = tmp_path / "run" / "variants"
        variants_dir.mkdir(parents=True)
        (variants_dir / "v01.json").write_text(json.dumps(
            _variant("v01").to_dict()))

        ep = FakeEndpoint({
            "thank you, so happy": {"labels": ["gratitude", "joy"]},
            "fine": {"labels": ["neutral"]},
        })
        monkeypatch.setattr(cli, "_build_endpoint", lambda *a, **k: ep)

        result = cli.run_experiment(str(tmp_path / "exp.yaml"))
        assert result["hybrid_score"].multi_label
        assert result["hybrid_score"].overall_score == 1.0
        saved = json.loads((tmp_path / "run" / "scores" / "seed.json").read_text())
        assert saved["multi_label"] and saved["macro_f1"] == 1.0
        assert "macro-F1" in capsys.readouterr().out

    def test_rejects_unknown_task_type(self, tmp_path):
        from potato.codebook_lab import cli

        (tmp_path / "seed.yaml").write_text(yaml.safe_dump(
            [Code(name="joy", definition="d").to_dict()]))
        (tmp_path / "plat.yaml").write_text(yaml.safe_dump(
            [{"id": "1", "text": "t", "label": "joy"}]))
        (tmp_path / "exp.yaml").write_text(yaml.safe_dump({
            "seed_codebook": "seed.yaml", "platinum_examples": "plat.yaml",
            "task_type": "multilabel"}))
        with pytest.raises(ValueError, match="task_type"):
            cli.run_experiment(str(tmp_path / "exp.yaml"))

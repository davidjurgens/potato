"""Training on agent traces: corrected trajectories and per-step rewards.

``trajectory_edit`` answers are (original, corrected) pairs: ``llm-sft``
learns to write the correction from the original, ``llm-dpo`` to prefer it.
``process_reward`` answers are one rating per step: ``prm-reward`` learns to
give them, and its written-back ratings are what the scheme's AI pre-label
button offers.

The models are built on the spot (tests/helpers/tiny_hf.py) and run on the
CPU. The data is easy on purpose: a step with the word "bad" in it is wrong,
and the correction always replaces "wrong" with "right".
"""

import json
import random

import pytest

from potato.training import registry
from potato.training.dataset import build_bundle
from potato.training.evaluation import score_split
from potato.training.events import EXIT_OK
from tests.unit.test_training_trainers import (_context, _predictions, _run,
                                               _spec)

HAVE = __import__("importlib").util.find_spec
needs_torch = pytest.mark.skipif(not (HAVE("torch") and HAVE("transformers")),
                                 reason="torch/transformers absent")

TRAJ = {"annotation_type": "trajectory_edit", "name": "fix",
        "description": "Correct the agent's steps.", "steps_key": "steps"}
PRM = {"annotation_type": "process_reward", "name": "prm",
       "description": "Rate each step.", "steps_key": "steps",
       "mode": "per_step"}
WORDS = ["open", "the", "file", "read", "line", "search", "docs", "write",
         "test", "run", "check", "output"]


def _edit(index, original, edited):
    return {"step_index": index, "field": "action", "edited": True,
            "original_text": original, "edited_text": edited}


def trajectory_project(tmp, n=40, unedited_every=8):
    rng = random.Random(0)
    items, annotations, texts = {}, [], ["task", "step", "action", "right",
                                         "wrong", "final_answer"]
    for i in range(n):
        iid = "t%03d" % i
        first = " ".join(rng.sample(WORDS, 3))
        second = " ".join(rng.sample(WORDS, 2))
        steps = [{"action": first}, {"action": "%s wrong" % second}]
        items[iid] = {"id": iid, "task": "task %d" % (i % 5), "steps": steps}
        edits = [] if i % unedited_every == unedited_every - 1 else [
            _edit(1, "%s wrong" % second, "%s right" % second)]
        blob = json.dumps({"steps": edits, "n_steps_edited": len(edits)})
        annotations.append({"instance_id": iid, "user_id": "u",
                            "labels": {"fix": {"fix": blob}}})
        texts += [first, second, "task %d" % (i % 5)]
    config, context = _context(tmp, [TRAJ], items, annotations)
    return config, context, texts


def prm_project(tmp, n=48):
    rng = random.Random(1)
    items, annotations, texts = {}, [], ["task", "step", "action", "bad"]
    for i in range(n):
        iid = "p%03d" % i
        steps, rewards = [], []
        for s in range(rng.randint(2, 4)):
            words = rng.sample(WORDS, 3)
            if rng.random() < 0.35:
                words.insert(1, "bad")
            steps.append({"action": " ".join(words)})
            rewards.append(-1 if "bad" in words else 1)
            texts.append(" ".join(words))
        items[iid] = {"id": iid, "task": "task", "steps": steps}
        blob = {"steps": [{"index": k, "reward": r} for k, r in enumerate(rewards)],
                "mode": "per_step"}
        if i % 7 == 0:
            blob["steps"] = blob["steps"][:1]  # a partly rated trace
        annotations.append({"instance_id": iid, "user_id": "u",
                            "labels": {"prm": {"prm": json.dumps(blob)}}})
    config, context = _context(tmp, [PRM], items, annotations)
    return config, context, texts


# ------------------------------------------------------------- kinds

class TestKinds:
    def test_trajectory_edit_and_process_reward_are_trainable(self):
        assert registry.kind_of_schema(TRAJ) == "trajectory"
        assert registry.kind_of_schema(PRM) == "trace"
        assert {t.name for t in registry.trainers_for_schema(TRAJ)} == {
            "llm-sft", "llm-dpo"}
        assert [t.name for t in registry.trainers_for_schema(PRM)] == ["prm-reward"]

    def test_prm_reward_is_offered_only_for_process_reward(self):
        """Other agent-trace types share the trace kind with process_reward
        for agreement, and have no per-step reward to learn."""
        other = {"annotation_type": "trajectory_eval", "name": "e"}
        assert registry.kind_of_schema(other) == "trace"
        assert "prm-reward" not in {t.name for t in
                                    registry.trainers_for_schema(other)}


# ----------------------------------------------------------- bundles

class TestBundleTargets:
    def test_a_correction_is_chosen_over_the_original(self, tmp_path):
        _, context, _ = trajectory_project(tmp_path, n=8)
        bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["fix"])
        rows = [r for s in ("train", "val", "test") for r in bundle.read_split(s)]
        # Every eighth trace was not edited: nothing to learn, left out.
        assert len(rows) == 7 and stats.n_skipped_no_label == 1
        row = rows[0]
        target = row["targets"]["fix"]
        assert target["chosen"].endswith("right") and "wrong" not in target["chosen"]
        assert target["rejected"].endswith("wrong")
        assert row["candidates"] == [target["chosen"], target["rejected"]]
        assert row["prompt"].startswith("task ")
        # The SFT input is the task and the ORIGINAL steps.
        assert "wrong" in row["text"] and row["text"].startswith(row["prompt"])

    def test_step_rewards_keep_their_positions(self, tmp_path):
        _, context, _ = prm_project(tmp_path, n=8)
        bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["prm"])
        rows = {r["instance_id"]: r for s in ("train", "val", "test")
                for r in bundle.read_split(s)}
        item = context.items["p000"]
        rewards = rows["p000"]["targets"]["prm"]
        # p000 had only its first step rated.
        assert len(rewards) == len(item["steps"])
        assert rewards[0] in (-1, 1) and all(r is None for r in rewards[1:])
        assert rows["p001"]["trace"]["steps"][0].startswith("action: ")

    def test_unlabelled_traces_carry_their_inputs(self, tmp_path):
        config, context, _ = prm_project(tmp_path, n=6)
        context.items["extra"] = {"id": "extra", "task": "task",
                                  "steps": [{"action": "read the file"}]}
        bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["prm"],
                                    include_unlabeled=True)
        (row,) = bundle.read_split("unlabeled")
        assert row["trace"]["steps"] == ["action: read the file"]


# ------------------------------------------------------------ scoring

class TestScoring:
    def test_trace_scores_by_hand(self):
        rows = [{"instance_id": "a", "targets": {"prm": [1, -1, -1]}},
                {"instance_id": "b", "targets": {"prm": [1, None, 1]}}]
        steps = lambda *r: {"steps": [{"index": i, "reward": v}
                                      for i, v in enumerate(r)]}
        predictions = {("a", "prm"): steps(1, 1, -1), ("b", "prm"): steps(1, -1, 1)}
        metrics, n = score_split(rows, predictions, "prm", "trace")
        assert n == 2
        # 5 rated steps, 4 right.
        assert metrics["step_accuracy"] == pytest.approx(0.8)
        assert metrics["n_steps"] == 5
        # a: first wrong step 1 vs predicted 2 -> miss. b: none vs none
        # (the unrated step 1 is not compared) -> hit.
        assert metrics["first_error_accuracy"] == pytest.approx(0.5)
        # macro-F1 over {-1, 1}: -1 P=1 R=.5 F=.667; 1 P=.75 R=1 F=.857
        assert metrics["step_macro_f1"] == pytest.approx((2 / 3 + 6 / 7) / 2, abs=1e-3)

    def test_trajectory_scores_for_a_preferrer_and_a_writer(self):
        rows = [{"instance_id": i, "targets": {"fix": {
            "chosen": "step one right", "rejected": "step one wrong"}}}
            for i in ("a", "b")]
        prefer = {("a", "fix"): {"label": "A"}, ("b", "fix"): {"label": "B"}}
        metrics, _ = score_split(rows, prefer, "fix", "trajectory")
        assert metrics["closer_to_correction"] == 0.5 and "token_f1" not in metrics
        write = {("a", "fix"): "step one right", ("b", "fix"): "step one wrong"}
        metrics, _ = score_split(rows, write, "fix", "trajectory")
        assert metrics["closer_to_correction"] == 0.5
        assert metrics["token_f1"] == pytest.approx((1 + 2 / 3) / 2)


# ------------------------------------------------------------ trainers

@needs_torch
class TestPRMReward:
    def test_learns_which_steps_are_wrong(self, tmp_path):
        from tests.helpers.tiny_hf import tiny_encoder
        config, context, texts = prm_project(tmp_path, n=240)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["prm"],
                                    split_seed=2)
        spec = _spec(tmp_path, config, bundle, "prm-reward", "prm",
                     {"model_name": tiny_encoder(str(tmp_path / "m"), texts),
                      "epochs": 30, "batch_size": 8, "learning_rate": 3e-3,
                      "patience": None, "min_instances": 4, "max_length": 128})
        code, result, report = _run(spec)
        assert code == EXIT_OK, report.of_type("error")
        metrics = result["metrics"]
        assert metrics["heldout_metric"] == "test step_macro_f1"
        assert metrics["heldout_score"] >= 0.9
        record = _predictions(spec)[0]
        steps = record["payload"]["steps"]
        assert {s["reward"] for s in steps} <= {-1, 0, 1}
        assert all(s["source"] == "model" and 0 < s["confidence"] <= 1
                   for s in steps)
        assert record["confidence"] == min(s["confidence"] for s in steps)

    def test_the_default_max_length_is_lowered_to_what_the_model_holds(
            self, tmp_path):
        # The tiny encoder has 128 positions, the default max_length is
        # 1024, and the first trace runs past 128 tokens. Unclamped, fit
        # fails on the position table (distilroberta: "index 514 is out of
        # bounds").
        from tests.helpers.tiny_hf import tiny_encoder
        config, context, texts = prm_project(tmp_path, n=24)
        long_step = {"action": " ".join(WORDS * 12)}
        context.items["p000"]["steps"] = [long_step, {"action": "run test"}]
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["prm"])
        spec = _spec(tmp_path, config, bundle, "prm-reward", "prm",
                     {"model_name": tiny_encoder(str(tmp_path / "m"), texts),
                      "epochs": 1, "batch_size": 8, "min_instances": 4})
        code, result, report = _run(spec)
        assert code == EXIT_OK, report.of_type("error")
        warnings = [e["msg"] for e in report.of_type("log")
                    if e.get("level") == "warning"]
        assert any("max_length=1024" in w and "using 128" in w
                   for w in warnings), warnings

    def test_step_coverage_counts_steps_not_traces(self):
        rows = [{"instance_id": "a", "targets": {"prm": [1, -1, -1, 1]}}]
        # The trace has a prediction, but only for its first two steps.
        predictions = {("a", "prm"): {"steps": [{"index": 0, "reward": 1},
                                                {"index": 1, "reward": -1}]}}
        metrics, _ = score_split(rows, predictions, "prm", "trace")
        assert metrics["coverage"] == 1.0
        assert metrics["step_coverage"] == 0.5

    def test_an_empty_step_is_not_blamed_on_max_length(self):
        from potato.training.trainers.prm_reward import PRMRewardTrainer

        class Tok:
            def __call__(self, text, **kw):
                words, offsets, at = text.split(), [], 0
                for w in words:
                    at = text.index(w, at)
                    offsets.append((at, at + len(w)))
                    at += len(w)
                return {"input_ids": list(range(len(words))),
                        "offset_mapping": offsets,
                        "special_tokens_mask": [0] * len(words)}

        encoded = PRMRewardTrainer._encode(
            Tok(), {"task": "t", "steps": ["aa", "", "bb"]}, 512)
        assert encoded["positions"][1] is None
        assert encoded["empty"] == [False, True, False]

    def test_a_cut_off_step_is_not_rated(self):
        from potato.training.trainers.prm_reward import step_tokens, trace_text
        text, spans = trace_text({"task": "t", "steps": ["aa bb", "cc dd"]})
        assert text[spans[1][0]:spans[1][1]] == "cc dd"
        # Tokens: every word, then the input stops inside step 2.
        words = [(i, i + 2) for i in range(len(text)) if text[i:i + 2] in
                 ("aa", "bb", "cc")]
        positions = step_tokens(words, [False] * len(words), spans)
        assert positions[0] == 1 and positions[1] is None


@needs_torch
class TestTrajectoryLLMs:
    def test_dpo_learns_to_prefer_the_correction(self, tmp_path):
        pytest.importorskip("peft")
        from tests.helpers.tiny_hf import tiny_causal_lm
        config, context, texts = trajectory_project(tmp_path, n=80)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["fix"],
                                    split_seed=1)
        spec = _spec(tmp_path, config, bundle, "llm-dpo", "fix",
                     {"model_name": tiny_causal_lm(str(tmp_path / "m"), texts),
                      "epochs": 6, "batch_size": 8, "gradient_accumulation": 1,
                      "beta": 0.5, "learning_rate": 1e-3, "patience": None,
                      "min_instances": 4})
        code, result, report = _run(spec)
        assert code == EXIT_OK, report.of_type("error")
        metrics = result["metrics"]
        assert metrics["heldout_metric"] == "test closer_to_correction"
        assert metrics["heldout_score"] >= 0.9

    def test_sft_writes_steps_and_is_scored_against_the_correction(self, tmp_path):
        pytest.importorskip("peft")
        from tests.helpers.tiny_hf import tiny_causal_lm
        config, context, texts = trajectory_project(tmp_path, n=40)
        bundle, _, _ = build_bundle(context, str(tmp_path / "bundle"), ["fix"],
                                    split_seed=1)
        spec = _spec(tmp_path, config, bundle, "llm-sft", "fix",
                     {"model_name": tiny_causal_lm(str(tmp_path / "m"), texts),
                      "epochs": 2, "batch_size": 4, "gradient_accumulation": 1,
                      "learning_rate": 1e-3, "patience": None,
                      "min_instances": 4, "max_new_tokens": 24})
        code, result, report = _run(spec)
        assert code == EXIT_OK, report.of_type("error")
        metrics = result["metrics"]
        assert metrics["heldout_metric"] == "test closer_to_correction"
        assert "test_token_f1" in metrics
        assert isinstance(_predictions(spec)[0]["payload"], str)


class TestWritebackCheck:
    def test_a_trajectory_scheme_cannot_be_published(self):
        from potato.training.config_check import training_config_problems
        config = {"annotation_schemes": [TRAJ, PRM],
                  "model_training": {"enabled": True,
                                     "writeback": {"schemas": ["fix", "prm"]}}}
        problems = training_config_problems(config)
        assert any("'fix'" in p and "no prelabel display" in p for p in problems)
        # process_reward is shown through its AI pre-label button.
        assert not any("'prm'" in p for p in problems)

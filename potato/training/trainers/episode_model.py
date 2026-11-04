"""Robot episode phases, outcomes and reward curves from episode_annotation answers.

For ``episode_annotation`` schemes. Each annotated episode is one example:
its numeric series (joint positions, gripper state, forces, whatever the
LeRobot dataset, HDF5 demo or episode manifest records), one row per frame
at the episode's frame rate, each series standardized. Video is not read:
the model learns from what the robot measured, not from what the cameras
saw, so a phase that only looks different (and is not different in the
joints) is not one it can find.

The network is a convolution over the series, a bidirectional GRU, and
three heads, one per layer of the answer:

* **phase**, per frame, with "no phase" between phases;
* **outcome**, once per episode, from the mean of the GRU's states;
* **reward**, per frame, regressed on the annotator's curve where it was
  drawn (outside the drawn range the annotator said nothing, so nothing is
  learned there).

A layer an episode's answer leaves empty is left out of that episode's loss.
Predictions are the stored answer's shape (phases, outcome, a reward curve
sampled ``reward_points`` times), written back as a pre-filled answer to
accept or correct. Needs torch, and the reader for the episode format
(pyarrow for LeRobot, h5py for HDF5).
"""

from __future__ import annotations

import os
import random
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf
from potato.training.trainers import _science_common as sc

INSTALL_HINT = "pip install 'potato-annotation[train-vision]'"
_NEEDS = ("torch", "numpy")


def _build(features: int, hidden: int, phases: int, outcomes: int):
    import torch
    from torch import nn

    class EpisodeNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv1d(max(1, features), hidden, 5, padding=2), nn.ReLU(inplace=True),
                nn.Conv1d(hidden, hidden, 5, padding=2), nn.ReLU(inplace=True))
            self.gru = nn.GRU(hidden, hidden, batch_first=True, bidirectional=True)
            self.phase = nn.Linear(2 * hidden, phases)
            self.outcome = nn.Linear(2 * hidden, max(1, outcomes))
            self.reward = nn.Linear(2 * hidden, 1)

        def forward(self, x, mask):
            # x: B x T x F, mask: B x T (1 where the frame is real)
            z = self.conv(x.transpose(1, 2)).transpose(1, 2)
            states, _ = self.gru(z)
            weights = mask[..., None]
            pooled = (states * weights).sum(1) / weights.sum(1).clamp(min=1.0)
            return self.phase(states), self.outcome(pooled), self.reward(states)[..., 0]

    return EpisodeNet()


def _frame_targets(target, frames: int, fps: float, phases: List[str], rng_reward):
    """Per-frame phase index (0 is none, -100 past the end) and reward with
    its mask, from one episode's target."""
    import numpy
    times = numpy.arange(frames) / fps
    phase = numpy.zeros(frames, dtype="int64")
    for p in target.get("phases") or []:
        if p["label"] in phases:
            phase[(times >= p["start"]) & (times < p["end"])] = phases.index(p["label"]) + 1
    reward = numpy.zeros(frames, dtype="float32")
    reward_mask = numpy.zeros(frames, dtype="float32")
    points = target.get("reward") or []
    if len(points) >= 2:
        ts = numpy.asarray([p["t"] for p in points])
        vs = numpy.asarray([p["value"] for p in points])
        inside = (times >= ts[0]) & (times <= ts[-1])
        reward[inside] = (numpy.interp(times[inside], ts, vs) - rng_reward[0]) / max(
            rng_reward[1] - rng_reward[0], 1e-9)
        reward_mask[inside] = 1.0
    return phase, reward, reward_mask


class EpisodeModelTrainer(Trainer):
    name: ClassVar[str] = "episode-model"
    description: ClassVar[str] = (
        "Robot episodes: a GRU over the recorded joint and sensor series that "
        "marks phases, predicts the outcome and draws the reward curve, from "
        "episode_annotation answers.")
    kinds: ClassVar[Tuple[str, ...]] = ("episode",)
    modalities: ClassVar[Tuple[str, ...]] = ("episode",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "BSD-3-Clause"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"epochs": 40, "batch_size": 4, "learning_rate": 1e-3, "weight_decay": 1e-4,
                "warmup_ratio": 0.05, "patience": 8, "precision": "fp32",
                "hidden": 64, "max_frames": 2000, "phase_weight": 1.0,
                "outcome_weight": 1.0, "reward_weight": 1.0, "reward_points": 50,
                "min_instances": 5}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = {key: hf.COMMON_PARAMS[key] for key in
                 ("epochs", "batch_size", "weight_decay", "warmup_ratio", "patience",
                  "precision", "min_instances")}
        props["epochs"] = dict(props["epochs"], default=40)
        props["batch_size"] = dict(props["batch_size"], default=4,
                                   description="Episodes per step.")
        props["patience"] = dict(props["patience"], default=8)
        props["precision"] = dict(props["precision"], default="fp32")
        props["min_instances"] = dict(props["min_instances"], default=5,
                                      description="Annotated episodes needed in the "
                                                  "train split.")
        props.update({
            "learning_rate": {"type": "number", "exclusiveMinimum": 0, "default": 1e-3},
            "hidden": {"type": "integer", "minimum": 8, "default": 64,
                       "description": "GRU state size."},
            "max_frames": {"type": "integer", "minimum": 16, "default": 2000,
                           "description": "Longest stretch trained on at once; longer "
                                          "episodes are cropped at random."},
            "phase_weight": {"type": "number", "minimum": 0, "default": 1.0},
            "outcome_weight": {"type": "number", "minimum": 0, "default": 1.0},
            "reward_weight": {"type": "number", "minimum": 0, "default": 1.0},
            "reward_points": {"type": "integer", "minimum": 2, "default": 50,
                              "description": "Points in a predicted reward curve."},
        })
        return {"type": "object", "properties": props, "additionalProperties": False}

    @classmethod
    def server_params(cls, config, schema_names, params) -> Dict[str, Any]:
        for scheme in (config or {}).get("annotation_schemes") or []:
            if isinstance(scheme, dict) and schema_names and \
                    scheme.get("name") == schema_names[0]:
                layers = scheme.get("layers") or ["phases", "outcome", "reward"]
                try:
                    low, high = (float(v) for v in scheme.get("reward_range", [0.0, 1.0]))
                except (TypeError, ValueError):
                    low, high = 0.0, 1.0
                return {"_reward_range": [low, high], "_layers": list(layers)}
        return {}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        if schema.kind not in self.kinds:
            return ["Schema %r is %s; this trainer learns episode_annotation answers."
                    % (schema.name, schema.kind)]
        rows = [r for r in hf.rows_with_target(bundle.read_split("train"), schema.name)
                if sc.has_input(r, bundle.resolve_media(r["media"]) if r.get("media")
                                else None)]
        if len(rows) < int(params["min_instances"]):
            return ["Only %d annotated episodes with a readable file in the train split; "
                    "this trainer needs at least %d."
                    % (len(rows), int(params["min_instances"]))]
        return []

    # ------------------------------------------------------------ data

    def _episode(self, row, media, names):
        episode = sc.episode_of(row, media)
        names, array = sc.episode_array(episode, names)
        if not names:
            raise TrainerError("the episode has no numeric series")
        return {"row": row, "episode": episode, "array": array, "names": names,
                "fps": float(episode.fps or 30.0), "frames": array.shape[0]}

    def _episodes(self, bundle, split, names, report):
        out, unreadable = [], []
        for row in hf.rows_with_target(bundle.read_split(split), self._schema):
            media = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not sc.has_input(row, media):
                unreadable.append(row["instance_id"])
                continue
            try:
                out.append(self._episode(row, media, names))
            except Exception as exc:  # noqa: BLE001 - one bad episode is one row
                unreadable.append("%s (%s)" % (row["instance_id"], exc))
        if unreadable:
            report.log("warning", "Left out %d %s episode(s): %s"
                       % (len(unreadable), split, ", ".join(unreadable[:5])))
        return out

    # ------------------------------------------------------------ predict

    def _answer(self, model, episode, card, device) -> Dict[str, Any]:
        import numpy
        import torch
        phases, outcomes = card["phases"], card["outcomes"]
        low, high = card["reward_range"]
        layers = set(card.get("layers") or ["phases", "outcome", "reward"])
        x = torch.from_numpy(episode["array"][None]).to(device)
        mask = torch.ones(1, episode["frames"], device=device)
        with torch.inference_mode():
            phase_logits, outcome_logits, reward = model(x, mask)
        fps = episode["fps"]
        answer: Dict[str, Any] = {"phases": [], "reward": [],
                                  "outcome": {"result": "", "cause": ""}, "instructions": []}
        confidences = []
        if "phases" in layers and phases:
            probs = torch.softmax(phase_logits[0].float(), -1).cpu().numpy()
            best = probs.argmax(-1)
            names = [phases[b - 1] if b else None for b in best]
            times = [n / fps for n in range(len(names))]
            for p in sc.runs(names, times, 1.0 / fps, probs.max(-1).tolist()):
                answer["phases"].append({"start": p["start"], "end": p["end"],
                                         "label": p["label"]})
                confidences.append(p["confidence"])
        if "outcome" in layers and card.get("trained_outcome") and outcomes:
            probs = torch.softmax(outcome_logits[0].float(), -1).cpu().numpy()
            best = int(probs.argmax())
            answer["outcome"]["result"] = outcomes[best]
            confidences.append(float(probs[best]))
        if "reward" in layers and card.get("trained_reward"):
            values = reward[0].float().cpu().numpy() * (high - low) + low
            frames = episode["frames"]
            points = sorted(set(numpy.linspace(0, frames - 1, min(frames, int(
                card["reward_points"]))).round().astype(int).tolist()))
            answer["reward"] = [{"t": round(i / fps, 4),
                                 "value": round(float(min(high, max(low, values[i]))), 4)}
                                for i in points]
        return answer, (round(min(confidences), 4) if confidences else None)

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import numpy
        import torch
        import torch.nn.functional as F
        from potato.training.science_metrics import score_episodes
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        self._schema = schema.name
        phases = list(bundle.labels(schema.name))
        train = self._episodes(bundle, "train", None, report)
        if not train:
            raise TrainerError("No annotated episodes with a readable file for %r"
                               % schema.name)
        # The first episode's series, in its order; the rest are read to match.
        names = train[0]["names"]
        for e in train:
            if e["names"] != names:
                e["names"], e["array"] = sc.episode_array(e["episode"], names)
        val = self._episodes(bundle, "val", names, report)
        outcomes = sorted({e["row"]["targets"][schema.name]["outcome"] for e in train
                           if e["row"]["targets"][schema.name].get("outcome")})
        reward_range = params.get("_reward_range") or [0.0, 1.0]
        card: Dict[str, Any] = {
            "series": names, "phases": phases, "outcomes": outcomes,
            "reward_range": reward_range, "layers": params.get("_layers"),
            "hidden": int(params["hidden"]), "reward_points": int(params["reward_points"]),
            "trained_outcome": len(outcomes) >= 2,
            "trained_reward": any(len(e["row"]["targets"][schema.name]["reward"]) >= 2
                                  for e in train)}
        for e in train:
            target = e["row"]["targets"][schema.name]
            e["phase"], e["reward"], e["reward_mask"] = _frame_targets(
                target, e["frames"], e["fps"], phases, reward_range)
            e["outcome"] = outcomes.index(target["outcome"]) \
                if target.get("outcome") in outcomes else -100
        hf.seed_everything(spec.seed)
        rng = random.Random(spec.seed)
        device = hf.pick_device(spec, report)
        model = _build(len(names), card["hidden"], len(phases) + 1, len(outcomes)).to(device)
        crop = int(params["max_frames"])
        report.log("info", "%d episodes, %d val; %d series; %d phase(s), %d outcome(s)%s"
                   % (len(train), len(val), len(names), len(phases), len(outcomes),
                      ", reward" if card["trained_reward"] else ""))

        def loss_of(batch):
            pieces = []
            for e in batch:
                start = rng.randint(0, max(0, e["frames"] - crop))
                pieces.append((e, start, min(e["frames"], start + crop)))
            length = max(b - a for _e, a, b in pieces)
            x = numpy.zeros((len(batch), length, len(names)), dtype="float32")
            mask = numpy.zeros((len(batch), length), dtype="float32")
            phase = numpy.full((len(batch), length), -100, dtype="int64")
            reward = numpy.zeros((len(batch), length), dtype="float32")
            reward_mask = numpy.zeros((len(batch), length), dtype="float32")
            outcome = numpy.full(len(batch), -100, dtype="int64")
            for n, (e, a, b) in enumerate(pieces):
                x[n, :b - a] = e["array"][a:b]
                mask[n, :b - a] = 1
                if e["row"]["targets"][schema.name]["phases"]:
                    phase[n, :b - a] = e["phase"][a:b]
                reward[n, :b - a] = e["reward"][a:b]
                reward_mask[n, :b - a] = e["reward_mask"][a:b]
                outcome[n] = e["outcome"]
            to = lambda array: torch.from_numpy(array).to(device)  # noqa: E731
            phase_logits, outcome_logits, predicted = model(to(x), to(mask))
            loss = torch.zeros((), device=device)
            phase_t = to(phase)
            if (phase_t >= 0).any():
                loss = loss + float(params["phase_weight"]) * F.cross_entropy(
                    phase_logits.float().reshape(-1, phase_logits.shape[-1]),
                    phase_t.reshape(-1), ignore_index=-100)
            outcome_t = to(outcome)
            if card["trained_outcome"] and (outcome_t >= 0).any():
                loss = loss + float(params["outcome_weight"]) * F.cross_entropy(
                    outcome_logits.float(), outcome_t, ignore_index=-100)
            reward_m = to(reward_mask)
            if reward_m.sum() > 0:
                loss = loss + float(params["reward_weight"]) * (
                    ((predicted.float() - to(reward)) ** 2) * reward_m).sum() / reward_m.sum()
            if not loss.requires_grad:
                loss = loss + 0.0 * predicted.sum()
            return loss

        model_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        os.makedirs(model_dir, exist_ok=True)
        weights = os.path.join(model_dir, "episode.pt")
        selected = {"best": None}

        def on_epoch_end(epoch):
            if not val:
                return None
            metrics = score_episodes([e["row"]["targets"][schema.name] for e in val],
                                     [self._answer(model, e, card, device)[0] for e in val])
            from potato.training.evaluation import headline_of
            name = headline_of("episode", metrics)
            if name is None:
                return None
            report.metric("val", name, metrics[name], step=epoch + 1)
            if selected["best"] is None or metrics[name] > selected["best"]:
                selected["best"] = metrics[name]
                torch.save(model.state_dict(), weights)
            return metrics[name]

        report.status("running", "training")
        summary = hf.train_loop(model, train, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if selected["best"] is None:
            torch.save(model.state_dict(), weights)
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        card.update(trainer=self.name, schema=schema.name, kind=schema.kind,
                    label_order=phases, model_version=version, device=device,
                    n_train=len(train), bundle_digest=bundle.digest,
                    selected_epoch=summary["best_epoch"])
        hf.write_card(spec.workdir, card)
        metrics = {"n_train": float(len(train)), "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(model_version=version, artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=phases,
                         selected_on="val" if val else "")

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        card = hf.read_card(artifact_dir)
        device = hf.pick_device(spec, report)
        model = _build(len(card["series"]), int(card["hidden"]), len(card["phases"]) + 1,
                       len(card["outcomes"]))
        model.load_state_dict(torch.load(os.path.join(artifact_dir, hf.MODEL_DIR,
                                                      "episode.pt"), map_location="cpu"))
        model.to(device).eval()
        items = [item for item in items if sc.has_input(item.data, item.media)]
        for n, item in enumerate(items):
            try:
                episode = self._episode(item.data, item.media, card["series"])
            except Exception as exc:  # noqa: BLE001
                report.log("warning", "%s: %s" % (item.instance_id, exc))
                continue
            answer, confidence = self._answer(model, episode, card, device)
            report.progress("predict", n + 1, len(items))
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=spec.primary_schema.name, payload=answer,
                                   confidence=confidence)
            if report.should_stop():
                return

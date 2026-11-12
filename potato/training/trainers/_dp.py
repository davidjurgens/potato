"""Differentially private fine-tuning (DP-SGD) with Opacus, for the
transformer classifiers (``hf-text-classification``, ``hf-image-classification``).

With ``dp: {epsilon, delta, max_grad_norm}``, training runs the DP-SGD
recipe: each step samples items by Poisson sampling (every train item is in
a batch independently, with probability 1 / batches per epoch, about
batch_size / n), clips each item's
gradient to ``max_grad_norm``, adds Gaussian noise sized by Opacus so that
the planned epochs spend at most ``epsilon`` at ``delta``, and the RDP
accountant reports what was spent. The run's metrics and model card carry
the epsilon spent, the noise multiplier and delta.

The guarantee covers the train split: one annotated item changes what the
released model could be by at most the stated epsilon. It does not cover
the val split, whose score picks the epoch kept, nor the label vocabulary,
which is read from the data. Mixed precision and gradient accumulation are
off under DP, and a 4-bit or 8-bit base model is refused. A text
transformer's position and token-type embedding tables are frozen: their
input is one row shared by the whole batch, which per-item gradients cannot
be taken through. A layer Opacus
cannot compute per-item gradients for (BatchNorm, among others) is refused
at the start of training with the layer named.

Needs opacus (``pip install opacus``), which is in no extra: it pins torch
versions of its own, so it is installed on purpose.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from potato.training.base import ProgressReporter, TrainerError

INSTALL_HINT = "pip install opacus"

PARAM = {
    "type": ["object", "null", "boolean"], "default": None,
    "description": "Differentially private training (DP-SGD, Opacus): "
                   "{epsilon, delta, max_grad_norm}, or null or false for off. epsilon is the privacy "
                   "budget for the whole run (1 to 10 is usual); delta defaults "
                   "to 1/(10 x train items); max_grad_norm, the per-item gradient "
                   "clip, defaults to 1.0. Needs opacus."}

_KEYS = {"epsilon", "delta", "max_grad_norm"}


def _off(dp: Any) -> bool:
    """DP is off only when ``dp`` is absent, null or false. An empty mapping
    is a request for DP with no budget, refused rather than read as off."""
    return dp is None or dp is False


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) and value > 0


def settings(params: Dict[str, Any], n_train: int) -> Optional[Dict[str, float]]:
    """The run's DP settings with defaults filled in, or None for no DP."""
    dp = params.get("dp")
    if _off(dp):
        return None
    delta = dp.get("delta")
    if delta is None:
        delta = 1.0 / (10.0 * max(1, n_train))
    return {"epsilon": float(dp["epsilon"]), "delta": float(delta),
            "max_grad_norm": float(dp.get("max_grad_norm", 1.0))}


def problems(params: Dict[str, Any], n_train: int,
             check_install: bool = True) -> List[str]:
    """Why these parameters cannot train privately; empty when they can or
    DP is off. With *n_train* 0 the delta-per-item check is skipped, and
    without *check_install* the opacus check: ``validate`` checks settings on
    the server, and the run may train on another machine."""
    import importlib.util
    dp = params.get("dp")
    if _off(dp):
        return []
    if not isinstance(dp, dict):
        return ["dp must be a mapping with epsilon (and optionally delta and "
                "max_grad_norm)."]
    out = []
    unknown = sorted(set(dp) - _KEYS)
    if unknown:
        out.append("dp does not take %s; it takes epsilon, delta and max_grad_norm."
                   % ", ".join(unknown))
    epsilon = dp.get("epsilon")
    if "epsilon" not in dp:
        out.append("dp needs epsilon, the privacy budget for the run (1 to 10 is usual).")
    elif not _positive(epsilon):
        out.append("dp.epsilon must be a finite number above 0.")
    delta = dp.get("delta")
    if delta is not None and (not _positive(delta) or not delta < 1):
        out.append("dp.delta must be a number between 0 and 1.")
    elif delta is not None and n_train and delta >= 1.0 / n_train:
        out.append("dp.delta is %g, at least 1 / %d train items: at that delta one "
                   "item's data could be released outright. Use less than %g."
                   % (delta, n_train, 1.0 / n_train))
    clip = dp.get("max_grad_norm", 1.0)
    if not _positive(clip):
        out.append("dp.max_grad_norm must be a finite number above 0.")
    lora = params.get("lora")
    if isinstance(lora, dict) and lora.get("quantize"):
        out.append("dp cannot train a quantized (4bit or 8bit) base model; drop "
                   "lora.quantize.")
    if int(params.get("gradient_accumulation", 1) or 1) > 1:
        out.append("dp trains one sampled batch per step; set gradient_accumulation "
                   "to 1.")
    if check_install and importlib.util.find_spec("opacus") is None:
        out.append("dp needs opacus, which is not installed (%s)." % INSTALL_HINT)
    return out


def freeze_shared_embeddings(model) -> List[str]:
    """Freeze the position and token-type embedding tables of a transformer
    (BERT, RoBERTa, DistilBERT) and return their names.

    Their ids are a buffer of shape 1 x length broadcast over the batch, so
    Opacus sees a batch of one for them and the per-item gradients cannot be
    stacked. Frozen, they are not trained and spend no privacy; the word
    embeddings and every other layer still train."""
    from torch import nn
    out = []
    for name, module in model.named_modules():
        leaf = name.rsplit(".", 1)[-1]
        if isinstance(module, nn.Embedding) and ("position" in leaf or "token_type" in leaf) \
                and any(p.requires_grad for p in module.parameters()):
            for parameter in module.parameters():
                parameter.requires_grad_(False)
            out.append(name)
    return out


def train_loop(model, train_rows: Sequence[Any], params: Dict[str, Any],
               loss_of: Callable[[List[Any]], Any], dp: Dict[str, float],
               report: ProgressReporter, *, device: str, seed: int,
               on_epoch_end: Optional[Callable[[int], Optional[float]]] = None
               ) -> Dict[str, Any]:
    """``_hf_common.train_loop``'s contract, under DP-SGD. *model* is
    trained in place (Opacus's hooks sit on its layers, so ``loss_of`` and
    ``on_epoch_end`` keep calling it as they are) and the hooks are removed
    before returning. The summary adds ``epsilon``, ``delta`` and
    ``noise_multiplier``."""
    import torch
    from opacus import PrivacyEngine
    from opacus.validators import ModuleValidator

    from potato.training.trainers import _hf_common as hf

    frozen = freeze_shared_embeddings(model)
    if frozen:
        report.log("info", "DP-SGD: %s frozen (their input is one row shared by the "
                           "whole batch, so no item has a gradient of its own there)"
                   % ", ".join(frozen))
    model.train()       # Opacus checks the layers of a model in training mode
    errors = ModuleValidator.validate(model, strict=False)
    if errors:
        raise TrainerError("DP-SGD cannot train this model: %s"
                           % "; ".join(str(e) for e in errors[:5]))
    n = len(train_rows)
    epochs = int(params["epochs"])
    size = min(int(params["batch_size"]), n)
    steps_per_epoch = max(1, math.ceil(n / size))
    optimizer, scheduler = hf.optimizer_and_schedule(model, params, steps_per_epoch * epochs)
    generator = torch.Generator().manual_seed(seed)
    loader = torch.utils.data.DataLoader(torch.utils.data.TensorDataset(torch.arange(n)),
                                         batch_size=size, shuffle=True, generator=generator)
    engine = PrivacyEngine(accountant="rdp")
    wrapped, optimizer, loader = engine.make_private_with_epsilon(
        module=model, optimizer=optimizer, data_loader=loader,
        target_epsilon=dp["epsilon"], target_delta=dp["delta"], epochs=epochs,
        max_grad_norm=dp["max_grad_norm"], poisson_sampling=True)
    noise = float(optimizer.noise_multiplier)
    # Opacus samples each item with probability 1 / (batches per epoch).
    rate = float(getattr(loader, "sample_rate", 1.0 / steps_per_epoch))
    report.log("info", "DP-SGD: epsilon %g at delta %.3g over %d epoch(s); noise "
               "multiplier %.3f, per-item clip %g, sampling rate %.4f"
               % (dp["epsilon"], dp["delta"], epochs, noise, dp["max_grad_norm"], rate))

    patience = params.get("patience")
    best, best_epoch, since_best, step = None, -1, 0, 0
    total = steps_per_epoch * epochs
    started = time.time()
    losses: List[float] = []
    model.train()
    try:
        for epoch in range(epochs):
            running, seen = 0.0, 0
            for (index,) in loader:
                if report.should_stop():
                    raise TrainerError("Cancelled during training")
                if not len(index):
                    # Poisson sampling drew nobody: nothing is released, so
                    # nothing is spent, and there is no loss to take.
                    continue
                loss = loss_of([train_rows[i] for i in index.tolist()])
                loss.backward()
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
                running += float(loss.detach())
                seen += 1
                step += 1
                elapsed = time.time() - started
                report.progress("train", step, total, eta_s=elapsed / step * max(0, total - step))
            epoch_loss = running / max(seen, 1)
            losses.append(epoch_loss)
            spent = float(engine.get_epsilon(dp["delta"]))
            report.metric("train", "loss", epoch_loss, step=epoch + 1)
            report.metric("train", "dp_epsilon", spent, step=epoch + 1)
            report.log("info", "Epoch %d/%d: loss %.4f, epsilon spent %.3f"
                       % (epoch + 1, epochs, epoch_loss, spent))
            if on_epoch_end is not None:
                model.eval()
                score = on_epoch_end(epoch)
                model.train()
                if score is not None:
                    if best is None or score > best:
                        best, best_epoch, since_best = score, epoch, 0
                    else:
                        since_best += 1
                        if patience and since_best >= int(patience):
                            report.log("info", "No improvement on val for %d epoch(s); "
                                               "stopping" % since_best)
                            break
    finally:
        wrapped.remove_hooks()
        for parameter in model.parameters():
            for attr in ("grad_sample", "_forward_counter", "summed_grad"):
                if hasattr(parameter, attr):
                    delattr(parameter, attr)
    model.eval()
    return {"best_score": best, "best_epoch": best_epoch + 1 if best_epoch >= 0 else None,
            "epochs_run": len(losses), "final_loss": losses[-1] if losses else None,
            "train_seconds": round(time.time() - started, 3),
            "epsilon": round(float(engine.get_epsilon(dp["delta"])), 4),
            "delta": dp["delta"], "noise_multiplier": round(noise, 4),
            "max_grad_norm": dp["max_grad_norm"], "accountant": "rdp"}


def card_entry(summary: Dict[str, Any], dp: Dict[str, float]) -> Dict[str, Any]:
    """What the model card says about the privacy of this run."""
    return {"epsilon_target": dp["epsilon"], "epsilon_spent": summary["epsilon"],
            "delta": summary["delta"], "max_grad_norm": summary["max_grad_norm"],
            "noise_multiplier": summary["noise_multiplier"],
            "accountant": summary["accountant"], "covers": "train split"}

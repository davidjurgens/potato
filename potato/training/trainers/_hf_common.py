"""Plumbing shared by the trainers that fine-tune a transformer.

Each trainer here runs its own short torch loop rather than
``transformers.Trainer`` or trl. The two hosts this was built against had
transformers 5.5 and 5.19 and trl absent and 0.17, and the high-level trainers'
argument names change between such versions; a loop of thirty lines does not.
It also gives what a Potato run needs directly: ``report.should_stop()``
checked every step, a progress event per step, and Apple's Metal device.

Imported only inside the training subprocess. Every torch import is inside a
function, so naming this module costs nothing in the parent.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import random
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from potato.training.base import (MissingDependency, ProgressReporter,
                                  TrainerError, TrainingSpec)

#: The card every transformer trainer writes beside its model.
CARD_FILE = "model_card.json"
#: Subdirectory holding the model (or the LoRA adapter) and its tokenizer.
MODEL_DIR = "model"

#: LoRA defaults. r=16 with alpha=32 is the configuration most fine-tuning
#: recipes start from; dropout keeps a few hundred examples from being
#: memorized outright.
LORA_DEFAULTS = {"r": 16, "alpha": 32, "dropout": 0.05, "target_modules": None}


def missing(modules: Sequence[str]) -> List[str]:
    """Which of *modules* are not importable, without importing them."""
    return [m for m in modules if importlib.util.find_spec(m) is None]


def availability(modules: Sequence[str]):
    absent = missing(modules)
    if absent:
        return False, "Not installed: %s" % ", ".join(absent)
    return True, ""


def require(modules: Sequence[str], hint: str) -> None:
    absent = missing(modules)
    if absent:
        raise MissingDependency("This trainer needs %s, which %s not installed"
                                % (", ".join(absent),
                                   "is" if len(absent) == 1 else "are"),
                                install_hint=hint)


def merged_params(defaults: Dict[str, Any],
                  spec: TrainingSpec) -> Dict[str, Any]:
    params = dict(defaults)
    params.update(spec.params or {})
    lora = params.get("lora")
    if lora is True:
        params["lora"] = dict(LORA_DEFAULTS)
    elif isinstance(lora, dict):
        params["lora"] = {**LORA_DEFAULTS, **lora}
    else:
        params["lora"] = None
    return params


def seed_everything(seed: int) -> None:
    import torch

    random.seed(seed)
    try:
        import numpy
        numpy.random.seed(seed % (2 ** 32))
    except ImportError:
        pass
    torch.manual_seed(seed)


def pick_device(spec: TrainingSpec, report: ProgressReporter) -> str:
    from potato.training.devices import describe_device, resolve_device

    device = resolve_device(spec.limits.device, log=report.log)
    report.log("info", "Training on %s" % describe_device(device))
    return device


def autocast_dtype(device: str, precision: str):
    """The dtype to autocast to, or None for full precision.

    bf16 only where the hardware has it. fp16 without a gradient scaler
    underflows on small learning rates, so it is not offered; on a GPU
    without bf16 a run trains in fp32.
    """
    import torch

    if precision == "fp32" or not device.startswith("cuda"):
        return None
    if precision in ("auto", "bf16") and torch.cuda.is_bf16_supported():
        return torch.bfloat16
    return None


def apply_lora(model, lora: Optional[Dict[str, Any]], task_type: Optional[str],
               report: ProgressReporter,
               modules_to_save: Optional[List[str]] = None):
    """Wrap *model* in a LoRA adapter when *lora* is set.

    *task_type* is peft's name for the head (``SEQ_CLS``, ``TOKEN_CLS``,
    ``CAUSAL_LM``), which also tells peft to train and save that head. peft
    has none for image classification, so a vision trainer passes None and
    names its head in *modules_to_save* instead.
    """
    if not lora:
        return model
    require(["peft"], "pip install peft")
    from peft import LoraConfig, get_peft_model

    kwargs = dict(r=int(lora["r"]), lora_alpha=int(lora["alpha"]),
                  lora_dropout=float(lora["dropout"]))
    if task_type:
        kwargs["task_type"] = task_type
    if modules_to_save:
        kwargs["modules_to_save"] = list(modules_to_save)
    if lora.get("target_modules"):
        kwargs["target_modules"] = list(lora["target_modules"])
    try:
        model = get_peft_model(model, LoraConfig(**kwargs))
    except ValueError as exc:
        if "target_modules" not in str(exc) or "target_modules" in kwargs:
            raise
        # peft knows the attention projections of the text model families it
        # ships a table for, and of no vision ones. "all-linear" adapts every
        # linear layer except the output head.
        report.log("info", "peft has no default LoRA targets for this "
                           "model; adapting every linear layer")
        kwargs["target_modules"] = "all-linear"
        model = get_peft_model(model, LoraConfig(**kwargs))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    report.log("info", "LoRA r=%d: training %s of %s parameters (%.2f%%)"
               % (kwargs["r"], _count(trainable), _count(total),
                  100.0 * trainable / max(total, 1)))
    return model


def _count(n: int) -> str:
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= size:
            return "%.1f%s" % (n / size, unit)
    return str(n)


def optimizer_and_schedule(model, params: Dict[str, Any], total_steps: int):
    """AdamW with linear warmup and linear decay, written out so nothing
    depends on where a transformers version keeps its scheduler helpers."""
    import torch

    decay, no_decay = [], []
    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        (no_decay if param.ndim < 2 or "norm" in name.lower()
         or name.endswith(".bias") else decay).append(param)
    optimizer = torch.optim.AdamW(
        [{"params": decay, "weight_decay": float(params["weight_decay"])},
         {"params": no_decay, "weight_decay": 0.0}],
        lr=float(params["learning_rate"]))

    warmup = int(total_steps * float(params.get("warmup_ratio", 0.1)))

    def factor(step: int) -> float:
        if warmup and step < warmup:
            return (step + 1) / warmup
        remaining = max(total_steps - warmup, 1)
        return max(0.0, 1.0 - (step - warmup) / remaining)

    return optimizer, torch.optim.lr_scheduler.LambdaLR(optimizer, factor)


def batches(rows: Sequence[Any], size: int, shuffle: bool,
            seed: int) -> List[List[Any]]:
    order = list(range(len(rows)))
    if shuffle:
        random.Random(seed).shuffle(order)
    return [[rows[i] for i in order[start:start + size]]
            for start in range(0, len(order), size)]


def train_loop(model, train_rows: Sequence[Any], params: Dict[str, Any],
               loss_of: Callable[[List[Any]], Any], report: ProgressReporter,
               *, device: str, seed: int,
               on_epoch_end: Optional[Callable[[int], Optional[float]]] = None
               ) -> Dict[str, Any]:
    """Run the epochs. ``loss_of(batch)`` returns the batch's loss tensor.

    ``on_epoch_end(epoch)`` may return a validation score; the loop records
    which epoch scored best and stops early after ``patience`` epochs without
    improvement. Saving the best model is the callback's job, since only the
    trainer knows what to save.
    """
    import torch

    epochs = int(params["epochs"])
    size = int(params["batch_size"])
    accumulate = max(1, int(params.get("gradient_accumulation", 1)))
    steps_per_epoch = math.ceil(math.ceil(len(train_rows) / size) / accumulate)
    total = max(1, steps_per_epoch * epochs)
    optimizer, scheduler = optimizer_and_schedule(model, params, total)
    dtype = autocast_dtype(device, str(params.get("precision", "auto")))
    patience = params.get("patience")

    best, best_epoch, since_best, step = None, -1, 0, 0
    started = time.time()
    losses: List[float] = []
    model.train()
    for epoch in range(epochs):
        running, seen = 0.0, 0
        for index, batch in enumerate(batches(train_rows, size, True,
                                              seed + epoch)):
            if report.should_stop():
                raise TrainerError("Cancelled during training")
            if dtype is not None:
                with torch.autocast(device_type="cuda", dtype=dtype):
                    loss = loss_of(batch)
            else:
                loss = loss_of(batch)
            (loss / accumulate).backward()
            running += float(loss.detach())
            seen += 1
            if (index + 1) % accumulate == 0:
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad], 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
                step += 1
                elapsed = time.time() - started
                report.progress("train", step, total,
                                eta_s=elapsed / step * (total - step))
        if seen % accumulate:
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
        epoch_loss = running / max(seen, 1)
        losses.append(epoch_loss)
        report.metric("train", "loss", epoch_loss, step=epoch + 1)
        report.log("info", "Epoch %d/%d: loss %.4f" % (epoch + 1, epochs,
                                                       epoch_loss))

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
                        report.log("info", "No improvement on val for %d "
                                           "epoch(s); stopping" % since_best)
                        break
    model.eval()
    return {"best_score": best, "best_epoch": best_epoch + 1 if best_epoch >= 0
            else None, "epochs_run": len(losses),
            "final_loss": losses[-1] if losses else None,
            "train_seconds": round(time.time() - started, 3)}


def write_card(workdir: str, card: Dict[str, Any]) -> None:
    os.makedirs(workdir, exist_ok=True)
    with open(os.path.join(workdir, CARD_FILE), "w") as fh:
        json.dump(card, fh, indent=2)


def read_card(artifact_dir: str) -> Dict[str, Any]:
    path = os.path.join(artifact_dir, CARD_FILE)
    if not os.path.isfile(path):
        raise TrainerError("No model card at %s" % path)
    with open(path) as fh:
        return json.load(fh)


def save_model(model, tokenizer, workdir: str) -> str:
    """Save the model (or only its adapter, for LoRA) and its tokenizer."""
    target = os.path.join(workdir, MODEL_DIR)
    os.makedirs(target, exist_ok=True)
    model.save_pretrained(target)
    if tokenizer is not None:
        tokenizer.save_pretrained(target)
    return target


def artifact_files(workdir: str) -> List[str]:
    """Every file under the artifact directory, relative to it."""
    out = []
    for root, _, files in os.walk(workdir):
        for name in files:
            out.append(os.path.relpath(os.path.join(root, name), workdir))
    return sorted(out)


def load_pretrained(loader, artifact_dir: str, card: Dict[str, Any],
                    device: str, **kwargs):
    """Load a fitted model: the saved weights, or base model plus adapter."""
    path = os.path.join(artifact_dir, MODEL_DIR)
    if card.get("lora"):
        require(["peft"], "pip install peft")
        from peft import PeftModel
        base = loader.from_pretrained(card["base_model"], **kwargs)
        model = PeftModel.from_pretrained(base, path)
    else:
        model = loader.from_pretrained(path, **kwargs)
    return model.to(device).eval()


def ensure_pad_token(tokenizer, model=None) -> None:
    """Decoder LLMs ship without a pad token; batching needs one."""
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token or tokenizer.unk_token
    if model is not None and getattr(model.config, "pad_token_id", None) is None:
        model.config.pad_token_id = tokenizer.pad_token_id


def rows_with_target(rows: Iterable[Dict[str, Any]], schema: str
                     ) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        target = (row.get("targets") or {}).get(schema)
        if target is None or target == "" or target == []:
            continue
        out.append(row)
    return out


COMMON_PARAMS = {
    "epochs": {"type": "integer", "minimum": 1, "default": 5,
               "description": "Passes over the training split."},
    "batch_size": {"type": "integer", "minimum": 1, "default": 16},
    "gradient_accumulation": {
        "type": "integer", "minimum": 1, "default": 1,
        "description": "Batches per optimizer step. Raises the effective "
                       "batch size without the memory."},
    "learning_rate": {"type": "number", "exclusiveMinimum": 0},
    "weight_decay": {"type": "number", "minimum": 0, "default": 0.01},
    "warmup_ratio": {"type": "number", "minimum": 0, "maximum": 1,
                     "default": 0.1},
    "patience": {
        "type": ["integer", "null"], "minimum": 1, "default": 2,
        "description": "Stop after this many epochs without a better val "
                       "score. null trains every epoch."},
    "precision": {"type": "string", "enum": ["auto", "bf16", "fp32"],
                  "default": "auto",
                  "description": "auto uses bf16 on a GPU that has it."},
    "lora": {
        "type": ["boolean", "object", "null"], "default": None,
        "description": "Train a LoRA adapter instead of every weight. true "
                       "for r=16, alpha=32, dropout=0.05, or an object "
                       "with r, alpha, dropout and target_modules."},
    "min_instances": {"type": "integer", "minimum": 2, "default": 20},
}

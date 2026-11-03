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
LORA_DEFAULTS = {"r": 16, "alpha": 32, "dropout": 0.05, "target_modules": None,
                 "quantize": None}

#: ``lora.quantize`` values: QLoRA's 4-bit NF4 base weights, or 8-bit.
QUANTIZE = ("4bit", "8bit")
BNB_HINT = "pip install bitsandbytes (CUDA only)"


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


def quantize_problems(params: Dict[str, Any], spec: TrainingSpec) -> List[str]:
    """Why ``lora.quantize`` cannot be used here; empty when it can.

    Checked in ``validate``, in the worker on the machine that trains, so a
    run on a Mac or a CPU-only host fails before it loads anything.
    """
    lora = params.get("lora") or {}
    quantize = lora.get("quantize") if isinstance(lora, dict) else None
    if not quantize:
        return []
    if quantize not in QUANTIZE:
        return ["lora.quantize must be one of %s (got %r)"
                % (", ".join(QUANTIZE), quantize)]
    device = str(getattr(spec.limits, "device", "auto") or "auto")
    if device != "auto" and not device.startswith("cuda"):
        return ["lora.quantize needs a CUDA GPU; this run's device is %s"
                % device]
    if missing(["bitsandbytes"]):
        return ["lora.quantize needs bitsandbytes, which is not installed "
                "here: %s" % BNB_HINT]
    try:
        import torch
        if not torch.cuda.is_available():
            return ["lora.quantize needs a CUDA GPU, and this machine has "
                    "none: bitsandbytes quantizes on the GPU"]
    except ImportError:
        return []
    return _bitsandbytes_runs(torch)


def _bitsandbytes_runs(torch) -> List[str]:
    """Quantize 64 zeros on the GPU. A bitsandbytes wheel without a binary
    for this torch's CUDA imports fine and fails only here; without the
    probe the run loaded the whole base model first and then failed in
    weight conversion with no word about why."""
    version = "?"
    try:
        import bitsandbytes
        version = getattr(bitsandbytes, "__version__", "?")
        import bitsandbytes.functional as functional
        functional.quantize_4bit(torch.zeros(64, device="cuda",
                                             dtype=torch.float16))
    except Exception as exc:  # noqa: BLE001
        lines = [line for line in str(exc).splitlines() if line.strip()]
        return ["bitsandbytes %s cannot quantize with this torch (%s, CUDA "
                "%s): %s. Install a bitsandbytes build for CUDA %s."
                % (version, torch.__version__, torch.version.cuda,
                   lines[-1] if lines else type(exc).__name__,
                   torch.version.cuda)]
    return []


def jit_kernel_problems(spec: TrainingSpec) -> List[str]:
    """Whether torch can compile a kernel at run time on this GPU.

    Some ops (``prod``, which Qwen2.5-VL's vision tower runs on every image)
    are compiled by NVRTC when first used. A torch built for one CUDA beside
    an NVRTC from another imports and runs everything else, and fails there,
    after the whole model has loaded, with a page of kernel source. Checked
    in ``validate``, on the machine that trains."""
    device = str(getattr(spec.limits, "device", "auto") or "auto")
    if device != "auto" and not device.startswith("cuda"):
        return []
    try:
        import torch
        if not torch.cuda.is_available():
            return []
        torch.ones(2, device="cuda").prod().item()
    except ImportError:
        return []
    except Exception as exc:  # noqa: BLE001
        lines = [line.strip() for line in str(exc).splitlines() if "nvrtc" in line.lower()]
        cuda = torch.version.cuda
        if not lines:
            # Not NVRTC: say what failed, and no NVRTC advice.
            return ["torch cannot run a kernel on this machine's GPU (torch %s%s): %s: %s"
                    % (torch.__version__, ", CUDA %s" % cuda if cuda else "", type(exc).__name__,
                       (str(exc).strip().splitlines() or [""])[0][:300])]
        found = nvrtc_builtins_dir(str(cuda or ""))
        if found:
            fix = ("The library is installed, in %s, but not on the loader's path: add that "
                   "folder to LD_LIBRARY_PATH (for an ssh or SLURM backend, in its env)." % found)
        elif cuda:
            fix = ("Install the NVRTC package that matches torch's CUDA, such as "
                   "nvidia-cuda-nvrtc for CUDA %s." % cuda)
        else:
            fix = "Install the NVRTC library that matches this torch build."
        return ["torch cannot compile GPU kernels on this machine (torch %s%s): %s %s"
                % (torch.__version__, ", CUDA %s" % cuda if cuda else "", lines[0], fix)]
    return []


def nvrtc_builtins_dir(cuda: str) -> Optional[str]:
    """The folder of an installed ``libnvrtc-builtins.so.<major>.<minor>`` for
    *cuda* (``13.0``) among the NVIDIA wheels beside torch, or None. pip puts
    it in ``site-packages/nvidia/<pkg>/lib``, which the loader does not
    search unless torch's own libraries were linked against it."""
    import glob
    import site
    if not cuda:
        return None
    roots = list(getattr(site, "getsitepackages", lambda: [])()) + [site.getusersitepackages()]
    for root in roots:
        for path in sorted(glob.glob(os.path.join(root, "nvidia", "*", "lib",
                                                  "libnvrtc-builtins.so.%s*" % cuda))):
            return os.path.dirname(path)
    return None


def quantize_unsupported(params: Dict[str, Any]) -> List[str]:
    """For trainers that do not load quantized weights: a problem when
    ``lora.quantize`` is set, so the run stops before the model loads."""
    lora = params.get("lora")
    if isinstance(lora, dict) and lora.get("quantize"):
        return ["lora.quantize is supported by llm-sft, llm-dpo, "
                "hf-text-classification and vlm-sft, not this trainer"]
    return []


def quantization_kwargs(lora: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """``from_pretrained`` arguments for a quantized base model, or ``{}``.

    4-bit is QLoRA's setup (Dettmers et al., 2023): NF4 weights, double
    quantization, bf16 compute where the GPU has it. The model is placed by
    ``device_map`` on the run's GPU, since a quantized model cannot be moved
    with ``.to()``.
    """
    quantize = (lora or {}).get("quantize") if isinstance(lora, dict) else None
    if not quantize:
        return {}
    import torch
    from transformers import BitsAndBytesConfig

    if quantize == "8bit":
        config = BitsAndBytesConfig(load_in_8bit=True)
    else:
        compute = (torch.bfloat16 if torch.cuda.is_available()
                   and torch.cuda.is_bf16_supported() else torch.float16)
        config = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=compute)
    index = torch.cuda.current_device() if torch.cuda.is_available() else 0
    return {"quantization_config": config, "device_map": {"": index}}


def is_quantized(model) -> bool:
    for candidate in (model, getattr(model, "base_model", None),
                      getattr(getattr(model, "base_model", None), "model", None)):
        if candidate is not None and (
                getattr(candidate, "is_loaded_in_4bit", False)
                or getattr(candidate, "is_loaded_in_8bit", False)):
            return True
    return False


def place(model, device: str):
    """``model.to(device)``, except for a quantized model, which ``device_map``
    already placed and which refuses ``.to()``."""
    return model if is_quantized(model) else model.to(device)


def prepare_quantized(model, params: Dict[str, Any], report: ProgressReporter):
    """peft's preparation of a quantized model for adapter training: norms in
    fp32, input gradients for checkpointing. A no-op without quantization."""
    if not is_quantized(model):
        return model
    require(["peft"], "pip install peft")
    from peft import prepare_model_for_kbit_training
    report.log("info", "Base weights quantized to %s (QLoRA)"
               % params["lora"]["quantize"])
    return prepare_model_for_kbit_training(
        model, use_gradient_checkpointing=bool(params.get("gradient_checkpointing")))


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

    if lora.get("quantize") and not is_quantized(model):
        # The trainers that load quantized weights never get here.
        raise TrainerError("lora.quantize is supported by llm-sft, llm-dpo, "
                           "hf-text-classification and vlm-sft, not this trainer")
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
    if device.startswith("cuda") and torch.cuda.is_available():
        # What the run needed, for sizing the next one (or choosing QLoRA).
        report.log("info", "Peak GPU memory: %.2f GB"
                   % (torch.cuda.max_memory_allocated() / 1e9))
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
        # An adapter trained on quantized base weights predicts on the same.
        kwargs = dict(kwargs, **quantization_kwargs(card["lora"]))
        base = loader.from_pretrained(card["base_model"], **kwargs)
        model = PeftModel.from_pretrained(base, path)
    else:
        model = loader.from_pretrained(path, **kwargs)
    return place(model, device).eval()


def ensure_pad_token(tokenizer, model=None) -> None:
    """Decoder LLMs ship without a pad token; batching needs one."""
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token or tokenizer.unk_token
    if model is not None and getattr(model.config, "pad_token_id", None) is None:
        model.config.pad_token_id = tokenizer.pad_token_id


def context_limit(tokenizer, model) -> Optional[int]:
    """The most tokens one input to *model* can hold, or None if unknown.

    The smaller of the tokenizer's ``model_max_length`` (a placeholder of
    about 1e30 when the tokenizer does not know) and the model's position
    table. RoBERTa-family position ids start past the padding index, so 514
    positions hold 512 tokens.
    """
    limits = []
    declared = getattr(tokenizer, "model_max_length", None)
    if isinstance(declared, int) and 0 < declared < 1_000_000:
        limits.append(declared)
    config = getattr(model, "config", None)
    positions = getattr(config, "max_position_embeddings", None)
    if isinstance(positions, int) and positions > 0:
        if getattr(config, "model_type", "") in _OFFSET_POSITIONS:
            positions -= int(getattr(config, "pad_token_id", 1) or 1) + 1
        limits.append(positions)
    return min(limits) if limits else None


_OFFSET_POSITIONS = ("roberta", "xlm-roberta", "camembert", "longformer",
                     "data2vec-text", "xmod")


def rows_with_target(rows: Iterable[Dict[str, Any]], schema: str,
                     negative_tiles: bool = False) -> List[Dict[str, Any]]:
    """Rows with a target for *schema*. With *negative_tiles*, also the
    tiles of an annotated slide that hold no object (``tiling``'s background
    sample): there, empty is an answer, where an empty untiled image is
    indistinguishable from one nobody finished."""
    out = []
    for row in rows:
        target = (row.get("targets") or {}).get(schema)
        if target == [] and negative_tiles and row.get("parent_id"):
            out.append(row)
            continue
        if target is None or target == "" or target == []:
            continue
        out.append(row)
    return out


def is_negative_tile(row: Dict[str, Any], schema: str) -> bool:
    return bool(row.get("parent_id")) and (row.get("targets") or {}).get(schema) == []


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
                       "with r, alpha, dropout, target_modules and "
                       "quantize (4bit for QLoRA, or 8bit; CUDA and "
                       "bitsandbytes only)."},
    "min_instances": {"type": "integer", "minimum": 2, "default": 20},
}

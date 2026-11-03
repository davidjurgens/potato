"""Fine-tune a vision-language model on the study's answers about images.

One trainer, four kinds of answer, each turned into (image, prompt, answer)
examples for supervised fine-tuning, with LoRA by default and QLoRA on a
CUDA GPU (``lora: {quantize: 4bit}``):

- ``text`` on image items: a caption or a question's answer typed in a
  text box. The prompt is the scheme's description (or ``instruction``) and
  the item's text, if it has any beside the image.
- ``caption`` (``region_caption``): one example per captioned region, the
  region drawn on the image as a red box and named by its coordinates.
- ``grounding`` (``grounding_eval``): one example per answered expression;
  the answer is JSON, ``{"bbox": [x0, y0, x1, y1]}`` (``{"point": [x, y]}``
  for a pointing scheme) on a 0-1000 grid, or ``{"absent": true}``.
- ``gui_click`` (``gui_trajectory``): one example per step annotators judged
  ``correct``: the screenshot and the step's action text, answered with the
  agent's click as ``{"point": [x, y]}``. A step judged wrong is not a
  positive example, since nobody marked where the right click was.

Coordinates on a fixed grid and in JSON are model-agnostic: any checkpoint
learns the format from the examples. An answer that does not parse is a
miss, never an error.

Predictions, in the shape each scheme stores:

- text: the generated answer;
- caption: ``{"captions": [{region, caption}]}`` for the regions the
  annotators drew, marked ``heldout_only`` (scored, never published: the
  regions are an annotator's answer);
- grounding: ``{"regions": {id: [shape]}, "absent": [ids]}`` for every
  expression on the item;
- gui_click: ``[{index, verdict, point, confidence}]`` for each step with a
  click: the model's own click against the agent's, ``correct`` when they
  are within ``click_radius`` of the screenshot, else ``wrong_element``.

Real checkpoints need a GPU; Qwen3-VL-2B with LoRA trains on Apple's Metal.
Model licences vary (Qwen2.5-VL-3B carries the Qwen research licence; 7B is
Apache-2.0); check the one you pick.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-vision]'"
_NEEDS = ("torch", "transformers", "PIL")
DEFAULT_MODEL = "Qwen/Qwen2.5-VL-3B-Instruct"
GRID = 1000
#: The attention projections of the language models VLMs are built on.
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj"]


def _local_image(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


def _grid(value: float) -> int:
    return int(round(max(0.0, min(1.0, float(value))) * GRID))


def region_box(obj: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """A shape's normalized ``(x0, y0, x1, y1)``."""
    from potato.export.cv_utils import normalize_annotation_object
    canonical = normalize_annotation_object(obj, 1.0, 1.0) or {}
    box = canonical.get("bbox")
    if not box:
        return None
    x, y, w, h = (float(v) for v in box[:4])
    if obj.get("type") == "mask":
        size = (obj.get("rle") or {}).get("size") or []
        if len(size) < 2 or not size[0] or not size[1]:
            return None
        x, w, y, h = x / size[1], w / size[1], y / size[0], h / size[0]
    return x, y, x + w, y + h


def parse_answer(text: str) -> Dict[str, Any]:
    """The first JSON object in *text*, or ``{}``. A model that wrote
    ``[12, 40, 300, 410]`` without the braces still gets its numbers read
    as a box (four) or a point (two)."""
    for match in re.finditer(r"\{[^{}]*\}", text or ""):
        try:
            value = json.loads(match.group(0))
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", text or "")]
    if len(numbers) >= 4:
        return {"bbox": numbers[:4]}
    if len(numbers) == 2:
        return {"point": numbers}
    return {}


def answer_region(answer: Dict[str, Any], label: str) -> Optional[Dict[str, Any]]:
    """A parsed grounding answer as the image widget's shape, or None."""
    try:
        if isinstance(answer.get("bbox"), list) and len(answer["bbox"]) == 4:
            x0, y0, x1, y1 = (max(0.0, min(1.0, float(v) / GRID)) for v in answer["bbox"])
            x0, x1 = min(x0, x1), max(x0, x1)
            y0, y1 = min(y0, y1), max(y0, y1)
            if x1 - x0 <= 0 or y1 - y0 <= 0:
                return None
            return {"type": "bbox", "label": label, "coordinates": {
                "x": round(x0, 5), "y": round(y0, 5),
                "width": round(x1 - x0, 5), "height": round(y1 - y0, 5)}}
        if isinstance(answer.get("point"), list) and len(answer["point"]) == 2:
            x, y = (max(0.0, min(1.0, float(v) / GRID)) for v in answer["point"])
            return {"type": "landmark", "label": label,
                    "coordinates": {"x": round(x, 5), "y": round(y, 5)}}
    except (TypeError, ValueError):
        return None
    return None


def click_verdict(point: Dict[str, float], agent: Dict[str, float], radius: float
                  ) -> Tuple[str, float]:
    """``correct`` when the model would click within *radius* of where the
    agent did, else ``wrong_element``; confidence grows with the margin."""
    distance = math.hypot(point["x"] - agent["x"], point["y"] - agent["y"])
    if distance <= radius:
        return "correct", round(max(0.5, 1.0 - distance / (2 * radius)), 4)
    return "wrong_element", round(min(1.0, 0.5 + (distance - radius) / (2 * radius)), 4)


class VLMSFTTrainer(Trainer):
    name: ClassVar[str] = "vlm-sft"
    description: ClassVar[str] = (
        "Fine-tunes a vision-language model (Qwen2.5-VL and others) on text "
        "answers about images, region captions, grounding boxes or GUI "
        "clicks, with LoRA or 4-bit QLoRA. Needs a GPU for real models.")
    kinds: ClassVar[Tuple[str, ...]] = ("text", "caption", "grounding", "gui_click")
    modalities: ClassVar[Tuple[str, ...]] = ("image",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 3, "batch_size": 2,
                "gradient_accumulation": 4, "learning_rate": None,
                "weight_decay": 0.0, "warmup_ratio": 0.05, "patience": 1,
                "precision": "auto", "lora": {"target_modules": LORA_TARGETS},
                "max_new_tokens": 64, "max_image_side": 896, "instruction": None,
                "click_radius": 0.05, "gradient_checkpointing": False,
                "min_instances": 10}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["lora"] = dict(props["lora"], default={"target_modules": LORA_TARGETS})
        props["batch_size"] = dict(props["batch_size"], default=2)
        props["learning_rate"] = dict(props["learning_rate"], default=None,
                                      description="Defaults to 1e-4 with LoRA, "
                                                  "1e-5 without.")
        props["min_instances"] = dict(props["min_instances"], default=10)
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "An image-text-to-text model on the Hugging "
                                          "Face Hub (Qwen2.5-VL, Qwen3-VL, SmolVLM, "
                                          "LLaVA, ...) or a local path."},
            "max_new_tokens": {"type": "integer", "minimum": 1, "default": 64},
            "max_image_side": {"type": "integer", "minimum": 32, "default": 896,
                               "description": "Images are shrunk to this longer side; "
                                              "larger images cost more tokens."},
            "instruction": {"type": ["string", "null"], "default": None,
                            "description": "For text answers: the question. Defaults "
                                           "to the scheme's description."},
            "click_radius": {"type": "number", "exclusiveMinimum": 0, "maximum": 1,
                             "default": 0.05,
                             "description": "How close, as a share of the screenshot, "
                                            "two clicks must be to count as the same."},
            "gradient_checkpointing": {"type": "boolean", "default": False},
        })
        return {"type": "object", "properties": props, "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer handles %s."
                            % (schema.name, schema.kind, ", ".join(self.kinds)))
        n = sum(len(self._examples(schema, row, bundle, params, for_training=True))
                for row in bundle.read_split("train"))
        if n < int(params["min_instances"]):
            problems.append("Only %d training examples in the train split; this trainer "
                            "needs at least %d. Annotate more, or lower min_instances."
                            % (n, int(params["min_instances"])))
        problems.extend(hf.quantize_problems(params, spec))
        problems.extend(hf.jit_kernel_problems(spec))
        return problems

    # ------------------------------------------------------------ examples

    def _image(self, path: str, params, box=None):
        from PIL import Image, ImageDraw
        with Image.open(path) as img:
            image = img.convert("RGB")
        side = int(params.get("max_image_side") or 896)
        if max(image.size) > side:
            image.thumbnail((side, side))
        if box is not None:
            draw = ImageDraw.Draw(image)
            w, h = image.size
            draw.rectangle([box[0] * w, box[1] * h, box[2] * w, box[3] * h],
                           outline=(255, 0, 0), width=max(2, int(0.006 * max(w, h))))
        return image

    def _examples(self, schema, row: Dict[str, Any], bundle: BundleRef,
                  params: Dict[str, Any], for_training: bool) -> List[Dict[str, Any]]:
        """``{path, box, prompt, answer, key}`` per example in *row*. Without
        *for_training*, every prompt the row could be asked, answer or not."""
        kind = schema.kind
        target = (row.get("targets") or {}).get(schema.name)
        path = bundle.resolve_media(row["media"]) if row.get("media") else None
        out: List[Dict[str, Any]] = []
        if kind == "text":
            if not _local_image(path) or (for_training and not isinstance(target, str)):
                return []
            question = params.get("instruction") or schema.description or "Describe the image."
            text = str(row.get("text") or "").strip()
            if text and text != str(row.get("media_source") or "") and not text.endswith(
                    (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp")):
                question = "%s\n\n%s" % (question, text)
            out.append({"path": path, "prompt": question, "answer": target, "key": None})
        elif kind == "caption":
            if not _local_image(path) or not isinstance(target, list):
                return []
            for n, entry in enumerate(target):
                box = region_box(entry.get("region") or {})
                if not box:
                    continue
                grid = ", ".join(str(_grid(v)) for v in box)
                out.append({"path": path, "box": box, "key": n, "region": entry["region"],
                            "prompt": "Describe what is in the red box, at [%s] on a 0-1000 "
                                      "grid, in one sentence." % grid,
                            "answer": entry.get("caption")})
        elif kind == "grounding":
            if not _local_image(path):
                return []
            pointing = (target or {}).get("region_type") == "point" if isinstance(
                target, dict) else row.get("region_type") == "point"
            shape = '{"point": [x, y]}' if pointing else '{"bbox": [x0, y0, x1, y1]}'
            expressions = (target or {}).get("expressions") if isinstance(target, dict) \
                else None
            if expressions is None and not for_training:
                expressions = [dict(e, regions=[], absent=None)
                               for e in row.get("expressions") or []]
            for expression in expressions or []:
                answer = None
                if expression.get("absent"):
                    answer = '{"absent": true}'
                elif expression.get("regions"):
                    box = region_box(expression["regions"][0])
                    if box and pointing:
                        answer = json.dumps({"point": [_grid((box[0] + box[2]) / 2),
                                                       _grid((box[1] + box[3]) / 2)]})
                    elif box:
                        answer = json.dumps({"bbox": [_grid(v) for v in box]})
                if for_training and answer is None:
                    continue
                out.append({"path": path, "key": str(expression.get("id")),
                            "label": "referent", "answer": answer,
                            "prompt": 'Where is "%s"? Answer with JSON: %s on a 0-1000 grid, '
                                      'or {"absent": true} if it is not in the image.'
                                      % (expression.get("text", ""), shape)})
        elif kind == "gui_click":
            verdicts = {int(v["index"]): v["verdict"] for v in target or []
                        if isinstance(v, dict)}
            for step in row.get("steps") or []:
                point = step.get("point")
                media = step.get("media")
                step_path = bundle.resolve_media(media) if media else None
                if not isinstance(point, dict) or not _local_image(step_path):
                    continue
                if for_training and verdicts.get(int(step["index"])) != "correct":
                    continue
                out.append({"path": step_path, "key": int(step["index"]), "agent": point,
                            "prompt": 'The task step is: "%s". Where should it click? '
                                      'Answer with JSON: {"point": [x, y]} on a 0-1000 grid.'
                                      % step.get("action", ""),
                            "answer": json.dumps({"point": [_grid(point["x"]),
                                                            _grid(point["y"])]})})
        if for_training:
            # An answer that is only whitespace teaches the model to say
            # nothing; stripped for encoding, it was an empty target.
            out = [e for e in out if str(e.get("answer") or "").strip()]
        return out

    # ------------------------------------------------------------ model

    def _messages(self, prompt: str, answer: Optional[str] = None):
        messages = [{"role": "user", "content": [{"type": "image"},
                                                 {"type": "text", "text": prompt}]}]
        if answer is not None:
            messages.append({"role": "assistant",
                             "content": [{"type": "text", "text": answer}]})
        return messages

    def _load(self, params, spec, report, card=None, artifact_dir=None):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
        device = hf.pick_device(spec, report)
        dtype = torch.float32
        if device.startswith("cuda") and params.get("precision") != "fp32" \
                and torch.cuda.is_bf16_supported():
            dtype = torch.bfloat16
        kwargs = {"dtype": dtype}
        if card is None:
            processor = AutoProcessor.from_pretrained(params["model_name"])
            kwargs.update(hf.quantization_kwargs(params.get("lora")))
            model = AutoModelForImageTextToText.from_pretrained(params["model_name"], **kwargs)
        else:
            processor = AutoProcessor.from_pretrained(os.path.join(artifact_dir, hf.MODEL_DIR))
            model = hf.load_pretrained(AutoModelForImageTextToText, artifact_dir, card,
                                       device, **kwargs)
        return device, processor, model

    def _batch(self, processor, examples, params, device, train: bool):
        """Inputs (and labels masking the prompt) for a batch of examples."""
        import torch
        images = [self._image(e["path"], params, e.get("box")) for e in examples]
        prompts = [processor.apply_chat_template(self._messages(e["prompt"]), tokenize=False,
                                                 add_generation_prompt=True)
                   for e in examples]
        if not train:
            return processor(images=images, text=prompts, return_tensors="pt",
                             padding=True).to(device), images
        tokenizer = getattr(processor, "tokenizer", processor)
        eos = tokenizer.eos_token or ""
        # Stripped: an answer starting with a newline merged with the
        # prompt's last token, and the shared prefix ended one token early.
        full = [p + str(e["answer"]).strip() + eos for p, e in zip(prompts, examples)]
        encoded = processor(images=images, text=full, return_tensors="pt", padding=True)
        labels = encoded["input_ids"].clone()
        for n, (image, prompt) in enumerate(zip(images, prompts)):
            prompt_ids = processor(images=[image], text=[prompt],
                                   return_tensors="pt")["input_ids"][0].tolist()
            mask = encoded["attention_mask"][n]
            # Left padding puts the pads before the prompt.
            start = int((mask == 0).sum()) if tokenizer.padding_side == "left" else 0
            # The prompt is the prefix the two encodings share: a tokenizer
            # that appends a special token to every text ends the prompt-only
            # encoding with one the full example has after the answer.
            ids = encoded["input_ids"][n, start:].tolist()
            shared = 0
            while shared < min(len(ids), len(prompt_ids)) and ids[shared] == prompt_ids[shared]:
                shared += 1
            labels[n, :start + shared] = -100
            labels[n][mask == 0] = -100
        encoded["labels"] = labels
        return encoded.to(device), images

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 1e-4 if params["lora"] else 1e-5
        schema = spec.primary_schema
        train = [e for row in bundle.read_split("train")
                 for e in self._examples(schema, row, bundle, params, True)]
        val = [e for row in bundle.read_split("val")
               for e in self._examples(schema, row, bundle, params, True)]
        if not train:
            raise TrainerError("No training examples for %r" % schema.name)
        hf.seed_everything(spec.seed)
        report.status("running", "loading %s" % params["model_name"])
        device, processor, model = self._load(params, spec, report)
        model = hf.prepare_quantized(model, params, report)
        if params.get("gradient_checkpointing"):
            model.gradient_checkpointing_enable()
            if params["lora"]:
                model.enable_input_require_grads()
        model = hf.apply_lora(model, params["lora"], None, report)
        model = hf.place(model, device)
        report.log("info", "%d train and %d val examples (%s)"
                   % (len(train), len(val), schema.kind))

        def loss_of(batch):
            encoded, _ = self._batch(processor, batch, params, device, train=True)
            return model(**encoded).loss

        model_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        selected = {"best": None, "saved": False}

        def save():
            model.save_pretrained(model_dir)
            processor.save_pretrained(model_dir)

        def on_epoch_end(epoch):
            if not val:
                return None
            import torch
            total = 0.0
            with torch.inference_mode():
                for start in range(0, len(val), int(params["batch_size"])):
                    batch = val[start:start + int(params["batch_size"])]
                    total += float(loss_of(batch)) * len(batch)
            loss = total / len(val)
            report.metric("val", "loss", loss, step=epoch + 1)
            if selected["best"] is None or loss < selected["best"]:
                selected["best"] = loss
                save()
                selected["saved"] = True
            return -loss

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, train, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            save()
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "lora": params["lora"],
            "label_order": bundle.labels(schema.name), "model_version": version,
            "max_new_tokens": int(params["max_new_tokens"]),
            "max_image_side": int(params["max_image_side"]),
            "instruction": params.get("instruction"),
            "click_radius": float(params["click_radius"]), "device": device,
            "n_train": len(train), "bundle_digest": bundle.digest,
            "selected_epoch": summary["best_epoch"]})
        metrics = {"n_train": float(len(train)), "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        if selected["best"] is not None:
            metrics["val_loss"] = round(selected["best"], 4)
        return FitResult(model_version=version, artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=bundle.labels(schema.name),
                         selected_on="val" if val else "")

    # ------------------------------------------------------------ predict

    def _generate(self, model, processor, examples, params, device) -> List[str]:
        import torch
        out = []
        tokenizer = getattr(processor, "tokenizer", processor)
        for start in range(0, len(examples), max(1, int(params.get("batch_size", 2)))):
            batch = examples[start:start + max(1, int(params.get("batch_size", 2)))]
            encoded, _ = self._batch(processor, batch, params, device, train=False)
            with torch.inference_mode():
                generated = model.generate(**encoded, do_sample=False,
                                           max_new_tokens=int(params["max_new_tokens"]))
            new = generated[:, encoded["input_ids"].shape[1]:]
            out.extend(tokenizer.batch_decode(new, skip_special_tokens=True))
        return out

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        card = hf.read_card(artifact_dir)
        params = dict(self.default_params(), **{k: card[k] for k in (
            "max_new_tokens", "max_image_side", "instruction", "click_radius") if k in card})
        schema = spec.primary_schema
        device, processor, model = self._load(params, spec, report, card, artifact_dir)
        model.eval()
        items = list(items)

        class _Bundle:
            @staticmethod
            def resolve_media(reference):
                return reference

        for n, item in enumerate(items):
            row = dict(item.data)
            # Media already resolved for the item; steps keep bundle paths.
            if item.media:
                row["media"] = item.media
            if row.get("steps"):
                row["steps"] = [dict(s, media=s["media"] if not s.get("media") or os.path.isabs(
                    s["media"]) else os.path.join(spec.bundle_dir, "media", s["media"]))
                    for s in row["steps"]]
            examples = self._examples(schema, row, _Bundle, params, for_training=False)
            report.progress("predict", n + 1, len(items))
            if not examples:
                continue
            answers = self._generate(model, processor, examples, params, device)
            record = self._record(schema, item, examples, answers, card, params)
            if record is not None:
                yield record
            if report.should_stop():
                return

    def _record(self, schema, item, examples, answers, card, params):
        version = card.get("model_version", "")
        if schema.kind == "text":
            text = answers[0].strip()
            return PredictionRecord(item.instance_id, schema.name, text) if text else None
        if schema.kind == "caption":
            captions = [{"region": e["region"], "caption": a.strip()}
                        for e, a in zip(examples, answers) if a.strip()]
            if not captions:
                return None
            return PredictionRecord(item.instance_id, schema.name, {"captions": captions},
                                    heldout_only=True)
        if schema.kind == "grounding":
            regions, absent = {}, []
            for example, answer in zip(examples, answers):
                parsed = parse_answer(answer)
                if parsed.get("absent"):
                    absent.append(example["key"])
                    continue
                shape = answer_region(parsed, example["label"])
                if shape is not None:
                    regions[example["key"]] = [dict(shape, source="ai", ai_model=version)]
            if not regions and not absent:
                return None
            return PredictionRecord(item.instance_id, schema.name,
                                    {"regions": regions, "absent": absent})
        if schema.kind == "gui_click":
            radius = float(params.get("click_radius", 0.05))
            steps = []
            for example, answer in zip(examples, answers):
                shape = answer_region(parse_answer(answer), "click")
                if not shape or shape["type"] != "landmark":
                    continue
                point = shape["coordinates"]
                verdict, confidence = click_verdict(point, example["agent"], radius)
                steps.append({"index": example["key"], "verdict": verdict, "point": point,
                              "confidence": confidence})
            if not steps:
                return None
            return PredictionRecord(item.instance_id, schema.name, steps,
                                    confidence=round(sum(s["confidence"] for s in steps)
                                                     / len(steps), 4))
        return None

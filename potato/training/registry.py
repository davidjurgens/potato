"""Trainer registration and capability matching.

Registration is lazy by module path, the same idiom as
``potato.embedders.registry`` and ``AIEndpointFactory``: naming a trainer must
not import torch or transformers. The admin UI lists every trainer, its
capabilities and its install hint without importing any of them, which is only
possible because that metadata lives in the registration call rather than on
the class.

Capability matching goes through ``iaa.dispatcher.classify_schema``. A trainer
says "I handle NOMINAL text"; the registry asks the dispatcher what kind a
scheme is and pairs them up. Reusing that classification means a new annotation
type becomes trainable the moment it is classified, without touching any
trainer.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "TrainerInfo",
    "register_lazy",
    "register",
    "unregister",
    "trainer_names",
    "get_trainer_class",
    "get_trainer",
    "trainer_info",
    "list_trainers",
    "trainers_for_schema",
    "kind_of_schema",
    "resolve_params",
    "validate_trainer_params",
]


@dataclass(frozen=True)
class TrainerInfo:
    """Everything the UI needs about a trainer, without importing it."""

    name: str
    module: str
    cls: str
    description: str = ""
    kinds: Tuple[str, ...] = ()
    modalities: Tuple[str, ...] = ("text",)
    install_hint: str = ""
    licence: str = "unspecified"
    commercial_use: Optional[bool] = None
    licence_ack: bool = False
    licence_url: str = ""
    #: Annotation types the trainer takes, when kind alone says too much:
    #: a slider is "continuous", like a number box or a 0-100 scale, and a
    #: decision model can ask only the short ones. Empty means any.
    annotation_types: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "kinds": list(self.kinds), "modalities": list(self.modalities),
                "annotation_types": list(self.annotation_types),
                "install_hint": self.install_hint, "licence": self.licence,
                "commercial_use": self.commercial_use,
                "licence_ack": self.licence_ack,
                "licence_url": self.licence_url}


_LAZY: Dict[str, TrainerInfo] = {}
_CLASSES: Dict[str, type] = {}


def register_lazy(name: str, module: str, cls: str, hint: str = "",
                  kinds: Tuple[str, ...] = (),
                  modalities: Tuple[str, ...] = ("text",),
                  description: str = "", licence: str = "unspecified",
                  commercial_use: Optional[bool] = None,
                  licence_ack: bool = False, licence_url: str = "",
                  annotation_types: Tuple[str, ...] = ()) -> None:
    """Register a trainer by module path, without importing it."""
    _LAZY[name] = TrainerInfo(
        name=name, module=module, cls=cls, description=description,
        kinds=tuple(kinds), modalities=tuple(modalities), install_hint=hint,
        licence=licence, commercial_use=commercial_use,
        licence_ack=licence_ack, licence_url=licence_url,
        annotation_types=tuple(annotation_types))


def register(cls: type) -> type:
    """Register an already-imported trainer class. Used by tests."""
    _CLASSES[cls.name] = cls
    _LAZY[cls.name] = TrainerInfo(
        name=cls.name, module=cls.__module__, cls=cls.__name__,
        description=getattr(cls, "description", ""),
        kinds=tuple(getattr(cls, "kinds", ())),
        modalities=tuple(getattr(cls, "modalities", ("text",))),
        install_hint=getattr(cls, "install_hint", ""),
        licence=getattr(cls, "licence", "unspecified"),
        commercial_use=getattr(cls, "commercial_use", None),
        licence_ack=getattr(cls, "licence_ack", False),
        licence_url=getattr(cls, "licence_url", ""),
        annotation_types=tuple(getattr(cls, "annotation_types", ())))
    return cls


def unregister(name: str) -> None:
    _CLASSES.pop(name, None)
    _LAZY.pop(name, None)


def trainer_names() -> List[str]:
    return sorted(set(_LAZY) | set(_CLASSES))


def trainer_info(name: str) -> Optional[TrainerInfo]:
    return _LAZY.get(name)


def list_trainers(include_unavailable: bool = True) -> List[Dict[str, Any]]:
    """Every registered trainer as a dict, with an availability flag.

    Availability is probed through ``Trainer.available()``, which is
    contractually forbidden from importing the training library -- so this
    stays cheap enough to call on every page render.
    """
    out = []
    for name in trainer_names():
        info = _LAZY.get(name)
        if info is None:
            continue
        entry = info.to_dict()
        try:
            usable, reason = get_trainer_class(name).available()
        except Exception as exc:  # noqa: BLE001 - a broken trainer is data
            usable, reason = False, str(exc)
        entry["available"] = bool(usable)
        entry["unavailable_reason"] = "" if usable else reason
        if usable or include_unavailable:
            out.append(entry)
    return out


def get_trainer_class(name: str) -> type:
    """Import and return a trainer class. This is where torch finally loads."""
    if name in _CLASSES:
        return _CLASSES[name]
    info = _LAZY.get(name)
    if info is None:
        raise KeyError(
            "Unknown trainer '%s'. Known trainers: %s"
            % (name, ", ".join(trainer_names()) or "(none)"))
    module = importlib.import_module(info.module)
    cls = getattr(module, info.cls)
    _CLASSES[name] = cls
    return cls


def get_trainer(name: str):
    """An instance of the named trainer."""
    return get_trainer_class(name)()


def kind_of_schema(scheme: Dict[str, Any]) -> str:
    """The ``SchemaKind`` value for one scheme, as a string.

    Falls back to ``"unsupported"`` rather than raising, so an unknown
    annotation type produces "no trainer handles this" instead of a 500.
    """
    # A binary pairwise answer is a preference between two responses, which
    # is what DPO and reward models learn from. Classified as nominal for
    # agreement, it would be offered to classifiers that see one text.
    if ((scheme.get("annotation_type") or "") == "pairwise"
            and str(scheme.get("mode") or "binary").lower() == "binary"):
        return "preference"
    try:
        from potato.server_utils.iaa.dispatcher import classify_schema
        return str(classify_schema(scheme).value)
    except Exception:
        logger.debug("Could not classify scheme %r", scheme.get("name"),
                     exc_info=True)
        return "unsupported"


def trainers_for_schema(scheme: Dict[str, Any],
                        modality: Optional[str] = None,
                        available_only: bool = False) -> List[TrainerInfo]:
    """Trainers that can handle this scheme.

    Matches on kind, and on modality when one is given. Imports nothing unless
    *available_only* is set, which is what lets the run form be rendered on a
    machine with no training extras installed.
    """
    kind = kind_of_schema(scheme)
    if kind == "unsupported":
        # No shape to learn. Free text (``text``) is matched like any other
        # kind: only a generative trainer declares it.
        return []

    matches = []
    for name in trainer_names():
        info = _LAZY.get(name)
        if info is None or kind not in info.kinds:
            continue
        if info.annotation_types and (scheme.get("annotation_type") or "") \
                not in info.annotation_types:
            continue
        if modality and modality not in info.modalities:
            continue
        if available_only:
            try:
                usable, _ = get_trainer_class(name).available()
            except Exception:
                usable = False
            if not usable:
                continue
        matches.append(info)
    return matches


def _unknown_params(name: str, params: Dict[str, Any]) -> List[str]:
    """Keys in *params* the trainer's schema does not declare.

    Only for a trainer that declares a closed schema
    (``additionalProperties: false``); one that accepts anything cannot have
    a misspelling.
    """
    schema = get_trainer_class(name).params_schema() or {}
    if schema.get("additionalProperties", True) is not False:
        return []
    return sorted(set(params) - set((schema.get("properties") or {})))


_JSON_TYPES = {"integer": (int,), "number": (int, float), "boolean": (bool,),
               "string": (str,), "object": (dict,), "array": (list, tuple),
               "null": (type(None),)}


def _value_problem(key: str, value: Any, rule: Dict[str, Any]) -> Optional[str]:
    """Why *value* does not fit one ``params_schema`` property, or None.

    The subset of JSON Schema the trainers use: type (one or a list), enum,
    minimum, maximum, exclusiveMinimum. ``epochs: "many"`` used to reach the
    worker and fail there.
    """
    types = rule.get("type")
    if types:
        types = [types] if isinstance(types, str) else list(types)

        def fits(t):
            if t in ("integer", "number") and isinstance(value, bool):
                return False
            if t == "integer" and isinstance(value, float):
                return value.is_integer()
            return isinstance(value, _JSON_TYPES.get(t, (object,)))
        if not any(fits(t) for t in types):
            return "%s must be %s, not %r" % (key, " or ".join(types), value)
    if "enum" in rule and value not in rule["enum"]:
        return "%s must be one of %s, not %r" % (
            key, ", ".join(repr(v) for v in rule["enum"]), value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in rule and value < rule["minimum"]:
            return "%s must be at least %s" % (key, rule["minimum"])
        if "maximum" in rule and value > rule["maximum"]:
            return "%s must be at most %s" % (key, rule["maximum"])
        if "exclusiveMinimum" in rule and value <= rule["exclusiveMinimum"]:
            return "%s must be more than %s" % (key, rule["exclusiveMinimum"])
    return None


def param_problems(name: str, params: Dict[str, Any]) -> List[str]:
    """Unknown parameter names and values of the wrong type or range."""
    schema = get_trainer_class(name).params_schema() or {}
    properties = schema.get("properties") or {}
    problems = []
    unknown = _unknown_params(name, params)
    if unknown:
        problems.append("%s does not take %s. Its parameters are: %s"
                        % (name, ", ".join(unknown),
                           ", ".join(sorted(properties))))
    for key, value in params.items():
        rule = properties.get(key)
        if isinstance(rule, dict):
            problem = _value_problem(key, value, rule)
            if problem:
                problems.append("%s: %s" % (name, problem))
    return problems


def resolve_params(config: Dict[str, Any], name: str,
                   params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The parameters a run of *name* gets: ``model_training.trainer_params``
    for that trainer, overridden by *params*.

    Raises ValueError for an unknown trainer or a parameter it does not take.
    A misspelt ``lora_r`` would otherwise be carried into the run, ignored
    by the trainer, and leave a model trained with the default.
    """
    if name not in trainer_names():
        raise ValueError("Unknown trainer %r. Known trainers: %s"
                         % (name, ", ".join(trainer_names())))
    training = (config or {}).get("model_training", {}) or {}
    merged = dict((training.get("trainer_params") or {}).get(name) or {})
    merged.update(params or {})
    problems = param_problems(name, merged)
    if problems:
        raise ValueError("; ".join(problems))
    return merged


def validate_trainer_params(value: Any) -> List[str]:
    """Problems with ``model_training.trainer_params``, as messages."""
    where = "model_training.trainer_params"
    if not isinstance(value, dict):
        return ["%s must map a trainer name to its parameters" % where]
    problems = []
    for name, params in value.items():
        if name not in trainer_names():
            problems.append("%s.%s: no trainer is called %r (known: %s)"
                            % (where, name, name, ", ".join(trainer_names())))
            continue
        if not isinstance(params, dict):
            problems.append("%s.%s must be a mapping" % (where, name))
            continue
        try:
            found = param_problems(name, params)
        except Exception:  # noqa: BLE001 - an unimportable trainer
            continue
        problems.extend("%s.%s: %s" % (where, name, p) for p in found)
    return problems


#: The annotation types a decision model can be asked about (the same list as
#: the labeling engine's decision source and ``questions_for_scheme``).
DECISION_TYPES = ("radio", "select", "likert", "slider")


def _register_builtins() -> None:
    # sklearn, scipy and numpy are core dependencies, so this one is always
    # usable and needs no extra.
    register_lazy(
        "sklearn-text", "potato.training.trainers.sklearn_text",
        "SklearnTextTrainer", hint="",
        kinds=("nominal", "ordinal", "multilabel"),
        modalities=("text", "image"),
        description="Linear and tree classifiers over bag-of-words, sentence "
                    "embeddings or CLIP image embeddings. No extra install.",
        licence="BSD-3-Clause", commercial_use=True)

    # The rest need torch and transformers, from the train-* extras. Naming
    # them here imports neither.
    register_lazy(
        "hf-text-classification",
        "potato.training.trainers.hf_text_classification",
        "HFTextClassificationTrainer",
        hint="pip install 'potato-annotation[train-text]'",
        kinds=("nominal", "ordinal", "multilabel"), modalities=("text",),
        description="Fine-tunes a Hugging Face transformer to classify "
                    "text. With lora: true, also an LLM such as Qwen or "
                    "Llama.",
        licence="Apache-2.0", commercial_use=True)
    register_lazy(
        "hf-token-classification",
        "potato.training.trainers.hf_token_classification",
        "HFTokenClassificationTrainer",
        hint="pip install 'potato-annotation[train-text]'",
        kinds=("span",), modalities=("text",),
        description="Fine-tunes a Hugging Face transformer to tag text "
                    "spans, such as named entities.",
        licence="Apache-2.0", commercial_use=True)
    register_lazy(
        "setfit", "potato.training.trainers.setfit_trainer", "SetFitTrainer",
        hint="pip install 'potato-annotation[embeddings]'",
        kinds=("nominal", "ordinal", "multilabel"), modalities=("text",),
        description="Few-shot text classification by the SetFit method; "
                    "works from about eight examples per label.",
        licence="Apache-2.0", commercial_use=True)
    register_lazy(
        "hf-image-classification",
        "potato.training.trainers.hf_image_classification",
        "HFImageClassificationTrainer",
        hint="pip install 'potato-annotation[train-vision]'",
        kinds=("nominal", "ordinal", "multilabel"), modalities=("image",),
        description="Fine-tunes a vision transformer (ViT, DeiT, ConvNeXt, "
                    "DINOv2) to classify images, with optional LoRA.",
        licence="Apache-2.0", commercial_use=True)
    register_lazy(
        "torchvision-detect", "potato.training.trainers.torchvision_detect",
        "TorchvisionDetectTrainer",
        hint="pip install 'potato-annotation[train-vision]'",
        kinds=("geometry",), modalities=("image",),
        description="Object detection: fine-tunes a torchvision Faster R-CNN "
                    "on the annotated boxes.",
        licence="BSD-3-Clause", commercial_use=True)
    register_lazy(
        "torchvision-segment", "potato.training.trainers.torchvision_segment",
        "TorchvisionSegmentTrainer",
        hint="pip install 'potato-annotation[train-vision]'",
        kinds=("geometry",), modalities=("image",),
        description="Instance segmentation: fine-tunes a torchvision Mask "
                    "R-CNN on the annotated outlines and predicts polygons.",
        licence="BSD-3-Clause", commercial_use=True)
    register_lazy(
        "ultralytics-detect", "potato.training.trainers.ultralytics_detect",
        "UltralyticsDetectTrainer", hint="pip install ultralytics",
        kinds=("geometry",), modalities=("image",),
        description="Object detection with Ultralytics YOLO. AGPL-3.0: "
                    "confirm the licence before the first run.",
        licence="AGPL-3.0", commercial_use=False, licence_ack=True,
        licence_url="https://www.ultralytics.com/license")
    register_lazy(
        "ultralytics-segment", "potato.training.trainers.ultralytics_segment",
        "UltralyticsSegmentTrainer", hint="pip install ultralytics",
        kinds=("geometry",), modalities=("image",),
        description="Instance segmentation with Ultralytics YOLO-seg, "
                    "predicting polygons. AGPL-3.0: confirm the licence "
                    "before the first run.",
        licence="AGPL-3.0", commercial_use=False, licence_ack=True,
        licence_url="https://www.ultralytics.com/license")
    register_lazy(
        "hf-audio-tagger", "potato.training.trainers.hf_audio_tagger",
        "HFAudioTaggerTrainer",
        hint="pip install 'potato-annotation[train-audio]'",
        kinds=("temporal",), modalities=("audio",),
        description="Tags labelled time segments in audio with a fine-tuned "
                    "speech encoder (wav2vec 2.0, WavLM).",
        licence="Apache-2.0", commercial_use=True)
    register_lazy(
        "decision-calibrate", "potato.training.trainers.decision_calibrate",
        "DecisionCalibrateTrainer", hint="",
        kinds=("nominal", "ordinal", "continuous"), modalities=("text",),
        annotation_types=DECISION_TYPES,
        description="Calibrates the project's decision model (Jev, OpenJev, "
                    "laya-serve, Laya) to the annotators' labels; writes a "
                    "calibration file the endpoint applies.",
        licence="BSD-3-Clause", commercial_use=True)
    register_lazy(
        "laya-finetune", "potato.training.trainers.laya_finetune",
        "LayaFinetuneTrainer",
        hint="pip install 'potato-annotation[decision]'",
        kinds=("nominal", "ordinal", "continuous"), modalities=("text",),
        annotation_types=DECISION_TYPES,
        description="Fine-tunes a Laya decision model on the scheme's labels; "
                    "the checkpoint loads in the laya endpoint.",
        licence="Apache-2.0", commercial_use=True)
    register_lazy(
        "openjev-finetune", "potato.training.trainers.openjev_finetune",
        "OpenJevFinetuneTrainer", hint="pip install wev-ai",
        kinds=("nominal", "ordinal", "continuous"), modalities=("text",),
        annotation_types=DECISION_TYPES,
        description="Fine-tunes OpenJev (an 8B decision model) on the "
                    "scheme's labels with wev's LoRA training; serve the "
                    "result with wev serve.",
        licence="Apache-2.0", commercial_use=None)
    register_lazy(
        "llm-sft", "potato.training.trainers.llm_sft", "LLMSFTTrainer",
        hint="pip install 'potato-annotation[train-llm]'",
        kinds=("text",), modalities=("text",),
        description="Fine-tunes an LLM (LoRA by default) to write what "
                    "annotators wrote in a free-text scheme.",
        licence="Apache-2.0", commercial_use=True)

    register_lazy(
        "llm-dpo", "potato.training.trainers.llm_dpo", "LLMDPOTrainer",
        hint="pip install 'potato-annotation[train-llm]'",
        kinds=("preference",), modalities=("text",),
        description="Direct Preference Optimization of an LLM (LoRA by "
                    "default) on which of two responses annotators preferred.",
        licence="Apache-2.0", commercial_use=True)


_register_builtins()

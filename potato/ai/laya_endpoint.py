"""
In-process Laya decision model (Convai Innovations, Apache-2.0).

``laya`` and ``torch`` are imported inside methods only. A module-level import
would pull the whole ML stack into server boot for every deployment that has
laya installed, whether or not it uses it (tests/unit/test_boot_import_weight.py
and tests/unit/test_decision_endpoint.py guard this).

Confirmed against laya 0.4.7 source (site-packages/laya/agent.py, router.py):
``laya.load(model_id_or_path, device=...)`` returns an ``Agent`` whose
``predict(state, questions)`` (alias of ``system_one``) returns
``{"answers": {...}, "usage": {...}}`` in the /v1/systemone shape;
``Agent.predict_batch(states, questions, batch_size=...)`` returns one such
dict per state. ``laya.Router(device=...).predict(state, questions)`` adds
script-based routing between the english and multilingual checkpoints.

ai_config keys:
    model       default 'convaiinnovations/laya' (English, ModernBERT-large).
                Anything ``laya.load`` accepts: a Hub id, a local checkpoint
                dir, or an alias ('multilingual', 'typed-decisions').
                'router' / 'auto' uses ``laya.Router`` instead.
    device      'cpu' (default), 'cuda', 'mps' or 'auto'
    batch_size  states per forward pass in decide_batch (laya's default if unset)
    max_options per-question cap, default 100 (laya-serve's one-pass cap;
                laya's docs note >20 options wants a larger head_max_len)
    head_max_len  optional token budget for the question head
"""

import logging
import threading
from typing import Any, Dict, List, Tuple

from .ai_endpoint import AIEndpointConfigError, AIEndpointRequestError
from .decision_endpoint import (
    DecisionAnswer, DecisionModelEndpoint, DecisionQuestion,
    build_systemone_questions, parse_systemone_answers,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "convaiinnovations/laya"
INSTALL_HINT = "pip install 'potato-annotation[decision]'"
ROUTER_MODELS = ("router", "auto")

# (model, device) -> loaded Agent or Router. Loading costs seconds and ~1.7 GB
# of weights, so every endpoint instance in the process shares one.
_PREDICTORS: Dict[Tuple[str, str], Any] = {}
_PREDICTORS_LOCK = threading.Lock()


def _import_laya():
    try:
        import laya  # noqa: deferred on purpose, see module docstring
    except ImportError as e:
        raise AIEndpointConfigError(
            f"The 'laya' endpoint needs the laya package ({e}). Install it with: {INSTALL_HINT}")
    return laya


def get_predictor(model: str, device: str):
    """Load (once per process) the laya Agent or Router for (model, device)."""
    key = (model, device)
    with _PREDICTORS_LOCK:
        predictor = _PREDICTORS.get(key)
        if predictor is None:
            laya = _import_laya()
            logger.info(f"Loading laya model {model!r} on {device}")
            if model.lower() in ROUTER_MODELS:
                predictor = laya.Router(device=device)
            else:
                predictor = laya.load(model, device=device)
            _PREDICTORS[key] = predictor
        return predictor


def clear_predictors() -> None:
    """Drop cached models (tests, or to free memory)."""
    with _PREDICTORS_LOCK:
        _PREDICTORS.clear()


class LayaEndpoint(DecisionModelEndpoint):
    """Laya run in this process."""

    def _initialize_client(self) -> None:
        self.device = str(self.ai_config.get("device", "cpu"))
        self.batch_size = self.ai_config.get("batch_size")
        self.head_max_len = self.ai_config.get("head_max_len")
        self.max_options = int(self.ai_config.get("max_options", 100))
        # Fail at config time, not on the first item, when laya is missing.
        # find_spec does not import the package.
        import importlib.util
        if importlib.util.find_spec("laya") is None:
            raise AIEndpointConfigError(
                f"The 'laya' endpoint needs the laya package. Install it with: {INSTALL_HINT}")

    def _get_default_model(self) -> str:
        return DEFAULT_MODEL

    def _predictor(self):
        return get_predictor(str(self.model), self.device)

    def _kwargs(self) -> Dict[str, Any]:
        return {"head_max_len": self.head_max_len} if self.head_max_len else {}

    def _decide_raw(self, state: str, questions: List[DecisionQuestion]) -> Dict[str, Any]:
        predictor = self._predictor()
        try:
            return predictor.predict(state, build_systemone_questions(questions), **self._kwargs())
        except (AIEndpointConfigError, AIEndpointRequestError):
            raise
        except Exception as e:
            raise AIEndpointRequestError(f"laya prediction failed: {e}")

    def decide_batch(self, states: List[str],
                     questions: List[DecisionQuestion]) -> List[List[DecisionAnswer]]:
        """One shared forward pass per ``batch_size`` states (Agent.predict_batch)."""
        self._check_questions(questions)
        if not states:
            return []
        predictor = self._predictor()
        payload = build_systemone_questions(questions)
        try:
            if hasattr(predictor, "predict_batch") and not isinstance(
                    predictor, getattr(_import_laya(), "Router", ())):
                results = predictor.predict_batch(list(states), payload,
                                                  batch_size=self.batch_size, **self._kwargs())
            else:
                results = [predictor.predict(s, payload, **self._kwargs()) for s in states]
        except (AIEndpointConfigError, AIEndpointRequestError):
            raise
        except Exception as e:
            raise AIEndpointRequestError(f"laya prediction failed: {e}")
        return [parse_systemone_answers(r, questions) for r in results]

    def health_check(self) -> bool:
        """True when the model loads; the first call downloads and builds it."""
        try:
            self._predictor()
            return True
        except Exception as e:
            logger.error(f"laya health check failed: {e}")
            return False

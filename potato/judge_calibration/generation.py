"""
Background LLM judge generation.

For every (model, item, schema) the judge LLM is queried ``k`` times; the raw
draws are aggregated (see ``aggregation.py``) into a modal prediction + a
vote-fraction confidence and persisted to the ``ResultStore``.

Endpoints are built with ``AIEndpointFactory`` via the reused solo-mode
``ModelConfig.to_endpoint_config()``. Label parsing reuses
``ai.judge.extract_labels`` / ``_fuzzy_match_label`` so model output is mapped
onto the schema's allowed label space exactly as the single-judge feature does.
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel

from potato.ai.judge import extract_labels, _fuzzy_match_label
from potato.judge_calibration.aggregation import aggregate, ModelItemResult

logger = logging.getLogger(__name__)

_MAX_WORKERS = 8
_SAVE_EVERY = 25  # persist the result store after this many completed units


# ----- output schemas -----------------------------------------------------

class _SingleLabel(BaseModel):
    label: str = ""
    reasoning: str = ""


class _MultiLabel(BaseModel):
    labels: List[str] = []
    reasoning: str = ""


class _SpanItem(BaseModel):
    start: int = 0
    end: int = 0
    label: str = ""


class _SpanList(BaseModel):
    spans: List[_SpanItem] = []
    reasoning: str = ""


def _output_model(annotation_type: str):
    if annotation_type == "multiselect":
        return _MultiLabel
    if annotation_type == "span":
        return _SpanList
    return _SingleLabel


# ----- prompt -------------------------------------------------------------

def build_prompt(judge_prompt: str, schema_info: Dict[str, Any], text: str) -> str:
    """Compose the judge prompt for one item + schema.

    The user's ``judge_prompt`` may contain ``{text}``, ``{labels}`` and
    ``{description}`` placeholders; if present they are substituted, otherwise
    the standard scaffold (labels + item + JSON instruction) is appended.
    """
    labels = extract_labels(schema_info)
    description = schema_info.get("description", "") or ""
    labels_str = ", ".join(labels)
    annotation_type = schema_info.get("annotation_type", "radio")

    head = judge_prompt or "You are an impartial expert annotator."
    try:
        head = head.format(text=text, labels=labels_str, description=description)
        substituted = head != (judge_prompt or "")
    except (KeyError, IndexError, ValueError):
        substituted = False

    parts = [head, ""]
    if description:
        parts.append(f"Task: {description}")
    if labels:
        parts.append("Allowed labels: " + labels_str)
    if annotation_type == "span":
        # Spans need the exact text + character-offset instructions.
        parts.append("\nItem to judge (label spans by 0-based character offsets):")
        parts.append(_truncate(text, 4000))
        parts.append(
            '\nRespond as JSON: {"spans": [{"start": <char offset, inclusive>, '
            '"end": <char offset, exclusive>, "label": <one of the allowed labels>}], '
            '"reasoning": <one sentence>}. Return an empty list if no span applies.'
        )
        return "\n".join(p for p in parts if p != "")
    if not substituted:
        parts.append("\nItem to judge:")
        parts.append(_truncate(text, 4000))
    if annotation_type == "multiselect":
        parts.append(
            '\nRespond as JSON: {"labels": [<zero or more of the allowed labels>], '
            '"reasoning": <one sentence>}.'
        )
    else:
        parts.append(
            '\nRespond as JSON: {"label": <one of the allowed labels>, '
            '"reasoning": <one sentence>}.'
        )
    return "\n".join(p for p in parts if p != "")


def _truncate(text: str, limit: int = 4000) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "…"


# ----- response parsing ---------------------------------------------------

def _extract_data(endpoint, response) -> Dict[str, Any]:
    if isinstance(response, str):
        try:
            return json.loads(endpoint.parseStringToJson(response))
        except Exception:
            try:
                return json.loads(response)
            except Exception:
                return {}
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "dict"):
        return response.dict()
    return response or {}


def parse_sample(endpoint, response, annotation_type: str, valid_labels: List[str]):
    """Parse one model response into a label value (or None on failure).

    Returns a label name (str) for single-label schemas, a sorted list of
    matched label names for multiselect, or None if nothing usable was parsed.
    """
    data = _extract_data(endpoint, response)
    if not isinstance(data, dict):
        return None

    if annotation_type == "multiselect":
        raw = data.get("labels", [])
        if not isinstance(raw, list):
            raw = [raw]
        matched = []
        for item in raw:
            m = _fuzzy_match_label(str(item).strip(), valid_labels) if valid_labels else str(item).strip()
            if m:
                matched.append(m)
        return sorted(set(matched))  # empty list is a valid "selected nothing"

    if annotation_type == "span":
        raw = data.get("spans", [])
        if not isinstance(raw, list):
            return None
        spans = []
        for sp in raw:
            if not isinstance(sp, dict):
                continue
            try:
                start, end = int(sp.get("start")), int(sp.get("end"))
            except (TypeError, ValueError):
                continue
            if end <= start:
                continue
            lab = str(sp.get("label", "")).strip()
            m = _fuzzy_match_label(lab, valid_labels) if valid_labels else lab
            if not m:
                continue
            spans.append({"start": start, "end": end, "label": m})
        return spans  # empty list is a valid "no spans"

    raw = str(data.get("label", "")).strip()
    if not raw:
        return None
    if valid_labels and raw not in valid_labels:
        matched = _fuzzy_match_label(raw, valid_labels)
        return matched  # may be None
    return raw


# ----- generation thread --------------------------------------------------

class LLMGenerationThread(threading.Thread):
    """Runs judge generation for all models/items/schemas in the background."""

    def __init__(
        self,
        config,                                  # JudgeCalibrationConfig
        work_items: List[Tuple[str, str]],       # (instance_id, text)
        schema_infos: List[Dict[str, Any]],      # schema dicts to evaluate
        result_store,                            # ResultStore
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
        multiselect_threshold: float = 0.5,
    ):
        super().__init__(daemon=True, name="jc-generation")
        self.config = config
        self.work_items = work_items
        self.schema_infos = schema_infos
        self.store = result_store
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.multiselect_threshold = multiselect_threshold
        self._stop_event = threading.Event()
        self.error: Optional[str] = None

        self.total_units = len(work_items) * len(schema_infos) * max(1, len(config.models))
        self.done_units = 0
        self._lock = threading.Lock()

    def stop(self) -> None:
        self._stop_event.set()

    # -- one (model, item, schema) unit: k samples + aggregate + store --
    def _label_unit(self, endpoint, model_name: str, instance_id: str, text: str,
                    schema_info: Dict[str, Any]) -> ModelItemResult:
        annotation_type = schema_info.get("annotation_type", "radio")
        schema_name = schema_info.get("name", "")
        valid_labels = extract_labels(schema_info)
        output_model = _output_model(annotation_type)
        prompt = build_prompt(self.config.prompt, schema_info, text)

        samples: List[Any] = []
        for _ in range(self.config.k_samples):
            if self._stop_event.is_set():
                break
            try:
                response = endpoint.query(prompt, output_model)
                samples.append(parse_sample(endpoint, response, annotation_type, valid_labels))
            except Exception as e:
                logger.warning("JC query failed (%s/%s/%s): %s",
                               model_name, instance_id, schema_name, e)
                samples.append(None)

        return aggregate(
            model=model_name,
            instance_id=instance_id,
            schema_name=schema_name,
            annotation_type=annotation_type,
            samples=samples,
            k=self.config.k_samples,
            multiselect_threshold=self.multiselect_threshold,
        )

    def _bump_progress(self, model_name: str) -> None:
        with self._lock:
            self.done_units += 1
            done = self.done_units
        if self.on_progress and (done % 5 == 0 or done == self.total_units):
            self.on_progress({
                "done_units": done,
                "total_units": self.total_units,
                "current_model": model_name,
            })

    def run(self) -> None:
        try:
            from potato.ai.ai_endpoint import AIEndpointFactory
            for model in self.config.models:
                if self._stop_event.is_set():
                    break
                try:
                    endpoint = AIEndpointFactory.create_endpoint(model.to_endpoint_config())
                except Exception as e:
                    self.error = f"Failed to create endpoint for {model.model}: {e}"
                    logger.error(self.error)
                    continue
                if endpoint is None:
                    logger.error("JC: endpoint None for %s", model.model)
                    continue

                # Build the list of units still needing generation (resume-safe).
                units: List[Tuple[str, str, Dict[str, Any]]] = []
                for instance_id, text in self.work_items:
                    for schema_info in self.schema_infos:
                        if self.store.has(model.model, instance_id, schema_info.get("name", "")):
                            with self._lock:
                                self.done_units += 1
                            continue
                        units.append((instance_id, text, schema_info))

                completed = 0
                with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
                    futures = {
                        ex.submit(self._label_unit, endpoint, model.model, iid, text, si): (iid, si)
                        for (iid, text, si) in units
                    }
                    for fut in as_completed(futures):
                        if self._stop_event.is_set():
                            break
                        try:
                            result = fut.result()
                            self.store.upsert(result, save=False)
                        except Exception as e:
                            logger.warning("JC unit failed: %s", e)
                        completed += 1
                        if completed % _SAVE_EVERY == 0:
                            self.store._save()
                        self._bump_progress(model.model)

                self.store._save()

            if self.on_complete and not self._stop_event.is_set():
                self.on_complete()
        except Exception as e:
            self.error = str(e)
            logger.exception("JC generation thread crashed: %s", e)

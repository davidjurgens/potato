"""
Agent (vision-LLM) annotation strategy.

The :class:`AgentSimulatorStrategy` consumes the *full* structured payload of
an instance — text fields, dialogue arrays (agent traces, conversations),
spreadsheet/table data, image references — and asks a vision-capable LLM to
produce a complete annotation set covering every schema for that instance.

It mirrors :class:`LLMStrategy` but differs in two important ways:

1. It reads ``instance["data"]`` (the full raw payload that
   ``/api/current_instance`` returns under the ``data`` key) instead of the
   single ``text`` field. This gives the model access to dialogue traces,
   metadata tables, and image URLs.

2. It batches the per-instance call: a single LLM query produces labels for
   every schema. Subsequent ``generate_annotation`` calls for the same
   instance are served from a per-instance cache. This keeps cost roughly
   1× (instances) instead of (instances × schemas).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import random
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from .annotation_strategies import AnnotationStrategy, RandomStrategy
from .competence_profiles import CompetenceProfile
from .config import AgentStrategyConfig

logger = logging.getLogger(__name__)


_FIELD_DETECTORS = {
    "dialogue": (
        "conversation",
        "dialogue",
        "trace",
        "messages",
        "turns",
        "structured_turns",  # coding-agent traces with role/content/tool_calls
    ),
    "spreadsheet": ("metadata_table", "table", "spreadsheet"),
    "image": ("image", "image_url", "screenshot", "screenshot_url", "media", "image_path"),
}

# Cap on how much tool I/O text we render per turn to keep prompts bounded.
_MAX_TOOL_INPUT_CHARS = 400
_MAX_TOOL_OUTPUT_CHARS = 800


class _AgentLabelResponse(BaseModel):
    """Pydantic schema returned by the LLM for a single instance.

    The model returns a flat dict keyed by ``<schema_name>`` whose value is
    either a label string (radio/multiselect/likert) or a numeric value
    (slider/likert as int) or a free-text response (text/textbox). The
    strategy maps these to the wire format the simulator submits.
    """

    annotations: Dict[str, Any] = Field(
        default_factory=dict,
        description="Mapping of schema_name -> chosen label/value/text.",
    )
    reasoning: str = Field(
        default="",
        description="One sentence explaining the labels (kept short).",
    )


class AgentSimulatorStrategy(AnnotationStrategy):
    """Vision-LLM strategy for multi-modal / structured agent content."""

    def __init__(self, config: AgentStrategyConfig):
        self.config = config
        self.endpoint = self._create_endpoint()
        self.random_strategy = RandomStrategy()
        # Per-instance result cache: instance_id -> dict[schema_name -> raw model value]
        self._cache: Dict[str, Dict[str, Any]] = {}
        # Errors are reported per-instance to avoid hammering the LLM with retries
        self._failed_instances: set = set()

    # ------------------------------------------------------------------
    # Endpoint construction
    # ------------------------------------------------------------------

    def _create_endpoint(self):
        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            ai_cfg: Dict[str, Any] = {
                "model": self.config.model,
                "api_key": self.config.api_key,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
            }
            if self.config.base_url:
                ai_cfg["base_url"] = self.config.base_url

            return AIEndpointFactory.create_endpoint({
                "ai_support": {
                    "enabled": True,
                    "endpoint_type": self.config.endpoint_type,
                    "ai_config": ai_cfg,
                }
            })
        except Exception as e:
            logger.warning("AgentSimulatorStrategy: endpoint init failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_annotation(
        self,
        instance: Dict[str, Any],
        schema: Dict[str, Any],
        competence: CompetenceProfile,
        gold_answer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.endpoint:
            return self.random_strategy.generate_annotation(
                instance, schema, competence, gold_answer
            )

        instance_id = instance.get("instance_id") or instance.get("id") or ""
        schema_name = schema.get("name")
        annotation_type = schema.get("annotation_type") or schema.get("type")
        labels = self.random_strategy._extract_labels(schema)

        # Per-instance cache: one LLM call answers every schema
        results = self._get_or_query(instance, instance_id)
        if results is None:
            return self.random_strategy.generate_annotation(
                instance, schema, competence, gold_answer
            )

        # Optional noise: mirrors LLMStrategy
        if self.config.add_noise and random.random() < self.config.noise_rate:
            return self.random_strategy.generate_annotation(
                instance, schema, competence, gold_answer
            )

        raw_value = results.get(schema_name)
        if raw_value is None:
            logger.debug(
                "Agent strategy: no value for schema=%s (instance=%s); falling back",
                schema_name, instance_id,
            )
            return self.random_strategy.generate_annotation(
                instance, schema, competence, gold_answer
            )

        formatted = self._format_value(
            schema_name, raw_value, annotation_type, labels, schema,
            instance=instance,
        )
        if not formatted:
            return self.random_strategy.generate_annotation(
                instance, schema, competence, gold_answer
            )
        return formatted

    # ------------------------------------------------------------------
    # Per-instance batch query
    # ------------------------------------------------------------------

    def _get_or_query(
        self, instance: Dict[str, Any], instance_id: str
    ) -> Optional[Dict[str, Any]]:
        if self.config.cache_per_instance and instance_id in self._cache:
            return self._cache[instance_id]
        if instance_id in self._failed_instances:
            return None

        schemas = instance.get("__all_schemas__") or instance.get("schemas") or []
        if not schemas:
            # The simulator should be passing schemas via the instance dict
            # (see SimulatedUser.generate_annotations). If it isn't, we can
            # still produce annotations for the single schema by callers
            # passing schema directly each time, but caching is then per-call.
            logger.debug("Agent strategy: no schemas attached to instance %s", instance_id)
            return None

        prompt, image_payloads = self._build_request(instance, schemas)
        try:
            response = self._invoke(prompt, image_payloads)
        except Exception as e:
            logger.warning(
                "Agent strategy: LLM call failed for instance=%s: %s", instance_id, e
            )
            self._failed_instances.add(instance_id)
            return None

        parsed = self._parse_response(response)
        if parsed is None:
            self._failed_instances.add(instance_id)
            return None

        # Models occasionally key by the schema's annotation_type instead of
        # its name (e.g. "code_review" instead of "review"). Re-key to schema
        # names so downstream lookup always works.
        parsed = self._normalize_keys_to_schema_names(parsed, schemas)

        if self.config.cache_per_instance:
            self._cache[instance_id] = parsed
        return parsed

    def _normalize_keys_to_schema_names(
        self, parsed: Dict[str, Any], schemas: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Re-key parsed annotations to match the schema *names* the
        simulator uses, even if the LLM keyed by annotation_type, label, or
        a case-variant.  Idempotent for already-correct keys.
        """
        if not isinstance(parsed, dict) or not schemas:
            return parsed

        names = {s.get("name"): s for s in schemas if s.get("name")}
        # Exact-name path -- fast and keeps existing behaviour.
        unmatched = [k for k in parsed.keys() if k not in names]
        if not unmatched:
            return parsed

        # Build alternate-key lookup: annotation_type -> schema name.
        type_to_name: Dict[str, str] = {}
        lower_name_to_name: Dict[str, str] = {n.lower(): n for n in names}
        for s in schemas:
            atype = s.get("annotation_type") or s.get("type")
            if atype and atype not in names and atype not in type_to_name:
                type_to_name[atype] = s["name"]

        out = dict(parsed)
        for key in list(unmatched):
            value = out[key]
            target: Optional[str] = None
            if key in type_to_name:
                target = type_to_name[key]
            elif key.lower() in lower_name_to_name:
                target = lower_name_to_name[key.lower()]
            if target and target not in out:
                out[target] = value
                # Keep the original key too -- harmless and aids debugging.
        return out

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_request(
        self,
        instance: Dict[str, Any],
        schemas: List[Dict[str, Any]],
    ) -> Tuple[str, List[Any]]:
        data = instance.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        text_blocks: List[str] = []

        # Top-level text/task description
        task_text = (
            data.get("task_description")
            or data.get("text")
            or instance.get("text", "")
        )
        if task_text:
            text_blocks.append(f"## Task\n{task_text}".strip())

        # Dialogue / conversation arrays
        if self.config.include_dialogue_text:
            for key in _FIELD_DETECTORS["dialogue"]:
                value = data.get(key)
                if value:
                    rendered = self._render_dialogue(value)
                    if rendered:
                        text_blocks.append(f"## {key.title()}\n{rendered}")
                    break  # Only render the first matching dialogue field

        # Spreadsheet / table data
        if self.config.include_spreadsheet:
            for key in _FIELD_DETECTORS["spreadsheet"]:
                value = data.get(key)
                if value:
                    rendered = self._render_spreadsheet(value)
                    if rendered:
                        text_blocks.append(f"## {key.replace('_', ' ').title()}\n{rendered}")
                    break

        # Other plain-text fields not already consumed
        consumed = (
            {"task_description", "text", "id"}
            | set(_FIELD_DETECTORS["dialogue"])
            | set(_FIELD_DETECTORS["spreadsheet"])
            | set(_FIELD_DETECTORS["image"])
            | {"gold_labels"}
        )
        for k, v in data.items():
            if k in consumed or k.startswith("_"):
                continue
            if isinstance(v, (str, int, float)) and str(v).strip():
                text_blocks.append(f"## {k}\n{v}")

        # Schema spec section (instance is needed for step-aware schemas)
        text_blocks.append(self._render_schema_spec(schemas, instance))

        text_blocks.append(
            "Respond with a single JSON object {\"annotations\": {...}, \"reasoning\": \"...\"} "
            "where each key under 'annotations' is exactly the schema name listed above. "
            "The value type matches the schema:\n"
            "- radio / multiselect / likert with named labels: a string label\n"
            "- likert / slider / number without labels: an integer in the allowed range\n"
            "- text / textbox: a short free-text string\n"
            "- multiselect: a JSON array of label strings\n"
            "- process_reward: an integer step index (or null) for first_error mode, "
            "or a JSON array of 1/-1/0 for per_step mode\n"
            "- code_review: a JSON object with verdict, comments, file_ratings keys\n"
            "Always include EVERY schema name as a key under 'annotations'."
        )

        prompt = "\n\n".join(text_blocks)

        # Collect image payloads (paths or URLs)
        image_payloads = self._collect_images(data)
        return prompt, image_payloads

    def _render_dialogue(self, value: Any) -> str:
        if isinstance(value, str):
            return value[: self.config.max_dialogue_chars]
        if not isinstance(value, list):
            return ""
        lines: List[str] = []
        for i, turn in enumerate(value, start=1):
            if isinstance(turn, dict):
                speaker = turn.get("speaker") or turn.get("role") or f"Turn {i}"
                text = turn.get("text") or turn.get("content") or ""
                lines.append(f"{i}. {speaker}: {text}")
                # Coding-agent shape: each turn may carry a list of
                # {tool, input, output, output_type, language} entries.
                # Render them so the LLM rater can see the actions taken.
                tool_calls = turn.get("tool_calls")
                if isinstance(tool_calls, list):
                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        lines.append(self._render_tool_call(call))
            else:
                lines.append(f"{i}. {turn}")
        rendered = "\n".join(lines)
        return rendered[: self.config.max_dialogue_chars]

    def _render_tool_call(self, call: Dict[str, Any]) -> str:
        tool_name = call.get("tool") or call.get("name") or "tool"
        # Inputs may be a dict or a string -- format for readability.
        raw_input = call.get("input") or call.get("arguments") or {}
        if isinstance(raw_input, dict):
            input_str = ", ".join(f"{k}={v!r}" for k, v in raw_input.items())
        else:
            input_str = str(raw_input)
        input_str = input_str[:_MAX_TOOL_INPUT_CHARS]

        output = call.get("output")
        if output is None:
            return f"   [tool: {tool_name}({input_str})]"
        output_str = str(output)
        if len(output_str) > _MAX_TOOL_OUTPUT_CHARS:
            output_str = (
                output_str[:_MAX_TOOL_OUTPUT_CHARS]
                + f"\n   [...truncated {len(output_str) - _MAX_TOOL_OUTPUT_CHARS} chars]"
            )
        return f"   [tool: {tool_name}({input_str})]\n   -> {output_str}"

    def _render_spreadsheet(self, value: Any) -> str:
        if isinstance(value, list) and value and isinstance(value[0], dict):
            keys = list(value[0].keys())
            header = " | ".join(keys)
            rows = [
                " | ".join(str(row.get(k, "")) for k in keys) for row in value
            ]
            return header + "\n" + "\n".join(rows)
        if isinstance(value, dict):
            return "\n".join(f"{k}: {v}" for k, v in value.items())
        return str(value)

    def _render_schema_spec(
        self,
        schemas: List[Dict[str, Any]],
        instance: Optional[Dict[str, Any]] = None,
    ) -> str:
        data = (instance or {}).get("data") or {}
        lines = ["## Schemas to label"]
        for schema in schemas:
            name = schema.get("name", "?")
            atype = schema.get("annotation_type") or schema.get("type") or "?"
            desc = schema.get("description", "")
            labels = self.random_strategy._extract_labels(schema)
            allowed: str
            if labels:
                allowed = "labels=" + ", ".join(labels)
            elif atype == "likert":
                size = schema.get("size", 5)
                allowed = f"integer 1..{size}"
            elif atype in ("slider", "number"):
                lo = schema.get("min_value", schema.get("min", 0))
                hi = schema.get("max_value", schema.get("max", 100))
                allowed = f"integer {lo}..{hi}"
            elif atype == "process_reward":
                steps_key = schema.get("steps_key", "structured_turns")
                steps = data.get(steps_key) if isinstance(data, dict) else None
                n = len(steps) if isinstance(steps, list) else 0
                mode = schema.get("mode", "first_error")
                if mode == "first_error":
                    allowed = (
                        f"first_error mode: integer 0..{max(n - 1, 0)} "
                        f"(index of the first wrong step in the {n}-step trace), "
                        "or null if every step is correct"
                    )
                else:
                    allowed = (
                        f"per_step mode: list of {n} entries, each one of "
                        "1 (correct), -1 (incorrect), 0 (unmarked)"
                    )
            elif atype == "code_review":
                verdicts = schema.get(
                    "verdict_options", ["approve", "request_changes", "comment_only"]
                )
                allowed = (
                    "object with keys: "
                    "verdict (one of " + ", ".join(verdicts) + "), "
                    "comments (list of {file, line?, category, body}), "
                    "file_ratings (object: filename -> {dim: 1..5})"
                )
            else:
                allowed = "free text"
            lines.append(f"- {name} ({atype}): {desc} [{allowed}]")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Image handling
    # ------------------------------------------------------------------

    def _collect_images(self, data: Dict[str, Any]) -> List[Any]:
        """Return up to ``max_image_count`` ImageData objects."""
        try:
            from potato.ai.ai_endpoint import ImageData
        except Exception:
            return []

        candidates: List[str] = []
        for key in _FIELD_DETECTORS["image"]:
            value = data.get(key)
            if not value:
                continue
            if isinstance(value, str):
                candidates.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        candidates.append(item)

        images: List[Any] = []
        for path_or_url in candidates[: self.config.max_image_count]:
            payload = self._load_image(path_or_url, ImageData)
            if payload is not None:
                images.append(payload)
        return images

    def _load_image(self, path_or_url: str, ImageData):
        try:
            if path_or_url.startswith(("http://", "https://", "data:")):
                # Remote / inline data URI -- pass through unchanged
                return ImageData(url=path_or_url) if hasattr(ImageData, "url") else None

            if not os.path.exists(path_or_url):
                logger.debug("Agent strategy: image not found at %s", path_or_url)
                return None

            with open(path_or_url, "rb") as f:
                raw = f.read()

            if self.config.max_image_dim:
                raw = self._maybe_resize(raw)

            b64 = base64.b64encode(raw).decode("ascii")
            # ImageData supports a few constructor signatures across providers;
            # try the most compatible one first.
            try:
                return ImageData(base64=b64, mime_type=self._guess_mime(path_or_url))
            except TypeError:
                try:
                    return ImageData(data=b64, mime_type=self._guess_mime(path_or_url))
                except TypeError:
                    return ImageData(b64)
        except Exception as e:
            logger.debug("Agent strategy: failed to load image %s: %s", path_or_url, e)
            return None

    def _maybe_resize(self, raw: bytes) -> bytes:
        try:
            from PIL import Image  # noqa: WPS433
        except Exception:
            return raw
        try:
            img = Image.open(io.BytesIO(raw))
            longest = max(img.size)
            if longest <= self.config.max_image_dim:
                return raw
            scale = self.config.max_image_dim / longest
            new_size = (max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale)))
            img = img.convert("RGB").resize(new_size)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
        except Exception:
            return raw

    def _guess_mime(self, path: str) -> str:
        lowered = path.lower()
        if lowered.endswith(".png"):
            return "image/png"
        if lowered.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if lowered.endswith(".webp"):
            return "image/webp"
        if lowered.endswith(".gif"):
            return "image/gif"
        return "image/jpeg"

    # ------------------------------------------------------------------
    # LLM invocation + response parsing
    # ------------------------------------------------------------------

    def _invoke(self, prompt: str, image_payloads: List[Any]) -> Any:
        """Call the endpoint, preferring vision API when images are present."""
        if image_payloads and hasattr(self.endpoint, "query_with_image"):
            return self.endpoint.query_with_image(
                prompt, image_payloads, _AgentLabelResponse
            )
        return self.endpoint.query(prompt, _AgentLabelResponse)

    def _parse_response(self, response: Any) -> Optional[Dict[str, Any]]:
        if response is None:
            return None
        # Endpoints with structured output return a dict-like object
        if hasattr(response, "model_dump"):
            data = response.model_dump()
        elif isinstance(response, dict):
            data = response
        elif isinstance(response, str):
            data = self._loose_json_parse(response)
        else:
            try:
                data = dict(response)
            except Exception:
                return None
        if not isinstance(data, dict):
            return None
        annotations = data.get("annotations") if isinstance(data, dict) else None
        if isinstance(annotations, dict):
            return annotations
        # Some endpoints return the raw annotations dict directly
        if all(isinstance(k, str) for k in data.keys()) and "reasoning" not in data:
            return data
        return None

    def _loose_json_parse(self, text: str) -> Dict[str, Any]:
        try:
            return json.loads(text)
        except Exception:
            pass
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        return {}

    # ------------------------------------------------------------------
    # Format translation: model output -> wire annotation
    # ------------------------------------------------------------------

    def _format_value(
        self,
        schema_name: str,
        raw_value: Any,
        annotation_type: str,
        labels: List[str],
        schema: Dict[str, Any],
        instance: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if annotation_type == "process_reward":
            return self._format_process_reward(
                schema_name, raw_value, schema, instance
            )

        if annotation_type == "code_review":
            return self._format_code_review(schema_name, raw_value, schema)

        if annotation_type == "multiselect":
            chosen = self._coerce_multilabels(raw_value, labels)
            if not chosen:
                return None
            return {f"{schema_name}:{label}": "on" for label in chosen}

        if annotation_type == "radio":
            chosen = self._coerce_label(raw_value, labels)
            if chosen is None:
                return None
            return {f"{schema_name}:{chosen}": "on"}

        if annotation_type == "likert":
            size = schema.get("size", 5)
            chosen = self._coerce_int(raw_value, 1, size)
            if chosen is None and labels:
                # Some likert schemas use named labels (e.g. ["Wrong","Right"])
                lbl = self._coerce_label(raw_value, labels)
                if lbl is not None:
                    return {f"{schema_name}:{lbl}": "on"}
            if chosen is None:
                return None
            return {f"{schema_name}:{chosen}": "on"}

        if annotation_type in ("slider", "number"):
            lo = schema.get("min_value", schema.get("min", 0))
            hi = schema.get("max_value", schema.get("max", 100))
            chosen = self._coerce_int(raw_value, lo, hi)
            if chosen is None:
                return None
            return {f"{schema_name}:{chosen}": str(chosen)}

        if annotation_type in ("text", "textbox"):
            return {f"{schema_name}:text": str(raw_value)[:1000]}

        # Unknown type — return string form
        return {f"{schema_name}:{raw_value}": "on"}

    def _coerce_label(self, raw_value: Any, labels: List[str]) -> Optional[str]:
        if not labels:
            return None
        if isinstance(raw_value, str):
            candidate = raw_value.strip()
            for label in labels:
                if label.lower() == candidate.lower():
                    return label
            for label in labels:
                if label.lower() in candidate.lower() or candidate.lower() in label.lower():
                    return label
        return None

    def _coerce_multilabels(self, raw_value: Any, labels: List[str]) -> List[str]:
        if not labels:
            return []
        if isinstance(raw_value, list):
            chosen: List[str] = []
            for item in raw_value:
                resolved = self._coerce_label(item, labels)
                if resolved and resolved not in chosen:
                    chosen.append(resolved)
            return chosen
        if isinstance(raw_value, str):
            parts = re.split(r"[,;|]", raw_value)
            chosen = []
            for part in parts:
                resolved = self._coerce_label(part, labels)
                if resolved and resolved not in chosen:
                    chosen.append(resolved)
            return chosen
        return []

    # ------------------------------------------------------------------
    # Custom-schema wire-format helpers
    # ------------------------------------------------------------------

    def _format_process_reward(
        self,
        schema_name: str,
        raw_value: Any,
        schema: Dict[str, Any],
        instance: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Build the wire-format payload for a process_reward schema.

        Server expects ``{"<schema>:::<schema>": "<json>"}`` where the JSON
        is ``{"steps": [{"index": N, "reward": 1|-1|0}, ...], "mode": ...}``.
        """
        steps_key = schema.get("steps_key", "structured_turns")
        mode = schema.get("mode", "first_error")
        data = (instance or {}).get("data") or {}
        steps = data.get(steps_key) if isinstance(data, dict) else None
        n = len(steps) if isinstance(steps, list) else 0
        if n == 0:
            return None

        if mode == "first_error":
            first_wrong = self._coerce_first_wrong_index(raw_value, n)
            entries = []
            for idx in range(n):
                if first_wrong is None:
                    reward = 1
                elif idx < first_wrong:
                    reward = 1
                else:
                    reward = -1
                entries.append({"index": idx, "reward": reward})
        else:
            entries = self._coerce_per_step_rewards(raw_value, n)
            if entries is None:
                return None

        payload = {"steps": entries, "mode": mode}
        return {f"{schema_name}:::{schema_name}": json.dumps(payload)}

    def _coerce_first_wrong_index(self, raw_value: Any, n: int) -> Optional[int]:
        """Interpret the LLM's first-error response as an int in 0..n-1 or None."""
        if raw_value is None:
            return None
        if isinstance(raw_value, str) and raw_value.strip().lower() in (
            "null", "none", "all_correct", "n/a", ""
        ):
            return None
        if isinstance(raw_value, dict):
            for key in ("first_wrong", "first_error", "index", "step"):
                if key in raw_value:
                    return self._coerce_first_wrong_index(raw_value[key], n)
            return None
        idx = self._coerce_int(raw_value, 0, max(n - 1, 0))
        return idx

    def _coerce_per_step_rewards(
        self, raw_value: Any, n: int
    ) -> Optional[List[Dict[str, int]]]:
        """Interpret the LLM's per_step response as a list of n {index,reward} entries."""
        items: List[int] = []
        if isinstance(raw_value, list):
            for v in raw_value:
                if isinstance(v, dict) and "reward" in v:
                    items.append(self._normalize_reward(v["reward"]))
                else:
                    items.append(self._normalize_reward(v))
        elif isinstance(raw_value, str):
            for part in re.split(r"[\s,;|]+", raw_value):
                if not part:
                    continue
                items.append(self._normalize_reward(part))
        else:
            return None

        if len(items) < n:
            items.extend([0] * (n - len(items)))
        items = items[:n]
        return [{"index": i, "reward": r} for i, r in enumerate(items)]

    def _normalize_reward(self, value: Any) -> int:
        """Map various encodings to the server's {1, -1, 0} reward space."""
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("1", "+1", "correct", "good", "true", "yes", "ok"):
                return 1
            if v in ("-1", "incorrect", "wrong", "bad", "false", "no"):
                return -1
            return 0
        try:
            i = int(value)
        except (TypeError, ValueError):
            return 0
        if i > 0:
            return 1
        if i < 0:
            return -1
        return 0

    def _format_code_review(
        self,
        schema_name: str,
        raw_value: Any,
        schema: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Build the wire-format payload for a code_review schema.

        Server expects ``{"<schema>:::<schema>": "<json>"}`` where the JSON
        is ``{"verdict": "...", "comments": [...], "file_ratings": {...}}``.
        """
        verdicts = schema.get(
            "verdict_options",
            ["approve", "request_changes", "comment_only"],
        )
        categories = schema.get(
            "comment_categories",
            ["bug", "style", "suggestion", "security", "question"],
        )
        rating_dims = schema.get(
            "file_rating_dimensions",
            ["correctness", "readability", "maintainability"],
        )

        verdict, comments, file_ratings = "comment_only", [], {}

        if isinstance(raw_value, dict):
            v = raw_value.get("verdict")
            if isinstance(v, str):
                v_lower = v.strip().lower()
                for option in verdicts:
                    if v_lower == option.lower() or v_lower in option.lower():
                        verdict = option
                        break

            raw_comments = raw_value.get("comments") or []
            if isinstance(raw_comments, list):
                for c in raw_comments:
                    if not isinstance(c, dict):
                        continue
                    body = str(c.get("body") or c.get("text") or c.get("comment") or "").strip()
                    if not body:
                        continue
                    cat = str(c.get("category") or "").strip().lower()
                    if cat not in {x.lower() for x in categories}:
                        cat = categories[0]
                    else:
                        # restore original casing
                        cat = next(x for x in categories if x.lower() == cat)
                    entry = {
                        "category": cat,
                        "body": body[:1000],
                    }
                    if c.get("file"):
                        entry["file"] = str(c["file"])
                    line = c.get("line")
                    if isinstance(line, int):
                        entry["line"] = line
                    comments.append(entry)

            raw_ratings = raw_value.get("file_ratings") or raw_value.get("ratings") or {}
            if isinstance(raw_ratings, dict):
                for filename, dims in raw_ratings.items():
                    if not isinstance(dims, dict):
                        continue
                    clean_dims: Dict[str, int] = {}
                    for dim, score in dims.items():
                        dim_match = next(
                            (d for d in rating_dims if d.lower() == str(dim).lower()),
                            None,
                        )
                        if dim_match is None:
                            continue
                        clamped = self._coerce_int(score, 1, 5)
                        if clamped is not None:
                            clean_dims[dim_match] = clamped
                    if clean_dims:
                        file_ratings[str(filename)] = clean_dims

        elif isinstance(raw_value, str):
            v_lower = raw_value.strip().lower()
            for option in verdicts:
                if v_lower == option.lower() or v_lower in option.lower():
                    verdict = option
                    break

        payload = {
            "verdict": verdict,
            "comments": comments,
            "file_ratings": file_ratings,
        }
        return {f"{schema_name}:::{schema_name}": json.dumps(payload)}

    def _coerce_int(self, raw_value: Any, lo: int, hi: int) -> Optional[int]:
        try:
            value = int(float(raw_value))
        except (TypeError, ValueError):
            if isinstance(raw_value, str):
                m = re.search(r"-?\d+", raw_value)
                if m:
                    try:
                        value = int(m.group(0))
                    except ValueError:
                        return None
                else:
                    return None
            else:
                return None
        if value < lo:
            value = lo
        elif value > hi:
            value = hi
        return value

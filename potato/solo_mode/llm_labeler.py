"""
LLM Labeler for Solo Mode

This module provides background LLM labeling functionality for Solo Mode.
It manages a thread that continuously labels instances while the human
annotator works, enabling parallel annotation.
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from queue import Queue, Empty

logger = logging.getLogger(__name__)


@dataclass
class LabelingResult:
    """Result of labeling a single instance."""
    instance_id: str
    schema_name: str
    label: Any
    confidence: float
    uncertainty: float
    reasoning: str
    prompt_version: int
    model_name: str
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None

    # Edge case rule discovery (Co-DETECT-style)
    is_edge_case: bool = False
    edge_case_rule: Optional[str] = None      # "When <condition> -> <action>"
    edge_case_condition: Optional[str] = None  # The <condition> part
    edge_case_action: Optional[str] = None     # The <action> part

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        result = {
            'instance_id': self.instance_id,
            'schema_name': self.schema_name,
            'label': self.label,
            'confidence': self.confidence,
            'uncertainty': self.uncertainty,
            'reasoning': self.reasoning,
            'prompt_version': self.prompt_version,
            'model_name': self.model_name,
            'timestamp': self.timestamp.isoformat(),
            'error': self.error,
        }
        if self.is_edge_case:
            result['is_edge_case'] = True
            result['edge_case_rule'] = self.edge_case_rule
            result['edge_case_condition'] = self.edge_case_condition
            result['edge_case_action'] = self.edge_case_action
        return result


class LLMLabelingThread(threading.Thread):
    """
    Background thread for LLM labeling.

    Continuously labels instances from a queue, respecting configured
    limits on parallel labeling and batch sizes.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        solo_config: Any,
        prompt_getter: callable,
        result_callback: callable,
        prompt_version_getter: Optional[callable] = None,
        examples_getter: Optional[callable] = None,
    ):
        """
        Initialize the labeling thread.

        Args:
            config: Full application configuration
            solo_config: SoloModeConfig instance
            prompt_getter: Callable that returns the current prompt text
            result_callback: Callable to handle labeling results
            prompt_version_getter: Optional callable that returns current prompt version int
            examples_getter: Optional callable that returns ICL examples list
        """
        super().__init__(name="LLMLabelingThread", daemon=True)

        self.config = config
        self.solo_config = solo_config
        self.prompt_getter = prompt_getter
        self.examples_getter = examples_getter
        self.result_callback = result_callback
        self.prompt_version_getter = prompt_version_getter

        # Threading control
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()

        # Instance queue
        self._queue: Queue = Queue()

        # State
        self._labeled_count = 0
        self._error_count = 0
        self._last_error: Optional[str] = None

        # AI endpoint (lazy init)
        self._endpoint = None
        self._uncertainty_estimator = None
        self._summary_endpoint = None
        self._summary_endpoint_failed = False
        self._summarizer_fn = None

    def _get_endpoint(self) -> Optional[Any]:
        """Get or create the labeling AI endpoint."""
        if self._endpoint is not None:
            return self._endpoint

        if not self.solo_config.labeling_models:
            logger.warning("No labeling models configured")
            return None

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            for model_config in self.solo_config.labeling_models:
                try:
                    endpoint_config = model_config.to_endpoint_config()

                    endpoint = AIEndpointFactory.create_endpoint(endpoint_config)
                    if endpoint:
                        self._endpoint = endpoint
                        logger.info(
                            f"Using labeling endpoint: "
                            f"{model_config.endpoint_type}/{model_config.model}"
                        )
                        return endpoint
                except Exception as e:
                    logger.debug(f"Failed to create endpoint {model_config.model}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error creating labeling endpoint: {e}")

        return None

    def _get_uncertainty_estimator(self) -> Optional[Any]:
        """Get or create the uncertainty estimator."""
        if self._uncertainty_estimator is not None:
            return self._uncertainty_estimator

        try:
            from .uncertainty import create_uncertainty_estimator

            strategy = self.solo_config.uncertainty.strategy
            estimator_config = {}

            if strategy == 'sampling_diversity':
                estimator_config = {
                    'num_samples': self.solo_config.uncertainty.num_samples,
                    'temperature': self.solo_config.uncertainty.sampling_temperature,
                }

            self._uncertainty_estimator = create_uncertainty_estimator(
                strategy,
                estimator_config
            )
            return self._uncertainty_estimator

        except Exception as e:
            logger.warning(f"Could not create uncertainty estimator: {e}")
            return None

    def enqueue(self, instance_id: str, instance_text: str, schema_name: str) -> None:
        """Add an instance to the labeling queue."""
        self._queue.put({
            'instance_id': instance_id,
            'text': instance_text,
            'schema_name': schema_name,
        })

    def enqueue_batch(
        self,
        instances: List[Dict[str, Any]],
        schema_name: str
    ) -> int:
        """
        Add a batch of instances to the labeling queue.

        Args:
            instances: List of {'instance_id': str, 'text': str}
            schema_name: The schema to label for

        Returns:
            Number of instances enqueued
        """
        count = 0
        for inst in instances:
            self.enqueue(
                inst['instance_id'],
                inst['text'],
                schema_name
            )
            count += 1
        return count

    def stop(self) -> None:
        """Signal the thread to stop."""
        self._stop_event.set()
        # Put sentinel to unblock queue
        self._queue.put(None)

    def pause(self) -> None:
        """Pause labeling."""
        self._pause_event.set()

    def resume(self) -> None:
        """Resume labeling."""
        self._pause_event.clear()

    def is_paused(self) -> bool:
        """Check if labeling is paused."""
        return self._pause_event.is_set()

    def get_queue_size(self) -> int:
        """Get the current queue size."""
        return self._queue.qsize()

    def run(self) -> None:
        """Main thread loop."""
        logger.info("LLM labeling thread started")

        while not self._stop_event.is_set():
            # Check pause
            while self._pause_event.is_set() and not self._stop_event.is_set():
                time.sleep(1)

            try:
                # Get next item (with timeout to check stop event)
                item = self._queue.get(timeout=1.0)

                if item is None:  # Sentinel
                    continue

                # Process the item
                result = self._label_instance(
                    item['instance_id'],
                    item['text'],
                    item['schema_name']
                )

                if result:
                    self._labeled_count += 1
                    self.result_callback(result)
                else:
                    self._error_count += 1

            except Empty:
                continue
            except Exception as e:
                logger.error(f"Error in labeling thread: {e}")
                self._error_count += 1
                self._last_error = str(e)
                time.sleep(1)  # Back off on error

        logger.info("LLM labeling thread stopped")

    @staticmethod
    def create_endpoint_from_model_config(model_config):
        """Create an AI endpoint from a ModelConfig."""
        from potato.ai.ai_endpoint import AIEndpointFactory
        endpoint_config = model_config.to_endpoint_config()
        return AIEndpointFactory.create_endpoint(endpoint_config)

    def _label_instance(
        self,
        instance_id: str,
        text: str,
        schema_name: str,
        endpoint=None,
    ) -> Optional[LabelingResult]:
        """Label a single instance."""
        if endpoint is None:
            endpoint = self._get_endpoint()
        if endpoint is None:
            return None

        prompt = self.prompt_getter()
        if not prompt:
            logger.warning("No prompt available for labeling")
            return None

        try:
            # Get schema info
            schemes = self.config.get('annotation_schemes', [])
            schema_info = next(
                (s for s in schemes if s.get('name') == schema_name),
                None
            )
            if not schema_info:
                logger.warning(f"Schema {schema_name} not found")
                return None

            # Build labeling prompt
            labels = self._extract_labels(schema_info)

            # Assemble the exact prompt the LLM will see. Kept in one place
            # (_build_full_prompt) so the annotate-UI "Prompt the LLM sees"
            # preview can render byte-for-byte what labeling actually sends —
            # including the live codebook section — with zero drift.
            assembled = self._build_full_prompt(text, labels, schema_info)
            full_prompt = assembled["full_prompt"]
            request_edge_case = assembled["request_edge_case"]

            # Query endpoint
            from pydantic import BaseModel

            class LabelResponse(BaseModel):
                label: str
                confidence: float = 50.0
                reasoning: str = ""

            response = endpoint.query(full_prompt, LabelResponse)

            # Parse response
            if isinstance(response, str):
                response_data = self._parse_json_response(response)
            elif hasattr(response, 'model_dump'):
                response_data = response.model_dump()
            else:
                response_data = response

            label = response_data.get('label', '')
            confidence = float(response_data.get('confidence', 50)) / 100.0
            reasoning = response_data.get('reasoning', '')

            # Validate label
            valid_labels = self._get_valid_labels(schema_info)
            if valid_labels and label not in valid_labels:
                label = self._fuzzy_match_label(label, valid_labels)
                if label is None:
                    return LabelingResult(
                        instance_id=instance_id,
                        schema_name=schema_name,
                        label=None,
                        confidence=0,
                        uncertainty=1,
                        reasoning="",
                        prompt_version=0,
                        model_name=getattr(endpoint, 'model', ''),
                        error="Invalid label returned"
                    )

            # Estimate uncertainty using configured strategy
            uncertainty = 1.0 - confidence
            estimator = self._get_uncertainty_estimator()
            if estimator:
                try:
                    logger.debug(f"Running uncertainty estimation ({estimator.__class__.__name__}) for {instance_id}")
                    estimate = estimator.estimate_uncertainty(
                        instance_id=instance_id,
                        text=text,
                        prompt=full_prompt,
                        predicted_label=label,
                        endpoint=endpoint,
                        schema_info=schema_info
                    )
                    uncertainty = estimate.uncertainty_score
                    confidence = estimate.confidence_score
                    logger.debug(
                        f"Uncertainty estimate for {instance_id}: "
                        f"conf={confidence:.3f}, unc={uncertainty:.3f}, "
                        f"method={estimate.method}"
                    )
                except Exception as e:
                    logger.warning(f"Uncertainty estimation failed for {instance_id}: {e}")

            # Extract edge case rule if present
            is_edge_case = False
            edge_case_rule = None
            edge_case_condition = None
            edge_case_action = None

            if request_edge_case and response_data.get('is_edge_case'):
                raw_rule = response_data.get('edge_case_rule', '')
                if raw_rule:
                    is_edge_case = True
                    edge_case_rule = raw_rule
                    edge_case_condition, edge_case_action = (
                        self._parse_edge_case_rule(raw_rule)
                    )

            prompt_version = 0
            if self.prompt_version_getter:
                try:
                    prompt_version = self.prompt_version_getter()
                except Exception:
                    pass

            return LabelingResult(
                instance_id=instance_id,
                schema_name=schema_name,
                label=label,
                confidence=confidence,
                uncertainty=uncertainty,
                reasoning=reasoning,
                prompt_version=prompt_version,
                model_name=getattr(endpoint, 'model', ''),
                is_edge_case=is_edge_case,
                edge_case_rule=edge_case_rule,
                edge_case_condition=edge_case_condition,
                edge_case_action=edge_case_action,
            )

        except Exception as e:
            logger.error(f"Error labeling {instance_id}: {e}")
            return LabelingResult(
                instance_id=instance_id,
                schema_name=schema_name,
                label=None,
                confidence=0,
                uncertainty=1,
                reasoning="",
                prompt_version=0,
                model_name='',
                error=str(e)
            )

    def _build_full_prompt(
        self,
        text: str,
        labels: str,
        schema_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assemble the full prompt sent to the LLM for one instance, and
        return it alongside its component sections.

        This is the single source of truth for the labeling prompt: both
        ``_label_instance`` (which queries the model) and the annotate-UI
        prompt preview (which only displays) call it, so what the user sees
        is exactly what the model is given. The base prompt is re-fetched
        here via ``prompt_getter`` so the preview reflects the current
        prompt version.
        """
        base_prompt = self.prompt_getter() or ""

        # Transparently augment the user's prompt with the project's
        # structured codebook (definitions / include / exclude / worked
        # examples). Returns "" unless the codebook carries structured
        # fields, so plain-label projects are unaffected.
        codebook_section = self._codebook_section()

        # Resolve the embedding endpoint and embed this instance ONCE,
        # shared by guideline + ICL retrieval (Req 5). (None, None) unless
        # a RAG path is actually active, so the default path does no
        # embedding work.
        rag_ep, rag_qv = self._rag_prepare(text)

        # RAG-retrieved guideline fragments (default OFF; "" unless
        # config['rag']['inject_guidelines']). Additive — never trims the
        # codebook/label set.
        guideline_section = self._guideline_section(
            text, endpoint=rag_ep, query_vec=rag_qv)

        # Check if edge case rule extraction is enabled
        ecr_config = getattr(self.solo_config, 'edge_case_rules', None)
        request_edge_case = (
            ecr_config is not None
            and ecr_config.enabled
            and ecr_config.auto_extract_on_labeling
        )

        # Build ICL examples section if available
        icl_section = ""
        if self.examples_getter:
            try:
                # Per-instance ICL selection when the getter supports it
                # (shares the instance embedding); older no-arg getters
                # still work.
                try:
                    examples = self.examples_getter(
                        instance_text=text, query_vec=rag_qv,
                        endpoint=rag_ep)
                except TypeError:
                    examples = self.examples_getter()
                if examples:
                    icl_lines = ["## Examples"]
                    for ex in examples:
                        icl_lines.append(f'Text: "{ex["text"]}"')
                        icl_lines.append(f'Label: {ex["label"]}')
                        icl_lines.append("")
                    icl_section = "\n".join(icl_lines) + "\n"
            except Exception:
                pass

        if request_edge_case:
            full_prompt = f"""{base_prompt}

{codebook_section}{guideline_section}{icl_section}Text to label:
{text}

Available labels: {labels}

Respond with JSON. If you are uncertain about the label (confidence below 75), also identify a generalizable edge case rule that describes when this type of ambiguity occurs:
{{
    "label": "<your label or -1 if unclassifiable>",
    "confidence": <0-100>,
    "reasoning": "<brief explanation>",
    "is_edge_case": <true if this is an ambiguous/edge case, false otherwise>,
    "edge_case_rule": "<When [condition] -> [action]> (only if is_edge_case is true)"
}}
"""
        else:
            full_prompt = f"""{base_prompt}

{codebook_section}{guideline_section}{icl_section}Text to label:
{text}

Available labels: {labels}

Respond with JSON:
{{
    "label": "<your label>",
    "confidence": <0-100>,
    "reasoning": "<brief explanation>"
}}
"""

        return {
            "full_prompt": full_prompt,
            "base_prompt": base_prompt,
            "codebook_section": codebook_section,
            "guideline_section": guideline_section,
            "icl_section": icl_section,
            "request_edge_case": request_edge_case,
        }

    def _codebook_section(self) -> str:
        """Structured codebook block for the current project, or "" when
        the project has no structured codebook fields. Trailing newlines
        keep it cleanly separated from the rest of the prompt; best-effort
        so it can never break labeling."""
        try:
            from potato.codebook.prompt import render_codebook_section
            from potato.solo_mode.distill_options import effective_options
            task_dir = self.config.get('task_dir', '.')
            project = self.config.get('annotation_task_name') or 'default'
            options = effective_options(self.solo_config)
            summarize = None
            if options.get('summarize_above_tokens', 0) > 0:
                # Lazy: only resolves (and potentially connects to) the
                # summary endpoint the first time a field actually exceeds
                # the threshold, so a codebook with nothing to summarize
                # never pays for endpoint construction. See _summarize_field.
                summarize = self._summarize_field
            section = render_codebook_section(
                task_dir, project, options=options, summarize=summarize)
            return (section + "\n\n") if section else ""
        except Exception:
            return ""

    def _summarize_field(self, code_id, field: str, text: str) -> str:
        """``summarize`` callback for render_from_codebook — called only
        when a field's length exceeds the configured threshold. Resolves
        the summary endpoint lazily (on first actual need) rather than on
        every prompt build, and never retries a model that has already
        failed to connect this session (see _get_summary_endpoint)."""
        endpoint = self._get_summary_endpoint()
        if endpoint is None:
            return text
        if self._summarizer_fn is None:
            from potato.codebook.summarizer import make_summarizer
            task_dir = self.config.get('task_dir', '.')
            self._summarizer_fn = make_summarizer(task_dir, endpoint)
        return self._summarizer_fn(code_id, field, text)

    def _get_summary_endpoint(self) -> Optional[Any]:
        """Endpoint used for length-k codebook summarization — the
        revision model (falls back to the labeling model), same source
        `guideline_updater._get_revision_endpoint` uses. Best-effort and
        cached: a failure here just means summarization is skipped and
        the full instruction text is rendered instead.

        Caches BOTH success and failure. Endpoint construction can be a
        blocking network call (e.g. Ollama's client health-checks the
        host in its constructor), so once every candidate model has
        failed we stop retrying for the rest of this thread's life —
        otherwise every single prompt build (including the synchronous
        on-demand /llm-suggestion request) would re-pay that blocking
        cost forever whenever no revision model is reachable."""
        if self._summary_endpoint is not None:
            return self._summary_endpoint
        if self._summary_endpoint_failed:
            return None
        try:
            models = (self.solo_config.revision_models
                      or self.solo_config.labeling_models)
            for model_config in models:
                try:
                    endpoint = self.create_endpoint_from_model_config(
                        model_config)
                    if endpoint:
                        self._summary_endpoint = endpoint
                        return endpoint
                except Exception:
                    continue
        except Exception:
            logger.debug("could not create summarization endpoint",
                         exc_info=True)
        self._summary_endpoint_failed = True
        return None

    def _rag_active(self) -> bool:
        """True if any per-instance RAG path is enabled (guideline injection
        or per-instance ICL retrieval) — gates the shared embedding so the
        default path stays embedding-free."""
        rag_cfg = self.config.get('rag') or {}
        if rag_cfg.get('inject_guidelines'):
            return True
        icl_cfg = getattr(self.solo_config, 'icl', None) \
            if self.solo_config is not None else None
        return bool(icl_cfg and getattr(icl_cfg, 'selection_strategy', None)
                    == 'per_instance_retrieval')

    def _rag_prepare(self, text: str):
        """Resolve the endpoint and embed ``text`` ONCE for all per-instance
        retrieval (Req 5). (None, None) when no RAG path is active or no
        embedder is available — best-effort, never breaks labeling."""
        try:
            if not self._rag_active():
                return None, None
            emb_cfg = getattr(self.solo_config, 'embedding', None) \
                if self.solo_config is not None else None
            from potato.rag.retriever import prepare_instance
            task_dir = self.config.get('task_dir', '.')
            project = self.config.get('annotation_task_name') or 'default'
            return prepare_instance(task_dir, project, text, config=emb_cfg)
        except Exception:
            return None, None

    def _guideline_section(self, text: str, *, endpoint=None,
                           query_vec=None) -> str:
        """RAG-retrieved guideline fragments relevant to ``text``.

        Default OFF — returns "" unless ``config['rag']['inject_guidelines']``
        is set, so the default prompt is byte-identical to today. When on, it
        injects ONLY the top-k relevant guideline fragments (it never touches
        the codebook/label set). Reuses the shared instance embedding
        (Req 5). Best-effort: any retrieval failure -> "".

        NOTE: this is the additive, behind-a-flag step. Replacing the prompt's
        whole-document guideline injection with only these fragments
        ("guideline injection replace-flip") is a separate scoped follow-up
        that decouples guidelines from PromptVersion.
        """
        try:
            rag_cfg = self.config.get('rag') or {}
            if not rag_cfg.get('inject_guidelines'):
                return ""
            emb_cfg = getattr(self.solo_config, 'embedding', None) \
                if self.solo_config is not None else None
            from potato.rag.retriever import retrieve_guidelines
            task_dir = self.config.get('task_dir', '.')
            project = self.config.get('annotation_task_name') or 'default'
            k = int(rag_cfg.get('guideline_top_k', 3))
            hits = retrieve_guidelines(task_dir, project, text, k=k,
                                       config=emb_cfg, endpoint=endpoint,
                                       query_vec=query_vec)
            if not hits:
                return ""
            lines = ["## Relevant Guidelines"]
            lines += [f"- {h['text']}" for h in hits]
            return "\n".join(lines) + "\n\n"
        except Exception:
            return ""

    def _extract_labels(self, schema_info: Dict[str, Any]) -> str:
        """Extract label names from schema."""
        labels = schema_info.get('labels', [])
        label_names = []
        for label in labels:
            if isinstance(label, str):
                label_names.append(label)
            elif isinstance(label, dict):
                label_names.append(label.get('name', str(label)))
        return ', '.join(label_names)

    def _get_valid_labels(self, schema_info: Dict[str, Any]) -> List[str]:
        """Get valid label list from schema."""
        labels = schema_info.get('labels', [])
        valid = []
        for label in labels:
            if isinstance(label, str):
                valid.append(label)
            elif isinstance(label, dict):
                valid.append(label.get('name', str(label)))
        return valid

    def _fuzzy_match_label(self, label, valid: List[str]) -> Optional[str]:
        """Try to match label to valid labels. Handles non-string inputs gracefully."""
        if label is None:
            return None
        try:
            label_lower = str(label).lower().strip()
        except Exception:
            return None
        for v in valid:
            if str(v).lower().strip() == label_lower:
                return v
        return None

    def _parse_edge_case_rule(self, rule_text: str) -> tuple:
        """Parse a rule in 'When <condition> -> <action>' format.

        Returns:
            Tuple of (condition, action). Falls back to (rule_text, "") if
            the format doesn't match.
        """
        # Try "When <condition> -> <action>" format
        match = re.match(
            r'[Ww]hen\s+(.+?)\s*->\s*(.+)',
            rule_text.strip()
        )
        if match:
            return match.group(1).strip(), match.group(2).strip()

        # Try "If <condition>, then <action>" format
        match = re.match(
            r'[Ii]f\s+(.+?),?\s+then\s+(.+)',
            rule_text.strip()
        )
        if match:
            return match.group(1).strip(), match.group(2).strip()

        # Fallback: use full text as condition
        return rule_text.strip(), ""

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from response."""
        content = response.strip()

        if '```json' in content:
            match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
            if match:
                content = match.group(1).strip()
        elif '```' in content:
            match = re.search(r'```\s*([\s\S]*?)\s*```', content)
            if match:
                content = match.group(1).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to extract just the label
            return {'label': content}

    def get_stats(self) -> Dict[str, Any]:
        """Get labeling statistics."""
        return {
            'labeled_count': self._labeled_count,
            'error_count': self._error_count,
            'queue_size': self.get_queue_size(),
            'is_paused': self.is_paused(),
            'is_running': self.is_alive(),
            'last_error': self._last_error,
        }

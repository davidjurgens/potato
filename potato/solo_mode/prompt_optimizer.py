"""
Prompt Optimizer for Solo Mode

This module implements DSPy-style automatic prompt optimization.
It uses labeled examples to iteratively improve prompts for better
accuracy while maintaining brevity.
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from queue import Queue

logger = logging.getLogger(__name__)


OPTIMIZATION_PROMPT_TEMPLATE = """You are an expert at improving annotation prompts.

Given the current prompt and some examples where the LLM made mistakes,
suggest improvements to the prompt that would help get the correct labels.

## Current Prompt
{current_prompt}

## Correct Examples
These are examples where the LLM got the right answer:
{correct_examples}

## Incorrect Examples
These are examples where the LLM got the wrong answer (with corrections):
{incorrect_examples}

## Optimization Goals
1. Improve accuracy on the incorrect examples
2. Keep the prompt concise (shorter is better)
3. Make instructions clearer and more specific
4. Add clarifying examples if helpful

## Requirements
- Focus on patterns in the errors
- Don't make the prompt too long
- Keep successful patterns from the current prompt
- Be specific about edge cases

## Output Format
Respond with JSON:
{{
    "improved_prompt": "<the improved prompt text>",
    "changes_made": ["<change 1>", "<change 2>", ...],
    "rationale": "<why these changes should help>"
}}
"""


@dataclass
class OptimizationResult:
    """Result of a prompt optimization run."""
    original_prompt: str
    optimized_prompt: str
    changes_made: List[str]
    rationale: str
    accuracy_before: float
    accuracy_after: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)
    model_used: str = ""
    num_examples_used: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'original_prompt': self.original_prompt,
            'optimized_prompt': self.optimized_prompt,
            'changes_made': self.changes_made,
            'rationale': self.rationale,
            'accuracy_before': self.accuracy_before,
            'accuracy_after': self.accuracy_after,
            'timestamp': self.timestamp.isoformat(),
            'model_used': self.model_used,
            'num_examples_used': self.num_examples_used,
        }


@dataclass
class OptimizationConfig:
    """Configuration for prompt optimization."""
    enabled: bool = True
    find_smallest_model: bool = True
    target_accuracy: float = 0.85
    min_examples_for_optimization: int = 10
    optimization_interval_seconds: int = 300  # 5 minutes
    max_prompt_length: int = 2000
    accuracy_weight: float = 0.7
    length_weight: float = 0.2
    consistency_weight: float = 0.1


class PromptOptimizer:
    """
    DSPy-style automatic prompt optimization.

    Optimizes prompts based on:
    1. Accuracy on labeled examples
    2. Prompt length (shorter is better)
    3. Prediction consistency

    Can run in background or be triggered on-demand.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        solo_config: Any,
        prompt_getter: callable,
        prompt_setter: callable,
        examples_getter: callable,
    ):
        """
        Initialize the prompt optimizer.

        Args:
            config: Full application configuration
            solo_config: SoloModeConfig instance
            prompt_getter: Callable that returns current prompt text
            prompt_setter: Callable to update the prompt
            examples_getter: Callable that returns labeled examples
        """
        self.config = config
        self.solo_config = solo_config
        self.prompt_getter = prompt_getter
        self.prompt_setter = prompt_setter
        self.examples_getter = examples_getter

        # Load optimization config
        opt_config = getattr(solo_config, 'prompt_optimization', None)
        if opt_config:
            self.opt_config = OptimizationConfig(
                enabled=opt_config.get('enabled', True),
                find_smallest_model=opt_config.get('find_smallest_model', True),
                target_accuracy=opt_config.get('target_accuracy', 0.85),
            )
        else:
            self.opt_config = OptimizationConfig()

        self._lock = threading.RLock()

        # Optimization history
        self.optimization_history: List[OptimizationResult] = []

        # Background optimization
        self._background_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._optimization_queue: Queue = Queue()

        # AI endpoint (lazy init)
        self._endpoint = None

        # Cached labeled examples
        self._cached_examples: Dict[str, Dict[str, Any]] = {}

    def _get_endpoint(self) -> Optional[Any]:
        """Get or create the optimization endpoint."""
        if self._endpoint is not None:
            return self._endpoint

        if not self.solo_config.revision_models:
            logger.warning("No revision models configured for optimization")
            return None

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            for model_config in self.solo_config.revision_models:
                try:
                    endpoint_config = {
                        'ai_support': {
                            'enabled': True,
                            'endpoint_type': model_config.endpoint_type,
                            'ai_config': {
                                'model': model_config.model,
                                'max_tokens': model_config.max_tokens,
                                'temperature': 0.3,  # Lower for optimization
                            }
                        }
                    }
                    if model_config.api_key:
                        endpoint_config['ai_support']['ai_config']['api_key'] = model_config.api_key

                    endpoint = AIEndpointFactory.create_endpoint(endpoint_config)
                    if endpoint:
                        self._endpoint = endpoint
                        return endpoint
                except Exception as e:
                    logger.debug(f"Failed to create optimization endpoint: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error creating optimization endpoint: {e}")

        return None

    def optimize(self, force: bool = False) -> Optional[OptimizationResult]:
        """
        Run prompt optimization.

        Args:
            force: Run even if not enough examples

        Returns:
            OptimizationResult if optimization was performed
        """
        with self._lock:
            # Get labeled examples
            examples = self.examples_getter()
            if not examples and not force:
                logger.info("No labeled examples available for optimization")
                return None

            if len(examples) < self.opt_config.min_examples_for_optimization and not force:
                logger.info(
                    f"Not enough examples for optimization "
                    f"({len(examples)} < {self.opt_config.min_examples_for_optimization})"
                )
                return None

            # Get current prompt
            current_prompt = self.prompt_getter()
            if not current_prompt:
                logger.warning("No current prompt to optimize")
                return None

            # Get endpoint
            endpoint = self._get_endpoint()
            if endpoint is None:
                logger.warning("No endpoint available for optimization")
                return None

            # Split examples into correct and incorrect
            correct, incorrect = self._split_examples(examples)

            if not incorrect:
                logger.info("No incorrect predictions to optimize for")
                return None

            # Calculate current accuracy
            accuracy_before = len(correct) / len(examples) if examples else 0.0

            # Check if already above target
            if accuracy_before >= self.opt_config.target_accuracy and not force:
                logger.info(
                    f"Accuracy ({accuracy_before:.2%}) already above target "
                    f"({self.opt_config.target_accuracy:.2%})"
                )
                return None

            # Generate optimized prompt
            result = self._generate_optimized_prompt(
                current_prompt,
                correct[:5],  # Limit examples
                incorrect[:10],
                endpoint,
                accuracy_before,
            )

            if result:
                self.optimization_history.append(result)

                # Update prompt if optimization was successful
                if result.optimized_prompt and result.optimized_prompt != current_prompt:
                    self.prompt_setter(
                        result.optimized_prompt,
                        source='llm_optimization',
                        source_description='; '.join(result.changes_made)
                    )
                    logger.info(f"Prompt optimized: {len(result.changes_made)} changes made")

            return result

    def _split_examples(
        self,
        examples: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Split examples into correct and incorrect predictions."""
        correct = []
        incorrect = []

        for ex in examples:
            if ex.get('agrees', True):
                correct.append(ex)
            else:
                incorrect.append(ex)

        return correct, incorrect

    def _generate_optimized_prompt(
        self,
        current_prompt: str,
        correct_examples: List[Dict[str, Any]],
        incorrect_examples: List[Dict[str, Any]],
        endpoint: Any,
        accuracy_before: float,
    ) -> Optional[OptimizationResult]:
        """Generate an optimized prompt using the LLM."""
        try:
            # Format examples
            correct_text = self._format_examples(correct_examples, show_correction=False)
            incorrect_text = self._format_examples(incorrect_examples, show_correction=True)

            optimization_prompt = OPTIMIZATION_PROMPT_TEMPLATE.format(
                current_prompt=current_prompt,
                correct_examples=correct_text or "None available",
                incorrect_examples=incorrect_text or "None available",
            )

            from pydantic import BaseModel

            class OptimizationResponse(BaseModel):
                improved_prompt: str = ""
                changes_made: List[str] = []
                rationale: str = ""

            response = endpoint.query(optimization_prompt, OptimizationResponse)

            # Parse response
            if isinstance(response, str):
                response_data = self._parse_json_response(response)
            elif hasattr(response, 'model_dump'):
                response_data = response.model_dump()
            else:
                response_data = response

            improved_prompt = response_data.get('improved_prompt', '')
            changes_made = response_data.get('changes_made', [])
            rationale = response_data.get('rationale', '')

            # Validate improved prompt
            if not improved_prompt:
                logger.warning("Optimization returned empty prompt")
                return None

            if len(improved_prompt) > self.opt_config.max_prompt_length:
                logger.warning(
                    f"Optimized prompt too long ({len(improved_prompt)} > {self.opt_config.max_prompt_length})"
                )
                # Truncate if necessary
                improved_prompt = improved_prompt[:self.opt_config.max_prompt_length]

            return OptimizationResult(
                original_prompt=current_prompt,
                optimized_prompt=improved_prompt,
                changes_made=changes_made,
                rationale=rationale,
                accuracy_before=accuracy_before,
                model_used=getattr(endpoint, 'model', ''),
                num_examples_used=len(correct_examples) + len(incorrect_examples),
            )

        except Exception as e:
            logger.error(f"Error generating optimized prompt: {e}")
            return None

    def _format_examples(
        self,
        examples: List[Dict[str, Any]],
        show_correction: bool = False
    ) -> str:
        """Format examples for the optimization prompt."""
        if not examples:
            return ""

        formatted = []
        for i, ex in enumerate(examples[:10], 1):
            text = ex.get('text', '')[:200]  # Truncate long text
            predicted = ex.get('predicted_label', '')
            if show_correction:
                actual = ex.get('actual_label', ex.get('human_label', ''))
                formatted.append(
                    f"{i}. Text: \"{text}\"\n"
                    f"   LLM predicted: {predicted}\n"
                    f"   Correct label: {actual}"
                )
            else:
                formatted.append(
                    f"{i}. Text: \"{text}\"\n"
                    f"   Label: {predicted}"
                )

        return '\n\n'.join(formatted)

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
            return {}

    # === Background Optimization ===

    def start_background_optimization(self) -> bool:
        """Start background optimization thread."""
        with self._lock:
            if self._background_thread is not None and self._background_thread.is_alive():
                logger.warning("Background optimization already running")
                return False

            if not self.opt_config.enabled:
                logger.info("Prompt optimization is disabled")
                return False

            self._stop_event.clear()
            self._background_thread = threading.Thread(
                target=self._background_optimization_loop,
                name="PromptOptimizationThread",
                daemon=True
            )
            self._background_thread.start()
            logger.info("Started background prompt optimization")
            return True

    def stop_background_optimization(self) -> None:
        """Stop background optimization thread."""
        if self._background_thread is None:
            return

        self._stop_event.set()
        self._background_thread.join(timeout=5.0)
        self._background_thread = None
        logger.info("Stopped background prompt optimization")

    def is_running(self) -> bool:
        """Check if background optimization is running."""
        return (
            self._background_thread is not None and
            self._background_thread.is_alive()
        )

    def _background_optimization_loop(self) -> None:
        """Main loop for background optimization."""
        interval = self.opt_config.optimization_interval_seconds

        logger.info(f"Background optimization started (interval={interval}s)")

        while not self._stop_event.is_set():
            try:
                # Wait for interval
                if self._stop_event.wait(timeout=interval):
                    break  # Stop event was set

                # Run optimization
                result = self.optimize()
                if result:
                    logger.info(
                        f"Background optimization completed: "
                        f"accuracy {result.accuracy_before:.2%} -> {result.accuracy_after or 'pending'}"
                    )

            except Exception as e:
                logger.error(f"Error in background optimization: {e}")

    # === Model Selection ===

    def find_smallest_accurate_model(
        self,
        models: List[Any],
        test_examples: List[Dict[str, Any]],
        prompt: str,
    ) -> Optional[str]:
        """
        Find the smallest model that achieves target accuracy.

        Args:
            models: List of model configs (ordered small to large)
            test_examples: Examples to test accuracy on
            prompt: The prompt to use

        Returns:
            Model name if found, None otherwise
        """
        if not self.opt_config.find_smallest_model:
            return None

        target = self.opt_config.target_accuracy

        for model_config in models:
            try:
                accuracy = self._test_model_accuracy(
                    model_config, test_examples, prompt
                )
                if accuracy >= target:
                    logger.info(
                        f"Model {model_config.model} achieves {accuracy:.2%} accuracy"
                    )
                    return model_config.model
            except Exception as e:
                logger.debug(f"Error testing model {model_config.model}: {e}")
                continue

        logger.warning("No model achieved target accuracy")
        return None

    def _test_model_accuracy(
        self,
        model_config: Any,
        examples: List[Dict[str, Any]],
        prompt: str,
    ) -> float:
        """Test a model's accuracy on examples."""
        # This is a placeholder - full implementation would
        # run predictions with the model and calculate accuracy
        return 0.0

    # === Status and History ===

    def get_optimization_history(self) -> List[OptimizationResult]:
        """Get optimization history."""
        with self._lock:
            return self.optimization_history.copy()

    def get_last_optimization(self) -> Optional[OptimizationResult]:
        """Get the most recent optimization result."""
        with self._lock:
            if self.optimization_history:
                return self.optimization_history[-1]
            return None

    def get_status(self) -> Dict[str, Any]:
        """Get optimizer status."""
        with self._lock:
            last = self.get_last_optimization()
            return {
                'enabled': self.opt_config.enabled,
                'is_running': self.is_running(),
                'optimization_count': len(self.optimization_history),
                'last_optimization': last.to_dict() if last else None,
                'target_accuracy': self.opt_config.target_accuracy,
                'interval_seconds': self.opt_config.optimization_interval_seconds,
            }

    def clear_history(self) -> None:
        """Clear optimization history."""
        with self._lock:
            self.optimization_history.clear()

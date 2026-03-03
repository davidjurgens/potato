"""
Iterative Guideline Refinement Loop for Solo Mode

Orchestrates the automated cycle:
  confusion analysis → guideline suggestions → prompt revision → re-annotation

Monitors agreement rate trends and stops cycling when metrics plateau.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RefinementCycle:
    """Record of a single refinement cycle."""
    cycle_number: int
    started_at: str
    completed_at: Optional[str] = None
    agreement_rate_before: float = 0.0
    agreement_rate_after: Optional[float] = None
    improvement: Optional[float] = None
    patterns_found: int = 0
    suggestions_generated: int = 0
    rules_applied: int = 0
    reannotation_count: int = 0
    prompt_version_before: int = 0
    prompt_version_after: Optional[int] = None
    status: str = "running"  # running, completed, no_improvement, failed

    def to_dict(self) -> Dict[str, Any]:
        return {
            'cycle_number': self.cycle_number,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'agreement_rate_before': self.agreement_rate_before,
            'agreement_rate_after': self.agreement_rate_after,
            'improvement': self.improvement,
            'patterns_found': self.patterns_found,
            'suggestions_generated': self.suggestions_generated,
            'rules_applied': self.rules_applied,
            'reannotation_count': self.reannotation_count,
            'prompt_version_before': self.prompt_version_before,
            'prompt_version_after': self.prompt_version_after,
            'status': self.status,
        }


class RefinementLoop:
    """Orchestrates iterative confusion analysis → prompt revision cycles.

    The loop monitors annotation progress and periodically:
    1. Analyzes confusion patterns from human-LLM disagreements
    2. Generates guideline suggestions for top confusion patterns
    3. Injects suggestions into the prompt (if auto_apply or human-approved)
    4. Triggers re-annotation of low-confidence instances
    5. Measures improvement and decides whether to continue

    The loop stops when:
    - Agreement rate meets the target threshold
    - Improvement plateaus (patience exceeded)
    - Maximum cycles reached
    """

    def __init__(self, solo_config: Any, app_config: Dict[str, Any]):
        self.solo_config = solo_config
        self.app_config = app_config
        self.rl_config = solo_config.refinement_loop

        # Cycle tracking
        self._cycles: List[RefinementCycle] = []
        self._annotations_since_last_check: int = 0
        self._consecutive_no_improvement: int = 0
        self._stopped: bool = False
        self._stop_reason: Optional[str] = None
        self._running: bool = False
        self._lock = threading.Lock()

    @property
    def cycle_count(self) -> int:
        return len(self._cycles)

    @property
    def is_stopped(self) -> bool:
        return self._stopped

    @property
    def stop_reason(self) -> Optional[str]:
        return self._stop_reason

    def record_annotation(self) -> bool:
        """Record that a human annotation was made.

        Returns:
            True if a refinement cycle should be triggered.
        """
        if not self.rl_config.enabled or self._stopped:
            return False

        with self._lock:
            self._annotations_since_last_check += 1
            return self._annotations_since_last_check >= self.rl_config.trigger_interval

    def should_trigger(self) -> bool:
        """Check if conditions are met to trigger a refinement cycle."""
        if not self.rl_config.enabled or self._stopped or self._running:
            return False

        with self._lock:
            return self._annotations_since_last_check >= self.rl_config.trigger_interval

    def run_cycle(
        self,
        agreement_rate: float,
        prompt_version: int,
        confusion_patterns: List[Any],
        apply_suggestions_fn: Callable[[List[str]], Dict[str, Any]],
        generate_suggestion_fn: Callable[[Any, str], Optional[str]],
        current_prompt: str,
    ) -> RefinementCycle:
        """Execute one refinement cycle.

        Args:
            agreement_rate: Current agreement rate before the cycle.
            prompt_version: Current prompt version number.
            confusion_patterns: List of ConfusionPattern objects from analyzer.
            apply_suggestions_fn: Callable that takes a list of suggestion strings
                and applies them to the prompt. Returns dict with results.
            generate_suggestion_fn: Callable(pattern, current_prompt) -> suggestion.
            current_prompt: The current annotation prompt text.

        Returns:
            RefinementCycle record with results.
        """
        with self._lock:
            if self._running:
                raise RuntimeError("Refinement cycle already running")
            self._running = True
            self._annotations_since_last_check = 0

        cycle = RefinementCycle(
            cycle_number=self.cycle_count + 1,
            started_at=datetime.now().isoformat(),
            agreement_rate_before=agreement_rate,
            prompt_version_before=prompt_version,
            patterns_found=len(confusion_patterns),
        )

        try:
            # Check if max cycles exceeded
            if self.cycle_count >= self.rl_config.max_cycles:
                cycle.status = "max_cycles_reached"
                self._stop("Max refinement cycles reached")
                self._finalize_cycle(cycle)
                return cycle

            # Generate suggestions for top patterns
            suggestions = []
            for pattern in confusion_patterns:
                suggestion = generate_suggestion_fn(pattern, current_prompt)
                if suggestion:
                    suggestions.append(suggestion)

            cycle.suggestions_generated = len(suggestions)

            if not suggestions:
                cycle.status = "no_suggestions"
                self._finalize_cycle(cycle)
                return cycle

            # Apply suggestions
            if self.rl_config.auto_apply_suggestions:
                result = apply_suggestions_fn(suggestions)
                cycle.rules_applied = result.get('categories_incorporated', 0)
                cycle.reannotation_count = result.get('reannotation_count', 0)
                cycle.prompt_version_after = result.get('new_prompt_version')
                cycle.status = "completed"
            else:
                # Suggestions generated but await human approval
                cycle.status = "awaiting_approval"

            self._finalize_cycle(cycle)
            return cycle

        except Exception as e:
            logger.error(f"Refinement cycle {cycle.cycle_number} failed: {e}")
            cycle.status = "failed"
            self._finalize_cycle(cycle)
            return cycle

    def record_post_cycle_metrics(self, agreement_rate_after: float) -> None:
        """Record the agreement rate after a cycle completes and re-annotation settles.

        This should be called after enough new annotations have been collected
        to measure the effect of the refinement.

        Args:
            agreement_rate_after: Agreement rate measured after the cycle.
        """
        with self._lock:
            if not self._cycles:
                return

            last_cycle = self._cycles[-1]
            if last_cycle.agreement_rate_after is not None:
                return  # Already recorded

            last_cycle.agreement_rate_after = agreement_rate_after
            improvement = agreement_rate_after - last_cycle.agreement_rate_before
            last_cycle.improvement = round(improvement, 4)

            if improvement < self.rl_config.min_improvement:
                self._consecutive_no_improvement += 1
                logger.info(
                    f"Refinement cycle {last_cycle.cycle_number}: "
                    f"no significant improvement ({improvement:+.4f}), "
                    f"patience {self._consecutive_no_improvement}/{self.rl_config.patience}"
                )
                if self._consecutive_no_improvement >= self.rl_config.patience:
                    self._stop("Improvement plateaued")
            else:
                self._consecutive_no_improvement = 0
                logger.info(
                    f"Refinement cycle {last_cycle.cycle_number}: "
                    f"improvement {improvement:+.4f}"
                )

    def _finalize_cycle(self, cycle: RefinementCycle) -> None:
        """Finalize a cycle and store it."""
        cycle.completed_at = datetime.now().isoformat()
        with self._lock:
            self._cycles.append(cycle)
            self._running = False

    def _stop(self, reason: str) -> None:
        """Stop the refinement loop."""
        self._stopped = True
        self._stop_reason = reason
        logger.info(f"Refinement loop stopped: {reason}")

    def reset(self) -> None:
        """Reset the refinement loop state, allowing new cycles."""
        with self._lock:
            self._consecutive_no_improvement = 0
            self._stopped = False
            self._stop_reason = None
            self._annotations_since_last_check = 0

    def get_status(self) -> Dict[str, Any]:
        """Get the current refinement loop status."""
        with self._lock:
            last_cycle = self._cycles[-1].to_dict() if self._cycles else None
            last_improvement = None
            if self._cycles and self._cycles[-1].improvement is not None:
                last_improvement = self._cycles[-1].improvement

            return {
                'enabled': self.rl_config.enabled,
                'total_cycles': len(self._cycles),
                'is_running': self._running,
                'is_stopped': self._stopped,
                'stop_reason': self._stop_reason,
                'consecutive_no_improvement': self._consecutive_no_improvement,
                'patience': self.rl_config.patience,
                'max_cycles': self.rl_config.max_cycles,
                'trigger_interval': self.rl_config.trigger_interval,
                'annotations_until_next': max(
                    0,
                    self.rl_config.trigger_interval - self._annotations_since_last_check
                ),
                'last_cycle': last_cycle,
                'last_improvement': last_improvement,
                'cycles': [c.to_dict() for c in self._cycles],
            }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state for persistence."""
        return {
            'cycles': [c.to_dict() for c in self._cycles],
            'annotations_since_last_check': self._annotations_since_last_check,
            'consecutive_no_improvement': self._consecutive_no_improvement,
            'stopped': self._stopped,
            'stop_reason': self._stop_reason,
        }

    def load_state(self, data: Dict[str, Any]) -> None:
        """Restore state from persistence."""
        with self._lock:
            self._annotations_since_last_check = data.get(
                'annotations_since_last_check', 0
            )
            self._consecutive_no_improvement = data.get(
                'consecutive_no_improvement', 0
            )
            self._stopped = data.get('stopped', False)
            self._stop_reason = data.get('stop_reason')

            self._cycles = []
            for cd in data.get('cycles', []):
                self._cycles.append(RefinementCycle(
                    cycle_number=cd.get('cycle_number', 0),
                    started_at=cd.get('started_at', ''),
                    completed_at=cd.get('completed_at'),
                    agreement_rate_before=cd.get('agreement_rate_before', 0.0),
                    agreement_rate_after=cd.get('agreement_rate_after'),
                    improvement=cd.get('improvement'),
                    patterns_found=cd.get('patterns_found', 0),
                    suggestions_generated=cd.get('suggestions_generated', 0),
                    rules_applied=cd.get('rules_applied', 0),
                    reannotation_count=cd.get('reannotation_count', 0),
                    prompt_version_before=cd.get('prompt_version_before', 0),
                    prompt_version_after=cd.get('prompt_version_after'),
                    status=cd.get('status', 'completed'),
                ))

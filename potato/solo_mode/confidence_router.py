"""
Confidence Router for Solo Mode

Implements cascaded confidence escalation: cheap model -> expensive model -> human.
Each tier has a confidence threshold; if the LLM's confidence is below the threshold,
the instance escalates to the next tier. If all tiers are exhausted, the instance
is routed to a human annotator.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TierStats:
    """Per-tier statistics for confidence routing."""
    name: str = ""
    instances_attempted: int = 0
    instances_accepted: int = 0
    instances_escalated: int = 0
    instances_errored: int = 0
    total_confidence: float = 0.0
    total_latency_ms: float = 0.0

    @property
    def avg_confidence(self) -> float:
        if self.instances_accepted == 0:
            return 0.0
        return self.total_confidence / self.instances_accepted

    @property
    def acceptance_rate(self) -> float:
        if self.instances_attempted == 0:
            return 0.0
        return self.instances_accepted / self.instances_attempted

    @property
    def avg_latency_ms(self) -> float:
        if self.instances_attempted == 0:
            return 0.0
        return self.total_latency_ms / self.instances_attempted

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'instances_attempted': self.instances_attempted,
            'instances_accepted': self.instances_accepted,
            'instances_escalated': self.instances_escalated,
            'instances_errored': self.instances_errored,
            'avg_confidence': round(self.avg_confidence, 4),
            'acceptance_rate': round(self.acceptance_rate, 4),
            'avg_latency_ms': round(self.avg_latency_ms, 1),
        }


@dataclass
class RoutingResult:
    """Result of routing an instance through the confidence cascade."""
    instance_id: str
    accepted: bool = False
    routed_to_human: bool = False
    tier_index: int = -1
    tier_name: str = ""
    labeling_result: Any = None  # Optional[LabelingResult]
    attempts: List[Dict[str, Any]] = field(default_factory=list)


class ConfidenceRouter:
    """
    Cascaded confidence escalation router.

    Routes instances through tiers of LLM models with decreasing
    confidence thresholds. If no tier accepts the instance, it is
    routed to a human annotator.
    """

    def __init__(
        self,
        routing_config,
        label_fn: Callable,
        endpoint_factory: Callable,
    ):
        """
        Initialize the confidence router.

        Args:
            routing_config: ConfidenceRoutingConfig instance
            label_fn: Function with signature (instance_id, text, schema_name, endpoint) -> LabelingResult
            endpoint_factory: Function with signature (ModelConfig) -> endpoint
        """
        self._config = routing_config
        self._label_fn = label_fn
        self._endpoint_factory = endpoint_factory
        self._lock = threading.Lock()

        # Per-tier stats
        self._tier_stats: List[TierStats] = [
            TierStats(name=tier.name or f"tier_{i}")
            for i, tier in enumerate(routing_config.tiers)
        ]

        # Lazy endpoint cache per tier
        self._endpoints: List[Optional[Any]] = [None] * len(routing_config.tiers)

        # Global counters
        self._human_routed_count = 0
        self._total_routed = 0

    def _get_tier_endpoint(self, tier_index: int):
        """Get or create the endpoint for a tier."""
        if self._endpoints[tier_index] is not None:
            return self._endpoints[tier_index]

        tier = self._config.tiers[tier_index]
        try:
            endpoint = self._endpoint_factory(tier.model)
            self._endpoints[tier_index] = endpoint
            return endpoint
        except Exception as e:
            logger.warning(
                f"Failed to create endpoint for tier {tier_index} "
                f"({tier.name}): {e}"
            )
            return None

    def route_instance(
        self,
        instance_id: str,
        text: str,
        schema_name: str,
    ) -> RoutingResult:
        """
        Route an instance through the confidence cascade.

        For each tier:
        1. Get/create the endpoint
        2. Call label_fn with the endpoint
        3. Check confidence vs threshold
        4. If confidence >= threshold -> accept
        5. If confidence < threshold -> escalate
        6. If error -> skip tier
        7. If all tiers exhausted -> route to human
        """
        result = RoutingResult(instance_id=instance_id)

        for i, tier in enumerate(self._config.tiers):
            endpoint = self._get_tier_endpoint(i)
            if endpoint is None:
                attempt = {
                    'tier_index': i,
                    'tier_name': tier.name,
                    'error': 'Failed to create endpoint',
                }
                result.attempts.append(attempt)
                with self._lock:
                    self._tier_stats[i].instances_attempted += 1
                    self._tier_stats[i].instances_errored += 1
                continue

            start_ms = time.monotonic() * 1000
            try:
                labeling_result = self._label_fn(
                    instance_id, text, schema_name, endpoint
                )
            except Exception as e:
                elapsed_ms = time.monotonic() * 1000 - start_ms
                attempt = {
                    'tier_index': i,
                    'tier_name': tier.name,
                    'error': str(e),
                    'latency_ms': round(elapsed_ms, 1),
                }
                result.attempts.append(attempt)
                with self._lock:
                    self._tier_stats[i].instances_attempted += 1
                    self._tier_stats[i].instances_errored += 1
                    self._tier_stats[i].total_latency_ms += elapsed_ms
                continue

            elapsed_ms = time.monotonic() * 1000 - start_ms

            if labeling_result is None or labeling_result.error:
                error_msg = (
                    labeling_result.error if labeling_result else 'No result'
                )
                attempt = {
                    'tier_index': i,
                    'tier_name': tier.name,
                    'error': error_msg,
                    'latency_ms': round(elapsed_ms, 1),
                }
                result.attempts.append(attempt)
                with self._lock:
                    self._tier_stats[i].instances_attempted += 1
                    self._tier_stats[i].instances_errored += 1
                    self._tier_stats[i].total_latency_ms += elapsed_ms
                continue

            confidence = labeling_result.confidence
            attempt = {
                'tier_index': i,
                'tier_name': tier.name,
                'confidence': confidence,
                'threshold': tier.confidence_threshold,
                'latency_ms': round(elapsed_ms, 1),
            }

            if confidence >= tier.confidence_threshold:
                # Accepted at this tier
                attempt['accepted'] = True
                result.attempts.append(attempt)
                result.accepted = True
                result.tier_index = i
                result.tier_name = tier.name
                result.labeling_result = labeling_result

                with self._lock:
                    self._tier_stats[i].instances_attempted += 1
                    self._tier_stats[i].instances_accepted += 1
                    self._tier_stats[i].total_confidence += confidence
                    self._tier_stats[i].total_latency_ms += elapsed_ms
                    self._total_routed += 1
                return result
            else:
                # Escalate to next tier
                attempt['accepted'] = False
                result.attempts.append(attempt)
                # Keep the best result so far in case all tiers fail
                if (
                    result.labeling_result is None
                    or confidence > result.labeling_result.confidence
                ):
                    result.labeling_result = labeling_result
                    result.tier_index = i
                    result.tier_name = tier.name

                with self._lock:
                    self._tier_stats[i].instances_attempted += 1
                    self._tier_stats[i].instances_escalated += 1
                    self._tier_stats[i].total_latency_ms += elapsed_ms

        # All tiers exhausted -> route to human
        result.routed_to_human = True
        result.accepted = False
        with self._lock:
            self._human_routed_count += 1
            self._total_routed += 1

        return result

    def get_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        with self._lock:
            return {
                'enabled': True,
                'num_tiers': len(self._config.tiers),
                'tiers': [s.to_dict() for s in self._tier_stats],
                'human_routed_count': self._human_routed_count,
                'total_routed': self._total_routed,
            }

    def reset_stats(self) -> None:
        """Reset all statistics counters."""
        with self._lock:
            for stats in self._tier_stats:
                stats.instances_attempted = 0
                stats.instances_accepted = 0
                stats.instances_escalated = 0
                stats.instances_errored = 0
                stats.total_confidence = 0.0
                stats.total_latency_ms = 0.0
            self._human_routed_count = 0
            self._total_routed = 0

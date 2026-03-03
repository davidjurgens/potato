"""
Disagreement Explorer

Provides rich aggregated data for visual exploration of human-LLM
disagreements, including:
- Scatter plot data: instances by confidence vs. agreement
- Timeline: disagreement rate over annotation windows
- Per-label breakdown: which labels cause most disagreements
- Filterable disagreement list with text, labels, and reasoning
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ScatterPoint:
    """A single point in the confidence-vs-agreement scatter plot."""
    instance_id: str
    confidence: float
    agrees: bool
    llm_label: str
    human_label: Optional[str] = None
    reasoning: str = ""
    text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'instance_id': self.instance_id,
            'confidence': self.confidence,
            'agrees': self.agrees,
            'llm_label': self.llm_label,
            'human_label': self.human_label,
            'reasoning': self.reasoning,
            'text': self.text,
        }


@dataclass
class TimelineBucket:
    """A time bucket for the disagreement timeline."""
    bucket_index: int
    start_index: int
    end_index: int
    total: int
    agreements: int
    disagreements: int
    agreement_rate: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'bucket_index': self.bucket_index,
            'start_index': self.start_index,
            'end_index': self.end_index,
            'total': self.total,
            'agreements': self.agreements,
            'disagreements': self.disagreements,
            'agreement_rate': self.agreement_rate,
        }


@dataclass
class LabelBreakdown:
    """Per-label disagreement statistics."""
    label: str
    total_comparisons: int
    agreements: int
    disagreements: int
    agreement_rate: float
    confused_with: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'label': self.label,
            'total_comparisons': self.total_comparisons,
            'agreements': self.agreements,
            'disagreements': self.disagreements,
            'agreement_rate': self.agreement_rate,
            'confused_with': self.confused_with,
        }


@dataclass
class DisagreementItem:
    """A single disagreement for the filterable list."""
    instance_id: str
    llm_label: str
    human_label: str
    confidence: float
    reasoning: str
    text: str
    timestamp: str = ""
    resolved: bool = False
    resolution_label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'instance_id': self.instance_id,
            'llm_label': self.llm_label,
            'human_label': self.human_label,
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'text': self.text,
            'timestamp': self.timestamp,
            'resolved': self.resolved,
            'resolution_label': self.resolution_label,
        }


class DisagreementExplorer:
    """Computes aggregated data for disagreement visualization.

    Takes prediction data and comparison history to produce
    scatter plots, timelines, label breakdowns, and disagreement lists.
    """

    def __init__(self, app_config: Dict[str, Any], solo_config=None):
        self._app_config = app_config
        self._solo_config = solo_config

    def get_explorer_data(
        self,
        predictions: Dict[str, Dict[str, Any]],
        comparison_history: List[Dict[str, Any]],
        text_getter: Optional[Callable[[str], Optional[str]]] = None,
        label_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compute the full disagreement explorer dataset.

        Args:
            predictions: Dict[instance_id][schema_name] -> LLMPrediction
            comparison_history: List of comparison dicts from ValidationTracker
            text_getter: Optional callable to get instance text by ID
            label_filter: Optional label to filter results by

        Returns:
            Dict with scatter_points, disagreements, label_breakdown, summary.
        """
        scatter_points = self._build_scatter_points(
            predictions, text_getter, label_filter
        )
        disagreements = self._build_disagreement_list(
            predictions, comparison_history, text_getter, label_filter
        )
        label_breakdown = self._build_label_breakdown(
            comparison_history, label_filter
        )

        # Summary stats
        total_compared = len(comparison_history)
        total_disagreements = sum(
            1 for c in comparison_history if not c.get('agrees')
        )
        disagreement_rate = (
            total_disagreements / total_compared if total_compared > 0 else 0.0
        )

        # Confidence distribution for disagreements
        disagree_confs = [
            p.confidence for p in scatter_points if not p.agrees
        ]
        avg_disagree_conf = (
            sum(disagree_confs) / len(disagree_confs)
            if disagree_confs else 0.0
        )

        return {
            'scatter_points': [p.to_dict() for p in scatter_points],
            'disagreements': [d.to_dict() for d in disagreements],
            'label_breakdown': [b.to_dict() for b in label_breakdown],
            'summary': {
                'total_compared': total_compared,
                'total_disagreements': total_disagreements,
                'disagreement_rate': round(disagreement_rate, 4),
                'avg_disagreement_confidence': round(avg_disagree_conf, 4),
                'labels_with_disagreements': len([
                    b for b in label_breakdown if b.disagreements > 0
                ]),
            },
        }

    def get_timeline(
        self,
        comparison_history: List[Dict[str, Any]],
        bucket_size: int = 10,
    ) -> Dict[str, Any]:
        """Compute temporal disagreement trends.

        Args:
            comparison_history: List of comparison dicts (ordered by time)
            bucket_size: Number of comparisons per bucket

        Returns:
            Dict with buckets (list of TimelineBucket) and overall trend.
        """
        if not comparison_history:
            return {'buckets': [], 'trend': 'stable', 'total': 0}

        buckets = []
        for i in range(0, len(comparison_history), bucket_size):
            chunk = comparison_history[i:i + bucket_size]
            agreements = sum(1 for c in chunk if c.get('agrees'))
            disagreements = len(chunk) - agreements
            rate = agreements / len(chunk) if chunk else 0.0

            buckets.append(TimelineBucket(
                bucket_index=len(buckets),
                start_index=i,
                end_index=i + len(chunk) - 1,
                total=len(chunk),
                agreements=agreements,
                disagreements=disagreements,
                agreement_rate=round(rate, 4),
            ))

        # Compute trend from first half vs second half
        trend = 'stable'
        if len(buckets) >= 4:
            mid = len(buckets) // 2
            first_half = buckets[:mid]
            second_half = buckets[mid:]

            first_rate = (
                sum(b.agreements for b in first_half)
                / max(sum(b.total for b in first_half), 1)
            )
            second_rate = (
                sum(b.agreements for b in second_half)
                / max(sum(b.total for b in second_half), 1)
            )

            diff = second_rate - first_rate
            if diff > 0.05:
                trend = 'improving'
            elif diff < -0.05:
                trend = 'declining'

        return {
            'buckets': [b.to_dict() for b in buckets],
            'trend': trend,
            'total': len(comparison_history),
            'bucket_size': bucket_size,
        }

    def _build_scatter_points(
        self,
        predictions: Dict[str, Dict[str, Any]],
        text_getter: Optional[Callable] = None,
        label_filter: Optional[str] = None,
    ) -> List[ScatterPoint]:
        """Build scatter plot data from predictions with human comparison."""
        points = []

        for instance_id, schemas in predictions.items():
            for schema_name, pred in schemas.items():
                # Only include predictions that have been compared
                if pred.agrees_with_human is None:
                    continue

                llm_label = str(pred.predicted_label)
                human_label = (
                    str(pred.human_label) if pred.human_label is not None
                    else None
                )

                # Apply label filter
                if label_filter:
                    if llm_label != label_filter and human_label != label_filter:
                        continue

                text = ''
                if text_getter:
                    text = text_getter(instance_id) or ''
                    if len(text) > 200:
                        text = text[:200] + '...'

                points.append(ScatterPoint(
                    instance_id=instance_id,
                    confidence=pred.confidence_score,
                    agrees=pred.agrees_with_human,
                    llm_label=llm_label,
                    human_label=human_label,
                    reasoning=pred.reasoning[:300] if pred.reasoning else '',
                    text=text,
                ))

        # Sort by confidence
        points.sort(key=lambda p: p.confidence)
        return points

    def _build_disagreement_list(
        self,
        predictions: Dict[str, Dict[str, Any]],
        comparison_history: List[Dict[str, Any]],
        text_getter: Optional[Callable] = None,
        label_filter: Optional[str] = None,
    ) -> List[DisagreementItem]:
        """Build filterable list of disagreements."""
        # Build a lookup from comparison history for timestamps
        timestamps: Dict[str, str] = {}
        for c in comparison_history:
            if not c.get('agrees'):
                timestamps[c['instance_id']] = c.get('timestamp', '')

        items = []
        for instance_id, schemas in predictions.items():
            for schema_name, pred in schemas.items():
                if pred.agrees_with_human is not False:
                    continue

                llm_label = str(pred.predicted_label)
                human_label = (
                    str(pred.human_label) if pred.human_label is not None
                    else ''
                )

                if label_filter:
                    if llm_label != label_filter and human_label != label_filter:
                        continue

                text = ''
                if text_getter:
                    text = text_getter(instance_id) or ''
                    if len(text) > 300:
                        text = text[:300] + '...'

                items.append(DisagreementItem(
                    instance_id=instance_id,
                    llm_label=llm_label,
                    human_label=human_label,
                    confidence=pred.confidence_score,
                    reasoning=pred.reasoning[:500] if pred.reasoning else '',
                    text=text,
                    timestamp=timestamps.get(instance_id, ''),
                    resolved=pred.disagreement_resolved,
                    resolution_label=(
                        str(pred.resolution_label)
                        if pred.resolution_label is not None else None
                    ),
                ))

        # Sort by confidence ascending (most surprising first)
        items.sort(key=lambda x: x.confidence, reverse=True)
        return items

    def _build_label_breakdown(
        self,
        comparison_history: List[Dict[str, Any]],
        label_filter: Optional[str] = None,
    ) -> List[LabelBreakdown]:
        """Build per-label disagreement statistics."""
        # Aggregate by human label (ground truth)
        label_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {'total': 0, 'agreements': 0, 'disagreements': 0}
        )
        confusion: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

        for c in comparison_history:
            human_label = str(c.get('human_label', ''))
            llm_label = str(c.get('llm_label', ''))
            agrees = c.get('agrees', False)

            if label_filter and human_label != label_filter and llm_label != label_filter:
                continue

            label_stats[human_label]['total'] += 1
            if agrees:
                label_stats[human_label]['agreements'] += 1
            else:
                label_stats[human_label]['disagreements'] += 1
                confusion[human_label][llm_label] += 1

        breakdowns = []
        for label, stats in sorted(
            label_stats.items(),
            key=lambda x: x[1]['disagreements'],
            reverse=True,
        ):
            rate = (
                stats['agreements'] / stats['total']
                if stats['total'] > 0 else 0.0
            )

            # Top confused-with labels
            confused_with = [
                {'label': confused_label, 'count': count}
                for confused_label, count in sorted(
                    confusion[label].items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:5]
            ]

            breakdowns.append(LabelBreakdown(
                label=label,
                total_comparisons=stats['total'],
                agreements=stats['agreements'],
                disagreements=stats['disagreements'],
                agreement_rate=round(rate, 4),
                confused_with=confused_with,
            ))

        return breakdowns

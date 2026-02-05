"""
Adjudication Module

This module provides a comprehensive adjudication system where designated users
review items with multiple annotations, resolve disagreements, and produce
gold-standard final decisions.

Adjudication is NOT a phase — it's a parallel workflow accessible via a dedicated
/adjudicate route, available to users with adjudicator privileges. This avoids
disrupting the existing phase progression system.

Key Components:
- AdjudicationConfig: Configuration dataclass for adjudication settings
- AdjudicationItem: Represents an item eligible for adjudication with all annotations
- AdjudicationDecision: Represents an adjudicator's final decision on an item
- AdjudicationManager: Singleton manager for the adjudication workflow

The workflow:
1. Annotators complete annotations via /annotate (existing workflow)
2. AdjudicationManager monitors annotation counts and agreement
3. Items are flagged when criteria are met (min annotations, low agreement)
4. Adjudicators review items via /adjudicate and submit decisions
5. Final dataset CLI merges unanimous + adjudicated decisions
"""

import json
import logging
import math
import os
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Set

logger = logging.getLogger(__name__)

# Singleton instance
_ADJUDICATION_MANAGER = None
_ADJUDICATION_LOCK = threading.Lock()


@dataclass
class AdjudicationConfig:
    """Configuration for adjudication features."""
    enabled: bool = False
    adjudicator_users: List[str] = field(default_factory=list)

    # Trigger criteria
    min_annotations: int = 2
    require_fully_annotated: bool = False
    agreement_threshold: float = 0.75
    show_all_items: bool = False

    # Display options
    show_annotator_names: bool = True
    show_timing_data: bool = True
    show_agreement_scores: bool = True
    fast_decision_warning_ms: int = 2000

    # Adjudicator metadata fields
    require_confidence: bool = True
    require_notes_on_override: bool = False
    error_taxonomy: List[str] = field(default_factory=lambda: [
        "ambiguous_text", "guideline_gap", "annotator_error",
        "edge_case", "subjective_disagreement", "other"
    ])

    # Similarity (Phase 3, optional)
    similarity_enabled: bool = False
    similarity_model: str = "all-MiniLM-L6-v2"
    similarity_top_k: int = 5
    similarity_precompute: bool = True

    # Output
    output_subdir: str = "adjudication"


@dataclass
class AdjudicationItem:
    """Represents an item eligible for adjudication with all annotator data."""
    instance_id: str
    annotations: Dict[str, Dict[str, Any]]  # user_id -> {schema: {label: value}}
    span_annotations: Dict[str, List[Dict]]  # user_id -> [span_dict, ...]
    behavioral_data: Dict[str, Dict]  # user_id -> {total_time_ms, ...}
    agreement_scores: Dict[str, float]  # schema_name -> agreement score
    overall_agreement: float
    num_annotators: int
    status: str = "pending"  # pending, in_progress, completed, skipped
    assigned_adjudicator: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return {
            "instance_id": self.instance_id,
            "annotations": self.annotations,
            "span_annotations": self.span_annotations,
            "behavioral_data": self.behavioral_data,
            "agreement_scores": self.agreement_scores,
            "overall_agreement": self.overall_agreement,
            "num_annotators": self.num_annotators,
            "status": self.status,
            "assigned_adjudicator": self.assigned_adjudicator,
        }


@dataclass
class AdjudicationDecision:
    """Represents an adjudicator's final decision on an item."""
    instance_id: str
    adjudicator_id: str
    timestamp: str  # ISO format string
    label_decisions: Dict[str, Any]  # schema -> value
    span_decisions: List[Dict]  # list of span dicts
    source: Dict[str, str]  # schema -> "annotator_X" | "adjudicator" | "merged"
    confidence: str  # "high", "medium", "low"
    notes: str
    error_taxonomy: List[str]
    guideline_update_flag: bool = False
    guideline_update_notes: str = ""
    time_spent_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return {
            "instance_id": self.instance_id,
            "adjudicator_id": self.adjudicator_id,
            "timestamp": self.timestamp,
            "label_decisions": self.label_decisions,
            "span_decisions": self.span_decisions,
            "source": self.source,
            "confidence": self.confidence,
            "notes": self.notes,
            "error_taxonomy": self.error_taxonomy,
            "guideline_update_flag": self.guideline_update_flag,
            "guideline_update_notes": self.guideline_update_notes,
            "time_spent_ms": self.time_spent_ms,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AdjudicationDecision":
        """Deserialize from dictionary."""
        return cls(
            instance_id=d["instance_id"],
            adjudicator_id=d["adjudicator_id"],
            timestamp=d["timestamp"],
            label_decisions=d.get("label_decisions", {}),
            span_decisions=d.get("span_decisions", []),
            source=d.get("source", {}),
            confidence=d.get("confidence", "medium"),
            notes=d.get("notes", ""),
            error_taxonomy=d.get("error_taxonomy", []),
            guideline_update_flag=d.get("guideline_update_flag", False),
            guideline_update_notes=d.get("guideline_update_notes", ""),
            time_spent_ms=d.get("time_spent_ms", 0),
        )


class AdjudicationManager:
    """
    Manages the adjudication workflow including queue building, agreement
    computation, decision storage, and final dataset generation.

    Follows the singleton pattern used by QualityControlManager.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the adjudication manager.

        Args:
            config: The full application configuration dictionary
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._lock = threading.RLock()

        # Parse configuration
        self.adj_config = self._parse_config(config)

        # Queue and decisions
        self.queue: Dict[str, AdjudicationItem] = {}  # instance_id -> AdjudicationItem
        self.decisions: Dict[str, AdjudicationDecision] = {}  # instance_id -> decision
        self._queue_built = False

        # Load any previously saved decisions
        self._load_decisions()

        # Initialize similarity engine (Phase 3)
        self.similarity_engine = None
        if self.adj_config.similarity_enabled:
            from potato.similarity import init_similarity_engine
            self.similarity_engine = init_similarity_engine(config, self.adj_config)
            if (self.similarity_engine and self.similarity_engine.enabled
                    and self.adj_config.similarity_precompute):
                self._precompute_similarities()

        self.logger.info(
            f"AdjudicationManager initialized: enabled={self.adj_config.enabled}, "
            f"adjudicators={self.adj_config.adjudicator_users}"
        )

    def _parse_config(self, config: Dict[str, Any]) -> AdjudicationConfig:
        """Parse adjudication configuration from the main config."""
        adj = AdjudicationConfig()

        adj_config = config.get("adjudication", {})
        if not adj_config or not adj_config.get("enabled", False):
            return adj

        adj.enabled = True
        adj.adjudicator_users = adj_config.get("adjudicator_users", [])
        adj.min_annotations = adj_config.get("min_annotations", 2)
        adj.require_fully_annotated = adj_config.get("require_fully_annotated", False)
        adj.agreement_threshold = adj_config.get("agreement_threshold", 0.75)
        adj.show_all_items = adj_config.get("show_all_items", False)
        adj.show_annotator_names = adj_config.get("show_annotator_names", True)
        adj.show_timing_data = adj_config.get("show_timing_data", True)
        adj.show_agreement_scores = adj_config.get("show_agreement_scores", True)
        adj.fast_decision_warning_ms = adj_config.get("fast_decision_warning_ms", 2000)
        adj.require_confidence = adj_config.get("require_confidence", True)
        adj.require_notes_on_override = adj_config.get("require_notes_on_override", False)

        if "error_taxonomy" in adj_config:
            adj.error_taxonomy = adj_config["error_taxonomy"]

        # Similarity settings
        sim_config = adj_config.get("similarity", {})
        if sim_config.get("enabled", False):
            adj.similarity_enabled = True
            adj.similarity_model = sim_config.get("model", "all-MiniLM-L6-v2")
            adj.similarity_top_k = sim_config.get("top_k", 5)
            adj.similarity_precompute = sim_config.get("precompute_on_start", True)

        adj.output_subdir = adj_config.get("output_subdir", "adjudication")

        return adj

    def is_adjudicator(self, username: str) -> bool:
        """Check if a user is an authorized adjudicator."""
        if not self.adj_config.enabled:
            return False
        return username in self.adj_config.adjudicator_users

    def build_queue(self) -> List[AdjudicationItem]:
        """
        Scan all user annotations and build the adjudication queue.

        Items become eligible when they have enough annotations and
        agreement is below the threshold.

        Returns:
            List of AdjudicationItem objects
        """
        from potato.user_state_management import get_user_state_manager
        from potato.item_state_management import get_item_state_manager

        with self._lock:
            usm = get_user_state_manager()
            ism = get_item_state_manager()

            # Get all annotation schemes from config
            annotation_schemes = self.config.get("annotation_schemes", [])
            scheme_names = [s.get("name", "") for s in annotation_schemes]

            # Iterate over all items
            for instance_id, item in ism.instance_id_to_instance.items():
                instance_id_str = str(instance_id)

                # Skip if already decided
                if instance_id_str in self.decisions:
                    if instance_id_str not in self.queue:
                        continue
                    # Mark as completed if decision exists
                    self.queue[instance_id_str].status = "completed"
                    continue

                # Get all annotators for this item
                annotators = ism.instance_annotators.get(instance_id, set())
                # Filter out adjudicators from annotator list
                annotators = {
                    u for u in annotators
                    if u not in self.adj_config.adjudicator_users
                }

                if len(annotators) < self.adj_config.min_annotations:
                    continue

                # Check if we require fully annotated items
                if self.adj_config.require_fully_annotated:
                    max_per_item = ism.max_annotations_per_item
                    if max_per_item > 0 and len(annotators) < max_per_item:
                        continue

                # Collect annotations from all annotators
                item_annotations = {}
                item_spans = {}
                item_behavioral = {}

                for user_id in annotators:
                    user_state = usm.get_user_state(user_id)
                    if not user_state:
                        continue

                    # Get label annotations
                    label_annots = user_state.instance_id_to_label_to_value.get(
                        instance_id_str, {}
                    )
                    if label_annots:
                        item_annotations[user_id] = self._serialize_labels(label_annots)

                    # Get span annotations
                    span_annots = user_state.instance_id_to_span_to_value.get(
                        instance_id_str, {}
                    )
                    if span_annots:
                        item_spans[user_id] = self._serialize_spans(span_annots)

                    # Get behavioral data
                    bd = user_state.instance_id_to_behavioral_data.get(
                        instance_id_str, {}
                    )
                    if bd:
                        item_behavioral[user_id] = self._serialize_behavioral(bd)

                if not item_annotations and not item_spans:
                    continue

                # Compute agreement scores
                agreement_scores = self._compute_agreement(
                    item_annotations, scheme_names
                )
                overall = self._compute_overall_agreement(agreement_scores)

                # Filter by agreement threshold
                if not self.adj_config.show_all_items:
                    if overall >= self.adj_config.agreement_threshold:
                        continue

                # Preserve existing status if already in queue
                existing = self.queue.get(instance_id_str)
                status = existing.status if existing else "pending"
                assigned = existing.assigned_adjudicator if existing else None

                self.queue[instance_id_str] = AdjudicationItem(
                    instance_id=instance_id_str,
                    annotations=item_annotations,
                    span_annotations=item_spans,
                    behavioral_data=item_behavioral,
                    agreement_scores=agreement_scores,
                    overall_agreement=overall,
                    num_annotators=len(annotators),
                    status=status,
                    assigned_adjudicator=assigned,
                )

            self._queue_built = True
            return list(self.queue.values())

    def _serialize_labels(self, label_data: Dict) -> Dict[str, Any]:
        """Convert label annotation data to serializable dict."""
        result = {}
        for key, value in label_data.items():
            # Key might be a Label object or a string
            if hasattr(key, 'get_schema'):
                schema = key.get_schema()
                name = key.get_name()
                if schema not in result:
                    result[schema] = {}
                result[schema][name] = value
            elif isinstance(key, str):
                result[key] = value
            else:
                result[str(key)] = value
        return result

    def _serialize_spans(self, span_data: Dict) -> List[Dict]:
        """Convert span annotation data to serializable list."""
        spans = []
        for key, value in span_data.items():
            if hasattr(key, 'get_schema'):
                spans.append({
                    "schema": key.get_schema(),
                    "name": key.get_name(),
                    "title": key.get_title() if hasattr(key, 'get_title') else "",
                    "start": key.get_start(),
                    "end": key.get_end(),
                    "id": key.get_id(),
                    "target_field": key.get_target_field() if hasattr(key, 'get_target_field') else None,
                })
            elif isinstance(value, dict):
                spans.append(value)
        return spans

    def _serialize_behavioral(self, bd) -> Dict:
        """Convert behavioral data to serializable dict."""
        if hasattr(bd, 'to_dict'):
            return bd.to_dict()
        elif isinstance(bd, dict):
            return bd
        return {}

    def _compute_agreement(
        self, item_annotations: Dict[str, Dict], scheme_names: List[str]
    ) -> Dict[str, float]:
        """
        Compute per-schema agreement for an item.

        Uses simple percentage agreement (proportion of annotators who chose
        the most common label). For more sophisticated metrics, simpledorff
        can be used but requires multiple items.

        Returns:
            Dict mapping schema_name to agreement score (0.0 - 1.0)
        """
        agreement_scores = {}

        for schema in scheme_names:
            values = []
            for user_id, user_annots in item_annotations.items():
                if schema in user_annots:
                    val = user_annots[schema]
                    # Normalize to comparable form
                    if isinstance(val, dict):
                        # For multiselect: frozenset of selected labels
                        selected = frozenset(
                            k for k, v in val.items()
                            if v is True or v == "true" or v == 1
                        )
                        values.append(selected)
                    else:
                        values.append(val)

            if len(values) < 2:
                continue

            # Compute pairwise agreement (percentage)
            agree_count = 0
            total_pairs = 0
            for i in range(len(values)):
                for j in range(i + 1, len(values)):
                    total_pairs += 1
                    if values[i] == values[j]:
                        agree_count += 1

            agreement_scores[schema] = (
                agree_count / total_pairs if total_pairs > 0 else 1.0
            )

        return agreement_scores

    def _compute_overall_agreement(self, agreement_scores: Dict[str, float]) -> float:
        """Compute overall agreement as the mean of per-schema scores."""
        if not agreement_scores:
            return 1.0
        return sum(agreement_scores.values()) / len(agreement_scores)

    def get_queue(
        self,
        adjudicator_id: Optional[str] = None,
        filter_status: Optional[str] = None,
    ) -> List[AdjudicationItem]:
        """
        Get the adjudication queue, optionally filtered by status.

        Args:
            adjudicator_id: Optional adjudicator to filter by assignment
            filter_status: Optional status filter ("pending", "completed", etc.)

        Returns:
            List of AdjudicationItem objects
        """
        with self._lock:
            if not self._queue_built:
                self.build_queue()

            items = list(self.queue.values())

            if filter_status:
                items = [i for i in items if i.status == filter_status]

            # Sort: pending first, then by agreement (lowest first)
            items.sort(key=lambda x: (
                0 if x.status == "pending" else 1 if x.status == "in_progress" else 2,
                x.overall_agreement,
            ))

            return items

    def get_item(self, instance_id: str) -> Optional[AdjudicationItem]:
        """
        Get full item data for adjudication.

        Args:
            instance_id: The instance ID to retrieve

        Returns:
            AdjudicationItem or None if not in queue
        """
        with self._lock:
            if not self._queue_built:
                self.build_queue()
            return self.queue.get(str(instance_id))

    def get_item_text(self, instance_id: str) -> str:
        """Get the text content for an item."""
        from potato.item_state_management import get_item_state_manager

        ism = get_item_state_manager()
        item = ism.instance_id_to_instance.get(instance_id)
        if item:
            # Use text_key from config if available
            text_key = self.config.get("item_properties", {}).get("text_key", "text")
            data = item.get_data()
            if isinstance(data, dict) and text_key in data:
                return data[text_key]
            return item.get_text()
        return ""

    def get_item_data(self, instance_id: str) -> Dict[str, Any]:
        """Get the full raw data for an item."""
        from potato.item_state_management import get_item_state_manager

        ism = get_item_state_manager()
        item = ism.instance_id_to_instance.get(instance_id)
        if item:
            data = item.get_data()
            if isinstance(data, dict):
                return data
            return {"text": str(data)}
        return {}

    def get_next_item(self, adjudicator_id: str) -> Optional[AdjudicationItem]:
        """Get the next pending item for an adjudicator."""
        items = self.get_queue(filter_status="pending")
        if items:
            return items[0]
        return None

    def skip_item(self, instance_id: str, adjudicator_id: str) -> bool:
        """Mark an item as skipped."""
        with self._lock:
            item = self.queue.get(str(instance_id))
            if item:
                item.status = "skipped"
                return True
            return False

    def submit_decision(self, decision: AdjudicationDecision) -> bool:
        """
        Submit an adjudication decision.

        Args:
            decision: The AdjudicationDecision to save

        Returns:
            True if successful
        """
        with self._lock:
            instance_id = str(decision.instance_id)
            self.decisions[instance_id] = decision

            # Update queue status
            if instance_id in self.queue:
                self.queue[instance_id].status = "completed"
                self.queue[instance_id].assigned_adjudicator = decision.adjudicator_id

            # Persist to disk
            self._save_decisions()

            self.logger.info(
                f"Adjudication decision saved for {instance_id} "
                f"by {decision.adjudicator_id}"
            )
            return True

    def get_stats(self) -> Dict[str, Any]:
        """Get adjudication progress statistics."""
        with self._lock:
            if not self._queue_built:
                self.build_queue()

            total = len(self.queue)
            completed = sum(
                1 for i in self.queue.values() if i.status == "completed"
            )
            pending = sum(
                1 for i in self.queue.values() if i.status == "pending"
            )
            skipped = sum(
                1 for i in self.queue.values() if i.status == "skipped"
            )
            in_progress = sum(
                1 for i in self.queue.values() if i.status == "in_progress"
            )

            avg_agreement = 0.0
            if self.queue:
                avg_agreement = sum(
                    i.overall_agreement for i in self.queue.values()
                ) / len(self.queue)

            # Per-adjudicator stats
            adjudicator_stats = defaultdict(lambda: {"completed": 0, "total_time_ms": 0})
            for decision in self.decisions.values():
                adj_id = decision.adjudicator_id
                adjudicator_stats[adj_id]["completed"] += 1
                adjudicator_stats[adj_id]["total_time_ms"] += decision.time_spent_ms

            return {
                "total": total,
                "completed": completed,
                "pending": pending,
                "skipped": skipped,
                "in_progress": in_progress,
                "completion_rate": completed / total if total > 0 else 0.0,
                "avg_agreement": avg_agreement,
                "adjudicator_stats": dict(adjudicator_stats),
            }

    def get_decision(self, instance_id: str) -> Optional[AdjudicationDecision]:
        """Get the decision for an item, if one exists."""
        return self.decisions.get(str(instance_id))

    # ------------------------------------------------------------------
    # Phase 3: Similarity integration
    # ------------------------------------------------------------------

    def _precompute_similarities(self) -> None:
        """Precompute embeddings for all items in the item state manager."""
        if not self.similarity_engine or not self.similarity_engine.enabled:
            return

        from potato.item_state_management import get_item_state_manager

        try:
            ism = get_item_state_manager()
            item_texts = {}
            for instance_id, item in ism.instance_id_to_instance.items():
                text = self.get_item_text(str(instance_id))
                if text:
                    item_texts[str(instance_id)] = text

            if item_texts:
                count = self.similarity_engine.precompute_embeddings(item_texts)
                self.logger.info(f"Precomputed {count} similarity embeddings")
        except Exception as e:
            self.logger.error(f"Error precomputing similarities: {e}")

    def get_similar_items(
        self, instance_id: str, include_metadata: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get similar items for a given instance, enriched with queue metadata.

        Args:
            instance_id: The reference instance ID
            include_metadata: Whether to include decision/consensus data

        Returns:
            List of dicts with instance_id, similarity, and optional metadata
        """
        if not self.similarity_engine or not self.similarity_engine.enabled:
            return []

        similar = self.similarity_engine.find_similar(instance_id)
        results = []

        for other_id, score in similar:
            entry = {
                "instance_id": other_id,
                "similarity": round(score, 4),
                "text_preview": self.similarity_engine.text_cache.get(
                    other_id, ""
                ),
            }

            if include_metadata:
                queue_item = self.queue.get(other_id)
                decision = self.decisions.get(other_id)

                entry["in_queue"] = queue_item is not None
                entry["status"] = queue_item.status if queue_item else None
                entry["overall_agreement"] = (
                    queue_item.overall_agreement if queue_item else None
                )

                if decision:
                    entry["decision"] = "completed"
                    entry["consensus_label"] = None
                else:
                    entry["decision"] = None
                    if queue_item:
                        entry["consensus_label"] = self._get_consensus_label(
                            queue_item
                        )
                    else:
                        entry["consensus_label"] = None

            results.append(entry)

        return results

    def _get_consensus_label(self, item: AdjudicationItem) -> Optional[str]:
        """
        Get the majority/consensus label for an item across the first schema.

        Args:
            item: The AdjudicationItem

        Returns:
            The most common label value as a string, or None
        """
        if not item.annotations:
            return None

        # Use the first schema that has values
        for user_annots in item.annotations.values():
            for schema_name in user_annots:
                # Collect all values for this schema
                values = []
                for ua in item.annotations.values():
                    val = ua.get(schema_name)
                    if val is not None:
                        if isinstance(val, dict):
                            # Multiselect: use frozenset representation
                            selected = sorted(
                                k for k, v in val.items()
                                if v is True or v == "true" or v == 1
                            )
                            values.append(", ".join(selected) if selected else str(val))
                        else:
                            values.append(str(val))

                if values:
                    counter = Counter(values)
                    return counter.most_common(1)[0][0]

        return None

    # ------------------------------------------------------------------
    # Phase 3: Behavioral signal analysis
    # ------------------------------------------------------------------

    def get_annotator_signals(
        self, user_id: str, instance_id: str
    ) -> Dict[str, Any]:
        """
        Compute per-annotator quality signals for a specific item.

        Returns:
            Dict with user_id, instance_id, flags list, and metrics dict
        """
        flags = []
        metrics = {}

        instance_id = str(instance_id)
        item = self.queue.get(instance_id)
        if not item:
            return {"user_id": user_id, "instance_id": instance_id,
                    "flags": [], "metrics": {}}

        # Get behavioral data for this user on this item
        bd = item.behavioral_data.get(user_id, {})
        if hasattr(bd, 'to_dict'):
            bd = bd.to_dict()

        total_time = bd.get("total_time_ms", 0)
        metrics["total_time_ms"] = total_time

        # 1. Speed z-score vs user's typical time
        user_times = self._get_user_times(user_id)
        if len(user_times) >= 3 and total_time > 0:
            mean_time = sum(user_times) / len(user_times)
            std_time = math.sqrt(
                sum((t - mean_time) ** 2 for t in user_times) / len(user_times)
            )
            if std_time > 0:
                z_score = (total_time - mean_time) / std_time
                metrics["speed_z_score"] = round(z_score, 2)
                if z_score < -2.0:
                    flags.append({
                        "type": "unusually_fast",
                        "severity": "high",
                        "message": f"Annotation time ({total_time}ms) is {abs(z_score):.1f} std devs below average"
                    })

        # 2. Fast decision warning
        fast_threshold = self.adj_config.fast_decision_warning_ms
        if fast_threshold > 0 and 0 < total_time < fast_threshold:
            flags.append({
                "type": "fast_decision",
                "severity": "medium",
                "message": f"Decision made in {total_time}ms (below {fast_threshold}ms threshold)"
            })

        # 3. Annotation change count
        raw_changes = bd.get("annotation_changes", [])
        change_count = len(raw_changes) if isinstance(raw_changes, list) else int(raw_changes or 0)
        metrics["annotation_changes"] = change_count
        if change_count > 5:
            flags.append({
                "type": "excessive_changes",
                "severity": "medium",
                "message": f"Made {change_count} annotation changes on this item"
            })

        # 4. Historical agreement rate with consensus
        agreement_rate = self._compute_user_agreement_rate(user_id)
        if agreement_rate is not None:
            metrics["agreement_rate"] = round(agreement_rate, 3)
            if agreement_rate < 0.4:
                flags.append({
                    "type": "low_agreement",
                    "severity": "high",
                    "message": f"Agreement rate with consensus: {agreement_rate:.0%}"
                })

        # 5. Similar item consistency
        if self.similarity_engine and self.similarity_engine.enabled:
            inconsistencies = self._check_similar_item_consistency(
                user_id, instance_id
            )
            metrics["similar_item_inconsistencies"] = inconsistencies
            if inconsistencies > 0:
                flags.append({
                    "type": "similar_item_inconsistency",
                    "severity": "medium",
                    "message": f"Different label on {inconsistencies} similar item(s)"
                })

        return {
            "user_id": user_id,
            "instance_id": instance_id,
            "flags": flags,
            "metrics": metrics,
        }

    def _get_user_times(self, user_id: str) -> List[float]:
        """Collect all annotation times for a user across queue items."""
        times = []
        for item in self.queue.values():
            bd = item.behavioral_data.get(user_id, {})
            if hasattr(bd, 'to_dict'):
                bd = bd.to_dict()
            t = bd.get("total_time_ms", 0)
            if t > 0:
                times.append(t)
        return times

    def _compute_user_agreement_rate(self, user_id: str) -> Optional[float]:
        """
        Compute how often a user agrees with the consensus across all items.

        Returns:
            Float 0-1 or None if insufficient data (needs >= 3 items)
        """
        agree_count = 0
        total_count = 0

        for item in self.queue.values():
            if user_id not in item.annotations:
                continue

            consensus = self._get_consensus_label(item)
            if consensus is None:
                continue

            user_annots = item.annotations[user_id]
            # Check the first schema
            for schema_name, val in user_annots.items():
                if isinstance(val, dict):
                    selected = sorted(
                        k for k, v in val.items()
                        if v is True or v == "true" or v == 1
                    )
                    user_label = ", ".join(selected) if selected else str(val)
                else:
                    user_label = str(val)

                if user_label == consensus:
                    agree_count += 1
                total_count += 1
                break  # Only check first schema

        if total_count < 3:
            return None

        return agree_count / total_count

    def _check_similar_item_consistency(
        self, user_id: str, instance_id: str
    ) -> int:
        """
        Check if user's label on similar items (>0.8 similarity) is consistent.

        Returns:
            Count of similar items where user's label differs
        """
        if not self.similarity_engine:
            return 0

        similar = self.similarity_engine.find_similar(instance_id)
        if not similar:
            return 0

        # Get user's label on the current item
        item = self.queue.get(instance_id)
        if not item or user_id not in item.annotations:
            return 0

        user_annots = item.annotations[user_id]
        current_label = None
        current_schema = None
        for schema_name, val in user_annots.items():
            current_schema = schema_name
            if isinstance(val, dict):
                selected = sorted(
                    k for k, v in val.items()
                    if v is True or v == "true" or v == 1
                )
                current_label = ", ".join(selected) if selected else str(val)
            else:
                current_label = str(val)
            break

        if current_label is None:
            return 0

        inconsistencies = 0
        for other_id, score in similar:
            if score < 0.8:
                break  # Results are sorted by score desc

            other_item = self.queue.get(other_id)
            if not other_item or user_id not in other_item.annotations:
                continue

            other_annots = other_item.annotations[user_id]
            other_val = other_annots.get(current_schema)
            if other_val is None:
                continue

            if isinstance(other_val, dict):
                selected = sorted(
                    k for k, v in other_val.items()
                    if v is True or v == "true" or v == 1
                )
                other_label = ", ".join(selected) if selected else str(other_val)
            else:
                other_label = str(other_val)

            if other_label != current_label:
                inconsistencies += 1

        return inconsistencies

    def _get_output_dir(self) -> str:
        """Get the adjudication output directory."""
        output_dir = self.config.get("output_annotation_dir", "annotation_output")
        adj_dir = os.path.join(output_dir, self.adj_config.output_subdir)
        os.makedirs(adj_dir, exist_ok=True)
        return adj_dir

    def _save_decisions(self) -> None:
        """Persist all decisions to disk."""
        try:
            adj_dir = self._get_output_dir()
            decisions_file = os.path.join(adj_dir, "decisions.json")

            data = {
                "decisions": [d.to_dict() for d in self.decisions.values()],
                "last_updated": datetime.now().isoformat(),
            }

            with open(decisions_file, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            self.logger.error(f"Failed to save adjudication decisions: {e}")

    def _load_decisions(self) -> None:
        """Load previously saved decisions from disk."""
        try:
            output_dir = self.config.get("output_annotation_dir", "annotation_output")
            adj_dir = os.path.join(output_dir, self.adj_config.output_subdir)
            decisions_file = os.path.join(adj_dir, "decisions.json")

            if not os.path.exists(decisions_file):
                return

            with open(decisions_file, "r") as f:
                data = json.load(f)

            for d in data.get("decisions", []):
                decision = AdjudicationDecision.from_dict(d)
                self.decisions[decision.instance_id] = decision

            self.logger.info(
                f"Loaded {len(self.decisions)} previous adjudication decisions"
            )

        except Exception as e:
            self.logger.warning(f"Failed to load adjudication decisions: {e}")

    def generate_final_dataset(self) -> List[Dict[str, Any]]:
        """
        Generate the final dataset by merging unanimous agreements
        and adjudication decisions.

        Returns:
            List of item dicts with final labels and provenance
        """
        from potato.user_state_management import get_user_state_manager
        from potato.item_state_management import get_item_state_manager

        usm = get_user_state_manager()
        ism = get_item_state_manager()

        annotation_schemes = self.config.get("annotation_schemes", [])
        scheme_names = [s.get("name", "") for s in annotation_schemes]
        results = []

        for instance_id, item in ism.instance_id_to_instance.items():
            instance_id_str = str(instance_id)
            result = {
                "instance_id": instance_id_str,
                "item_data": item.get_data() if hasattr(item, 'get_data') else {},
            }

            # Check if we have an adjudication decision
            decision = self.decisions.get(instance_id_str)
            if decision:
                result["labels"] = decision.label_decisions
                result["spans"] = decision.span_decisions
                result["source"] = "adjudicated"
                result["adjudicator"] = decision.adjudicator_id
                result["confidence"] = decision.confidence
                result["provenance"] = decision.source
                results.append(result)
                continue

            # Check for unanimous agreement
            annotators = ism.instance_annotators.get(instance_id, set())
            annotators = {
                u for u in annotators
                if u not in self.adj_config.adjudicator_users
            }

            if len(annotators) < 2:
                continue

            # Collect annotations
            annotations = {}
            for user_id in annotators:
                user_state = usm.get_user_state(user_id)
                if not user_state:
                    continue
                labels = user_state.instance_id_to_label_to_value.get(
                    instance_id_str, {}
                )
                if labels:
                    annotations[user_id] = self._serialize_labels(labels)

            if not annotations:
                continue

            # Check for unanimity per schema
            unanimous_labels = {}
            is_unanimous = True
            for schema in scheme_names:
                values = []
                for user_annots in annotations.values():
                    if schema in user_annots:
                        values.append(json.dumps(user_annots[schema], sort_keys=True))

                if len(values) < 2:
                    continue

                if len(set(values)) == 1:
                    unanimous_labels[schema] = json.loads(values[0])
                else:
                    is_unanimous = False

            if is_unanimous and unanimous_labels:
                result["labels"] = unanimous_labels
                result["source"] = "unanimous"
                result["num_annotators"] = len(annotators)
                results.append(result)
            else:
                result["labels"] = {}
                result["source"] = "unresolved"
                result["num_annotators"] = len(annotators)
                results.append(result)

        return results


def init_adjudication_manager(config: Dict[str, Any]) -> Optional[AdjudicationManager]:
    """Initialize the singleton AdjudicationManager."""
    global _ADJUDICATION_MANAGER

    with _ADJUDICATION_LOCK:
        if _ADJUDICATION_MANAGER is None:
            _ADJUDICATION_MANAGER = AdjudicationManager(config)

    return _ADJUDICATION_MANAGER


def get_adjudication_manager() -> Optional[AdjudicationManager]:
    """Get the singleton AdjudicationManager instance."""
    return _ADJUDICATION_MANAGER


def clear_adjudication_manager():
    """Clear the singleton (for testing)."""
    global _ADJUDICATION_MANAGER
    with _ADJUDICATION_LOCK:
        _ADJUDICATION_MANAGER = None

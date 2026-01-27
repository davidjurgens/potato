"""
Quality Control Module

This module provides comprehensive quality control features for annotation projects:
- Attention Checks: Inject known-answer items to verify annotator engagement
- Gold Standards: Compare annotations against expert-labeled items for accuracy tracking
- Pre-annotation Support: Pre-fill forms with model predictions

The module integrates with ItemStateManager for item injection and UserStateManager
for tracking results.
"""

import json
import logging
import random
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

# Singleton instance
_QUALITY_CONTROL_MANAGER = None
_QUALITY_CONTROL_LOCK = threading.Lock()


@dataclass
class AttentionCheckResult:
    """Result of an attention check evaluation."""
    item_id: str
    user_id: str
    passed: bool
    expected: Dict[str, Any]
    actual: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    response_time_seconds: Optional[float] = None


@dataclass
class GoldStandardResult:
    """Result of a gold standard evaluation."""
    item_id: str
    user_id: str
    correct: bool
    gold_label: Dict[str, Any]
    user_response: Dict[str, Any]
    explanation: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class QualityControlConfig:
    """Configuration for quality control features."""
    # Attention checks config
    attention_checks_enabled: bool = False
    attention_items_file: Optional[str] = None
    attention_frequency: Optional[int] = None  # Insert one every N items
    attention_probability: Optional[float] = None  # OR probability per item
    attention_min_response_time: float = 0.0  # Minimum seconds (flag fast responses)
    attention_warn_threshold: int = 2
    attention_warn_message: str = "Please read items carefully before answering."
    attention_block_threshold: int = 5
    attention_block_message: str = "You have been blocked due to too many incorrect attention check responses."

    # Gold standards config
    gold_standards_enabled: bool = False
    gold_items_file: Optional[str] = None
    gold_mode: str = "mixed"  # training, mixed, separate
    gold_frequency: Optional[int] = None
    gold_min_accuracy: float = 0.7
    gold_evaluation_count: int = 10
    gold_show_correct_answer: bool = False  # Default to silent (admin-only tracking)
    gold_show_explanation: bool = False     # Default to silent (admin-only tracking)

    # Auto-promotion: items become gold standards when annotators agree
    gold_auto_promote_enabled: bool = False
    gold_auto_promote_min_annotators: int = 3  # Minimum annotators before checking
    gold_auto_promote_agreement: float = 1.0   # Agreement threshold (1.0 = unanimous)

    # Pre-annotation config
    pre_annotation_enabled: bool = False
    pre_annotation_field: str = "predictions"
    pre_annotation_allow_modification: bool = True
    pre_annotation_show_confidence: bool = False
    pre_annotation_highlight_threshold: float = 0.7


class QualityControlManager:
    """
    Manages quality control features including attention checks, gold standards,
    and pre-annotation support.
    """

    def __init__(self, config: Dict[str, Any], base_dir: str):
        """
        Initialize the quality control manager.

        Args:
            config: The full application configuration
            base_dir: Base directory for resolving file paths
        """
        self.config = config
        self.base_dir = base_dir
        self.logger = logging.getLogger(__name__)
        self._lock = threading.RLock()

        # Parse configuration
        self.qc_config = self._parse_config(config)

        # Attention check data
        self.attention_items: List[Dict] = []
        self.attention_expected: Dict[str, Dict[str, Any]] = {}  # item_id -> expected_answer
        self.attention_results: Dict[str, List[AttentionCheckResult]] = defaultdict(list)  # user_id -> results
        self.user_items_since_attention: Dict[str, int] = defaultdict(int)  # user_id -> count

        # Gold standard data
        self.gold_items: List[Dict] = []
        self.gold_labels: Dict[str, Dict[str, Any]] = {}  # item_id -> gold_label
        self.gold_explanations: Dict[str, str] = {}  # item_id -> explanation
        self.gold_results: Dict[str, List[GoldStandardResult]] = defaultdict(list)  # user_id -> results

        # Pre-annotation data (stored per-item)
        self.pre_annotations: Dict[str, Dict[str, Any]] = {}  # item_id -> pre_annotation_data

        # Auto-promotion tracking
        self.item_annotations: Dict[str, Dict[str, Any]] = defaultdict(dict)  # item_id -> {user_id -> response}
        self.promoted_gold_items: List[Dict] = []  # Items promoted to gold via consensus
        self.promoted_gold_labels: Dict[str, Dict[str, Any]] = {}  # Promoted item_id -> consensus_label

        # Load data files if configured
        self._load_attention_checks()
        self._load_gold_standards()

        self.logger.info(f"QualityControlManager initialized: "
                        f"attention_checks={self.qc_config.attention_checks_enabled}, "
                        f"gold_standards={self.qc_config.gold_standards_enabled}, "
                        f"pre_annotation={self.qc_config.pre_annotation_enabled}")

    def _parse_config(self, config: Dict[str, Any]) -> QualityControlConfig:
        """Parse quality control configuration from the main config."""
        qc = QualityControlConfig()

        # Parse attention checks config
        attn_config = config.get('attention_checks', {})
        if attn_config.get('enabled', False):
            qc.attention_checks_enabled = True
            qc.attention_items_file = attn_config.get('items_file')
            qc.attention_frequency = attn_config.get('frequency')
            qc.attention_probability = attn_config.get('probability')
            qc.attention_min_response_time = attn_config.get('min_response_time', 0.0)

            failure_handling = attn_config.get('failure_handling', {})
            qc.attention_warn_threshold = failure_handling.get('warn_threshold', 2)
            qc.attention_warn_message = failure_handling.get('warn_message', qc.attention_warn_message)
            qc.attention_block_threshold = failure_handling.get('block_threshold', 5)
            qc.attention_block_message = failure_handling.get('block_message', qc.attention_block_message)

        # Parse gold standards config
        gold_config = config.get('gold_standards', {})
        if gold_config.get('enabled', False):
            qc.gold_standards_enabled = True
            qc.gold_items_file = gold_config.get('items_file')
            qc.gold_mode = gold_config.get('mode', 'mixed')
            qc.gold_frequency = gold_config.get('frequency')

            accuracy_config = gold_config.get('accuracy', {})
            qc.gold_min_accuracy = accuracy_config.get('min_threshold', 0.7)
            qc.gold_evaluation_count = accuracy_config.get('evaluation_count', 10)

            feedback_config = gold_config.get('feedback', {})
            qc.gold_show_correct_answer = feedback_config.get('show_correct_answer', False)
            qc.gold_show_explanation = feedback_config.get('show_explanation', False)

            # Auto-promotion settings
            auto_promote = gold_config.get('auto_promote', {})
            if auto_promote.get('enabled', False):
                qc.gold_auto_promote_enabled = True
                qc.gold_auto_promote_min_annotators = auto_promote.get('min_annotators', 3)
                qc.gold_auto_promote_agreement = auto_promote.get('agreement_threshold', 1.0)

        # Parse pre-annotation config
        pre_config = config.get('pre_annotation', {})
        if pre_config.get('enabled', False):
            qc.pre_annotation_enabled = True
            qc.pre_annotation_field = pre_config.get('field', 'predictions')
            qc.pre_annotation_allow_modification = pre_config.get('allow_modification', True)
            qc.pre_annotation_show_confidence = pre_config.get('show_confidence', False)
            qc.pre_annotation_highlight_threshold = pre_config.get('highlight_low_confidence', 0.7)

        return qc

    def _load_attention_checks(self) -> None:
        """Load attention check items from file."""
        if not self.qc_config.attention_checks_enabled:
            return

        if not self.qc_config.attention_items_file:
            self.logger.warning("Attention checks enabled but no items_file specified")
            return

        file_path = Path(self.base_dir) / self.qc_config.attention_items_file
        if not file_path.exists():
            self.logger.warning(f"Attention checks file not found: {file_path}")
            return

        try:
            with open(file_path, 'r') as f:
                items = json.load(f)

            if not isinstance(items, list):
                self.logger.error("Attention checks file must contain a JSON array")
                return

            for item in items:
                if 'id' not in item or 'expected_answer' not in item:
                    self.logger.warning(f"Attention check item missing required fields: {item}")
                    continue

                self.attention_items.append(item)
                self.attention_expected[item['id']] = item['expected_answer']

            self.logger.info(f"Loaded {len(self.attention_items)} attention check items")

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse attention checks file: {e}")
        except Exception as e:
            self.logger.error(f"Failed to load attention checks: {e}")

    def _load_gold_standards(self) -> None:
        """Load gold standard items from file."""
        if not self.qc_config.gold_standards_enabled:
            return

        if not self.qc_config.gold_items_file:
            self.logger.warning("Gold standards enabled but no items_file specified")
            return

        file_path = Path(self.base_dir) / self.qc_config.gold_items_file
        if not file_path.exists():
            self.logger.warning(f"Gold standards file not found: {file_path}")
            return

        try:
            with open(file_path, 'r') as f:
                items = json.load(f)

            if not isinstance(items, list):
                self.logger.error("Gold standards file must contain a JSON array")
                return

            for item in items:
                if 'id' not in item or 'gold_label' not in item:
                    self.logger.warning(f"Gold standard item missing required fields: {item}")
                    continue

                self.gold_items.append(item)
                self.gold_labels[item['id']] = item['gold_label']
                if 'explanation' in item:
                    self.gold_explanations[item['id']] = item['explanation']

            self.logger.info(f"Loaded {len(self.gold_items)} gold standard items")

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse gold standards file: {e}")
        except Exception as e:
            self.logger.error(f"Failed to load gold standards: {e}")

    # =========================================================================
    # Attention Check Methods
    # =========================================================================

    def is_attention_check(self, item_id: str) -> bool:
        """Check if an item is an attention check."""
        return item_id in self.attention_expected

    def should_inject_attention_check(self, user_id: str) -> bool:
        """
        Determine if an attention check should be injected for this user.

        Args:
            user_id: The user ID

        Returns:
            True if an attention check should be injected
        """
        if not self.qc_config.attention_checks_enabled or not self.attention_items:
            return False

        with self._lock:
            # Frequency-based injection
            if self.qc_config.attention_frequency:
                items_since = self.user_items_since_attention.get(user_id, 0)
                return items_since >= self.qc_config.attention_frequency

            # Probability-based injection
            if self.qc_config.attention_probability:
                return random.random() < self.qc_config.attention_probability

        return False

    def get_attention_check_item(self, user_id: str) -> Optional[Dict]:
        """
        Get a random attention check item for a user.

        Args:
            user_id: The user ID

        Returns:
            An attention check item dict, or None if none available
        """
        if not self.attention_items:
            return None

        with self._lock:
            # Get items this user hasn't seen yet
            seen_ids = {r.item_id for r in self.attention_results.get(user_id, [])}
            available = [item for item in self.attention_items if item['id'] not in seen_ids]

            if not available:
                # Recycle items if all have been seen
                available = self.attention_items

            selected = random.choice(available)
            # Reset counter
            self.user_items_since_attention[user_id] = 0
            return selected

    def record_regular_item(self, user_id: str) -> None:
        """Record that a user annotated a regular (non-attention-check) item."""
        with self._lock:
            self.user_items_since_attention[user_id] = self.user_items_since_attention.get(user_id, 0) + 1

    def validate_attention_response(
        self,
        user_id: str,
        item_id: str,
        response: Dict[str, Any],
        response_time_seconds: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Validate a response to an attention check.

        Args:
            user_id: The user ID
            item_id: The attention check item ID
            response: The user's response (schema_name -> value)
            response_time_seconds: Time taken to respond

        Returns:
            Dict with validation result if this is an attention check, None otherwise.
            Result includes: passed, warning (optional), blocked (optional), message (optional)
        """
        if item_id not in self.attention_expected:
            return None

        expected = self.attention_expected[item_id]
        passed = self._compare_responses(expected, response)

        # Check for suspiciously fast response
        if (response_time_seconds is not None and
            self.qc_config.attention_min_response_time > 0 and
            response_time_seconds < self.qc_config.attention_min_response_time):
            self.logger.warning(f"User {user_id} responded to attention check {item_id} "
                              f"in {response_time_seconds:.1f}s (min: {self.qc_config.attention_min_response_time}s)")
            # Still record the result but log the fast response

        # Record result
        result = AttentionCheckResult(
            item_id=item_id,
            user_id=user_id,
            passed=passed,
            expected=expected,
            actual=response,
            response_time_seconds=response_time_seconds
        )

        with self._lock:
            self.attention_results[user_id].append(result)
            failures = len([r for r in self.attention_results[user_id] if not r.passed])

        # Check thresholds
        response_data = {"passed": passed}

        if failures >= self.qc_config.attention_block_threshold:
            response_data["blocked"] = True
            response_data["message"] = self.qc_config.attention_block_message
            self.logger.warning(f"User {user_id} blocked after {failures} attention check failures")
        elif failures >= self.qc_config.attention_warn_threshold:
            response_data["warning"] = True
            response_data["message"] = self.qc_config.attention_warn_message
            self.logger.info(f"User {user_id} warned after {failures} attention check failures")

        return response_data

    def get_attention_check_stats(self, user_id: str) -> Dict[str, Any]:
        """Get attention check statistics for a user."""
        with self._lock:
            results = self.attention_results.get(user_id, [])
            passed = len([r for r in results if r.passed])
            failed = len([r for r in results if not r.passed])
            total = passed + failed

            return {
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": passed / total if total > 0 else 0.0
            }

    # =========================================================================
    # Gold Standard Methods
    # =========================================================================

    def is_gold_standard(self, item_id: str) -> bool:
        """Check if an item is a gold standard."""
        return item_id in self.gold_labels

    def should_inject_gold_standard(self, user_id: str, items_since_last: int) -> bool:
        """
        Determine if a gold standard should be injected.

        Args:
            user_id: The user ID
            items_since_last: Number of items since last gold standard

        Returns:
            True if a gold standard should be injected
        """
        if not self.qc_config.gold_standards_enabled or not self.gold_items:
            return False

        if self.qc_config.gold_mode == 'training':
            # Gold standards only in training phase - handled separately
            return False

        if self.qc_config.gold_frequency:
            return items_since_last >= self.qc_config.gold_frequency

        return False

    def get_gold_standard_item(self, user_id: str) -> Optional[Dict]:
        """
        Get a gold standard item for a user.

        Args:
            user_id: The user ID

        Returns:
            A gold standard item dict, or None if none available
        """
        if not self.gold_items:
            return None

        with self._lock:
            # Get items this user hasn't seen yet
            seen_ids = {r.item_id for r in self.gold_results.get(user_id, [])}
            available = [item for item in self.gold_items if item['id'] not in seen_ids]

            if not available:
                # Recycle items if all have been seen
                available = self.gold_items

            return random.choice(available)

    def validate_gold_response(
        self,
        user_id: str,
        item_id: str,
        response: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Validate a response against a gold standard.

        By default, gold standards are "silent" - results are recorded for admin
        review but no feedback is shown to users. This can be changed via config
        for training scenarios.

        Args:
            user_id: The user ID
            item_id: The gold standard item ID
            response: The user's response

        Returns:
            Dict with validation result if this is a gold standard, None otherwise.
            By default only contains 'recorded': True to indicate silent recording.
            If feedback is enabled, also includes: correct, gold_label, explanation.
        """
        if item_id not in self.gold_labels:
            return None

        gold = self.gold_labels[item_id]
        correct = self._compare_responses(gold, response)
        explanation = self.gold_explanations.get(item_id)

        # Record result (always happens, regardless of feedback settings)
        result = GoldStandardResult(
            item_id=item_id,
            user_id=user_id,
            correct=correct,
            gold_label=gold,
            user_response=response,
            explanation=explanation
        )

        with self._lock:
            self.gold_results[user_id].append(result)

        # By default, gold standards are silent (recorded but no feedback to user)
        # Only include feedback if explicitly enabled in config
        show_feedback = (self.qc_config.gold_show_correct_answer or
                        self.qc_config.gold_show_explanation)

        if not show_feedback:
            # Silent recording - just indicate it was recorded, no user feedback
            return {"recorded": True, "silent": True}

        # Build response with feedback (only if enabled)
        response_data = {"correct": correct, "recorded": True}

        if self.qc_config.gold_show_correct_answer:
            response_data["gold_label"] = gold

        if self.qc_config.gold_show_explanation and explanation:
            response_data["explanation"] = explanation

        # Check accuracy threshold (only show warning if feedback is enabled)
        accuracy_data = self.get_gold_accuracy(user_id)
        if accuracy_data["total"] >= self.qc_config.gold_evaluation_count:
            if accuracy_data["accuracy"] < self.qc_config.gold_min_accuracy:
                response_data["accuracy_warning"] = True
                response_data["current_accuracy"] = accuracy_data["accuracy"]
                response_data["required_accuracy"] = self.qc_config.gold_min_accuracy

        return response_data

    def get_gold_accuracy(self, user_id: str) -> Dict[str, Any]:
        """Get gold standard accuracy for a user."""
        with self._lock:
            results = self.gold_results.get(user_id, [])
            correct = len([r for r in results if r.correct])
            total = len(results)

            return {
                "total": total,
                "correct": correct,
                "accuracy": correct / total if total > 0 else 0.0,
                "results": [
                    {
                        "item_id": r.item_id,
                        "correct": r.correct,
                        "timestamp": r.timestamp.isoformat()
                    }
                    for r in results
                ]
            }

    # =========================================================================
    # Gold Standard Auto-Promotion Methods
    # =========================================================================

    def record_item_annotation(
        self,
        item_id: str,
        user_id: str,
        response: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Record an annotation for potential gold standard auto-promotion.

        When enough annotators agree on a label, the item is automatically
        promoted to the gold standard pool.

        Args:
            item_id: The item ID
            user_id: The user ID
            response: The user's annotation response

        Returns:
            Dict with promotion info if item was promoted, None otherwise
        """
        if not self.qc_config.gold_auto_promote_enabled:
            return None

        # Don't track items that are already gold standards
        if self.is_gold_standard(item_id):
            return None

        with self._lock:
            # Record this annotation
            self.item_annotations[item_id][user_id] = response

            # Check if we have enough annotators
            annotations = self.item_annotations[item_id]
            if len(annotations) < self.qc_config.gold_auto_promote_min_annotators:
                return None

            # Check agreement
            promotion_result = self._check_and_promote(item_id, annotations)
            return promotion_result

    def _check_and_promote(
        self,
        item_id: str,
        annotations: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Check if annotations meet agreement threshold and promote if so.

        Args:
            item_id: The item ID
            annotations: Dict of user_id -> response

        Returns:
            Promotion info if promoted, None otherwise
        """
        # Extract responses and check agreement for each schema
        consensus_label = {}
        all_schemas_agree = True

        # Group by schema
        schema_responses: Dict[str, List[Any]] = defaultdict(list)
        for user_id, response in annotations.items():
            for schema, value in response.items():
                schema_responses[schema].append(value)

        # Check agreement for each schema
        for schema, values in schema_responses.items():
            # Calculate agreement ratio
            from collections import Counter
            value_counts = Counter(str(v).lower() for v in values)
            most_common_value, most_common_count = value_counts.most_common(1)[0]
            agreement_ratio = most_common_count / len(values)

            if agreement_ratio >= self.qc_config.gold_auto_promote_agreement:
                # Find the original value (not lowercased)
                for v in values:
                    if str(v).lower() == most_common_value:
                        consensus_label[schema] = v
                        break
            else:
                all_schemas_agree = False
                break

        if not all_schemas_agree:
            return None

        # Promote to gold standard
        self._promote_to_gold(item_id, consensus_label, annotations)

        self.logger.info(f"Auto-promoted item {item_id} to gold standard with label: {consensus_label}")

        return {
            "promoted": True,
            "item_id": item_id,
            "consensus_label": consensus_label,
            "annotator_count": len(annotations),
            "agreement": 1.0  # At this point we have consensus
        }

    def _promote_to_gold(
        self,
        item_id: str,
        consensus_label: Dict[str, Any],
        source_annotations: Dict[str, Dict[str, Any]]
    ) -> None:
        """
        Promote an item to the gold standard pool.

        Args:
            item_id: The item ID to promote
            consensus_label: The agreed-upon label
            source_annotations: The annotations that led to promotion
        """
        # Create gold standard entry
        gold_item = {
            "id": item_id,
            "gold_label": consensus_label,
            "auto_promoted": True,
            "promoted_at": datetime.now().isoformat(),
            "source_annotators": list(source_annotations.keys()),
            "annotator_count": len(source_annotations)
        }

        # Add to promoted gold items
        self.promoted_gold_items.append(gold_item)
        self.promoted_gold_labels[item_id] = consensus_label

        # Also add to main gold labels so is_gold_standard() works
        self.gold_labels[item_id] = consensus_label

    def get_promoted_gold_standards(self) -> List[Dict]:
        """Get all items that were auto-promoted to gold standards."""
        with self._lock:
            return list(self.promoted_gold_items)

    def get_promotion_candidates(self) -> List[Dict[str, Any]]:
        """
        Get items that are close to being promoted (for admin visibility).

        Returns items with annotations but not yet meeting the threshold.
        """
        candidates = []

        with self._lock:
            min_annotators = self.qc_config.gold_auto_promote_min_annotators

            for item_id, annotations in self.item_annotations.items():
                if item_id in self.gold_labels:
                    continue  # Already a gold standard

                if len(annotations) == 0:
                    continue

                # Calculate current agreement
                schema_agreement = {}
                schema_responses: Dict[str, List[Any]] = defaultdict(list)

                for user_id, response in annotations.items():
                    for schema, value in response.items():
                        schema_responses[schema].append(value)

                for schema, values in schema_responses.items():
                    from collections import Counter
                    value_counts = Counter(str(v).lower() for v in values)
                    if value_counts:
                        most_common_value, most_common_count = value_counts.most_common(1)[0]
                        schema_agreement[schema] = {
                            "value": most_common_value,
                            "count": most_common_count,
                            "total": len(values),
                            "agreement": most_common_count / len(values)
                        }

                candidates.append({
                    "item_id": item_id,
                    "annotator_count": len(annotations),
                    "needed_annotators": min_annotators,
                    "schema_agreement": schema_agreement
                })

        return candidates

    # =========================================================================
    # Pre-annotation Methods
    # =========================================================================

    def extract_pre_annotations(self, item_id: str, item_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract pre-annotation data from an item.

        Args:
            item_id: The item ID
            item_data: The item's data dictionary

        Returns:
            Pre-annotation data dict if available, None otherwise
        """
        if not self.qc_config.pre_annotation_enabled:
            return None

        field = self.qc_config.pre_annotation_field
        if field not in item_data:
            return None

        pre_data = item_data[field]
        if not isinstance(pre_data, dict):
            self.logger.warning(f"Pre-annotation field '{field}' in item {item_id} is not a dict")
            return None

        # Cache for later use
        self.pre_annotations[item_id] = pre_data
        return pre_data

    def get_pre_annotations(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Get cached pre-annotations for an item."""
        return self.pre_annotations.get(item_id)

    def get_pre_annotation_config(self) -> Dict[str, Any]:
        """Get pre-annotation configuration for frontend."""
        if not self.qc_config.pre_annotation_enabled:
            return {"enabled": False}

        return {
            "enabled": True,
            "allow_modification": self.qc_config.pre_annotation_allow_modification,
            "show_confidence": self.qc_config.pre_annotation_show_confidence,
            "highlight_threshold": self.qc_config.pre_annotation_highlight_threshold
        }

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _compare_responses(self, expected: Dict[str, Any], actual: Dict[str, Any]) -> bool:
        """
        Compare expected and actual responses.

        Handles various response formats:
        - Simple key-value pairs
        - Lists (for multiselect)
        - Nested structures

        Args:
            expected: The expected response
            actual: The actual response

        Returns:
            True if responses match
        """
        for key, expected_value in expected.items():
            # Handle both "schema_name" and "schema_name:label_name" formats
            actual_value = None

            # Direct match
            if key in actual:
                actual_value = actual[key]
            else:
                # Check for prefixed keys (schema_name:label_name format)
                for actual_key, val in actual.items():
                    if actual_key.startswith(key + ":") or actual_key == key:
                        actual_value = val
                        break

            if actual_value is None:
                return False

            # Compare values
            if isinstance(expected_value, list):
                if not isinstance(actual_value, list):
                    actual_value = [actual_value]
                if set(expected_value) != set(actual_value):
                    return False
            elif isinstance(expected_value, dict):
                if not isinstance(actual_value, dict):
                    return False
                if not self._compare_responses(expected_value, actual_value):
                    return False
            else:
                # Simple value comparison
                if str(expected_value).lower() != str(actual_value).lower():
                    return False

        return True

    def get_all_attention_results(self) -> Dict[str, List[Dict]]:
        """Get all attention check results for all users."""
        with self._lock:
            return {
                user_id: [
                    {
                        "item_id": r.item_id,
                        "passed": r.passed,
                        "timestamp": r.timestamp.isoformat(),
                        "response_time": r.response_time_seconds
                    }
                    for r in results
                ]
                for user_id, results in self.attention_results.items()
            }

    def get_all_gold_results(self) -> Dict[str, List[Dict]]:
        """Get all gold standard results for all users."""
        with self._lock:
            return {
                user_id: [
                    {
                        "item_id": r.item_id,
                        "correct": r.correct,
                        "timestamp": r.timestamp.isoformat()
                    }
                    for r in results
                ]
                for user_id, results in self.gold_results.items()
            }

    def get_quality_metrics(self) -> Dict[str, Any]:
        """Get comprehensive quality control metrics for admin dashboard."""
        with self._lock:
            # Attention check metrics
            attention_metrics = {
                "enabled": self.qc_config.attention_checks_enabled,
                "total_items": len(self.attention_items),
                "total_checks": sum(len(r) for r in self.attention_results.values()),
                "total_passed": sum(
                    len([x for x in r if x.passed])
                    for r in self.attention_results.values()
                ),
                "total_failed": sum(
                    len([x for x in r if not x.passed])
                    for r in self.attention_results.values()
                ),
                "by_user": {}
            }

            for user_id, results in self.attention_results.items():
                passed = len([r for r in results if r.passed])
                failed = len([r for r in results if not r.passed])
                attention_metrics["by_user"][user_id] = {
                    "passed": passed,
                    "failed": failed,
                    "pass_rate": passed / (passed + failed) if (passed + failed) > 0 else 0
                }

            # Gold standard metrics
            gold_metrics = {
                "enabled": self.qc_config.gold_standards_enabled,
                "total_items": len(self.gold_items),
                "total_evaluations": sum(len(r) for r in self.gold_results.values()),
                "total_correct": sum(
                    len([x for x in r if x.correct])
                    for r in self.gold_results.values()
                ),
                "total_incorrect": sum(
                    len([x for x in r if not x.correct])
                    for r in self.gold_results.values()
                ),
                "by_user": {},
                "by_item": {}
            }

            for user_id, results in self.gold_results.items():
                correct = len([r for r in results if r.correct])
                total = len(results)
                gold_metrics["by_user"][user_id] = {
                    "correct": correct,
                    "total": total,
                    "accuracy": correct / total if total > 0 else 0
                }

            # Per-item accuracy
            item_results = defaultdict(lambda: {"correct": 0, "total": 0})
            for results in self.gold_results.values():
                for r in results:
                    item_results[r.item_id]["total"] += 1
                    if r.correct:
                        item_results[r.item_id]["correct"] += 1

            for item_id, counts in item_results.items():
                gold_metrics["by_item"][item_id] = {
                    "correct": counts["correct"],
                    "total": counts["total"],
                    "accuracy": counts["correct"] / counts["total"] if counts["total"] > 0 else 0
                }

            # Auto-promotion metrics
            auto_promotion_metrics = {
                "enabled": self.qc_config.gold_auto_promote_enabled,
                "min_annotators": self.qc_config.gold_auto_promote_min_annotators,
                "agreement_threshold": self.qc_config.gold_auto_promote_agreement,
                "promoted_count": len(self.promoted_gold_items),
                "promoted_items": [
                    {
                        "item_id": item["id"],
                        "consensus_label": item["gold_label"],
                        "annotator_count": item["annotator_count"],
                        "promoted_at": item["promoted_at"]
                    }
                    for item in self.promoted_gold_items
                ],
                "candidates": self.get_promotion_candidates()[:20]  # Top 20 candidates
            }

            return {
                "attention_checks": attention_metrics,
                "gold_standards": gold_metrics,
                "auto_promotion": auto_promotion_metrics,
                "pre_annotation": {
                    "enabled": self.qc_config.pre_annotation_enabled,
                    "items_with_predictions": len(self.pre_annotations)
                }
            }


def init_quality_control_manager(config: Dict[str, Any], base_dir: str) -> QualityControlManager:
    """Initialize the singleton QualityControlManager."""
    global _QUALITY_CONTROL_MANAGER

    with _QUALITY_CONTROL_LOCK:
        if _QUALITY_CONTROL_MANAGER is None:
            _QUALITY_CONTROL_MANAGER = QualityControlManager(config, base_dir)

    return _QUALITY_CONTROL_MANAGER


def get_quality_control_manager() -> Optional[QualityControlManager]:
    """Get the singleton QualityControlManager instance."""
    return _QUALITY_CONTROL_MANAGER


def clear_quality_control_manager():
    """Clear the singleton (for testing)."""
    global _QUALITY_CONTROL_MANAGER
    with _QUALITY_CONTROL_LOCK:
        _QUALITY_CONTROL_MANAGER = None

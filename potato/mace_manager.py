"""
MACE Manager — integration layer between MACE algorithm and Potato data model.

Extracts annotation data from Potato's state managers, converts to MACE format,
runs the algorithm, and stores/caches results. Follows the singleton pattern
used by SimilarityEngine and other Potato managers.

Supports:
- Radio, likert, select: single categorical annotation per item
- Multiselect: per-option binary MACE (each checkbox = separate yes/no run)
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

import numpy as np

from potato.mace import MACEAlgorithm

logger = logging.getLogger(__name__)

# Categorical annotation types that MACE can process
CATEGORICAL_TYPES = {"radio", "likert", "select", "multiselect"}


@dataclass
class MACEConfig:
    """Configuration for MACE competence estimation."""

    enabled: bool = False
    trigger_every_n: int = 10
    min_annotations_per_item: int = 3
    min_items: int = 5
    num_restarts: int = 10
    num_iters: int = 50
    alpha: float = 0.5
    beta: float = 0.5
    output_subdir: str = "mace"
    cache_results: bool = True

    @classmethod
    def from_dict(cls, d):
        """Create MACEConfig from a dictionary, ignoring unknown keys."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class MACEResult:
    """Result of a single MACE run for one schema (or schema+option for multiselect)."""

    schema_name: str
    competence_scores: Dict[str, float]  # user_id -> P(knowing)
    predicted_labels: Dict[str, Any]  # instance_id -> predicted label
    label_entropy: Dict[str, float]  # instance_id -> entropy
    label_mapping: Dict[int, str]  # index -> original label value
    num_annotators: int
    num_instances: int
    timestamp: str
    log_likelihood: float
    option_name: Optional[str] = None  # For multiselect per-option

    def to_dict(self):
        return {
            "schema_name": self.schema_name,
            "competence_scores": self.competence_scores,
            "predicted_labels": self.predicted_labels,
            "label_entropy": self.label_entropy,
            "label_mapping": self.label_mapping,
            "num_annotators": self.num_annotators,
            "num_instances": self.num_instances,
            "timestamp": self.timestamp,
            "log_likelihood": self.log_likelihood,
            "option_name": self.option_name,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


class MACEManager:
    """Manages MACE computation, caching, and result access.

    Args:
        config: Full Potato configuration dictionary.
    """

    def __init__(self, config: dict):
        self.config = config
        self.mace_config = MACEConfig.from_dict(config.get("mace", {}))
        self._lock = threading.Lock()
        self._last_trigger_count = 0
        self.results: Dict[str, MACEResult] = {}  # key -> MACEResult

        # Determine output directory
        output_dir = config.get("output_annotation_dir", "annotation_output")
        self._output_dir = os.path.join(output_dir, self.mace_config.output_subdir)

        # Load cached results if configured
        if self.mace_config.cache_results:
            self._load_cache()

    def _result_key(self, schema_name: str, option_name: Optional[str] = None) -> str:
        """Generate a unique key for a MACE result."""
        if option_name:
            return f"{schema_name}::{option_name}"
        return schema_name

    def check_and_run(self, total_annotations: int) -> bool:
        """Check if it's time to run MACE and trigger if so.

        Args:
            total_annotations: Current total annotation count across all users.

        Returns:
            True if MACE was run, False otherwise.
        """
        if not self.mace_config.enabled:
            return False

        trigger_n = self.mace_config.trigger_every_n
        if trigger_n <= 0:
            return False

        # Check if we've crossed the next threshold
        if total_annotations - self._last_trigger_count >= trigger_n:
            self._last_trigger_count = total_annotations
            try:
                self.run_all_schemas()
                return True
            except Exception as e:
                logger.error(f"MACE run failed: {e}", exc_info=True)
                return False

        return False

    def run_all_schemas(self, _usm=None, _ism=None) -> Dict[str, MACEResult]:
        """Run MACE for all eligible annotation schemas.

        Args:
            _usm: Optional UserStateManager override (for testing).
            _ism: Optional ItemStateManager override (for testing).

        Returns:
            Dict mapping result keys to MACEResult objects.
        """
        if _usm is None:
            from potato.user_state_management import get_user_state_manager
            _usm = get_user_state_manager()
        if _ism is None:
            from potato.item_state_management import get_item_state_manager
            _ism = get_item_state_manager()

        usm = _usm
        ism = _ism

        annotation_schemes = self.config.get("annotation_schemes", [])
        new_results = {}

        for scheme in annotation_schemes:
            schema_type = scheme.get("annotation_type", "")
            schema_name = scheme.get("name", "")

            if schema_type not in CATEGORICAL_TYPES:
                continue

            if not schema_name:
                continue

            if schema_type == "multiselect":
                # Per-option binary MACE
                labels = scheme.get("labels", [])
                for option in labels:
                    option_name = option if isinstance(option, str) else str(option)
                    result = self._run_for_schema(
                        usm, ism, schema_name, schema_type,
                        binary_option=option_name
                    )
                    if result:
                        key = self._result_key(schema_name, option_name)
                        new_results[key] = result
            else:
                # Standard categorical MACE
                result = self._run_for_schema(usm, ism, schema_name, schema_type)
                if result:
                    key = self._result_key(schema_name)
                    new_results[key] = result

        with self._lock:
            self.results.update(new_results)

        # Save to disk
        if self.mace_config.cache_results and new_results:
            self._save_cache()

        if new_results:
            logger.info(
                f"MACE completed: {len(new_results)} schema(s) processed"
            )

        return new_results

    def _run_for_schema(
        self, usm, ism, schema_name: str, schema_type: str,
        binary_option: Optional[str] = None
    ) -> Optional[MACEResult]:
        """Run MACE for a single schema (or schema+option).

        Args:
            usm: UserStateManager instance
            ism: ItemStateManager instance
            schema_name: Name of the annotation schema
            schema_type: Type of annotation (radio, likert, select, multiselect)
            binary_option: For multiselect, the specific option to create binary MACE for

        Returns:
            MACEResult or None if insufficient data.
        """
        # Collect all annotations: {instance_id: {user_id: label_value}}
        annotations_by_item = {}
        all_annotators = set()

        user_ids = usm.get_user_ids()
        for user_id in user_ids:
            user_state = usm.get_user_state(user_id)
            if not user_state:
                continue

            for instance_id, label_dict in user_state.instance_id_to_label_to_value.items():
                annotation_value = self._extract_annotation(
                    label_dict, schema_name, schema_type, binary_option
                )
                if annotation_value is not None:
                    if instance_id not in annotations_by_item:
                        annotations_by_item[instance_id] = {}
                    annotations_by_item[instance_id][user_id] = annotation_value
                    all_annotators.add(user_id)

        # Filter items with enough annotators
        min_annots = self.mace_config.min_annotations_per_item
        eligible_items = {
            iid: annots for iid, annots in annotations_by_item.items()
            if len(annots) >= min_annots
        }

        if len(eligible_items) < self.mace_config.min_items:
            logger.debug(
                f"MACE skip {schema_name}: only {len(eligible_items)} eligible items "
                f"(need {self.mace_config.min_items})"
            )
            return None

        # Build label mapping
        if binary_option:
            # Binary: 0 = False/No, 1 = True/Yes
            all_values = {"0", "1"}
        else:
            all_values = set()
            for annots in eligible_items.values():
                all_values.update(str(v) for v in annots.values())

        sorted_values = sorted(all_values)
        value_to_idx = {v: i for i, v in enumerate(sorted_values)}
        idx_to_value = {i: v for v, i in value_to_idx.items()}
        num_labels = len(sorted_values)

        if num_labels < 2:
            logger.debug(f"MACE skip {schema_name}: only {num_labels} unique label(s)")
            return None

        # Build annotator mapping
        sorted_annotators = sorted(all_annotators)
        annotator_to_idx = {u: i for i, u in enumerate(sorted_annotators)}
        num_annotators = len(sorted_annotators)

        # Build item mapping
        sorted_items = sorted(eligible_items.keys())
        num_instances = len(sorted_items)

        # Build annotation matrix
        matrix = np.full((num_instances, num_annotators), -1, dtype=int)
        for i, iid in enumerate(sorted_items):
            for uid, val in eligible_items[iid].items():
                j = annotator_to_idx[uid]
                str_val = str(val)
                if str_val in value_to_idx:
                    matrix[i, j] = value_to_idx[str_val]

        # Run MACE
        mace = MACEAlgorithm(
            num_annotators=num_annotators,
            num_labels=num_labels,
            num_instances=num_instances,
            alpha=self.mace_config.alpha,
            beta=self.mace_config.beta,
            num_restarts=self.mace_config.num_restarts,
            num_iters=self.mace_config.num_iters,
            seed=42,
        )

        predicted_indices, competence, marginals, log_lik = mace.fit(matrix)
        entropies = MACEAlgorithm.entropy(marginals)

        # Map results back to original IDs
        competence_scores = {
            sorted_annotators[j]: float(competence[j])
            for j in range(num_annotators)
        }
        predicted_labels = {
            sorted_items[i]: idx_to_value[int(predicted_indices[i])]
            for i in range(num_instances)
        }
        label_entropy = {
            sorted_items[i]: float(entropies[i])
            for i in range(num_instances)
        }

        return MACEResult(
            schema_name=schema_name,
            competence_scores=competence_scores,
            predicted_labels=predicted_labels,
            label_entropy=label_entropy,
            label_mapping={int(k): v for k, v in idx_to_value.items()},
            num_annotators=num_annotators,
            num_instances=num_instances,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            log_likelihood=float(log_lik),
            option_name=binary_option,
        )

    def _extract_annotation(
        self, label_dict, schema_name: str, schema_type: str,
        binary_option: Optional[str] = None
    ) -> Optional[str]:
        """Extract a single annotation value from a label dictionary.

        Args:
            label_dict: Dict mapping Label objects to values for one instance+user
            schema_name: Target schema name
            schema_type: Annotation type (radio, likert, select, multiselect)
            binary_option: For multiselect, the specific option name

        Returns:
            The annotation value as a string, or None if not found.
        """
        # Known falsy values that indicate "not selected"
        _FALSY = (False, "false", "False", 0, "0", "", None)

        if schema_type == "multiselect" and binary_option:
            # Look for the specific option's Label
            for label, value in label_dict.items():
                if (label.get_schema() == schema_name
                        and label.get_name() == binary_option):
                    # Convert to binary: "1" for checked, "0" for unchecked
                    if value not in _FALSY:
                        return "1"
                    return "0"
            return None
        else:
            # Radio/likert/select: find the label with a truthy (non-falsy) value.
            # The value may be True, "true", or the label name itself (e.g. "positive").
            for label, value in label_dict.items():
                if label.get_schema() != schema_name:
                    continue
                if value not in _FALSY:
                    return label.get_name()
            return None

    def get_competence(self, user_id: str) -> Dict[str, float]:
        """Get competence scores for a user across all schemas.

        Args:
            user_id: The user/annotator ID.

        Returns:
            Dict mapping schema (or schema::option) keys to competence scores.
        """
        scores = {}
        with self._lock:
            for key, result in self.results.items():
                if user_id in result.competence_scores:
                    scores[key] = result.competence_scores[user_id]
        return scores

    def get_prediction(self, instance_id: str, schema: str) -> Optional[str]:
        """Get MACE predicted label for an instance and schema.

        Args:
            instance_id: The instance/item ID.
            schema: The schema name.

        Returns:
            Predicted label string, or None if no prediction available.
        """
        with self._lock:
            result = self.results.get(schema)
            if result and instance_id in result.predicted_labels:
                return result.predicted_labels[instance_id]
        return None

    def get_results_summary(self) -> dict:
        """Get a summary of all MACE results for the admin API.

        Returns:
            Dict with schema results, overall stats, and per-user competence.
        """
        with self._lock:
            if not self.results:
                return {
                    "enabled": self.mace_config.enabled,
                    "has_results": False,
                    "schemas": [],
                    "annotator_competence": {},
                }

            schemas = []
            all_competence = {}

            for key, result in self.results.items():
                schemas.append({
                    "key": key,
                    "schema_name": result.schema_name,
                    "option_name": result.option_name,
                    "num_annotators": result.num_annotators,
                    "num_instances": result.num_instances,
                    "log_likelihood": result.log_likelihood,
                    "timestamp": result.timestamp,
                    "label_mapping": result.label_mapping,
                })

                # Aggregate competence across schemas
                for uid, score in result.competence_scores.items():
                    if uid not in all_competence:
                        all_competence[uid] = {}
                    all_competence[uid][key] = score

            # Compute average competence per annotator
            annotator_competence = {}
            for uid, schema_scores in all_competence.items():
                scores = list(schema_scores.values())
                annotator_competence[uid] = {
                    "scores": schema_scores,
                    "average": sum(scores) / len(scores) if scores else 0.0,
                }

            return {
                "enabled": self.mace_config.enabled,
                "has_results": True,
                "schemas": schemas,
                "annotator_competence": annotator_competence,
                "config": {
                    "trigger_every_n": self.mace_config.trigger_every_n,
                    "min_annotations_per_item": self.mace_config.min_annotations_per_item,
                    "min_items": self.mace_config.min_items,
                    "num_restarts": self.mace_config.num_restarts,
                    "num_iters": self.mace_config.num_iters,
                },
            }

    def get_predictions_for_schema(
        self, schema: str, instance_id: Optional[str] = None
    ) -> dict:
        """Get predictions with optional filtering.

        Args:
            schema: Schema name to get predictions for.
            instance_id: Optional specific instance to get.

        Returns:
            Dict with predictions and entropy data.
        """
        with self._lock:
            result = self.results.get(schema)
            if not result:
                return {"error": f"No MACE results for schema '{schema}'"}

            if instance_id:
                pred = result.predicted_labels.get(instance_id)
                ent = result.label_entropy.get(instance_id)
                if pred is None:
                    return {"error": f"No prediction for instance '{instance_id}'"}
                return {
                    "instance_id": instance_id,
                    "predicted_label": pred,
                    "entropy": ent,
                    "label_mapping": result.label_mapping,
                }

            return {
                "schema_name": result.schema_name,
                "option_name": result.option_name,
                "predicted_labels": result.predicted_labels,
                "label_entropy": result.label_entropy,
                "label_mapping": result.label_mapping,
                "num_instances": result.num_instances,
            }

    def count_total_annotations(self, _usm=None) -> int:
        """Count total annotations across all users.

        Args:
            _usm: Optional UserStateManager override (for testing).

        Returns:
            Total number of annotated instances across all users.
        """
        if _usm is None:
            from potato.user_state_management import get_user_state_manager
            _usm = get_user_state_manager()

        usm = _usm
        total = 0
        for user_id in usm.get_user_ids():
            user_state = usm.get_user_state(user_id)
            if user_state:
                total += len(user_state.instance_id_to_label_to_value)
        return total

    def _save_cache(self):
        """Save current results to disk."""
        try:
            os.makedirs(self._output_dir, exist_ok=True)
            cache_path = os.path.join(self._output_dir, "mace_results.json")
            with self._lock:
                data = {key: result.to_dict() for key, result in self.results.items()}
            with open(cache_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"MACE results saved to {cache_path}")
        except Exception as e:
            logger.error(f"Failed to save MACE cache: {e}")

    def _load_cache(self):
        """Load cached results from disk if available."""
        cache_path = os.path.join(self._output_dir, "mace_results.json")
        if not os.path.exists(cache_path):
            return

        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
            for key, result_dict in data.items():
                self.results[key] = MACEResult.from_dict(result_dict)
            logger.info(f"Loaded {len(self.results)} cached MACE results")
        except Exception as e:
            logger.warning(f"Failed to load MACE cache: {e}")


# ============================================================================
# Singleton management
# ============================================================================

_MACE_MANAGER: Optional[MACEManager] = None
_MACE_LOCK = threading.Lock()


def init_mace_manager(config: dict) -> Optional[MACEManager]:
    """Initialize the MACE manager singleton.

    Args:
        config: Full Potato configuration dictionary.

    Returns:
        MACEManager instance, or None if not enabled.
    """
    global _MACE_MANAGER
    with _MACE_LOCK:
        if _MACE_MANAGER is None:
            mace_config = config.get("mace", {})
            if mace_config.get("enabled", False):
                _MACE_MANAGER = MACEManager(config)
                logger.info("MACE manager initialized")
            else:
                logger.debug("MACE not enabled in config")
    return _MACE_MANAGER


def get_mace_manager() -> Optional[MACEManager]:
    """Get the MACE manager singleton.

    Returns:
        MACEManager instance, or None if not initialized.
    """
    return _MACE_MANAGER


def clear_mace_manager():
    """Clear the MACE manager singleton (for testing)."""
    global _MACE_MANAGER
    with _MACE_LOCK:
        _MACE_MANAGER = None

"""
Edge Case Rule Discovery for Solo Mode

Implements Co-DETECT-inspired edge case rule discovery from real data during
annotation. When the LLM labels an instance with low confidence, it extracts
a generalizable edge case rule ("When <condition> -> <action>"). These rules
are clustered, aggregated into categories, reviewed by the human, and injected
back into the annotation guidelines.

Reference: Co-DETECT (EMNLP 2025 Demo) - https://aclanthology.org/2025.emnlp-demos.25.pdf
"""

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class EdgeCaseRule:
    """A rule discovered from real data during annotation.

    Extracted when the LLM labels an instance with low confidence.
    Format: "When <condition> -> <action>"
    """
    id: str
    instance_id: str
    rule_text: str  # Full rule: "When <condition> -> <action>"
    condition: str  # The <condition> part
    action: str     # The <action> part

    # Source context
    source_confidence: float
    source_label: Any
    prompt_version: int
    model_name: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    # Clustering (filled during Phase 2)
    cluster_id: Optional[int] = None
    embedding: Optional[List[float]] = None

    # Review (filled during Phase 3)
    reviewed: bool = False
    approved: Optional[bool] = None
    reviewer_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'id': self.id,
            'instance_id': self.instance_id,
            'rule_text': self.rule_text,
            'condition': self.condition,
            'action': self.action,
            'source_confidence': self.source_confidence,
            'source_label': self.source_label,
            'prompt_version': self.prompt_version,
            'model_name': self.model_name,
            'created_at': self.created_at.isoformat(),
            'cluster_id': self.cluster_id,
            'reviewed': self.reviewed,
            'approved': self.approved,
            'reviewer_notes': self.reviewer_notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EdgeCaseRule':
        """Deserialize from dictionary."""
        return cls(
            id=data['id'],
            instance_id=data['instance_id'],
            rule_text=data['rule_text'],
            condition=data['condition'],
            action=data['action'],
            source_confidence=data['source_confidence'],
            source_label=data.get('source_label'),
            prompt_version=data.get('prompt_version', 0),
            model_name=data.get('model_name', ''),
            created_at=datetime.fromisoformat(data['created_at']),
            cluster_id=data.get('cluster_id'),
            reviewed=data.get('reviewed', False),
            approved=data.get('approved'),
            reviewer_notes=data.get('reviewer_notes', ''),
        )


@dataclass
class EdgeCaseCategory:
    """An aggregated group of similar edge case rules.

    Created by clustering individual rules and synthesizing a summary.
    """
    id: str
    summary_rule: str  # Aggregated summary rule for the cluster
    member_rule_ids: List[str] = field(default_factory=list)

    # Review status
    reviewed: bool = False
    approved: Optional[bool] = None
    reviewer_notes: str = ""
    incorporated_into_prompt_version: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'id': self.id,
            'summary_rule': self.summary_rule,
            'member_rule_ids': self.member_rule_ids,
            'reviewed': self.reviewed,
            'approved': self.approved,
            'reviewer_notes': self.reviewer_notes,
            'incorporated_into_prompt_version': self.incorporated_into_prompt_version,
            'created_at': self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EdgeCaseCategory':
        """Deserialize from dictionary."""
        return cls(
            id=data['id'],
            summary_rule=data['summary_rule'],
            member_rule_ids=data.get('member_rule_ids', []),
            reviewed=data.get('reviewed', False),
            approved=data.get('approved'),
            reviewer_notes=data.get('reviewer_notes', ''),
            incorporated_into_prompt_version=data.get('incorporated_into_prompt_version'),
            created_at=datetime.fromisoformat(data['created_at']),
        )


class EdgeCaseRuleManager:
    """Manages edge case rule storage, retrieval, and lifecycle.

    Thread-safe manager that handles:
    - Recording new rules from LLM labeling
    - Retrieving rules by status (unclustered, pending review, approved)
    - Approving/rejecting categories
    - Formatting approved rules for prompt injection
    - Persistence to disk
    """

    def __init__(self, state_dir: Optional[str] = None):
        """Initialize the rule manager.

        Args:
            state_dir: Directory for persistent storage
        """
        self._lock = threading.RLock()
        self._rules: Dict[str, EdgeCaseRule] = {}  # id -> rule
        self._categories: Dict[str, EdgeCaseCategory] = {}  # id -> category
        self.state_dir = state_dir
        self._state_file = 'edge_case_rules.json'

    def record_rule_from_labeling(
        self,
        instance_id: str,
        rule_text: str,
        condition: str,
        action: str,
        confidence: float,
        label: Any,
        prompt_version: int,
        model_name: str = "",
    ) -> EdgeCaseRule:
        """Record a new edge case rule discovered during labeling.

        Args:
            instance_id: ID of the instance that triggered rule extraction
            rule_text: Full rule text: "When <condition> -> <action>"
            condition: The condition part of the rule
            action: The action part of the rule
            confidence: LLM confidence when labeling this instance
            label: The label assigned by the LLM
            prompt_version: Version of the prompt used
            model_name: Name of the model that produced the rule

        Returns:
            The created EdgeCaseRule
        """
        with self._lock:
            rule_id = f"rule_{uuid.uuid4().hex[:8]}"
            rule = EdgeCaseRule(
                id=rule_id,
                instance_id=instance_id,
                rule_text=rule_text,
                condition=condition,
                action=action,
                source_confidence=confidence,
                source_label=label,
                prompt_version=prompt_version,
                model_name=model_name,
            )
            self._rules[rule_id] = rule
            self._save_state()
            logger.info(
                f"Recorded edge case rule {rule_id} from instance {instance_id} "
                f"(confidence={confidence:.2f})"
            )
            return rule

    def get_rule(self, rule_id: str) -> Optional[EdgeCaseRule]:
        """Get a rule by ID."""
        with self._lock:
            return self._rules.get(rule_id)

    def get_all_rules(self) -> List[EdgeCaseRule]:
        """Get all rules."""
        with self._lock:
            return list(self._rules.values())

    def get_rule_instance_ids(self) -> Set[str]:
        """Get instance IDs that have edge case rules."""
        with self._lock:
            return {rule.instance_id for rule in self._rules.values()}

    def get_unclustered_rules(self) -> List[EdgeCaseRule]:
        """Get rules that haven't been assigned to a cluster."""
        with self._lock:
            return [r for r in self._rules.values() if r.cluster_id is None]

    def get_rules_for_cluster(self, cluster_id: int) -> List[EdgeCaseRule]:
        """Get all rules in a specific cluster."""
        with self._lock:
            return [r for r in self._rules.values() if r.cluster_id == cluster_id]

    def set_rule_cluster(self, rule_id: str, cluster_id: int) -> None:
        """Assign a rule to a cluster."""
        with self._lock:
            if rule_id in self._rules:
                self._rules[rule_id].cluster_id = cluster_id

    def add_category(self, category: EdgeCaseCategory) -> None:
        """Add an aggregated category."""
        with self._lock:
            self._categories[category.id] = category
            self._save_state()

    def get_category(self, category_id: str) -> Optional[EdgeCaseCategory]:
        """Get a category by ID."""
        with self._lock:
            return self._categories.get(category_id)

    def get_category_for_rule(self, rule_id: str) -> Optional[EdgeCaseCategory]:
        """Get the category that contains a given rule."""
        with self._lock:
            for cat in self._categories.values():
                if rule_id in cat.member_rule_ids:
                    return cat
            return None

    def get_all_categories(self) -> List[EdgeCaseCategory]:
        """Get all categories."""
        with self._lock:
            return list(self._categories.values())

    def get_pending_categories(self) -> List[EdgeCaseCategory]:
        """Get categories that haven't been reviewed yet."""
        with self._lock:
            return [c for c in self._categories.values() if not c.reviewed]

    def get_approved_categories(self) -> List[EdgeCaseCategory]:
        """Get categories that have been approved."""
        with self._lock:
            return [
                c for c in self._categories.values()
                if c.reviewed and c.approved
            ]

    def get_rejected_categories(self) -> List[EdgeCaseCategory]:
        """Get categories that have been rejected."""
        with self._lock:
            return [
                c for c in self._categories.values()
                if c.reviewed and not c.approved
            ]

    def approve_category(
        self,
        category_id: str,
        notes: str = ""
    ) -> bool:
        """Approve a category for prompt injection.

        Args:
            category_id: ID of the category to approve
            notes: Optional reviewer notes

        Returns:
            True if category was found and approved
        """
        with self._lock:
            category = self._categories.get(category_id)
            if category is None:
                return False
            category.reviewed = True
            category.approved = True
            category.reviewer_notes = notes
            self._save_state()
            logger.info(f"Approved edge case category {category_id}")
            return True

    def reject_category(
        self,
        category_id: str,
        notes: str = ""
    ) -> bool:
        """Reject a category.

        Args:
            category_id: ID of the category to reject
            notes: Optional reviewer notes

        Returns:
            True if category was found and rejected
        """
        with self._lock:
            category = self._categories.get(category_id)
            if category is None:
                return False
            category.reviewed = True
            category.approved = False
            category.reviewer_notes = notes
            self._save_state()
            logger.info(f"Rejected edge case category {category_id}")
            return True

    def mark_category_incorporated(
        self,
        category_id: str,
        prompt_version: int
    ) -> None:
        """Mark a category as incorporated into a prompt version."""
        with self._lock:
            category = self._categories.get(category_id)
            if category:
                category.incorporated_into_prompt_version = prompt_version
                self._save_state()

    def get_rules_for_prompt_injection(self) -> str:
        """Get approved rules formatted for prompt injection.

        Returns:
            Formatted string of approved edge case guidelines
        """
        with self._lock:
            approved = self.get_approved_categories()
            if not approved:
                return ""

            # Filter to only categories not yet incorporated
            unincorporated = [
                c for c in approved
                if c.incorporated_into_prompt_version is None
            ]
            if not unincorporated:
                return ""

            lines = ["## Edge Case Guidelines", ""]
            for i, category in enumerate(unincorporated, 1):
                lines.append(f"{i}. {category.summary_rule}")
            lines.append("")

            return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about rules and categories."""
        with self._lock:
            return {
                'total_rules': len(self._rules),
                'unclustered_rules': len(self.get_unclustered_rules()),
                'total_categories': len(self._categories),
                'pending_categories': len(self.get_pending_categories()),
                'approved_categories': len(self.get_approved_categories()),
                'rejected_categories': len(self.get_rejected_categories()),
            }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize full state to dictionary."""
        with self._lock:
            return {
                'rules': {
                    rid: rule.to_dict()
                    for rid, rule in self._rules.items()
                },
                'categories': {
                    cid: cat.to_dict()
                    for cid, cat in self._categories.items()
                },
            }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        state_dir: Optional[str] = None
    ) -> 'EdgeCaseRuleManager':
        """Deserialize from dictionary."""
        manager = cls(state_dir=state_dir)
        for rid, rule_data in data.get('rules', {}).items():
            manager._rules[rid] = EdgeCaseRule.from_dict(rule_data)
        for cid, cat_data in data.get('categories', {}).items():
            manager._categories[cid] = EdgeCaseCategory.from_dict(cat_data)
        return manager

    def _save_state(self) -> None:
        """Save state to disk."""
        if not self.state_dir:
            return

        try:
            os.makedirs(self.state_dir, exist_ok=True)
            filepath = os.path.join(self.state_dir, self._state_file)
            temp_path = filepath + '.tmp'
            with open(temp_path, 'w') as f:
                json.dump(self.to_dict(), f, indent=2)
            os.replace(temp_path, filepath)
        except Exception as e:
            logger.error(f"Error saving edge case rules state: {e}")

    def load_state(self) -> bool:
        """Load state from disk.

        Returns:
            True if state was loaded
        """
        if not self.state_dir:
            return False

        filepath = os.path.join(self.state_dir, self._state_file)
        if not os.path.exists(filepath):
            return False

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            with self._lock:
                for rid, rule_data in data.get('rules', {}).items():
                    self._rules[rid] = EdgeCaseRule.from_dict(rule_data)
                for cid, cat_data in data.get('categories', {}).items():
                    self._categories[cid] = EdgeCaseCategory.from_dict(cat_data)
            logger.info(
                f"Loaded edge case rules state: "
                f"{len(self._rules)} rules, {len(self._categories)} categories"
            )
            return True
        except Exception as e:
            logger.error(f"Error loading edge case rules state: {e}")
            return False

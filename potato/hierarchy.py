"""
Hierarchical Annotation Framework

Provides a general framework for managing parent-child relationships between
annotations. This is a type-agnostic system that works with any annotation type
(temporal segments, text spans, image regions, etc.).

The framework consists of:
- ConstraintType: Rules for how children relate to parents
- TierDefinition: Definition of an annotation tier
- HierarchyDefinition: Complete hierarchy configuration
- HierarchyManager: Validates constraints and manages relationships

This module supports ELAN-style tiered annotation as the primary use case,
but the design is general enough to extend to other hierarchical annotation
scenarios (discourse > paragraph > sentence, scene > object > part, etc.).
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Any, Set, Tuple

logger = logging.getLogger(__name__)


class ConstraintType(Enum):
    """
    Defines how child annotations relate to their parent annotations.

    These constraint types follow ELAN's linguistic type stereotypes:
    - TIME_SUBDIVISION: Children partition the parent's time span with no gaps
    - INCLUDED_IN: Children are within parent bounds but may have gaps
    - SYMBOLIC_ASSOCIATION: Children linked to parent without own time alignment
    - SYMBOLIC_SUBDIVISION: Children subdivide parent symbolically (no time)
    - NONE: No constraints (independent tier)
    """
    TIME_SUBDIVISION = "time_subdivision"
    INCLUDED_IN = "included_in"
    SYMBOLIC_ASSOCIATION = "symbolic_association"
    SYMBOLIC_SUBDIVISION = "symbolic_subdivision"
    NONE = "none"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "ConstraintType":
        """Convert a string value to ConstraintType, defaulting to NONE."""
        if value is None:
            return cls.NONE
        try:
            return cls(value.lower())
        except ValueError:
            logger.warning(f"Unknown constraint type '{value}', defaulting to NONE")
            return cls.NONE


@dataclass
class TierDefinition:
    """
    Definition of an annotation tier.

    Attributes:
        name: Unique identifier for this tier
        tier_type: "independent" (time-aligned) or "dependent" (references parent)
        parent_tier: Name of parent tier (required if tier_type is "dependent")
        constraint_type: How child annotations relate to parent
        description: Human-readable description
        labels: List of label definitions (name, color, tooltip, etc.)
        linguistic_type: ELAN linguistic type name (for EAF export)
    """
    name: str
    tier_type: str = "independent"  # "independent" | "dependent"
    parent_tier: Optional[str] = None
    constraint_type: ConstraintType = ConstraintType.NONE
    description: str = ""
    labels: List[Dict[str, Any]] = field(default_factory=list)
    linguistic_type: Optional[str] = None

    def __post_init__(self):
        """Normalize and validate tier definition."""
        # Normalize tier_type
        self.tier_type = self.tier_type.lower() if self.tier_type else "independent"
        if self.tier_type not in ("independent", "dependent"):
            logger.warning(f"Invalid tier_type '{self.tier_type}', defaulting to 'independent'")
            self.tier_type = "independent"

        # Convert constraint_type if it's a string
        if isinstance(self.constraint_type, str):
            self.constraint_type = ConstraintType.from_string(self.constraint_type)

        # Dependent tiers should have a constraint type
        if self.tier_type == "dependent" and self.constraint_type == ConstraintType.NONE:
            self.constraint_type = ConstraintType.INCLUDED_IN
            logger.debug(f"Tier '{self.name}' is dependent but has no constraint, defaulting to INCLUDED_IN")

    @property
    def is_independent(self) -> bool:
        """Check if this is an independent (time-aligned) tier."""
        return self.tier_type == "independent"

    @property
    def is_dependent(self) -> bool:
        """Check if this is a dependent tier (references parent)."""
        return self.tier_type == "dependent"

    @property
    def is_time_aligned(self) -> bool:
        """Check if annotations on this tier have their own time alignment."""
        if self.is_independent:
            return True
        return self.constraint_type in (
            ConstraintType.TIME_SUBDIVISION,
            ConstraintType.INCLUDED_IN
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TierDefinition":
        """Create a TierDefinition from a configuration dictionary."""
        return cls(
            name=data.get("name", ""),
            tier_type=data.get("tier_type", "independent"),
            parent_tier=data.get("parent_tier"),
            constraint_type=ConstraintType.from_string(data.get("constraint_type")),
            description=data.get("description", ""),
            labels=data.get("labels", []),
            linguistic_type=data.get("linguistic_type"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for serialization."""
        result = {
            "name": self.name,
            "tier_type": self.tier_type,
            "description": self.description,
            "labels": self.labels,
        }
        if self.parent_tier:
            result["parent_tier"] = self.parent_tier
        if self.constraint_type != ConstraintType.NONE:
            result["constraint_type"] = self.constraint_type.value
        if self.linguistic_type:
            result["linguistic_type"] = self.linguistic_type
        return result


@dataclass
class HierarchyDefinition:
    """
    Complete hierarchy configuration defining all tiers and their relationships.

    Attributes:
        tiers: Ordered list of tier definitions (order = display order)
    """
    tiers: List[TierDefinition] = field(default_factory=list)

    def __post_init__(self):
        """Convert dict tiers to TierDefinition objects."""
        converted = []
        for tier in self.tiers:
            if isinstance(tier, dict):
                converted.append(TierDefinition.from_dict(tier))
            elif isinstance(tier, TierDefinition):
                converted.append(tier)
            else:
                raise ValueError(f"Invalid tier type: {type(tier)}")
        self.tiers = converted

    def get_tier(self, name: str) -> Optional[TierDefinition]:
        """Get a tier definition by name."""
        for tier in self.tiers:
            if tier.name == name:
                return tier
        return None

    def get_tier_index(self, name: str) -> int:
        """Get the index of a tier by name (-1 if not found)."""
        for i, tier in enumerate(self.tiers):
            if tier.name == name:
                return i
        return -1

    def get_children(self, tier_name: str) -> List[TierDefinition]:
        """Get all tiers that have the given tier as their parent."""
        return [t for t in self.tiers if t.parent_tier == tier_name]

    def get_descendants(self, tier_name: str) -> List[TierDefinition]:
        """Get all tiers descended from the given tier (recursive)."""
        descendants = []
        for child in self.get_children(tier_name):
            descendants.append(child)
            descendants.extend(self.get_descendants(child.name))
        return descendants

    def get_ancestors(self, tier_name: str) -> List[TierDefinition]:
        """Get all ancestor tiers of the given tier (up to root)."""
        ancestors = []
        tier = self.get_tier(tier_name)
        while tier and tier.parent_tier:
            parent = self.get_tier(tier.parent_tier)
            if parent:
                ancestors.append(parent)
                tier = parent
            else:
                break
        return ancestors

    def get_root_tiers(self) -> List[TierDefinition]:
        """Get all independent (root) tiers."""
        return [t for t in self.tiers if t.is_independent]

    def get_tier_names(self) -> List[str]:
        """Get list of all tier names in display order."""
        return [t.name for t in self.tiers]

    def validate_structure(self) -> List[str]:
        """
        Validate the hierarchy structure.

        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        tier_names: Set[str] = set()

        # Check for duplicate names and build name set
        for tier in self.tiers:
            if not tier.name:
                errors.append("Tier name cannot be empty")
                continue
            if tier.name in tier_names:
                errors.append(f"Duplicate tier name: '{tier.name}'")
            tier_names.add(tier.name)

        # Validate parent references and dependent tier requirements
        for tier in self.tiers:
            if tier.is_dependent:
                if not tier.parent_tier:
                    errors.append(
                        f"Tier '{tier.name}' is dependent but has no parent_tier specified"
                    )
                elif tier.parent_tier not in tier_names:
                    errors.append(
                        f"Tier '{tier.name}' references unknown parent '{tier.parent_tier}'"
                    )
                elif tier.parent_tier == tier.name:
                    errors.append(
                        f"Tier '{tier.name}' cannot be its own parent"
                    )

        # Check for cycles
        cycle_errors = self._detect_cycles()
        errors.extend(cycle_errors)

        return errors

    def _detect_cycles(self) -> List[str]:
        """Detect cycles in the tier hierarchy using DFS."""
        errors = []
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(tier_name: str, path: List[str]) -> bool:
            """Returns True if a cycle is detected."""
            visited.add(tier_name)
            rec_stack.add(tier_name)

            tier = self.get_tier(tier_name)
            if tier and tier.parent_tier:
                if tier.parent_tier in rec_stack:
                    # Found a cycle
                    cycle_path = path + [tier_name, tier.parent_tier]
                    errors.append(
                        f"Cycle detected in tier hierarchy: {' -> '.join(cycle_path)}"
                    )
                    return True
                elif tier.parent_tier not in visited:
                    if dfs(tier.parent_tier, path + [tier_name]):
                        return True

            rec_stack.remove(tier_name)
            return False

        # Run DFS from each unvisited tier
        for tier in self.tiers:
            if tier.name not in visited:
                dfs(tier.name, [])

        return errors

    @classmethod
    def from_config(cls, tiers_config: List[Dict[str, Any]]) -> "HierarchyDefinition":
        """Create a HierarchyDefinition from a configuration list."""
        return cls(tiers=tiers_config)

    def to_config(self) -> List[Dict[str, Any]]:
        """Convert to a configuration list for serialization."""
        return [tier.to_dict() for tier in self.tiers]


@dataclass
class Annotation:
    """
    Represents a single annotation on a tier.

    Attributes:
        id: Unique identifier for this annotation
        tier: Name of the tier this annotation belongs to
        start_time: Start time in milliseconds (for time-aligned tiers)
        end_time: End time in milliseconds (for time-aligned tiers)
        label: The label/value of this annotation
        parent_id: ID of parent annotation (for dependent tiers)
        value: Optional additional text/value content
        metadata: Optional additional metadata
    """
    id: str
    tier: str
    label: str = ""
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    parent_id: Optional[str] = None
    value: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> Optional[float]:
        """Get duration in milliseconds (if time-aligned)."""
        if self.start_time is not None and self.end_time is not None:
            return self.end_time - self.start_time
        return None

    def overlaps(self, other: "Annotation") -> bool:
        """Check if this annotation overlaps with another."""
        if self.start_time is None or self.end_time is None:
            return False
        if other.start_time is None or other.end_time is None:
            return False
        return (self.start_time < other.end_time and
                self.end_time > other.start_time)

    def contains(self, other: "Annotation") -> bool:
        """Check if this annotation fully contains another."""
        if self.start_time is None or self.end_time is None:
            return False
        if other.start_time is None or other.end_time is None:
            return False
        return (self.start_time <= other.start_time and
                self.end_time >= other.end_time)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Annotation":
        """Create an Annotation from a dictionary."""
        return cls(
            id=data.get("id", ""),
            tier=data.get("tier", ""),
            label=data.get("label", ""),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            parent_id=data.get("parent_id"),
            value=data.get("value"),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for serialization."""
        result = {
            "id": self.id,
            "tier": self.tier,
            "label": self.label,
        }
        if self.start_time is not None:
            result["start_time"] = self.start_time
        if self.end_time is not None:
            result["end_time"] = self.end_time
        if self.parent_id:
            result["parent_id"] = self.parent_id
        if self.value:
            result["value"] = self.value
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class ValidationResult:
    """Result of a constraint validation check."""
    valid: bool
    error: str = ""
    warnings: List[str] = field(default_factory=list)


class HierarchyManager:
    """
    Validates and manages hierarchical annotations.

    This class is responsible for:
    - Validating that annotations satisfy tier constraints
    - Finding parent annotations for dependent tiers
    - Managing the annotation collection for a single instance
    """

    def __init__(self, definition: HierarchyDefinition):
        """
        Initialize with a hierarchy definition.

        Args:
            definition: HierarchyDefinition describing the tier structure
        """
        self.definition = definition
        self._annotations: Dict[str, List[Annotation]] = {}

        # Validate the hierarchy structure
        errors = definition.validate_structure()
        if errors:
            error_msg = "; ".join(errors)
            raise ValueError(f"Invalid hierarchy definition: {error_msg}")

        # Initialize annotation lists for each tier
        for tier in definition.tiers:
            self._annotations[tier.name] = []

    @property
    def annotations(self) -> Dict[str, List[Annotation]]:
        """Get all annotations organized by tier."""
        return self._annotations

    def get_tier_annotations(self, tier_name: str) -> List[Annotation]:
        """Get all annotations for a specific tier."""
        return self._annotations.get(tier_name, [])

    def get_annotation(self, annotation_id: str) -> Optional[Annotation]:
        """Find an annotation by ID across all tiers."""
        for annotations in self._annotations.values():
            for ann in annotations:
                if ann.id == annotation_id:
                    return ann
        return None

    def find_parent_annotation(
        self,
        tier_name: str,
        start_time: float,
        end_time: float
    ) -> Optional[Annotation]:
        """
        Find a parent annotation that contains the given time range.

        Args:
            tier_name: Name of the child tier
            start_time: Start time of proposed annotation
            end_time: End time of proposed annotation

        Returns:
            Parent annotation if found, None otherwise
        """
        tier = self.definition.get_tier(tier_name)
        if not tier or not tier.parent_tier:
            return None

        parent_annotations = self._annotations.get(tier.parent_tier, [])
        for parent in parent_annotations:
            if parent.start_time is None or parent.end_time is None:
                continue
            if parent.start_time <= start_time and parent.end_time >= end_time:
                return parent

        return None

    def find_overlapping_parent(
        self,
        tier_name: str,
        start_time: float,
        end_time: float
    ) -> Optional[Annotation]:
        """
        Find a parent annotation that overlaps the given time range.

        Useful for INCLUDED_IN constraint where child doesn't need to be
        fully contained but just overlap.

        Args:
            tier_name: Name of the child tier
            start_time: Start time of proposed annotation
            end_time: End time of proposed annotation

        Returns:
            Overlapping parent annotation if found, None otherwise
        """
        tier = self.definition.get_tier(tier_name)
        if not tier or not tier.parent_tier:
            return None

        parent_annotations = self._annotations.get(tier.parent_tier, [])
        for parent in parent_annotations:
            if parent.start_time is None or parent.end_time is None:
                continue
            if parent.start_time < end_time and parent.end_time > start_time:
                return parent

        return None

    def validate_annotation(
        self,
        tier_name: str,
        start_time: Optional[float],
        end_time: Optional[float],
        parent_annotation: Optional[Annotation] = None
    ) -> ValidationResult:
        """
        Validate that a proposed annotation satisfies tier constraints.

        Args:
            tier_name: Name of the tier for this annotation
            start_time: Start time (None for symbolic annotations)
            end_time: End time (None for symbolic annotations)
            parent_annotation: Parent annotation (for dependent tiers)

        Returns:
            ValidationResult with valid flag and any error message
        """
        tier = self.definition.get_tier(tier_name)
        if not tier:
            return ValidationResult(
                valid=False,
                error=f"Unknown tier: '{tier_name}'"
            )

        # Independent tiers have no parent constraints
        if tier.is_independent:
            return self._validate_time_range(start_time, end_time)

        # Dependent tiers require a parent
        if not parent_annotation:
            return ValidationResult(
                valid=False,
                error=f"Dependent tier '{tier_name}' requires a parent annotation"
            )

        # Validate based on constraint type
        constraint = tier.constraint_type

        if constraint == ConstraintType.TIME_SUBDIVISION:
            return self._validate_time_subdivision(
                start_time, end_time, parent_annotation
            )

        elif constraint == ConstraintType.INCLUDED_IN:
            return self._validate_included_in(
                start_time, end_time, parent_annotation
            )

        elif constraint == ConstraintType.SYMBOLIC_ASSOCIATION:
            # No time constraints - just need valid parent
            return ValidationResult(valid=True)

        elif constraint == ConstraintType.SYMBOLIC_SUBDIVISION:
            # No time constraints - just need valid parent
            return ValidationResult(valid=True)

        return ValidationResult(valid=True)

    def _validate_time_range(
        self,
        start_time: Optional[float],
        end_time: Optional[float]
    ) -> ValidationResult:
        """Validate that start/end times are valid."""
        if start_time is None or end_time is None:
            return ValidationResult(valid=True)  # Symbolic annotation

        if start_time < 0:
            return ValidationResult(
                valid=False,
                error="Start time cannot be negative"
            )

        if end_time < start_time:
            return ValidationResult(
                valid=False,
                error="End time must be >= start time"
            )

        return ValidationResult(valid=True)

    def _validate_time_subdivision(
        self,
        start_time: Optional[float],
        end_time: Optional[float],
        parent: Annotation
    ) -> ValidationResult:
        """Validate TIME_SUBDIVISION constraint."""
        if start_time is None or end_time is None:
            return ValidationResult(
                valid=False,
                error="Time subdivision requires time-aligned annotation"
            )

        if parent.start_time is None or parent.end_time is None:
            return ValidationResult(
                valid=False,
                error="Parent must be time-aligned for time subdivision"
            )

        # Child must be within parent bounds
        if start_time < parent.start_time:
            return ValidationResult(
                valid=False,
                error=f"Start time ({start_time}ms) is before parent start ({parent.start_time}ms)"
            )

        if end_time > parent.end_time:
            return ValidationResult(
                valid=False,
                error=f"End time ({end_time}ms) is after parent end ({parent.end_time}ms)"
            )

        return ValidationResult(valid=True)

    def _validate_included_in(
        self,
        start_time: Optional[float],
        end_time: Optional[float],
        parent: Annotation
    ) -> ValidationResult:
        """Validate INCLUDED_IN constraint."""
        if start_time is None or end_time is None:
            return ValidationResult(
                valid=False,
                error="Included-in requires time-aligned annotation"
            )

        if parent.start_time is None or parent.end_time is None:
            return ValidationResult(
                valid=False,
                error="Parent must be time-aligned for included-in"
            )

        # Child must be within parent bounds (same as subdivision)
        if start_time < parent.start_time or end_time > parent.end_time:
            return ValidationResult(
                valid=False,
                error="Annotation must be within parent time bounds"
            )

        return ValidationResult(valid=True)

    def add_annotation(self, annotation: Annotation) -> ValidationResult:
        """
        Add an annotation after validating it.

        Args:
            annotation: The annotation to add

        Returns:
            ValidationResult indicating success or failure
        """
        tier = self.definition.get_tier(annotation.tier)
        if not tier:
            return ValidationResult(
                valid=False,
                error=f"Unknown tier: '{annotation.tier}'"
            )

        # Find parent if needed
        parent = None
        if tier.is_dependent and annotation.parent_id:
            parent = self.get_annotation(annotation.parent_id)
            if not parent:
                return ValidationResult(
                    valid=False,
                    error=f"Parent annotation '{annotation.parent_id}' not found"
                )
        elif tier.is_dependent and annotation.start_time is not None:
            # Try to find parent by time range
            parent = self.find_parent_annotation(
                annotation.tier,
                annotation.start_time,
                annotation.end_time or annotation.start_time
            )
            if parent:
                annotation.parent_id = parent.id

        # Validate the annotation
        result = self.validate_annotation(
            annotation.tier,
            annotation.start_time,
            annotation.end_time,
            parent
        )

        if not result.valid:
            return result

        # Add to the appropriate tier
        self._annotations[annotation.tier].append(annotation)
        return ValidationResult(valid=True)

    def remove_annotation(
        self,
        annotation_id: str,
        cascade: bool = True
    ) -> Tuple[bool, List[str]]:
        """
        Remove an annotation and optionally its dependents.

        Args:
            annotation_id: ID of annotation to remove
            cascade: If True, also remove child annotations

        Returns:
            Tuple of (success, list of removed annotation IDs)
        """
        annotation = self.get_annotation(annotation_id)
        if not annotation:
            return False, []

        removed_ids = [annotation_id]

        # Remove from its tier
        tier_annotations = self._annotations.get(annotation.tier, [])
        self._annotations[annotation.tier] = [
            a for a in tier_annotations if a.id != annotation_id
        ]

        # Cascade delete children if requested
        if cascade:
            tier = self.definition.get_tier(annotation.tier)
            if tier:
                for child_tier in self.definition.get_children(tier.name):
                    child_annotations = self._annotations.get(child_tier.name, [])
                    for child in child_annotations[:]:  # Copy to allow modification
                        if child.parent_id == annotation_id:
                            _, child_removed = self.remove_annotation(
                                child.id, cascade=True
                            )
                            removed_ids.extend(child_removed)

        return True, removed_ids

    def clear(self) -> None:
        """Clear all annotations."""
        for tier_name in self._annotations:
            self._annotations[tier_name] = []

    def load_annotations(
        self,
        annotations_data: Dict[str, List[Dict[str, Any]]]
    ) -> List[str]:
        """
        Load annotations from serialized data.

        Args:
            annotations_data: Dict mapping tier names to list of annotation dicts

        Returns:
            List of error messages (empty if successful)
        """
        errors = []
        self.clear()

        # Load in tier order to ensure parents exist before children
        for tier in self.definition.tiers:
            tier_data = annotations_data.get(tier.name, [])
            for ann_data in tier_data:
                annotation = Annotation.from_dict(ann_data)
                annotation.tier = tier.name  # Ensure tier is set
                result = self.add_annotation(annotation)
                if not result.valid:
                    errors.append(f"Tier '{tier.name}': {result.error}")

        return errors

    def serialize(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Serialize all annotations for storage.

        Returns:
            Dict mapping tier names to list of annotation dicts
        """
        return {
            tier_name: [ann.to_dict() for ann in annotations]
            for tier_name, annotations in self._annotations.items()
        }

    def generate_time_slots(self) -> Dict[str, int]:
        """
        Generate ELAN-style time slots from all annotations.

        Returns:
            Dict mapping slot ID to time in milliseconds
        """
        times: Set[int] = set()

        for annotations in self._annotations.values():
            for ann in annotations:
                if ann.start_time is not None:
                    times.add(int(ann.start_time))
                if ann.end_time is not None:
                    times.add(int(ann.end_time))

        # Generate slot IDs in chronological order
        return {
            f"ts{i+1}": time
            for i, time in enumerate(sorted(times))
        }

    def get_time_slot_id(
        self,
        time_ms: int,
        time_slots: Dict[str, int]
    ) -> Optional[str]:
        """Find the time slot ID for a given time value."""
        for slot_id, slot_time in time_slots.items():
            if slot_time == time_ms:
                return slot_id
        return None

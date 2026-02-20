"""
Unit tests for the hierarchical annotation framework.

Tests the core hierarchy module including TierDefinition, HierarchyDefinition,
and HierarchyManager classes.
"""

import pytest
from potato.hierarchy import (
    ConstraintType,
    TierDefinition,
    HierarchyDefinition,
    HierarchyManager,
    Annotation,
    ValidationResult,
)


class TestConstraintType:
    """Tests for ConstraintType enum."""

    def test_from_string_valid(self):
        """Test valid constraint type string conversion."""
        assert ConstraintType.from_string("time_subdivision") == ConstraintType.TIME_SUBDIVISION
        assert ConstraintType.from_string("included_in") == ConstraintType.INCLUDED_IN
        assert ConstraintType.from_string("symbolic_association") == ConstraintType.SYMBOLIC_ASSOCIATION
        assert ConstraintType.from_string("symbolic_subdivision") == ConstraintType.SYMBOLIC_SUBDIVISION
        assert ConstraintType.from_string("none") == ConstraintType.NONE

    def test_from_string_case_insensitive(self):
        """Test case-insensitive string conversion."""
        assert ConstraintType.from_string("TIME_SUBDIVISION") == ConstraintType.TIME_SUBDIVISION
        assert ConstraintType.from_string("Included_In") == ConstraintType.INCLUDED_IN

    def test_from_string_invalid(self):
        """Test invalid string defaults to NONE."""
        assert ConstraintType.from_string("invalid") == ConstraintType.NONE
        assert ConstraintType.from_string("") == ConstraintType.NONE

    def test_from_string_none(self):
        """Test None input returns NONE."""
        assert ConstraintType.from_string(None) == ConstraintType.NONE


class TestTierDefinition:
    """Tests for TierDefinition dataclass."""

    def test_basic_creation(self):
        """Test basic tier creation."""
        tier = TierDefinition(name="test_tier")
        assert tier.name == "test_tier"
        assert tier.tier_type == "independent"
        assert tier.parent_tier is None
        assert tier.constraint_type == ConstraintType.NONE

    def test_dependent_tier(self):
        """Test dependent tier creation."""
        tier = TierDefinition(
            name="child",
            tier_type="dependent",
            parent_tier="parent",
            constraint_type=ConstraintType.TIME_SUBDIVISION
        )
        assert tier.tier_type == "dependent"
        assert tier.parent_tier == "parent"
        assert tier.is_dependent
        assert not tier.is_independent

    def test_is_time_aligned(self):
        """Test time alignment detection."""
        independent = TierDefinition(name="ind")
        assert independent.is_time_aligned

        subdivision = TierDefinition(
            name="sub",
            tier_type="dependent",
            parent_tier="parent",
            constraint_type=ConstraintType.TIME_SUBDIVISION
        )
        assert subdivision.is_time_aligned

        symbolic = TierDefinition(
            name="sym",
            tier_type="dependent",
            parent_tier="parent",
            constraint_type=ConstraintType.SYMBOLIC_ASSOCIATION
        )
        assert not symbolic.is_time_aligned

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "name": "word",
            "tier_type": "dependent",
            "parent_tier": "utterance",
            "constraint_type": "time_subdivision",
            "description": "Word-level annotation",
            "labels": [{"name": "Word", "color": "#FF0000"}],
        }
        tier = TierDefinition.from_dict(data)
        assert tier.name == "word"
        assert tier.tier_type == "dependent"
        assert tier.parent_tier == "utterance"
        assert tier.constraint_type == ConstraintType.TIME_SUBDIVISION
        assert tier.description == "Word-level annotation"
        assert len(tier.labels) == 1

    def test_to_dict(self):
        """Test serialization to dictionary."""
        tier = TierDefinition(
            name="test",
            tier_type="dependent",
            parent_tier="parent",
            constraint_type=ConstraintType.INCLUDED_IN,
            description="Test tier",
            labels=[{"name": "Label"}],
        )
        data = tier.to_dict()
        assert data["name"] == "test"
        assert data["tier_type"] == "dependent"
        assert data["parent_tier"] == "parent"
        assert data["constraint_type"] == "included_in"

    def test_dependent_tier_defaults_to_included_in(self):
        """Test that dependent tier without constraint defaults to INCLUDED_IN."""
        tier = TierDefinition(
            name="child",
            tier_type="dependent",
            parent_tier="parent"
        )
        assert tier.constraint_type == ConstraintType.INCLUDED_IN


class TestHierarchyDefinition:
    """Tests for HierarchyDefinition."""

    def test_basic_creation(self):
        """Test basic hierarchy creation."""
        tiers = [
            {"name": "utterance", "tier_type": "independent"},
            {"name": "word", "tier_type": "dependent", "parent_tier": "utterance"},
        ]
        hierarchy = HierarchyDefinition(tiers=tiers)
        assert len(hierarchy.tiers) == 2
        assert isinstance(hierarchy.tiers[0], TierDefinition)

    def test_get_tier(self):
        """Test getting tier by name."""
        hierarchy = HierarchyDefinition(tiers=[
            {"name": "tier1"},
            {"name": "tier2"},
        ])
        assert hierarchy.get_tier("tier1") is not None
        assert hierarchy.get_tier("tier1").name == "tier1"
        assert hierarchy.get_tier("nonexistent") is None

    def test_get_children(self):
        """Test getting child tiers."""
        hierarchy = HierarchyDefinition(tiers=[
            {"name": "parent", "tier_type": "independent"},
            {"name": "child1", "tier_type": "dependent", "parent_tier": "parent"},
            {"name": "child2", "tier_type": "dependent", "parent_tier": "parent"},
            {"name": "other", "tier_type": "independent"},
        ])
        children = hierarchy.get_children("parent")
        assert len(children) == 2
        assert all(c.parent_tier == "parent" for c in children)

    def test_get_root_tiers(self):
        """Test getting independent (root) tiers."""
        hierarchy = HierarchyDefinition(tiers=[
            {"name": "root1", "tier_type": "independent"},
            {"name": "child", "tier_type": "dependent", "parent_tier": "root1"},
            {"name": "root2", "tier_type": "independent"},
        ])
        roots = hierarchy.get_root_tiers()
        assert len(roots) == 2
        assert all(r.is_independent for r in roots)

    def test_validate_structure_valid(self):
        """Test validation of valid hierarchy."""
        hierarchy = HierarchyDefinition(tiers=[
            {"name": "utterance", "tier_type": "independent"},
            {"name": "word", "tier_type": "dependent", "parent_tier": "utterance"},
            {"name": "phoneme", "tier_type": "dependent", "parent_tier": "word"},
        ])
        errors = hierarchy.validate_structure()
        assert len(errors) == 0

    def test_validate_structure_duplicate_names(self):
        """Test validation catches duplicate tier names."""
        hierarchy = HierarchyDefinition(tiers=[
            {"name": "tier1"},
            {"name": "tier1"},  # Duplicate
        ])
        errors = hierarchy.validate_structure()
        assert any("Duplicate" in e for e in errors)

    def test_validate_structure_missing_parent(self):
        """Test validation catches missing parent reference."""
        hierarchy = HierarchyDefinition(tiers=[
            {"name": "child", "tier_type": "dependent", "parent_tier": "nonexistent"},
        ])
        errors = hierarchy.validate_structure()
        assert any("unknown parent" in e for e in errors)

    def test_validate_structure_dependent_without_parent(self):
        """Test validation catches dependent tier without parent."""
        tier = TierDefinition(name="orphan", tier_type="dependent")
        # Force parent_tier to None (bypassing __post_init__)
        tier.parent_tier = None
        hierarchy = HierarchyDefinition(tiers=[tier])
        errors = hierarchy.validate_structure()
        assert any("no parent_tier" in e for e in errors)

    def test_validate_structure_self_reference(self):
        """Test validation catches self-referencing tier."""
        hierarchy = HierarchyDefinition(tiers=[
            {"name": "loop", "tier_type": "dependent", "parent_tier": "loop"},
        ])
        errors = hierarchy.validate_structure()
        assert any("own parent" in e for e in errors)

    def test_from_config(self):
        """Test creation from config list."""
        config = [
            {"name": "tier1"},
            {"name": "tier2"},
        ]
        hierarchy = HierarchyDefinition.from_config(config)
        assert len(hierarchy.tiers) == 2


class TestAnnotation:
    """Tests for Annotation dataclass."""

    def test_basic_creation(self):
        """Test basic annotation creation."""
        ann = Annotation(
            id="ann1",
            tier="utterance",
            start_time=1000.0,
            end_time=2000.0,
            label="Speaker_A"
        )
        assert ann.id == "ann1"
        assert ann.duration == 1000.0

    def test_overlaps(self):
        """Test overlap detection."""
        ann1 = Annotation(id="1", tier="t", start_time=1000, end_time=2000)
        ann2 = Annotation(id="2", tier="t", start_time=1500, end_time=2500)
        ann3 = Annotation(id="3", tier="t", start_time=3000, end_time=4000)

        assert ann1.overlaps(ann2)
        assert ann2.overlaps(ann1)
        assert not ann1.overlaps(ann3)

    def test_contains(self):
        """Test containment detection."""
        parent = Annotation(id="1", tier="t", start_time=1000, end_time=3000)
        child = Annotation(id="2", tier="t", start_time=1500, end_time=2500)
        outside = Annotation(id="3", tier="t", start_time=0, end_time=500)

        assert parent.contains(child)
        assert not child.contains(parent)
        assert not parent.contains(outside)

    def test_from_dict_to_dict_roundtrip(self):
        """Test serialization roundtrip."""
        original = Annotation(
            id="ann1",
            tier="word",
            start_time=1000.0,
            end_time=2000.0,
            label="Content",
            parent_id="parent1",
            value="hello"
        )
        data = original.to_dict()
        restored = Annotation.from_dict(data)

        assert restored.id == original.id
        assert restored.tier == original.tier
        assert restored.start_time == original.start_time
        assert restored.end_time == original.end_time
        assert restored.label == original.label
        assert restored.parent_id == original.parent_id


class TestHierarchyManager:
    """Tests for HierarchyManager."""

    @pytest.fixture
    def simple_hierarchy(self):
        """Create a simple two-level hierarchy."""
        definition = HierarchyDefinition(tiers=[
            {"name": "utterance", "tier_type": "independent"},
            {"name": "word", "tier_type": "dependent", "parent_tier": "utterance",
             "constraint_type": "time_subdivision"},
        ])
        return HierarchyManager(definition)

    def test_creation(self, simple_hierarchy):
        """Test manager creation."""
        assert len(simple_hierarchy.annotations) == 2
        assert "utterance" in simple_hierarchy.annotations
        assert "word" in simple_hierarchy.annotations

    def test_invalid_hierarchy_raises(self):
        """Test that invalid hierarchy raises ValueError."""
        definition = HierarchyDefinition(tiers=[
            {"name": "child", "tier_type": "dependent", "parent_tier": "nonexistent"},
        ])
        with pytest.raises(ValueError):
            HierarchyManager(definition)

    def test_validate_independent_tier(self, simple_hierarchy):
        """Test validation for independent tier."""
        result = simple_hierarchy.validate_annotation(
            "utterance",
            start_time=1000.0,
            end_time=2000.0
        )
        assert result.valid

    def test_validate_dependent_without_parent(self, simple_hierarchy):
        """Test validation fails for dependent tier without parent."""
        result = simple_hierarchy.validate_annotation(
            "word",
            start_time=1000.0,
            end_time=2000.0,
            parent_annotation=None
        )
        assert not result.valid
        assert "requires a parent" in result.error

    def test_validate_time_subdivision_within_bounds(self, simple_hierarchy):
        """Test time subdivision validation within parent bounds."""
        parent = Annotation(
            id="parent1",
            tier="utterance",
            start_time=1000.0,
            end_time=3000.0
        )
        result = simple_hierarchy.validate_annotation(
            "word",
            start_time=1500.0,
            end_time=2500.0,
            parent_annotation=parent
        )
        assert result.valid

    def test_validate_time_subdivision_outside_bounds(self, simple_hierarchy):
        """Test time subdivision validation outside parent bounds fails."""
        parent = Annotation(
            id="parent1",
            tier="utterance",
            start_time=1000.0,
            end_time=2000.0
        )
        # Child extends past parent end
        result = simple_hierarchy.validate_annotation(
            "word",
            start_time=1500.0,
            end_time=2500.0,
            parent_annotation=parent
        )
        assert not result.valid
        assert "after parent end" in result.error

    def test_add_annotation_independent(self, simple_hierarchy):
        """Test adding annotation to independent tier."""
        ann = Annotation(
            id="ann1",
            tier="utterance",
            start_time=1000.0,
            end_time=2000.0,
            label="Speaker_A"
        )
        result = simple_hierarchy.add_annotation(ann)
        assert result.valid
        assert len(simple_hierarchy.get_tier_annotations("utterance")) == 1

    def test_add_annotation_dependent_with_parent(self, simple_hierarchy):
        """Test adding dependent annotation with valid parent."""
        # Add parent first
        parent = Annotation(
            id="parent1",
            tier="utterance",
            start_time=1000.0,
            end_time=3000.0,
            label="Speaker_A"
        )
        simple_hierarchy.add_annotation(parent)

        # Add child
        child = Annotation(
            id="child1",
            tier="word",
            start_time=1500.0,
            end_time=2500.0,
            label="Content",
            parent_id="parent1"
        )
        result = simple_hierarchy.add_annotation(child)
        assert result.valid
        assert len(simple_hierarchy.get_tier_annotations("word")) == 1

    def test_remove_annotation_cascade(self, simple_hierarchy):
        """Test cascading delete removes children."""
        # Add parent
        parent = Annotation(
            id="parent1",
            tier="utterance",
            start_time=1000.0,
            end_time=3000.0
        )
        simple_hierarchy.add_annotation(parent)

        # Add child
        child = Annotation(
            id="child1",
            tier="word",
            start_time=1500.0,
            end_time=2500.0,
            parent_id="parent1"
        )
        simple_hierarchy.add_annotation(child)

        # Remove parent with cascade
        success, removed = simple_hierarchy.remove_annotation("parent1", cascade=True)
        assert success
        assert "parent1" in removed
        assert "child1" in removed
        assert len(simple_hierarchy.get_tier_annotations("utterance")) == 0
        assert len(simple_hierarchy.get_tier_annotations("word")) == 0

    def test_find_parent_annotation(self, simple_hierarchy):
        """Test finding parent annotation by time range."""
        parent = Annotation(
            id="parent1",
            tier="utterance",
            start_time=1000.0,
            end_time=3000.0
        )
        simple_hierarchy.add_annotation(parent)

        found = simple_hierarchy.find_parent_annotation(
            "word",
            start_time=1500.0,
            end_time=2500.0
        )
        assert found is not None
        assert found.id == "parent1"

        # Outside range should return None
        not_found = simple_hierarchy.find_parent_annotation(
            "word",
            start_time=5000.0,
            end_time=6000.0
        )
        assert not_found is None

    def test_serialize_and_load(self, simple_hierarchy):
        """Test serialization and loading roundtrip."""
        # Add annotations
        parent = Annotation(
            id="parent1",
            tier="utterance",
            start_time=1000.0,
            end_time=3000.0,
            label="Speaker_A"
        )
        simple_hierarchy.add_annotation(parent)

        child = Annotation(
            id="child1",
            tier="word",
            start_time=1500.0,
            end_time=2500.0,
            label="Content",
            parent_id="parent1"
        )
        simple_hierarchy.add_annotation(child)

        # Serialize
        data = simple_hierarchy.serialize()

        # Create new manager and load
        new_manager = HierarchyManager(simple_hierarchy.definition)
        errors = new_manager.load_annotations(data)
        assert len(errors) == 0

        # Verify
        assert len(new_manager.get_tier_annotations("utterance")) == 1
        assert len(new_manager.get_tier_annotations("word")) == 1

    def test_generate_time_slots(self, simple_hierarchy):
        """Test time slot generation."""
        parent = Annotation(id="1", tier="utterance", start_time=1000, end_time=3000)
        child = Annotation(id="2", tier="word", start_time=1500, end_time=2500, parent_id="1")
        simple_hierarchy.add_annotation(parent)
        simple_hierarchy.add_annotation(child)

        slots = simple_hierarchy.generate_time_slots()
        assert len(slots) == 4  # 1000, 1500, 2500, 3000
        assert 1000 in slots.values()
        assert 3000 in slots.values()

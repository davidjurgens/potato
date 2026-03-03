"""
Tests for edge case rule discovery (Co-DETECT-style).

Tests EdgeCaseRule, EdgeCaseCategory, and EdgeCaseRuleManager.
"""

import os
import json
import tempfile
import pytest
from datetime import datetime

from potato.solo_mode.edge_case_rules import (
    EdgeCaseRule,
    EdgeCaseCategory,
    EdgeCaseRuleManager,
)


class TestEdgeCaseRule:
    """Tests for EdgeCaseRule dataclass."""

    def test_creation(self):
        rule = EdgeCaseRule(
            id="rule_001",
            instance_id="inst_42",
            rule_text="When the text contains sarcasm -> label as negative",
            condition="the text contains sarcasm",
            action="label as negative",
            source_confidence=0.45,
            source_label="positive",
            prompt_version=1,
        )
        assert rule.id == "rule_001"
        assert rule.condition == "the text contains sarcasm"
        assert rule.action == "label as negative"
        assert rule.cluster_id is None
        assert rule.reviewed is False

    def test_serialization_roundtrip(self):
        rule = EdgeCaseRule(
            id="rule_002",
            instance_id="inst_99",
            rule_text="When X -> Y",
            condition="X",
            action="Y",
            source_confidence=0.3,
            source_label="neutral",
            prompt_version=2,
            model_name="test-model",
            cluster_id=5,
            reviewed=True,
            approved=True,
            reviewer_notes="Good rule",
        )
        data = rule.to_dict()
        restored = EdgeCaseRule.from_dict(data)

        assert restored.id == rule.id
        assert restored.instance_id == rule.instance_id
        assert restored.rule_text == rule.rule_text
        assert restored.condition == rule.condition
        assert restored.action == rule.action
        assert restored.source_confidence == rule.source_confidence
        assert restored.source_label == rule.source_label
        assert restored.prompt_version == rule.prompt_version
        assert restored.model_name == rule.model_name
        assert restored.cluster_id == rule.cluster_id
        assert restored.reviewed is True
        assert restored.approved is True
        assert restored.reviewer_notes == "Good rule"

    def test_defaults(self):
        rule = EdgeCaseRule(
            id="r", instance_id="i", rule_text="r",
            condition="c", action="a",
            source_confidence=0.5, source_label="x",
            prompt_version=1,
        )
        assert rule.model_name == ""
        assert rule.cluster_id is None
        assert rule.embedding is None
        assert rule.reviewed is False
        assert rule.approved is None
        assert rule.reviewer_notes == ""


class TestEdgeCaseCategory:
    """Tests for EdgeCaseCategory dataclass."""

    def test_creation(self):
        cat = EdgeCaseCategory(
            id="cat_001",
            summary_rule="When sarcasm is present, prioritize tone over literal meaning",
            member_rule_ids=["rule_001", "rule_002", "rule_003"],
        )
        assert cat.id == "cat_001"
        assert len(cat.member_rule_ids) == 3
        assert cat.reviewed is False
        assert cat.incorporated_into_prompt_version is None

    def test_serialization_roundtrip(self):
        cat = EdgeCaseCategory(
            id="cat_002",
            summary_rule="Summary rule text",
            member_rule_ids=["r1", "r2"],
            reviewed=True,
            approved=True,
            reviewer_notes="Looks good",
            incorporated_into_prompt_version=3,
        )
        data = cat.to_dict()
        restored = EdgeCaseCategory.from_dict(data)

        assert restored.id == cat.id
        assert restored.summary_rule == cat.summary_rule
        assert restored.member_rule_ids == cat.member_rule_ids
        assert restored.reviewed is True
        assert restored.approved is True
        assert restored.reviewer_notes == "Looks good"
        assert restored.incorporated_into_prompt_version == 3


class TestEdgeCaseRuleManager:
    """Tests for EdgeCaseRuleManager."""

    @pytest.fixture
    def manager(self):
        return EdgeCaseRuleManager()

    @pytest.fixture
    def manager_with_state_dir(self, tmp_path):
        return EdgeCaseRuleManager(state_dir=str(tmp_path))

    def test_record_rule(self, manager):
        rule = manager.record_rule_from_labeling(
            instance_id="inst_1",
            rule_text="When ambiguous -> choose neutral",
            condition="ambiguous",
            action="choose neutral",
            confidence=0.4,
            label="positive",
            prompt_version=1,
        )
        assert rule.id.startswith("rule_")
        assert rule.instance_id == "inst_1"
        assert manager.get_rule(rule.id) is not None

    def test_get_all_rules(self, manager):
        for i in range(3):
            manager.record_rule_from_labeling(
                instance_id=f"inst_{i}",
                rule_text=f"Rule {i}",
                condition=f"Cond {i}",
                action=f"Act {i}",
                confidence=0.3,
                label="x",
                prompt_version=1,
            )
        assert len(manager.get_all_rules()) == 3

    def test_get_unclustered_rules(self, manager):
        r1 = manager.record_rule_from_labeling(
            instance_id="i1", rule_text="R1", condition="C1", action="A1",
            confidence=0.3, label="x", prompt_version=1,
        )
        r2 = manager.record_rule_from_labeling(
            instance_id="i2", rule_text="R2", condition="C2", action="A2",
            confidence=0.3, label="x", prompt_version=1,
        )

        assert len(manager.get_unclustered_rules()) == 2

        # Assign cluster to r1
        manager.set_rule_cluster(r1.id, 0)
        assert len(manager.get_unclustered_rules()) == 1
        assert manager.get_unclustered_rules()[0].id == r2.id

    def test_add_and_get_category(self, manager):
        cat = EdgeCaseCategory(
            id="cat_1",
            summary_rule="Summary",
            member_rule_ids=["r1", "r2"],
        )
        manager.add_category(cat)
        assert manager.get_category("cat_1") is not None
        assert len(manager.get_all_categories()) == 1

    def test_pending_categories(self, manager):
        cat1 = EdgeCaseCategory(id="c1", summary_rule="S1")
        cat2 = EdgeCaseCategory(id="c2", summary_rule="S2", reviewed=True, approved=True)
        cat3 = EdgeCaseCategory(id="c3", summary_rule="S3")
        manager.add_category(cat1)
        manager.add_category(cat2)
        manager.add_category(cat3)

        pending = manager.get_pending_categories()
        assert len(pending) == 2

    def test_approve_category(self, manager):
        cat = EdgeCaseCategory(id="c1", summary_rule="S1")
        manager.add_category(cat)

        assert manager.approve_category("c1", notes="LGTM")
        approved = manager.get_approved_categories()
        assert len(approved) == 1
        assert approved[0].reviewer_notes == "LGTM"

    def test_reject_category(self, manager):
        cat = EdgeCaseCategory(id="c1", summary_rule="S1")
        manager.add_category(cat)

        assert manager.reject_category("c1", notes="Too broad")
        rejected = manager.get_rejected_categories()
        assert len(rejected) == 1
        assert rejected[0].reviewer_notes == "Too broad"

    def test_approve_nonexistent(self, manager):
        assert not manager.approve_category("nonexistent")
        assert not manager.reject_category("nonexistent")

    def test_get_category_for_rule(self, manager):
        """Test finding the category that contains a rule."""
        rule = manager.record_rule_from_labeling(
            instance_id="inst_1",
            rule_text="When X -> Y",
            condition="X", action="Y",
            confidence=0.5, label="test", prompt_version=1,
        )

        cat = EdgeCaseCategory(
            id="c1", summary_rule="Summary",
            member_rule_ids=[rule.id, "r2"],
        )
        manager.add_category(cat)

        # Rule belongs to c1
        found = manager.get_category_for_rule(rule.id)
        assert found is not None
        assert found.id == "c1"

        # Unknown rule returns None
        assert manager.get_category_for_rule("unknown") is None

    def test_mark_category_incorporated(self, manager):
        cat = EdgeCaseCategory(id="c1", summary_rule="S1")
        manager.add_category(cat)
        manager.approve_category("c1")
        manager.mark_category_incorporated("c1", prompt_version=5)

        updated = manager.get_category("c1")
        assert updated.incorporated_into_prompt_version == 5

    def test_rules_for_prompt_injection(self, manager):
        # No approved categories -> empty string
        assert manager.get_rules_for_prompt_injection() == ""

        # Add an approved category
        cat = EdgeCaseCategory(
            id="c1",
            summary_rule="When sarcasm -> label as negative",
        )
        manager.add_category(cat)
        manager.approve_category("c1")

        text = manager.get_rules_for_prompt_injection()
        assert "Edge Case Guidelines" in text
        assert "When sarcasm -> label as negative" in text

    def test_rules_for_prompt_injection_skips_incorporated(self, manager):
        cat = EdgeCaseCategory(
            id="c1",
            summary_rule="Already used rule",
        )
        manager.add_category(cat)
        manager.approve_category("c1")
        manager.mark_category_incorporated("c1", prompt_version=3)

        # Should be empty since the only approved category is already incorporated
        assert manager.get_rules_for_prompt_injection() == ""

    def test_get_stats(self, manager):
        manager.record_rule_from_labeling(
            instance_id="i1", rule_text="R", condition="C", action="A",
            confidence=0.3, label="x", prompt_version=1,
        )
        cat = EdgeCaseCategory(id="c1", summary_rule="S")
        manager.add_category(cat)

        stats = manager.get_stats()
        assert stats['total_rules'] == 1
        assert stats['unclustered_rules'] == 1
        assert stats['total_categories'] == 1
        assert stats['pending_categories'] == 1

    def test_serialization_roundtrip(self, manager):
        r = manager.record_rule_from_labeling(
            instance_id="i1", rule_text="R1", condition="C1", action="A1",
            confidence=0.3, label="x", prompt_version=1,
        )
        cat = EdgeCaseCategory(id="c1", summary_rule="S1", member_rule_ids=[r.id])
        manager.add_category(cat)
        manager.approve_category("c1")

        data = manager.to_dict()
        restored = EdgeCaseRuleManager.from_dict(data)

        assert len(restored.get_all_rules()) == 1
        assert len(restored.get_all_categories()) == 1
        assert len(restored.get_approved_categories()) == 1

    def test_persistence(self, manager_with_state_dir):
        m = manager_with_state_dir
        m.record_rule_from_labeling(
            instance_id="i1", rule_text="R1", condition="C1", action="A1",
            confidence=0.3, label="x", prompt_version=1,
        )
        cat = EdgeCaseCategory(id="c1", summary_rule="S1")
        m.add_category(cat)

        # Create a new manager from the same state dir
        m2 = EdgeCaseRuleManager(state_dir=m.state_dir)
        assert m2.load_state()
        assert len(m2.get_all_rules()) == 1
        assert len(m2.get_all_categories()) == 1


class TestLabelingResultEdgeCaseFields:
    """Tests for LabelingResult edge case extensions."""

    def test_labeling_result_edge_case_fields(self):
        from potato.solo_mode.llm_labeler import LabelingResult

        result = LabelingResult(
            instance_id="i1",
            schema_name="sentiment",
            label="positive",
            confidence=0.4,
            uncertainty=0.6,
            reasoning="Ambiguous tone",
            prompt_version=1,
            model_name="test",
            is_edge_case=True,
            edge_case_rule="When sarcasm present -> label as negative",
            edge_case_condition="sarcasm present",
            edge_case_action="label as negative",
        )

        data = result.to_dict()
        assert data['is_edge_case'] is True
        assert "sarcasm" in data['edge_case_rule']
        assert data['edge_case_condition'] == "sarcasm present"
        assert data['edge_case_action'] == "label as negative"

    def test_labeling_result_no_edge_case(self):
        from potato.solo_mode.llm_labeler import LabelingResult

        result = LabelingResult(
            instance_id="i1",
            schema_name="sentiment",
            label="positive",
            confidence=0.9,
            uncertainty=0.1,
            reasoning="Clear positive",
            prompt_version=1,
            model_name="test",
        )

        data = result.to_dict()
        assert 'is_edge_case' not in data


class TestEdgeCaseRuleParsing:
    """Tests for the LLM labeler's rule parsing."""

    def test_parse_when_arrow_format(self):
        from potato.solo_mode.llm_labeler import LLMLabelingThread

        thread = LLMLabelingThread.__new__(LLMLabelingThread)
        cond, act = thread._parse_edge_case_rule(
            "When the text uses double negatives -> label as positive"
        )
        assert cond == "the text uses double negatives"
        assert act == "label as positive"

    def test_parse_if_then_format(self):
        from potato.solo_mode.llm_labeler import LLMLabelingThread

        thread = LLMLabelingThread.__new__(LLMLabelingThread)
        cond, act = thread._parse_edge_case_rule(
            "If the sentiment is mixed, then choose the dominant emotion"
        )
        assert cond == "the sentiment is mixed"
        assert act == "choose the dominant emotion"

    def test_parse_fallback(self):
        from potato.solo_mode.llm_labeler import LLMLabelingThread

        thread = LLMLabelingThread.__new__(LLMLabelingThread)
        cond, act = thread._parse_edge_case_rule("Some unstructured rule text")
        assert cond == "Some unstructured rule text"
        assert act == ""


class TestEdgeCaseRuleConfig:
    """Tests for EdgeCaseRuleConfig parsing."""

    def test_default_config(self):
        from potato.solo_mode.config import EdgeCaseRuleConfig
        config = EdgeCaseRuleConfig()
        assert config.enabled is True
        assert config.confidence_threshold == 0.75
        assert config.min_rules_for_clustering == 10
        assert config.target_cluster_size == 15
        assert config.reannotation_enabled is True
        assert config.max_reannotations_per_instance == 2

    def test_parse_from_yaml(self):
        from potato.solo_mode.config import parse_solo_mode_config

        config_data = {
            'solo_mode': {
                'enabled': True,
                'labeling_models': [
                    {'endpoint_type': 'ollama', 'model': 'test'}
                ],
                'edge_case_rules': {
                    'enabled': True,
                    'confidence_threshold': 0.80,
                    'min_rules_for_clustering': 15,
                    'target_cluster_size': 20,
                    'reannotation_enabled': False,
                },
            },
        }
        config = parse_solo_mode_config(config_data)
        assert config.edge_case_rules.enabled is True
        assert config.edge_case_rules.confidence_threshold == 0.80
        assert config.edge_case_rules.min_rules_for_clustering == 15
        assert config.edge_case_rules.target_cluster_size == 20
        assert config.edge_case_rules.reannotation_enabled is False

    def test_parse_defaults_when_missing(self):
        from potato.solo_mode.config import parse_solo_mode_config

        config_data = {
            'solo_mode': {
                'enabled': True,
                'labeling_models': [
                    {'endpoint_type': 'ollama', 'model': 'test'}
                ],
            },
        }
        config = parse_solo_mode_config(config_data)
        assert config.edge_case_rules.enabled is True
        assert config.edge_case_rules.confidence_threshold == 0.75

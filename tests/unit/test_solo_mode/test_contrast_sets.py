"""
Tests for ContrastSetGenerator and contrast-pair rule proposal.

Tests ContrastPair dataclass, pair preparation, the human-authored edit
recording flow, serialization, and the propose_rules_from_contrast_pairs
pipeline that stages codebook edits via the existing propose/human-confirm
flow.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from potato.solo_mode.contrast_sets import (
    ContrastPair,
    ContrastSetGenerator,
    _describe_edit,
    propose_rules_from_contrast_pairs,
)
from potato.solo_mode.edge_case_synthesizer import EdgeCase


class TestContrastPair:
    """Tests for ContrastPair dataclass."""

    def test_creation(self):
        pair = ContrastPair(
            id="contrast_0001",
            source_case_id="edge_0001",
            label_a="cost concerns",
            label_b="access barriers",
            original_text="I could not afford the visit.",
            edited_text="",
            changed_span="",
            proposed_label="access barriers",
        )
        assert pair.id == "contrast_0001"
        assert pair.human_verdict is None
        assert pair.human_label is None

    def test_serialization_roundtrip(self):
        pair = ContrastPair(
            id="c1", source_case_id="e1", label_a="a", label_b="b",
            original_text="orig", edited_text="edit",
            changed_span="span", proposed_label="b",
            human_verdict="authored", human_label="b", notes="clear flip",
            reviewed_at=datetime(2025, 1, 1, 12, 0, 0),
        )
        data = pair.to_dict()
        restored = ContrastPair.from_dict(data)

        assert restored.id == pair.id
        assert restored.label_a == "a"
        assert restored.label_b == "b"
        assert restored.human_verdict == "authored"
        assert restored.human_label == "b"
        assert restored.notes == "clear flip"
        assert restored.reviewed_at is not None

    def test_serialization_unwritten(self):
        pair = ContrastPair(
            id="c1", source_case_id="e1", label_a="a", label_b="b",
            original_text="o", edited_text="", changed_span="",
            proposed_label="b",
        )
        data = pair.to_dict()
        assert data['human_verdict'] is None
        assert data['reviewed_at'] is None

        restored = ContrastPair.from_dict(data)
        assert restored.human_verdict is None
        assert restored.reviewed_at is None


class TestDescribeEdit:
    """Tests for the deterministic diff-description helper."""

    def test_describes_word_swap(self):
        desc = _describe_edit(
            "I could not afford the visit.",
            "I could not reach the clinic.",
        )
        assert "afford" in desc
        assert "reach" in desc
        assert "visit." in desc
        assert "clinic." in desc
        assert "->" in desc

    def test_pure_addition(self):
        desc = _describe_edit("I went to the clinic", "I went to the clinic today")
        assert "(nothing removed)" in desc
        assert "today" in desc

    def test_pure_removal(self):
        desc = _describe_edit("I went to the clinic today", "I went to the clinic")
        assert "(nothing added)" in desc


class TestContrastSetGeneratorCRUD:
    """Tests for the human-edit recording flow, without touching the LLM."""

    @pytest.fixture
    def generator(self):
        solo_config = MagicMock()
        solo_config.revision_models = []
        return ContrastSetGenerator({}, solo_config)

    def _add_pair(self, generator, pair_id="contrast_0001",
                  original_text="orig text here"):
        pair = ContrastPair(
            id=pair_id, source_case_id="e1", label_a="a", label_b="b",
            original_text=original_text, edited_text="",
            changed_span="", proposed_label="b",
        )
        generator.pairs[pair_id] = pair
        return pair

    def test_record_human_edit(self, generator):
        self._add_pair(generator)
        assert generator.record_human_edit(
            "contrast_0001", "edited text here", notes="swapped a word") is True
        pair = generator.pairs["contrast_0001"]
        assert pair.edited_text == "edited text here"
        assert pair.human_verdict == "authored"
        assert pair.human_label == "b"  # the proposed/target label
        assert pair.notes == "swapped a word"
        assert pair.reviewed_at is not None
        assert "->" in pair.changed_span

    def test_record_human_edit_rejects_empty(self, generator):
        self._add_pair(generator)
        assert generator.record_human_edit("contrast_0001", "") is False
        assert generator.pairs["contrast_0001"].human_verdict is None

    def test_record_human_edit_rejects_unchanged(self, generator):
        self._add_pair(generator, original_text="same text")
        assert generator.record_human_edit("contrast_0001", "same text") is False
        assert generator.pairs["contrast_0001"].human_verdict is None

    def test_record_human_edit_nonexistent(self, generator):
        assert generator.record_human_edit("nonexistent", "x") is False

    def test_get_unreviewed_and_reviewed(self, generator):
        self._add_pair(generator, "c1")
        self._add_pair(generator, "c2")
        generator.record_human_edit("c1", "edited")

        unreviewed = generator.get_unreviewed_pairs()
        reviewed = generator.get_reviewed_pairs()
        assert len(unreviewed) == 1
        assert unreviewed[0].id == "c2"
        assert len(reviewed) == 1
        assert reviewed[0].id == "c1"

    def test_get_status(self, generator):
        self._add_pair(generator, "c1")
        self._add_pair(generator, "c2")
        generator.record_human_edit("c1", "edited")

        status = generator.get_status()
        assert status['total_pairs'] == 2
        assert status['reviewed'] == 1
        assert status['unreviewed'] == 1

    def test_serialization_roundtrip(self, generator):
        self._add_pair(generator, "c1")
        generator.record_human_edit("c1", "edited")

        data = generator.to_dict()
        restored = ContrastSetGenerator({}, MagicMock(revision_models=[]))
        restored.from_dict(data)

        assert len(restored.pairs) == 1
        assert restored.pairs["c1"].human_verdict == "authored"

    def test_try_claim_rule_proposal_only_succeeds_once(self, generator):
        assert generator.try_claim_rule_proposal() is True
        assert generator.try_claim_rule_proposal() is False
        assert generator.try_claim_rule_proposal() is False

    def test_rules_proposed_flag_roundtrips(self, generator):
        generator.try_claim_rule_proposal()
        data = generator.to_dict()
        assert data['rules_proposed'] is True

        restored = ContrastSetGenerator({}, MagicMock(revision_models=[]))
        restored.from_dict(data)
        assert restored.rules_proposed is True
        assert restored.try_claim_rule_proposal() is False


class TestPreparePairsForWriting:
    """Tests for prepare_pairs_for_writing — no LLM involved, purely
    deriving eligible (label_a, label_b) targets from labeled edge cases."""

    @pytest.fixture
    def generator(self):
        return ContrastSetGenerator({}, MagicMock(revision_models=[]))

    def _labeled_case(self, boundary_labels, human_label):
        case = EdgeCase(
            id="edge_0001", text="I could not afford the visit.",
            boundary_labels=boundary_labels,
            difficulty_reason="boundary", which_aspect="cost vs access",
        )
        case.human_label = human_label
        return case

    def test_prepares_pair_for_two_boundary_labels(self, generator):
        case = self._labeled_case(["cost concerns", "access barriers"],
                                   "cost concerns")
        pairs = generator.prepare_pairs_for_writing([case])

        assert len(pairs) == 1
        pair = pairs[0]
        assert pair.label_a == "cost concerns"
        assert pair.label_b == "access barriers"
        assert pair.original_text == case.text
        assert pair.edited_text == ""
        assert pair.proposed_label == "access barriers"
        assert pair.source_case_id == "edge_0001"
        assert pair.human_verdict is None  # awaiting the human's edit

    def test_skips_case_with_single_boundary_label(self, generator):
        case = self._labeled_case(["cost concerns"], "cost concerns")
        pairs = generator.prepare_pairs_for_writing([case])
        assert pairs == []

    def test_skips_case_with_no_human_label(self, generator):
        case = self._labeled_case(["a", "b"], None)
        pairs = generator.prepare_pairs_for_writing([case])
        assert pairs == []

    def test_prepared_pairs_are_stored_and_pending(self, generator):
        case = self._labeled_case(["a", "b"], "a")
        generator.prepare_pairs_for_writing([case])
        assert len(generator.get_unreviewed_pairs()) == 1
        assert generator.get_reviewed_pairs() == []


class TestProposeRulesFromContrastPairs:
    """Tests for the rule-proposal pipeline, with changelog/Codebook mocked."""

    def _make_pair(self, label_a="cost concerns", label_b="access barriers"):
        pair = ContrastPair(
            id="c1", source_case_id="e1", label_a=label_a, label_b=label_b,
            original_text="I could not afford the visit.",
            edited_text="I could not reach the clinic.",
            changed_span='"afford the visit." -> "reach the clinic."',
            proposed_label=label_b,
        )
        pair.human_verdict = "authored"
        pair.human_label = label_b
        return pair

    def test_no_written_pairs_creates_nothing(self):
        pair = ContrastPair(
            id="c1", source_case_id="e1", label_a="a", label_b="b",
            original_text="o", edited_text="", changed_span="",
            proposed_label="b",
        )  # human_verdict is None -> not yet written
        endpoint = MagicMock()
        created = propose_rules_from_contrast_pairs(
            "task_dir", "project", [pair], endpoint=endpoint)
        assert created == []
        endpoint.query.assert_not_called()

    def test_creates_two_proposals_for_a_written_pair(self):
        pair = self._make_pair()
        endpoint = MagicMock()
        endpoint.query.return_value = (
            '{"should_propose": true, "rationale": "cost vs distance",'
            ' "label_a_negative_clarification": "not cost if distance is the issue",'
            ' "label_b_negative_clarification": "not access if money is the issue"}'
        )
        fake_codes = [
            {'id': 'code-access', 'name': 'access barriers'},
            {'id': 'code-cost', 'name': 'cost concerns'},
        ]
        fake_cb = MagicMock()
        fake_cb.details_in_order.return_value = fake_codes

        with patch('potato.codebook.codebook.Codebook.load',
                    return_value=fake_cb), \
             patch('potato.codebook.changelog.propose_change') as mock_propose:
            mock_propose.side_effect = (
                lambda *a, **kw: {'id': 'prop', 'payload': kw['payload']})
            created = propose_rules_from_contrast_pairs(
                "task_dir", "project", [pair], endpoint=endpoint,
                actor="contrast_set_llm")

        assert len(created) == 2
        assert mock_propose.call_count == 2
        for call in mock_propose.call_args_list:
            assert call.kwargs['op'] == 'update_fields'
            assert call.kwargs['actor_kind'] == 'model'
            payload = call.kwargs['payload']
            # Paraphrase-only: no raw example text ever lands in the
            # codebook for contrast-set-derived rules — negative_clarification
            # is the sole carrier of what was learned.
            assert 'negative_examples' not in payload
            assert 'negative_example' not in payload
            assert 'negative_example_why' not in payload
            assert payload['negative_clarification']

        access_call = next(
            c for c in mock_propose.call_args_list
            if c.kwargs['payload']['code_id'] == 'code-access')
        assert access_call.kwargs['payload']['negative_clarification'] == (
            "not cost if distance is the issue")

    def test_should_propose_false_creates_nothing(self):
        pair = self._make_pair()
        endpoint = MagicMock()
        endpoint.query.return_value = '{"should_propose": false}'
        fake_cb = MagicMock()
        fake_cb.details_in_order.return_value = []

        with patch('potato.codebook.codebook.Codebook.load',
                    return_value=fake_cb), \
             patch('potato.codebook.changelog.propose_change') as mock_propose:
            created = propose_rules_from_contrast_pairs(
                "task_dir", "project", [pair], endpoint=endpoint)

        assert created == []
        mock_propose.assert_not_called()

    def test_unknown_code_name_is_skipped(self):
        pair = self._make_pair()
        endpoint = MagicMock()
        endpoint.query.return_value = (
            '{"should_propose": true, '
            '"label_a_negative_clarification": "x", '
            '"label_b_negative_clarification": "y"}'
        )
        fake_cb = MagicMock()
        fake_cb.details_in_order.return_value = []  # no codes at all

        with patch('potato.codebook.codebook.Codebook.load',
                    return_value=fake_cb), \
             patch('potato.codebook.changelog.propose_change') as mock_propose:
            created = propose_rules_from_contrast_pairs(
                "task_dir", "project", [pair], endpoint=endpoint)

        assert created == []
        mock_propose.assert_not_called()

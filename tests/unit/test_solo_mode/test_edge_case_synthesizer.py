"""
Tests for EdgeCaseSynthesizer.

Tests EdgeCase dataclass, synthesizer CRUD operations, label recording,
prompt revision formatting, status, and serialization.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from potato.solo_mode.edge_case_synthesizer import (
    EdgeCase,
    EdgeCaseSynthesizer,
)


class TestEdgeCase:
    """Tests for EdgeCase dataclass."""

    def test_creation(self):
        ec = EdgeCase(
            id="edge_0001",
            text="The product is not bad at all",
            boundary_labels=["positive", "negative"],
            difficulty_reason="Double negation",
            which_aspect="negation handling",
        )
        assert ec.id == "edge_0001"
        assert ec.human_label is None
        assert ec.labeled_at is None

    def test_serialization_roundtrip(self):
        ec = EdgeCase(
            id="edge_0001",
            text="Test text",
            boundary_labels=["a", "b"],
            difficulty_reason="Ambiguous",
            which_aspect="boundary",
            human_label="a",
            labeler_notes="Clearly a",
            labeled_at=datetime(2025, 1, 1, 12, 0, 0),
        )
        data = ec.to_dict()
        restored = EdgeCase.from_dict(data)

        assert restored.id == ec.id
        assert restored.text == ec.text
        assert restored.boundary_labels == ec.boundary_labels
        assert restored.difficulty_reason == ec.difficulty_reason
        assert restored.which_aspect == ec.which_aspect
        assert restored.human_label == "a"
        assert restored.labeler_notes == "Clearly a"
        assert restored.labeled_at is not None

    def test_serialization_no_label(self):
        ec = EdgeCase(
            id="e1", text="t", boundary_labels=[], difficulty_reason="",
            which_aspect="",
        )
        data = ec.to_dict()
        assert data['human_label'] is None
        assert data['labeled_at'] is None

        restored = EdgeCase.from_dict(data)
        assert restored.human_label is None
        assert restored.labeled_at is None


class TestEdgeCaseSynthesizerCRUD:
    """Tests for synthesizer CRUD operations."""

    @pytest.fixture
    def synthesizer(self):
        config = {'annotation_schemes': [
            {'name': 'test', 'labels': ['positive', 'negative']}
        ]}
        solo_config = MagicMock()
        solo_config.revision_models = []
        return EdgeCaseSynthesizer(config, solo_config)

    def _add_case(self, synthesizer, case_id="edge_0001", text="Test"):
        """Helper to directly add a case."""
        case = EdgeCase(
            id=case_id, text=text, boundary_labels=["a", "b"],
            difficulty_reason="reason", which_aspect="aspect",
        )
        synthesizer.edge_cases[case_id] = case
        return case

    def test_get_edge_case(self, synthesizer):
        case = self._add_case(synthesizer)
        result = synthesizer.get_edge_case("edge_0001")
        assert result is not None
        assert result.text == "Test"

    def test_get_edge_case_nonexistent(self, synthesizer):
        assert synthesizer.get_edge_case("nonexistent") is None

    def test_get_all_edge_cases(self, synthesizer):
        self._add_case(synthesizer, "e1", "t1")
        self._add_case(synthesizer, "e2", "t2")
        assert len(synthesizer.get_all_edge_cases()) == 2

    def test_get_unlabeled(self, synthesizer):
        self._add_case(synthesizer, "e1")
        self._add_case(synthesizer, "e2")
        synthesizer.edge_cases["e1"].human_label = "x"

        unlabeled = synthesizer.get_unlabeled_edge_cases()
        assert len(unlabeled) == 1
        assert unlabeled[0].id == "e2"

    def test_get_labeled(self, synthesizer):
        self._add_case(synthesizer, "e1")
        self._add_case(synthesizer, "e2")
        synthesizer.edge_cases["e1"].human_label = "x"

        labeled = synthesizer.get_labeled_edge_cases()
        assert len(labeled) == 1
        assert labeled[0].id == "e1"


class TestEdgeCaseSynthesizerLabeling:
    """Tests for label recording."""

    @pytest.fixture
    def synthesizer(self):
        s = EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))
        case = EdgeCase(
            id="e1", text="test", boundary_labels=["a", "b"],
            difficulty_reason="r", which_aspect="a",
        )
        s.edge_cases["e1"] = case
        return s

    def test_record_label(self, synthesizer):
        assert synthesizer.record_label("e1", "positive", "Clear case") is True
        case = synthesizer.get_edge_case("e1")
        assert case.human_label == "positive"
        assert case.labeler_notes == "Clear case"
        assert case.labeled_at is not None

    def test_record_label_no_notes(self, synthesizer):
        assert synthesizer.record_label("e1", "x") is True
        assert synthesizer.get_edge_case("e1").labeler_notes is None

    def test_record_label_nonexistent(self, synthesizer):
        assert synthesizer.record_label("nonexistent", "x") is False


class TestEdgeCaseSynthesizerPromptRevision:
    """Tests for prompt revision formatting."""

    @pytest.fixture
    def synthesizer(self):
        s = EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))
        for i in range(3):
            case = EdgeCase(
                id=f"e{i}", text=f"text_{i}",
                boundary_labels=["a", "b"],
                difficulty_reason=f"reason_{i}",
                which_aspect=f"aspect_{i}",
            )
            s.edge_cases[f"e{i}"] = case
        # Label first two
        s.edge_cases["e0"].human_label = "a"
        s.edge_cases["e1"].human_label = "b"
        return s

    def test_get_cases_for_prompt_revision(self, synthesizer):
        cases = synthesizer.get_cases_for_prompt_revision()
        assert len(cases) == 2  # Only labeled ones
        assert cases[0]['text'] == "text_0"
        assert cases[0]['expected_label'] == "a"
        assert 'boundary_labels' in cases[0]
        assert 'difficulty_reason' in cases[0]


class TestEdgeCaseSynthesizerStatus:
    """Tests for status reporting."""

    def test_empty_status(self):
        s = EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))
        status = s.get_status()
        assert status['total_edge_cases'] == 0
        assert status['labeled'] == 0
        assert status['unlabeled'] == 0
        assert status['synthesis_rounds'] == 0

    def test_status_with_data(self):
        s = EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))
        for i in range(3):
            case = EdgeCase(
                id=f"e{i}", text=f"t{i}", boundary_labels=[],
                difficulty_reason="", which_aspect=f"a{i}",
            )
            s.edge_cases[f"e{i}"] = case
            s.tested_aspects.add(f"a{i}")
        s.edge_cases["e0"].human_label = "x"

        status = s.get_status()
        assert status['total_edge_cases'] == 3
        assert status['labeled'] == 1
        assert status['unlabeled'] == 2
        assert len(status['tested_aspects']) == 3


class TestEdgeCaseSynthesizerFormatting:
    """Tests for formatting helper methods."""

    @pytest.fixture
    def synthesizer(self):
        return EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))

    def test_extract_labels(self, synthesizer):
        schemes = [{'labels': ['pos', 'neg']}]
        result = synthesizer._extract_labels(schemes)
        assert "pos" in result
        assert "neg" in result

    def test_extract_labels_with_descriptions(self, synthesizer):
        schemes = [{'labels': [{'name': 'pos', 'description': 'positive'}]}]
        result = synthesizer._extract_labels(schemes)
        assert "pos: positive" in result

    def test_format_examples(self, synthesizer):
        examples = ["First example", "Second example"]
        result = synthesizer._format_examples(examples)
        assert "First example" in result
        assert "Second example" in result

    def test_format_examples_empty(self, synthesizer):
        result = synthesizer._format_examples([])
        assert "No existing examples" in result

    def test_format_examples_truncates(self, synthesizer):
        examples = ["x" * 500]
        result = synthesizer._format_examples(examples)
        # Text truncated to 200
        assert len(result) < 500

    def test_format_examples_limits_to_5(self, synthesizer):
        examples = [f"example_{i}" for i in range(10)]
        result = synthesizer._format_examples(examples)
        assert "example_4" in result
        assert "example_5" not in result


class TestEdgeCaseSynthesizerJsonParsing:
    """Tests for JSON response parsing."""

    @pytest.fixture
    def synthesizer(self):
        return EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))

    def test_parse_valid(self, synthesizer):
        result = synthesizer._parse_json_response(
            '{"edge_cases": [{"text": "test"}]}'
        )
        assert len(result['edge_cases']) == 1

    def test_parse_markdown(self, synthesizer):
        result = synthesizer._parse_json_response(
            '```json\n{"edge_cases": []}\n```'
        )
        assert result['edge_cases'] == []

    def test_parse_invalid(self, synthesizer):
        result = synthesizer._parse_json_response("not json")
        assert result == {'edge_cases': []}


class TestEdgeCaseSynthesizerSerialization:
    """Tests for to_dict/from_dict."""

    def test_roundtrip(self):
        s = EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))
        case = EdgeCase(
            id="e1", text="test", boundary_labels=["a"],
            difficulty_reason="r", which_aspect="aspect",
        )
        s.edge_cases["e1"] = case
        s.tested_aspects.add("aspect")
        s.synthesis_rounds.append({'timestamp': '2025-01-01', 'num_generated': 1})
        s._id_counter = 1

        data = s.to_dict()
        assert 'edge_cases' in data
        assert data['id_counter'] == 1

        s2 = EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))
        s2.from_dict(data)
        assert len(s2.edge_cases) == 1
        assert "aspect" in s2.tested_aspects
        assert s2._id_counter == 1

    def test_from_dict_empty(self):
        s = EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))
        s.from_dict({})
        assert len(s.edge_cases) == 0


class TestEdgeCaseSynthesizerIdGeneration:
    """Tests for ID generation."""

    def test_sequential_ids(self):
        s = EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))
        assert s._generate_id() == "edge_0001"
        assert s._generate_id() == "edge_0002"
        assert s._generate_id() == "edge_0003"


class TestEdgeCaseSynthesizerSynthesizeNoEndpoint:
    """Tests for synthesis without endpoint."""

    def test_no_endpoint_returns_empty(self):
        s = EdgeCaseSynthesizer({}, MagicMock(revision_models=[]))
        result = s.synthesize_edge_cases("task", "prompt", num_cases=5)
        assert result == []

"""Unit tests for survey instruments library."""
import json
import pytest
from pathlib import Path


class TestSurveyInstrumentsLoader:
    """Test the survey instruments loader module."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear module cache before each test."""
        from potato.survey_instruments import clear_cache
        clear_cache()
        yield
        clear_cache()

    def test_get_registry_returns_dict(self):
        """Test that get_registry returns a dictionary."""
        from potato.survey_instruments import get_registry
        registry = get_registry()
        assert isinstance(registry, dict)
        assert "instruments" in registry
        assert "categories" in registry

    def test_get_registry_caching(self):
        """Test that registry is cached after first load."""
        from potato.survey_instruments import get_registry, _registry_cache

        # First call should load
        registry1 = get_registry()

        # Second call should return same object (cached)
        registry2 = get_registry()
        assert registry1 is registry2

    def test_list_instruments_returns_all(self):
        """Test that list_instruments returns all instruments."""
        from potato.survey_instruments import list_instruments, get_registry

        instruments = list_instruments()
        registry = get_registry()

        assert len(instruments) == len(registry["instruments"])
        assert all("id" in inst for inst in instruments)
        assert all("name" in inst for inst in instruments)

    def test_list_instruments_by_category(self):
        """Test filtering instruments by category."""
        from potato.survey_instruments import list_instruments

        mental_health = list_instruments(category="mental_health")
        personality = list_instruments(category="personality")

        assert len(mental_health) > 0
        assert len(personality) > 0
        assert len(mental_health) != len(personality)

        # Check that returned instruments are from the right category
        mental_health_ids = {inst["id"] for inst in mental_health}
        assert "phq-9" in mental_health_ids
        assert "gad-7" in mental_health_ids

    def test_get_instrument_valid_id(self):
        """Test loading a valid instrument."""
        from potato.survey_instruments import get_instrument

        phq9 = get_instrument("phq-9")
        assert phq9["id"] == "phq-9"
        assert "questions" in phq9
        assert len(phq9["questions"]) == 9

    def test_get_instrument_invalid_id(self):
        """Test that invalid instrument ID raises ValueError."""
        from potato.survey_instruments import get_instrument

        with pytest.raises(ValueError) as excinfo:
            get_instrument("nonexistent-instrument")

        assert "Unknown instrument" in str(excinfo.value)
        assert "nonexistent-instrument" in str(excinfo.value)

    def test_get_instrument_caching(self):
        """Test that instruments are cached after loading."""
        from potato.survey_instruments import get_instrument

        inst1 = get_instrument("phq-9")
        inst2 = get_instrument("phq-9")

        assert inst1 is inst2

    def test_get_instrument_questions(self):
        """Test getting just the questions from an instrument."""
        from potato.survey_instruments import get_instrument_questions

        questions = get_instrument_questions("tipi")

        assert isinstance(questions, list)
        assert len(questions) == 10
        assert all("name" in q for q in questions)
        assert all("description" in q for q in questions)
        assert all("annotation_type" in q for q in questions)

    def test_get_categories(self):
        """Test getting category mappings."""
        from potato.survey_instruments import get_categories

        categories = get_categories()

        assert isinstance(categories, dict)
        assert "personality" in categories
        assert "mental_health" in categories
        assert "affect" in categories
        assert "social" in categories
        assert "attitudes" in categories

    def test_clear_cache(self):
        """Test that clear_cache actually clears the cache."""
        from potato.survey_instruments import (
            get_registry, get_instrument, clear_cache,
            _registry_cache, _instruments_cache
        )

        # Load some data
        get_registry()
        get_instrument("phq-9")

        # Clear cache
        clear_cache()

        # Import again to check state
        from potato import survey_instruments
        assert survey_instruments._registry_cache is None
        assert len(survey_instruments._instruments_cache) == 0


class TestInstrumentFileFormat:
    """Test that all instrument JSON files have valid format."""

    @pytest.fixture
    def instruments_dir(self):
        """Get the instruments directory path."""
        return Path(__file__).parent.parent.parent / "potato" / "survey_instruments" / "instruments"

    @pytest.fixture
    def registry_file(self):
        """Get the registry file path."""
        return Path(__file__).parent.parent.parent / "potato" / "survey_instruments" / "registry.json"

    def test_all_registered_instruments_exist(self, instruments_dir, registry_file):
        """Test that all instruments in registry have corresponding files."""
        with open(registry_file) as f:
            registry = json.load(f)

        for inst_id, inst_meta in registry["instruments"].items():
            file_path = instruments_dir / inst_meta["file"]
            assert file_path.exists(), f"Missing instrument file: {inst_meta['file']}"

    def test_all_instrument_files_in_registry(self, instruments_dir, registry_file):
        """Test that all instrument files are registered."""
        with open(registry_file) as f:
            registry = json.load(f)

        registered_files = {meta["file"] for meta in registry["instruments"].values()}
        actual_files = {f.name for f in instruments_dir.glob("*.json")}

        unregistered = actual_files - registered_files
        assert len(unregistered) == 0, f"Unregistered files: {unregistered}"

    def test_instrument_file_structure(self, instruments_dir):
        """Test that all instrument files have required fields."""
        required_fields = ["id", "name", "description", "questions"]
        question_fields = ["name", "description", "annotation_type"]

        for file_path in instruments_dir.glob("*.json"):
            with open(file_path) as f:
                instrument = json.load(f)

            # Check top-level fields
            for field in required_fields:
                assert field in instrument, f"{file_path.name} missing field: {field}"

            # Check questions
            assert len(instrument["questions"]) > 0, f"{file_path.name} has no questions"

            for i, q in enumerate(instrument["questions"]):
                for field in question_fields:
                    assert field in q, \
                        f"{file_path.name} question {i} missing field: {field}"

    def test_instrument_ids_match_filenames(self, instruments_dir):
        """Test that instrument IDs match their filenames."""
        for file_path in instruments_dir.glob("*.json"):
            with open(file_path) as f:
                instrument = json.load(f)

            expected_id = file_path.stem  # filename without .json
            assert instrument["id"] == expected_id, \
                f"{file_path.name}: id '{instrument['id']}' doesn't match filename"

    def test_annotation_types_are_valid(self, instruments_dir):
        """Test that all annotation types are valid Potato types."""
        valid_types = {"radio", "likert", "slider", "multiselect", "textbox"}

        for file_path in instruments_dir.glob("*.json"):
            with open(file_path) as f:
                instrument = json.load(f)

            for q in instrument["questions"]:
                assert q["annotation_type"] in valid_types, \
                    f"{file_path.name} has invalid annotation_type: {q['annotation_type']}"


class TestInstrumentContent:
    """Test content quality of specific instruments."""

    def test_phq9_has_9_items(self):
        """Test PHQ-9 has exactly 9 items."""
        from potato.survey_instruments import get_instrument
        phq9 = get_instrument("phq-9")
        assert len(phq9["questions"]) == 9

    def test_gad7_has_7_items(self):
        """Test GAD-7 has exactly 7 items."""
        from potato.survey_instruments import get_instrument
        gad7 = get_instrument("gad-7")
        assert len(gad7["questions"]) == 7

    def test_tipi_has_10_items(self):
        """Test TIPI has exactly 10 items."""
        from potato.survey_instruments import get_instrument
        tipi = get_instrument("tipi")
        assert len(tipi["questions"]) == 10

    def test_panas_has_20_items(self):
        """Test PANAS has exactly 20 items."""
        from potato.survey_instruments import get_instrument
        panas = get_instrument("panas")
        assert len(panas["questions"]) == 20

    def test_bfi2_has_60_items(self):
        """Test BFI-2 has exactly 60 items."""
        from potato.survey_instruments import get_instrument
        bfi2 = get_instrument("bfi-2")
        assert len(bfi2["questions"]) == 60

    def test_swls_has_5_items(self):
        """Test SWLS has exactly 5 items."""
        from potato.survey_instruments import get_instrument
        swls = get_instrument("swls")
        assert len(swls["questions"]) == 5

    def test_rse_has_10_items(self):
        """Test RSE has exactly 10 items."""
        from potato.survey_instruments import get_instrument
        rse = get_instrument("rse")
        assert len(rse["questions"]) == 10


class TestRegistryIntegrity:
    """Test registry data integrity."""

    def test_category_instruments_exist(self):
        """Test that all instruments in categories exist in main registry."""
        from potato.survey_instruments import get_registry

        registry = get_registry()
        all_instrument_ids = set(registry["instruments"].keys())

        for category, inst_ids in registry["categories"].items():
            for inst_id in inst_ids:
                assert inst_id in all_instrument_ids, \
                    f"Category '{category}' references unknown instrument: {inst_id}"

    def test_all_instruments_in_categories(self):
        """Test that all instruments are assigned to at least one category."""
        from potato.survey_instruments import get_registry

        registry = get_registry()
        all_instrument_ids = set(registry["instruments"].keys())

        categorized_ids = set()
        for inst_ids in registry["categories"].values():
            categorized_ids.update(inst_ids)

        uncategorized = all_instrument_ids - categorized_ids
        assert len(uncategorized) == 0, f"Uncategorized instruments: {uncategorized}"

    def test_instrument_count(self):
        """Test that we have the expected number of instruments."""
        from potato.survey_instruments import get_registry

        registry = get_registry()
        # We should have 55 instruments: 35 original + 12 short-forms + 8 demographics
        assert len(registry["instruments"]) == 55

"""Tests for PartialReader."""

import os
import tempfile
import pytest
from potato.data_sources.partial_reader import (
    PartialReader,
    PartialReadState,
    PartialLoadingConfig,
)


class TestPartialReadState:
    """Tests for PartialReadState dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        state = PartialReadState(source_id="test")

        assert state.items_loaded == 0
        assert state.total_estimate is None
        assert state.is_complete is False
        assert state.file_position == 0
        assert state.line_number == 0

    def test_to_dict_and_from_dict(self):
        """Test serialization round-trip."""
        state = PartialReadState(
            source_id="test_source",
            items_loaded=500,
            total_estimate=1000,
            file_position=12345,
            line_number=500,
            is_complete=False,
            last_loaded_at=1234567890.0,
            metadata={"key": "value"},
        )

        data = state.to_dict()
        restored = PartialReadState.from_dict(data)

        assert restored.source_id == state.source_id
        assert restored.items_loaded == state.items_loaded
        assert restored.total_estimate == state.total_estimate
        assert restored.is_complete == state.is_complete
        assert restored.metadata == state.metadata


class TestPartialLoadingConfig:
    """Tests for PartialLoadingConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = PartialLoadingConfig()

        assert config.enabled is False
        assert config.initial_count == 1000
        assert config.batch_size == 500
        assert config.auto_load_threshold == 0.8
        assert config.auto_load_enabled is True

    def test_from_dict_empty(self):
        """Test creating config from empty dict."""
        config = PartialLoadingConfig.from_dict({})

        assert config.enabled is False
        assert config.initial_count == 1000

    def test_from_dict_with_values(self):
        """Test creating config with custom values."""
        config = PartialLoadingConfig.from_dict({
            "partial_loading": {
                "enabled": True,
                "initial_count": 500,
                "batch_size": 200,
                "auto_load_threshold": 0.5,
            }
        })

        assert config.enabled is True
        assert config.initial_count == 500
        assert config.batch_size == 200
        assert config.auto_load_threshold == 0.5

    def test_validate_valid_config(self):
        """Test validation passes for valid config."""
        config = PartialLoadingConfig(
            enabled=True,
            initial_count=100,
            batch_size=50,
            auto_load_threshold=0.8,
        )

        errors = config.validate()
        assert len(errors) == 0

    def test_validate_invalid_initial_count(self):
        """Test validation fails for invalid initial_count."""
        config = PartialLoadingConfig(initial_count=0)
        errors = config.validate()

        assert len(errors) > 0
        assert any("initial_count" in e for e in errors)

    def test_validate_invalid_batch_size(self):
        """Test validation fails for invalid batch_size."""
        config = PartialLoadingConfig(batch_size=0)
        errors = config.validate()

        assert len(errors) > 0
        assert any("batch_size" in e for e in errors)

    def test_validate_invalid_threshold(self):
        """Test validation fails for invalid threshold."""
        config = PartialLoadingConfig(auto_load_threshold=1.5)
        errors = config.validate()

        assert len(errors) > 0
        assert any("threshold" in e for e in errors)


class TestPartialReader:
    """Tests for PartialReader."""

    @pytest.fixture
    def output_dir(self, tmp_path):
        """Create a temporary output directory."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        return str(out_dir)

    @pytest.fixture
    def config(self):
        """Create a partial loading config."""
        return PartialLoadingConfig(
            enabled=True,
            initial_count=100,
            batch_size=50,
            auto_load_threshold=0.8,
        )

    @pytest.fixture
    def reader(self, config, output_dir):
        """Create a PartialReader."""
        return PartialReader(config, output_dir)

    def test_get_or_create_state(self, reader):
        """Test getting or creating state for a source."""
        state = reader.get_or_create_state("new_source")

        assert state.source_id == "new_source"
        assert state.items_loaded == 0

        # Getting again should return same state
        state2 = reader.get_or_create_state("new_source")
        assert state2.source_id == "new_source"

    def test_update_state(self, reader):
        """Test updating state after loading items."""
        reader.update_state(
            source_id="source1",
            items_added=100,
            file_position=5000,
            line_number=100,
            is_complete=False,
            total_estimate=1000,
        )

        state = reader.get_state("source1")
        assert state.items_loaded == 100
        assert state.file_position == 5000
        assert state.line_number == 100
        assert state.is_complete is False
        assert state.total_estimate == 1000
        assert state.last_loaded_at is not None

    def test_update_state_accumulates(self, reader):
        """Test that update_state accumulates items_loaded."""
        reader.update_state("source1", items_added=50)
        reader.update_state("source1", items_added=50)

        state = reader.get_state("source1")
        assert state.items_loaded == 100

    def test_mark_complete(self, reader):
        """Test marking a source as complete."""
        reader.get_or_create_state("source1")
        reader.mark_complete("source1")

        state = reader.get_state("source1")
        assert state.is_complete is True

    def test_should_load_more_below_threshold(self, reader):
        """Test should_load_more returns False below threshold."""
        reader.get_or_create_state("source1")

        # 50% annotated (below 80% threshold)
        result = reader.should_load_more("source1", annotated_count=50, total_loaded=100)
        assert result is False

    def test_should_load_more_above_threshold(self, reader):
        """Test should_load_more returns True above threshold."""
        reader.get_or_create_state("source1")

        # 85% annotated (above 80% threshold)
        result = reader.should_load_more("source1", annotated_count=85, total_loaded=100)
        assert result is True

    def test_should_load_more_complete_source(self, reader):
        """Test should_load_more returns False for complete source."""
        reader.get_or_create_state("source1")
        reader.mark_complete("source1")

        # Even above threshold, complete source shouldn't load more
        result = reader.should_load_more("source1", annotated_count=90, total_loaded=100)
        assert result is False

    def test_get_load_count_initial(self, reader):
        """Test get_load_count for initial load."""
        count = reader.get_load_count("source1", is_initial=True)
        assert count == 100  # initial_count from config

    def test_get_load_count_subsequent(self, reader):
        """Test get_load_count for subsequent loads."""
        count = reader.get_load_count("source1", is_initial=False)
        assert count == 50  # batch_size from config

    def test_get_start_position(self, reader):
        """Test getting start position for next load."""
        # New source starts at 0
        pos = reader.get_start_position("source1")
        assert pos == 0

        # After loading items
        reader.update_state("source1", items_added=100)
        pos = reader.get_start_position("source1")
        assert pos == 100

    def test_reset_state(self, reader):
        """Test resetting state for a source."""
        reader.update_state("source1", items_added=100)
        reader.reset_state("source1")

        state = reader.get_state("source1")
        assert state is None

    def test_clear_all_state(self, reader):
        """Test clearing all source states."""
        reader.update_state("source1", items_added=100)
        reader.update_state("source2", items_added=200)

        reader.clear_all_state()

        assert reader.get_state("source1") is None
        assert reader.get_state("source2") is None

    def test_get_stats(self, reader):
        """Test getting partial loading statistics."""
        reader.update_state("source1", items_added=100)
        reader.update_state("source2", items_added=200)
        reader.mark_complete("source1")

        stats = reader.get_stats()

        assert stats["enabled"] is True
        assert stats["initial_count"] == 100
        assert stats["batch_size"] == 50
        assert stats["sources_tracked"] == 2
        assert stats["sources_complete"] == 1
        assert stats["total_items_loaded"] == 300

    def test_persistence(self, config, output_dir):
        """Test that state persists across reader instances."""
        reader1 = PartialReader(config, output_dir)
        reader1.update_state("source1", items_added=100, is_complete=True)

        # Create new reader (simulating restart)
        reader2 = PartialReader(config, output_dir)

        state = reader2.get_state("source1")
        assert state is not None
        assert state.items_loaded == 100
        assert state.is_complete is True

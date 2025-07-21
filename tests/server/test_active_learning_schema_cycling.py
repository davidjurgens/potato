"""
Schema Cycling and Multi-Schema Tests for Active Learning

This module contains tests for cycling through schemas, schema-specific stats, order preservation, and schema validation.
"""

import pytest
from potato.active_learning_manager import SchemaCycler

class TestActiveLearningSchemaCycling:
    """Schema cycling and multi-schema tests for active learning."""

    def test_schema_cycling_order(self):
        """Test that schema cycling proceeds in the specified order and wraps around."""
        schemas = ["sentiment", "topic", "urgency"]
        cycler = SchemaCycler(schemas)
        assert cycler.get_schema_order() == schemas
        assert cycler.get_current_schema() == "sentiment"
        cycler.advance_schema()
        assert cycler.get_current_schema() == "topic"
        cycler.advance_schema()
        assert cycler.get_current_schema() == "urgency"
        cycler.advance_schema()
        assert cycler.get_current_schema() == "sentiment"
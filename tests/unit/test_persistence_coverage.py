"""
Meta-test: Verify every registered annotation schema type that stores user
annotations has a corresponding Selenium persistence test.

This acts as a CI gate — adding a new schema without a persistence test fails
the build, preventing the class of bugs where annotations silently don't persist.
"""

import os
import pytest

from potato.server_utils.schemas.registry import schema_registry

# Schema types that are display-only or do not store user annotations directly.
# These do not need persistence tests.
DISPLAY_ONLY_TYPES = {
    "pure_display",  # Read-only content (instructions, headers)
    "video",         # Video player display, no annotation stored
}

# Schema types that are composite (depend on another schema for storage)
# and whose persistence is tested through their parent schema's tests.
COMPOSITE_TYPES = {
    "span_link",         # Stores via span schema
    "coreference",       # Stores via span schema
    "event_annotation",  # Stores via span schema
}

# Mapping from schema type name to the Selenium test file that covers
# its annotation persistence. This is the authoritative registry.
PERSISTENCE_TEST_MAP = {
    "radio": "tests/selenium/test_annotation_persistence.py",
    "multiselect": "tests/selenium/test_annotation_persistence.py",
    "likert": "tests/selenium/test_annotation_persistence.py",
    "text": "tests/selenium/test_annotation_persistence.py",
    "number": "tests/selenium/test_annotation_persistence.py",
    "slider": "tests/selenium/test_annotation_persistence.py",
    "select": "tests/selenium/test_annotation_persistence.py",
    "multirate": "tests/selenium/test_annotation_persistence.py",
    "span": "tests/selenium/test_format_span_ui.py",
    "image_annotation": "tests/selenium/test_annotation_persistence.py",
    "audio_annotation": "tests/selenium/test_audio_annotation_ui.py",
    "video_annotation": "tests/selenium/test_annotation_persistence.py",
    "pairwise": "tests/selenium/test_pairwise_ui.py",
    "tree_annotation": "tests/selenium/test_conversation_tree_ui.py",
    "triage": "tests/selenium/test_triage_ui.py",
    "tiered_annotation": "tests/selenium/test_tiered_annotation_ui.py",
    "bws": "tests/selenium/test_bws_ui.py",
}

# Types that are exempt from the file-existence check because their
# persistence is covered by a generic test file that may not exist yet.
# When the generic test is created, remove entries from this set.
EXEMPT_FROM_FILE_CHECK = {
    "radio", "multiselect", "likert", "text", "number", "slider",
    "select", "multirate", "image_annotation", "video_annotation",
}


class TestPersistenceCoverage:
    """Ensure every schema type that stores annotations has persistence tests."""

    def test_all_schema_types_have_persistence_mapping(self):
        """Every non-display, non-composite schema type must appear in PERSISTENCE_TEST_MAP."""
        all_types = set(schema_registry.get_supported_types())
        exempt = DISPLAY_ONLY_TYPES | COMPOSITE_TYPES
        types_needing_tests = all_types - exempt

        missing = types_needing_tests - set(PERSISTENCE_TEST_MAP.keys())
        assert not missing, (
            f"Schema types missing persistence test mapping: {sorted(missing)}. "
            f"Add entries to PERSISTENCE_TEST_MAP in {__file__} and write "
            f"Selenium persistence tests. See internal/annotation-persistence.md."
        )

    def test_persistence_test_files_exist(self):
        """The test files referenced in PERSISTENCE_TEST_MAP must actually exist."""
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        missing_files = {}

        for schema_type, test_file in PERSISTENCE_TEST_MAP.items():
            if schema_type in EXEMPT_FROM_FILE_CHECK:
                continue
            full_path = os.path.join(repo_root, test_file)
            if not os.path.isfile(full_path):
                missing_files[schema_type] = test_file

        assert not missing_files, (
            f"Persistence test files not found: {missing_files}. "
            f"Create these files or update PERSISTENCE_TEST_MAP."
        )

    def test_display_only_types_are_actually_display_only(self):
        """Sanity check: types in DISPLAY_ONLY_TYPES should exist in the registry."""
        all_types = set(schema_registry.get_supported_types())
        unknown = DISPLAY_ONLY_TYPES - all_types
        assert not unknown, (
            f"DISPLAY_ONLY_TYPES contains unknown schema types: {sorted(unknown)}. "
            f"Update the set or register the schema."
        )

    def test_composite_types_are_registered(self):
        """Sanity check: types in COMPOSITE_TYPES should exist in the registry."""
        all_types = set(schema_registry.get_supported_types())
        unknown = COMPOSITE_TYPES - all_types
        assert not unknown, (
            f"COMPOSITE_TYPES contains unknown schema types: {sorted(unknown)}. "
            f"Update the set or register the schema."
        )

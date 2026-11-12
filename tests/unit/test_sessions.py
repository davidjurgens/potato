"""
Unit tests for D1 session-level scoring.

Covers: the case_annotations store (upsert/delete/round-trip/project
join), sessions service (enablement, scheme discovery, aggregates,
export writer), and session_level config validation.
"""

import json

import pytest

from potato.cases import get_or_create_case, assign_instance
from potato.cases.annotations import (
    _CASE_ANNOTATIONS_MIGRATION,
    annotations_for_case,
    annotations_for_project,
    set_annotation,
)
from potato.cases.store import _CASES_MIGRATION
from potato.persistence import (
    clear_db_cache,
    clear_migrations,
    register_migration,
)
from potato.sessions.service import (
    SESSION_LEVEL_SUPPORTED_TYPES,
    get_session_level_schemes,
    session_aggregates,
    sessions_enabled,
    sessions_project,
    write_session_export,
)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(_CASES_MIGRATION)
    register_migration(_CASE_ANNOTATIONS_MIGRATION)
    yield
    clear_db_cache()
    clear_migrations()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


class TestCaseAnnotationsStore:
    def test_round_trip(self, td):
        c = get_or_create_case(td, project="P::sessions", name="sess-1")
        set_annotation(td, case_id=c["id"], annotator="alice",
                       schema="session_quality", value={"value": 4})
        rows = annotations_for_case(td, c["id"])
        assert len(rows) == 1
        assert rows[0]["value"] == {"value": 4}
        assert rows[0]["annotator"] == "alice"

    def test_upsert_replaces(self, td):
        c = get_or_create_case(td, project="P::sessions", name="sess-1")
        set_annotation(td, case_id=c["id"], annotator="alice",
                       schema="q", value={"value": 2})
        set_annotation(td, case_id=c["id"], annotator="alice",
                       schema="q", value={"value": 5})
        rows = annotations_for_case(td, c["id"], annotator="alice")
        assert len(rows) == 1 and rows[0]["value"] == {"value": 5}

    def test_none_value_deletes(self, td):
        c = get_or_create_case(td, project="P::sessions", name="sess-1")
        set_annotation(td, case_id=c["id"], annotator="alice",
                       schema="q", value={"value": 2})
        set_annotation(td, case_id=c["id"], annotator="alice",
                       schema="q", value=None)
        assert annotations_for_case(td, c["id"]) == []

    def test_annotator_filter(self, td):
        c = get_or_create_case(td, project="P::sessions", name="sess-1")
        set_annotation(td, case_id=c["id"], annotator="alice",
                       schema="q", value={"value": 1})
        set_annotation(td, case_id=c["id"], annotator="bob",
                       schema="q", value={"value": 3})
        assert len(annotations_for_case(td, c["id"])) == 2
        mine = annotations_for_case(td, c["id"], annotator="bob")
        assert len(mine) == 1 and mine[0]["value"] == {"value": 3}

    def test_project_join_carries_case_name(self, td):
        c = get_or_create_case(td, project="P::sessions", name="sess-9")
        other = get_or_create_case(td, project="OTHER", name="x")
        set_annotation(td, case_id=c["id"], annotator="a",
                       schema="q", value={"values": ["good"]})
        set_annotation(td, case_id=other["id"], annotator="a",
                       schema="q", value={"value": 1})
        rows = annotations_for_project(td, "P::sessions")
        assert len(rows) == 1
        assert rows[0]["case_name"] == "sess-9"
        assert rows[0]["value"] == {"values": ["good"]}


class TestSessionsService:
    def test_enablement_and_namespace(self):
        assert not sessions_enabled({})
        assert not sessions_enabled({"sessions": {}})
        assert sessions_enabled({"sessions": {"enabled": True}})
        assert sessions_project(
            {"annotation_task_name": "T"}) == "T::sessions"
        assert sessions_project({}) == "default::sessions"

    def test_scheme_discovery_top_level(self):
        config = {"annotation_schemes": [
            {"name": "a", "annotation_type": "likert", "session_level": True},
            {"name": "b", "annotation_type": "radio"},
        ]}
        assert [s["name"] for s in get_session_level_schemes(config)] == ["a"]

    def test_scheme_discovery_phases(self):
        config = {"phases": {
            "order": ["main"],
            "main": {"annotation_schemes": [
                {"name": "s", "annotation_type": "radio",
                 "session_level": True},
            ]},
        }}
        assert [s["name"] for s in get_session_level_schemes(config)] == ["s"]

    def test_supported_types_are_registered(self):
        from potato.server_utils.schemas.registry import schema_registry
        registered = set(schema_registry.get_supported_types())
        assert SESSION_LEVEL_SUPPORTED_TYPES <= registered


class TestAggregates:
    def test_numeric_mean(self):
        agg = session_aggregates([
            {"schema": "q", "annotator": "a", "value": {"value": 2}},
            {"schema": "q", "annotator": "b", "value": {"value": 4}},
        ])
        assert agg["q"]["n_annotators"] == 2
        assert agg["q"]["mean"] == 3.0
        assert agg["q"]["value_counts"] == {}

    def test_categorical_counts(self):
        agg = session_aggregates([
            {"schema": "q", "annotator": "a", "value": {"values": ["good", "fast"]}},
            {"schema": "q", "annotator": "b", "value": {"values": ["good"]}},
        ])
        assert agg["q"]["value_counts"] == {"good": 2, "fast": 1}
        assert agg["q"]["mean"] is None

    def test_numeric_strings_count_as_numeric(self):
        agg = session_aggregates([
            {"schema": "q", "annotator": "a", "value": {"value": "3"}},
        ])
        assert agg["q"]["mean"] == 3.0

    def test_empty(self):
        assert session_aggregates([]) == {}


class TestExportWriter:
    def test_writes_jsonl(self, td):
        project = "T::sessions"
        c = get_or_create_case(td, project=project, name="sess-1")
        assign_instance(td, project=project, instance_id="tr-1",
                        case_id=c["id"])
        set_annotation(td, case_id=c["id"], annotator="alice",
                       schema="session_quality", value={"value": 5})

        config = {"task_dir": td, "annotation_task_name": "T",
                  "output_annotation_dir": "out"}
        path = write_session_export(config)
        assert path is not None
        with open(path) as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert len(rows) == 1
        assert rows[0]["session"] == "sess-1"
        assert rows[0]["annotator"] == "alice"
        assert rows[0]["value"] == {"value": 5}
        assert rows[0]["instance_ids"] == ["tr-1"]


class TestConfigValidation:
    def test_session_level_unsupported_type_rejected(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_single_annotation_scheme)
        scheme = {"annotation_type": "span", "name": "s",
                  "description": "d", "labels": ["x"],
                  "session_level": True}
        with pytest.raises(ConfigValidationError, match="session_level"):
            validate_single_annotation_scheme(scheme, "t")

    def test_session_and_turn_level_mutually_exclusive(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_single_annotation_scheme)
        scheme = {"annotation_type": "radio", "name": "s",
                  "description": "d", "labels": ["x"],
                  "session_level": True, "turn_level": True}
        with pytest.raises(ConfigValidationError,
                           match="turn_level and session_level"):
            validate_single_annotation_scheme(scheme, "t")

    def test_session_level_radio_accepted(self):
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme)
        scheme = {"annotation_type": "radio", "name": "s",
                  "description": "d", "labels": ["x", "y"],
                  "session_level": True}
        validate_single_annotation_scheme(scheme, "t")  # should not raise


class TestSchematicInterception:
    def test_session_level_scheme_renders_note_only(self):
        from potato.server_utils.front_end import generate_schematic
        html, keybindings = generate_schematic({
            "annotation_type": "likert", "name": "session_quality",
            "description": "Overall quality", "size": 5,
            "session_level": True,
        })
        assert keybindings == []
        assert "session-level-note" in html
        assert "annotation-input" not in html
        assert "annotation-form" not in html

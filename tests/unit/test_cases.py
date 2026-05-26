"""Unit tests for potato.cases store + service (auto-detect, attrs)."""

import pytest

from potato.cases import (
    assign_instance,
    attribute_for_instance,
    attributes,
    auto_detect,
    case_for_instance,
    cases_enabled,
    get_or_create_case,
    list_cases,
    set_attribute,
)
from potato.cases.store import _CASES_MIGRATION
from potato.persistence import (
    clear_db_cache,
    clear_migrations,
    register_migration,
)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(_CASES_MIGRATION)
    yield
    clear_db_cache()
    clear_migrations()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


class TestGetOrCreate:
    def test_idempotent(self, td):
        a = get_or_create_case(td, project="P", name="P01")
        b = get_or_create_case(td, project="P", name="P01")
        assert a["id"] == b["id"]
        assert len(list_cases(td, "P")) == 1

    def test_scoped_by_project(self, td):
        get_or_create_case(td, project="P", name="x")
        get_or_create_case(td, project="Q", name="x")
        assert len(list_cases(td, "P")) == 1
        assert len(list_cases(td, "Q")) == 1


class TestAttributesAndMembership:
    def test_attribute_roundtrip(self, td):
        c = get_or_create_case(td, project="P", name="P01")
        set_attribute(td, c["id"], "condition", "treatment")
        assert attributes(td, c["id"]) == {"condition": "treatment"}

    def test_instance_membership_and_lookup(self, td):
        c = get_or_create_case(td, project="P", name="P01")
        assign_instance(td, project="P", instance_id="i1", case_id=c["id"])
        found = case_for_instance(td, "P", "i1")
        assert found["id"] == c["id"]

    def test_attribute_for_instance(self, td):
        c = get_or_create_case(td, project="P", name="P01")
        set_attribute(td, c["id"], "age", "42")
        assign_instance(td, project="P", instance_id="i1", case_id=c["id"])
        assert attribute_for_instance(td, "P", "i1", "age") == "42"
        assert attribute_for_instance(td, "P", "i1", "missing") is None
        assert attribute_for_instance(td, "P", "unknown", "age") is None

    def test_one_case_per_instance(self, td):
        a = get_or_create_case(td, project="P", name="A")
        b = get_or_create_case(td, project="P", name="B")
        assign_instance(td, project="P", instance_id="i1", case_id=a["id"])
        assign_instance(td, project="P", instance_id="i1", case_id=b["id"])
        assert case_for_instance(td, "P", "i1")["id"] == b["id"]


class TestAutoDetect:
    def test_groups_by_participant_id(self, td):
        items = [
            {"id": "1", "participant_id": "P01", "text": "a"},
            {"id": "2", "participant_id": "P01", "text": "b"},
            {"id": "3", "participant_id": "P02", "text": "c"},
        ]
        res = auto_detect(td, project="P", items=items)
        assert res == {"cases": 2, "assigned": 3}
        assert case_for_instance(td, "P", "1")["name"] == "P01"
        assert case_for_instance(td, "P", "3")["name"] == "P02"

    def test_priority_order_case_id_first(self, td):
        items = [{"id": "1", "case_id": "C9", "participant_id": "P01"}]
        auto_detect(td, project="P", items=items)
        assert case_for_instance(td, "P", "1")["name"] == "C9"

    def test_explicit_key_overrides_defaults(self, td):
        items = [{"id": "1", "respondent": "R7", "participant_id": "P01"}]
        auto_detect(td, project="P", items=items, case_key="respondent")
        assert case_for_instance(td, "P", "1")["name"] == "R7"

    def test_lifts_attributes(self, td):
        items = [{"id": "1", "participant_id": "P01",
                  "condition": "control", "age": 30}]
        auto_detect(td, project="P", items=items,
                    attribute_keys=["condition", "age"])
        assert attribute_for_instance(td, "P", "1", "condition") == "control"
        assert attribute_for_instance(td, "P", "1", "age") == "30"

    def test_idempotent(self, td):
        items = [{"id": "1", "participant_id": "P01"}]
        auto_detect(td, project="P", items=items)
        auto_detect(td, project="P", items=items)
        assert len(list_cases(td, "P")) == 1

    def test_items_without_case_key_skipped(self, td):
        res = auto_detect(td, project="P", items=[{"id": "1", "text": "x"}])
        assert res == {"cases": 0, "assigned": 0}


class TestCasesEnabled:
    def test_explicit_enabled(self):
        assert cases_enabled({"cases": {"enabled": True}}) is True

    def test_explicit_disabled_overrides_qda(self):
        assert cases_enabled(
            {"cases": {"enabled": False},
             "qda_mode": {"enabled": True}}) is False

    def test_qda_implies_enabled(self):
        assert cases_enabled({"qda_mode": {"enabled": True}}) is True

    def test_standard_default_off(self):
        assert cases_enabled({}) is False

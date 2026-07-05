"""Unit tests for the per-cohort schema resolver."""

import pytest

from potato.server_utils.cohort_schemes import (
    CohortSchemeResolver,
    clear_cohort_scheme_resolver,
)


_SCHEMES = [
    {"name": "sentiment", "annotation_type": "radio", "labels": ["pos", "neg"]},
    {"name": "topic", "annotation_type": "radio", "labels": ["a", "b"]},
    {"name": "quality", "annotation_type": "radio", "labels": ["good", "bad"]},
]


def _config(**overrides):
    cfg = {
        "annotation_schemes": _SCHEMES,
        "scheme_sets": {"minimal": ["sentiment"]},
        "batch_assignment": {
            "groups": [
                {"name": "cohortA", "annotators": ["alice"], "schemes": "minimal"},
                {"name": "cohortB", "annotators": ["bob"], "schemes": ["sentiment", "topic"]},
                {"name": "cohortC", "annotators": ["carol"]},  # no schemes -> global
            ]
        },
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture(autouse=True)
def _clear():
    clear_cohort_scheme_resolver()
    yield
    clear_cohort_scheme_resolver()


def _names(schemes):
    return [s["name"] for s in schemes]


def test_named_scheme_set_resolves():
    r = CohortSchemeResolver(_config())
    assert _names(r.get_schemes_for_cohort("cohortA")) == ["sentiment"]


def test_inline_name_list_resolves():
    r = CohortSchemeResolver(_config())
    assert _names(r.get_schemes_for_cohort("cohortB")) == ["sentiment", "topic"]


def test_group_without_schemes_falls_back_to_global():
    r = CohortSchemeResolver(_config())
    assert _names(r.get_schemes_for_cohort("cohortC")) == ["sentiment", "topic", "quality"]


def test_unknown_cohort_falls_back_to_global():
    r = CohortSchemeResolver(_config())
    assert _names(r.get_schemes_for_cohort("ghost")) == ["sentiment", "topic", "quality"]
    assert _names(r.get_schemes_for_cohort(None)) == ["sentiment", "topic", "quality"]


def test_inline_scheme_dict_member():
    cfg = _config()
    cfg["batch_assignment"]["groups"][0]["schemes"] = [
        "sentiment",
        {"name": "adhoc", "annotation_type": "textbox"},
    ]
    r = CohortSchemeResolver(cfg)
    assert _names(r.get_schemes_for_cohort("cohortA")) == ["sentiment", "adhoc"]


def test_union_of_all_schemes_dedups_by_name():
    r = CohortSchemeResolver(_config())
    # global has all three; cohorts add nothing new -> union == global order.
    assert _names(r.union_of_all_schemes()) == ["sentiment", "topic", "quality"]


def test_union_includes_cohort_only_schemes():
    cfg = _config()
    cfg["annotation_schemes"] = [_SCHEMES[0]]  # global only has sentiment
    cfg["batch_assignment"]["groups"][1]["schemes"] = [
        "sentiment",
        {"name": "cohort_only", "annotation_type": "textbox"},
    ]
    r = CohortSchemeResolver(cfg)
    assert "cohort_only" in _names(r.union_of_all_schemes())


def test_has_cohort_schemes():
    assert CohortSchemeResolver(_config()).has_cohort_schemes()
    assert not CohortSchemeResolver(
        {"annotation_schemes": _SCHEMES}
    ).has_cohort_schemes()


def test_no_batch_assignment_returns_global():
    r = CohortSchemeResolver({"annotation_schemes": _SCHEMES})
    assert _names(r.get_schemes_for_user("anyone")) == ["sentiment", "topic", "quality"]


def test_scheme_names_for_user_fallback():
    r = CohortSchemeResolver({"annotation_schemes": _SCHEMES})
    assert r.scheme_names_for_user("anyone") == {"sentiment", "topic", "quality"}


def test_deep_copy_isolates_mutation():
    r = CohortSchemeResolver(_config())
    copies = r.deep_copy_cohort_schemes()
    # Mutating a copy must not touch the resolver's stored schemes or the global.
    copies["cohortB"][0]["annotation_id"] = 99
    assert "annotation_id" not in r.get_schemes_for_cohort("cohortB")[0]
    assert "annotation_id" not in _SCHEMES[0]


def test_layout_name_slug():
    r = CohortSchemeResolver(_config())
    assert r.layout_name_for_cohort("Cohort A!") == "cohort-a"
    assert r.layout_name_for_cohort("") == "cohort"

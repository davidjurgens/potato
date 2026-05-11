"""Unit tests for the code co-occurrence and crosstab admin analytics methods.

These exercise the AdminDashboard methods in isolation, mocking
get_item_state_manager / get_user_state_manager / get_users so we don't need a
real Flask server.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _FakeUserState:
    def __init__(self, annotations_by_instance):
        self._anns = annotations_by_instance

    def get_all_annotations(self):
        return self._anns


class _FakeItem:
    def __init__(self, item_id, data=None):
        self._id = item_id
        self.data = data or {}

    def get_id(self):
        return self._id


@pytest.fixture
def admin_dashboard():
    """Create an AdminDashboard instance bypassing the admin-access check."""
    from potato.admin import AdminDashboard
    dash = AdminDashboard()
    dash.check_admin_access = lambda: True
    return dash


def _patch_admin_globals(items, user_to_anns):
    """Patch the three globals get_code_*_matrix() reads."""
    ism = SimpleNamespace(items=lambda: items)
    user_states = {u: _FakeUserState(anns) for u, anns in user_to_anns.items()}
    usm = SimpleNamespace(get_user_state=lambda u: user_states.get(u))
    return [
        patch("potato.admin.get_item_state_manager", lambda: ism),
        patch("potato.admin.get_user_state_manager", lambda: usm),
        patch("potato.admin.get_users", lambda: list(user_to_anns.keys())),
    ]


class TestCooccurrence:
    def test_counts_pair_when_two_codes_applied_to_same_instance(self, admin_dashboard):
        items = [_FakeItem("i1"), _FakeItem("i2")]
        user_anns = {
            "u1": {
                "i1": {"labels": {"themes": {"frustration": 1, "delight": 1}}},
                "i2": {"labels": {"themes": {"frustration": 1}}},
            },
        }
        patches = _patch_admin_globals(items, user_anns)
        for p in patches: p.start()
        try:
            result = admin_dashboard.get_code_cooccurrence_matrix()
        finally:
            for p in patches: p.stop()

        assert result["n_instances"] == 2
        assert any(
            p["count"] == 1
            and {p["code_a"], p["code_b"]} == {"themes::frustration", "themes::delight"}
            for p in result["pairs"]
        )

    def test_min_count_filter(self, admin_dashboard):
        items = [_FakeItem("i1"), _FakeItem("i2")]
        user_anns = {
            "u1": {
                "i1": {"labels": {"t": {"a": 1, "b": 1}}},
                "i2": {"labels": {"t": {"a": 1}}},
            },
        }
        patches = _patch_admin_globals(items, user_anns)
        for p in patches: p.start()
        try:
            result = admin_dashboard.get_code_cooccurrence_matrix(min_count=2)
        finally:
            for p in patches: p.stop()
        assert result["pairs"] == []

    def test_dedupes_within_instance_across_annotators(self, admin_dashboard):
        """Two annotators applying the same pair to one instance counts once."""
        items = [_FakeItem("i1")]
        user_anns = {
            "u1": {"i1": {"labels": {"t": {"a": 1, "b": 1}}}},
            "u2": {"i1": {"labels": {"t": {"a": 1, "b": 1}}}},
        }
        patches = _patch_admin_globals(items, user_anns)
        for p in patches: p.start()
        try:
            result = admin_dashboard.get_code_cooccurrence_matrix()
        finally:
            for p in patches: p.stop()
        assert result["pairs"][0]["count"] == 1

    def test_schema_filter(self, admin_dashboard):
        items = [_FakeItem("i1")]
        user_anns = {
            "u1": {"i1": {
                "labels": {"sentiment": {"pos": 1}, "topic": {"food": 1}},
            }},
        }
        patches = _patch_admin_globals(items, user_anns)
        for p in patches: p.start()
        try:
            result = admin_dashboard.get_code_cooccurrence_matrix(schema_filter="sentiment")
        finally:
            for p in patches: p.stop()
        # only one code passes the filter, so no pairs
        assert result["pairs"] == []
        assert result["codes"] == ["sentiment::pos"]


class TestCrosstab:
    def test_pivots_codes_by_attribute(self, admin_dashboard):
        items = [
            _FakeItem("i1", data={"site": "A", "text": "x"}),
            _FakeItem("i2", data={"site": "A", "text": "y"}),
            _FakeItem("i3", data={"site": "B", "text": "z"}),
        ]
        user_anns = {
            "u1": {
                "i1": {"labels": {"t": {"frustration": 1}}},
                "i2": {"labels": {"t": {"frustration": 1, "delight": 1}}},
                "i3": {"labels": {"t": {"delight": 1}}},
            },
        }
        patches = _patch_admin_globals(items, user_anns)
        for p in patches: p.start()
        try:
            result = admin_dashboard.get_code_crosstab(attribute_key="site")
        finally:
            for p in patches: p.stop()

        cells = {(c["code"], c["value"]): c["count"] for c in result["cells"]}
        assert cells[("t::frustration", "A")] == 2
        assert cells[("t::delight", "A")] == 1
        assert cells[("t::delight", "B")] == 1
        assert ("t::frustration", "B") not in cells
        assert set(result["values"]) == {"A", "B"}
        assert result["n_instances"] == 3

    def test_skips_instances_missing_attribute(self, admin_dashboard):
        items = [
            _FakeItem("i1", data={"site": "A"}),
            _FakeItem("i2", data={}),
        ]
        user_anns = {"u1": {
            "i1": {"labels": {"t": {"x": 1}}},
            "i2": {"labels": {"t": {"x": 1}}},
        }}
        patches = _patch_admin_globals(items, user_anns)
        for p in patches: p.start()
        try:
            result = admin_dashboard.get_code_crosstab(attribute_key="site")
        finally:
            for p in patches: p.stop()
        assert result["n_instances"] == 1
        assert result["cells"] == [{"code": "t::x", "value": "A", "count": 1}]

    def test_missing_attribute_key_errors(self, admin_dashboard):
        result = admin_dashboard.get_code_crosstab(attribute_key="")
        assert isinstance(result, tuple)
        assert result[1] == 400

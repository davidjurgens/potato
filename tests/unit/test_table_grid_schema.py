"""Unit tests for the table_grid schema (M16)."""

from potato.server_utils.schemas.table_grid import generate_table_grid_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "table_grid", "name": "tbl",
            "description": "Annotate the table structure"}
    base.update(kw)
    return base


class TestTableGrid:
    def test_generates_container_and_input(self):
        html, kb = generate_table_grid_layout(_scheme())
        assert "table-grid-container" in html and "table-grid-input" in html
        assert kb == []

    def test_default_roles(self):
        html, _ = generate_table_grid_layout(_scheme())
        for r in ("data", "col_header", "row_header", "empty"):
            assert r in html

    def test_default_dims(self):
        html, _ = generate_table_grid_layout(_scheme(default_rows=5, default_cols=4))
        assert '"default_rows": 5' in html and '"default_cols": 4' in html

    def test_custom_roles(self):
        html, _ = generate_table_grid_layout(_scheme(roles=["data", "header", "merged"]))
        assert '"roles": ["data", "header", "merged"]' in html

    def test_persistence_seeds_from_hidden(self):
        html, _ = generate_table_grid_layout(_scheme())
        assert "function restore()" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "table_grid" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "table_grid", "name": "x", "description": "d"})
        assert "table-grid-container" in html

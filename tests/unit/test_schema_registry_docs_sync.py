"""Drift guards for the annotation-schema registry.

The schema registry is the single source of truth for which `annotation_type`
values exist. `docs/annotation-types/schemas_and_templates.md` is where an admin
goes to find out what those values are called, and it drifted badly: when v2.8.0
shipped, the page named 39 of the 61 registered types, and every one of the five
types that release added was among the missing 22. A type absent from the page
is one nobody can find, however well it works.

`tests/unit/test_display_registry_docs_sync.py` guards the display registry the
same way. These tests are the schema-side counterpart, and fail when a type is
registered without a reference-table row, or when the table names a type the
registry does not serve.
"""

import re
from pathlib import Path

import pytest

from potato.server_utils.schemas.registry import schema_registry


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DOC = REPO_ROOT / "docs" / "annotation-types" / "schemas_and_templates.md"


def _registered_types():
    return {s["name"] for s in schema_registry.list_schemas()}


def _doc_text():
    return SCHEMA_DOC.read_text(encoding="utf-8")


def _table_rows():
    """Rows of the reference table, as {type: (details, example)}.

    Rows look like ``| `radio` | Description | [below](#...) | `examples/x/y/` |``.
    Matching on the leading-pipe-then-backticked-name shape keeps the many prose
    and YAML mentions of a type from counting as a row.
    """
    rows = {}
    pattern = re.compile(
        r"^\|\s*`([a-z_0-9]+)`\s*\|[^|]*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$",
        flags=re.MULTILINE,
    )
    for match in pattern.finditer(_doc_text()):
        rows[match.group(1)] = (match.group(2), match.group(3))
    return rows


class TestSchemaDocsSync:
    """The reference table must name every registered type, and no others."""

    def test_doc_file_exists(self):
        assert SCHEMA_DOC.is_file(), f"Schema reference doc missing: {SCHEMA_DOC}"

    def test_every_registered_type_is_documented(self):
        missing = _registered_types() - set(_table_rows())
        assert not missing, (
            "Annotation types registered but absent from the reference table in "
            f"docs/annotation-types/schemas_and_templates.md: {sorted(missing)}. "
            "Admins find annotation types by scanning that table; a type missing "
            "from it is effectively undiscoverable. Add a row of the form "
            "`| `type_name` | What it does | Details | Example |`."
        )

    def test_no_documented_type_is_unregistered(self):
        phantom = set(_table_rows()) - _registered_types()
        assert not phantom, (
            "The reference table documents annotation types the registry does "
            f"not serve: {sorted(phantom)}. Either register them or remove the "
            "rows — a documented type that fails config validation is worse than "
            "an undocumented one."
        )

    def test_config_validation_prefers_the_registry(self):
        """`annotation_type` validation must not grow a second hardcoded list."""
        import inspect

        from potato.server_utils import config_module

        src = inspect.getsource(config_module.validate_single_annotation_scheme)
        assert "schema_registry.get_supported_types()" in src, (
            "validate_single_annotation_scheme no longer sources valid types "
            "from schema_registry.get_supported_types(); the registry and the "
            "config validator can now drift out of sync."
        )


class TestSchemaDocPointers:
    """Every row must point somewhere that exists."""

    def test_detail_links_resolve(self):
        broken = []
        for schema_type, (details, _example) in _table_rows().items():
            for target in re.findall(r"\]\(([^)#][^)]*)\)", details):
                if not (SCHEMA_DOC.parent / target).exists():
                    broken.append((schema_type, target))
        assert not broken, f"Reference-table Details links point at missing files: {broken}"

    def test_detail_anchors_resolve(self):
        headings = set()
        for heading in re.findall(r"^###\s+(.+?)\s*$", _doc_text(), flags=re.MULTILINE):
            slug = re.sub(r"[^\w\s-]", "", heading.lower()).strip().replace(" ", "-")
            headings.add(slug)
        broken = []
        for schema_type, (details, _example) in _table_rows().items():
            for anchor in re.findall(r"\]\(#([^)]+)\)", details):
                if anchor not in headings:
                    broken.append((schema_type, anchor))
        assert not broken, (
            f"Reference-table Details anchors point at missing sections: {broken}"
        )

    def test_example_directories_exist(self):
        broken = []
        for schema_type, (_details, example) in _table_rows().items():
            for path in re.findall(r"`(examples/[^`]+?)/`", example):
                if not (REPO_ROOT / path).is_dir():
                    broken.append((schema_type, path))
        assert not broken, f"Reference-table Example paths point at missing directories: {broken}"

    def test_example_configs_actually_use_their_type(self):
        """A row's example must configure the type the row is about."""
        mismatched = []
        for schema_type, (_details, example) in _table_rows().items():
            for path in re.findall(r"`(examples/[^`]+?)/`", example):
                config = REPO_ROOT / path / "config.yaml"
                if not config.is_file():
                    mismatched.append((schema_type, path, "no config.yaml"))
                    continue
                text = config.read_text(encoding="utf-8", errors="ignore")
                if not re.search(
                    rf'annotation_type:\s*["\']?{re.escape(schema_type)}["\']?\s*$',
                    text,
                    flags=re.MULTILINE,
                ):
                    mismatched.append((schema_type, path, "type not configured"))
        assert not mismatched, (
            "Reference-table examples do not configure the type they illustrate: "
            f"{mismatched}"
        )


def test_every_registered_type_has_a_worked_example():
    """A type with no example config is a type nobody can copy.

    `annotation-types.md` in the agent pack promises a worked example per type
    and prints "_No example config ships with this type._" where there is none.
    That happened once and nothing failed: `video` was registered, documented,
    and had no example anywhere in `examples/`, so an agent reaching for it got
    a field list and no idea what a working one looks like.

    The neighbouring test only checks the examples that *are* named. This checks
    that each type has one at all.
    """
    from potato.server_utils.schema_examples import example_scheme_for
    from potato.server_utils.schemas.registry import schema_registry

    missing = sorted(
        name for name in schema_registry.get_supported_types()
        if not example_scheme_for(name)
    )
    assert not missing, (
        f"No example config uses these registered annotation types: {missing}. "
        f"Add one under examples/<category>/<name>/ -- a type nobody can copy "
        f"is a type an agent will guess at."
    )

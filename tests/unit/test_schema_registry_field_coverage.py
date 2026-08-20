"""Drift guard: every config key a schema module reads must be declared.

`schema_registry` is the only place that says which keys an `annotation_scheme`
entry may carry. `potato/schemas/potato-config.schema.json`, the published JSON
Schema an editor resolves, and `docs/configuration/config_reference.md` are all
generated from it, so a key a generator reads but the registry never declares is
invisible to every downstream consumer — an editor underlines a working option,
and an agent writing a config from the schema will not emit it.

Five such keys shipped at once (`image_annotation.text_prompt`,
`video_annotation.ai_support` / `.source_field`, `likert.labels`,
`span.codebook`), found only when the website docs were audited against the
committed spec: the docs were right and the registry was wrong. This test walks
each type's schema module for the keys it actually reads and diffs them against
what the registry declares, so the next one fails here instead.

Only *reads* are checked. A declared-but-unread key is a different defect (see
`number`'s `min`/`max`/`step`, which were declared for releases before the
generator learned to honor them) and is not detectable by static means alone.
"""

import ast
import inspect
from pathlib import Path

import pytest

from potato.server_utils.schemas.registry import (
    INTERNAL_SCHEME_FIELDS,
    UNIVERSAL_OPTIONAL_FIELDS,
    UNIVERSAL_REQUIRED_FIELDS,
    schema_registry,
)


#: Local names that hold an annotation_scheme dict inside a schema module.
_SCHEME_VARS = {"annotation_scheme", "annotation_schema", "scheme"}

#: Keys read from a scheme dict that are not configuration:
#:   - INTERNAL_SCHEME_FIELDS: written by the server before rendering.
#:   - a leading underscore: same, by convention.
#: Anything else a module reads has to be declared.
def _is_internal(key: str) -> bool:
    return key.startswith("_") or key in INTERNAL_SCHEME_FIELDS


class _SchemeKeyVisitor(ast.NodeVisitor):
    """Collect literal keys read off an annotation_scheme dict.

    Walking the AST rather than grepping is what keeps docstrings out: a
    ``process_reward`` docstring naming its ``first_error`` mode value, or
    ``rubric_eval``'s internal ``overall`` criteria name, are prose and not
    reads, and a text search cannot tell the difference.
    """

    def __init__(self):
        self.keys = {}  # key -> lineno of first read

    def _add(self, key, node):
        if isinstance(key, str):
            self.keys.setdefault(key, node.lineno)

    def visit_Call(self, node):
        func = node.func
        if (isinstance(func, ast.Attribute)
                and func.attr in ("get", "pop", "setdefault")
                and isinstance(func.value, ast.Name)
                and func.value.id in _SCHEME_VARS
                and node.args
                and isinstance(node.args[0], ast.Constant)):
            self._add(node.args[0].value, node)
        self.generic_visit(node)

    def visit_Compare(self, node):
        if (len(node.ops) == 1
                and isinstance(node.ops[0], (ast.In, ast.NotIn))
                and isinstance(node.left, ast.Constant)
                and isinstance(node.comparators[0], ast.Name)
                and node.comparators[0].id in _SCHEME_VARS):
            self._add(node.left.value, node)
        self.generic_visit(node)

    def visit_Subscript(self, node):
        if (isinstance(node.value, ast.Name)
                and node.value.id in _SCHEME_VARS
                and isinstance(node.slice, ast.Constant)):
            self._add(node.slice.value, node)
        self.generic_visit(node)


def _keys_read_by(module_path: Path):
    visitor = _SchemeKeyVisitor()
    visitor.visit(ast.parse(module_path.read_text(encoding="utf-8"), str(module_path)))
    return visitor.keys


def _module_for(type_name: str) -> Path:
    return Path(inspect.getsourcefile(schema_registry.get(type_name).generator))


REGISTERED_TYPES = schema_registry.get_supported_types()


@pytest.mark.parametrize("type_name", REGISTERED_TYPES)
def test_every_key_a_schema_module_reads_is_declared(type_name):
    """The generator's module may not read a key the registry hides."""
    module_path = _module_for(type_name)
    accepted = schema_registry.get_accepted_fields(type_name)

    undeclared = {
        key: lineno
        for key, lineno in _keys_read_by(module_path).items()
        if key not in accepted and not _is_internal(key)
    }

    assert not undeclared, (
        f"'{type_name}' reads config key(s) its registry entry does not declare: "
        + ", ".join(
            f"{key!r} ({module_path.name}:{lineno})"
            for key, lineno in sorted(undeclared.items())
        )
        + ". Add them to that SchemaDefinition's optional_fields, or — if the "
        "server writes them rather than the user — to INTERNAL_SCHEME_FIELDS."
    )


@pytest.mark.parametrize("type_name", REGISTERED_TYPES)
def test_server_written_keys_are_never_declared_as_config(type_name):
    """Publishing an injected key would invite users to set it."""
    definition = schema_registry.get(type_name)
    declared = set(definition.required_fields) | set(definition.optional_fields)
    leaked = declared & set(INTERNAL_SCHEME_FIELDS)
    assert not leaked, (
        f"'{type_name}' declares server-written key(s) as configuration: "
        f"{sorted(leaked)}"
    )


def test_universal_fields_are_not_repeated_by_name():
    """Universal keys live in one place, so they cannot drift per type."""
    overlap = UNIVERSAL_REQUIRED_FIELDS & UNIVERSAL_OPTIONAL_FIELDS
    assert not overlap, f"key is both universally required and optional: {sorted(overlap)}"


# (type, key, module that reads it) for keys read *outside* the type's own schema
# module, which the AST walk above cannot see. Each was verified by reading the
# cited call site.
CROSS_MODULE_KEYS = [
    ("span", "codebook", "potato/codebook_cli.py"),
    ("radio", "codebook", "potato/codebook/schema_bridge.py"),
    ("multiselect", "codebook", "potato/codebook/schema_bridge.py"),
    ("select", "codebook", "potato/codebook/schema_bridge.py"),
    ("speech_transcript", "speaker_key", "potato/server_utils/transcripts/binding.py"),
    ("speech_transcript", "text_key", "potato/server_utils/transcripts/binding.py"),
    ("voice_interaction", "text_key", "potato/server_utils/transcripts/binding.py"),
    ("tiered_annotation", "transcript_field", "potato/server_utils/transcripts/binding.py"),
    ("tiered_annotation", "speaker_key", "potato/server_utils/transcripts/binding.py"),
    ("tiered_annotation", "text_key", "potato/server_utils/transcripts/binding.py"),
]


@pytest.mark.parametrize("type_name,key,reader", CROSS_MODULE_KEYS)
def test_cross_module_scheme_keys_are_declared(type_name, key, reader):
    accepted = schema_registry.get_accepted_fields(type_name)
    assert key in accepted, (
        f"{reader} reads '{key}' off a '{type_name}' scheme, but the registry "
        f"entry does not declare it"
    )


@pytest.mark.parametrize("type_name,key", [
    ("image_annotation", "text_prompt"),
    ("video_annotation", "ai_support"),
    ("video_annotation", "source_field"),
    ("likert", "labels"),
    ("span", "codebook"),
])
def test_reported_missing_keys_stay_declared(type_name, key):
    """The five keys that motivated this guard, pinned by name."""
    assert key in schema_registry.get_accepted_fields(type_name)

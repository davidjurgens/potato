"""
Build a JSON Schema description of a Potato task configuration.

The schema is *derived*, not hand-written. Every enumerable value comes from
the same source of truth the server validates against:

    annotation_schemes[].annotation_type  <- schema_registry
    instance_display.fields[].type        <- display_registry
    assignment_strategy                   <- _VALID_ASSIGNMENT_STRATEGIES
    top-level + nested key names          <- KNOWN_CONFIG_KEYS
    integer / boolean typing              <- _OPTIONAL_INT_FIELDS / _OPTIONAL_BOOL_FIELDS

so a new annotation type, display type, or config key shows up in the schema
the moment it is registered. `tests/unit/test_config_schema_drift.py` fails the
build if the checked-in artifact stops matching what this module produces.

Fidelity note: `additionalProperties` is `true` throughout. The server only
*warns* about unrecognized keys (see `validate_unknown_keys`), so a schema that
rejected them would be stricter than Potato itself and would flag working
configs as invalid.

Usage:
    from potato.server_utils.config_schema import build_config_schema
    schema = build_config_schema()
"""

from typing import Any, Dict, List, Optional

from potato.server_utils.schema_examples import (
    example_scheme_for,
    example_source_for,
)

# Published location of the generated artifact. Used as the schema's $id and as
# the URL that `# yaml-language-server: $schema=` lines point at.
SCHEMA_URL = (
    "https://potatoannotator.readthedocs.io/en/latest/"
    "schemas/potato-config.schema.json"
)

# Enforced by validate_yaml_structure(). 'data_files' is deliberately absent —
# it is one of four mutually-acceptable data sources, expressed as anyOf below.
REQUIRED_TOP_LEVEL = [
    "item_properties",
    "task_dir",
    "output_annotation_dir",
    "annotation_task_name",
]

# Every annotation scheme carries these regardless of type.
_UNIVERSAL_SCHEME_FIELDS = {"name", "description"}

# A registry `required_fields` entry names one key, but some generators accept a
# documented substitute that the registry has no way to express. Encoding the
# registry value alone as `required` would reject working, shipped configs — so
# these become "one of" instead. Keep this table minimal and cite the code that
# implements the alternative.
#
#   hierarchical_multiselect: schemas/hierarchical_multiselect.py:164 raises
#   unless one of 'taxonomy' or 'taxonomy_preset' is present.
_REQUIRED_FIELD_ALTERNATIVES = {
    ("hierarchical_multiselect", "taxonomy"): ["taxonomy_preset"],
}

# data_sources[].type, from validate_data_sources_config().
_DATA_SOURCE_TYPES = [
    "file", "url", "google_drive", "dropbox",
    "s3", "huggingface", "google_sheets", "database",
]


def _documented(path: str) -> Dict[str, Any]:
    """Description/type/default/examples for a dotted path, if we have them.

    Nested sub-keys used to come out of here as a bare `{}` -- the schema knew
    `attention_checks.failure_handling` existed and nothing else about it. The
    docs table is keyed by dotted path precisely so those can be filled in.
    """
    from potato.server_utils.config_key_docs import (
        UNSET,
        get_key_doc,
        json_schema_type,
    )

    doc = get_key_doc(path)
    if doc is None:
        return {}

    out: Dict[str, Any] = {}
    declared = json_schema_type(doc)
    if declared is not None:
        out["type"] = declared
    if doc.summary:
        out["description"] = doc.summary
    if doc.default is not UNSET:
        out["default"] = doc.default
    if doc.example is not None:
        out["examples"] = [doc.example]
    return out


def _leaf_schema(
    key: str, int_fields: set, bool_fields: set, path: Optional[str] = None
) -> Dict[str, Any]:
    """Type a leaf config key using the server's own coercion tables."""
    schema = _documented(path or key)

    # config_module's coercion tables stay authoritative for the keys they
    # cover: they are what the server actually enforces at load time.
    if key in int_fields:
        schema["type"] = "integer"
    elif key in bool_fields:
        schema["type"] = "boolean"
    return schema


def _object_schema(
    sub_keys, int_fields: set, bool_fields: set, path: Optional[str] = None
) -> Dict[str, Any]:
    """Build a nested object schema from a KNOWN_CONFIG_KEYS set-or-dict value."""
    if isinstance(sub_keys, dict):
        names = sub_keys.keys()
    else:
        names = sub_keys

    schema = _documented(path) if path else {}
    schema["type"] = "object"
    schema["properties"] = {
        name: _leaf_schema(
            name, int_fields, bool_fields, f"{path}.{name}" if path else name
        )
        for name in sorted(names)
    }
    schema["additionalProperties"] = True
    return schema


def _annotation_schemes_schema(schemas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Schema for the annotation_schemes list.

    Beyond the annotation_type enum, this emits one if/then per type whose
    required_fields go beyond name+description, so an agent writing a
    `constant_sum` scheme is told it needs `labels` before the server rejects it.
    """
    conditionals = []
    for schema in schemas:
        extra = sorted(set(schema["required_fields"]) - _UNIVERSAL_SCHEME_FIELDS)
        if not extra:
            continue

        plain, either = [], []
        for field_name in extra:
            alts = _REQUIRED_FIELD_ALTERNATIVES.get((schema["name"], field_name))
            if alts:
                either.append(
                    {"anyOf": [{"required": [f]} for f in [field_name, *alts]]}
                )
            else:
                plain.append(field_name)

        then: Dict[str, Any] = {}
        if plain:
            then["required"] = plain
        if either:
            then["allOf"] = either

        conditionals.append({
            "if": {
                "properties": {"annotation_type": {"const": schema["name"]}},
                "required": ["annotation_type"],
            },
            "then": then,
        })

    # A worked example per type, lifted from the example config the docs table
    # links to. `x-potato-examples` rather than JSON Schema's `examples`: sixty
    # whole schemes on `items` would drown editor completion, and what a reader
    # actually wants is a lookup from type name to a config that runs.
    examples_by_type: Dict[str, Any] = {}
    for schema in schemas:
        example = example_scheme_for(schema["name"])
        if example:
            entry: Dict[str, Any] = {"scheme": example}
            source = example_source_for(schema["name"])
            if source:
                entry["source"] = source
            examples_by_type[schema["name"]] = entry

    known_fields: Dict[str, Any] = {
        "annotation_type": {
            "description": "Annotation type, as registered in the schema registry.",
            "oneOf": [
                {"const": s["name"], "description": s["description"] or s["name"]}
                for s in schemas
            ],
        },
        "name": {
            "type": "string",
            "description": "Unique key this scheme's answers are stored under.",
        },
        "description": {
            "type": "string",
            "description": "Prompt shown to the annotator.",
        },
    }

    # Surface every optional field any registered type accepts, so editors can
    # complete them. Types are left open — they vary per annotation type.
    for schema in schemas:
        for field_name in schema["optional_fields"]:
            known_fields.setdefault(field_name, {})
        for field_name in schema["required_fields"]:
            known_fields.setdefault(field_name, {})

    # Keys read by shared helpers rather than by any one generator, so no
    # registry entry lists them. Omitting them made an editor underline
    # `layout:` and `label_requirement:` on the types that never spelled
    # them out. See registry.UNIVERSAL_OPTIONAL_FIELDS.
    from potato.server_utils.schemas.registry import UNIVERSAL_OPTIONAL_FIELDS
    for field_name in sorted(UNIVERSAL_OPTIONAL_FIELDS):
        known_fields.setdefault(field_name, {})

    item: Dict[str, Any] = {
        "type": "object",
        "required": ["annotation_type", "name", "description"],
        "properties": known_fields,
        "additionalProperties": True,
    }
    if conditionals:
        item["allOf"] = conditionals

    out: Dict[str, Any] = {
        "type": "array",
        "description": "The annotation form. Each entry renders one widget.",
        "items": item,
    }
    if examples_by_type:
        out["x-potato-examples"] = examples_by_type
    return out


def _instance_display_schema(displays: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Schema for instance_display, whose field types come from the display registry."""
    span_targets = sorted(
        d["name"] for d in displays if d.get("supports_span_target")
    )
    return {
        "type": "object",
        "description": "How each item is rendered. Omit for plain single-field text.",
        "properties": {
            "fields": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["key", "type"],
                    "properties": {
                        "key": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Field in the data file to render.",
                        },
                        "type": {
                            "description": "Display type, from the display registry.",
                            "oneOf": [
                                {
                                    "const": d["name"],
                                    "description": d["description"] or d["name"],
                                }
                                for d in displays
                            ],
                        },
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
        "$comment": (
            "Display types accepting span annotation targets: "
            + ", ".join(span_targets)
        ),
    }


def build_config_schema() -> Dict[str, Any]:
    """Return the JSON Schema for a Potato config as a plain dict."""
    from potato.server_utils.config_module import (
        KNOWN_CONFIG_KEYS,
        _OPTIONAL_INT_FIELDS,
        _OPTIONAL_BOOL_FIELDS,
        _VALID_ASSIGNMENT_STRATEGIES,
    )
    from potato.server_utils.schemas.registry import schema_registry
    from potato.server_utils.displays import display_registry

    int_fields = set(_OPTIONAL_INT_FIELDS)
    bool_fields = set(_OPTIONAL_BOOL_FIELDS)

    properties: Dict[str, Any] = {}
    for key, sub_keys in sorted(KNOWN_CONFIG_KEYS.items()):
        if sub_keys is None:
            properties[key] = _leaf_schema(key, int_fields, bool_fields, key)
        else:
            properties[key] = _object_schema(sub_keys, int_fields, bool_fields, key)

    # Hand-shaped overrides for the keys with real internal structure.
    properties["item_properties"] = {
        "type": "object",
        "required": ["id_key", "text_key"],
        "properties": {
            "id_key": {
                "type": "string",
                "description": "Field holding each item's unique id.",
            },
            "text_key": {
                "type": "string",
                "description": "Field holding the text shown to annotators.",
            },
            "category_key": {
                "type": "string",
                "minLength": 1,
                "description": "Field used by the category_based assignment strategy.",
            },
            # Shape varies by task; examples pass both a list and a mapping.
            "kwargs": {},
        },
        "additionalProperties": True,
    }
    properties["data_files"] = {
        "type": "array",
        "description": (
            "Data files, relative to task_dir. Each entry is either a path "
            "string or a mapping carrying per-file overrides "
            "(see flask_server.py:493)."
        ),
        "items": {
            "anyOf": [
                {"type": "string"},
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string"},
                        "type": {"type": "string"},
                        "format": {"type": "string"},
                        "id_key": {"type": "string"},
                        "text_key": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            ]
        },
    }
    properties["task_dir"] = {
        "type": "string",
        "description": (
            "Working directory for all relative paths. Paths resolving outside "
            "it are rejected by validate_path_security()."
        ),
    }
    properties["annotation_task_name"] = {"type": "string"}
    properties["output_annotation_dir"] = {"type": "string"}
    properties["annotation_schemes"] = _annotation_schemes_schema(
        schema_registry.list_schemas()
    )
    properties["instance_display"] = _instance_display_schema(
        display_registry.list_displays()
    )
    properties["assignment_strategy"] = {
        "enum": list(_VALID_ASSIGNMENT_STRATEGIES),
        "description": "How items are handed out to annotators.",
    }
    properties["data_sources"] = {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["type"],
            "properties": {"type": {"enum": list(_DATA_SOURCE_TYPES)}},
            "additionalProperties": True,
        },
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URL,
        "title": "Potato task configuration",
        "description": (
            "Configuration for a Potato annotation task. Generated from the "
            "live schema and display registries — see "
            "potato/server_utils/config_schema.py."
        ),
        "type": "object",
        "required": list(REQUIRED_TOP_LEVEL),
        "anyOf": [
            {"required": ["data_files"]},
            {"required": ["data_directory"]},
            {"required": ["data_sources"]},
            {"required": ["batch_assignment"]},
        ],
        "properties": properties,
        "additionalProperties": True,
    }

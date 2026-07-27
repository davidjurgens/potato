"""
Drift guards for the generated config JSON Schema.

`potato/schemas/potato-config.schema.json` is what editors and coding agents
validate a `config.yaml` against. It is generated from the schema registry, the
display registry, and `KNOWN_CONFIG_KEYS` — but it is *checked in*, so it only
stays true if something fails when the code moves and the artifact does not.

Three failure modes, each with a guard below:

1. **The artifact goes stale.** Someone registers an annotation type and the
   schema still lists the old set, so agents are told a real type is invalid.

2. **The schema drifts from the registries in either direction.** A type in the
   schema that the registry does not serve is worse than a missing one: the
   config validates and then fails at render time.

3. **The schema becomes stricter than the server.** This is the subtle one. The
   server only *warns* about unrecognized keys, and several fields accept more
   shapes than an obvious reading suggests — `data_files` entries may be strings
   or mappings, and `hierarchical_multiselect` accepts `taxonomy` *or*
   `taxonomy_preset`. A schema that rejects those flags working, shipped configs
   as broken, which is exactly the false signal this artifact exists to prevent.
   Validating every example config in the repo is what catches it.
"""

import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
jsonschema = pytest.importorskip("jsonschema")

from potato.server_utils.config_schema import build_config_schema
from potato.server_utils.displays import display_registry
from potato.server_utils.schemas.registry import schema_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_COPY = REPO_ROOT / "potato" / "schemas" / "potato-config.schema.json"
DOCS_COPY = REPO_ROOT / "docs" / "schemas" / "potato-config.schema.json"

REGENERATE = "Regenerate with: python scripts/generate_config_schema.py"


def _rendered():
    """Serialized exactly as scripts/generate_config_schema.py writes it."""
    return json.dumps(build_config_schema(), indent=2, sort_keys=True) + "\n"


def _checked_in():
    return json.loads(PACKAGE_COPY.read_text(encoding="utf-8"))


def _enum_values(node):
    """Pull the allowed values out of either an `enum` or a `oneOf` of consts."""
    if "enum" in node:
        return set(node["enum"])
    return {entry["const"] for entry in node.get("oneOf", []) if "const" in entry}


def _annotation_type_node(schema):
    return schema["properties"]["annotation_schemes"]["items"]["properties"]["annotation_type"]


def _display_type_node(schema):
    return (schema["properties"]["instance_display"]["properties"]["fields"]
            ["items"]["properties"]["type"])


def _example_configs():
    return sorted(REPO_ROOT.glob("examples/**/config.yaml"))


class TestArtifactIsCurrent:
    def test_package_copy_matches_generator(self):
        assert PACKAGE_COPY.exists(), f"{PACKAGE_COPY} is missing. {REGENERATE}"
        assert PACKAGE_COPY.read_text(encoding="utf-8") == _rendered(), (
            f"{PACKAGE_COPY.relative_to(REPO_ROOT)} is stale. {REGENERATE}"
        )

    def test_docs_copy_matches_package_copy(self):
        """The docs site serves its own copy; both must be the same bytes."""
        assert DOCS_COPY.exists(), f"{DOCS_COPY} is missing. {REGENERATE}"
        assert DOCS_COPY.read_text(encoding="utf-8") == PACKAGE_COPY.read_text(
            encoding="utf-8"
        ), f"The docs and package copies disagree. {REGENERATE}"

    def test_schema_is_valid_json_schema(self):
        schema = _checked_in()
        validator = jsonschema.validators.validator_for(schema)
        validator.check_schema(schema)


class TestRegistriesAndSchemaAgree:
    def test_every_registered_annotation_type_is_in_the_schema(self):
        registered = set(schema_registry.get_supported_types())
        in_schema = _enum_values(_annotation_type_node(_checked_in()))
        missing = registered - in_schema
        assert not missing, (
            f"Annotation types registered but absent from the schema: "
            f"{sorted(missing)}. Agents will be told these are invalid. {REGENERATE}"
        )

    def test_schema_names_no_unregistered_annotation_type(self):
        registered = set(schema_registry.get_supported_types())
        in_schema = _enum_values(_annotation_type_node(_checked_in()))
        extra = in_schema - registered
        assert not extra, (
            f"Schema allows annotation types the registry does not serve: "
            f"{sorted(extra)}. A config using one validates, then fails at render."
        )

    def test_every_registered_display_type_is_in_the_schema(self):
        registered = set(display_registry.get_supported_types())
        in_schema = _enum_values(_display_type_node(_checked_in()))
        missing = registered - in_schema
        assert not missing, (
            f"Display types registered but absent from the schema: {sorted(missing)}. "
            f"{REGENERATE}"
        )

    def test_schema_names_no_unregistered_display_type(self):
        registered = set(display_registry.get_supported_types())
        in_schema = _enum_values(_display_type_node(_checked_in()))
        extra = in_schema - registered
        assert not extra, (
            f"Schema allows display types the registry does not serve: {sorted(extra)}."
        )

    def test_every_known_config_key_is_a_schema_property(self):
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS

        in_schema = set(_checked_in()["properties"])
        missing = set(KNOWN_CONFIG_KEYS) - in_schema
        assert not missing, (
            f"Config keys the server recognizes but the schema omits: "
            f"{sorted(missing)}. {REGENERATE}"
        )


class TestSchemaIsNotStricterThanTheServer:
    """
    Every config shipped in `examples/` must validate.

    These configs are known-good — they are what the docs tell people to run — so
    a validation failure here means the schema is wrong, not the config.
    """

    def test_every_example_config_validates(self):
        schema = _checked_in()
        validator = jsonschema.Draft202012Validator(schema)

        failures = []
        for path in _example_configs():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                failures.append(f"{path.relative_to(REPO_ROOT)}: unparseable YAML ({exc})")
                continue
            if not isinstance(data, dict):
                continue
            for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
                location = "/".join(str(p) for p in error.path) or "<root>"
                failures.append(
                    f"{path.relative_to(REPO_ROOT)} :: {location}: {error.message}"
                )

        assert not failures, (
            "The schema rejects config(s) that Potato itself accepts, so it is "
            "stricter than the server:\n  " + "\n  ".join(failures[:20])
        )

    def test_there_are_example_configs_to_check(self):
        """Guard against the glob silently matching nothing and vacuously passing."""
        assert len(_example_configs()) > 50


class TestSchemaCatchesRealMistakes:
    """
    The complement of the test above: a schema that accepts everything would pass
    every check so far while being useless. These are the mistakes coding agents
    actually make.
    """

    BASE = {
        "annotation_task_name": "t",
        "task_dir": ".",
        "output_annotation_dir": "out/",
        "item_properties": {"id_key": "id", "text_key": "text"},
        "data_files": ["d.json"],
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "x", "description": "d",
             "labels": ["a"]}
        ],
    }

    @pytest.fixture
    def validator(self):
        return jsonschema.Draft202012Validator(_checked_in())

    def test_baseline_config_is_valid(self, validator):
        assert not list(validator.iter_errors(self.BASE))

    @pytest.mark.parametrize("label,mutate", [
        ("typo'd annotation type",
         lambda c: c["annotation_schemes"][0].update(annotation_type="radioo")),
        ("hallucinated annotation type",
         lambda c: c["annotation_schemes"][0].update(annotation_type="sentiment")),
        ("per-type required field missing",
         lambda c: c.update(annotation_schemes=[
             {"annotation_type": "constant_sum", "name": "x", "description": "d"}])),
        ("scheme missing name",
         lambda c: c["annotation_schemes"][0].pop("name")),
        ("item_properties missing text_key",
         lambda c: c["item_properties"].pop("text_key")),
        ("no data source configured", lambda c: c.pop("data_files")),
        ("required top-level key missing", lambda c: c.pop("task_dir")),
        ("unknown display type",
         lambda c: c.update(instance_display={"fields": [{"key": "t", "type": "tekst"}]})),
        ("invalid assignment strategy",
         lambda c: c.update(assignment_strategy="round_robin")),
        ("integer field given a string",
         lambda c: c.update(max_annotations_per_user="five")),
    ])
    def test_invalid_config_is_rejected(self, validator, label, mutate):
        import copy

        config = copy.deepcopy(self.BASE)
        mutate(config)
        assert list(validator.iter_errors(config)), (
            f"Schema accepted an invalid config ({label}); it is too permissive "
            f"to be worth publishing."
        )

    def test_documented_required_field_alternative_is_accepted(self):
        """
        `hierarchical_multiselect` takes `taxonomy` OR `taxonomy_preset`
        (schemas/hierarchical_multiselect.py raises unless one is present), which
        the registry's flat `required_fields` cannot express. Encoding the registry
        value verbatim rejected a shipped example.
        """
        import copy

        validator = jsonschema.Draft202012Validator(_checked_in())
        config = copy.deepcopy(self.BASE)
        config["annotation_schemes"] = [{
            "annotation_type": "hierarchical_multiselect",
            "name": "x", "description": "d", "taxonomy_preset": "mast",
        }]
        assert not list(validator.iter_errors(config))

        config["annotation_schemes"][0].pop("taxonomy_preset")
        assert list(validator.iter_errors(config)), (
            "Neither taxonomy nor taxonomy_preset present — should be rejected."
        )

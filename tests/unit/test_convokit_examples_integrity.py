"""Integrity guard for the conversation example projects.

These examples download their corpus text on demand rather than committing it, so
this file cannot check that a data file exists — CI has no network and no corpus.
What it *can* check, and what actually breaks in practice, is that each config is
internally coherent and consistent with the item shape the importer produces:

* the config parses and passes real validation
* every `instance_display` field key is one the importer emits
* every `turn_binding.field` names a field that exists and can host widgets
* every scheme generates a layout without silently producing an error block

The last one matters because `safe_generate_layout` swallows generator exceptions
into an ``annotation-error`` block rather than raising, so a misconfigured scheme
renders as a broken box instead of failing the boot. That is how `span_link` with
string `link_types` silently vanished from a page while the config validated.

Where a data file *has* been produced locally, the shape checks run against it
too; otherwise they are skipped.
"""

import glob
import json
import os

import pytest
import yaml

from potato.convokit.items import PROVENANCE_KEY
from potato.server_utils.displays.registry import display_registry
from potato.server_utils.schemas.registry import schema_registry
from potato.validate_cli import validate_config_file

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXAMPLES_DIR = os.path.join(PROJECT_ROOT, "examples", "conversation")

EXAMPLE_DIRS = sorted(
    os.path.basename(os.path.dirname(p))
    for p in glob.glob(os.path.join(EXAMPLES_DIR, "*", "config.yaml"))
)

CONFIGS = [os.path.join(EXAMPLES_DIR, d, "config.yaml") for d in EXAMPLE_DIRS]

#: Keys the ConvoKit importer can emit, plus the ones a hand-written example
#: legitimately adds. A display field pointing anywhere else is a typo.
KNOWN_ITEM_KEYS = {
    "id", "text", "title", "conversation", "conversation_tree", "thread",
    "convo_meta", "speakers", "focus_turn_id", PROVENANCE_KEY,
}


def load(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_examples_are_discovered():
    """A rename that empties this list would make every test below vacuous."""
    assert len(EXAMPLE_DIRS) >= 3, EXAMPLE_DIRS


@pytest.mark.parametrize("config_path", CONFIGS, ids=EXAMPLE_DIRS)
class TestExampleConfig:
    def test_parses(self, config_path):
        assert isinstance(load(config_path), dict)

    def test_passes_validation(self, config_path):
        report = validate_config_file(config_path)
        assert report.ok, report.errors

    def test_every_scheme_generates_without_an_error_block(self, config_path):
        config = load(config_path)
        for scheme in config.get("annotation_schemes", []):
            html, _ = schema_registry.generate(scheme)
            assert "annotation-error" not in html, (
                f"scheme '{scheme.get('name')}' "
                f"({scheme.get('annotation_type')}) rendered an error block"
            )

    def test_display_field_keys_are_ones_the_importer_emits(self, config_path):
        config = load(config_path)
        for field in config.get("instance_display", {}).get("fields", []):
            key = field.get("key")
            promoted = _promoted_keys(config)
            assert key in KNOWN_ITEM_KEYS or key in promoted, (
                f"instance_display field '{key}' is not a key the importer "
                f"produces; known: {sorted(KNOWN_ITEM_KEYS)}"
            )

    def test_display_types_are_registered(self, config_path):
        config = load(config_path)
        for field in config.get("instance_display", {}).get("fields", []):
            assert display_registry.get(field.get("type")) is not None, (
                f"unknown display type '{field.get('type')}'"
            )

    def test_turn_bindings_reference_a_real_field(self, config_path):
        config = load(config_path)
        field_keys = {
            f.get("key") for f in config.get("instance_display", {}).get("fields", [])
        }
        for scheme in config.get("annotation_schemes", []):
            binding = scheme.get("turn_binding") or {}
            bound = binding.get("field")
            if bound is None:
                continue
            assert bound in field_keys, (
                f"scheme '{scheme.get('name')}' binds to '{bound}', "
                f"which is not a display field ({sorted(field_keys)})"
            )

    def test_turn_bindings_target_a_turn_capable_display(self, config_path):
        """Binding to a `text` field yields an anchor input nobody can fill."""
        config = load(config_path)
        types = {
            f.get("key"): f.get("type")
            for f in config.get("instance_display", {}).get("fields", [])
        }
        turn_capable = {
            "dialogue", "audio_dialogue", "multi_agent_discussion",
            "agent_trace", "cot_trace", "conversation_tree",
        }
        for scheme in config.get("annotation_schemes", []):
            bound = (scheme.get("turn_binding") or {}).get("field")
            if bound is None:
                continue
            assert types.get(bound) in turn_capable, (
                f"scheme '{scheme.get('name')}' binds to '{bound}' of type "
                f"'{types.get(bound)}', which cannot render per-turn widgets"
            )

    def test_span_targets_are_span_capable(self, config_path):
        config = load(config_path)
        for field in config.get("instance_display", {}).get("fields", []):
            if not field.get("span_target"):
                continue
            definition = display_registry.get(field.get("type"))
            assert definition.supports_span_target, (
                f"field '{field.get('key')}' of type '{field.get('type')}' "
                "cannot be a span target"
            )

    def test_has_a_setup_script_and_readme(self, config_path):
        """Corpus text is not committed, so the fetch step must be documented."""
        example_dir = os.path.dirname(config_path)
        assert os.path.exists(os.path.join(example_dir, "README.md"))
        if os.path.basename(example_dir).startswith("convokit-"):
            assert os.path.exists(os.path.join(example_dir, "setup_data.sh"))


def _promoted_keys(config):
    """Top-level keys an example may reference via --promote-meta."""
    return {"Binary", "split", "page_title"}


@pytest.mark.parametrize("config_path", CONFIGS, ids=EXAMPLE_DIRS)
def test_local_data_matches_the_config(config_path):
    """When a data file has been produced locally, check the config against it."""
    config = load(config_path)
    example_dir = os.path.dirname(config_path)
    data_files = config.get("data_files") or []
    path = os.path.join(example_dir, str(data_files[0])) if data_files else None
    if not path or not os.path.exists(path):
        pytest.skip("data not fetched; run setup_data.sh to exercise this check")

    with open(path, "r", encoding="utf-8") as f:
        first = f.readline().strip()
    item = json.loads(first)

    id_key = config.get("item_properties", {}).get("id_key", "id")
    text_key = config.get("item_properties", {}).get("text_key", "text")
    assert id_key in item, f"id_key '{id_key}' missing from the data"
    assert text_key in item, f"text_key '{text_key}' missing from the data"

    for field in config.get("instance_display", {}).get("fields", []):
        assert field["key"] in item, (
            f"display field '{field['key']}' is not present in the data file"
        )

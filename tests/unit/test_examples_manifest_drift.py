"""
Guards for the generated example catalog.

`potato/schemas/potato-examples.manifest.json` is what answers "show me a `bws`
example" for editors, the docs site and the MCP tools. It is derived from the
configs, so the failure mode is not inaccuracy but staleness -- and a stale
catalog that still parses looks exactly like a fresh one.

These tests also cover two things the catalog makes cheap to check across all
212 examples at once: that every annotation type named in an example is really
registered, and that every config carries the `$schema` modeline. Eleven were
missing it and nothing noticed, because until now nothing could see them all.
"""

import json
import os
import subprocess
import sys

import pytest

from potato.server_utils.examples_manifest import (
    MANIFEST_FILENAME,
    build_manifest,
    load_manifest,
    search_examples,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGED = os.path.join(REPO_ROOT, "potato", "schemas", MANIFEST_FILENAME)
PUBLISHED = os.path.join(REPO_ROOT, "docs", "schemas", MANIFEST_FILENAME)
GENERATOR = os.path.join(REPO_ROOT, "scripts", "generate_examples_manifest.py")


@pytest.fixture(scope="module")
def checked_in():
    with open(PACKAGED, "r", encoding="utf-8") as f:
        return json.load(f)


class TestArtifactIsCurrent:
    def test_both_copies_exist(self):
        assert os.path.isfile(PACKAGED), f"missing {PACKAGED}"
        assert os.path.isfile(PUBLISHED), f"missing {PUBLISHED}"

    def test_copies_are_identical(self):
        with open(PACKAGED, "r", encoding="utf-8") as f:
            packaged = f.read()
        with open(PUBLISHED, "r", encoding="utf-8") as f:
            published = f.read()
        assert packaged == published, (
            "The wheel copy and the published copy have diverged. Regenerate "
            "both: python scripts/generate_examples_manifest.py"
        )

    def test_check_flag_passes(self):
        """What CI runs. Fails when examples/ changed and nobody regenerated."""
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "Examples manifest is stale:\n"
            + result.stdout
            + result.stderr
        )

    def test_rebuild_matches_checked_in(self, checked_in):
        assert build_manifest(REPO_ROOT) == checked_in


class TestManifestContent:
    def test_catalog_is_not_empty(self):
        """Fail loudly if the glob stops matching rather than silently shrinking."""
        manifest = load_manifest()
        assert manifest is not None
        assert manifest["count"] > 150, (
            f"only {manifest['count']} examples catalogued; the walk has "
            f"probably stopped finding them"
        )

    def test_every_example_directory_exists(self, checked_in):
        for entry in checked_in["examples"]:
            path = os.path.join(REPO_ROOT, entry["path"])
            assert os.path.isfile(path), f"{entry['path']} is catalogued but absent"

    def test_every_annotation_type_is_registered(self, checked_in):
        from potato.server_utils.schemas.registry import schema_registry

        registered = set(schema_registry.get_supported_types())
        unknown = {}
        for entry in checked_in["examples"]:
            for type_name in entry["annotation_types"]:
                if type_name not in registered:
                    unknown.setdefault(type_name, []).append(entry["dir"])
        assert not unknown, (
            "Example configs name annotation types that are not registered, so "
            "they cannot run: "
            + "; ".join(f"{t} in {d[0]}" for t, d in sorted(unknown.items()))
        )

    def test_every_display_type_is_registered(self, checked_in):
        from potato.server_utils.displays import display_registry

        registered = set(display_registry.get_supported_types())
        unknown = {}
        for entry in checked_in["examples"]:
            for type_name in entry["display_types"]:
                if type_name not in registered:
                    unknown.setdefault(type_name, []).append(entry["dir"])
        assert not unknown, (
            "Example configs name display types that are not registered: "
            + "; ".join(f"{t} in {d[0]}" for t, d in sorted(unknown.items()))
        )

    def test_every_config_carries_the_schema_modeline(self, checked_in):
        """The modeline is what turns on live validation in an editor.

        Eleven configs shipped without it. Stamp them with:
            python scripts/generate_config_schema.py --stamp-examples
        """
        missing = [e["dir"] for e in checked_in["examples"] if not e["has_modeline"]]
        assert not missing, (
            "These example configs have no `# yaml-language-server: $schema=` "
            "line, so an editor opening them gets no validation and no "
            "completion: " + ", ".join(missing)
        )

    def test_entries_have_the_expected_fields(self, checked_in):
        required = {
            "path", "dir", "category", "name", "task_name", "description",
            "annotation_types", "display_types", "config_keys", "data_files",
            "has_readme", "has_data_dir", "has_modeline", "run",
        }
        for entry in checked_in["examples"]:
            assert required <= set(entry), (
                f"{entry.get('dir')} is missing {sorted(required - set(entry))}"
            )


class TestReadmeIndex:
    """examples/README.md must name every example, not just the curated ones."""

    def test_every_example_appears_in_the_readme(self, checked_in):
        with open(os.path.join(REPO_ROOT, "examples", "README.md"), encoding="utf-8") as f:
            readme = f.read()
        missing = [
            e["dir"] for e in checked_in["examples"]
            if f"`{e['name']}/`" not in readme
        ]
        assert not missing, (
            f"{len(missing)} examples are absent from examples/README.md. "
            "Regenerate the index: python scripts/generate_examples_manifest.py. "
            f"First few: {missing[:5]}"
        )

    def test_generated_block_is_delimited(self):
        with open(os.path.join(REPO_ROOT, "examples", "README.md"), encoding="utf-8") as f:
            readme = f.read()
        assert "<!-- BEGIN GENERATED INDEX -->" in readme
        assert "<!-- END GENERATED INDEX -->" in readme
        assert readme.index("<!-- BEGIN GENERATED INDEX -->") < readme.index(
            "<!-- END GENERATED INDEX -->"
        )

    def test_curated_prose_survives_regeneration(self):
        """The hand-written half must stay above the marker, untouched."""
        with open(os.path.join(REPO_ROOT, "examples", "README.md"), encoding="utf-8") as f:
            readme = f.read()
        curated = readme[: readme.index("<!-- BEGIN GENERATED INDEX -->")]
        assert "Multi-label checkbox selection" in curated, (
            "The curated descriptions were lost. They say what each example is "
            "for, which parsing configs cannot recover."
        )


class TestSearch:
    def test_filters_by_annotation_type(self):
        results = search_examples(annotation_type="bws")
        assert results, "no bws examples found"
        assert all("bws" in r["annotation_types"] for r in results)

    def test_filters_by_config_key(self):
        results = search_examples(config_key="gold_standards")
        assert all("gold_standards" in r["config_keys"] for r in results)

    def test_unknown_filter_returns_nothing(self):
        assert search_examples(annotation_type="not_a_real_type") == []

    def test_limit_is_honored(self):
        assert len(search_examples(limit=3)) <= 3

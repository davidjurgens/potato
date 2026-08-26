"""
Drift guard for the "Potato has N of these" claims in the docs.

These numbers rot silently. Every wave that registers a schema, a display type
or a config key makes them wrong, and nothing fails, so the docs shipped four
different answers to "how many annotation types are there?" at once: 36 in the
decision guide, 56 in the README and the docs index, 61 in the comparison page,
and "20+" in the FAQ. The registry said 61.

A wrong count is worse than a vague one. A reader who sees "36 annotation
schema types" on the page that exists to help them choose concludes the type
they need is not there.

Each case below pins one sentence in one file to the registry that decides it.
When you add a schema and this fails, update the prose -- that is the point.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _counts():
    """The authoritative numbers, read from the code rather than restated."""
    from potato.server_utils.schemas.registry import schema_registry
    from potato.server_utils.displays.registry import display_registry

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_config_reference", REPO_ROOT / "scripts" / "generate_config_reference.py"
    )
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    import json

    with open(REPO_ROOT / "docs" / "api-reference" / "openapi.json", encoding="utf-8") as f:
        openapi = json.load(f)

    from potato.server_utils.examples_manifest import load_manifest

    return {
        "annotation_types": len(schema_registry.get_supported_types()),
        "display_types": len(display_registry.get_supported_types()),
        "config_keys": len(gen.KNOWN_CONFIG_KEYS),
        "http_paths": len(openapi["paths"]),
        "examples": load_manifest()["count"],
    }


@pytest.fixture(scope="module")
def counts():
    return _counts()


# (relative path, regex with one capture group, which count it must equal)
CLAIMS = [
    ("README.md",
     r"All (\d+) config keys, \d+ annotation types, \d+ display types",
     "config_keys"),
    ("README.md",
     r"All \d+ config keys, (\d+) annotation types, \d+ display types",
     "annotation_types"),
    ("README.md",
     r"All \d+ config keys, \d+ annotation types, (\d+) display types",
     "display_types"),

    ("docs/index.md",
     r"all (\d+) annotation types and \d+ display types",
     "annotation_types"),
    ("docs/index.md",
     r"all \d+ annotation types and (\d+) display types",
     "display_types"),

    ("docs/api-reference/machine_readable.md",
     r"\*\*(\d+) top-level config keys\*\*",
     "config_keys"),
    ("docs/api-reference/machine_readable.md",
     r"\*\*(\d+) annotation types\*\*",
     "annotation_types"),
    ("docs/api-reference/machine_readable.md",
     r"\*\*(\d+) display types\*\*",
     "display_types"),

    ("docs/annotation-types/choosing_annotation_types.md",
     r"Potato has (\d+) annotation schema types",
     "annotation_types"),

    ("docs/guides/getting-started.md",
     r"Potato has (\d+) annotation types",
     "annotation_types"),

    ("docs/faq.md",
     r"^(\d+) schemes:",
     "annotation_types"),

    ("docs/comparison.md",
     r"Potato has (\d+) annotation schemas and \d+ display types",
     "annotation_types"),
    ("docs/comparison.md",
     r"Potato has \d+ annotation schemas and (\d+) display types",
     "display_types"),
    ("docs/comparison.md",
     r"\| Annotation schemas \| (\d+) \|",
     "annotation_types"),
    ("docs/comparison.md",
     r"\| Display types \| (\d+) \|",
     "display_types"),

    # llms.txt is the entry point we hand to coding agents, and it was the one
    # index nothing checked: it claimed 56 annotation types, 23 display types
    # and 390 HTTP paths against an actual 61 / 24 / 422.
    ("docs/llms.txt",
     r"all (\d+) annotation types and \d+ display types",
     "annotation_types"),
    ("docs/llms.txt",
     r"all \d+ annotation types and (\d+) display types",
     "display_types"),
    ("docs/llms.txt",
     r"all (\d+) HTTP paths",
     "http_paths"),

    ("docs/api-reference/machine_readable.md",
     r"\*\*(\d+) paths / \d+ operations\*\*",
     "http_paths"),

    # Both of these said 212 against a manifest of 214. The examples count was
    # the one number in llms.txt and machine_readable.md that nothing pinned.
    ("docs/llms.txt",
     r"all (\d+) example projects",
     "examples"),
    ("docs/api-reference/machine_readable.md",
     r"the \*\*(\d+) example projects\*\*",
     "examples"),

]


@pytest.mark.parametrize("rel_path,pattern,key", CLAIMS)
def test_doc_count_matches_registry(rel_path, pattern, key, counts):
    path = REPO_ROOT / rel_path
    text = path.read_text(encoding="utf-8")

    match = re.search(pattern, text, re.M)
    assert match, (
        f"{rel_path}: no text matched {pattern!r}. Either the sentence was "
        f"reworded (update this test) or the claim was dropped."
    )

    claimed = int(match.group(1))
    assert claimed == counts[key], (
        f"{rel_path} claims {claimed} {key.replace('_', ' ')}, but the registry "
        f"has {counts[key]}. Update the prose in {rel_path}."
    )


def test_release_notes_are_not_swept_up():
    """A release note records what was true at that version and must not be
    'corrected' to the current count."""
    note = REPO_ROOT / "docs" / "releasenotes" / "v2.6.2.md"
    assert "53 annotation schema types" in note.read_text(encoding="utf-8"), (
        "v2.6.2's count was rewritten. Release notes are version-scoped: they "
        "should keep the number that was true when they were published."
    )

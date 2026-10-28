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

    from potato.export.registry import export_registry
    from potato.importers.registry import import_registry
    from potato.importers.text.registry import text_import_registry
    from potato.item_state_management import AssignmentStrategy
    from potato.survey_instruments import list_instruments
    from potato.crowdsourcing.registry import get_supported_providers
    from potato.data_sources.base import SourceType
    from potato.phase import UserPhase

    from potato.importers.projects import IMPORTERS as project_importers

    cv_imports = len(import_registry._importers)
    text_imports = len(text_import_registry._importers)
    project_imports = len(project_importers)

    return {
        "annotation_types": len(schema_registry.get_supported_types()),
        "display_types": len(display_registry.get_supported_types()),
        "config_keys": len(gen.KNOWN_CONFIG_KEYS),
        "http_paths": len(openapi["paths"]),
        "examples": load_manifest()["count"],
        "export_formats": len(export_registry._exporters),
        "cv_import_formats": cv_imports,
        "text_import_formats": text_imports,
        "project_import_formats": project_imports,
        "import_formats": cv_imports + text_imports + project_imports,
        "ai_endpoint_types": len(_endpoint_classes()),
        "ai_support_endpoint_types": _ai_support_endpoint_classes(),
        "assignment_strategies": len(AssignmentStrategy),
        "survey_instruments": len(list_instruments()),
        "crowd_providers": len(get_supported_providers()),
        "data_source_types": len(SourceType),
        "workflow_phases": len(UserPhase),
    }


def _endpoint_classes():
    """Distinct endpoint implementations, keyed by type name.

    An alias (``open_router`` for ``openrouter``) maps to the same class, so
    counting type names would overstate what Potato can talk to.
    """
    from potato.ai.ai_endpoint import AIEndpointFactory

    # Potato's own endpoints only: other tests register fakes into the same
    # factory, and in a full run those were counted too (27 instead of 15).
    def builtin(module):
        return str(module).startswith((".", "potato."))

    # A lazy entry names its module relative to potato.ai; once a test has
    # loaded it, the same class is also in _endpoints under its full name.
    def full(module):
        return "potato.ai" + module if str(module).startswith(".") else module

    classes = {}
    for name, target in AIEndpointFactory._lazy_endpoints.items():
        if builtin(target[0]):
            classes.setdefault((full(target[0]), target[1]), name)
    for name, cls in AIEndpointFactory._endpoints.items():
        if builtin(cls.__module__):
            classes.setdefault((cls.__module__, cls.__name__), name)
    return classes


def _ai_support_endpoint_classes():
    """How many endpoint implementations ``ai_support`` accepts, by asking its
    validator rather than restating its allow-list."""
    from potato.server_utils.config_module import (
        ConfigValidationError, validate_ai_support_config)

    accepted = 0
    for name in _endpoint_classes().values():
        try:
            validate_ai_support_config(
                {"ai_support": {"enabled": True, "endpoint_type": name}})
        except ConfigValidationError:
            continue
        accepted += 1
    return accepted


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

    # README and the docs index said 419 HTTP paths against an actual 477.
    ("README.md",
     r"All (\d+) HTTP paths",
     "http_paths"),
    ("docs/index.md",
     r"All (\d+) HTTP paths",
     "http_paths"),

    # llms.txt's gallery line said "20+" when the registry had 61.
    ("docs/llms.txt",
     r"schemas_and_templates/\): all (\d+) annotation types",
     "annotation_types"),

    # The comparison page's feature-count table said its numbers were
    # "generated from Potato's own registries". They were not: it claimed 29
    # export formats (32), 15 import formats (15 CV plus 5 text), 13 AI
    # endpoint types (15) and 11 assignment strategies (13). Every row of
    # that table, and each prose restatement of it, is pinned here, which is
    # what makes the sentence under the table true.
    ("docs/comparison.md",
     r"\| Export formats \| (\d+) \| Multiple",
     "export_formats"),
    # The jsPsych migration guide said 41 while the registry had 60.
    ("docs/guides/coming-from-jspsych.md",
     r"`python -m potato.export` \| (\d+) formats",
     "export_formats"),
    ("docs/comparison.md",
     r"Export annotations in (\d+) formats",
     "export_formats"),
    ("docs/comparison.md",
     r"import from (\d+) \(\d+ computer-vision formats, \d+ text formats",
     "import_formats"),
    ("docs/comparison.md",
     r"import from \d+ \((\d+) computer-vision formats, \d+ text formats",
     "cv_import_formats"),
    ("docs/comparison.md",
     r"import from \d+ \(\d+ computer-vision formats, (\d+) text formats",
     "text_import_formats"),
    ("docs/comparison.md",
     r"\| CV format import \| (\d+) formats \|",
     "cv_import_formats"),
    ("docs/comparison.md",
     r"Potato imports (\d+) CV formats and exports \d+ formats",
     "cv_import_formats"),
    ("docs/comparison.md",
     r"Potato imports \d+ CV formats and exports (\d+) formats",
     "export_formats"),
    ("docs/comparison.md",
     r"integrates with (\d+) AI endpoint types",
     "ai_endpoint_types"),
    ("docs/comparison.md",
     r"`ai_support` accepts (\d+) of them",
     "ai_support_endpoint_types"),
    ("docs/comparison.md",
     r"Combined with (\d+) AI endpoint types",
     "ai_endpoint_types"),
    ("docs/comparison.md",
     r"\*\*(\d+) validated survey instruments\*\*",
     "survey_instruments"),
    ("docs/comparison.md",
     r"Load data from (\d+) source types",
     "data_source_types"),
    ("docs/comparison.md",
     r"^- \*\*Crowdsourcing\*\*: (\w+) crowd providers",
     "crowd_providers"),
    ("docs/comparison.md",
     r"^\| Export formats \| (\d+) \|$",
     "export_formats"),
    ("docs/comparison.md",
     r"^\| Import formats \(\d+ CV, \d+ text, \d+ whole-project\) \| (\d+) \|$",
     "import_formats"),
    ("docs/comparison.md",
     r"^\| Import formats \((\d+) CV, \d+ text, \d+ whole-project\) \|",
     "cv_import_formats"),
    ("docs/comparison.md",
     r"^\| Import formats \(\d+ CV, (\d+) text, \d+ whole-project\) \|",
     "text_import_formats"),
    ("docs/comparison.md",
     r"^\| Import formats \(\d+ CV, \d+ text, (\d+) whole-project\) \|",
     "project_import_formats"),
    ("docs/comparison.md",
     r"^\| AI/LLM endpoint types \| (\d+) \|$",
     "ai_endpoint_types"),
    ("docs/comparison.md",
     r"^\| Data source types \| (\d+) \|$",
     "data_source_types"),
    ("docs/comparison.md",
     r"^\| Assignment strategies \| (\d+) \|$",
     "assignment_strategies"),
    ("docs/comparison.md",
     r"^\| Survey instruments \| (\d+) \|$",
     "survey_instruments"),
    ("docs/comparison.md",
     r"^\| Crowdsourcing integrations \| (\d+) \|$",
     "crowd_providers"),
    ("docs/comparison.md",
     r"^\| Workflow phases \| (\d+) \|$",
     "workflow_phases"),

    # Crowdsourcing was described as "Prolific and MTurk" in five places
    # while the registry shipped nine providers.
    ("README.md",
     r"\| (\w+) crowd providers: Prolific",
     "crowd_providers"),
    ("docs/faq.md",
     r"Potato ships (\w+) \[crowd providers\]",
     "crowd_providers"),
    ("docs/llms.txt",
     r"deployment/crowdsourcing/\): (\w+) crowd providers",
     "crowd_providers"),
    ("docs/index.md",
     r"Configuring a crowd provider; (\w+) ship",
     "crowd_providers"),

]

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def _as_int(text):
    """A claimed count, written either as digits or as a word ("Nine")."""
    if text.isdigit():
        return int(text)
    word = text.lower()
    assert word in _NUMBER_WORDS, f"cannot read {text!r} as a count"
    return _NUMBER_WORDS[word]


@pytest.mark.parametrize("rel_path,pattern,key", CLAIMS)
def test_doc_count_matches_registry(rel_path, pattern, key, counts):
    path = REPO_ROOT / rel_path
    text = path.read_text(encoding="utf-8")

    match = re.search(pattern, text, re.M)
    assert match, (
        f"{rel_path}: no text matched {pattern!r}. Either the sentence was "
        f"reworded (update this test) or the claim was dropped."
    )

    claimed = _as_int(match.group(1))
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

"""
Drift guard for the generated configuration reference.

`docs/configuration/config_reference.md` opens by calling itself "a complete
reference of all recognized configuration keys in Potato". It was not. The
generator groups keys using a hand-maintained CATEGORY_ORDER list, and a key
that belongs to no category was simply skipped — silently, with no warning and
no leftover section.

Thirty-five of 154 recognized keys had drifted out that way, including whole
subsystems: `rooms`, `psychometrics`, `rbac`, `crowdsourcing`, `publish`,
`surveyflow`, `triage`, and the entire agent-evaluation suite (`datasets`,
`automation`, `curation`, `arena`). A release note linking to
`#agent-evaluation-suite` pointed at a section that had never existed, which is
how the gap surfaced.

The generator now emits an "Other" catch-all so a new key is at worst
uncategorized rather than undocumented. These tests make the promise in the
first paragraph enforceable.
"""

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE = REPO_ROOT / "docs" / "configuration" / "config_reference.md"
GENERATOR = REPO_ROOT / "scripts" / "generate_config_reference.py"

REGENERATE = "Regenerate with: python scripts/generate_config_reference.py"


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("generate_config_reference", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reference_text():
    assert REFERENCE.exists(), f"{REFERENCE} is missing. {REGENERATE}"
    return REFERENCE.read_text(encoding="utf-8")


def _documented_keys(text):
    """Keys that have a table row. Rows look like ``| `task_dir` | Yes | ... |``."""
    return set(re.findall(r"^\| `([a-zA-Z_][\w]*)` \|", text, flags=re.MULTILINE))


class TestEveryRecognizedKeyIsDocumented:
    def test_no_recognized_key_is_missing(self, generator, reference_text):
        expected = set(generator.KNOWN_CONFIG_KEYS) - generator.INTERNAL_KEYS
        missing = sorted(expected - _documented_keys(reference_text))
        assert not missing, (
            f"{len(missing)} recognized config key(s) are absent from a reference "
            f"that claims to be complete: {missing}. Add them to CATEGORY_ORDER in "
            f"the generator (the 'Other' catch-all should have caught these — if "
            f"they are still missing, the catch-all is broken). {REGENERATE}"
        )

    def test_reference_documents_no_unrecognized_key(self, generator, reference_text):
        """The reverse: a documented key the server does not recognize is a lie."""
        documented = _documented_keys(reference_text)
        known = set(generator.KNOWN_CONFIG_KEYS)
        # Annotation-type and label-structure tables use the same row shape, so
        # only consider names that look like config keys the generator emitted.
        categorized = {k for _, keys in generator.CATEGORY_ORDER for k in keys}
        extra = sorted((documented & categorized) - known)
        assert not extra, (
            f"CATEGORY_ORDER names key(s) the server does not recognize: {extra}. "
            f"A reader would configure them and be silently ignored."
        )

    def test_artifact_is_current(self, generator, reference_text):
        assert reference_text == generator.generate_reference(), (
            f"config_reference.md is stale. {REGENERATE}"
        )


class TestAnchorsMatchMkDocs:
    """
    The table of contents links to headings on the same page, so its anchors must
    match the ids MkDocs generates. An ad-hoc slugify that left punctuation in
    place produced `#qualitative-coding-(qda)` for a heading rendered as
    `qualitative-coding-qda` — a link that quietly did nothing.
    """

    @pytest.mark.parametrize("label,expected", [
        ("Qualitative Coding (QDA)", "qualitative-coding-qda"),
        ("Core / Required", "core-required"),
        ("UI & Layout", "ui-layout"),
        ("Agent Evaluation Suite", "agent-evaluation-suite"),
        ("Debug / Logging", "debug-logging"),
    ])
    def test_slugify_matches_python_markdown(self, generator, label, expected):
        assert generator.slugify(label) == expected

    def test_every_toc_anchor_resolves_to_a_heading(self, generator, reference_text):
        headings = {
            generator.slugify(line[3:].strip())
            for line in reference_text.splitlines()
            if line.startswith("## ")
        }
        toc_anchors = set(re.findall(r"^- \[[^\]]+\]\(#([^)]+)\)", reference_text, re.MULTILINE))
        dangling = sorted(toc_anchors - headings)
        assert not dangling, (
            f"Table-of-contents entries pointing at headings that do not exist: "
            f"{dangling}"
        )

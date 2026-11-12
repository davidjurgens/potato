"""Structural checks on the HuggingFace Spaces manifest.

These run offline. The live reconciliation — which manifest entries are actually
deployed and reachable — needs a HuggingFace token and lives in
``deployment/huggingface-spaces/audit_spaces.py``; run that with ``--check``.

Context: an audit found 23 of 64 manifest entries had never been deployed, one
had uploaded only two files, and the rest sat PAUSED, a state that (unlike
SLEEPING) does not wake for a visitor. Nothing compared the manifest to reality,
and the docs promised behaviour the catalog no longer had.
"""

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "deployment" / "huggingface-spaces" / "spaces_manifest.yaml"
DOCS_PAGE = REPO_ROOT / "docs" / "data-export" / "potato_on_huggingface.md"

sys.path.insert(0, str(MANIFEST_PATH.parent))


@pytest.fixture(scope="module")
def manifest():
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def entries(manifest):
    return manifest["spaces"]


@pytest.fixture(scope="module")
def defaults(manifest):
    return manifest.get("defaults", {}) or {}


def _featured(entries, defaults):
    return [e for e in entries if e.get("featured", defaults.get("featured", False))]


class TestManifestStructure:
    def test_every_entry_has_required_fields(self, entries):
        required = ("id", "source", "title", "summary", "category")
        for entry in entries:
            missing = [f for f in required if f not in entry]
            assert not missing, f"{entry.get('id', '?')} missing {missing}"

    def test_ids_are_unique(self, entries):
        ids = [e["id"] for e in entries]
        dupes = {i for i in ids if ids.count(i) > 1}
        assert not dupes, f"duplicate ids: {dupes}"

    def test_ids_are_kebab_case(self, entries):
        bad = [e["id"] for e in entries
               if not e["id"].replace("-", "").isalnum() or e["id"] != e["id"].lower()]
        assert not bad, f"non-kebab-case ids: {bad}"

    def test_every_source_project_exists(self, entries):
        """A manifest entry pointing at a deleted example builds an empty Space.

        This is how event-annotation reached HF with two files and no Dockerfile.
        """
        missing = []
        for entry in entries:
            config = REPO_ROOT / entry["source"] / "config.yaml"
            if not config.is_file():
                missing.append(f"{entry['id']} -> {entry['source']}/config.yaml")
        assert not missing, f"manifest entries with no runnable source: {missing}"


class TestFeaturedSet:
    def test_featured_count_fits_the_quota(self, entries, defaults):
        """HuggingFace allows 3 concurrent running Spaces on free CPU-basic.

        Three, not four. A fourth entry can look healthy while it happens to be
        SLEEPING, but sleeping is not a stable state: the next commit queues a
        rebuild, the rebuild asks for a slot, and the 403 leaves the Space
        PAUSED, which no visitor can wake. That is how ner-span went dark on
        2026-08-20 during a README-only push.
        """
        featured = _featured(entries, defaults)
        assert 1 <= len(featured) <= 3, (
            f"{len(featured)} featured Spaces; the cpu-basic quota is 3 concurrent. "
            "Raising this means the docs will promise demos that visitors cannot open."
        )

    def test_featured_spans_multiple_categories(self, entries, defaults):
        """The featured set is the shop window — it should not be three of a kind.

        Two is the floor rather than three because three slots and a
        traffic-led pick cannot cover much range: search demand concentrates so
        heavily in video that two of the three go there or to images. The live
        set currently demonstrates no text annotation at all, which the catalog
        page says in as many words.
        """
        featured = _featured(entries, defaults)
        categories = {e.get("category") for e in featured}
        assert len(categories) >= 2, (
            f"featured Spaces cover only {categories}; pick a spread of "
            "annotation types so the live set demonstrates range"
        )

    def test_featured_are_not_ai_dependent(self, entries, defaults):
        """needs_ai demos require an API key wired in as a Space secret.

        Featuring one without a key gives visitors a demo that looks broken.
        """
        featured = _featured(entries, defaults)
        ai_backed = [e["id"] for e in featured
                     if e.get("needs_ai", defaults.get("needs_ai", False))]
        assert not ai_backed, (
            f"featured Spaces needing an LLM key: {ai_backed}. Either wire the "
            "secret and drop this assertion, or feature a self-contained demo."
        )

    def test_featured_are_not_gated(self, entries, defaults):
        featured = _featured(entries, defaults)
        gated = [e["id"] for e in featured
                 if e.get("status", defaults.get("status", "ready")) != "ready"]
        assert not gated, f"featured but not ready: {gated}"


class TestDocsMatchManifest:
    @pytest.fixture(scope="class")
    def docs_text(self):
        return DOCS_PAGE.read_text(encoding="utf-8")

    def test_docs_do_not_promise_free_duplication(self, docs_text):
        """HF now requires PRO to create or duplicate a Docker Space.

        The page used to tell readers to click "Duplicate this Space" to run a
        copy on free hardware.
        """
        body = docs_text.lower()
        # The phrase may appear only inside the correction that explains it is gone.
        for marker in ("duplicate this space",):
            for line in docs_text.split("\n"):
                if marker in line.lower():
                    assert "no longer" in line.lower() or "requires pro" in line.lower(), (
                        f"docs still recommend duplication without noting it needs PRO: {line!r}"
                    )

    def test_docs_do_not_claim_paused_demos_wake_themselves(self, docs_text):
        assert "auto-waking" not in docs_text, (
            "the docs claimed paused demos wake when opened; only SLEEPING Spaces do"
        )

    def test_every_featured_id_is_named_in_the_docs(self, entries, defaults, docs_text):
        for entry in _featured(entries, defaults):
            assert entry["id"] in docs_text, (
                f"featured Space {entry['id']} is not mentioned in {DOCS_PAGE.name}"
            )

    def test_docs_category_counts_match_manifest(self, entries, docs_text):
        """The catalog headings carry counts, which silently went stale."""
        import re
        from collections import Counter

        actual = Counter(e.get("category", "other") for e in entries)
        titles = {
            "Text classification": "classification", "Span & structure": "span",
            "Agent & GenAI evaluation": "agent", "Multimodal": "multimodal",
            "Advanced workflows": "advanced", "AI-assisted": "ai-assisted",
            "Domain layouts": "custom", "Showcase": "showcase",
        }
        for heading, count in re.findall(r"^### (.+?) \((\d+)\)$", docs_text, re.M):
            category = titles.get(heading)
            if category is None:
                continue
            assert int(count) == actual[category], (
                f"docs say '{heading} ({count})' but the manifest has "
                f"{actual[category]} entries in '{category}'"
            )


class TestAuditToolImports:
    """The audit tool must at least load without a token."""

    def test_helpers_are_importable_and_pure(self):
        import audit_spaces

        entries, defaults = audit_spaces.load_manifest(MANIFEST_PATH)
        assert entries and isinstance(defaults, dict)
        assert "SLEEPING" in audit_spaces.HEALTHY_STAGES
        assert "PAUSED" not in audit_spaces.HEALTHY_STAGES, (
            "a paused Space does not serve visitors and must not count as healthy"
        )

    def test_problems_flags_unreachable_featured(self):
        import audit_spaces

        report = {"org": "x", "manifest_count": 2, "live_count": 1, "orphans": [], "rows": [
            {"id": "good", "featured": True, "deployed": True, "stage": "SLEEPING",
             "healthy": True, "error": None},
            {"id": "bad", "featured": True, "deployed": True, "stage": "PAUSED",
             "healthy": False, "error": None},
        ]}
        found = audit_spaces.problems(report)
        assert any("bad" in p for p in found)
        assert not any("good" in p for p in found)

    def test_problems_ignores_unfeatured_paused(self):
        import audit_spaces

        report = {"org": "x", "manifest_count": 1, "live_count": 1, "orphans": [], "rows": [
            {"id": "shelf", "featured": False, "deployed": True, "stage": "PAUSED",
             "healthy": False, "error": None},
        ]}
        assert audit_spaces.problems(report) == []

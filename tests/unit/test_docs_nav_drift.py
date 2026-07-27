"""
Drift guards for documentation discoverability.

MkDocs copies every file under `docs/` into the built site whether or not the
nav references it. A page missing from the nav is therefore not a 404 — it is
worse: it exists, it is indexed, and nothing on the site links to it. The only
way to reach it is to already know its URL.

This is not hypothetical. Thirty-four pages had drifted out of the nav,
including `configuration/config_reference.md` — the generated config reference
that `llms.txt` points at — plus the QDA, codebook, psychometrics, roles and
permissions, reverse-proxy, and scaling guides. Whole shipped features were
documented and unreachable, which is the same failure that made `audio_dialogue`
undiscoverable (see test_display_registry_docs_sync.py).

The generated `llms-full.txt` walks the nav to decide reading order, so an
off-nav page also lands in a degraded position there.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
MKDOCS_YML = REPO_ROOT / "mkdocs.yml"
LLMS_FULL = DOCS_DIR / "llms-full.txt"

# Directories under docs/ that hold assets rather than prose.
ASSET_DIRS = {"img", "stylesheets", "javascripts", "schemas"}


def _nav_entries(node, out):
    """Depth-first walk of the mkdocs nav, collecting referenced doc paths."""
    if isinstance(node, str):
        if node.endswith(".md"):
            out.append(node)
    elif isinstance(node, list):
        for item in node:
            _nav_entries(item, out)
    elif isinstance(node, dict):
        for value in node.values():
            _nav_entries(value, out)
    return out


@pytest.fixture(scope="module")
def nav_paths():
    config = yaml.safe_load(MKDOCS_YML.read_text(encoding="utf-8"))
    return _nav_entries(config.get("nav", []), [])


@pytest.fixture(scope="module")
def markdown_pages():
    pages = []
    for path in DOCS_DIR.rglob("*.md"):
        relative = path.relative_to(DOCS_DIR)
        if relative.parts[0] in ASSET_DIRS:
            continue
        pages.append(relative.as_posix())
    return sorted(pages)


class TestNavCoversEveryPage:
    def test_every_markdown_page_is_in_the_nav(self, nav_paths, markdown_pages):
        missing = sorted(set(markdown_pages) - set(nav_paths))
        assert not missing, (
            f"{len(missing)} documentation page(s) are not reachable from the site "
            f"navigation. They will still build and be indexed, but nothing links "
            f"to them:\n  " + "\n  ".join(missing)
        )

    def test_every_nav_entry_exists_on_disk(self, nav_paths):
        missing = sorted(
            entry for entry in nav_paths if not (DOCS_DIR / entry).exists()
        )
        assert not missing, (
            f"mkdocs.yml nav references file(s) that do not exist — the build "
            f"fails in strict mode:\n  " + "\n  ".join(missing)
        )

    def test_no_duplicate_nav_entries(self, nav_paths):
        duplicates = sorted({p for p in nav_paths if nav_paths.count(p) > 1})
        assert not duplicates, (
            f"Pages listed more than once in the nav: {duplicates}"
        )

    def test_there_are_pages_to_check(self, markdown_pages):
        """Guard against the glob matching nothing and vacuously passing."""
        assert len(markdown_pages) > 100


class TestGeneratedIndexes:
    """
    `llms.txt` is hand-curated; `llms-full.txt` is generated. Both are the entry
    point a coding agent is pointed at, so a stale or broken one is costly.
    """

    def test_llms_full_is_current(self):
        spec = pytest.importorskip("importlib.util")
        loader = spec.spec_from_file_location(
            "generate_llms_full", REPO_ROOT / "scripts" / "generate_llms_full.py"
        )
        module = spec.module_from_spec(loader)
        loader.loader.exec_module(module)

        assert LLMS_FULL.exists(), (
            "docs/llms-full.txt is missing. "
            "Regenerate with: python scripts/generate_llms_full.py"
        )
        assert LLMS_FULL.read_text(encoding="utf-8") == module.render(), (
            "docs/llms-full.txt is stale. "
            "Regenerate with: python scripts/generate_llms_full.py"
        )

    def test_llms_txt_links_resolve_to_real_pages(self):
        """
        Every readthedocs link in the curated index must correspond to a file that
        exists, so the index does not send an agent to a 404.
        """
        import re

        text = (DOCS_DIR / "llms.txt").read_text(encoding="utf-8")
        slugs = re.findall(
            r"https://potatoannotator\.readthedocs\.io/en/latest/([^)\s]*)", text
        )

        broken = []
        for slug in slugs:
            slug = slug.strip("/")
            if not slug:
                continue
            candidates = [
                DOCS_DIR / slug,                       # a literal file (llms.txt, *.json)
                DOCS_DIR / f"{slug}.md",
                DOCS_DIR / slug / "index.md",
            ]
            if not any(candidate.exists() for candidate in candidates):
                broken.append(slug)

        assert not broken, (
            f"llms.txt links to path(s) with no corresponding docs file: {broken}"
        )

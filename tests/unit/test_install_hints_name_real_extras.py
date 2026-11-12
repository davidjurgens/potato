"""Every `pip install <package>[extra]` Potato prints or documents must work.

Three did not: sam_endpoint and segmentation.md said `pip install
'potato[vision]'` (the package is potato-annotation, so that installs something
else), and the image-embedding trainer said `potato-annotation[embeddings]`, an
extra that does not exist. Release notes and the changelog describe old
versions and are left alone.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HINT = re.compile(r"pip install\s+(?:-U\s+|--upgrade\s+)?['\"]?([A-Za-z0-9_.-]+)\[([A-Za-z0-9_,\s-]+)\]")
SKIP = ("docs/releasenotes/", "docs/llms-full.txt", "CHANGELOG.md")


def declared_extras():
    block = re.search(r"extras_require=\{(.*?)\n    \},", (REPO / "setup.py").read_text(), re.S)
    return set(re.findall(r'^\s+"([a-z0-9-]+)":', block.group(1), re.M))


def hints():
    for path in list((REPO / "potato").rglob("*.py")) + list((REPO / "docs").rglob("*.md")) \
            + [REPO / "README.md"]:
        rel = str(path.relative_to(REPO))
        if rel.startswith(SKIP) or rel in SKIP:
            continue
        for match in HINT.finditer(path.read_text(errors="ignore")):
            yield rel, match.group(1), [e.strip() for e in match.group(2).split(",")]


def test_hints_name_the_real_package_and_real_extras():
    extras = declared_extras()
    assert {"ai", "vision", "mysql", "auth"} <= extras, extras
    bad = []
    for rel, package, wanted in hints():
        # Other projects' extras (imageio[openexr]) are theirs to name.
        if not package.startswith("potato"):
            continue
        if package != "potato-annotation":
            bad.append(f"{rel}: package {package!r}")
        bad += [f"{rel}: no extra {e!r}" for e in wanted if e not in extras]
    assert not bad, bad


def test_the_scan_finds_hints():
    """Guard the guard: an empty scan would pass vacuously."""
    assert sum(1 for _, package, _ in hints() if package.startswith("potato")) > 10
